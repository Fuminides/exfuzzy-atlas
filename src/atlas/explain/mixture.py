"""Exact rule activations of a fitted ex_fuzzy mixture-of-rules classifier (contract v0.7, ``inference='mixture'``).

The score of class ``c`` for a row is ``b_c + sum_r W[r, c] * firing_r`` and the prediction is the first class of
largest score (ex_fuzzy PR 44, ``docs/ml/rule_mixture.md``). Every number comes from ex_fuzzy's public API: the
antecedent memberships (``rules.compute_antecedents_memberships``), the firing (``rule_mixture.rule_firing``), the
scores (``mixture_scores``), the per-rule contributions ``W[r, c] * firing_r`` (``mixture_contributions``) and the
class (``predict``). The weights are the fitted ``mixture_`` (``coef_`` W, ``intercept_`` b).

Two things are derived here, from those numbers only:

* **Centred weights** ``W[r, c] - mean_c W[r, c]``. Adding a constant to all the weights of one rule changes no score
  difference, so non-negative and unconstrained fits describe the same family of models; in the centred form a rule
  visibly *supports* some classes (> 0) and *suppresses* others (< 0) relative to the rest, whichever penalty was used.
  Suppression is not "evidence against" a class and nothing here is a probability.
* **Top rule** of a prediction: the rule with the largest positive centred contribution ``centred[r, c] * firing_r``
  to the predicted class ``c`` (first in rule order on exact ties), and its share of the positive centred
  contributions to that class. It is the rule that supports the prediction the most; it did not decide it alone.
* **Decisive rules** of a prediction: those whose removal (all their weights set to 0, the scores recomputed by
  ex_fuzzy's ``RuleMixture.predict`` with that rule's row of ``coef_`` zeroed) would change the predicted class.

Rules are in the library's flat order (``get_rules()``), so column ``r`` of every array is rule ``R(r+1)``, as in
``atlas.explain.classifier``.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import timedelta

import numpy as np
import pandas as pd

from atlas.contracts import models as m
from atlas.explain.classifier import duplicate_groups, feature_names, get_master_rulebase, rule_ids, tnorm_of
from atlas.explain.engine import UnsupportedModelError, rule_modifier, trace_antecedents
from atlas.explain.traces import _as_utc_datetimes, _check_lengths


def get_estimator(model):
    """The ex_fuzzy ``BaseFuzzyRulesClassifier`` of a fitted model (the Atlas ``FuzzyClassifier`` wrapper or itself)."""
    estimator = getattr(model, "estimator", model)
    if not hasattr(estimator, "rule_base"):
        raise UnsupportedModelError(f"expected a fitted ex_fuzzy classifier, got {type(model)!r}")
    return estimator


def is_mixture(model) -> bool:
    """True for a classifier whose inference is the mixture of rules (``inference='mixture'``)."""
    try:
        return getattr(get_estimator(model), "inference", "winning_rule") == "mixture"
    except UnsupportedModelError:
        return False


def fitted_mixture(model):
    """The fitted ``rule_mixture.RuleMixture`` (``mixture_``), checked against the model's current rules."""
    from ex_fuzzy import rule_mixture

    estimator = get_estimator(model)
    if not is_mixture(model):
        raise UnsupportedModelError("the model does not use inference='mixture'")
    mixture = getattr(estimator, "mixture_", None)
    if mixture is None:
        raise UnsupportedModelError("the mixture weights are not fitted (mixture_ is None)")
    if mixture.rule_keys_ is not None and mixture.rule_keys_ != rule_mixture.rule_keys(estimator.rule_base):
        raise UnsupportedModelError("the rules changed after the mixture weights were fitted")
    return mixture


def check_supported(model) -> None:
    from ex_fuzzy import fuzzy_sets as fs

    rb = get_master_rulebase(model)
    mixture = fitted_mixture(model)
    if rb.fuzzy_type() != fs.FUZZY_SETS.t1:
        raise UnsupportedModelError("only type-1 classifiers are supported")
    if not rb.get_rules():
        raise UnsupportedModelError("the rule base has no rules")
    for rule in rb.get_rules():
        if any(rule_modifier(rule, f) is not None for f in range(len(rule.antecedents))):
            raise UnsupportedModelError("rule modifiers (hedges) are not supported for classifiers")
    n_classes = mixture.coef_.shape[1]
    classes = getattr(get_estimator(model), "classes_", None)
    if classes is not None and not np.array_equal(np.asarray(classes), np.arange(n_classes)):
        # predict() returns fitted labels; the Atlas wrapper fits class indexes, so labels and indexes coincide
        raise UnsupportedModelError(f"the classifier was fitted with labels {list(classes)}, not class indexes")


def centred_weights(coef: np.ndarray) -> np.ndarray:
    """``W[r, c] - mean_c W[r, c]``: the same decision function, with each rule's support (+) and suppression (-)."""
    coef = np.asarray(coef, dtype=float)
    return coef - coef.mean(axis=1, keepdims=True)


def strongest_class(weights: Sequence[float]) -> int | None:
    """Index of the first largest weight; None when all are equal (the rule changes no prediction)."""
    values = list(weights)
    return None if max(values) == min(values) else values.index(max(values))


def inference_spec(model) -> m.InferenceSpec:
    """Mixture-of-rules description read from the fitted classifier."""
    from atlas.ml.exfuzzy_features import exfuzzy_version  # atlas.ml imports atlas.explain: import at call time

    check_supported(model)
    rb, estimator = get_master_rulebase(model), get_estimator(model)
    mixture = fitted_mixture(model)
    allow_unknown = bool(rb.allow_unknown)
    return m.InferenceSpec(
        family=m.InferenceFamily.RULE_MIXTURE_CLASSIFIER, tnorm=tnorm_of(rb), rule_mode=None, tolerance=0.0,
        fallback="unknown" if allow_unknown else "largest_bias", rule_weighting=None, allow_unknown=allow_unknown,
        mixture_weights="non_negative" if mixture.non_negative else "unconstrained",
        mixture_C=float(getattr(estimator, "mixture_C", mixture.C)), exfuzzy_version=exfuzzy_version(),
    )


def top_rules(support: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per row of ``support`` (rows x rules, the centred contributions to the predicted class): the top rule's
    position (-1 when no contribution is positive) and its share of the positive contributions (NaN without one).

    The same definition as ``atlas.contracts.models.top_contributor``: the first rule of largest positive value."""
    support = np.asarray(support, dtype=float)
    if support.shape[1] == 0:
        return np.full(support.shape[0], -1), np.full(support.shape[0], np.nan)
    best = support.max(axis=1)
    top = np.where(best > 0, support.argmax(axis=1), -1)
    positive = np.where(support > 0, support, 0.0).sum(axis=1)
    share = np.where(best > 0, best / np.where(positive > 0, positive, 1.0), np.nan)
    return top, share


@dataclass(frozen=True)
class MixtureActivations:
    """Row i of each array is input row i (finite inputs only); classes are in consequent order."""

    memberships: list  # per feature: terms x rows, from ex_fuzzy
    firing: np.ndarray  # (rows, rules) t-norm output (rule_mixture.rule_firing)
    weights: np.ndarray  # (rules, classes) W, as fitted
    centred: np.ndarray  # (rules, classes) W - mean over the classes
    bias: np.ndarray  # (classes,) b
    scores: np.ndarray  # (rows, classes) ex_fuzzy mixture_scores
    contributions: np.ndarray  # (rows, rules, classes) ex_fuzzy mixture_contributions
    prediction: np.ndarray  # (rows,) class index from ex_fuzzy predict, -1 = no rule fired (allow_unknown)
    support: np.ndarray  # (rows, rules) centred contribution to the predicted class (0 where there is none)
    top: np.ndarray  # (rows,) top rule position, -1 = none
    top_share: np.ndarray  # (rows,) NaN without a top rule
    decisive: np.ndarray  # (rows, rules) bool: zeroing the rule's weights changes the predicted class


def compute_mixture_activations(model, X: np.ndarray, *, with_decisive: bool = True) -> MixtureActivations:
    """Run ex_fuzzy on ``X`` (finite, columns in antecedent order)."""
    from ex_fuzzy import rule_mixture
    from ex_fuzzy import rules as fz_rules

    check_supported(model)
    rb, estimator, mixture = get_master_rulebase(model), get_estimator(model), fitted_mixture(model)
    X = np.asarray(X, dtype=float)
    memberships = fz_rules.compute_antecedents_memberships(rb.antecedents, X)
    firing = rule_mixture.rule_firing(rb, X)
    scores = np.asarray(estimator.mixture_scores(X), dtype=float)
    contributions = np.asarray(estimator.mixture_contributions(X), dtype=float)
    prediction = np.asarray(estimator.predict(X), dtype=int)
    weights = np.asarray(mixture.coef_, dtype=float)
    centred = centred_weights(weights)
    if not np.array_equal(mixture.predict(firing, allow_unknown=bool(rb.allow_unknown)), prediction):
        raise AssertionError("ex_fuzzy predict and the mixture of the rule firing disagree")
    answered = prediction >= 0
    support = np.zeros(firing.shape)
    support[answered] = firing[answered] * centred[:, prediction[answered]].T
    top, share = top_rules(support)
    top[~answered], share[~answered] = -1, np.nan
    decisive = np.zeros(firing.shape, dtype=bool)
    if with_decisive and answered.any():
        for r in range(weights.shape[0]):
            without = copy.copy(mixture)  # the library's own scoring, with this rule's weights removed
            without.coef_ = weights.copy()
            without.coef_[r] = 0.0
            changed = without.predict(firing, allow_unknown=bool(rb.allow_unknown)) != prediction
            decisive[:, r] = changed & answered
    return MixtureActivations(
        memberships=memberships, firing=firing, weights=weights, centred=centred,
        bias=np.asarray(mixture.intercept_, dtype=float), scores=scores, contributions=contributions,
        prediction=prediction, support=support, top=top, top_share=share, decisive=decisive,
    )


def mixture_top_rules(model, X: pd.DataFrame, chunk_size: int = 100_000) -> tuple[np.ndarray, np.ndarray]:
    """Top rule position (-1 = none) and share (NaN) for every row of ``X``; rows with a missing input get none."""
    names = feature_names(get_master_rulebase(model))
    values = X[names].to_numpy(dtype=float)
    top, share = np.full(len(values), -1), np.full(len(values), np.nan)
    finite = np.flatnonzero(np.isfinite(values).all(axis=1))
    for start in range(0, len(finite), chunk_size):
        part = finite[start:start + chunk_size]
        act = compute_mixture_activations(model, values[part], with_decisive=False)
        top[part], share[part] = act.top, act.top_share
    return top, share


def _labels(order: Sequence[str], values) -> dict[str, float]:
    return {label: float(v) for label, v in zip(order, values, strict=True)}


def build_mixture_traces(
    model,
    X: pd.DataFrame,
    entity_ids: Sequence[str],
    issued_at_utc: Sequence,
    *,
    class_labels: Sequence[str],
    model_id: str,
    task_id: str,
    horizon_hours: int,
    target_unit: str,
    data_version: str,
    synthetic: bool = False,
    feature_units: dict[str, str] | None = None,
) -> list[m.RuleTrace]:
    """One ``RuleTrace`` per row of ``X`` for a mixture-of-rules classifier (contract v0.7).

    Each rule carries its firing, its class weights and its contributions to every class score (as fitted and
    centred); the prediction carries ex_fuzzy's class scores, the biases, the class and the top rule. A row that fires
    no rule has scores equal to the biases and, with ``allow_unknown``, no class (``prediction_unavailable``); a row
    with a non-finite input is not sent to ex_fuzzy (no rules, ``missing_input``). ``winning_rule_id`` is always null:
    no single rule decides. Nothing here is a probability; the softmax of the scores is not served.
    """
    rb = get_master_rulebase(model)
    spec = inference_spec(model)
    names = feature_names(rb)
    if absent := [n for n in names if n not in X.columns]:
        raise KeyError(f"X is missing model features: {absent}")
    values = X[names].to_numpy(dtype=float)
    _check_lengths(values.shape[0], entity_ids, issued_at_utc)
    issued = _as_utc_datetimes(issued_at_utc)
    ids = rule_ids(rb)
    order = list(class_labels)
    units = {n: getattr(v, "units", None) for n, v in zip(names, rb.antecedents, strict=True)}
    units.update(feature_units or {})
    finite = np.isfinite(values).all(axis=1)
    index = np.full(values.shape[0], -1, dtype=int)
    index[finite] = np.arange(int(finite.sum()))
    act = compute_mixture_activations(model, values[finite], with_decisive=False) if finite.any() else None
    if act is not None and act.weights.shape[1] != len(order):
        raise ValueError(f"{act.weights.shape[1]} mixture classes but {len(order)} class labels")
    rules = rb.get_rules()

    traces = []
    for row in range(values.shape[0]):
        feature_values = []
        for f, name in enumerate(names):
            value = values[row, f]
            ok = bool(np.isfinite(value))
            reason = None if ok else (
                m.MissingReason.NO_OBSERVATION if np.isnan(value) else m.MissingReason.INVALID_OBSERVATION)
            feature_values.append(m.FeatureValue(
                feature=name, value=float(value) if ok else None, unit=units[name], missing_reason=reason))
        common = dict(
            data_version=data_version, synthetic=synthetic, model_id=model_id, task_id=task_id,
            entity_id=str(entity_ids[row]), issued_at_utc=issued[row],
            valid_at_utc=issued[row] + timedelta(hours=horizon_hours), inference=spec, feature_values=feature_values,
        )
        if not finite[row]:
            missing = [fv.feature for fv in feature_values if fv.value is None]
            traces.append(m.RuleTrace(
                **common, rules=[],
                prediction=m.TracePrediction(value=None, unit=target_unit, fallback_used=False,
                                             missing_reason=m.MissingReason.MISSING_INPUT),
                quality=m.Quality(status=m.QualityStatus.WARNING, warnings=["missing input: " + ", ".join(missing)]),
            ))
            continue
        k = index[row]
        entries = []
        for r, rule_id in enumerate(ids):
            antecedents = trace_antecedents(rules[r], rb.antecedents, names, act.memberships, k)
            firing = float(act.firing[k, r])
            entries.append(m.RuleTraceEntry(
                rule_id=rule_id, antecedents=antecedents, firing_strength=firing, effective_firing=firing,
                class_weights=_labels(order, act.weights[r]),
                class_contributions=_labels(order, act.contributions[k, r]),
                class_contributions_centred=_labels(order, act.firing[k, r] * act.centred[r]),
            ))
        cls = int(act.prediction[k])
        fired = bool(np.any(act.firing[k] > 0))
        scores = dict(class_scores=_labels(order, act.scores[k]), class_bias=_labels(order, act.bias))
        if cls < 0:
            prediction = m.TracePrediction(value=None, unit=target_unit, fallback_used=True,
                                           missing_reason=m.MissingReason.PREDICTION_UNAVAILABLE, **scores)
        else:
            top = int(act.top[k])
            prediction = m.TracePrediction(
                value=None, label=order[cls], unit=target_unit, fallback_used=not fired,
                top_rule_id=ids[top] if top >= 0 else None,
                top_rule_share=float(act.top_share[k]) if top >= 0 else None, **scores)
        traces.append(m.RuleTrace(**common, rules=entries, prediction=prediction))
    return traces


def iter_mixture_firing_tables(
    model, X: pd.DataFrame, entity_ids: Sequence[str], issued_at_utc: Sequence, *, chunk_size: int = 100_000,
) -> Iterator[pd.DataFrame]:
    """Tidy firing tables, ``chunk_size`` rows at a time: one record per row and rule.

    Columns: ``entity_id``, ``issued_at_utc``, ``rule_id``, ``firing_strength``, ``centred_contribution`` (the rule's
    centred contribution to the predicted class: > 0 supports it, < 0 suppresses it; NaN without a prediction),
    ``is_decisive`` (zeroing the rule's weights changes the predicted class) and ``missing_reason``. A row with a
    non-finite input has NaN numbers and ``missing_reason="missing_input"``.
    """
    if chunk_size < 1:
        raise ValueError("chunk_size must be >= 1")
    rb = get_master_rulebase(model)
    check_supported(model)
    names = feature_names(rb)
    values = X[names].to_numpy(dtype=float)
    _check_lengths(values.shape[0], entity_ids, issued_at_utc)
    stamps = pd.DatetimeIndex(issued_at_utc)
    if stamps.tz is None:
        raise ValueError("issued_at_utc must be timezone-aware (UTC)")
    stamps = stamps.tz_convert("UTC")
    entities = pd.Categorical(np.asarray(entity_ids, dtype=object))
    ids = rule_ids(rb)
    n_rules = len(ids)
    rule_cat = pd.Categorical.from_codes(np.arange(n_rules), categories=ids)
    for start in range(0, values.shape[0], chunk_size):
        stop = min(start + chunk_size, values.shape[0])
        chunk = values[start:stop]
        finite = np.isfinite(chunk).all(axis=1)
        firing = np.full((stop - start, n_rules), np.nan)
        support = np.full((stop - start, n_rules), np.nan)
        decisive = np.zeros((stop - start, n_rules), dtype=bool)
        if finite.any():
            act = compute_mixture_activations(model, chunk[finite])
            firing[finite] = act.firing
            support[finite] = np.where((act.prediction >= 0)[:, None], act.support, np.nan)
            decisive[finite] = act.decisive
        reason = np.where(finite, None, m.MissingReason.MISSING_INPUT.value).repeat(n_rules)
        yield pd.DataFrame({
            "entity_id": pd.Categorical.from_codes(np.repeat(entities.codes[start:stop], n_rules), entities.categories),
            "issued_at_utc": stamps[start:stop].repeat(n_rules),
            "rule_id": pd.Categorical.from_codes(np.tile(np.arange(n_rules), stop - start), dtype=rule_cat.dtype),
            "firing_strength": firing.ravel(),
            "centred_contribution": support.ravel(),
            "is_decisive": decisive.ravel(),
            "missing_reason": pd.Categorical(reason, categories=[m.MissingReason.MISSING_INPUT.value]),
        })


__all__ = [
    "MixtureActivations", "build_mixture_traces", "centred_weights", "check_supported", "compute_mixture_activations",
    "duplicate_groups", "fitted_mixture", "get_estimator", "inference_spec", "is_mixture", "iter_mixture_firing_tables",
    "mixture_top_rules", "strongest_class", "top_rules",
]
