"""#51: a row without a reference level has no class in the series, so its rule trace must not name one either."""

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient

from atlas.contracts import models as m
from atlas.services import layout
from atlas.services.publish import publish_run
from atlas.services.synthetic import SCHEME
from atlas_api.artifact_store import ArtifactStore
from atlas_api.main import create_app

START, END = "2024-01-05T00:00:00Z", "2024-02-14T23:00:00Z"


@pytest.fixture(scope="module")
def served(built_class, tmp_path_factory):
    """The synthetic classifier republished with an observed-label column that is null on some observed rows."""
    table = built_class.table.copy()
    labels = np.array(SCHEME.labels, dtype=object)
    table["lvl"] = labels[(np.arange(len(table)) // 7) % 3]
    table.loc[table.index[::11], "lvl"] = None
    path = tmp_path_factory.mktemp("noref-features") / "features.parquet"
    table.to_parquet(path, index=False)
    out = tmp_path_factory.mktemp("noref-published")
    publish_run(
        built_class.run.run_dir, path, built_class.root / "entities.geojson", built_class.root / "feature_spec.json",
        START, END, published_dir=out, synthetic=True, observed_label_column="lvl")
    model_id = built_class.run.manifest.model_id
    preds = pq.read_table(out / model_id / layout.PREDICTIONS_FILE).to_pandas()
    return TestClient(create_app(ArtifactStore(out))), model_id, preds


def get_trace(client, model_id, entity, issued):
    at = pd.Timestamp(issued).strftime("%Y-%m-%dT%H:%M:%SZ")
    response = client.get(f"/api/v1/entities/{entity}/rule-trace", params={"model_id": model_id, "at": at})
    assert response.status_code == 200, response.text
    return m.RuleTrace.model_validate(response.json())  # runs the contract validator


def test_trace_of_a_row_without_reference_has_no_class_but_keeps_its_rules(served):
    client, model_id, preds = served
    unavailable = preds[(preds["prediction_label"].isna()) & (preds["missing_reason"] == "prediction_unavailable")]
    assert len(unavailable) > 0
    withheld = 0
    for _, row in unavailable.head(60).iterrows():
        t = get_trace(client, model_id, row["entity_id"], row["issued_at_utc"])
        assert t.prediction.label is None and t.prediction.winning_rule_id is None
        assert t.prediction.missing_reason == m.MissingReason.PREDICTION_UNAVAILABLE
        assert len(t.rules) > 0
        if t.quality.status == m.QualityStatus.WARNING:  # the engine had a class; the table withholds it
            withheld += 1
            assert "no reference level" in t.quality.warnings[-1]
            # the rule firings and associations are the engine's own outputs, still listed
            assert any(r.firing_strength > 0 and r.association_degree > 0 for r in t.rules)
    assert withheld > 0


def test_trace_of_a_row_with_a_label_is_unchanged(served):
    client, model_id, preds = served
    answered = preds[preds["prediction_label"].notna()]
    assert len(answered) > 0
    for _, row in answered.head(5).iterrows():
        t = get_trace(client, model_id, row["entity_id"], row["issued_at_utc"])
        assert t.prediction.label == row["prediction_label"]
        assert t.prediction.winning_rule_id is not None and t.prediction.missing_reason is None
        assert t.quality.status == m.QualityStatus.VALID


def test_series_and_trace_agree_on_every_sampled_row(served):
    client, model_id, preds = served
    for _, row in preds.sample(30, random_state=0).iterrows():
        t = get_trace(client, model_id, row["entity_id"], row["issued_at_utc"])
        series_label = None if pd.isna(row["prediction_label"]) else row["prediction_label"]
        if row["missing_reason"] == "missing_input":
            assert t.prediction.missing_reason == m.MissingReason.MISSING_INPUT
        assert t.prediction.label == series_label


def test_a_scenario_on_a_row_without_reference_keeps_the_class_withheld_in_both_traces(served):
    """v0.4: a what-if must not name a class for a row the series withholds; rules stay the engine's."""
    client, model_id, preds = served
    unavailable = preds[(preds["prediction_label"].isna()) & (preds["missing_reason"] == "prediction_unavailable")]
    for _, row in unavailable.head(40).iterrows():
        original = get_trace(client, model_id, row["entity_id"], row["issued_at_utc"])
        if original.quality.status != m.QualityStatus.WARNING or not original.rules:
            continue
        at = pd.Timestamp(row["issued_at_utc"]).strftime("%Y-%m-%dT%H:%M:%SZ")
        response = client.post("/api/v1/scenarios", json={
            "model_id": model_id, "entity_id": row["entity_id"], "at": at, "overrides": {}})
        assert response.status_code == 200, response.text
        scenario = m.ScenarioResponse.model_validate(response.json())
        assert scenario.original == original and scenario.modified == original
        assert scenario.modified.prediction.label is None and scenario.prediction_change.label_changed is None
        assert all(d.association_delta == 0 for d in scenario.rule_deltas)
        return
    pytest.fail("no withheld row with rules found")
