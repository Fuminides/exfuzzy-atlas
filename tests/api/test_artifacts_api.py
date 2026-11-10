"""API in artifacts mode over a published synthetic run: contract, parity, aggregates, 0 != null, 422/404."""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from atlas.contracts import models as m
from atlas.services import layout
from atlas.services.publish import publish_run
from atlas_api import artifact_store
from atlas_api.artifact_store import ArtifactStore
from atlas_api.cache import approx_bytes
from atlas_api.main import create_app, make_store
from atlas_api.mock_store import FixtureStore

T0 = datetime(2024, 1, 10, 0, tzinfo=timezone.utc)
CONTRACT = {"firing_strength": m.RuleMapResponse}


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture(scope="module")
def store(built):
    return ArtifactStore(built.published_dir)


@pytest.fixture(scope="module")
def client(store):
    return TestClient(create_app(store))


@pytest.fixture(scope="module")
def model_id(built):
    return built.run.manifest.model_id


@pytest.fixture(scope="module")
def firing(built):
    """The published firing table as pandas: the ground truth the API must aggregate."""
    frame = pq.read_table(built.model_dir / "activations").to_pandas()
    return frame.astype({"entity_id": str, "rule_id": str})[
        ["entity_id", "issued_at_utc", "rule_id", "firing_strength", "effective_firing", "missing_reason"]]


def get_ok(client, path, model, **params):
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    return model.model_validate(response.json())


def rule_map(client, model_id, rule_id, metric, **params):
    return client.get("/api/v1/rule-map", params={"model_id": model_id, "rule_id": rule_id, "metric": metric, **params})


def props(response):
    assert response.status_code == 200, response.text
    return {f["id"]: f["properties"] for f in response.json()["features"]}


# ------------------------------------------------------------------ contract and discovery


def test_every_payload_validates_and_is_labelled_synthetic(client, built, model_id):
    assert client.get("/api/v1/health").json() == {"status": "ok", "schema_version": m.SCHEMA_VERSION,
                                                   "mode": "artifacts"}
    task = built.run.manifest.task_id
    payloads = [
        get_ok(client, "/api/v1/domains", m.DomainsResponse),
        get_ok(client, "/api/v1/entities", m.EntityCollection, domain="air"),
        get_ok(client, f"/api/v1/models/{model_id}", m.ModelCard),
        get_ok(client, f"/api/v1/models/{model_id}/rules", m.ModelRules),
        get_ok(client, "/api/v1/series", m.SeriesResponse, task_id=task, entity_id="E0"),
        get_ok(client, "/api/v1/rule-map", m.RuleMapResponse, model_id=model_id, rule_id="R01",
               metric="firing_strength", time=iso(T0)),
        get_ok(client, "/api/v1/rule-map", m.RuleMapResponse, model_id=model_id, rule_id="R01",
               metric="mean_activation", **{"from": iso(T0), "to": iso(T0 + timedelta(days=2))}),
        get_ok(client, "/api/v1/entities/E0/rule-trace", m.RuleTrace, model_id=model_id, at=iso(T0)),
    ]
    assert all(p.synthetic for p in payloads)
    rules = payloads[3]
    assert rules.rules == built.run.rules.rules  # served as trained, not re-derived
    assert payloads[2].coverage.step_hours == 1


def test_domains_expose_the_served_model(client, model_id, built):
    domains = get_ok(client, "/api/v1/domains", m.DomainsResponse)
    by_domain = {d.domain: d for d in domains.domains}
    task = by_domain[m.Domain.AIR].tasks[0]
    assert (task.task_id, task.model_id, task.status, task.horizon_hours) == (
        built.run.manifest.task_id, model_id, "available", 6)
    assert by_domain[m.Domain.AIR].status == "available"
    assert by_domain[m.Domain.WATER].status == "planned" and by_domain[m.Domain.WATER].tasks == []


def test_empty_published_dir(tmp_path):
    empty = TestClient(create_app(ArtifactStore(tmp_path)))
    domains = empty.get("/api/v1/domains").json()
    assert all(d["status"] == "planned" and d["tasks"] == [] for d in domains["domains"])
    assert empty.get("/api/v1/entities", params={"domain": "air"}).status_code == 404
    assert empty.get("/api/v1/models/nope").status_code == 404
    assert empty.get("/api/v1/models/..").status_code == 404


def test_mode_is_selected_by_environment(built, monkeypatch):
    assert isinstance(make_store(), FixtureStore)
    monkeypatch.setenv("ATLAS_API_MODE", "artifacts")
    monkeypatch.setenv("ATLAS_PUBLISHED_DIR", str(built.published_dir))
    assert make_store().root == built.published_dir
    monkeypatch.setenv("ATLAS_API_MODE", "bogus")
    with pytest.raises(ValueError, match="ATLAS_API_MODE"):
        make_store()


# --------------------------------------------------------------------- parity map/trace/table


def test_map_value_equals_trace_equals_activation_row(client, store, model_id, firing, built):
    times = [T0, T0 + timedelta(hours=7), datetime(2024, 1, 31, 23, tzinfo=timezone.utc),
             datetime(2024, 2, 1, tzinfo=timezone.utc)]
    n_rules = len(built.run.rules.rules)
    checked = 0
    for t in times:
        at = firing[firing["issued_at_utc"] == pd.Timestamp(t)]
        traces = {e: get_ok(client, f"/api/v1/entities/{e}/rule-trace", m.RuleTrace, model_id=model_id, at=iso(t))
                  for e in ("E0", "E1", "E2")}
        for rule in built.run.rules.rules:
            got = props(rule_map(client, model_id, rule.rule_id, "firing_strength", time=iso(t)))
            for entity, trace in traces.items():
                row = at[(at["entity_id"] == entity) & (at["rule_id"] == rule.rule_id)]
                assert len(row) == 1
                table_value = None if pd.isna(row["firing_strength"].iloc[0]) else row["firing_strength"].iloc[0]
                entries = [r for r in trace.rules if r.rule_id == rule.rule_id]
                trace_value = entries[0].firing_strength if entries else None
                assert got[entity]["value"] == pytest.approx(table_value, abs=1e-12) if table_value is not None \
                    else got[entity]["value"] is None
                assert trace_value == pytest.approx(table_value, abs=1e-12) if table_value is not None \
                    else trace_value is None
                assert got[entity]["n_valid"] == (0 if table_value is None else 1)
                assert got[entity]["valid_at_utc"] == iso(t + timedelta(hours=6))
                checked += 1
        assert all(len(trace.rules) in (0, n_rules) for trace in traces.values())
    assert checked == len(times) * 3 * n_rules


def test_missing_input_is_null_with_a_reason_and_zero_is_a_number(client, model_id, firing, built):
    table = built.table
    nan_row = table[table["exo_t"].isna() & (table["issued_at_utc"] > pd.Timestamp("2024-01-06", tz="UTC"))].iloc[0]
    t, entity = nan_row["issued_at_utc"].to_pydatetime(), nan_row["entity_id"]
    got = props(rule_map(client, model_id, "R01", "firing_strength", time=iso(t)))
    assert got[entity]["value"] is None and got[entity]["missing_reason"] == "missing_input"
    assert got[entity]["n_valid"] == 0 and got[entity]["quality"]["status"] == "warning"
    others = [p for e, p in got.items() if e != entity]
    assert others and all(p["missing_reason"] != "missing_input" for p in others if p["value"] is not None)
    trace = get_ok(client, f"/api/v1/entities/{entity}/rule-trace", m.RuleTrace, model_id=model_id, at=iso(t))
    assert trace.rules == [] and trace.prediction.missing_reason == m.MissingReason.MISSING_INPUT
    exo = next(f for f in trace.feature_values if f.feature == "exo_t")
    assert exo.value is None and exo.observed_at_utc is None and exo.source_id == "synthetic-exo_t"

    zero = firing[firing["firing_strength"] == 0.0].iloc[0]
    zero_map = props(rule_map(client, model_id, zero["rule_id"], "firing_strength", time=iso(zero["issued_at_utc"])))
    assert zero_map[zero["entity_id"]]["value"] == 0.0 and zero_map[zero["entity_id"]]["missing_reason"] is None
    assert zero_map[zero["entity_id"]]["n_valid"] == 1


def test_no_observation_outside_the_published_period(client, model_id):
    before = props(rule_map(client, model_id, "R01", "firing_strength", time="2023-06-01T00:00:00Z"))
    assert all(p["value"] is None and p["missing_reason"] == "no_observation" and p["n_valid"] == 0
               and p["valid_at_utc"] is None for p in before.values())
    window = {"from": "2023-06-01T00:00:00Z", "to": "2023-07-01T00:00:00Z"}
    assert all(p["missing_reason"] == "no_observation"
               for p in props(rule_map(client, model_id, "R01", "mean_activation", **window)).values())


# ------------------------------------------------------------------------------ aggregates


@pytest.mark.parametrize("start,end", [
    (datetime(2024, 1, 10, tzinfo=timezone.utc), datetime(2024, 1, 12, 7, tzinfo=timezone.utc)),
    (datetime(2024, 1, 31, 12, tzinfo=timezone.utc), datetime(2024, 2, 1, 12, tzinfo=timezone.utc)),  # two months
    (datetime(2024, 1, 4, tzinfo=timezone.utc), datetime(2024, 3, 1, tzinfo=timezone.utc)),  # beyond the coverage
])
def test_aggregates_equal_a_pandas_recomputation(client, model_id, firing, built, start, end):
    window = firing[(firing["issued_at_utc"] >= pd.Timestamp(start)) & (firing["issued_at_utc"] < pd.Timestamp(end))]
    for rule in ("R01", "R03", "R08"):
        sub = window[window["rule_id"] == rule]
        for metric, tau in (("mean_activation", None), ("activation_frequency", 0.3),
                            ("activation_frequency", 0.5)):
            params = {"from": iso(start), "to": iso(end), **({"tau": tau} if tau else {})}
            got = props(rule_map(client, model_id, rule, metric, **params))
            for entity in ("E0", "E1", "E2"):
                valid = sub[(sub["entity_id"] == entity)]["firing_strength"].dropna()
                p = got[entity]
                assert p["n_valid"] == len(valid) > 0
                expected = valid.mean() if tau is None else (valid >= tau).sum() / len(valid)
                assert p["value"] == pytest.approx(expected, abs=1e-12) and p["missing_reason"] is None
                assert (p["time_from_utc"], p["time_to_utc"], p["tau"]) == (iso(start), iso(end), tau)
                assert p["issued_at_utc"] is None and p["valid_at_utc"] is None


def test_n_valid_excludes_missing_records(client, model_id, firing):
    window = {"from": "2024-01-10T00:00:00Z", "to": "2024-02-10T00:00:00Z", "tau": 0.5}
    got = props(rule_map(client, model_id, "R01", "activation_frequency", **window))
    sub = firing[(firing["rule_id"] == "R01") & (firing["issued_at_utc"] >= pd.Timestamp(window["from"]))
                 & (firing["issued_at_utc"] < pd.Timestamp(window["to"]))]
    records = sub.groupby("entity_id").size()
    assert any(got[e]["n_valid"] < records[e] for e in got)  # some records have a missing input
    assert all(got[e]["n_valid"] == sub[sub["entity_id"] == e]["firing_strength"].notna().sum() for e in got)


def test_window_is_half_open(client, model_id):
    t = datetime(2024, 1, 20, 12, tzinfo=timezone.utc)
    at = props(rule_map(client, model_id, "R02", "firing_strength", time=iso(t)))
    nxt = props(rule_map(client, model_id, "R02", "firing_strength", time=iso(t + timedelta(hours=1))))
    one_hour = {"from": iso(t), "to": iso(t + timedelta(hours=1))}
    two_hours = {"from": iso(t), "to": iso(t + timedelta(hours=2))}
    one = props(rule_map(client, model_id, "R02", "mean_activation", **one_hour))
    two = props(rule_map(client, model_id, "R02", "mean_activation", **two_hours))
    for e in at:
        if at[e]["value"] is not None:  # `from` included, `to` excluded
            assert one[e]["n_valid"] == 1 and one[e]["value"] == pytest.approx(at[e]["value"])
        if at[e]["value"] is not None and nxt[e]["value"] is not None:
            assert two[e]["n_valid"] == 2
            assert two[e]["value"] == pytest.approx((at[e]["value"] + nxt[e]["value"]) / 2)


def test_all_missing_window_is_missing_input_not_zero(client, model_id, built):
    table = built.table
    row = table[table["exo_t"].isna() & (table["issued_at_utc"] > pd.Timestamp("2024-01-06", tz="UTC"))].iloc[0]
    t = row["issued_at_utc"].to_pydatetime()
    for metric, extra in (("mean_activation", {}), ("activation_frequency", {"tau": 0.5})):
        got = props(rule_map(client, model_id, "R01", metric,
                             **{"from": iso(t), "to": iso(t + timedelta(hours=1)), **extra}))[row["entity_id"]]
        assert got["value"] is None and got["missing_reason"] == "missing_input" and got["n_valid"] == 0


# -------------------------------------------------------------------------- 422 and 404


def mock_client():
    return TestClient(create_app(FixtureStore()))


@pytest.fixture(params=["mock", "artifacts"])
def any_mode(request, client, model_id):
    if request.param == "mock":
        return mock_client(), "synthetic-no2-h6-v0"
    return client, model_id


T = "2024-01-10T00:00:00Z"
T1 = "2024-01-10T06:00:00Z"
BAD_QUERIES = [
    {"metric": "firing_strength"},
    {"metric": "firing_strength", "time": T, "tau": 0.5},
    {"metric": "firing_strength", "time": T, "to": T1},
    {"metric": "mean_activation", "time": T},
    {"metric": "mean_activation", "time": T, "from": T, "to": T1},
    {"metric": "mean_activation", "from": T},
    {"metric": "mean_activation", "from": T, "to": T1, "tau": 0.5},
    {"metric": "activation_frequency", "from": T, "to": T1},
    {"metric": "activation_frequency", "from": T, "to": T1, "tau": 0},
    {"metric": "activation_frequency", "from": T, "to": T1, "tau": 1.5},
    {"metric": "mean_activation", "from": T, "to": T},
    {"metric": "mean_activation", "from": T1, "to": T},
    {"metric": "mean_activation", "from": "2022-12-31T00:00:00Z", "to": "2024-01-02T00:00:00Z"},  # > 366 days
    {"metric": "firing_strength", "time": "2024-01-10T00:00:00"},  # no explicit UTC
    {"metric": "firing_strength", "time": "2024-01-10T00:00:00+01:00"},
    {"metric": "mean_activation", "from": "2024-01-10T00:00:00", "to": T1},
]


@pytest.mark.parametrize("params", BAD_QUERIES)
def test_422_rules_are_shared_by_both_modes(any_mode, params):
    client, model = any_mode
    assert client.get("/api/v1/rule-map", params={"model_id": model, "rule_id": "R01", **params}).status_code == 422
    # validation comes before lookup, so an unknown model is a 422 too, not a 404
    assert client.get("/api/v1/rule-map", params={"model_id": "nope", "rule_id": "R01", **params}).status_code == 422


def test_window_limit_is_366_days(client, model_id):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    ok = rule_map(client, model_id, "R01", "mean_activation",
                  **{"from": iso(start), "to": iso(start + timedelta(days=366))})
    too_long = rule_map(client, model_id, "R01", "mean_activation",
                        **{"from": iso(start), "to": iso(start + timedelta(days=366, seconds=1))})
    assert (ok.status_code, too_long.status_code) == (200, 422)


def test_series_and_trace_422(any_mode):
    client, _ = any_mode
    backwards = {"task_id": "x", "entity_id": "y", "from": T1, "to": T}
    assert client.get("/api/v1/series", params=backwards).status_code == 422
    assert client.get("/api/v1/entities/E0/rule-trace", params={"model_id": "x", "at": "2024-01-10T00:00:00"}
                      ).status_code == 422


def test_unknown_things_are_404(client, model_id, built):
    task = built.run.manifest.task_id
    assert rule_map(client, "nope", "R01", "firing_strength", time=T).status_code == 404
    assert rule_map(client, model_id, "R99", "firing_strength", time=T).status_code == 404
    assert client.get("/api/v1/entities/E9/rule-trace", params={"model_id": model_id, "at": T}).status_code == 404
    assert client.get("/api/v1/entities/E0/rule-trace",
                      params={"model_id": model_id, "at": "2030-01-01T00:00:00Z"}).status_code == 404
    assert client.get("/api/v1/entities/E0/rule-trace",
                      params={"model_id": model_id, "at": "2024-01-10T00:30:00Z"}).status_code == 404  # off the grid
    assert client.get("/api/v1/series", params={"task_id": "nope", "entity_id": "E0"}).status_code == 404
    assert client.get("/api/v1/series", params={"task_id": task, "entity_id": "E9"}).status_code == 404
    assert client.get("/api/v1/models/nope/rules").status_code == 404
    assert client.get("/api/v1/entities", params={"domain": "water"}).status_code == 404


# --------------------------------------------------------------------- trace and series


def test_trace_reproduces_predict_and_fills_provenance(client, model_id, built):
    table = built.table
    for entity, t in (("E1", T0), ("E2", datetime(2024, 2, 3, 17, tzinfo=timezone.utc))):
        trace = get_ok(client, f"/api/v1/entities/{entity}/rule-trace", m.RuleTrace, model_id=model_id, at=iso(t))
        row = table[(table["entity_id"] == entity) & (table["issued_at_utc"] == pd.Timestamp(t))]
        expected = built.run.model.predict(row[built.run.config.features])[0]
        assert trace.prediction.value == pytest.approx(expected, abs=1e-9)
        assert trace.valid_at_utc - trace.issued_at_utc == timedelta(hours=6) and trace.synthetic
        lags = {"y_t": 0, "y_lag3": 3, "exo_t": 1, "hour": 0}
        for fv in trace.feature_values:
            assert fv.observed_at_utc == t - timedelta(hours=lags[fv.feature]) <= trace.issued_at_utc
            assert fv.source_id == f"synthetic-{fv.feature}" and fv.value == pytest.approx(row[fv.feature].iloc[0])
        assert len(trace.rules) == len(built.run.rules.rules)


def test_series_reproduces_predict_and_the_target(client, built):
    task = built.run.manifest.task_id
    series = get_ok(client, "/api/v1/series", m.SeriesResponse, task_id=task, entity_id="E1")
    rows = built.table[(built.table["entity_id"] == "E1") & (built.table["issued_at_utc"] >= pd.Timestamp(
        "2024-01-05", tz="UTC"))].iloc[:-1]
    assert len(series.points) == len(rows) and series.next_cursor is None
    expected = built.run.model.predict(rows[built.run.config.features])
    for point, (_, row), want in zip(series.points, rows.iterrows(), expected, strict=True):
        assert point.issued_at_utc == row["issued_at_utc"].to_pydatetime()
        if pd.isna(want):
            assert point.prediction is None and point.missing_reason == m.MissingReason.MISSING_INPUT
        else:
            assert point.prediction == want and point.missing_reason is None
        target = row[built.run.config.target_column]
        assert point.observed == (None if pd.isna(target) else target)
    assert (series.target, series.unit, series.horizon_hours) == ("y", "u", 6)


def test_series_window_and_pagination(client, built, monkeypatch):
    task = built.run.manifest.task_id
    window = get_ok(client, "/api/v1/series", m.SeriesResponse, task_id=task, entity_id="E0",
                    **{"from": T, "to": "2024-01-10T05:00:00Z"})
    assert [iso(p.issued_at_utc) for p in window.points] == [f"2024-01-10T0{h}:00:00Z" for h in range(5)]
    everything = get_ok(client, "/api/v1/series", m.SeriesResponse, task_id=task, entity_id="E0")

    monkeypatch.setattr(artifact_store, "SERIES_MAX_POINTS", 100)
    pages, cursor = [], None
    while True:
        page = get_ok(client, "/api/v1/series", m.SeriesResponse, task_id=task, entity_id="E0",
                      **({"cursor": cursor} if cursor else {}))
        pages.append(page)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert all(len(p.points) == 100 for p in pages[:-1]) and len(pages) > 2
    assert [p for page in pages for p in page.points] == everything.points


# ---------------------------------------------------------------------------- cache


def test_rule_map_cache_keys_and_lru(built, model_id, monkeypatch):
    one = approx_bytes(ArtifactStore(built.published_dir).rule_map(
        model_id, "R01", m.RuleMapMetric.ACTIVATION_FREQUENCY, None, T0, T0 + timedelta(days=2), 0.5))
    store = ArtifactStore(built.published_dir, cache_bytes=int(one * 2.5))  # room for two of these maps (B5)
    calls = []
    original = store._compute_rule_map
    monkeypatch.setattr(store, "_compute_rule_map", lambda *a: calls.append(a) or original(*a))
    window = (datetime(2024, 1, 10, tzinfo=timezone.utc), datetime(2024, 1, 12, tzinfo=timezone.utc))
    freq = m.RuleMapMetric.ACTIVATION_FREQUENCY

    first = store.rule_map(model_id, "R01", freq, None, *window, 0.5)
    assert store.rule_map(model_id, "R01", freq, None, *window, 0.5) is first and len(calls) == 1
    store.rule_map(model_id, "R01", freq, None, *window, 0.6)  # tau is part of the key
    store.rule_map(model_id, "R02", freq, None, *window, 0.5)  # so is the rule
    assert len(calls) == 3
    store.rule_map(model_id, "R01", freq, None, *window, 0.5)  # evicted (size 2): computed again
    assert len(calls) == 4
    store.rule_map(model_id, "R01", m.RuleMapMetric.MEAN_ACTIVATION, None, *window, None)  # so is the metric
    longer = (window[0], window[1] + timedelta(hours=1))
    store.rule_map(model_id, "R01", m.RuleMapMetric.MEAN_ACTIVATION, None, *longer, None)  # and the window
    assert len(calls) == 6


def test_republishing_invalidates_cached_state(built, model_id, tmp_path):
    published = tmp_path / "pub"
    args = (built.run.run_dir, built.root / "features.parquet", built.root / "entities.geojson",
            built.root / "feature_spec.json")
    publish_run(*args, "2024-01-05T00:00:00Z", "2024-02-14T23:00:00Z", published_dir=published, synthetic=True)
    store = ArtifactStore(published)
    window = (datetime(2024, 1, 10, tzinfo=timezone.utc), datetime(2024, 1, 31, tzinfo=timezone.utc))
    before = store.rule_map(model_id, "R01", m.RuleMapMetric.MEAN_ACTIVATION, None, *window, None)
    # publish a shorter period under the same model_id: the same query must not be served from the old cache
    publish_run(*args, "2024-01-20T00:00:00Z", "2024-02-14T23:00:00Z", published_dir=published, synthetic=True,
                replace=True)
    after = store.rule_map(model_id, "R01", m.RuleMapMetric.MEAN_ACTIVATION, None, *window, None)
    assert after is not before
    n_before = {f.id: f.properties.n_valid for f in before.features}
    n_after = {f.id: f.properties.n_valid for f in after.features}
    assert all(n_after[e] < n_before[e] for e in n_before)
    assert layout.read_registry(published).tasks[built.run.manifest.task_id].model_id == model_id


def test_a_tampered_published_model_is_not_unpickled(built, tmp_path):
    import shutil

    published = tmp_path / "pub"
    shutil.copytree(built.published_dir, published)
    model_id = built.run.manifest.model_id
    with open(published / model_id / "model.pkl", "ab") as fh:
        fh.write(b"x")
    client = TestClient(create_app(ArtifactStore(published)), raise_server_exceptions=False)
    assert client.get(f"/api/v1/models/{model_id}/rules").status_code == 200  # JSON views do not need the pickle
    with pytest.raises(ValueError, match="checksum mismatch"):
        TestClient(create_app(ArtifactStore(published))).get(
            "/api/v1/entities/E0/rule-trace", params={"model_id": model_id, "at": T})
