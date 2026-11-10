"""Contract v0.4: attribution, regular flag, scheme kind, merged classes, not_modelled, and the new views."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from atlas.contracts import models as m

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic"
T0 = datetime(2025, 1, 15, 6, tzinfo=timezone.utc)
POINT = {"type": "Point", "coordinates": (-3.7, 40.4)}


def test_schema_version_is_0_4():
    assert m.SCHEMA_VERSION == "0.7.0"  # v0.5 to v0.6.2 are additive over v0.4.1; v0.7 too, but for two relaxations


def test_v03_payloads_still_validate_without_the_new_fields():
    """Backwards compatibility: every v0.4 addition to an existing model is optional."""
    card = json.loads((FIXTURES / "model_card.json").read_text())
    card.pop("attribution")
    card["coverage"].pop("regular")
    parsed = m.ModelCard.model_validate(card)
    assert parsed.attribution == [] and parsed.coverage.regular is True
    entities = json.loads((FIXTURES / "entities_air.json").read_text())
    entities.pop("attribution")
    for feature in entities["features"]:
        feature["properties"].pop("modelled")
    parsed = m.EntityCollection.model_validate(entities)
    assert parsed.attribution == [] and {f.properties.modelled for f in parsed.features} == {None}
    rules = json.loads((FIXTURES / "model_rules.json").read_text())
    assert m.ModelRules.model_validate(rules)  # no scheme, so nothing of kind / merged_from is needed
    trace = json.loads((FIXTURES / "rule_traces.json").read_text())[0]
    trace.pop("observed")
    assert m.RuleTrace.model_validate(trace).observed is None


def test_attribution_and_scheme_metadata():
    credit = m.Attribution(text="Ayuntamiento de Madrid", license="CC BY 4.0", url="https://datos.madrid.es")
    assert m.Attribution(text="no explicit licence").license is None
    with pytest.raises(ValidationError):
        m.Attribution(text="x", licence="typo")  # unknown field
    scheme = m.TargetScheme(
        name="ICA", short_name="ICA", kind="official_index", source_url="https://x", unit="ug/m3",
        classes=[
            m.TargetClass(label="a", lower=None, upper=1),
            m.TargetClass(label="b or worse", lower=1, upper=3, merged_from=["b", "c"]),
        ],
    )
    assert scheme.kind == m.SchemeKind.OFFICIAL_INDEX and scheme.classes[1].merged_from == ["b", "c"]
    assert scheme.classes[0].merged_from == [] and credit.url
    with pytest.raises(ValidationError):
        m.TargetScheme(name="x", kind="made_up", source_url="u", unit="u", classes=scheme.classes)
    assert {k.value for k in m.SchemeKind} == {"official_index", "percentile_reference", "analytical"}


def test_not_modelled_is_a_missing_reason_that_still_needs_a_null():
    assert m.MissingReason("not_modelled") is m.MissingReason.NOT_MODELLED
    props = dict(entity_id="E", rule_id="R01", metric="mean_activation", value=None, n_valid=0, time_from_utc=T0,
                 time_to_utc=T0 + timedelta(hours=1), model_id="m", data_version="v",
                 geometry_support="observed_point", missing_reason="not_modelled")
    assert m.RuleMapProperties(**props).missing_reason == m.MissingReason.NOT_MODELLED
    with pytest.raises(ValidationError, match="must be null when value is present"):
        m.RuleMapProperties(**{**props, "value": 0.0})


def prediction_props(**overrides):
    base = dict(entity_id="E1", model_id="m", data_version="v", unit="u", issued_at_utc=T0,
                valid_at_utc=T0 + timedelta(hours=6), prediction=1.5, geometry_support="observed_point")
    return {**base, **overrides}


def prediction_feature(**overrides):
    return {"type": "Feature", "id": "E1", "geometry": POINT, "properties": prediction_props(**overrides)}


def predictions_response(features, **overrides):
    base = dict(type="FeatureCollection", data_version="v", task_id="t", model_id="m", task_type="regression",
                target="y", unit="u", horizon_hours=6, issued_at_utc=T0, features=features)
    return {**base, **overrides}


def test_prediction_properties_follow_the_null_needs_a_reason_rule():
    assert m.PredictionProperties(**prediction_props(prediction=0.0)).prediction == 0.0
    assert m.PredictionProperties(**prediction_props(prediction=None, prediction_label="high")).prediction_label
    with pytest.raises(ValidationError, match="missing_reason is required"):
        m.PredictionProperties(**prediction_props(prediction=None))
    with pytest.raises(ValidationError, match="must be null when a label"):
        m.PredictionProperties(
            **prediction_props(prediction=None, prediction_label="a", missing_reason="no_observation"))
    absent = dict(issued_at_utc=None, valid_at_utc=None, prediction=None, missing_reason="not_modelled")
    assert m.PredictionProperties(**prediction_props(**absent)).issued_at_utc is None
    with pytest.raises(ValidationError, match="go together"):
        m.PredictionProperties(**prediction_props(valid_at_utc=None))
    with pytest.raises(ValidationError, match="needs missing_reason"):
        m.PredictionProperties(**prediction_props(issued_at_utc=None, valid_at_utc=None, prediction=None,
                                                  prediction_label="a"))
    with pytest.raises(ValidationError, match="no model has no row"):
        m.PredictionProperties(**prediction_props(**absent, observed=3.0))


def test_predictions_response_time_semantics():
    ok = m.PredictionsResponse(**predictions_response([prediction_feature()]))
    assert ok.features[0].properties.valid_at_utc - ok.features[0].properties.issued_at_utc == timedelta(hours=6)
    with pytest.raises(ValidationError, match="not both and not neither"):
        m.PredictionsResponse(**predictions_response([], issued_at_utc=None))
    with pytest.raises(ValidationError, match="not both and not neither"):
        m.PredictionsResponse(**predictions_response([], time_from_utc=T0, time_to_utc=T0 + timedelta(days=1)))
    window = dict(issued_at_utc=None, time_from_utc=T0, time_to_utc=T0 + timedelta(days=1))
    assert m.PredictionsResponse(**predictions_response([prediction_feature()], **window))
    with pytest.raises(ValidationError, match="outside the window"):
        m.PredictionsResponse(**predictions_response(
            [prediction_feature(issued_at_utc=T0 + timedelta(days=2), valid_at_utc=T0 + timedelta(days=2, hours=6))],
            **window))
    with pytest.raises(ValidationError, match="window"):
        m.PredictionsResponse(**predictions_response([], issued_at_utc=None, time_from_utc=T0, time_to_utc=T0))
    with pytest.raises(ValidationError, match="horizon_hours"):
        m.PredictionsResponse(**predictions_response([prediction_feature(valid_at_utc=T0 + timedelta(hours=5))]))
    with pytest.raises(ValidationError, match="differs from the query time"):
        m.PredictionsResponse(**predictions_response(
            [prediction_feature(issued_at_utc=T0 + timedelta(hours=1), valid_at_utc=T0 + timedelta(hours=7))]))
    with pytest.raises(ValidationError, match="duplicate entity"):
        m.PredictionsResponse(**predictions_response([prediction_feature(), prediction_feature()]))
    with pytest.raises(ValidationError, match="disagrees"):
        m.PredictionsResponse(**predictions_response([prediction_feature(model_id="other")]))


def observation_props(**overrides):
    base = dict(
        entity_id="E1", model_id="m", data_version="v", issued_at_utc=T0, valid_at_utc=T0 + timedelta(hours=6),
        geometry_support="observed_point",
        target={"feature": "y", "value": 4.0, "unit": "u", "observed_at_utc": T0 + timedelta(hours=6)},
        inputs=[{"feature": "x", "value": 1.0, "unit": "u", "observed_at_utc": T0 - timedelta(hours=1)}],
    )
    return {**base, **overrides}


def test_observation_properties():
    assert m.ObservationProperties(**observation_props())
    missing = {"feature": "y", "value": None, "missing_reason": "no_observation"}
    assert m.ObservationProperties(**observation_props(target=missing)).target.value is None
    with pytest.raises(ValidationError, match="missing_reason is required"):
        m.ObservationProperties(**observation_props(target={"feature": "y", "value": None}))
    with pytest.raises(ValidationError, match="future information"):
        m.ObservationProperties(**observation_props(
            inputs=[{"feature": "x", "value": 1.0, "observed_at_utc": T0 + timedelta(hours=1)}]))
    nothing = dict(issued_at_utc=None, valid_at_utc=None, target=None, inputs=[], missing_reason="not_modelled")
    assert m.ObservationProperties(**observation_props(**nothing))
    with pytest.raises(ValidationError, match="row xor a missing_reason"):
        m.ObservationProperties(**observation_props(missing_reason="no_observation"))
    with pytest.raises(ValidationError, match="row xor a missing_reason"):
        m.ObservationProperties(**observation_props(**{**nothing, "missing_reason": None}))
    with pytest.raises(ValidationError, match="carries no values"):
        m.ObservationProperties(**observation_props(**{**nothing, "inputs": [{"feature": "x", "value": 1.0}]}))
    with pytest.raises(ValidationError, match="needs a target"):
        m.ObservationProperties(**observation_props(target=None))


def stats(rule_id, mean, frequency, share=None):
    return {"rule_id": rule_id, "mean_activation": mean, "activation_frequency": frequency, "winner_share": share}


def territory_props(rules, dominant, value, **overrides):
    base = dict(entity_id="E1", model_id="m", data_version="v", geometry_support="observed_point", n_records=10,
                n_valid=9, dominant_rule_id=dominant, dominant_value=value, rules=rules)
    return {**base, **overrides}


def territories_response(props_list, measure="mean_activation", **overrides):
    features = [{"type": "Feature", "id": p["entity_id"], "geometry": POINT, "properties": p} for p in props_list]
    base = dict(type="FeatureCollection", data_version="v", model_id="m", inference_family="tsk_zero_order",
                measure=measure, tau=0.5, time_from_utc=T0, time_to_utc=T0 + timedelta(days=1), n_rules=2,
                tie_break="lowest position", denominators="n_valid", features=features)
    return {**base, **overrides}


def test_dominant_index_is_the_argmax_with_a_documented_tie_break():
    assert m.dominant_index([0.1, 0.4, 0.2]) == 1
    assert m.dominant_index([0.4, 0.4]) == 0  # exact tie: lowest position
    assert m.dominant_index([0.1, 0.4 + 5e-13, 0.4]) == 1  # positions 1 and 2 tie (5e-13 apart): the lowest wins
    assert m.dominant_index([0.4, 0.4 + 5e-13]) == 0  # within tolerance of the best: the lowest position wins
    assert m.dominant_index([0.4, 0.4 + 5e-12]) == 1  # clearly larger
    assert m.dominant_index([0.0, 0.0]) is None and m.dominant_index([]) is None


def test_territories_dominant_rule_must_be_the_argmax_of_the_measure():
    rules = [stats("R01", 0.2, 0.9), stats("R02", 0.6, 0.1)]
    ok = m.RuleTerritoriesResponse(**territories_response([territory_props(rules, "R02", 0.6)]))
    assert ok.features[0].properties.dominant_rule_id == "R02"
    # under activation_frequency the dominant rule is another one: dominance depends on the stated measure
    other = territories_response([territory_props(rules, "R01", 0.9)], measure="activation_frequency")
    assert m.RuleTerritoriesResponse(**other).features[0].properties.dominant_value == 0.9
    with pytest.raises(ValidationError, match="argmax of mean_activation"):
        m.RuleTerritoriesResponse(**territories_response([territory_props(rules, "R01", 0.2)]))
    tie = [stats("R01", 0.5, 0.5), stats("R02", 0.5, 0.5)]
    assert m.RuleTerritoriesResponse(**territories_response([territory_props(tie, "R01", 0.5)]))
    with pytest.raises(ValidationError, match="argmax"):
        m.RuleTerritoriesResponse(**territories_response([territory_props(tie, "R02", 0.5)]))
    zeros = [stats("R01", 0.0, 0.0), stats("R02", 0.0, 0.0)]
    assert m.RuleTerritoriesResponse(**territories_response([territory_props(zeros, None, None)]))
    with pytest.raises(ValidationError, match="argmax"):
        m.RuleTerritoriesResponse(**territories_response([territory_props(zeros, "R01", 0.0)]))


def test_territories_denominators_and_missing_entities():
    rules = [stats("R01", 0.2, 0.9), stats("R02", 0.6, 0.1)]
    empty = territory_props([], None, None, n_records=0, n_valid=0, missing_reason="not_modelled")
    second = territory_props(rules, "R02", 0.6, entity_id="E2")
    assert m.RuleTerritoriesResponse(**territories_response([empty, second]))
    with pytest.raises(ValidationError, match="exactly when n_valid is 0"):
        m.TerritoryProperties(**territory_props(rules, "R02", 0.6, missing_reason="missing_input"))
    with pytest.raises(ValidationError, match="exactly when n_valid is 0"):
        m.TerritoryProperties(**{**empty, "missing_reason": None})
    with pytest.raises(ValidationError, match="n_valid cannot exceed"):
        m.TerritoryProperties(**territory_props(rules, "R02", 0.6, n_valid=11))
    with pytest.raises(ValidationError, match="carries no rule values"):
        m.TerritoryProperties(**{**empty, "rules": rules})
    with pytest.raises(ValidationError, match="go together"):
        m.TerritoryProperties(**territory_props(rules, "R02", None))
    with pytest.raises(ValidationError, match="lists every rule"):
        m.TerritoryProperties(**territory_props([], None, None))
    with pytest.raises(ValidationError, match="every rule must be listed"):
        m.RuleTerritoriesResponse(**territories_response([territory_props(rules[:1], "R01", 0.2)]))
    with pytest.raises(ValidationError):
        m.RuleTerritoriesResponse(**territories_response([territory_props(rules, "R02", 0.6)], tau=0.0))
    with pytest.raises(ValidationError, match="window"):
        m.RuleTerritoriesResponse(**territories_response([], time_to_utc=T0))


def test_winner_share_only_exists_for_classifiers():
    with pytest.raises(ValidationError, match="winner_share only exists for winning-rule classifiers"):
        m.RuleTerritoriesResponse(**territories_response([], measure="winner_share"))
    shares = [stats("R01", 0.2, 0.9, 0.3), stats("R02", 0.6, 0.1, 0.6)]
    classifier = dict(inference_family="winning_rule_classifier")
    ok = m.RuleTerritoriesResponse(**territories_response(
        [territory_props(shares, "R02", 0.6)], measure="winner_share", **classifier))
    assert ok.features[0].properties.rules[1].winner_share == 0.6
    with pytest.raises(ValidationError, match="winner_share exactly for classifiers"):
        m.RuleTerritoriesResponse(**territories_response([territory_props(shares, "R02", 0.6)]))
    with pytest.raises(ValidationError, match="winner_share exactly for classifiers"):
        m.RuleTerritoriesResponse(**territories_response(
            [territory_props([stats("R01", 0.2, 0.9), stats("R02", 0.6, 0.1)], "R02", 0.6)], **classifier))


def story(**overrides):
    base = dict(
        story_id="s", kind="territory_leader", rule_id="R01", text="R01 ...", score=0.5, numbers={"k": 2},
        queries=[{"path": "/api/v1/rule-territories", "params": {"model_id": "m"}}],
        checks=[{"query": 0, "property": "n_valid", "op": "gte", "operand": 1, "expected": 2}],
    )
    return {**base, **overrides}


def stories_response(stories, **overrides):
    base = dict(data_version="v", model_id="m", time_from_utc=T0, time_to_utc=T0 + timedelta(days=1), tau=0.5,
                limit=5, n_candidates=len(stories), score_definition="s", stories=stories)
    return {**base, **overrides}


def test_stories_are_ranked_capped_and_auditable():
    assert m.RuleStoriesResponse(**stories_response([story(story_id="a", score=0.9), story(story_id="b", score=0.2)]))
    with pytest.raises(ValidationError, match="descending score"):
        m.RuleStoriesResponse(**stories_response([story(story_id="a", score=0.2), story(story_id="b", score=0.9)]))
    with pytest.raises(ValidationError, match="more stories than the limit"):
        m.RuleStoriesResponse(**stories_response([story(story_id="a"), story(story_id="b")], limit=1))
    with pytest.raises(ValidationError, match="duplicate story_id"):
        m.RuleStoriesResponse(**stories_response([story(), story()]))
    with pytest.raises(ValidationError, match="query that does not exist"):
        m.RuleStory(**story(checks=[{"query": 3, "property": "value", "op": "not_null", "expected": 1}]))
    with pytest.raises(ValidationError):  # a story without a query to reproduce it
        m.RuleStory(**story(queries=[]))
    with pytest.raises(ValidationError):  # nor a check
        m.RuleStory(**story(checks=[]))
    with pytest.raises(ValidationError, match="operand"):
        m.StoryCheck(query=0, property="value", op="gte", expected=1)
    with pytest.raises(ValidationError, match="operand"):
        m.StoryCheck(query=0, property="value", op="not_null", operand=0.5, expected=1)
    with pytest.raises(ValidationError):  # only the two map endpoints can reproduce a story
        m.StoryQuery(path="/api/v1/scenarios", params={})
    assert m.STORIES_DISCLAIMER.startswith("Descripciones de activaciones") and "No son causas" in m.STORIES_DISCLAIMER


def test_scenario_request_validation():
    request = m.ScenarioRequest(model_id="m", entity_id="E1", at=T0, overrides={"x": 1.5})
    assert request.overrides == {"x": 1.5} and m.ScenarioRequest(model_id="m", entity_id="E", at=T0).overrides == {}
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValidationError):
            m.ScenarioRequest(model_id="m", entity_id="E1", at=T0, overrides={"x": bad})
    with pytest.raises(ValidationError):
        m.ScenarioRequest(model_id="m", entity_id="E1", at=datetime(2025, 1, 1), overrides={})  # naive time
    with pytest.raises(ValidationError):
        m.ScenarioRequest(model_id="m", entity_id="E1", at=T0, overrides={}, extra=1)


def scenario_payload():
    entry = json.loads((FIXTURES / "v04_responses.json").read_text())[-1]
    assert entry["path"] == "/api/v1/scenarios"
    return entry["response"]


def test_the_committed_scenario_fixture_is_valid_and_honestly_labelled():
    scenario = m.ScenarioResponse.model_validate(scenario_payload())
    assert scenario.synthetic_what_if is True and scenario.label == m.WHAT_IF_LABEL
    assert "no efecto causal ni predicción" in scenario.label
    assert [i.origin for i in scenario.inputs] == ["observed", "overridden"]


def test_scenario_response_checks_its_own_consistency():
    payload = scenario_payload()
    with pytest.raises(ValidationError):
        m.ScenarioResponse.model_validate({**payload, "synthetic_what_if": False})
    wrong_delta = json.loads(json.dumps(payload))
    wrong_delta["rule_deltas"][0]["firing_delta"] += 0.1
    with pytest.raises(ValidationError, match="firing_delta != scenario - original"):
        m.ScenarioResponse.model_validate(wrong_delta)
    wrong_firing = json.loads(json.dumps(payload))
    wrong_firing["rule_deltas"][0]["firing_scenario"] = 0.77
    with pytest.raises(ValidationError, match="disagree with the traces"):
        m.ScenarioResponse.model_validate(wrong_firing)
    changed = json.loads(json.dumps(payload))
    changed["inputs"][0]["scenario_value"] = 1.0  # an observed input cannot differ from its original
    with pytest.raises(ValidationError):
        m.ScenarioResponse.model_validate(changed)
    other_entity = json.loads(json.dumps(payload))
    other_entity["modified"]["entity_id"] = "SYN_B"
    with pytest.raises(ValidationError, match="requested model, entity and time"):
        m.ScenarioResponse.model_validate(other_entity)


def test_trace_and_coverage_new_fields():
    trace = json.loads((FIXTURES / "rule_traces.json").read_text())[0]
    assert m.RuleTrace.model_validate(trace).observed == trace["observed"]
    coverage = m.TimeCoverage(issued_from_utc=T0, issued_to_utc=T0 + timedelta(days=3), step_hours=1, regular=False)
    assert coverage.regular is False
