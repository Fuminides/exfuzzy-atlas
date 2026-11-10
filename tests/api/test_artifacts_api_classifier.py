"""API in artifacts mode over a published synthetic classifier: contract, parity, labels, no class index as a number."""

import shutil
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from atlas.contracts import models as m
from atlas.services.publish import publish_run
from atlas.services.synthetic import SCHEME
from atlas_api.artifact_store import ArtifactStore
from atlas_api.main import create_app

T0 = datetime(2024, 1, 10, 0, tzinfo=timezone.utc)
HOURS = [T0 + timedelta(hours=h) for h in (0, 5, 11, 40)]
ENTITIES = ("E0", "E1", "E2")


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture(scope="module")
def client(built_class):
    return TestClient(create_app(ArtifactStore(built_class.published_dir)))


@pytest.fixture(scope="module")
def model_id(built_class):
    return built_class.run.manifest.model_id


@pytest.fixture(scope="module")
def firing(built_class):
    frame = pq.read_table(built_class.model_dir / "activations").to_pandas()
    return frame.astype({"entity_id": str, "rule_id": str})


def get_ok(client, path, model, **params):
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    return model.model_validate(response.json())


def trace(client, model_id, entity, at):
    return get_ok(client, f"/api/v1/entities/{entity}/rule-trace", m.RuleTrace, model_id=model_id, at=iso(at))


def test_every_classifier_payload_validates(client, built_class, model_id):
    task = built_class.run.manifest.task_id
    window = {"from": iso(T0), "to": iso(T0 + timedelta(days=2))}
    payloads = [
        get_ok(client, "/api/v1/domains", m.DomainsResponse),
        get_ok(client, "/api/v1/entities", m.EntityCollection, domain="air"),
        get_ok(client, f"/api/v1/models/{model_id}", m.ModelCard),
        get_ok(client, f"/api/v1/models/{model_id}/rules", m.ModelRules),
        get_ok(client, "/api/v1/series", m.SeriesResponse, task_id=task, entity_id="E0"),
        get_ok(client, "/api/v1/rule-map", m.RuleMapResponse, model_id=model_id, rule_id="R01",
               metric="firing_strength", time=iso(T0)),
        get_ok(client, "/api/v1/rule-map", m.RuleMapResponse, model_id=model_id, rule_id="R01",
               metric="mean_activation", **window),
        get_ok(client, "/api/v1/rule-map", m.RuleMapResponse, model_id=model_id, rule_id="R01",
               metric="activation_frequency", tau=0.5, **window),
        trace(client, model_id, "E0", T0),
    ]
    assert all(p.synthetic for p in payloads)


def test_domains_card_and_rules_describe_a_classifier(client, built_class, model_id):
    domains = get_ok(client, "/api/v1/domains", m.DomainsResponse)
    task = {d.domain: d for d in domains.domains}[m.Domain.AIR].tasks[0]
    assert (task.task_id, task.task_type, task.model_id, task.status) == (
        built_class.run.manifest.task_id, "classification", model_id, "available")
    card = get_ok(client, f"/api/v1/models/{model_id}", m.ModelCard)
    assert card.target_scheme == built_class.run.rules.target_scheme == SCHEME.to_target_scheme()
    assert [c.color for c in card.target_scheme.classes] == ["#00FFFF", "#FFCC00", "#FF3300"]
    rules = get_ok(client, f"/api/v1/models/{model_id}/rules", m.ModelRules)
    assert rules.inference.family == m.InferenceFamily.WINNING_RULE_CLASSIFIER
    assert rules.rules == built_class.run.rules.rules
    assert {r.consequent.type for r in rules.rules} == {"class"} and all(r.weight is not None for r in rules.rules)
    assert {r.consequent.term for r in rules.rules} <= set(SCHEME.labels)


def test_map_value_equals_trace_equals_firing_table(client, model_id, firing, built_class):
    checked = 0
    for t in HOURS:
        at = firing[firing["issued_at_utc"] == pd.Timestamp(t)]
        traces = {e: trace(client, model_id, e, t) for e in ENTITIES}
        for rule in built_class.run.rules.rules:
            response = client.get("/api/v1/rule-map", params={
                "model_id": model_id, "rule_id": rule.rule_id, "metric": "firing_strength", "time": iso(t)})
            assert response.status_code == 200
            got = {f["id"]: f["properties"]["value"] for f in response.json()["features"]}
            for entity, tr in traces.items():
                row = at[(at["entity_id"] == entity) & (at["rule_id"] == rule.rule_id)]
                assert len(row) == 1
                table_value = row["firing_strength"].iloc[0]
                entry = [r for r in tr.rules if r.rule_id == rule.rule_id]
                if pd.isna(table_value):
                    assert got[entity] is None and not entry
                else:
                    assert got[entity] == pytest.approx(table_value, abs=1e-12)
                    assert entry[0].firing_strength == pytest.approx(table_value, abs=1e-12)
                    assert entry[0].association_degree == pytest.approx(row["association_degree"].iloc[0], abs=1e-12)
                    assert entry[0].weight == pytest.approx(row["weight"].iloc[0], abs=1e-12)
                    checked += 1
    assert checked >= 3 * len(built_class.run.rules.rules)


def test_trace_winner_and_label_equal_predict_labels_and_the_table(client, model_id, firing, built_class):
    run = built_class.run
    inputs = pq.read_table(built_class.model_dir / "inputs.parquet").to_pandas()
    labelled = 0
    for t in HOURS:
        for entity in ENTITIES:
            tr = trace(client, model_id, entity, t)
            row = inputs[(inputs["entity_id"] == entity) & (inputs["issued_at_utc"] == pd.Timestamp(t))]
            expected = run.model.predict_labels(row[run.config.features])[0]
            assert tr.prediction.label == expected and tr.prediction.value is None
            winners = firing[(firing["entity_id"] == entity) & (firing["issued_at_utc"] == pd.Timestamp(t))
                             & firing["is_winner"]]["rule_id"].tolist()
            assert winners == ([] if expected is None else [tr.prediction.winning_rule_id])
            if expected is None:
                assert tr.prediction.missing_reason in (m.MissingReason.PREDICTION_UNAVAILABLE,
                                                        m.MissingReason.MISSING_INPUT)
            else:
                labelled += 1
                assert expected in SCHEME.labels
    assert labelled > 0


def test_trace_fills_provenance_from_the_feature_spec(client, model_id, built_class):
    tr = trace(client, model_id, "E1", T0 + timedelta(hours=3))
    lags = {fv.feature: fv for fv in tr.feature_values}
    assert lags["y_lag3"].observed_at_utc == tr.issued_at_utc - timedelta(hours=3)
    assert lags["y_lag3"].source_id == "synthetic-y_lag3"


def test_series_labels_equal_the_predictions_and_prediction_is_null(client, built_class):
    run, task = built_class.run, built_class.run.manifest.task_id
    inputs = pq.read_table(built_class.model_dir / "inputs.parquet").to_pandas()
    for entity in ENTITIES:
        series = get_ok(client, "/api/v1/series", m.SeriesResponse, task_id=task, entity_id=entity)
        rows = inputs[inputs["entity_id"] == entity].sort_values("issued_at_utc")
        assert len(series.points) == len(rows)
        expected = run.model.predict_labels(rows[run.config.features])
        assert [p.predicted_label for p in series.points] == list(expected)
        assert all(p.prediction is None for p in series.points)  # a class index is never a number
        for p, label in zip(series.points, expected, strict=True):
            assert (p.missing_reason is None) == (label is not None)
        truth = built_class.table[built_class.table["entity_id"] == entity].set_index("issued_at_utc")
        for p in series.points[:200]:
            observed = truth.loc[p.issued_at_utc, run.config.target_column]
            if np.isnan(observed):
                assert p.observed is None and p.observed_label is None
            else:
                assert p.observed == pytest.approx(observed)
                index = SCHEME.classify([observed])[0]
                assert p.observed_label == (None if index < 0 else SCHEME.labels[index])
        assert any(p.predicted_label is not None for p in series.points)
        assert {p.observed_label for p in series.points} - {None} <= set(SCHEME.labels)


def test_a_classifier_and_a_regressor_are_served_side_by_side(built, built_class, tmp_path):
    shutil.copytree(built.published_dir, tmp_path / "pub")
    publish_run(
        built_class.run.run_dir, built_class.root / "features.parquet", built_class.root / "entities.geojson",
        built_class.root / "feature_spec.json", "2024-01-05T00:00:00Z", "2024-02-14T23:00:00Z",
        published_dir=tmp_path / "pub", synthetic=True)
    client = TestClient(create_app(ArtifactStore(tmp_path / "pub")))
    domains = get_ok(client, "/api/v1/domains", m.DomainsResponse)
    air = {d.domain: d for d in domains.domains}[m.Domain.AIR]
    assert {t.task_id: t.task_type for t in air.tasks} == {
        built.run.manifest.task_id: "regression", built_class.run.manifest.task_id: "classification"}
    regression = get_ok(client, "/api/v1/series", m.SeriesResponse, task_id=built.run.manifest.task_id,
                        entity_id="E0")
    assert all(p.predicted_label is None and p.observed_label is None for p in regression.points)
    assert any(p.prediction is not None for p in regression.points)
