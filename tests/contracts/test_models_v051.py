"""Contract v0.5.1 (CONTRACTS.md §13): term labels, translated class names, the rule that decided a prediction."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from atlas.contracts import models as m

T0 = datetime(2025, 1, 8, 7, tzinfo=timezone.utc)


def prediction_props(**overrides):
    base = dict(entity_id="E1", model_id="m", data_version="v", unit="u", issued_at_utc=T0,
                valid_at_utc=T0 + timedelta(hours=6), prediction=1.5, geometry_support="observed_point")
    return {**base, **overrides}


def test_v05_payloads_validate_without_the_new_fields():
    term = m.LinguisticTerm(name="<=L", membership_type="trapezoidal", params=[0.0, 0.0, 0.03, 0.0304])
    assert term.label is None
    cls = m.TargetClass(label="Good", lower=None, upper=10.0)
    assert cls.display_label is None
    assert m.PredictionProperties(**prediction_props(prediction=0.0)).decided_by_rule_id is None


def test_new_fields_round_trip():
    term = m.LinguisticTerm(name="<=L", label="≤ límite de detección", membership_type="trapezoidal",
                            params=[0.0, 0.0, 0.03, 0.0304])
    assert term.label == "≤ límite de detección"
    assert m.TargetClass(label="Good", display_label="Buena", lower=None, upper=10.0).display_label == "Buena"
    props = m.PredictionProperties(**prediction_props(prediction=None, prediction_label="high",
                                                      decided_by_rule_id="R04"))
    assert props.decided_by_rule_id == "R04"


def test_decided_by_rule_id_needs_a_prediction():
    with pytest.raises(ValidationError, match="needs a prediction"):
        m.PredictionProperties(**prediction_props(prediction=None, missing_reason="missing_input",
                                                  decided_by_rule_id="R04"))


def _importance(measure, **extra):
    t1 = T0 + timedelta(days=1)
    if measure == m.ImportanceMeasure.WINNING_RULE:
        rules = [m.RuleImportance(rule_id="R01", n_decided=2, decided_share=1.0, n_checked=2, accuracy=0.5)]
    else:
        rules = [m.RuleImportance(rule_id="R01", n_decided=2, decided_share=1.0, n_checked=2, mean_weight_share=1.0,
                                  mae=0.1)]
    return m.RuleImportanceResponse(data_version="v", model_id="x", task_id="t", measure=measure, period_from_utc=T0,
                                    period_to_utc=t1, n_predicted=2, n_no_rule=0, rules=rules, variables=[],
                                    entities=[], **extra)


def test_v052_observed_class_shares_are_optional_and_for_classifiers():
    assert _importance(m.ImportanceMeasure.WINNING_RULE).observed_class_shares is None
    shares = {"Buena": 0.75, "Regular": 0.25}
    assert _importance(m.ImportanceMeasure.WINNING_RULE, observed_class_shares=shares).observed_class_shares == shares
    with pytest.raises(ValidationError, match="add up to 1"):
        _importance(m.ImportanceMeasure.WINNING_RULE, observed_class_shares={"Buena": 0.5})
    with pytest.raises(ValidationError, match="for classifiers"):
        _importance(m.ImportanceMeasure.WEIGHTED_AVERAGE, observed_class_shares=shares)
