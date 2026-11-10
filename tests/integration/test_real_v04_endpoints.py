"""Contract v0.4 over the real published models: metadata, predictions, observations, territories, stories, what-if.

Ground truth comes from the published Parquet/JSON files and from the pickled model itself (never from the API store).
"""

from __future__ import annotations

import pandas as pd
import pytest
import wording_audit
from qa_support import api_get, feature_by_entity, iso, rng, series, trace

from atlas.contracts import models as m
from atlas.explain import build_classifier_traces, build_mixture_traces, build_rule_traces
from atlas.ml import artifacts

WINDOW_DAYS = 3


def window_of(task):
    """A short window around a sampled issue time (Water: wider, its samples are sparse)."""
    t0 = task.sample_rows(1, "v04-window")["issued_at_utc"].iloc[0]
    span = pd.Timedelta(days=60 if task.task_id == "uk_water_do" else WINDOW_DAYS)
    return t0 - span / 2, t0 + span / 2


# ---------------------------------------------------------------------------------- metadata


def test_attribution_regular_flag_scheme_kind_and_merged_classes(client, task):
    card = api_get(client, f"/api/v1/models/{task.model_id}")
    entities = api_get(client, "/api/v1/entities", domain=task.expect.domain, task_id=task.task_id)
    assert card["attribution"] and entities["attribution"], "every real model publishes the credits of its sources"
    assert all(a["text"] for a in card["attribution"])
    assert card["coverage"]["regular"] is (task.task_id != "uk_water_do")
    rules = api_get(client, f"/api/v1/models/{task.model_id}/rules")
    scheme = rules.get("target_scheme")
    if task.task_id == "madrid_no2_h6":
        assert (scheme["kind"], scheme["short_name"]) == ("official_index", "ICA")
        merged = {c["label"]: c["merged_from"] for c in scheme["classes"]}
        assert merged["Desfavorable o peor"] == ["Desfavorable", "Muy desfavorable", "Extremadamente desfavorable"]
        assert all(v == [] for k, v in merged.items() if k != "Desfavorable o peor")
        assert any(a["license"] == "CC BY 4.0" for a in card["attribution"])
        assert any(a["license"] is None and "ICA" in a["text"] for a in card["attribution"])  # no declared licence
    elif task.task_id == "de_no2_h6":
        assert (scheme["kind"], scheme["short_name"]) == ("official_index", "EAQI")
        merged = {c["label"]: c["merged_from"] for c in scheme["classes"]}
        assert merged == {"Good": [], "Fair": [], "Moderate": [],
                          "Poor or worse": ["Poor", "Very poor", "Extremely poor"]}
        assert [c["color"] for c in scheme["classes"]] == ["#50F0E6", "#50CCAA", "#F0E641", "#FF5050"]  # EEA viewer
        assert all(a["license"] == "CC BY 4.0" for a in card["attribution"])
    elif task.task_id == "nyc_pickups_h1":
        assert scheme["kind"] == "percentile_reference" and scheme["short_name"]
        assert any(a["license"] is None and "licencia abierta" in a["text"] for a in card["attribution"])
    else:
        assert scheme is None
        assert any(a["license"] == "Open Government Licence v3.0" for a in card["attribution"])
    assert card["target_scheme"] == scheme


def test_unmodelled_entities_have_no_value_in_any_view(client, task):
    flags = {f["id"]: f["properties"]["modelled"] for f in api_get(
        client, "/api/v1/entities", domain=task.expect.domain, task_id=task.task_id)["features"]}
    unmodelled = sorted(e for e, v in flags.items() if v is False)
    assert len(unmodelled) == len(task.unmodelled_ids)
    assert len(unmodelled) == (153 if task.task_id == "nyc_pickups_h1" else 0)
    if not unmodelled:
        return
    eid = unmodelled[0]
    t = task.sample_rows(1, "unmodelled")["issued_at_utc"].iloc[0]
    tr = trace(client, task, eid, t)
    assert tr["rules"] == [] and tr["feature_values"] == []
    assert tr["prediction"]["missing_reason"] == "not_modelled" and tr["prediction"]["label"] is None
    window = {"from": iso(t - pd.Timedelta(hours=12)), "to": iso(t + pd.Timedelta(hours=12))}
    views = [
        api_get(client, "/api/v1/predictions", task_id=task.task_id, time=iso(t)),
        api_get(client, "/api/v1/observations", task_id=task.task_id, time=iso(t)),
        api_get(client, "/api/v1/rule-territories", model_id=task.model_id, **window),
        api_get(client, "/api/v1/rule-map", model_id=task.model_id, rule_id=task.rule_ids[0],
                metric="mean_activation", **window),
    ]
    for view in views:
        props = feature_by_entity(view)
        for e in unmodelled:
            assert props[e]["missing_reason"] == "not_modelled", (view.get("type"), e)
            assert props[e].get("value") is None and props[e].get("prediction") is None
    assert client.get("/api/v1/series", params={"task_id": task.task_id, "entity_id": eid}).status_code == 404


# ----------------------------------------------------------------------- predictions, observations


def test_predictions_equal_the_series_for_every_entity_of_an_issue_time(client, task):
    if task.task_id == "uk_water_do":
        pytest.skip("Water issue times are irregular samples: see the window test")
    t = task.sample_rows(1, "v04-pred")["issued_at_utc"].iloc[0]
    response = api_get(client, "/api/v1/predictions", task_id=task.task_id, time=iso(t))
    m.PredictionsResponse.model_validate(response)
    props = feature_by_entity(response)
    assert len(props) == task.expect.n_entities and response["issued_at_utc"] == iso(t)
    rows = task.preds[task.preds["issued_at_utc"] == t].set_index("entity_id")
    for eid in rng(task.task_id, "v04-pred-entities").sample(sorted(rows.index), 5):
        point = series(client, task, eid, t, t + pd.Timedelta(seconds=1))["points"][0]
        p = props[eid]
        assert (p["prediction"], p["observed"], p["missing_reason"], p["valid_at_utc"]) == (
            point["prediction"], point["observed"], point["missing_reason"], point["valid_at_utc"])
        assert p["prediction_label"] == point["predicted_label"] and p["observed_label"] == point["observed_label"]
    for eid, p in props.items():
        if eid in rows.index:
            stored = rows.loc[eid]
            assert p["valid_at_utc"] == iso(stored["valid_at_utc"])
            assert p["prediction_label"] == (stored.get("prediction_label") if task.classifier else None)
        elif eid not in task.unmodelled_ids:
            assert p["missing_reason"] == "no_observation" and p["prediction"] is None
    if task.classifier:
        assert all(p["prediction"] is None for p in props.values())


def test_predictions_window_returns_the_latest_sample_per_entity(client, task):
    lo, hi = window_of(task)
    response = api_get(client, "/api/v1/predictions", task_id=task.task_id, **{"from": iso(lo), "to": iso(hi)})
    m.PredictionsResponse.model_validate(response)
    inside = task.preds[(task.preds["issued_at_utc"] >= lo) & (task.preds["issued_at_utc"] < hi)]
    latest = inside.sort_values("issued_at_utc").groupby("entity_id").tail(1).set_index("entity_id")
    props = feature_by_entity(response)
    assert response["issued_at_utc"] is None and response["time_from_utc"] == iso(lo)
    assert set(latest.index) <= set(props)
    for eid, row in latest.iterrows():
        assert props[eid]["issued_at_utc"] == iso(row["issued_at_utc"]), eid
        assert props[eid]["valid_at_utc"] == iso(row["valid_at_utc"])
        assert props[eid]["observed"] == (None if pd.isna(row["observed"]) else row["observed"])
    for eid in set(props) - set(latest.index):
        assert props[eid]["prediction"] is None and props[eid]["missing_reason"] in ("no_observation", "not_modelled")


def test_observations_equal_the_published_inputs_and_target(client, task):
    rows = task.sample_rows(4, "v04-obs")
    for _, row in rows.iterrows():
        t, eid = row["issued_at_utc"], row["entity_id"]
        response = api_get(client, "/api/v1/observations", task_id=task.task_id,
                           **{"from": iso(t), "to": iso(t + pd.Timedelta(seconds=1))})
        m.ObservationsResponse.model_validate(response)
        p = feature_by_entity(response)[eid]
        stored = task.inputs[(task.inputs["entity_id"] == eid) & (task.inputs["issued_at_utc"] == t)].iloc[0]
        assert p["issued_at_utc"] == iso(t)
        assert p["target"]["observed_at_utc"] == p["valid_at_utc"] == iso(t + task.horizon)
        assert p["target"]["value"] == (None if pd.isna(row["observed"]) else row["observed"])
        if task.classifier:
            assert p["target_label"] == (None if pd.isna(row["observed_label"]) else row["observed_label"])
        for fv in p["inputs"]:
            spec = task.spec[fv["feature"]]
            if pd.isna(stored[fv["feature"]]):
                assert fv["value"] is None and fv["missing_reason"] == "no_observation"
            else:
                assert fv["value"] == stored[fv["feature"]] and fv["unit"] == spec["unit"]
                assert pd.Timestamp(fv["observed_at_utc"]) == t - pd.Timedelta(hours=spec["lag_hours"])
                assert pd.Timestamp(fv["observed_at_utc"]) <= t  # no information from after the issue time


def test_traces_carry_the_observed_target(client, task):
    for _, row in task.sample_rows(3, "v04-trace-observed").iterrows():
        tr = trace(client, task, row["entity_id"], row["issued_at_utc"])
        assert tr["observed"] == (None if pd.isna(row["observed"]) else row["observed"])
        if task.classifier:
            assert tr["observed_label"] == (None if pd.isna(row["observed_label"]) else row["observed_label"])


# ------------------------------------------------------------------- territories and stories


def test_territories_equal_a_recomputation_from_the_published_firing_table(client, task):
    lo, hi = window_of(task)
    act = task.activations("issued_at_utc >= ? AND issued_at_utc < ?", [lo.to_pydatetime(), hi.to_pydatetime()])
    measures = ["mean_activation", "activation_frequency"] + (["winner_share"] if task.winning_rule else [])
    checked = 0
    for measure in measures:
        response = api_get(client, "/api/v1/rule-territories", model_id=task.model_id, measure=measure, tau=0.3,
                           **{"from": iso(lo), "to": iso(hi)})
        m.RuleTerritoriesResponse.model_validate(response)
        props = feature_by_entity(response)
        for eid, frame in act.groupby("entity_id"):
            valid = frame.dropna(subset=["firing_strength"])
            p = props[eid]
            n_valid = valid["issued_at_utc"].nunique()
            assert p["n_valid"] == n_valid and p["n_records"] == frame["issued_at_utc"].nunique(), eid
            if not n_valid:
                assert p["dominant_rule_id"] is None and p["missing_reason"] == "missing_input"
                continue
            values = {}
            for r in p["rules"]:
                sub = valid[valid["rule_id"] == r["rule_id"]]["firing_strength"]
                assert r["mean_activation"] == pytest.approx(sub.sum() / n_valid, abs=1e-9)
                assert r["activation_frequency"] == pytest.approx((sub >= 0.3).sum() / n_valid, abs=1e-9)
                if task.winning_rule:
                    wins = valid[(valid["rule_id"] == r["rule_id"]) & valid["is_winner"]].shape[0]
                    assert r["winner_share"] == pytest.approx(wins / n_valid, abs=1e-9)
                values[r["rule_id"]] = r[measure]
            top = max(values.values())
            expected = None if top <= 0 else next(r for r in task.rule_ids if values[r] >= top - 1e-12)
            assert p["dominant_rule_id"] == expected, (measure, eid)
            checked += 1
    assert checked > 0
    assert api_get(client, "/api/v1/rule-territories", model_id=task.model_id, **{"from": iso(lo), "to": iso(hi)}
                   )["tie_break"]


def test_every_story_reproduces_its_numbers_through_the_quoted_queries(client, task):
    lo, hi = window_of(task)
    wide = pd.Timedelta(days=30 if task.task_id != "uk_water_do" else 200)
    params = {"model_id": task.model_id, "from": iso(lo - wide / 2), "to": iso(hi + wide / 2), "tau": 0.5}
    response = api_get(client, "/api/v1/rule-stories", **params)
    m.RuleStoriesResponse.model_validate(response)
    scores = [s["score"] for s in response["stories"]]
    assert scores == sorted(scores, reverse=True) and len(scores) <= 10
    if task.task_id == "uk_water_do":  # irregular samples: instants are meaningless, so no burst stories
        assert "co_activation_burst" not in {s["kind"] for s in response["stories"]}
    for story in response["stories"][:6]:
        results = [api_get(client, q["path"], **q["params"])["features"] for q in story["queries"]]
        for check in story["checks"]:
            values = [f["properties"][check["property"]] for f in results[check["query"]]]
            got = (sum(v is not None for v in values) if check["op"] == "not_null"
                   else sum(v == check["operand"] for v in values) if check["op"] == "eq"
                   else sum(v is not None and v >= check["operand"] for v in values))
            assert got == check["expected"], (story["story_id"], check)
    assert [h for h in wording_audit.scan_payload(response, "rule-stories") if h.kind != "other-context"] == []


# ------------------------------------------------------------------------------------- what-if


def _engine(task, values, entity, at):
    model = artifacts.load_model(task.path)  # trusted: our own published run, SHA256SUMS checked by load_model
    X = pd.DataFrame([{f: values[f] for f in task.json("run_manifest.json")["features"]}])
    common = dict(model_id=task.model_id, task_id=task.task_id, horizon_hours=task.entry["horizon_hours"],
                  target_unit=task.entry["unit"], data_version=task.entry["data_version"])
    if task.mixture:
        return build_mixture_traces(model, X, [entity], [at], class_labels=task.labels, **common)[0]
    if task.classifier:
        return build_classifier_traces(model, X, [entity], [at], class_labels=task.labels, **common)[0]
    return build_rule_traces(model, X, [entity], [at], **common)[0]


def _complete_row(task):
    features = task.json("run_manifest.json")["features"]
    full = task.inputs[task.inputs[features].notna().all(axis=1)]
    return full.sample(1, random_state=20261031).iloc[0]


def test_what_if_reruns_the_real_engine_and_changes_nothing_on_disk(client, task):
    row = _complete_row(task)
    eid, at = row["entity_id"], row["issued_at_utc"]
    features = task.json("run_manifest.json")["features"]
    domains = {v["feature"]: v["domain"] for v in task.rules["variables"]}
    used = next(f for f in features if any(a["feature"] == f for r in task.rules["rules"] for a in r["antecedents"]))
    lo, hi = domains[used]
    override = lo + 0.9 * (hi - lo)
    sums_before = (task.path / "SHA256SUMS").read_text()
    body = {"model_id": task.model_id, "entity_id": eid, "at": iso(at), "overrides": {used: override}}
    response = client.post("/api/v1/scenarios", json=body)
    assert response.status_code == 200, response.text
    scenario = m.ScenarioResponse.model_validate(response.json())
    values = {f: float(row[f]) for f in features} | {used: override}
    expected = _engine(task, values, eid, at)
    assert [r.model_dump() for r in scenario.modified.rules] == [r.model_dump() for r in expected.rules]
    assert scenario.modified.prediction.value == expected.prediction.value
    assert scenario.modified.prediction.label == expected.prediction.label
    assert scenario.original == m.RuleTrace.model_validate(trace(client, task, eid, at))
    assert {i.feature: i.origin for i in scenario.inputs}[used] == "overridden"
    assert scenario.synthetic_what_if and "no efecto causal" in scenario.label
    same = m.ScenarioResponse.model_validate(client.post("/api/v1/scenarios", json={**body, "overrides": {}}).json())
    assert same.modified == same.original
    out_of_domain = client.post("/api/v1/scenarios", json={**body, "overrides": {used: hi + 1e-6 * abs(hi) + 1e-9}})
    assert out_of_domain.status_code == 422
    assert client.post("/api/v1/scenarios", json={**body, "overrides": {"nope": 1.0}}).status_code == 422
    assert (task.path / "SHA256SUMS").read_text() == sums_before
    artifacts.verify_checksums(task.path)
    hits = wording_audit.scan_payload(response.json(), "scenario")
    assert [h for h in hits if h.kind != "other-context"] == []
