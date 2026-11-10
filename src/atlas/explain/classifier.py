"""Exact rule activations of a fitted ex_fuzzy winning-rule classifier (AT-041c).

Everything numeric comes from ex_fuzzy's public methods: antecedent memberships
(``rules.compute_antecedents_memberships``), the t-norm firing (``MasterRuleBase.compute_firing_strengths``), the
association degree (``compute_association_degrees``: firing x dominance score / weight / 1 according to
``ds_mode``), and the winning rule and class (``explainable_predict``). Nothing here recomputes a membership or a
t-norm. Rules are indexed by their position in the library's flat list (``get_rules()``: all rules of class 0, then
class 1, ...), so column ``r`` of every array is rule ``R(r+1)``.

``rule_weights`` makes explicit what multiplies the firing: ``ds_mode`` 0 reads ``get_scores()`` (the dominance
score, computed once on the fitting rows), 1 is all ones, 2 reads ``get_weights()``.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import timedelta

import numpy as np
import pandas as pd
from ex_fuzzy import rules as fz_rules
from ex_fuzzy.rules import MasterRuleBase

from atlas.contracts import models as m
from atlas.explain.engine import UnsupportedModelError, rule_modifier
from atlas.explain.traces import _as_utc_datetimes, _check_lengths


def get_master_rulebase(model) -> MasterRuleBase:
    """The ``MasterRuleBase`` of a fitted classifier, wrapper (``.rule_base``) or rule base."""
    if isinstance(model, MasterRuleBase):
        return model
    rb = getattr(model, "rule_base", None)
    if isinstance(rb, MasterRuleBase):
        return rb
    raise UnsupportedModelError(f"expected a fitted BaseFuzzyRulesClassifier or MasterRuleBase, got {type(model)!r}")


def check_supported(rb: MasterRuleBase) -> None:
    from ex_fuzzy import fuzzy_sets as fs

    if rb.fuzzy_type() != fs.FUZZY_SETS.t1:
        raise UnsupportedModelError("only type-1 classifiers are supported")
    if not rb.allow_unknown:
        # ex_fuzzy then answers the class of rule 0 when nothing fires: a winner with association 0.
        raise UnsupportedModelError("allow_unknown=False cannot be described: no rule would win a row nothing fires on")
    for rule in rb.get_rules():
        for f in range(len(rule.antecedents)):
            if rule_modifier(rule, f) is not None:
                raise UnsupportedModelError("rule modifiers (hedges) are not supported for classifiers")


def feature_names(rb: MasterRuleBase) -> list[str]:
    return [str(v.name) for v in rb.antecedents]


def rule_ids(rb: MasterRuleBase) -> list[str]:
    n = len(rb.get_rules())
    width = max(2, len(str(n)))
    return [f"R{p + 1:0{width}d}" for p in range(n)]


def rule_classes(rb: MasterRuleBase) -> list[int]:
    """Class index of each rule, in rule order."""
    return [int(c) for c in rb.get_consequents()]


def rule_weights(rb: MasterRuleBase) -> np.ndarray:
    """Factor that multiplies the firing in the association degree, per rule."""
    n = len(rb.get_rules())
    if rb.ds_mode == 0:
        return np.asarray(rb.get_scores(), dtype=float)
    if rb.ds_mode == 1:
        return np.ones(n)
    return np.asarray(rb.get_weights(), dtype=float)


def rule_weighting_name(rb: MasterRuleBase) -> str:
    return {0: "dominance_score", 1: "none", 2: "weight"}[int(rb.ds_mode)]


@dataclass(frozen=True)
class ClassifierActivations:
    """Row i of each array is input row i (finite inputs only)."""

    memberships: list  # per feature: terms x rows, from ex_fuzzy
    firing: np.ndarray  # (n_rows, n_rules) t-norm output
    weights: np.ndarray  # (n_rules,)
    association: np.ndarray  # (n_rows, n_rules) = firing x weights, from ex_fuzzy
    winner: np.ndarray  # (n_rows,) rule position of the winning rule, -1 when nothing fired and allow_unknown
    prediction: np.ndarray  # (n_rows,) class index of the winning rule, -1 = unknown


def refuse_mixture(model) -> None:
    """The winning-rule description would be wrong for a mixture of rules (v0.7): use ``atlas.explain.mixture``."""
    if getattr(getattr(model, "estimator", model), "inference", "winning_rule") == "mixture":
        raise UnsupportedModelError("this classifier uses inference='mixture': no rule wins alone; use "
                                    "atlas.explain.mixture (build_mixture_traces, iter_mixture_firing_tables)")


def compute_classifier_activations(model, X: np.ndarray) -> ClassifierActivations:
    """Run ex_fuzzy on ``X`` (finite, columns in antecedent order)."""
    refuse_mixture(model)
    rb = get_master_rulebase(model)
    X = np.asarray(X, dtype=float)
    if not rb.get_rules():
        raise UnsupportedModelError("the rule base has no rules")
    memberships = fz_rules.compute_antecedents_memberships(rb.antecedents, X)
    firing = rb.compute_firing_strengths(X, precomputed_truth=memberships)
    association = rb.compute_association_degrees(X, precomputed_truth=memberships, firing_strengths=firing)
    explained = rb.explainable_predict(X, precomputed_truth=memberships)
    return ClassifierActivations(
        memberships=memberships, firing=firing, weights=rule_weights(rb), association=association,
        winner=np.asarray(explained.winning_rule, dtype=int), prediction=np.asarray(explained.prediction, dtype=int),
    )


def tnorm_of(rb: MasterRuleBase) -> m.TNorm:
    tnorms = {rule_base.tnorm for rule_base in rb.rule_bases}
    if tnorms == {np.prod}:
        return m.TNorm.PRODUCT
    if tnorms <= {np.min, np.amin}:
        return m.TNorm.MINIMUM
    raise UnsupportedModelError(f"t-norm(s) {tnorms!r} have no equivalent in the TNorm contract enum")


def inference_spec(rb: MasterRuleBase) -> m.InferenceSpec:
    """Winning-rule classifier description read from the fitted rule base."""
    from atlas.ml.exfuzzy_features import exfuzzy_version  # atlas.ml imports atlas.explain: import at call time

    check_supported(rb)
    return m.InferenceSpec(
        family=m.InferenceFamily.WINNING_RULE_CLASSIFIER, tnorm=tnorm_of(rb), rule_mode=None, tolerance=0.0,
        fallback="unknown", rule_weighting=rule_weighting_name(rb), allow_unknown=bool(rb.allow_unknown),
        exfuzzy_version=exfuzzy_version(),
    )


def duplicate_groups(rb: MasterRuleBase) -> list[list[int]]:
    """Groups (positions, ascending) of rules with identical antecedents, whatever their class."""
    groups: dict[tuple, list[int]] = {}
    for position, rule in enumerate(rb.get_rules()):
        groups.setdefault(tuple(int(t) for t in rule.antecedents), []).append(position)
    return [g for g in groups.values() if len(g) > 1]


def _trace_entry(rb, act: ClassifierActivations, r: int, rule_id: str, k: int, names, term_names):
    rule = rb.get_rules()[r]
    antecedents = []
    for f, term in enumerate(rule.antecedents):
        if term < 0:
            continue
        membership = float(act.memberships[f][term][k])
        antecedents.append(m.AntecedentTrace(
            feature=names[f], term=term_names[f][term], membership=membership, modifier=None,
            effective_membership=membership,
        ))
    firing = float(act.firing[k, r])
    return m.RuleTraceEntry(
        rule_id=rule_id, antecedents=antecedents, firing_strength=firing, effective_firing=firing,
        weight=float(act.weights[r]), association_degree=float(act.association[k, r]),
    )


def build_classifier_traces(
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
    """One ``RuleTrace`` per row of ``X`` for a winning-rule classifier.

    Firing, association degree, winning rule and class are ex_fuzzy's own numbers. A row nothing fires on has
    ``label=None`` and ``missing_reason="prediction_unavailable"``; a row with a non-finite input is not sent to
    ex_fuzzy (no rules, ``missing_reason="missing_input"``). The firing is a degree of rule match and the
    association degree is firing x weight; neither is a probability or a risk.
    """
    refuse_mixture(model)
    rb = get_master_rulebase(model)
    spec = inference_spec(rb)
    names = feature_names(rb)
    absent = [n for n in names if n not in X.columns]
    if absent:
        raise KeyError(f"X is missing model features: {absent}")
    values = X[names].to_numpy(dtype=float)
    _check_lengths(values.shape[0], entity_ids, issued_at_utc)
    issued = _as_utc_datetimes(issued_at_utc)
    ids = rule_ids(rb)
    units = {n: getattr(v, "units", None) for n, v in zip(names, rb.antecedents, strict=True)}
    units.update(feature_units or {})
    term_names = [v.linguistic_variable_names() for v in rb.antecedents]
    finite = np.isfinite(values).all(axis=1)
    index = np.full(values.shape[0], -1, dtype=int)
    index[finite] = np.arange(int(finite.sum()))
    act = compute_classifier_activations(rb, values[finite]) if finite.any() else None

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
            valid_at_utc=issued[row] + timedelta(hours=horizon_hours), inference=spec,
            feature_values=feature_values,
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
        entries = [_trace_entry(rb, act, r, ids[r], k, names, term_names) for r in range(len(ids))]
        winner, cls = int(act.winner[k]), int(act.prediction[k])
        if winner < 0:
            prediction = m.TracePrediction(value=None, unit=target_unit, fallback_used=True,
                                           missing_reason=m.MissingReason.PREDICTION_UNAVAILABLE)
        else:
            prediction = m.TracePrediction(value=None, label=class_labels[cls], winning_rule_id=ids[winner],
                                           unit=target_unit, fallback_used=False)
        traces.append(m.RuleTrace(**common, rules=entries, prediction=prediction))
    return traces


def iter_classifier_firing_tables(
    model, X: pd.DataFrame, entity_ids: Sequence[str], issued_at_utc: Sequence, *, chunk_size: int = 100_000,
) -> Iterator[pd.DataFrame]:
    """Tidy firing tables, ``chunk_size`` rows at a time: one record per row and rule.

    Columns: ``entity_id``, ``issued_at_utc``, ``rule_id``, ``firing_strength`` (t-norm), ``weight``,
    ``association_degree`` (firing x weight), ``is_winner`` and ``missing_reason``. A row with a non-finite input
    has NaN numbers and ``missing_reason="missing_input"``; a row nothing fires on has no winner.
    """
    if chunk_size < 1:
        raise ValueError("chunk_size must be >= 1")
    refuse_mixture(model)
    rb = get_master_rulebase(model)
    check_supported(rb)
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
    weights = rule_weights(rb)
    for start in range(0, values.shape[0], chunk_size):
        stop = min(start + chunk_size, values.shape[0])
        chunk = values[start:stop]
        finite = np.isfinite(chunk).all(axis=1)
        firing = np.full((stop - start, n_rules), np.nan)
        assoc = np.full((stop - start, n_rules), np.nan)
        winner = np.full(stop - start, -1)
        if finite.any():
            act = compute_classifier_activations(rb, chunk[finite])
            firing[finite], assoc[finite], winner[finite] = act.firing, act.association, act.winner
        is_winner = winner[:, None] == np.arange(n_rules)[None, :]
        reason = np.where(finite, None, m.MissingReason.MISSING_INPUT.value).repeat(n_rules)
        yield pd.DataFrame({
            "entity_id": pd.Categorical.from_codes(np.repeat(entities.codes[start:stop], n_rules), entities.categories),
            "issued_at_utc": stamps[start:stop].repeat(n_rules),
            "rule_id": pd.Categorical.from_codes(np.tile(np.arange(n_rules), stop - start), dtype=rule_cat.dtype),
            "firing_strength": firing.ravel(),
            "weight": np.where(finite[:, None], weights[None, :], np.nan).ravel(),
            "association_degree": assoc.ravel(),
            "is_winner": is_winner.ravel(),
            "missing_reason": pd.Categorical(reason, categories=[m.MissingReason.MISSING_INPUT.value]),
        })
