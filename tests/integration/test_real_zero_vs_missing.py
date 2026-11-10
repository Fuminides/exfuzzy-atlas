"""AT-062 #2: a 0 is a value and a missing value is null with a reason; never interchanged (map, series, trace)."""

from __future__ import annotations

import math

import pandas as pd
from qa_support import api_get, feature_by_entity, iso, rule_map, series, trace

_ORDER = "ORDER BY hash(entity_id || CAST(issued_at_utc AS VARCHAR) || rule_id) LIMIT 4"  # deterministic sample


def test_zero_firing_is_a_number_in_the_map_and_the_trace(client, task):
    zeros = task.activations(f"firing_strength = 0 {_ORDER}")
    assert len(zeros) > 0, "no exact-zero firing in the table: nothing to distinguish from missing"
    for _, z in zeros.iterrows():
        p = feature_by_entity(
            rule_map(client, task, z["rule_id"], metric="firing_strength", time=iso(z["issued_at_utc"]))
        )[z["entity_id"]]
        assert p["value"] == 0.0 and p["value"] is not None, f"0 firing turned into null: {dict(z)}"
        assert p["missing_reason"] is None and p["n_valid"] == 1
        entry = next(
            r for r in trace(client, task, z["entity_id"], z["issued_at_utc"])["rules"] if r["rule_id"] == z["rule_id"]
        )
        assert entry["firing_strength"] == 0.0


def test_a_zero_aggregate_is_a_number_and_an_entity_without_records_is_null(client, task):
    """mean_activation 0.0 (all records valid and zero) must not be reported as missing, and vice versa."""
    zero = task.activations(
        "rule_id = (SELECT rule_id FROM read_parquet(?, hive_partitioning=true) WHERE firing_strength = 0 LIMIT 1) "
        "AND firing_strength = 0 LIMIT 1",
        [str(task.path / "activations" / "*" / "*" / "*.parquet")],
    )
    t = zero["issued_at_utc"].iloc[0]
    resp = rule_map(
        client,
        task,
        zero["rule_id"].iloc[0],
        metric="activation_frequency",
        tau=0.5,
        **{"from": iso(t), "to": iso(t + pd.Timedelta(hours=1))},
    )
    feats = feature_by_entity(resp)
    p = feats[zero["entity_id"].iloc[0]]
    assert p["value"] == 0.0 and p["n_valid"] == 1 and p["missing_reason"] is None
    for q in feats.values():  # the invariant, over every entity
        assert (q["value"] is None) == (q["missing_reason"] is not None)
        if q["value"] is None:
            assert q["n_valid"] == 0


def test_missing_inputs_are_null_with_a_reason_everywhere(client, task):
    missing = task.preds[task.preds["missing_reason"] == "missing_input"]
    if missing.empty:
        return  # NYC: its inputs are complete (no missing_input rows to check)
    row = missing.iloc[len(missing) // 2]
    t, eid = row["issued_at_utc"], row["entity_id"]
    tr = trace(client, task, eid, t)
    assert tr["prediction"]["value"] is None and tr["prediction"]["label"] is None
    assert tr["prediction"]["missing_reason"] == "missing_input"
    assert tr["rules"] == [], "no inference is run with a missing input, so no firing may be shown (not even 0)"
    nulls = [f for f in tr["feature_values"] if f["value"] is None]
    assert nulls and all(f["missing_reason"] is not None and f["observed_at_utc"] is None for f in nulls)
    assert all(f["missing_reason"] is None for f in tr["feature_values"] if f["value"] is not None)
    # the map shows the same cell as null/missing_input for every rule, not 0
    for rid in task.rule_ids[:3]:
        p = feature_by_entity(rule_map(client, task, rid, metric="firing_strength", time=iso(t)))[eid]
        assert (p["value"], p["missing_reason"]) == (None, "missing_input")
    # and the series point says why the prediction is missing
    point = series(client, task, eid, t, t + pd.Timedelta(seconds=1))["points"][0]
    assert (
        point["prediction"] is None and point["predicted_label"] is None and point["missing_reason"] == "missing_input"
    )


def test_an_input_that_is_exactly_zero_stays_a_value_in_the_trace(client, task):
    cols = [c for c in task.inputs.columns if c not in ("entity_id", "issued_at_utc")]
    pairs = [(c, task.inputs[task.inputs[c] == 0]) for c in cols]
    pairs = [(c, df) for c, df in pairs if len(df)]
    assert pairs, "no input equal to 0 in inputs.parquet"
    col, df = pairs[0]
    r = df.iloc[len(df) // 2]
    fv = next(
        f for f in trace(client, task, r["entity_id"], r["issued_at_utc"])["feature_values"] if f["feature"] == col
    )
    assert fv["value"] == 0.0 and fv["missing_reason"] is None and fv["observed_at_utc"] is not None


def test_series_keeps_observed_zero_distinct_from_missing(client, task):
    obs = task.preds["observed"]
    for label, rows in (("zero", task.preds[obs == 0]), ("null", task.preds[obs.isna()])):
        if rows.empty:
            continue
        r = rows.iloc[len(rows) // 2]
        point = series(client, task, r["entity_id"], r["issued_at_utc"], r["issued_at_utc"] + pd.Timedelta(seconds=1))[
            "points"
        ][0]
        if label == "zero":
            assert point["observed"] == 0.0 and point["observed"] is not None
        else:
            assert point["observed"] is None


def test_series_points_equal_predictions_table_row_by_row(client, task):
    """Sampled windows of three entities: NaN <-> null, labels, reasons and observed values identical to the Parquet."""
    entities = sorted(task.preds["entity_id"].unique())
    checked = 0
    for eid in entities[:: max(1, len(entities) // 3)][:3]:
        part = task.preds[task.preds["entity_id"] == eid].sort_values("issued_at_utc").iloc[:400]
        pts = series(
            client, task, eid, part["issued_at_utc"].iloc[0], part["issued_at_utc"].iloc[-1] + pd.Timedelta(seconds=1)
        )["points"]
        assert len(pts) == len(part)
        for (_, row), pt in zip(part.iterrows(), pts, strict=True):
            assert pt["issued_at_utc"] == iso(row["issued_at_utc"])
            assert (pt["observed"] is None) == math.isnan(row["observed"])
            if pt["observed"] is not None:
                assert pt["observed"] == row["observed"]
            answered = pt["prediction"] is not None or pt["predicted_label"] is not None
            assert answered == (row["missing_reason"] is None), (eid, pt)
            assert (pt["missing_reason"] is None) == answered  # a reason exactly when there is no prediction
            if task.classifier:
                assert pt["prediction"] is None
                assert pt["predicted_label"] == row["prediction_label"] or (
                    pt["predicted_label"] is None and pd.isna(row["prediction_label"])
                )
            elif answered:
                assert pt["prediction"] == row["prediction"]
            checked += 1
    assert checked > 50
    assert api_get(client, "/api/v1/health")["status"] == "ok"
