"""Contract v0.4 endpoints over published synthetic runs (a regressor and a classifier), artifacts mode.

Every value is checked against an independent recomputation (pandas over the published Parquet files, or the ex_fuzzy
engine itself), never against the code under test.
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from atlas.contracts import models as m
from atlas.explain import build_classifier_traces, build_rule_traces
from atlas.ml import artifacts
from atlas_api.artifact_store import ArtifactStore
from atlas_api.main import create_app

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "qa"))
import wording_audit  # noqa: E402

T0 = datetime(2024, 1, 10, 0, tzinfo=timezone.utc)
MODELLED = ("E0", "E1", "E2")
WINDOW = {"from": "2024-01-10T00:00:00Z", "to": "2024-01-20T00:00:00Z"}
ACROSS_MONTHS = {"from": "2024-01-25T00:00:00Z", "to": "2024-02-05T00:00:00Z"}


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture(scope="module", params=["regression", "classification"])
def world(request, built_v04, built_class_v04):
    built = built_v04 if request.param == "regression" else built_class_v04
    store = ArtifactStore(built.published_dir)
    model_dir = built.model_dir
    activations = pq.read_table(model_dir / "activations").to_pandas().astype({"entity_id": str, "rule_id": str})
    return SimpleNamespace(
        kind=request.param, built=built, classifier=request.param == "classification",
        client=TestClient(create_app(store)),
        model_id=built.run.manifest.model_id, task_id=built.run.manifest.task_id, model_dir=model_dir,
        activations=activations, rule_ids=[r.rule_id for r in built.run.rules.rules],
        inputs=pq.read_table(model_dir / "inputs.parquet").to_pandas(),
        predictions=pq.read_table(model_dir / "predictions.parquet").to_pandas(),
        spec=json.loads((model_dir / "feature_spec.json").read_text())["features"],
    )


def get_ok(world, path, model, **params):
    response = world.client.get(path, params=params)
    assert response.status_code == 200, response.text
    return model.model_validate(response.json())


def by_entity(response):
    return {f.id: f.properties for f in response.features}


# ------------------------------------------------------------------------- unmodelled entities


def test_entities_card_and_attribution(world):
    entities = get_ok(world, "/api/v1/entities", m.EntityCollection, domain="air")
    assert {f.id: f.properties.modelled for f in entities.features} == {"E0": True, "E1": True, "E2": True, "E9": False}
    assert [a.text for a in entities.attribution][0].startswith("Synthetic data")
    card = get_ok(world, f"/api/v1/models/{world.model_id}", m.ModelCard)
    assert card.attribution == entities.attribution and card.coverage.regular is True
    if world.classifier:
        assert card.target_scheme.kind == m.SchemeKind.ANALYTICAL and card.target_scheme.short_name == "synthetic"
        rules = get_ok(world, f"/api/v1/models/{world.model_id}/rules", m.ModelRules)
        assert rules.target_scheme.classes[-1].merged_from == ["very high (invented)", "extreme (invented)"]


@pytest.mark.parametrize("metric,extra", [
    ("firing_strength", {"time": iso(T0)}),
    ("mean_activation", WINDOW),
    ("activation_frequency", {**WINDOW, "tau": 0.5}),
])
def test_rule_map_says_not_modelled_and_never_a_value(world, metric, extra):
    response = world.client.get("/api/v1/rule-map", params={
        "model_id": world.model_id, "rule_id": "R01", "metric": metric, **extra})
    assert response.status_code == 200, response.text
    features = {f["id"]: f for f in response.json()["features"]}
    props = features["E9"]["properties"]
    assert props["value"] is None and props["missing_reason"] == "not_modelled" and props["n_valid"] == 0
    assert features["E9"]["geometry"]["type"] == "Point"
    assert all(features[e]["properties"]["missing_reason"] is None for e in MODELLED)


def test_trace_series_and_scenario_for_an_unmodelled_entity(world):
    trace = get_ok(world, "/api/v1/entities/E9/rule-trace", m.RuleTrace, model_id=world.model_id, at=iso(T0))
    assert trace.rules == [] and trace.feature_values == []
    assert trace.prediction.value is None and trace.prediction.label is None
    assert trace.prediction.missing_reason == m.MissingReason.NOT_MODELLED
    assert world.client.get("/api/v1/series", params={"task_id": world.task_id, "entity_id": "E9"}).status_code == 404
    response = world.client.post("/api/v1/scenarios", json={
        "model_id": world.model_id, "entity_id": "E9", "at": iso(T0), "overrides": {}})
    assert response.status_code == 422 and "not_modelled" in response.text


# ------------------------------------------------------------- predictions (== series, == table)


def test_predictions_equal_the_series_and_the_table(world):
    response = get_ok(world, "/api/v1/predictions", m.PredictionsResponse, task_id=world.task_id, time=iso(T0))
    assert response.synthetic and response.issued_at_utc == T0 and response.horizon_hours == 6
    assert response.task_type == ("classification" if world.classifier else "regression")
    rows = by_entity(response)
    assert set(rows) == {"E0", "E1", "E2", "E9"}
    for entity in MODELLED:
        series = get_ok(world, "/api/v1/series", m.SeriesResponse, task_id=world.task_id, entity_id=entity,
                        **{"from": iso(T0), "to": iso(T0 + timedelta(hours=1))})
        [point] = series.points
        p = rows[entity]
        assert (p.issued_at_utc, p.valid_at_utc, p.observed) == (
            point.issued_at_utc, point.valid_at_utc, point.observed)
        assert (p.prediction, p.prediction_label, p.observed_label, p.missing_reason) == (
            point.prediction, point.predicted_label, point.observed_label, point.missing_reason)
        assert p.unit == "u" and p.geometry_support == m.GeometrySupport.OBSERVED_POINT
        table = world.predictions[(world.predictions.entity_id == entity) & (world.predictions.issued_at_utc == T0)]
        assert len(table) == 1 and table.iloc[0]["observed"] == p.observed
    if world.classifier:
        assert all(p.prediction is None for p in rows.values())  # a class index is never a number
    unmodelled = rows["E9"]
    assert (unmodelled.prediction, unmodelled.prediction_label, unmodelled.observed, unmodelled.issued_at_utc) == (
        None, None, None, None)
    assert unmodelled.missing_reason == m.MissingReason.NOT_MODELLED


def test_a_time_without_rows_gives_no_observation_not_a_value(world):
    response = get_ok(world, "/api/v1/predictions", m.PredictionsResponse, task_id=world.task_id,
                      time="2030-01-01T00:00:00Z")
    reasons = {e: p.missing_reason.value for e, p in by_entity(response).items()}
    assert reasons == {"E0": "no_observation", "E1": "no_observation", "E2": "no_observation", "E9": "not_modelled"}
    assert all(p.prediction is None and p.prediction_label is None for p in by_entity(response).values())


def test_predictions_window_returns_the_latest_sample_per_entity(world):
    window = {"from": "2024-01-10T00:00:00Z", "to": "2024-01-10T05:30:00Z"}  # latest issue time inside: 05:00
    response = get_ok(world, "/api/v1/predictions", m.PredictionsResponse, task_id=world.task_id, **window)
    assert response.issued_at_utc is None and response.time_to_utc == datetime(2024, 1, 10, 5, 30, tzinfo=timezone.utc)
    table = world.predictions
    for entity, p in by_entity(response).items():
        if entity == "E9":
            continue
        inside = table[(table.entity_id == entity) & (table.issued_at_utc >= T0)
                       & (table.issued_at_utc < T0 + timedelta(hours=5, minutes=30))]
        latest = inside.sort_values("issued_at_utc").iloc[-1]
        assert p.issued_at_utc == latest["issued_at_utc"] == T0 + timedelta(hours=5)
        assert p.observed == latest["observed"] and p.valid_at_utc == T0 + timedelta(hours=11)
    half_open = get_ok(world, "/api/v1/predictions", m.PredictionsResponse, task_id=world.task_id,
                       **{"from": "2024-01-10T00:00:00Z", "to": "2024-01-10T05:00:00Z"})
    assert {p.issued_at_utc for e, p in by_entity(half_open).items() if e != "E9"} == {T0 + timedelta(hours=4)}


@pytest.mark.parametrize("path", ["/api/v1/predictions", "/api/v1/observations"])
@pytest.mark.parametrize("params", [
    {}, {"time": "2024-01-10T00:00:00Z", "from": "2024-01-10T00:00:00Z", "to": "2024-01-11T00:00:00Z"},
    {"time": "2024-01-10T00:00:00Z", "to": "2024-01-11T00:00:00Z"}, {"from": "2024-01-10T00:00:00Z"},
    {"from": "2024-01-11T00:00:00Z", "to": "2024-01-10T00:00:00Z"},
    {"from": "2024-01-10T00:00:00Z", "to": "2024-01-10T00:00:00Z"},
    {"from": "2023-01-01T00:00:00Z", "to": "2024-06-01T00:00:00Z"}, {"time": "2024-01-10T00:00:00"},
])
def test_predictions_and_observations_reject_ambiguous_queries(world, path, params):
    assert world.client.get(path, params={"task_id": world.task_id, **params}).status_code == 422


@pytest.mark.parametrize("path", ["/api/v1/predictions", "/api/v1/observations"])
def test_unknown_task_is_404(world, path):
    assert world.client.get(path, params={"task_id": "nope", "time": iso(T0)}).status_code == 404


# ------------------------------------------------------------ observations (== published inputs)


def test_observations_equal_the_published_inputs(world):
    response = get_ok(world, "/api/v1/observations", m.ObservationsResponse, task_id=world.task_id, time=iso(T0))
    assert response.horizon_hours == 6 and "no predicciones ni interpolaciones" in response.note
    rows = by_entity(response)
    for entity in MODELLED:
        p = rows[entity]
        stored = world.inputs[(world.inputs.entity_id == entity) & (world.inputs.issued_at_utc == T0)].iloc[0]
        observed = world.predictions[(world.predictions.entity_id == entity)
                                     & (world.predictions.issued_at_utc == T0)].iloc[0]
        assert [fv.feature for fv in p.inputs] == world.built.run.manifest.features
        for fv in p.inputs:
            spec = world.spec[fv.feature]
            assert fv.unit == spec["unit"] and fv.source_id == spec["source_id"]
            if pd.isna(stored[fv.feature]):
                assert fv.value is None and fv.missing_reason == m.MissingReason.NO_OBSERVATION
                assert fv.observed_at_utc is None
            else:
                assert fv.value == stored[fv.feature] and fv.missing_reason is None
                assert fv.observed_at_utc == T0 - timedelta(hours=spec["lag_hours"])
        # the target is the value observed at valid_at (= issued + horizon): not known at issue time
        assert p.target.feature == "y" and p.target.unit == "u"
        assert p.target.observed_at_utc == p.valid_at_utc == T0 + timedelta(hours=6)
        assert p.target.value == (None if pd.isna(observed["observed"]) else observed["observed"])
        if world.classifier:
            assert p.target_label == observed["observed_label"]
    unmodelled = rows["E9"]
    assert unmodelled.missing_reason == m.MissingReason.NOT_MODELLED
    assert unmodelled.target is None and unmodelled.inputs == []


def test_observations_flag_missing_inputs_as_null_with_a_reason(world):
    missing = world.inputs[world.inputs[world.built.run.manifest.features].isna().any(axis=1)]
    assert not missing.empty, "the synthetic table must have some missing inputs"
    row = missing.iloc[0]
    response = get_ok(world, "/api/v1/observations", m.ObservationsResponse, task_id=world.task_id,
                      time=iso(row["issued_at_utc"]))
    p = by_entity(response)[row["entity_id"]]
    nulls = [fv for fv in p.inputs if fv.value is None]
    assert nulls and all(fv.missing_reason == m.MissingReason.NO_OBSERVATION for fv in nulls)
    assert p.quality.status == m.QualityStatus.WARNING
    assert all(fv.value != 0 for fv in nulls)  # null is never turned into 0


def test_observations_window_is_the_latest_sample_per_entity(world):
    response = get_ok(world, "/api/v1/observations", m.ObservationsResponse, task_id=world.task_id,
                      **{"from": "2024-01-10T00:00:00Z", "to": "2024-01-10T05:30:00Z"})
    issued = {p.issued_at_utc for e, p in by_entity(response).items() if e != "E9"}
    assert issued == {T0 + timedelta(hours=5)}


def test_trace_carries_the_observed_target(world):
    trace = get_ok(world, "/api/v1/entities/E0/rule-trace", m.RuleTrace, model_id=world.model_id, at=iso(T0))
    row = world.predictions[(world.predictions.entity_id == "E0") & (world.predictions.issued_at_utc == T0)].iloc[0]
    assert trace.observed == row["observed"]
    assert trace.observed_label == (row["observed_label"] if world.classifier else None)


# ------------------------------------------------------------------------------- territories


def oracle_territory(world, window, tau):
    """Per entity and rule, recomputed with pandas from the published firing table."""
    lo, hi = pd.Timestamp(window["from"]), pd.Timestamp(window["to"])
    table = world.activations
    table = table[(table.issued_at_utc >= lo) & (table.issued_at_utc < hi)]
    out = {}
    for entity, frame in table.groupby("entity_id"):
        n_records = frame.issued_at_utc.nunique()
        valid = frame[frame.firing_strength.notna()]
        n_valid = valid.issued_at_utc.nunique()
        rules = {}
        for rule_id in world.rule_ids:
            sub = valid[valid.rule_id == rule_id]
            rules[rule_id] = dict(
                mean=sub.firing_strength.sum() / n_valid if n_valid else None,
                freq=(sub.firing_strength >= tau).sum() / n_valid if n_valid else None,
                win=sub.is_winner.sum() / n_valid if n_valid and world.classifier else None,
            )
        out[entity] = (n_records, n_valid, rules)
    return out


def oracle_dominant(values):
    best = max(values)
    if best <= 0:
        return None
    return next(i for i, v in enumerate(values) if v >= best - 1e-12)


@pytest.mark.parametrize("window", [WINDOW, ACROSS_MONTHS], ids=["january", "across-months"])
@pytest.mark.parametrize("tau", [0.5, 0.2])
def test_territories_equal_a_pandas_recomputation(world, window, tau):
    measures = ["mean_activation", "activation_frequency"] + (["winner_share"] if world.classifier else [])
    expected = oracle_territory(world, window, tau)
    for measure in measures:
        response = get_ok(world, "/api/v1/rule-territories", m.RuleTerritoriesResponse, model_id=world.model_id,
                          measure=measure, tau=tau, **window)
        assert response.measure.value == measure and response.tau == tau and response.n_rules == len(world.rule_ids)
        assert "n_valid" in response.denominators and "lowest" in response.tie_break
        assert {n for n in response.notes if "overlap" in n}
        props = by_entity(response)
        assert set(props) == {"E0", "E1", "E2", "E9"}
        for entity, (n_records, n_valid, rules) in expected.items():
            p = props[entity]
            assert (p.n_records, p.n_valid) == (n_records, n_valid) and n_valid > 0
            assert [r.rule_id for r in p.rules] == world.rule_ids
            key = {"mean_activation": "mean", "activation_frequency": "freq", "winner_share": "win"}[measure]
            for r in p.rules:
                assert r.mean_activation == pytest.approx(rules[r.rule_id]["mean"], abs=1e-12)
                assert r.activation_frequency == pytest.approx(rules[r.rule_id]["freq"], abs=1e-12)
                assert (r.winner_share is not None) == world.classifier
                if world.classifier:
                    assert r.winner_share == pytest.approx(rules[r.rule_id]["win"], abs=1e-12)
            chosen = oracle_dominant([rules[r][key] for r in world.rule_ids])
            assert p.dominant_rule_id == (None if chosen is None else world.rule_ids[chosen])
        assert props["E9"].missing_reason == m.MissingReason.NOT_MODELLED
        assert props["E9"].rules == [] and props["E9"].dominant_rule_id is None and props["E9"].n_valid == 0


def test_territories_n_valid_excludes_missing_inputs_and_the_window_is_half_open(world):
    first = get_ok(world, "/api/v1/rule-territories", m.RuleTerritoriesResponse, model_id=world.model_id, **WINDOW)
    longer = get_ok(world, "/api/v1/rule-territories", m.RuleTerritoriesResponse, model_id=world.model_id,
                    **{"from": WINDOW["from"], "to": "2024-01-20T01:00:00Z"})
    a, b = by_entity(first), by_entity(longer)
    for entity in MODELLED:
        assert b[entity].n_records == a[entity].n_records + 1  # `to` itself is excluded, +1 h adds one record
        assert a[entity].n_valid <= a[entity].n_records
    assert any(a[e].n_valid < a[e].n_records for e in MODELLED), "the synthetic table has missing inputs"


def test_territories_tie_break_and_dominance_are_only_the_argmax_of_the_measure(world):
    response = get_ok(world, "/api/v1/rule-territories", m.RuleTerritoriesResponse, model_id=world.model_id, **WINDOW)
    for p in by_entity(response).values():
        if not p.rules:
            continue
        top = max(r.mean_activation for r in p.rules)
        first = next(r for r in p.rules if r.mean_activation >= top - 1e-12)
        assert p.dominant_rule_id == first.rule_id and p.dominant_value == first.mean_activation
    # different measures may give different dominant rules: dominance is not a property of the entity
    freq = get_ok(world, "/api/v1/rule-territories", m.RuleTerritoriesResponse, model_id=world.model_id,
                  measure="activation_frequency", **WINDOW)
    assert freq.measure == m.TerritoryMeasure.ACTIVATION_FREQUENCY


def test_territories_reject_bad_queries(world):
    base = {"model_id": world.model_id, **WINDOW}
    url = "/api/v1/rule-territories"
    assert world.client.get(url, params={**base, "from": WINDOW["to"], "to": WINDOW["from"]}).status_code == 422
    assert world.client.get(url, params={**base, "from": "2023-01-01T00:00:00Z", "to": "2024-06-01T00:00:00Z"}
                            ).status_code == 422  # more than 366 days
    assert world.client.get(url, params={**base, "from": "2023-01-10T00:00:00Z", "to": "2024-01-10T00:00:00Z"}
                            ).status_code == 200  # 365 days
    assert world.client.get(url, params={**base, "measure": "dominant"}).status_code == 422
    assert world.client.get(url, params={**base, "tau": 0}).status_code == 422
    assert world.client.get(url, params={**base, "tau": 1.5}).status_code == 422
    assert world.client.get(url, params={**base, "from": "2024-01-10T00:00:00"}).status_code == 422
    assert world.client.get(url, params={"model_id": "nope", **WINDOW}).status_code == 404
    assert world.client.get(url, params={"model_id": world.model_id}).status_code == 422
    winner = world.client.get(url, params={**base, "measure": "winner_share"})
    assert winner.status_code == (200 if world.classifier else 422)


def test_territories_are_cached_and_stable(world):
    a = world.client.get("/api/v1/rule-territories", params={"model_id": world.model_id, **WINDOW})
    b = world.client.get("/api/v1/rule-territories", params={"model_id": world.model_id, **WINDOW})
    assert a.json() == b.json()


def test_a_window_without_records_is_no_observation(world):
    response = get_ok(world, "/api/v1/rule-territories", m.RuleTerritoriesResponse, model_id=world.model_id,
                      **{"from": "2030-01-01T00:00:00Z", "to": "2030-01-02T00:00:00Z"})
    reasons = {e: p.missing_reason.value for e, p in by_entity(response).items()}
    assert reasons == {"E0": "no_observation", "E1": "no_observation", "E2": "no_observation", "E9": "not_modelled"}


# ----------------------------------------------------------------------------------- stories


def count(features, check):
    values = [f["properties"][check.property] for f in features]
    if check.op == "not_null":
        return sum(v is not None for v in values)
    if check.op == "eq":
        return sum(v == check.operand for v in values)
    return sum(v is not None and v >= check.operand for v in values)


def reproduce(world, story):
    """Run the story's own queries through the API and apply its checks."""
    results = []
    for query in story.queries:
        response = world.client.request(query.method, query.path, params=query.params)
        assert response.status_code == 200, (query, response.text)
        results.append(response.json()["features"])
    for check in story.checks:
        assert count(results[check.query], check) == check.expected, (story.story_id, check)


@pytest.mark.parametrize("tau", [0.5, 0.1])
def test_every_story_reproduces_its_numbers_through_the_quoted_queries(world, tau):
    response = get_ok(world, "/api/v1/rule-stories", m.RuleStoriesResponse, model_id=world.model_id, tau=tau,
                      **{"from": "2024-01-05T00:00:00Z", "to": "2024-02-14T00:00:00Z"})
    assert response.stories, "the synthetic runs have co-activation bursts"
    assert response.n_candidates >= len(response.stories) and response.tau == tau
    kinds = {s.kind for s in response.stories}
    assert m.StoryKind.CO_ACTIVATION_BURST in kinds
    for story in response.stories:
        reproduce(world, story)
        assert story.rule_id in story.text and f"τ={tau:g}" in story.text or story.kind == m.StoryKind.TERRITORY_LEADER
        if story.kind == m.StoryKind.CO_ACTIVATION_BURST:
            n = story.numbers
            assert f"{n['n_active_at_peak']} de {n['n_reporting_at_peak']}" in story.text
            assert f"{n['hours']} h" in story.text and n["steps"] == len(story.queries)
            assert all(q.params["metric"] == "firing_strength" and "time" in q.params for q in story.queries)
            assert n["n_reporting_at_peak"] == 3  # E9 has no model and never counts
        else:
            assert "3" in story.text or "de 4" not in story.text
    scores = [s.score for s in response.stories]
    assert scores == sorted(scores, reverse=True) and all(0 <= s <= 1 for s in scores)


def test_story_numbers_agree_with_an_independent_burst_count(world):
    response = get_ok(world, "/api/v1/rule-stories", m.RuleStoriesResponse, model_id=world.model_id,
                      **{"from": "2024-01-05T00:00:00Z", "to": "2024-02-14T00:00:00Z"})
    burst = next(s for s in response.stories if s.kind == m.StoryKind.CO_ACTIVATION_BURST)
    table = world.activations
    table = table[(table.rule_id == burst.rule_id) & table.firing_strength.notna()]
    for q in burst.queries:
        t = pd.Timestamp(q.params["time"])
        at = table[table.issued_at_utc == t]
        check = next(c for c in burst.checks if c.query == burst.queries.index(q) and c.op == "gte")
        assert (at.firing_strength >= 0.5).sum() == check.expected
    assert len(burst.queries) >= 3  # a burst is a run of at least three consecutive issue times
    times = [pd.Timestamp(q.params["time"]) for q in burst.queries]
    assert all(b - a == pd.Timedelta(hours=1) for a, b in zip(times, times[1:], strict=False))


def test_stories_are_capped_deterministic_and_wording_clean(world):
    params = {"model_id": world.model_id, "from": "2024-01-05T00:00:00Z", "to": "2024-02-14T00:00:00Z", "tau": 0.1}
    full = world.client.get("/api/v1/rule-stories", params=params).json()
    again = world.client.get("/api/v1/rule-stories", params=params).json()
    assert full == again
    top = world.client.get("/api/v1/rule-stories", params={**params, "limit": 1}).json()
    assert top["stories"] == full["stories"][:1] and top["n_candidates"] == full["n_candidates"] and top["limit"] == 1
    assert len(full["stories"]) == min(10, full["n_candidates"])
    hits = [h for h in wording_audit.scan_payload(full, "rule-stories") if h.kind != "other-context"]
    assert hits == []
    hits = [h for h in wording_audit.scan_payload(world.client.get("/api/v1/rule-territories", params={
        "model_id": world.model_id, **WINDOW}).json(), "rule-territories") if h.kind != "other-context"]
    assert hits == []
    assert full["disclaimer"].startswith("Descripciones de activaciones") and "No son causas" in full["disclaimer"]
    for story in full["stories"]:
        for word in ("causa", "explica", "debido a", "porque", "provoca", "probabilidad", "riesgo"):
            assert word not in story["text"].lower().replace("no es la contribución", "")


def test_stories_reject_bad_queries(world):
    base = {"model_id": world.model_id, "from": "2024-01-05T00:00:00Z", "to": "2024-02-14T00:00:00Z"}
    url = "/api/v1/rule-stories"
    assert world.client.get(url, params={**base, "limit": 0}).status_code == 422
    assert world.client.get(url, params={**base, "limit": 51}).status_code == 422
    assert world.client.get(url, params={**base, "tau": 0}).status_code == 422
    assert world.client.get(url, params={**base, "from": base["to"], "to": base["from"]}).status_code == 422
    assert world.client.get(url, params={**base, "from": "2023-01-01T00:00:00Z", "to": "2024-06-01T00:00:00Z"}
                            ).status_code == 422
    assert world.client.get(url, params={**base, "model_id": "nope"}).status_code == 404


# ----------------------------------------------------------------------------------- scenarios


def focus(world):
    """An input that some rule of the model uses, so that overriding it moves a firing."""
    return "y_lag3" if world.classifier else "y_t"


def full_row(world, entity="E0"):
    features = world.built.run.manifest.features
    rows = world.inputs[(world.inputs.entity_id == entity) & world.inputs[features].notna().all(axis=1)
                        & (world.inputs.issued_at_utc >= T0)]
    return rows.iloc[0]


def engine_trace(world, values, entity, at):
    """The ex_fuzzy engine on a modified row, built straight from the model (not through the API)."""
    features = world.built.run.manifest.features
    X = pd.DataFrame([{f: values[f] for f in features}])
    common = dict(model_id=world.model_id, task_id=world.task_id, horizon_hours=6, target_unit="u",
                  data_version="synthetic-test", synthetic=True)
    if world.classifier:
        labels = [c.label for c in world.built.run.rules.target_scheme.classes]
        return build_classifier_traces(world.built.run.model, X, [entity], [at], class_labels=labels, **common)[0]
    return build_rule_traces(world.built.run.model, X, [entity], [at], **common)[0]


def post(world, **body):
    return world.client.post("/api/v1/scenarios", json={"model_id": world.model_id, **body})


def domain_of(world, feature):
    variable = next(v for v in world.built.run.rules.variables if v.feature == feature)
    return variable.domain


def test_scenario_equals_the_engine_on_the_modified_row(world):
    row = full_row(world)
    at = row["issued_at_utc"]
    lo, hi = domain_of(world, focus(world))
    overrides = {focus(world): lo + 0.8 * (hi - lo), "exo_t": float(row["exo_t"]) + 0.5}
    response = post(world, entity_id="E0", at=iso(at), overrides=overrides)
    assert response.status_code == 200, response.text
    scenario = m.ScenarioResponse.model_validate(response.json())
    assert scenario.synthetic_what_if is True and scenario.label == m.WHAT_IF_LABEL and scenario.synthetic
    values = {f: float(row[f]) for f in world.built.run.manifest.features} | overrides
    expected = engine_trace(world, values, "E0", at)
    assert [r.model_dump() for r in scenario.modified.rules] == [r.model_dump() for r in expected.rules]
    assert scenario.modified.prediction == expected.prediction
    assert {fv.feature: fv.value for fv in scenario.modified.feature_values} == values
    # the original is exactly what the published row gives, i.e. the same as GET rule-trace
    served = get_ok(world, "/api/v1/entities/E0/rule-trace", m.RuleTrace, model_id=world.model_id, at=iso(at))
    assert scenario.original == served
    assert scenario.model_id == world.model_id and scenario.entity_id == "E0" and scenario.issued_at_utc == at
    # deltas are modified - original, rule by rule, and some rule really moved
    before = {r.rule_id: r for r in scenario.original.rules}
    after = {r.rule_id: r for r in scenario.modified.rules}
    assert [d.rule_id for d in scenario.rule_deltas] == world.rule_ids
    for delta in scenario.rule_deltas:
        moved = after[delta.rule_id].firing_strength - before[delta.rule_id].firing_strength
        assert delta.firing_delta == pytest.approx(moved, abs=1e-12)
        if world.classifier:
            assert delta.association_delta == pytest.approx(
                after[delta.rule_id].association_degree - before[delta.rule_id].association_degree, abs=1e-12)
        else:
            assert delta.association_delta is None
    assert any(abs(d.firing_delta) > 1e-9 for d in scenario.rule_deltas)
    change = scenario.prediction_change
    if world.classifier:
        assert (change.original_label, change.scenario_label) == (served.prediction.label, expected.prediction.label)
        assert change.label_changed == (change.original_label != change.scenario_label)
        assert change.original_value is None and change.value_delta is None
    else:
        assert change.value_delta == pytest.approx(expected.prediction.value - served.prediction.value, abs=1e-9)
        assert change.label_changed is None
    # the modified trace is labelled as a what-if and nothing claims it was observed
    assert any("no efecto causal" in w for w in scenario.modified.quality.warnings)
    overridden = [fv for fv in scenario.modified.feature_values if fv.feature in overrides]
    assert all(fv.source_id == "what_if_override" and fv.observed_at_utc is None for fv in overridden)
    assert scenario.modified.observed is None


def test_no_override_gives_the_identical_trace(world):
    row = full_row(world, "E1")
    scenario = m.ScenarioResponse.model_validate(post(world, entity_id="E1", at=iso(row["issued_at_utc"])).json())
    assert scenario.modified == scenario.original
    assert all(d.firing_delta == 0 for d in scenario.rule_deltas)
    assert scenario.prediction_change.label_changed in (False, None)
    assert scenario.prediction_change.value_delta in (0, None)
    assert {i.origin for i in scenario.inputs} == {"observed"}


def test_each_input_is_flagged_observed_or_overridden(world):
    row = full_row(world)
    lo, hi = domain_of(world, "hour")
    scenario = m.ScenarioResponse.model_validate(post(
        world, entity_id="E0", at=iso(row["issued_at_utc"]), overrides={"hour": (lo + hi) / 2}).json())
    flags = {i.feature: i.origin for i in scenario.inputs}
    assert flags == {"y_t": "observed", "y_lag3": "observed", "exo_t": "observed", "hour": "overridden"}
    hour = next(i for i in scenario.inputs if i.feature == "hour")
    assert hour.original_value == row["hour"] and hour.scenario_value == (lo + hi) / 2 and hour.domain == (lo, hi)
    assert hour.unit == "h"


@pytest.mark.parametrize("which", ["below", "above"])
def test_out_of_domain_overrides_are_422(world, which):
    row = full_row(world)
    lo, hi = domain_of(world, focus(world))
    value = lo - 1e-6 if which == "below" else hi + 1e-6
    response = post(world, entity_id="E0", at=iso(row["issued_at_utc"]), overrides={focus(world): value})
    assert response.status_code == 422 and "outside the variable's domain" in response.text


def test_domain_bounds_are_inside(world):
    row = full_row(world)
    lo, hi = domain_of(world, focus(world))
    for value in (lo, hi):
        response = post(world, entity_id="E0", at=iso(row["issued_at_utc"]), overrides={focus(world): value})
        assert response.status_code == 200


def test_invalid_scenarios_are_rejected(world):
    row = full_row(world)
    at = iso(row["issued_at_utc"])
    assert post(world, entity_id="E0", at=at, overrides={"not_a_feature": 1.0}).status_code == 422
    assert post(world, entity_id="E0", at=at, overrides={focus(world): "abc"}).status_code == 422
    raw = json.dumps({"model_id": world.model_id, "entity_id": "E0", "at": at, "overrides": {focus(world): 0}}
                     ).replace(": 0}", ": NaN}")
    assert world.client.post("/api/v1/scenarios", content=raw, headers={"content-type": "application/json"}
                             ).status_code == 422
    raw = raw.replace("NaN", "Infinity")
    assert world.client.post("/api/v1/scenarios", content=raw, headers={"content-type": "application/json"}
                             ).status_code == 422
    assert post(world, entity_id="E0", at="2024-01-10T00:00:00").status_code == 422  # not explicit UTC
    assert post(world, entity_id="E0", at=at, overrides={}, extra=1).status_code == 422
    assert world.client.post("/api/v1/scenarios", json={"entity_id": "E0", "at": at}).status_code == 422
    assert post(world, entity_id="E0", at="2030-01-01T00:00:00Z").status_code == 404  # no published row
    assert post(world, entity_id="NOPE", at=at).status_code == 404
    assert world.client.post("/api/v1/scenarios", json={"model_id": "nope", "entity_id": "E0", "at": at}
                             ).status_code == 404
    assert world.client.get("/api/v1/scenarios").status_code == 405


def test_overriding_a_missing_input_gives_the_engine_answer_and_no_delta_against_nothing(world):
    features = world.built.run.manifest.features
    missing = world.inputs[(world.inputs.entity_id == "E0") & (world.inputs[features].isna().sum(axis=1) == 1)
                           & (world.inputs.issued_at_utc >= T0)]
    row = missing.iloc[0]
    feature = next(f for f in features if pd.isna(row[f]))
    lo, hi = domain_of(world, feature)
    scenario = m.ScenarioResponse.model_validate(post(
        world, entity_id="E0", at=iso(row["issued_at_utc"]), overrides={feature: (lo + hi) / 2}).json())
    assert scenario.original.rules == []
    assert scenario.original.prediction.missing_reason == m.MissingReason.MISSING_INPUT
    assert scenario.modified.rules and scenario.modified.prediction.missing_reason is None
    flagged = next(i for i in scenario.inputs if i.feature == feature)
    assert flagged.origin == "overridden" and flagged.original_value is None
    assert flagged.missing_reason == m.MissingReason.NO_OBSERVATION
    assert all(d.firing_original is None and d.firing_delta is None for d in scenario.rule_deltas)
    assert all(d.firing_scenario is not None for d in scenario.rule_deltas)
    values = {f: row[f] for f in features} | {feature: (lo + hi) / 2}
    expected = engine_trace(world, values, "E0", row["issued_at_utc"])
    assert [r.firing_strength for r in scenario.modified.rules] == [r.firing_strength for r in expected.rules]
    # without the override the missing input stays missing: no inference, no invented value
    plain = m.ScenarioResponse.model_validate(post(world, entity_id="E0", at=iso(row["issued_at_utc"])).json())
    assert plain.modified.rules == [] and plain.modified == plain.original


def snapshot(root: Path):
    return sorted(
        (str(p.relative_to(root)), p.stat().st_size, p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file())


def test_scenarios_write_nothing_to_disk(world):
    row = full_row(world)
    before = snapshot(world.built.published_dir)
    lo, hi = domain_of(world, focus(world))
    for value in (lo, (lo + hi) / 2, hi):
        response = post(world, entity_id="E0", at=iso(row["issued_at_utc"]), overrides={focus(world): value})
        assert response.status_code == 200
    assert snapshot(world.built.published_dir) == before
    artifacts.verify_checksums(world.model_dir)
    # and the published series did not move
    after = pq.read_table(world.model_dir / "predictions.parquet").to_pandas()
    pd.testing.assert_frame_equal(after, world.predictions)


def test_classifier_scenarios_can_change_the_class_and_the_winning_rule(world):
    if not world.classifier:
        pytest.skip("classifier only")
    row = full_row(world)
    lo, hi = domain_of(world, focus(world))
    changed = False
    for value in np.linspace(lo, hi, 9):
        scenario = m.ScenarioResponse.model_validate(post(
            world, entity_id="E0", at=iso(row["issued_at_utc"]), overrides={focus(world): float(value)}).json())
        change = scenario.prediction_change
        if change.label_changed:
            changed = True
            assert change.original_label != change.scenario_label
            assert change.scenario_label == scenario.modified.prediction.label
            best = max(scenario.modified.rules, key=lambda r: r.association_degree)
            assert best.rule_id == change.scenario_winning_rule_id
    assert changed, "moving y_t across its whole domain must change the synthetic class somewhere"


def test_scenario_payload_wording_is_clean(world):
    row = full_row(world)
    payload = post(world, entity_id="E0", at=iso(row["issued_at_utc"]), overrides={focus(world): 10.0}).json()
    hits = [h for h in wording_audit.scan_payload(payload, "scenario") if h.kind != "other-context"]
    assert hits == []
