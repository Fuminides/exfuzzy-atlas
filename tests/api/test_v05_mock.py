"""Contract v0.5 in mock mode: importance and summary fixtures for the toy regressor and a synthetic classifier."""

import pytest
from fastapi.testclient import TestClient

from atlas.contracts import models as m
from atlas_api.main import app

client = TestClient(app)
REGRESSOR, CLASSIFIER = "synthetic-no2-h6-v0", "exfuzzy-synthetic_class_h6-synthetic-class-seed3"


def get_ok(path, model, **params):
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    return model.model_validate(response.json())


def test_the_toy_regressor_has_its_importance_and_every_rule_and_input_is_listed():
    importance = get_ok(f"/api/v1/models/{REGRESSOR}/importance", m.RuleImportanceResponse)
    rules = get_ok(f"/api/v1/models/{REGRESSOR}/rules", m.ModelRules)
    assert importance.synthetic and importance.measure == m.ImportanceMeasure.WEIGHTED_AVERAGE
    assert [r.rule_id for r in importance.rules] == [r.rule_id for r in rules.rules]
    assert [v.feature for v in importance.variables] == [v.feature for v in rules.variables]
    assert importance.n_predicted + importance.n_no_rule + 1 == 24  # 24 rows, one with a missing input
    assert sum(r.mean_weight_share for r in importance.rules) == pytest.approx(1.0)
    assert [v.label for v in rules.variables] == [
        "NO₂ en la emisión (inventado)", "Viento en la emisión (m/s, inventado)"]


def test_the_synthetic_classifier_has_importance_rules_and_accuracy():
    importance = get_ok(f"/api/v1/models/{CLASSIFIER}/importance", m.RuleImportanceResponse)
    rules = get_ok(f"/api/v1/models/{CLASSIFIER}/rules", m.ModelRules)
    assert importance.measure == m.ImportanceMeasure.WINNING_RULE and importance.n_no_rule > 0
    assert [r.rule_id for r in importance.rules] == [r.rule_id for r in rules.rules]
    assert any(r.accuracy is not None for r in importance.rules)
    assert all(v.label for v in rules.variables if v.feature in {x.feature for x in importance.variables})


def test_summaries_of_both_tasks_one_numeric_and_one_in_classes():
    numeric = get_ok("/api/v1/summary", m.SummaryResponse, task_id="madrid_no2_h6")
    classed = get_ok("/api/v1/summary", m.SummaryResponse, task_id="synthetic_class_h6")
    assert numeric.classes is None and numeric.groups[m.SummaryGroup.ALL][0].quantiles is not None
    assert classed.classes is not None and classed.groups[m.SummaryGroup.ALL][0].shares is not None
    assert numeric.synthetic and classed.synthetic
    for summary in (numeric, classed):
        assert set(summary.groups) == set(m.SummaryGroup)


def test_domains_carry_the_territory_and_unknown_ids_are_404():
    tasks = [t for d in client.get("/api/v1/domains").json()["domains"] for t in d["tasks"]]
    assert tasks[0]["territory"] == "madrid" and tasks[0]["territory_title"]
    assert client.get("/api/v1/models/nope/importance").status_code == 404
    assert client.get("/api/v1/summary", params={"task_id": "nope"}).status_code == 404
