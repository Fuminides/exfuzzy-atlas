"""AT-062 #4: issue time vs valid time, no future inputs, one clock across series, maps and traces."""

from __future__ import annotations

import pandas as pd
from qa_support import api_get, feature_by_entity, iso, parse, rng, rule_map, series, trace


def test_valid_at_minus_issued_at_equals_the_documented_horizon(task):
    p = task.preds
    assert ((p["valid_at_utc"] - p["issued_at_utc"]) == task.horizon).all()
    assert task.json("run_manifest.json")["horizon_hours"] == task.expect.horizon_hours == task.entry["horizon_hours"]


def test_series_rule_map_and_trace_share_the_issue_time_and_horizon(client, task):
    for _, row in task.sample_rows(3, "clock").iterrows():
        t, eid = row["issued_at_utc"], row["entity_id"]
        point = series(client, task, eid, t, t + pd.Timedelta(seconds=1))
        assert point["horizon_hours"] == task.expect.horizon_hours
        (pt,) = point["points"]
        tr = trace(client, task, eid, t)
        p = feature_by_entity(rule_map(client, task, task.rule_ids[0], metric="firing_strength", time=iso(t)))[eid]
        assert pt["issued_at_utc"] == tr["issued_at_utc"] == p["issued_at_utc"] == iso(t)
        assert pt["valid_at_utc"] == tr["valid_at_utc"] == p["valid_at_utc"] == iso(t + task.horizon)
        assert parse(pt["valid_at_utc"]) - parse(pt["issued_at_utc"]) == task.horizon


def test_series_is_sorted_by_issue_time_without_duplicates_and_inside_the_card_coverage(client, task):
    cov = api_get(client, f"/api/v1/models/{task.model_id}")["coverage"]
    entities = sorted(task.preds["entity_id"].unique())
    for eid in rng(task.task_id, "series-entities").sample(entities, 3):
        pts = (
            series(client, task, eid, None, None)["points"]
            if task.task_id == "uk_water_do"
            else series(
                client, task, eid, parse(cov["issued_from_utc"]), parse(cov["issued_from_utc"]) + pd.Timedelta(days=20)
            )["points"]
        )
        issued = [p["issued_at_utc"] for p in pts]
        assert issued == sorted(set(issued)), "issue times must be strictly increasing"
        assert cov["issued_from_utc"] <= issued[0] and issued[-1] <= cov["issued_to_utc"]
        assert all(parse(p["valid_at_utc"]) - parse(p["issued_at_utc"]) == task.horizon for p in pts)
    assert cov["issued_from_utc"] == iso(task.preds["issued_at_utc"].min())
    assert cov["issued_to_utc"] == iso(task.preds["issued_at_utc"].max())


def test_no_trace_input_is_observed_after_the_issue_time(client, task):
    """observed_at <= issued_at for every input, and observed_at == issued_at - lag_hours from feature_spec."""
    for _, row in task.sample_rows(4, "leak").iterrows():
        tr = trace(client, task, row["entity_id"], row["issued_at_utc"])
        issued = parse(tr["issued_at_utc"])
        assert parse(tr["valid_at_utc"]) - issued == task.horizon
        for fv in tr["feature_values"]:
            if fv["value"] is None:
                assert fv["observed_at_utc"] is None
                continue
            observed = parse(fv["observed_at_utc"])
            assert observed <= issued, f"LEAK: {fv['feature']} observed at {observed} after issue {issued}"
            assert issued - observed == pd.Timedelta(hours=task.spec[fv["feature"]]["lag_hours"])
            assert fv["source_id"] == task.spec[fv["feature"]]["source_id"]


def test_feature_spec_has_no_future_lags_and_forecast_observations_are_strictly_older(task):
    for name, source in task.spec.items():
        assert source["lag_hours"] >= 0, f"{name}: observed after the issue time"
        if task.expect.horizon_hours > 0 and not source["source_id"].startswith("calendar"):
            assert source["lag_hours"] >= 1, f"{name}: a measured input of a forecast must predate the issue hour"
    assert set(task.json("run_manifest.json")["features"]) <= set(task.spec)  # every model input has a source and a lag


def test_rule_map_instant_has_issue_semantics_and_water_is_a_sparse_irregular_series(client, task):
    """Madrid/NYC: an issue instant covers (almost) every entity. Water: samples are irregular, so only windows make
    sense; an instant map holds very few entities, which is why the UI must use windows there."""
    t = task.sample_rows(1, "density")["issued_at_utc"].iloc[0]
    feats = feature_by_entity(rule_map(client, task, task.rule_ids[0], metric="firing_strength", time=iso(t)))
    feats = {e: p for e, p in feats.items() if e not in task.unmodelled_ids}  # "sin modelo" zones are never covered
    covered = sum(p["n_valid"] > 0 or p["missing_reason"] == "missing_input" for p in feats.values()) / len(feats)
    on_the_hour = (task.preds["issued_at_utc"].dt.minute == 0).mean()
    if task.task_id == "uk_water_do":
        assert covered < 0.1, "an instant map of Water unexpectedly covers many points"
        assert on_the_hour < 0.2, "Water issue times are not on a regular hourly grid"
    else:
        assert covered > 0.5 and on_the_hour == 1.0
