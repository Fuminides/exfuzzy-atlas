"""Contract v0.8 (CONTRACTS.md §19): ordinal ("at least / at most") and compound conditions on an Antecedent."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from atlas.contracts import models as m

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic"
T0 = datetime(2025, 1, 8, 7, tzinfo=timezone.utc)
SPEC = m.InferenceSpec(family="tsk_zero_order", tnorm="product", rule_mode="additive", fallback="train_target_mean",
                       exfuzzy_version="3.5.0")
HOUR = ["Night", "Morning", "Midday", "Evening"]


def _variable(feature, names):
    return m.LinguisticVariable(feature=feature, terms=[
        m.LinguisticTerm(name=n, membership_type="trapezoidal", params=[i, i + 1, i + 2, i + 3])
        for i, n in enumerate(names)])


def _rules(*antecedents, variables=None):
    rule = m.RuleDefinition(rule_id="R01", position=0, antecedents=list(antecedents), text="IF ...",
                            consequent=m.Consequent(type="crisp", value=1.0, unit="u"))
    return m.ModelRules(
        data_version="v", model_id="mod", task_id="t", domain=m.Domain.AIR, inference=SPEC,
        variables=variables or [_variable("quality", ["Poor", "Fair", "Good", "Great"]), _variable("hour", HOUR)],
        rules=[rule])


def test_an_old_antecedent_is_an_is_condition_over_its_term():
    a = m.Antecedent(feature="quality", term="Fair")
    assert (a.operator, a.terms, a.label, a.label_en) == ("is", ["Fair"], None, None)
    assert a.model_dump()["terms"] == ["Fair"]  # serialised: operator "is", terms [term]
    _rules(a)


def test_at_least_and_at_most_name_the_threshold_term_and_cover_the_scale_from_it():
    at_least = m.Antecedent(feature="quality", term="Fair", operator="at_least", terms=["Fair", "Good", "Great"])
    at_most = m.Antecedent(feature="quality", term="Good", operator="at_most", terms=["Poor", "Fair", "Good"])
    _rules(at_least)
    _rules(at_most)
    for bad in (
        dict(term="Fair", operator="at_least", terms=["Fair"]),  # one term is the term itself
        dict(term="Good", operator="at_least", terms=["Fair", "Good"]),  # the threshold is the lowest term covered
        dict(term="Fair", operator="at_most", terms=["Poor", "Fair", "Good"]),  # ... and the highest, for at_most
        dict(term="Fair", operator="is", terms=["Fair", "Good"]),
        dict(term="Fair", operator="at_least", terms=["Fair", "Fair", "Good"]),
    ):
        with pytest.raises(ValidationError):
            m.Antecedent(feature="quality", **bad)
    # consistent in itself but not a run to the end of the scale of the variable
    with pytest.raises(ValidationError, match="from the threshold to that end of the scale"):
        _rules(m.Antecedent(feature="quality", term="Fair", operator="at_least", terms=["Fair", "Good"]))
    with pytest.raises(ValidationError, match="unknown term"):
        _rules(m.Antecedent(feature="quality", term="Fine", operator="at_least", terms=["Fine", "Great"]))


def test_a_compound_has_its_own_name_and_covers_terms_of_the_variable():
    wrap = m.Antecedent(feature="hour", term="Long night", operator="any_of", terms=["Night", "Evening"],
                        label="Noche larga", label_en="Long night")
    rules = _rules(wrap)
    assert rules.rules[0].antecedents[0].label_en == "Long night"
    with pytest.raises(ValidationError, match="compound"):
        _rules(m.Antecedent(feature="hour", term="Night", operator="any_of", terms=["Night", "Morning"]))
    with pytest.raises(ValidationError, match="compound"):
        _rules(m.Antecedent(feature="hour", term="Late", operator="any_of", terms=["Night", "Nine"]))
    with pytest.raises(ValidationError, match="at least two"):
        m.Antecedent(feature="hour", term="Late", operator="any_of", terms=["Night"])
    with pytest.raises(ValidationError, match="compound"):
        m.Antecedent(feature="hour", term="Night", label="Noche")  # a label is for a compound


def test_a_trace_condition_carries_the_same_operator_and_terms():
    t = m.AntecedentTrace(feature="hour", term="Long night", operator="any_of", terms=["Night", "Evening"],
                          membership=0.75, effective_membership=0.75)
    assert t.terms == ["Night", "Evening"]
    old = m.AntecedentTrace(feature="hour", term="Night", membership=0.5, effective_membership=0.5)
    assert (old.operator, old.terms) == ("is", ["Night"])
    with pytest.raises(ValidationError):
        m.AntecedentTrace(feature="q", term="Good", operator="at_least", terms=["Fair", "Good"],
                          membership=0.5, effective_membership=0.5)
    entry = m.RuleTraceEntry(rule_id="R01", antecedents=[t, old], firing_strength=0.375, effective_firing=0.375)
    assert entry.antecedents[0].operator == "any_of"
    trace = m.RuleTrace(
        data_version="v", model_id="mod", task_id="t", entity_id="E", issued_at_utc=T0,
        valid_at_utc=T0 + timedelta(hours=1), inference=SPEC,
        feature_values=[m.FeatureValue(feature="hour", value=19.0)], rules=[entry],
        prediction=m.TracePrediction(value=1.0, unit="u", fallback_used=False))
    assert trace.rules[0].firing_strength == 0.375


def test_older_payloads_validate_and_serialise_as_is():
    assert m.SCHEMA_VERSION == "0.8.0"
    for item in json.loads((FIXTURES / "model_rules_extra.json").read_text()):
        rules = m.ModelRules.model_validate(item)
        assert all(a.operator == "is" and a.terms == [a.term] for r in rules.rules for a in r.antecedents)
    old = json.loads((FIXTURES / "model_rules.json").read_text())
    for rule in old["rules"]:  # a v0.7 payload carries neither operator nor terms
        for a in rule["antecedents"]:
            a.pop("operator", None), a.pop("terms", None), a.pop("label", None), a.pop("label_en", None)
    m.ModelRules.model_validate(old)


def test_the_what_if_label_and_the_stories_text_state_what_they_are():
    assert m.WHAT_IF_LABEL == "respuesta del modelo ante entradas modificadas"
    assert m.STORIES_DISCLAIMER == "Descripciones de activaciones del modelo en la ventana pedida."
    assert datetime.now(timezone.utc).tzinfo is not None
