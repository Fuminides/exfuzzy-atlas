"""Per-class decision calibration and dominance-score recomputation for winning-rule classifiers (AT-041e).

Why. The dominance score of a rule is ``confidence x support`` computed by ex_fuzzy on the rows the GA was fitted on
(``evalRuleBase.add_rule_weights``). Both factors carry the class mix of that sample: with a class-tempered
subsample the rare classes are still under-represented, so a rule of a rare class that fires with strength 1.0 can
lose to a rule of a frequent class that fires weakly. Two cheap levers leave the rules (antecedents, classes)
untouched:

* ``rescore``: recompute the scores with the library's own ``evalRuleBase`` on other rows (all training rows, i.e.
  the natural class prior). Nothing numeric is reimplemented here.
* ``tune_class_factors`` / ``apply_class_factors``: one multiplicative factor per class on the association degree,
  tuned on validation rows to maximise macro-F1. Because the association is ``firing x weight``, the factor of a class
  is folded into the weight of each of its rules, so ``association = firing x weight`` (the contract's trace parity)
  still holds; the score before the factor is kept on the rule as ``score_raw`` (exported as the metric
  ``dominance_score_raw``).

A factor is a decision threshold, not a probability correction: firing, weight and association stay degrees of
rule match.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Sequence

import numpy as np
import pandas as pd
from ex_fuzzy import eval_rules

from atlas.explain.classifier import compute_classifier_activations, get_master_rulebase, rule_classes
from atlas.ml.classification import classification_metrics

DEFAULT_GRID_LOG10 = (-2.0, 3.0, 41)  # factors from 0.01 to 1000, ~x1.33 per step


# --------------------------------------------------------------------------------------------- recompute scores


def rescore(model, X: np.ndarray, y: np.ndarray):
    """A deep copy of ``model`` whose dominance scores are recomputed by ex_fuzzy on the rows ``X`` / ``y``.

    ``y`` holds class indexes in the order of the rule bases. ``score_raw`` of each rule is set to the new score.
    """
    out = copy.deepcopy(model)
    rb = get_master_rulebase(out)
    eval_rules.evalRuleBase(rb, np.asarray(X, dtype=float), np.asarray(y, dtype=int)).add_rule_weights()
    for rule in rb.get_rules():
        rule.score_raw = float(rule.score)
        rule.class_factor = 1.0
    return out


# ------------------------------------------------------------------------------------------ class association


def class_max_association(model, X: np.ndarray, n_classes: int, chunk: int = 200_000) -> np.ndarray:
    """``(n_rows, n_classes)``: the largest association degree among the rules of each class (0 without rules).

    The winner of the library is the rule with the largest association; its class is the argmax of this matrix, and a
    row with an all-zero line is *unknown*. Scaling a class by a factor scales its column.
    """
    rb = get_master_rulebase(model)
    classes = np.asarray(rule_classes(rb), dtype=int)
    X = np.asarray(X, dtype=float)
    out = np.zeros((len(X), n_classes))
    for start in range(0, len(X), chunk):
        assoc = compute_classifier_activations(rb, X[start:start + chunk]).association
        for c in range(n_classes):
            cols = classes == c
            if cols.any():
                out[start:start + chunk, c] = assoc[:, cols].max(axis=1)
    return out


def predict_with_factors(assoc: np.ndarray, factors: Sequence[float]) -> np.ndarray:
    """Class index per row from the class-association matrix and the class factors; ``-1`` where nothing fires."""
    scaled = assoc * np.asarray(factors, dtype=float)[None, :]
    pred = scaled.argmax(axis=1)
    return np.where(scaled.max(axis=1) > 0.0, pred, -1)


# -------------------------------------------------------------------------------------------------- tuning


def coordinate_ascent(score: Callable[[np.ndarray], float], n_params: int, *, anchor: int | None = 0,
                      grid_log10: tuple[float, float, int] = DEFAULT_GRID_LOG10, sweeps: int = 3) -> np.ndarray:
    """Maximise ``score(factors)`` over positive factors by coordinate ascent on a log grid.

    ``anchor`` is held at 1 (the scale is irrelevant for an argmax). Ties between grid values go to the one closest to 1
    (so a flat score leaves the factor alone). Stops when a sweep changes nothing.
    """
    grid = 10.0 ** np.linspace(*grid_log10)
    f = np.ones(n_params)
    for _ in range(sweeps):
        changed = False
        for k in range(n_params):
            if k == anchor:
                continue
            candidates = []
            for g in grid:
                trial = f.copy()
                trial[k] = g
                candidates.append((score(trial), abs(np.log10(g)), g))
            top = max(c[0] for c in candidates)
            g_best = min((c for c in candidates if c[0] >= top - 1e-12), key=lambda c: c[1])[2]
            changed |= not np.isclose(g_best, f[k])
            f[k] = g_best
        if not changed:
            break
    return f


def tune_class_factors(assoc: np.ndarray, y: np.ndarray, *, anchor: int = 0,
                       grid_log10: tuple[float, float, int] = DEFAULT_GRID_LOG10, sweeps: int = 3) -> np.ndarray:
    """Factors per class (class ``anchor`` fixed at 1) maximising the macro-F1 of ``predict_with_factors``."""
    k = assoc.shape[1]
    y = np.asarray(y, dtype=int)

    def score(f: np.ndarray) -> float:
        return classification_metrics(y, predict_with_factors(assoc, f), k)["macro_f1"]

    return coordinate_ascent(score, k, anchor=anchor, grid_log10=grid_log10, sweeps=sweeps)


def cross_fit_predictions(assoc: np.ndarray, y: np.ndarray, groups: np.ndarray, **kwargs) -> np.ndarray:
    """Predictions where the rows of each group get the factors tuned on all the *other* groups.

    Estimates what the tuning would score on rows it did not see: the figure to compare an in-sample tuned model
    with an untuned one.
    """
    pred = np.empty(len(y), dtype=int)
    for g in np.unique(groups):
        held = groups == g
        factors = tune_class_factors(assoc[~held], np.asarray(y)[~held], **kwargs)
        pred[held] = predict_with_factors(assoc[held], factors)
    return pred


def week_parity(issued_at_utc) -> np.ndarray:
    """0/1 by ISO-week parity of the issue time: two interleaved halves of the year for ``cross_fit_predictions``."""
    return np.asarray(pd.DatetimeIndex(issued_at_utc).isocalendar().week.to_numpy() % 2, dtype=int)


# ------------------------------------------------------------------------------------------ apply to a model


def apply_class_factors(model, factors: Sequence[float]):
    """A deep copy of ``model`` whose rule weights are ``score_raw x factor[class]``.

    Sets ``rule.score`` (what ex_fuzzy multiplies the firing with, ``ds_mode`` 0), ``rule.score_raw`` (the score before
    this call, kept if already set by ``rescore``) and ``rule.class_factor``.
    """
    out = copy.deepcopy(model)
    rb = get_master_rulebase(out)
    if rb.ds_mode != 0:
        raise ValueError("class factors are folded into the dominance score: ds_mode must be 0")
    factors = np.asarray(factors, dtype=float)
    for rule, cls in zip(rb.get_rules(), rule_classes(rb), strict=True):
        raw = float(getattr(rule, "score_raw", rule.score))
        rule.score_raw, rule.class_factor, rule.score = raw, float(factors[cls]), raw * float(factors[cls])
    return out


def rule_metric_columns(model) -> dict[str, list[float]]:
    """Per-rule values for ``RuleDefinition.metrics``: ``dominance_score_raw``, ``class_factor`` and, when present,
    ``selection_frequency`` (rules in rule order). Empty when the model carries none of them."""
    rb = get_master_rulebase(model)
    rules = rb.get_rules()
    out: dict[str, list[float]] = {}
    if rules and all(hasattr(r, "score_raw") for r in rules):
        out["dominance_score_raw"] = [float(r.score_raw) for r in rules]
        out["class_factor"] = [float(r.class_factor) for r in rules]
    if rules and all(hasattr(r, "selection_frequency") for r in rules):
        out["selection_frequency"] = [float(r.selection_frequency) for r in rules]
    return out
