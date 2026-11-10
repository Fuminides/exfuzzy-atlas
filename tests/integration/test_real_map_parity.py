"""AT-062 #1: the value painted on the map is the value of the activations table and of the rule trace (real models)."""

from __future__ import annotations

import pandas as pd
import pytest
from qa_support import api_get, feature_by_entity, iso, rng, rule_map, trace

ABS = 1e-9


def _rules_to_check(task, act: pd.DataFrame) -> list[str]:
    """First rule, the rule with the highest firing at that instant, and a random one (deterministic)."""
    ids = [task.rule_ids[0]]
    valid = act.dropna(subset=["firing_strength"])
    if len(valid):
        ids.append(valid.loc[valid["firing_strength"].idxmax(), "rule_id"])
    ids.append(rng(task.task_id, "rule-pick").choice(task.rule_ids))
    return list(dict.fromkeys(ids))


def test_firing_strength_map_equals_activations_table_and_rule_trace(client, task):
    entity_ids = {f["properties"]["entity_id"] for f in task.entities["features"]}
    checked_trace = 0
    for _, row in task.sample_rows(3, "parity").iterrows():
        t = row["issued_at_utc"]
        act_all = task.activations("issued_at_utc = ?", [t.to_pydatetime()])
        assert len(act_all), f"no activation records at {t} although predictions.parquet has a row"
        for rid in _rules_to_check(task, act_all):
            resp = rule_map(client, task, rid, metric="firing_strength", time=iso(t))
            feats = feature_by_entity(resp)
            assert set(feats) == entity_ids, "rule-map must carry exactly the published entities"
            act = act_all[act_all["rule_id"] == rid].set_index("entity_id")
            for eid, p in feats.items():
                where = f"{task.task_id} {rid} {eid} {t}"
                assert p["issued_at_utc"] == iso(t) == p["time_from_utc"] == p["time_to_utc"], where
                if eid in task.unmodelled_ids:
                    assert (p["value"], p["n_valid"], p["missing_reason"]) == (None, 0, "not_modelled"), where
                elif eid not in act.index:
                    assert (p["value"], p["n_valid"], p["missing_reason"]) == (None, 0, "no_observation"), where
                elif pd.isna(act.loc[eid, "firing_strength"]):
                    assert (p["value"], p["n_valid"], p["missing_reason"]) == (None, 0, "missing_input"), where
                else:
                    assert p["value"] == pytest.approx(act.loc[eid, "firing_strength"], abs=1e-12), where
                    assert p["n_valid"] == 1 and p["missing_reason"] is None, where
            # the same cell through the rule trace (the verified engine run on one row)
            with_value = [e for e in act.index if not pd.isna(act.loc[e, "firing_strength"])]
            for eid in with_value[:2]:
                entry = next(r for r in trace(client, task, eid, t)["rules"] if r["rule_id"] == rid)
                assert entry["firing_strength"] == pytest.approx(feats[eid]["value"], abs=ABS), f"trace {rid} {eid} {t}"
                if "effective_firing" in act.columns:
                    assert entry["effective_firing"] == pytest.approx(act.loc[eid, "effective_firing"], abs=ABS)
                if "association_degree" in act.columns:
                    assert entry["association_degree"] == pytest.approx(act.loc[eid, "association_degree"], abs=ABS)
                    assert entry["weight"] == pytest.approx(act.loc[eid, "weight"], abs=ABS)
                checked_trace += 1
    assert checked_trace > 0


@pytest.mark.parametrize(
    "metric,tau", [("mean_activation", None), ("activation_frequency", 0.5), ("activation_frequency", 0.2)]
)
def test_window_aggregates_equal_a_recomputation_with_n_valid(client, task, metric, tau):
    t0 = task.sample_rows(1, "window")["issued_at_utc"].iloc[0]
    span = pd.Timedelta(days=45 if task.task_id == "uk_water_do" else 2)  # Water: sparse irregular samples
    lo, hi = t0 - span / 2, t0 + span / 2
    act_all = task.activations("issued_at_utc >= ? AND issued_at_utc < ?", [lo.to_pydatetime(), hi.to_pydatetime()])
    entity_ids = {f["properties"]["entity_id"] for f in task.entities["features"]}
    seen_valid = 0
    for rid in [task.rule_ids[0], rng(task.task_id, "window-rule").choice(task.rule_ids)]:
        params = {"metric": metric, "from": iso(lo), "to": iso(hi)}
        if tau is not None:
            params["tau"] = tau
        feats = feature_by_entity(rule_map(client, task, rid, **params))
        assert set(feats) == entity_ids
        act = act_all[act_all["rule_id"] == rid]
        for eid, p in feats.items():
            rows = act[act["entity_id"] == eid]["firing_strength"]
            valid = rows.dropna()
            where = f"{task.task_id} {metric} {rid} {eid}"
            assert p["n_valid"] == len(valid), where  # the denominator is the number of non-missing records
            if len(valid) == 0:
                assert p["value"] is None, where
                unmodelled = eid in task.unmodelled_ids
                assert p["missing_reason"] == (
                    "not_modelled" if unmodelled else "missing_input" if len(rows) else "no_observation"), where
                continue
            seen_valid += 1
            expected = valid.mean() if metric == "mean_activation" else (valid >= tau).sum() / len(valid)
            assert p["value"] == pytest.approx(expected, abs=1e-9), where
            assert p["missing_reason"] is None and 0.0 <= p["value"] <= 1.0, where
            assert p["time_from_utc"] == iso(lo) and p["time_to_utc"] == iso(hi), where
    assert seen_valid > 0, "the window contained no valid activation: the test checked nothing"


def test_the_rule_map_endpoint_rejects_ambiguous_time_arguments(client, task):
    """A window metric given an instant (and the reverse) is a 422, never a silently reinterpreted time."""
    rid, t = task.rule_ids[0], iso(task.preds["issued_at_utc"].iloc[0])
    base = {"model_id": task.model_id, "rule_id": rid}
    assert client.get("/api/v1/rule-map", params={**base, "metric": "mean_activation", "time": t}).status_code == 422
    assert (
        client.get("/api/v1/rule-map", params={**base, "metric": "firing_strength", "from": t, "to": t}).status_code
        == 422
    )
    assert api_get(client, "/api/v1/health")["mode"] == "artifacts"
