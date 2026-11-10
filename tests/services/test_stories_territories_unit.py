"""Rule Stories and Territories on hand-made statistics: the burst, localized and leader definitions, to the letter."""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from atlas.contracts import models as m
from atlas.services import stories, territories

T0 = datetime(2025, 3, 1, 0, tzinfo=timezone.utc)
START, END = T0, T0 + timedelta(days=1)
RULES = ["R01", "R02", "R03"]


def step_stats(active_by_step, rule="R01", n_reporting=10, skip=()):
    """One row per step: ``active_by_step[i]`` entities above tau out of ``n_reporting``."""
    rows = [[rule, pd.Timestamp(T0 + timedelta(hours=i)), n_reporting, a]
            for i, a in enumerate(active_by_step) if i not in skip]
    return pd.DataFrame(rows, columns=stories.STEP_COLUMNS)


def territory(shares, dominant=None):
    """TerritoriesResponse for entities with the given (mean, frequency) per rule; ``dominant`` is recomputed."""
    features = []
    for i, per_rule in enumerate(shares):
        rules = [m.TerritoryRuleStats(rule_id=r, mean_activation=mean, activation_frequency=freq)
                 for r, (mean, freq) in zip(RULES, per_rule, strict=True)]
        top = m.dominant_index([r.mean_activation for r in rules])
        features.append(m.TerritoryFeature(
            type="Feature", id=f"E{i}", geometry=None, properties=m.TerritoryProperties(
                entity_id=f"E{i}", model_id="m", data_version="v", geometry_support="observed_point", n_records=24,
                n_valid=24, rules=rules, dominant_rule_id=None if top is None else RULES[top],
                dominant_value=None if top is None else rules[top].mean_activation)))
    return m.RuleTerritoriesResponse(
        type="FeatureCollection", data_version="v", model_id="m", inference_family="tsk_zero_order",
        measure="mean_activation", tau=0.5, time_from_utc=START, time_to_utc=END, n_rules=3, tie_break="t",
        denominators="d", features=features)


def build(step=None, territories_response=None, limit=10, step_hours=1):
    return stories.build_stories(
        model_id="m", data_version="v", synthetic=False, domain=m.Domain.AIR, rule_ids=RULES,
        territories=territories_response or territory([[(0.0, 0.0)] * 3] * 3), step_stats=step, step_hours=step_hours,
        entity_names={}, start=START, end=END, tau=0.5, limit=limit)


def test_a_burst_is_a_run_well_above_the_baseline():
    #            quiet   |---- 5 steps with 6 of 10 ----|   quiet
    active = [0, 0, 1, 0, 6, 7, 6, 6, 5, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    [story] = build(step_stats(active)).stories
    assert story.kind == m.StoryKind.CO_ACTIVATION_BURST and story.rule_id == "R01"
    n = story.numbers
    assert (n["steps"], n["hours"], n["n_active_at_peak"], n["n_reporting_at_peak"]) == (5, 5, 7, 10)
    assert n["peak_time_utc"] == "2025-03-01T05:00:00Z" and n["first_issue_utc"] == "2025-03-01T04:00:00Z"
    assert n["last_issue_utc"] == "2025-03-01T08:00:00Z"
    baseline = sum(active) / 10 / len(active)
    assert n["baseline_share"] == pytest.approx(baseline, abs=1e-6)
    assert story.score == pytest.approx(0.7 * (1 - baseline) * min(1, 5 / 12), abs=1e-5)
    assert story.text.startswith("R01 superó τ=0.5 en 7 de 10 estaciones a la vez (máximo), durante 5 h seguidas")
    assert [q.params["time"] for q in story.queries] == [f"2025-03-01T0{h}:00:00Z" for h in range(4, 9)]
    assert {q.path for q in story.queries} == {"/api/v1/rule-map"}
    expected = [6, 7, 6, 6, 5]
    gte = [c.expected for c in story.checks if c.op == "gte"]
    assert gte == expected and [c.expected for c in story.checks if c.op == "not_null"] == [10] * 5


def test_short_runs_missing_steps_and_regimes_are_not_bursts():
    assert build(step_stats([0, 6, 6, 0, 0, 0])).stories == []  # two steps: shorter than 3
    hot = [6] * 5 + [0] * 19
    assert build(step_stats(hot, skip={2})).stories == []  # a missing issue time breaks the run into 2 + 2 steps
    assert [s.kind for s in build(step_stats(hot)).stories] == [m.StoryKind.CO_ACTIVATION_BURST]
    assert build(step_stats([6] * 100 + [0] * 200)).stories == []  # longer than 72 steps: a regime
    assert build(step_stats([1, 2, 1, 2, 1, 2])).stories == []  # below 25 % never counts
    assert build(step_stats([2, 2, 2, 0, 0, 0, 0, 0, 0], n_reporting=10)).stories == []  # 20 % < 25 %
    assert build(step_stats([6] * 12, n_reporting=10)).stories == []  # always active: not above twice its baseline
    assert build(step_stats([6, 6, 6, 0, 0, 0], n_reporting=2)).stories == []  # fewer than 3 reporting entities
    assert build(None).stories == []  # irregular tasks have no issue-time bursts


def test_only_the_best_burst_of_a_rule_is_told_and_steps_follow_step_hours():
    active = [0] * 3 + [5, 5, 5] + [0] * 5 + [9, 9, 9, 9] + [0] * 9
    [story] = build(step_stats(active)).stories
    assert story.numbers["steps"] == 4 and story.numbers["n_active_at_peak"] == 9
    two_hourly = step_stats(active)
    two_hourly["issued_at_utc"] = [pd.Timestamp(T0 + timedelta(hours=2 * i)) for i in range(len(two_hourly))]
    [story] = build(two_hourly, step_hours=2).stories
    assert story.numbers["hours"] == 8 and "durante 8 h seguidas" in story.text
    assert build(two_hourly, step_hours=1).stories == []  # 2 h apart is not consecutive on a 1 h grid


def test_localized_rule_needs_a_few_entities_out_of_at_least_four():
    quiet = [(0.1, 0.0)] * 3
    busy = [(0.4, 0.6), (0.1, 0.0), (0.1, 0.0)]
    response = build(territories_response=territory([busy] + [quiet] * 7))
    [story] = [s for s in response.stories if s.kind == m.StoryKind.LOCALIZED_RULE]
    assert story.rule_id == "R01" and story.numbers["k"] == 1 and story.numbers["n"] == 8
    assert story.score == pytest.approx(0.8 * (1 - 1 / 8) * 0.6, abs=1e-6)
    assert story.numbers["entity_ids"] == "E0" and "1 de 8 estaciones (E0)" in story.text
    assert story.queries[0].params["metric"] == "activation_frequency" and story.queries[0].params["tau"] == "0.5"
    assert [(c.property, c.operand, c.expected) for c in story.checks] == [("value", 0.1, 1), ("n_valid", 1, 8)]
    everywhere = build(territories_response=territory([busy] * 8))
    assert not [s for s in everywhere.stories if s.kind == m.StoryKind.LOCALIZED_RULE]  # k > n / 4
    assert not [s for s in build(territories_response=territory([busy] + [quiet] * 2)).stories
                if s.kind == m.StoryKind.LOCALIZED_RULE]  # fewer than 4 entities


def test_territory_leader_is_the_rule_dominant_in_most_entities():
    a, b = [(0.6, 0.9), (0.2, 0.1), (0.1, 0.0)], [(0.1, 0.0), (0.7, 0.9), (0.1, 0.0)]
    response = build(territories_response=territory([a, a, a, b]))
    [story] = [s for s in response.stories if s.kind == m.StoryKind.TERRITORY_LEADER]
    assert story.rule_id == "R01" and story.numbers["entities_led"] == 3 and story.score == pytest.approx(0.5 * 3 / 4)
    assert "R01 es la regla con mayor activación media en 3 de 4 estaciones" in story.text
    assert "no es la contribución a la predicción" in story.text
    assert story.queries[0].path == "/api/v1/rule-territories"
    assert story.queries[0].params["measure"] == "mean_activation"
    tie = build(territories_response=territory([a, a, b, b]))
    [leader] = [s for s in tie.stories if s.kind == m.StoryKind.TERRITORY_LEADER]
    assert leader.rule_id == "R01"  # 2 vs 2: the lowest rule position
    single = [s for s in build(territories_response=territory([a, b, [(0.0, 0.0)] * 3])).stories
              if s.kind == m.StoryKind.TERRITORY_LEADER]
    assert single == []  # nobody is led by more than one entity


def test_ranking_is_by_score_then_kind_then_rule_and_the_limit_caps():
    a = [(0.6, 0.9), (0.2, 0.1), (0.1, 0.0)]
    quiet = [(0.1, 0.0)] * 3
    step = pd.concat([step_stats([0, 0, 6, 6, 6, 0, 0, 0], "R01"), step_stats([0, 0, 0, 7, 7, 7, 0, 0], "R02")])
    response = build(step, territory([a] * 5 + [quiet] * 3))
    assert [s.score for s in response.stories] == sorted((s.score for s in response.stories), reverse=True)
    assert response.n_candidates == len(response.stories) >= 3
    capped = build(step, territory([a] * 5 + [quiet] * 3), limit=2)
    assert capped.stories == response.stories[:2] and capped.n_candidates == response.n_candidates
    assert build(step, territory([a] * 5 + [quiet] * 3)).model_dump() == response.model_dump()  # deterministic


def entities(*modelled):
    return [m.EntityFeature(type="Feature", id=f"E{i}", geometry=None, properties=m.EntityProperties(
        entity_id=f"E{i}", domain=m.Domain.AIR, geometry_support="observed_point", geometry_source="s", timezone="UTC",
        modelled=flag)) for i, flag in enumerate(modelled)]


def stats_rows(entity, n_records, n_valid, sums, overs, wins=(0, 0, 0)):
    return [[entity, r, n_records, n_valid, sums[i], overs[i], wins[i]] for i, r in enumerate(RULES)]


def test_build_territories_covers_every_entity_state():
    rows = stats_rows("E0", 10, 8, [4.0, 0.0, 2.0], [4, 0, 8]) + stats_rows("E1", 5, 0, [0, 0, 0], [0, 0, 0])
    stats = pd.DataFrame(rows, columns=territories.STATS_COLUMNS)
    response = territories.build_territories(
        model_id="m", data_version="v", synthetic=False, family=m.InferenceFamily.TSK_ZERO_ORDER, rule_ids=RULES,
        entities=entities(True, True, True, False), stats=stats, measure=m.TerritoryMeasure.ACTIVATION_FREQUENCY,
        tau=0.5, start=START, end=END)
    p = {f.id: f.properties for f in response.features}
    assert (p["E0"].n_records, p["E0"].n_valid) == (10, 8)
    assert [r.mean_activation for r in p["E0"].rules] == [0.5, 0.0, 0.25]
    assert [r.activation_frequency for r in p["E0"].rules] == [0.5, 0.0, 1.0]
    assert p["E0"].dominant_rule_id == "R03" and p["E0"].dominant_value == 1.0  # frequency, not mean
    assert (p["E1"].n_valid, p["E1"].missing_reason, p["E1"].rules) == (0, m.MissingReason.MISSING_INPUT, [])
    assert p["E2"].missing_reason == m.MissingReason.NO_OBSERVATION and p["E2"].n_records == 0
    assert p["E3"].missing_reason == m.MissingReason.NOT_MODELLED
    with pytest.raises(ValueError, match="winner_share"):
        territories.build_territories(
            model_id="m", data_version="v", synthetic=False, family=m.InferenceFamily.TSK_ZERO_ORDER, rule_ids=RULES,
            entities=entities(True), stats=stats, measure=m.TerritoryMeasure.WINNER_SHARE, tau=0.5, start=START,
            end=END)


def test_a_tie_between_rules_goes_to_the_lowest_position_and_classifier_winner_share_is_used():
    rows = stats_rows("E0", 10, 10, [5.0, 5.0, 1.0], [5, 5, 1], wins=[0, 6, 4])
    response = territories.build_territories(
        model_id="m", data_version="v", synthetic=False, family=m.InferenceFamily.WINNING_RULE_CLASSIFIER,
        rule_ids=RULES, entities=entities(True), stats=pd.DataFrame(rows, columns=territories.STATS_COLUMNS),
        measure=m.TerritoryMeasure.MEAN_ACTIVATION, tau=0.5, start=START, end=END)
    p = response.features[0].properties
    assert p.dominant_rule_id == "R01"  # R01 and R02 tie at 0.5: the first one
    assert [r.winner_share for r in p.rules] == [0.0, 0.6, 0.4]
    by_winner = territories.build_territories(
        model_id="m", data_version="v", synthetic=False, family=m.InferenceFamily.WINNING_RULE_CLASSIFIER,
        rule_ids=RULES, entities=entities(True), stats=pd.DataFrame(rows, columns=territories.STATS_COLUMNS),
        measure=m.TerritoryMeasure.WINNER_SHARE, tau=0.5, start=START, end=END)
    assert by_winner.features[0].properties.dominant_rule_id == "R02"
