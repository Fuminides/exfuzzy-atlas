"""Contract v0.7 over a published mixture of rules: predictions name the top rule, traces carry the class scores,
what-if reruns the engine, importance has the top and decisive measures, and nothing says a rule decided."""

from __future__ import annotations

import os

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from atlas.contracts import models as m
from atlas.ml.exfuzzy_features import has_rule_mixture
from atlas.services import layout
from atlas_api.artifact_store import ArtifactStore
from atlas_api.main import create_app

pytestmark = pytest.mark.skipif(not has_rule_mixture() and not os.environ.get("CI"),
                                reason="needs ex_fuzzy with inference='mixture' (EXFUZZY_SRC, docs/reproduce.md)")


@pytest.fixture(scope="module")
def served(built_mixture):
    store = ArtifactStore(built_mixture.published_dir)
    model_id = built_mixture.run.manifest.model_id
    predictions = pd.read_parquet(built_mixture.model_dir / layout.PREDICTIONS_FILE)
    return store, TestClient(create_app(store)), model_id, built_mixture.run.manifest.task_id, predictions


def _at(stamp) -> str:
    return pd.Timestamp(stamp).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_rules_document_is_a_mixture(served):
    _, client, model_id, _, _ = served
    rules = m.ModelRules.model_validate(client.get(f"/api/v1/models/{model_id}/rules").json())
    assert rules.inference.family == m.InferenceFamily.RULE_MIXTURE_CLASSIFIER
    assert rules.class_bias is not None and all(r.class_weights_centred for r in rules.rules)


def test_predictions_carry_the_top_rule_and_agree_with_the_trace(served):
    store, client, model_id, task_id, predictions = served
    row = predictions[predictions["top_rule_id"].notna()].iloc[len(predictions) // 3]
    body = client.get("/api/v1/predictions", params={"task_id": task_id, "time": _at(row["issued_at_utc"])}).json()
    response = m.PredictionsResponse.model_validate(body)
    props = {f.id: f.properties for f in response.features}[row["entity_id"]]
    assert props.decided_by_rule_id is None and props.top_rule_id == row["top_rule_id"]
    trace = m.RuleTrace.model_validate(client.get(
        f"/api/v1/entities/{row['entity_id']}/rule-trace",
        params={"model_id": model_id, "at": _at(row["issued_at_utc"])}).json())
    assert trace.prediction.winning_rule_id is None
    assert trace.prediction.top_rule_id == props.top_rule_id
    assert trace.prediction.top_rule_share == pytest.approx(props.top_rule_share, abs=0)
    assert trace.prediction.label == props.prediction_label
    assert all(e.class_contributions is not None for e in trace.rules)


def test_what_if_reruns_the_engine(served):
    store, client, model_id, _, predictions = served
    row = predictions[predictions["top_rule_id"].notna()].iloc[0]
    low, high = next(v.domain for v in store.model_rules(model_id).variables if v.feature == "y_t")
    body = {"model_id": model_id, "entity_id": row["entity_id"], "at": _at(row["issued_at_utc"]),
            "overrides": {"y_t": high}}
    response = client.post("/api/v1/scenarios", json=body)
    assert response.status_code == 200, response.text
    scenario = m.ScenarioResponse.model_validate(response.json())
    assert scenario.modified.prediction.class_scores != scenario.original.prediction.class_scores
    assert scenario.prediction_change.original_winning_rule_id is None
    assert scenario.prediction_change.original_top_rule_id == scenario.original.prediction.top_rule_id
    assert all(d.association_delta is None for d in scenario.rule_deltas)


def test_winner_share_is_refused_and_activation_measures_work(served):
    _, client, model_id, _, predictions = served
    window = {"model_id": model_id, "from": _at(predictions["issued_at_utc"].min()),
              "to": _at(predictions["issued_at_utc"].max())}
    assert client.get("/api/v1/rule-territories", params={**window, "measure": "winner_share"}).status_code == 422
    ok = client.get("/api/v1/rule-territories", params={**window, "measure": "mean_activation"})
    assert ok.status_code == 200 and m.RuleTerritoriesResponse.model_validate(ok.json()).features


def test_importance_counts_top_rules_from_the_published_predictions(served):
    store, client, model_id, _, predictions = served
    response = m.RuleImportanceResponse.model_validate(client.get(f"/api/v1/models/{model_id}/importance").json())
    assert response.measure == m.ImportanceMeasure.RULE_MIXTURE
    labelled = predictions[predictions["prediction_label"].notna()]
    assert response.n_predicted == len(labelled)
    tops = labelled["top_rule_id"].value_counts()
    assert {r.rule_id: r.n_top for r in response.rules} == {r.rule_id: int(tops.get(r.rule_id, 0))
                                                            for r in response.rules}
    assert response.n_no_top_rule == int(labelled["top_rule_id"].isna().sum())
    assert all(r.decided_share is None for r in response.rules)


def test_publish_parity_of_the_mixture(built_mixture):
    from atlas.ml.publish_parity import check, check_tables

    result = check(built_mixture.model_dir)
    assert result["ok"], result
    assert check_tables(built_mixture.model_dir)["ok"]


def test_mock_api_serves_the_mixture_fixture():
    from atlas_api.mock_store import FixtureStore

    store = FixtureStore()
    mixture = [r for r in store.rules.values() if r.inference.family == m.InferenceFamily.RULE_MIXTURE_CLASSIFIER]
    assert len(mixture) == 1
    traces = [t for t in store.traces.values() if t.model_id == mixture[0].model_id]
    assert traces and any(t.prediction.top_rule_id for t in traces)
    assert store.importance(mixture[0].model_id).measure == m.ImportanceMeasure.RULE_MIXTURE


def test_a_winning_rule_and_a_mixture_classifier_are_served_side_by_side(built_class, built_mixture, tmp_path):
    """v0.7: one published directory, one domain, both families (NYC +6 h stays winning-rule next to mixtures)."""
    from atlas.ml.publish_parity import check
    from atlas.services.publish import publish_run

    published = tmp_path / "published"
    models = {}
    for built in (built_class, built_mixture):
        table = built.table
        summary = publish_run(built.run.run_dir, built.root / "features.parquet", built.root / "entities.geojson",
                              built.root / "feature_spec.json", table["issued_at_utc"].min() + pd.Timedelta(days=4),
                              table["issued_at_utc"].max(), published_dir=published, synthetic=True)
        models[built.run.manifest.task_id] = summary.model_dir
    client = TestClient(create_app(ArtifactStore(published)))
    air = next(d for d in client.get("/api/v1/domains").json()["domains"] if d["domain"] == "air")
    assert {t["task_id"] for t in air["tasks"]} == set(models)
    for task_id, model_dir in models.items():
        model_id = model_dir.name
        mixture = "mixture" in task_id
        rules = client.get(f"/api/v1/models/{model_id}/rules").json()
        assert rules["inference"]["family"] == ("rule_mixture_classifier" if mixture else "winning_rule_classifier")
        preds = pd.read_parquet(model_dir / layout.PREDICTIONS_FILE)
        row = preds[preds["prediction_label"].notna()].iloc[len(preds) // 2]
        body = client.get("/api/v1/predictions", params={"task_id": task_id, "time": _at(row["issued_at_utc"])}).json()
        props = {f["id"]: f["properties"] for f in body["features"]}[row["entity_id"]]
        assert (props["top_rule_id"] is not None or not mixture) and (props["decided_by_rule_id"] is None) == mixture
        trace = client.get(f"/api/v1/entities/{row['entity_id']}/rule-trace",
                           params={"model_id": model_id, "at": _at(row["issued_at_utc"])}).json()
        assert (trace["prediction"]["winning_rule_id"] is None) == mixture
        assert (trace["prediction"]["class_scores"] is not None) == mixture
        importance = client.get(f"/api/v1/models/{model_id}/importance").json()
        assert importance["measure"] == ("rule_mixture" if mixture else "winning_rule")
        assert check(model_dir)["ok"]
