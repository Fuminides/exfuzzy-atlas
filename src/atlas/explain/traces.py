"""Rule traces (AT-044) and bulk firing tables for precomputing rule maps.

``build_rule_traces`` returns one ``atlas.contracts.models.RuleTrace`` per input row, every number coming
from ex_fuzzy (see ``engine``). Rows with a non-finite input are never sent to ex_fuzzy: their trace has
no rules and ``prediction.missing_reason == "missing_input"`` (v0.1 has no partial firing). A firing of
exactly 0 is a number; only a missing input yields null.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from atlas.contracts import models as m
from atlas.explain.engine import (
    RuleActivations,
    compute_activations,
    feature_names,
    get_rulebase,
    inference_spec,
    rule_ids,
    rule_modifier,
)


def _feature_matrix(rulebase, X: pd.DataFrame) -> np.ndarray:
    """Feature columns in antecedent order as float64 (a missing column raises KeyError)."""
    names = feature_names(rulebase)
    absent = [name for name in names if name not in X.columns]
    if absent:
        raise KeyError(f"X is missing model features: {absent}")
    return X[names].to_numpy(dtype=float)


def _as_utc_datetimes(issued_at_utc: Sequence) -> list[datetime]:
    stamps = pd.DatetimeIndex(issued_at_utc)
    if stamps.tz is None:
        raise ValueError("issued_at_utc must be timezone-aware (UTC)")
    return [stamp.tz_convert("UTC").to_pydatetime() for stamp in stamps]


def _check_lengths(n_rows: int, entity_ids: Sequence, issued_at_utc: Sequence) -> None:
    if len(entity_ids) != n_rows or len(issued_at_utc) != n_rows:
        raise ValueError("X, entity_ids and issued_at_utc must have the same length")


def _activations_for_finite_rows(rulebase, values: np.ndarray, finite: np.ndarray, with_prediction: bool):
    """Activations for the finite rows only, plus the map from original row to activation row."""
    index = np.full(values.shape[0], -1, dtype=int)
    index[finite] = np.arange(int(finite.sum()))
    if not finite.any():
        return None, index
    return compute_activations(rulebase, values[finite], with_prediction=with_prediction), index


def build_rule_traces(
    model,
    X: pd.DataFrame,
    entity_ids: Sequence[str],
    issued_at_utc: Sequence,
    *,
    model_id: str,
    task_id: str,
    horizon_hours: int,
    target_unit: str,
    data_version: str,
    synthetic: bool = False,
    feature_units: dict[str, str] | None = None,
) -> list[m.RuleTrace]:
    """One ``RuleTrace`` per row of ``X``; ``model`` is a fitted regressor, wrapper or rule base."""
    rulebase = get_rulebase(model)
    values = _feature_matrix(rulebase, X)
    _check_lengths(values.shape[0], entity_ids, issued_at_utc)
    issued = _as_utc_datetimes(issued_at_utc)
    names = feature_names(rulebase)
    ids = rule_ids(rulebase)
    units = {name: getattr(var, "units", None) for name, var in zip(names, rulebase.antecedents, strict=True)}
    units.update(feature_units or {})
    spec = inference_spec(rulebase)
    term_names = [var.linguistic_variable_names() for var in rulebase.antecedents]

    finite = np.isfinite(values).all(axis=1)
    act, index = _activations_for_finite_rows(rulebase, values, finite, with_prediction=True)

    traces = []
    for row in range(values.shape[0]):
        feature_values = []
        for f, name in enumerate(names):
            value = values[row, f]
            ok = bool(np.isfinite(value))
            reason = None
            if not ok:
                reason = m.MissingReason.NO_OBSERVATION if np.isnan(value) else m.MissingReason.INVALID_OBSERVATION
            feature_values.append(m.FeatureValue(
                feature=name, value=float(value) if ok else None, unit=units[name], missing_reason=reason,
            ))
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
                prediction=m.TracePrediction(
                    value=None, unit=target_unit, fallback_used=False, missing_reason=m.MissingReason.MISSING_INPUT,
                ),
                quality=m.Quality(status=m.QualityStatus.WARNING, warnings=["missing input: " + ", ".join(missing)]),
            ))
            continue
        k = index[row]
        entries = [
            _trace_entry(rulebase, act, r, ids[r], k, names, term_names) for r in range(len(rulebase.rules))
        ]
        traces.append(m.RuleTrace(
            **common, rules=entries,
            prediction=m.TracePrediction(
                value=float(act.prediction[k]), unit=target_unit, fallback_used=bool(act.fallback_used[k]),
            ),
        ))
    return traces


def _trace_entry(rulebase, act: RuleActivations, r: int, rule_id: str, k: int, names, term_names) -> m.RuleTraceEntry:
    rule = rulebase.rules[r]
    antecedents = []
    for f, term in enumerate(rule.antecedents):
        if term < 0:
            continue
        membership = float(act.memberships[f][term][k])
        modifier = rule_modifier(rule, f)
        antecedents.append(m.AntecedentTrace(
            feature=names[f], term=term_names[f][term], membership=membership, modifier=modifier,
            effective_membership=membership if modifier is None else membership**modifier,
        ))
    return m.RuleTraceEntry(
        rule_id=rule_id, antecedents=antecedents,
        firing_strength=float(act.raw[k, r]), effective_firing=float(act.effective[k, r]),
    )


def iter_firing_tables(
    model,
    X: pd.DataFrame,
    entity_ids: Sequence[str],
    issued_at_utc: Sequence,
    *,
    chunk_size: int = 100_000,
) -> Iterator[pd.DataFrame]:
    """Tidy firing tables, ``chunk_size`` input rows at a time (rows x rules records per chunk).

    Columns: ``entity_id``, ``issued_at_utc``, ``rule_id``, ``firing_strength`` (raw t-norm),
    ``effective_firing`` (after rule_mode) and ``missing_reason``. Rows with a missing input get one record
    per rule with NaN firing and ``missing_reason="missing_input"``, so null never looks like 0.
    Ordering is row-major: all rules of input row 0, then input row 1, ...
    """
    if chunk_size < 1:
        raise ValueError("chunk_size must be >= 1")
    rulebase = get_rulebase(model)
    values = _feature_matrix(rulebase, X)
    _check_lengths(values.shape[0], entity_ids, issued_at_utc)
    stamps = pd.DatetimeIndex(issued_at_utc)
    if stamps.tz is None:
        raise ValueError("issued_at_utc must be timezone-aware (UTC)")
    stamps = stamps.tz_convert("UTC")
    entities = pd.Categorical(np.asarray(entity_ids, dtype=object))
    ids = rule_ids(rulebase)
    n_rules = len(ids)
    rule_codes = np.arange(n_rules)
    rule_cat = pd.Categorical.from_codes(np.arange(n_rules), categories=ids)

    for start in range(0, values.shape[0], chunk_size):
        stop = min(start + chunk_size, values.shape[0])
        chunk = values[start:stop]
        finite = np.isfinite(chunk).all(axis=1)
        raw = np.full((stop - start, n_rules), np.nan)
        effective = np.full((stop - start, n_rules), np.nan)
        if finite.any():
            act = compute_activations(rulebase, chunk[finite], with_prediction=False)
            raw[finite], effective[finite] = act.raw, act.effective
        reason = np.where(finite, None, m.MissingReason.MISSING_INPUT.value).repeat(n_rules)
        yield pd.DataFrame({
            "entity_id": pd.Categorical.from_codes(np.repeat(entities.codes[start:stop], n_rules), entities.categories),
            "issued_at_utc": stamps[start:stop].repeat(n_rules),
            "rule_id": pd.Categorical.from_codes(np.tile(rule_codes, stop - start), dtype=rule_cat.dtype),
            "firing_strength": raw.ravel(),
            "effective_firing": effective.ravel(),
            "missing_reason": pd.Categorical(reason, categories=[m.MissingReason.MISSING_INPUT.value]),
        })


def firing_table(model, X: pd.DataFrame, entity_ids: Sequence[str], issued_at_utc: Sequence, **kwargs) -> pd.DataFrame:
    """All chunks of ``iter_firing_tables`` concatenated (rows x rules records: mind the memory)."""
    chunks = list(iter_firing_tables(model, X, entity_ids, issued_at_utc, **kwargs))
    if not chunks:
        return pd.DataFrame(columns=["entity_id", "issued_at_utc", "rule_id", "firing_strength", "effective_firing",
                                     "missing_reason"])
    return pd.concat(chunks, ignore_index=True)
