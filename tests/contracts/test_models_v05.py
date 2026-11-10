"""Contract v0.5: input labels, territories with several horizons, rule importance and the data summary."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from atlas.contracts import models as m
from atlas.services import layout

T0, T1 = datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc)


def importance(measure, rules, n_predicted, **extra):
    return m.RuleImportanceResponse(
        data_version="v", model_id="x", task_id="t", measure=measure, period_from_utc=T0, period_to_utc=T1,
        n_predicted=n_predicted, n_no_rule=0, rules=rules, variables=[], entities=[], **extra,
    )


def test_labels_and_territory_are_optional_and_additive():
    variable = m.LinguisticVariable(feature="no2_lag3h", terms=[m.LinguisticTerm(
        name="Buena", membership_type="trapezoidal", params=[0, 0, 40, 46])])
    assert variable.label is None and variable.description is None
    task = m.TaskInfo(task_id="madrid_no2_h6", target="no2", unit="ug/m3", horizon_hours=6, status="available")
    assert task.territory is None and task.territory_title is None
    meta = layout.PublishMetadata.model_validate({"features": {"no2_lag3h": {"label": "NO₂ hace 3 h"}}})
    assert meta.features["no2_lag3h"].label == "NO₂ hace 3 h"


def test_classifier_importance_decides_every_prediction_once():
    rules = [m.RuleImportance(rule_id="R01", n_decided=3, decided_share=0.75, n_checked=2, accuracy=0.5),
             m.RuleImportance(rule_id="R02", n_decided=1, decided_share=0.25, n_checked=1, accuracy=1.0)]
    assert importance(m.ImportanceMeasure.WINNING_RULE, rules, 4).n_predicted == 4
    with pytest.raises(ValidationError, match="exactly one rule"):
        importance(m.ImportanceMeasure.WINNING_RULE, rules, 5)
    with pytest.raises(ValidationError, match="n_checked"):
        importance(m.ImportanceMeasure.WINNING_RULE, [m.RuleImportance(
            rule_id="R01", n_decided=1, decided_share=1, n_checked=2)], 1)
    with pytest.raises(ValidationError, match="no weight share"):
        importance(m.ImportanceMeasure.WINNING_RULE, [m.RuleImportance(
            rule_id="R01", n_decided=1, decided_share=1, n_checked=1, mean_weight_share=1.0)], 1)


def test_regression_importance_shares_add_up_to_one():
    rules = [m.RuleImportance(rule_id="R01", n_decided=2, decided_share=1, n_checked=2, mean_weight_share=0.7, mae=0.4),
             m.RuleImportance(rule_id="R02", n_decided=0, decided_share=0, n_checked=0, mean_weight_share=0.3)]
    assert importance(m.ImportanceMeasure.WEIGHTED_AVERAGE, rules, 2).measure == "weighted_average"
    rules[1] = rules[1].model_copy(update={"mean_weight_share": 0.2})
    with pytest.raises(ValidationError, match="add up to 1"):
        importance(m.ImportanceMeasure.WEIGHTED_AVERAGE, rules, 2)
    with pytest.raises(ValidationError, match="no accuracy"):
        importance(m.ImportanceMeasure.WEIGHTED_AVERAGE, [m.RuleImportance(
            rule_id="R01", n_decided=1, decided_share=1, n_checked=1, accuracy=1.0, mean_weight_share=1.0)], 1)


def summary(classes, rows):
    return m.SummaryResponse(
        data_version="v", task_id="t", domain="air", variable="no2", label="NO₂", unit="ug/m3",
        timezone="Europe/Madrid", period_from_utc=T0, period_to_utc=T1, classes=classes, groups=rows,
    )


def test_summary_rows_match_the_kind_of_variable():
    classes = [m.TargetClass(label="Buena", lower=None, upper=40), m.TargetClass(label="Mala", lower=40, upper=None)]
    ok = {"all": [m.DistributionRow(key="all", n=10, shares=[0.7, 0.3])],
          "year": [m.DistributionRow(key="2025", n=0, shares=[0, 0])]}
    assert summary(classes, ok).groups[m.SummaryGroup.ALL][0].shares == [0.7, 0.3]
    with pytest.raises(ValidationError, match="add up to 1"):
        summary(classes, {"all": [m.DistributionRow(key="all", n=10, shares=[0.7, 0.2])]})
    with pytest.raises(ValidationError, match="one share per class"):
        summary(classes, {"all": [m.DistributionRow(key="all", n=10, shares=[1.0])]})
    numeric = {"all": [m.DistributionRow(key="all", n=5, quantiles={"p50": 9.1, "mean": 9.0})]}
    assert summary(None, numeric).classes is None
    with pytest.raises(ValidationError, match="quantiles"):
        summary(None, {"all": [m.DistributionRow(key="all", n=5)]})
    with pytest.raises(ValidationError, match="exactly one row"):
        summary(None, {"year": []})
