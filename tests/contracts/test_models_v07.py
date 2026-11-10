"""Contract v0.7 (CONTRACTS.md §18): the mixture-of-rules classifier, its rules, traces, predictions and importance."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from atlas.contracts import models as m

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic"
T0 = datetime(2025, 1, 8, 7, tzinfo=timezone.utc)
LABELS = ["low", "mid", "high"]
SCHEME = m.TargetScheme(name="bands", source_url="https://example.org", unit="u", boundary="upper_inclusive", classes=[
    m.TargetClass(label="low", lower=None, upper=10), m.TargetClass(label="mid", lower=10, upper=20),
    m.TargetClass(label="high", lower=20, upper=None)])
SPEC = dict(family="rule_mixture_classifier", tnorm="product", fallback="unknown", allow_unknown=True,
            mixture_weights="unconstrained", mixture_C=1.0, exfuzzy_version="3.3.1+g20c1095")
WEIGHTS = {"R01": [1.5, 0.5, -2.0], "R02": [-0.5, 0.25, 0.25]}
BIAS = [0.1, 0.2, -0.3]


def _centred(w):
    mean = sum(w) / len(w)
    return [v - mean for v in w]


def _rule(rule_id, position, weights, **update):
    w = dict(zip(LABELS, weights, strict=True))
    strongest = None if max(weights) == min(weights) else LABELS[weights.index(max(weights))]
    body = dict(rule_id=rule_id, position=position, text="IF x IS Low: weights",
                antecedents=[m.Antecedent(feature="x", term="Low")], consequent=m.Consequent(type="class", term="low"),
                class_weights=w, class_weights_centred=dict(zip(LABELS, _centred(weights), strict=True)),
                strongest_class=strongest)
    body.update(update)
    return m.RuleDefinition(**body)


def _rules(**update):
    body = dict(
        data_version="v", model_id="mix", task_id="t", domain=m.Domain.AIR, inference=m.InferenceSpec(**SPEC),
        target_scheme=SCHEME,
        variables=[m.LinguisticVariable(feature="x", terms=[
            m.LinguisticTerm(name="Low", membership_type="trapezoidal", params=[0, 0, 1, 2])])],
        rules=[_rule(r, k, w) for k, (r, w) in enumerate(WEIGHTS.items())],
        class_bias=dict(zip(LABELS, BIAS, strict=True)))
    body.update(update)
    return m.ModelRules(**body)


def _trace(firing=(0.8, 0.4), **prediction):
    entries, scores, centred_sums = [], list(BIAS), []
    for (rule_id, w), f in zip(WEIGHTS.items(), firing, strict=True):
        entries.append(m.RuleTraceEntry(
            rule_id=rule_id, antecedents=[m.AntecedentTrace(feature="x", term="Low", membership=f,
                                                            effective_membership=f)],
            firing_strength=f, effective_firing=f, class_weights=dict(zip(LABELS, w, strict=True)),
            class_contributions=dict(zip(LABELS, [v * f for v in w], strict=True)),
            class_contributions_centred=dict(zip(LABELS, [v * f for v in _centred(w)], strict=True))))
        scores = [s + v * f for s, v in zip(scores, w, strict=True)]
        centred_sums.append([v * f for v in _centred(w)])
    label = LABELS[scores.index(max(scores))] if any(firing) else None
    support = [c[LABELS.index(label)] for c in centred_sums] if label else []
    top = m.top_contributor(support) if label else None
    body = dict(value=None, label=label, unit="u", fallback_used=not any(firing),
                missing_reason=None if label else m.MissingReason.PREDICTION_UNAVAILABLE,
                class_scores=dict(zip(LABELS, scores, strict=True)), class_bias=dict(zip(LABELS, BIAS, strict=True)),
                top_rule_id=None if top is None else list(WEIGHTS)[top],
                top_rule_share=None if top is None else support[top] / sum(v for v in support if v > 0))
    body.update(prediction)
    return dict(data_version="v", model_id="mix", task_id="t", entity_id="E0", issued_at_utc=T0,
                valid_at_utc=T0 + timedelta(hours=6), inference=m.InferenceSpec(**SPEC),
                feature_values=[m.FeatureValue(feature="x", value=0.5)], rules=entries,
                prediction=m.TracePrediction(**body))


def test_v061_payloads_still_validate():
    assert m.SCHEMA_VERSION == "0.7.0"
    m.ModelRules.model_validate_json((FIXTURES / "model_rules.json").read_text())
    regression = m.InferenceFamily.TSK_ZERO_ORDER
    for item in json.loads((FIXTURES / "model_rules_extra.json").read_text()):
        assert m.ModelRules.model_validate(item).inference.family in m.CLASSIFIER_FAMILIES
    for item in json.loads((FIXTURES / "rule_traces.json").read_text()):
        trace = m.RuleTrace.model_validate(item)
        assert trace.inference.family == regression and trace.prediction.class_scores is None
    for item in json.loads((FIXTURES / "importance.json").read_text()):
        response = m.RuleImportanceResponse.model_validate(item)
        if response.measure != m.ImportanceMeasure.RULE_MIXTURE:  # the measures of v0.5 are unchanged
            assert all(r.decided_share is not None and r.top_contributor_share is None for r in response.rules)
            assert response.n_no_top_rule is None


def test_inference_spec_of_the_mixture():
    spec = m.InferenceSpec(**SPEC)
    assert spec.rule_weighting is None and spec.rule_mode is None
    assert m.InferenceSpec(**{**SPEC, "allow_unknown": False, "fallback": "largest_bias"}).fallback == "largest_bias"
    for bad in ({"fallback": "largest_bias"}, {"mixture_weights": None}, {"mixture_C": None},
                {"rule_weighting": "dominance_score"}, {"mixture_C": 0.0}):
        with pytest.raises(ValidationError):
            m.InferenceSpec(**{**SPEC, **bad})
    with pytest.raises(ValidationError, match="mixture only"):  # winning rule cannot carry mixture fields
        m.InferenceSpec(family="winning_rule_classifier", tnorm="product", fallback="unknown",
                        rule_weighting="none", allow_unknown=True, mixture_C=1.0, exfuzzy_version="x")


def test_rules_carry_signed_weights_centred_weights_strongest_class_and_bias():
    rules = _rules()
    assert rules.rules[0].class_weights["high"] == -2.0  # signed: the v0.3 `weight` (>= 0) could not hold it
    assert rules.rules[0].weight is None and rules.rules[0].strongest_class == "low"
    assert rules.rules[1].class_weights_centred == pytest.approx({"low": -0.5, "mid": 0.25, "high": 0.25})
    assert rules.rules[1].strongest_class == "mid"  # first of the largest weight in scheme order
    with pytest.raises(ValidationError, match="class_bias"):
        _rules(class_bias=None)
    with pytest.raises(ValidationError, match="scheme order"):
        _rules(class_bias={"mid": 0.2, "low": 0.1, "high": -0.3})
    with pytest.raises(ValidationError, match="centred"):
        _rules(rules=[_rule("R01", 0, [1.0, 0.0, 0.0], class_weights_centred={"low": 1.0, "mid": 0.0, "high": 0.0})])
    with pytest.raises(ValidationError, match="strongest_class"):
        _rules(rules=[_rule("R01", 0, [1.0, 0.0, 0.0], strongest_class="mid")])
    with pytest.raises(ValidationError, match="not weight"):
        _rules(rules=[_rule("R01", 0, [1.0, 0.0, 0.0], weight=1.0)])
    with pytest.raises(ValidationError, match="cannot be negative"):
        _rules(inference=m.InferenceSpec(**{**SPEC, "mixture_weights": "non_negative"}))
    zeros = _rule("R02", 1, [0.0, 0.0, 0.0], duplicate_of="R01")
    assert _rules(rules=[_rule("R01", 0, [1.0, 0.0, 0.0]), zeros]).rules[1].strongest_class is None
    with pytest.raises(ValidationError, match="all-zero"):
        _rules(rules=[_rule("R01", 0, [1.0, 0.0, 0.0]), _rule("R02", 1, [1.0, 0.0, 0.0], duplicate_of="R01")])
    with pytest.raises(ValidationError, match="mixture only"):  # a winning-rule document cannot carry them
        m.ModelRules.model_validate({**json.loads((FIXTURES / "model_rules.json").read_text()),
                                     "class_bias": {"a": 0.0}})


def test_trace_contributions_scores_label_and_top_rule():
    trace = m.RuleTrace(**_trace())
    p = trace.prediction
    assert p.winning_rule_id is None and p.label == "low" and p.top_rule_id == "R01"
    assert p.class_scores["low"] == pytest.approx(0.1 + 1.5 * 0.8 - 0.5 * 0.4)
    assert sum(e.class_contributions["low"] for e in trace.rules) + p.class_bias["low"] == pytest.approx(
        p.class_scores["low"])
    bad = _trace()
    bad["rules"][0] = bad["rules"][0].model_copy(update={"class_contributions": {"low": 9.0, "mid": 0.4, "high": -1.6}})
    with pytest.raises(ValidationError, match="class_weights x firing"):
        m.RuleTrace(**bad)
    with pytest.raises(ValidationError, match="first class of largest"):
        m.RuleTrace(**_trace(label="mid", top_rule_id=None, top_rule_share=None))
    with pytest.raises(ValidationError, match="top_rule_id"):
        m.RuleTrace(**_trace(top_rule_id="R02"))
    with pytest.raises(ValidationError, match="winning_rule_id"):
        m.RuleTrace(**_trace(winning_rule_id="R01"))
    with pytest.raises(ValidationError, match="class_scores"):
        m.RuleTrace(**_trace(class_scores={"low": 1.0, "mid": 0.0, "high": 0.0}))
    # no rule fires: scores = biases, no class with allow_unknown, fallback_used
    quiet = m.RuleTrace(**_trace(firing=(0.0, 0.0)))
    assert quiet.prediction.label is None and quiet.prediction.fallback_used
    assert quiet.prediction.class_scores == quiet.prediction.class_bias
    with pytest.raises(ValidationError, match="no class"):
        m.RuleTrace(**_trace(firing=(0.0, 0.0), label="mid", missing_reason=None))


def test_predictions_name_the_top_rule_never_a_deciding_rule():
    base = dict(entity_id="E0", model_id="mix", data_version="v", unit="u", issued_at_utc=T0,
                valid_at_utc=T0 + timedelta(hours=6), prediction=None, prediction_label="low",
                geometry_support=m.GeometrySupport.OBSERVED_POINT)
    props = m.PredictionProperties(**base, top_rule_id="R01", top_rule_share=0.8)
    assert props.decided_by_rule_id is None
    with pytest.raises(ValidationError, match="go together"):
        m.PredictionProperties(**base, top_rule_id="R01")
    with pytest.raises(ValidationError, match="excludes decided_by_rule_id"):
        m.PredictionProperties(**base, top_rule_id="R01", top_rule_share=0.8, decided_by_rule_id="R01")
    with pytest.raises(ValidationError):
        m.PredictionProperties(**{**base, "prediction_label": None, "missing_reason": "prediction_unavailable"},
                               top_rule_id="R01", top_rule_share=0.8)


def _importance(**update):
    rules = [m.RuleImportance(rule_id="R01", n_top=6, top_contributor_share=0.6, n_decisive=3, decisive_share=0.3,
                              n_checked=6, accuracy=0.5),
             m.RuleImportance(rule_id="R02", n_top=3, top_contributor_share=0.3, n_decisive=5, decisive_share=0.5,
                              n_checked=2, accuracy=1.0)]
    body = dict(data_version="v", model_id="mix", task_id="t", measure="rule_mixture", period_from_utc=T0,
                period_to_utc=T0, n_predicted=10, n_no_rule=0, n_no_top_rule=1, rules=rules,
                variables=[m.VariableImportance(feature="x", n_rules=2, top_contributor_share=0.9,
                                                decisive_share=0.6)], entities=[])
    body.update(update)
    return m.RuleImportanceResponse(**body)


def test_importance_of_the_mixture_top_and_decisive_shares():
    response = _importance()
    assert all(r.n_decided is None and r.decided_share is None for r in response.rules)
    assert sum(r.decisive_share for r in response.rules) != 1  # several rules can be decisive for one prediction
    with pytest.raises(ValidationError, match="one top rule"):
        _importance(n_no_top_rule=0)
    with pytest.raises(ValidationError, match="n_no_top_rule"):
        _importance(n_no_top_rule=None)
    with pytest.raises(ValidationError, match="winning rule and TSK only"):
        _importance(rules=[m.RuleImportance(rule_id="R01", n_top=9, top_contributor_share=0.9, n_decisive=1,
                                            decisive_share=0.1, n_checked=0, n_decided=9, decided_share=0.9)])
    with pytest.raises(ValidationError, match="decided_share for the winning rule"):
        _importance(variables=[m.VariableImportance(feature="x", n_rules=2, decided_share=0.9)])


def test_the_mixture_fixture_responses_validate():
    """fixtures/synthetic/v07_responses.json: artifacts-mode answers of the synthetic mixture (make fixtures)."""
    items = json.loads((FIXTURES / "v07_responses.json").read_text())
    shapes = {"/rules": m.ModelRules, "/rule-trace": m.RuleTrace, "/predictions": m.PredictionsResponse,
              "/scenarios": m.ScenarioResponse, "/importance": m.RuleImportanceResponse}
    seen = set()
    for item in items:
        suffix = next(s for s in shapes if item["path"].endswith(s))
        seen.add(suffix)
        payload = shapes[suffix].model_validate(item["response"])
        assert payload.synthetic
        if suffix == "/rule-trace" and payload.rules:
            assert payload.prediction.winning_rule_id is None and payload.prediction.class_scores is not None
        if suffix == "/predictions":
            answered = [f.properties for f in payload.features if f.properties.prediction_label is not None]
            assert answered and all(p.decided_by_rule_id is None for p in answered)
            assert any(p.top_rule_id is not None for p in answered)
    assert seen == set(shapes)
