"""Contract invariants from CONTRACTS.md §5-6 and MAP_EXPERIENCE.md §4."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from atlas.contracts import models as m

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic"
T0 = datetime(2025, 1, 15, 6, tzinfo=timezone.utc)


def rule_map_props(**overrides):
    base = dict(
        entity_id="E1", rule_id="R01", metric="firing_strength", value=0.4, n_valid=1,
        time_from_utc=T0, time_to_utc=T0, issued_at_utc=T0, model_id="m", data_version="v",
        geometry_support="observed_point",
    )
    return {**base, **overrides}


def first_trace():
    traces = json.loads((FIXTURES / "rule_traces.json").read_text())
    return next(t for t in traces if t["rules"])


def test_zero_is_a_value_and_null_needs_a_reason():
    assert m.RuleMapProperties(**rule_map_props(value=0.0)).value == 0.0
    with pytest.raises(ValidationError, match="missing_reason is required"):
        m.RuleMapProperties(**rule_map_props(value=None, n_valid=0))
    with pytest.raises(ValidationError, match="must be null when value is present"):
        m.RuleMapProperties(**rule_map_props(missing_reason="no_observation"))
    missing = m.RuleMapProperties(**rule_map_props(value=None, n_valid=0, missing_reason="missing_input"))
    assert missing.value is None


def test_firing_is_bounded_and_single_record():
    with pytest.raises(ValidationError):
        m.RuleMapProperties(**rule_map_props(value=1.2))
    with pytest.raises(ValidationError, match="single-record"):
        m.RuleMapProperties(**rule_map_props(n_valid=3))
    with pytest.raises(ValidationError, match="n_valid >= 1"):
        m.RuleMapProperties(**rule_map_props(metric="mean_activation", n_valid=0, issued_at_utc=None))


def test_tau_only_for_activation_frequency():
    window = dict(issued_at_utc=None, time_to_utc=T0 + timedelta(hours=6), n_valid=6)
    assert m.RuleMapProperties(**rule_map_props(metric="activation_frequency", tau=0.5, **window)).tau == 0.5
    with pytest.raises(ValidationError, match="tau"):
        m.RuleMapProperties(**rule_map_props(metric="activation_frequency", **window))
    with pytest.raises(ValidationError, match="tau"):
        m.RuleMapProperties(**rule_map_props(tau=0.5))


def test_estimated_surface_is_rejected():
    with pytest.raises(ValidationError):
        m.RuleMapProperties(**rule_map_props(geometry_support="estimated_surface"))


def test_point_support_needs_point_geometry():
    square = {"type": "Polygon", "coordinates": [[(0, 0), (1, 0), (1, 1), (0, 0)]]}
    with pytest.raises(ValidationError, match="does not match geometry_support"):
        m.RuleMapFeature(type="Feature", id="E1", geometry=square, properties=rule_map_props())


def test_timestamps_must_be_utc():
    madrid = timezone(timedelta(hours=1))
    with pytest.raises(ValidationError, match="UTC"):
        m.RuleMapProperties(**rule_map_props(issued_at_utc=T0.astimezone(madrid)))
    with pytest.raises(ValidationError):
        m.RuleMapProperties(**rule_map_props(issued_at_utc=T0.replace(tzinfo=None)))


def test_trace_rejects_firing_that_is_not_the_model_tnorm():
    trace = first_trace()
    m.RuleTrace.model_validate(trace)
    multi = next(r for r in trace["rules"] if len(r["antecedents"]) > 1 or r["firing_strength"] > 0)
    multi["firing_strength"] = min(1.0, multi["firing_strength"] + 0.1)
    multi["effective_firing"] = multi["firing_strength"]
    with pytest.raises(ValidationError, match="t-norm"):
        m.RuleTrace.model_validate(trace)


def test_trace_rejects_future_inputs():
    trace = first_trace()
    trace["feature_values"][0]["observed_at_utc"] = "2025-01-15T23:00:00Z"
    with pytest.raises(ValidationError, match="future information"):
        m.RuleTrace.model_validate(trace)


def test_prediction_valid_time_never_precedes_issue_time():
    record = dict(data_version="v", domain="air", task_id="t", entity_id="E1", issued_at_utc=T0,
                  target="no2", unit="ug/m3", prediction=10.0, model_id="m")
    m.PredictionRecord(valid_at_utc=T0, **record)  # horizon 0: same-time inference (water)
    with pytest.raises(ValidationError, match="must not precede"):
        m.PredictionRecord(valid_at_utc=T0 - timedelta(hours=1), **record)


def test_split_must_be_chronological_with_embargo():
    def split(**kw):
        days = {k: T0 + timedelta(days=v) for k, v in kw.items()}
        return m.SplitSpec(embargo_hours=24, **days)

    split(train_from_utc=0, train_to_utc=10, test_from_utc=11, test_to_utc=20)
    with pytest.raises(ValidationError, match="embargo"):
        split(train_from_utc=0, train_to_utc=10, test_from_utc=10, test_to_utc=20)
    with pytest.raises(ValidationError, match="embargo"):
        split(train_from_utc=11, train_to_utc=20, test_from_utc=0, test_to_utc=10)


def test_model_rules_reject_unknown_terms():
    rules = json.loads((FIXTURES / "model_rules.json").read_text())
    rules["rules"][0]["antecedents"][0]["term"] = "Extreme"
    with pytest.raises(ValidationError, match="unknown term"):
        m.ModelRules.model_validate(rules)


def test_duplicate_of_must_name_an_earlier_rule():
    rules = json.loads((FIXTURES / "model_rules.json").read_text())
    rules["rules"][2]["duplicate_of"] = "R01"
    assert m.ModelRules.model_validate(rules).rules[2].duplicate_of == "R01"
    rules["rules"][0]["duplicate_of"] = "R03"
    with pytest.raises(ValidationError, match="earlier rule"):
        m.ModelRules.model_validate(rules)


def test_variable_domain_is_ordered():
    term = {"name": "Low", "membership_type": "trapezoidal", "params": [0, 0, 1, 2]}
    assert m.LinguisticVariable(feature="x", domain=(0, 10), terms=[term]).domain == (0, 10)
    with pytest.raises(ValidationError, match="min < max"):
        m.LinguisticVariable(feature="x", domain=(10, 0), terms=[term])


# ------------------------------------------------------------------ v0.3: classification

ICA_LIKE = {
    "name": "test scheme", "source_url": "https://example.org/scheme", "unit": "ug/m3",
    "classes": [
        {"label": "Buena", "lower": 0, "upper": 40, "color": "#50F0E6"},
        {"label": "Regular", "lower": 40, "upper": 120},
        {"label": "Desfavorable o peor", "lower": 120, "upper": None},
    ],
}


def classifier_inference(**kw):
    base = dict(family="winning_rule_classifier", tnorm="product", fallback="unknown",
                rule_weighting="dominance_score", allow_unknown=True, exfuzzy_version="3.3.1")
    return {**base, **kw}


def classifier_trace(winning="R02", label="Regular", weights=(0.5, 0.9)):
    entries = []
    for rid, mu, w in [("R01", 0.8, weights[0]), ("R02", 0.6, weights[1])]:
        entries.append({
            "rule_id": rid, "antecedents": [{"feature": "x", "term": "High", "membership": mu,
                                             "effective_membership": mu}],
            "firing_strength": mu, "effective_firing": mu, "weight": w, "association_degree": mu * w,
        })
    return {
        "data_version": "v", "model_id": "m", "task_id": "t", "entity_id": "E1",
        "issued_at_utc": T0, "valid_at_utc": T0 + timedelta(hours=6), "inference": classifier_inference(),
        "feature_values": [{"feature": "x", "value": 1.0}], "rules": entries,
        "prediction": {"value": None, "label": label, "winning_rule_id": winning, "unit": "ug/m3",
                       "fallback_used": False},
    }


def test_target_scheme_must_be_ordered_and_contiguous():
    assert len(m.TargetScheme.model_validate(ICA_LIKE).classes) == 3
    gap = json.loads(json.dumps(ICA_LIKE))
    gap["classes"][1]["lower"] = 50
    with pytest.raises(ValidationError, match="contiguous"):
        m.TargetScheme.model_validate(gap)


def test_inference_spec_families():
    m.InferenceSpec.model_validate(classifier_inference())
    with pytest.raises(ValidationError, match="classifier needs"):
        m.InferenceSpec.model_validate(classifier_inference(rule_weighting=None))
    with pytest.raises(ValidationError, match="TSK/Mamdani need rule_mode"):
        m.InferenceSpec(family="tsk_zero_order", tnorm="product", fallback="train_target_mean",
                        exfuzzy_version="3.3.1")


def test_classifier_trace_names_the_argmax_rule():
    # R01: 0.8 x 0.5 = 0.40; R02: 0.6 x 0.9 = 0.54 -> R02 decides even though R01 fires more.
    assert m.RuleTrace.model_validate(classifier_trace()).prediction.winning_rule_id == "R02"
    with pytest.raises(ValidationError, match="largest positive association_degree"):
        m.RuleTrace.model_validate(classifier_trace(winning="R01"))


def test_classifier_trace_checks_association_parity():
    trace = classifier_trace()
    trace["rules"][1]["association_degree"] = 0.3
    with pytest.raises(ValidationError, match="association_degree != firing_strength x weight"):
        m.RuleTrace.model_validate(trace)


def test_classifier_rules_need_scheme_labels():
    rule = {"rule_id": "R01", "position": 0, "antecedents": [{"feature": "x", "term": "High"}],
            "consequent": {"type": "class", "term": "Regular"}, "text": "IF x IS High THEN Regular", "weight": 0.7}
    payload = {"data_version": "v", "model_id": "m", "task_id": "t", "domain": "air",
               "inference": classifier_inference(), "target_scheme": ICA_LIKE,
               "variables": [{"feature": "x", "terms": [{"name": "High", "membership_type": "trapezoidal",
                                                          "params": [0, 1, 2, 3]}]}], "rules": [rule]}
    m.ModelRules.model_validate(payload)
    payload["rules"][0]["consequent"]["term"] = "Muy mala"
    with pytest.raises(ValidationError, match="class of target_scheme"):
        m.ModelRules.model_validate(payload)


def test_labels_count_as_predictions_and_horizon_zero_is_allowed():
    point = m.SeriesPoint(issued_at_utc=T0, valid_at_utc=T0, observed=30.0, prediction=None,
                          observed_label="Buena", predicted_label="Regular")
    assert point.predicted_label == "Regular"
    with pytest.raises(ValidationError, match="missing_reason is required"):
        m.SeriesPoint(issued_at_utc=T0, valid_at_utc=T0, observed=None, prediction=None)
    m.SeriesResponse(data_version="v", task_id="t", entity_id="E1", model_id="m", target="do", unit="mg/l",
                     horizon_hours=0, points=[point])
