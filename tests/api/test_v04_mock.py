"""Contract v0.4 endpoints in mock mode (fixtures/synthetic): same semantics as artifacts mode, hand-checkable data."""

import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from atlas.contracts import models as m
from atlas.explain import build_rule_traces
from atlas.services.mock_model import build_rulebase
from atlas_api.main import app, create_app
from atlas_api.mock_store import FixtureStore

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "fixtures" / "synthetic"
sys.path.insert(0, str(REPO / "scripts" / "qa"))
import wording_audit  # noqa: E402

client = TestClient(app)
MODEL, TASK = "synthetic-no2-h6-v0", "madrid_no2_h6"
T0 = datetime(2025, 1, 15, 6, tzinfo=timezone.utc)
WINDOW = {"from": "2025-01-15T06:00:00Z", "to": "2025-01-15T12:00:00Z"}
RULES = ["R01", "R02", "R03"]


def iso(value):
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def get_ok(path, model, **params):
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    return model.model_validate(response.json())


def raw(name):
    return json.loads((FIXTURES / name).read_text())


# ------------------------------------------------------------------- unmodelled station


@pytest.fixture(scope="module")
def unmodelled_client(tmp_path_factory):
    """The stock fixtures plus a fifth station that is in the geometry file but has no model (SYN_E)."""
    root = tmp_path_factory.mktemp("fixtures")
    for path in FIXTURES.iterdir():
        shutil.copy(path, root / path.name)
    entities = raw("entities_air.json")
    extra = json.loads(json.dumps(entities["features"][0]))
    extra["id"] = extra["properties"]["entity_id"] = "SYN_E"
    extra["properties"]["modelled"] = False
    entities["features"].append(extra)
    (root / "entities_air.json").write_text(json.dumps(entities))
    return TestClient(create_app(FixtureStore(root)))


def test_the_stock_mock_fixtures_have_attribution_and_every_station_modelled():
    entities = get_ok("/api/v1/entities", m.EntityCollection, domain="air")
    assert {f.id: f.properties.modelled for f in entities.features} == {
        "SYN_A": True, "SYN_B": True, "SYN_C": True, "SYN_D": True}
    assert entities.attribution and get_ok(f"/api/v1/models/{MODEL}", m.ModelCard).attribution == entities.attribution


def test_unmodelled_station_in_every_view(unmodelled_client):
    c = unmodelled_client

    def ok(path, model, **params):
        response = c.get(path, params=params)
        assert response.status_code == 200, response.text
        return model.model_validate(response.json())

    for metric, extra in [("firing_strength", {"time": iso(T0)}), ("mean_activation", WINDOW)]:
        response = c.get("/api/v1/rule-map", params={"model_id": MODEL, "rule_id": "R01", "metric": metric, **extra})
        p = {f["id"]: f["properties"] for f in response.json()["features"]}["SYN_E"]
        assert (p["value"], p["missing_reason"], p["n_valid"]) == (None, "not_modelled", 0)
    trace = ok("/api/v1/entities/SYN_E/rule-trace", m.RuleTrace, model_id=MODEL, at=iso(T0))
    assert trace.rules == [] and trace.prediction.missing_reason == m.MissingReason.NOT_MODELLED
    assert c.get("/api/v1/series", params={"task_id": TASK, "entity_id": "SYN_E"}).status_code == 404
    p = by_entity(ok("/api/v1/predictions", m.PredictionsResponse, task_id=TASK, time=iso(T0)))
    assert p["SYN_E"].prediction is None and p["SYN_E"].missing_reason == m.MissingReason.NOT_MODELLED
    assert p["SYN_A"].prediction is not None  # the other stations are unaffected
    o = by_entity(ok("/api/v1/observations", m.ObservationsResponse, task_id=TASK, time=iso(T0)))["SYN_E"]
    assert o.target is None and o.missing_reason == m.MissingReason.NOT_MODELLED
    t = by_entity(ok("/api/v1/rule-territories", m.RuleTerritoriesResponse, model_id=MODEL, **WINDOW))["SYN_E"]
    assert (t.n_valid, t.dominant_rule_id, t.missing_reason) == (0, None, m.MissingReason.NOT_MODELLED)
    stories = ok("/api/v1/rule-stories", m.RuleStoriesResponse, model_id=MODEL, **WINDOW)
    assert all(s.numbers.get("n", 4) == 4 and s.numbers.get("n_reporting_at_peak", 4) == 4 for s in stories.stories)
    body = {"model_id": MODEL, "entity_id": "SYN_E", "at": iso(T0), "overrides": {}}
    assert c.post("/api/v1/scenarios", json=body).status_code == 422


def by_entity(response):
    return {f.id: f.properties for f in response.features}


# ----------------------------------------------------------- predictions and observations


@pytest.mark.parametrize("hours", range(6))
def test_predictions_equal_the_series_at_every_issue_time(hours):
    t = T0 + timedelta(hours=hours)
    rows = by_entity(get_ok("/api/v1/predictions", m.PredictionsResponse, task_id=TASK, time=iso(t)))
    for entity in ("SYN_A", "SYN_B", "SYN_C", "SYN_D"):
        series = get_ok("/api/v1/series", m.SeriesResponse, task_id=TASK, entity_id=entity)
        point = next(p for p in series.points if p.issued_at_utc == t)
        p = rows[entity]
        assert (p.prediction, p.observed, p.missing_reason, p.valid_at_utc) == (
            point.prediction, point.observed, point.missing_reason, point.valid_at_utc)


def test_a_missing_input_gives_a_null_prediction_with_its_reason():
    at = iso(T0 + timedelta(hours=2))
    rows = by_entity(get_ok("/api/v1/predictions", m.PredictionsResponse, task_id=TASK, time=at))
    assert rows["SYN_D"].prediction is None and rows["SYN_D"].missing_reason == m.MissingReason.MISSING_INPUT
    assert rows["SYN_B"].prediction == 44.0  # an actual 44.0, not a null


def test_predictions_window_and_errors():
    rows = by_entity(get_ok("/api/v1/predictions", m.PredictionsResponse, task_id=TASK, **WINDOW))
    assert {r.issued_at_utc for r in rows.values()} == {T0 + timedelta(hours=5)}
    for params in ({}, {"time": iso(T0), **WINDOW}, {"from": iso(T0)}):
        assert client.get("/api/v1/predictions", params={"task_id": TASK, **params}).status_code == 422
    assert client.get("/api/v1/predictions", params={"task_id": "nope", "time": iso(T0)}).status_code == 404
    empty = by_entity(get_ok("/api/v1/predictions", m.PredictionsResponse, task_id=TASK, time="2030-01-01T00:00:00Z"))
    assert {r.missing_reason.value for r in empty.values()} == {"no_observation"}


def test_observations_equal_the_fixture_inputs():
    t = T0 + timedelta(hours=2)
    rows = by_entity(get_ok("/api/v1/observations", m.ObservationsResponse, task_id=TASK, time=iso(t)))
    traces = {(x["entity_id"], x["issued_at_utc"]): x for x in raw("rule_traces.json")}
    series = {s["entity_id"]: s for s in raw("series.json")}
    for entity, p in rows.items():
        stored = traces[(entity, iso(t).replace("Z", "Z"))]
        assert [(fv.feature, fv.value) for fv in p.inputs] == [
            (f["feature"], f["value"]) for f in stored["feature_values"]]
        point = next(x for x in series[entity]["points"] if x["issued_at_utc"] == iso(t))
        assert p.target.value == point["observed"] and p.target.observed_at_utc == p.valid_at_utc
    wind = next(fv for fv in rows["SYN_D"].inputs if fv.feature == "wind_speed_t")
    assert wind.value is None and wind.missing_reason == m.MissingReason.NO_OBSERVATION  # missing, not 0
    assert all(fv.observed_at_utc <= t for p in rows.values() for fv in p.inputs if fv.observed_at_utc)


def test_trace_carries_observed():
    trace = get_ok("/api/v1/entities/SYN_A/rule-trace", m.RuleTrace, model_id=MODEL, at=iso(T0))
    point = next(x for x in raw("series.json") if x["entity_id"] == "SYN_A")["points"][0]
    assert trace.observed == point["observed"]


# ------------------------------------------------------------------------------ territories


def oracle(tau):
    frame = pd.DataFrame([
        {"entity": t["entity_id"], "issued": t["issued_at_utc"], "rule": r["rule_id"], "f": r["firing_strength"]}
        for t in raw("rule_traces.json") for r in t["rules"]
    ])
    records = pd.DataFrame([{"entity": t["entity_id"], "issued": t["issued_at_utc"]} for t in raw("rule_traces.json")])
    out = {}
    for entity, sub in frame.groupby("entity"):
        n_valid = sub.issued.nunique()
        out[entity] = dict(
            n_records=(records.entity == entity).sum(), n_valid=n_valid,
            mean={r: sub[sub.rule == r].f.sum() / n_valid for r in RULES},
            freq={r: (sub[sub.rule == r].f >= tau).sum() / n_valid for r in RULES},
        )
    return out


@pytest.mark.parametrize("tau", [0.5, 0.25])
def test_territories_equal_a_pandas_recomputation(tau):
    expected = oracle(tau)
    for measure in ("mean_activation", "activation_frequency"):
        response = get_ok("/api/v1/rule-territories", m.RuleTerritoriesResponse, model_id=MODEL, measure=measure,
                          tau=tau, **WINDOW)
        key = {"mean_activation": "mean", "activation_frequency": "freq"}[measure]
        props = by_entity(response)
        assert props["SYN_D"].n_records == 6 and props["SYN_D"].n_valid == 5  # one missing input
        for entity, e in expected.items():
            p = props[entity]
            assert (p.n_records, p.n_valid) == (e["n_records"], e["n_valid"])
            for r in p.rules:
                assert r.mean_activation == pytest.approx(e["mean"][r.rule_id], abs=1e-12)
                assert r.activation_frequency == pytest.approx(e["freq"][r.rule_id], abs=1e-12)
                assert r.winner_share is None  # a TSK regressor has no winning rule
            values = [e[key][r] for r in RULES]
            top = max(values)
            first = next(i for i, v in enumerate(values) if v >= top - 1e-12)
            assert p.dominant_rule_id == (None if top <= 0 else RULES[first])


def test_a_regressor_has_no_winner_share_and_a_zero_measure_has_no_dominant_rule():
    assert client.get("/api/v1/rule-territories", params={"model_id": MODEL, "measure": "winner_share", **WINDOW}
                      ).status_code == 422
    # SYN_B never activates R01 or R03 above tau=1.0 ... use a window with one record where everything is 0
    response = get_ok("/api/v1/rule-territories", m.RuleTerritoriesResponse, model_id=MODEL,
                      measure="activation_frequency", tau=1.0, **WINDOW)
    zeroed = [p for p in by_entity(response).values() if p.rules and all(r.activation_frequency == 0 for r in p.rules)]
    assert zeroed and all(p.dominant_rule_id is None and p.quality.warnings for p in zeroed)


def test_territory_errors():
    url = "/api/v1/rule-territories"
    assert client.get(url, params={"model_id": MODEL, "from": WINDOW["to"], "to": WINDOW["from"]}).status_code == 422
    assert client.get(url, params={"model_id": MODEL, "from": "2023-01-01T00:00:00Z", "to": "2025-01-01T00:00:00Z"}
                      ).status_code == 422
    assert client.get(url, params={"model_id": "nope", **WINDOW}).status_code == 404


# --------------------------------------------------------------------------------- stories


def test_stories_reproduce_through_their_queries_in_the_mock():
    response = get_ok("/api/v1/rule-stories", m.RuleStoriesResponse, model_id=MODEL, tau=0.5, **WINDOW)
    assert response.stories
    for story in response.stories:
        results = []
        for q in story.queries:
            r = client.request(q.method, q.path, params=q.params)
            assert r.status_code == 200
            results.append(r.json()["features"])
        for c in story.checks:
            values = [f["properties"][c.property] for f in results[c.query]]
            got = (sum(v is not None for v in values) if c.op == "not_null"
                   else sum(v == c.operand for v in values) if c.op == "eq"
                   else sum(v is not None and v >= c.operand for v in values))
            assert got == c.expected, (story.story_id, c)
    hits = wording_audit.scan_payload(response.model_dump(mode="json"), "stories")
    assert [h for h in hits if h.kind != "other-context"] == []


# --------------------------------------------------------------------------------- scenarios


def engine(values, entity, at):
    X = pd.DataFrame([values])
    return build_rule_traces(build_rulebase(), X, [entity], [at], model_id=MODEL, task_id=TASK, horizon_hours=6,
                             target_unit="ug/m3", data_version="synthetic-fixture-v0", synthetic=True)[0]


def scenario(**body):
    return client.post("/api/v1/scenarios", json={"model_id": MODEL, **body})


def test_scenario_is_the_engine_on_the_modified_row():
    at = T0 + timedelta(hours=1)
    trace = next(x for x in raw("rule_traces.json")
                 if x["entity_id"] == "SYN_A" and x["issued_at_utc"] == iso(at))
    stored = {fv["feature"]: fv["value"] for fv in trace["feature_values"]}
    response = scenario(entity_id="SYN_A", at=iso(at), overrides={"wind_speed_t": 5.0, "no2_t": 120.0})
    assert response.status_code == 200, response.text
    result = m.ScenarioResponse.model_validate(response.json())
    expected = engine({**stored, "wind_speed_t": 5.0, "no2_t": 120.0}, "SYN_A", at)
    assert [r.model_dump() for r in result.modified.rules] == [r.model_dump() for r in expected.rules]
    assert result.modified.prediction == expected.prediction
    assert result.original == get_ok("/api/v1/entities/SYN_A/rule-trace", m.RuleTrace, model_id=MODEL, at=iso(at))
    assert result.synthetic_what_if and result.label == m.WHAT_IF_LABEL
    assert {i.feature: i.origin for i in result.inputs} == {"no2_t": "overridden", "wind_speed_t": "overridden"}
    assert result.prediction_change.value_delta == pytest.approx(
        expected.prediction.value - result.original.prediction.value, abs=1e-9)


def test_no_override_is_the_identical_trace_and_bad_overrides_are_422():
    at = iso(T0)
    result = m.ScenarioResponse.model_validate(scenario(entity_id="SYN_B", at=at).json())
    assert result.modified == result.original and {i.origin for i in result.inputs} == {"observed"}
    bounds = scenario(entity_id="SYN_B", at=at, overrides={"no2_t": 200.0, "wind_speed_t": 0.0})
    assert bounds.status_code == 200
    for overrides in ({"no2_t": 200.1}, {"no2_t": -0.1}, {"wind_speed_t": 20.5}, {"nope": 1.0}, {"no2_t": "x"}):
        assert scenario(entity_id="SYN_B", at=at, overrides=overrides).status_code == 422, overrides
    assert scenario(entity_id="NOPE", at=at).status_code == 404
    assert scenario(entity_id="SYN_B", at="2030-01-01T00:00:00Z").status_code == 404


def test_overriding_the_missing_input_of_the_fixture_runs_the_engine():
    at = T0 + timedelta(hours=2)  # SYN_D has no wind here
    plain = m.ScenarioResponse.model_validate(scenario(entity_id="SYN_D", at=iso(at)).json())
    assert plain.original.rules == [] and plain.modified == plain.original
    filled = m.ScenarioResponse.model_validate(
        scenario(entity_id="SYN_D", at=iso(at), overrides={"wind_speed_t": 1.0}).json())
    assert filled.modified.rules and all(d.firing_delta is None for d in filled.rule_deltas)


def test_scenarios_do_not_touch_the_fixtures():
    before = sorted((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in FIXTURES.iterdir())
    scenario(entity_id="SYN_A", at=iso(T0), overrides={"no2_t": 10.0})
    assert sorted((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in FIXTURES.iterdir()) == before


# ---------------------------------------------------------------- reference responses


def test_committed_reference_responses_are_what_the_api_returns():
    entries = raw("v04_responses.json")
    assert {e["path"] for e in entries} == {
        "/api/v1/predictions", "/api/v1/observations", "/api/v1/rule-territories", "/api/v1/rule-stories",
        "/api/v1/scenarios"}
    for entry in entries:
        if entry["method"] == "GET":
            response = client.get(entry["path"], params=entry["query"])
        else:
            response = client.post(entry["path"], json=entry["body"])
        assert response.status_code == 200, entry
        assert response.json() == entry["response"], entry["path"]
