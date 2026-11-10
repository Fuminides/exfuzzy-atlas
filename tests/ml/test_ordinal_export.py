"""Contract v0.8: ordinal and compound conditions in rules.json and in the traces, from the library's own numbers."""

import numpy as np
import pytest
from ml_helpers import fit_fuzzy

from atlas.compound_terms import CompoundLabel, apply_labels
from atlas.contracts import models as m
from atlas.explain import build_rule_traces
from atlas.explain.classifier import build_classifier_traces, get_master_rulebase
from atlas.explain.mixture import build_mixture_traces
from atlas.ml import exfuzzy_features as xf
from atlas.ml.fuzzy_classifier import FuzzyClassifier, FuzzyClassifierParams
from atlas.ml.rules_export import export_classifier_rules, export_model_rules
from atlas.ml.synthetic import FEATURE_UNITS, FEATURES, TARGET

LABELS = ["lo", "mid", "hi"]
SCHEME = m.TargetScheme(name="b", source_url="https://example.org", unit="u", boundary="upper_inclusive", classes=[
    m.TargetClass(label="lo", lower=None, upper=1), m.TargetClass(label="mid", lower=1, upper=2),
    m.TargetClass(label="hi", lower=2, upper=None)])
needs_compound = pytest.mark.skipif(not (xf.has_ordinal_conditions() and xf.has_compound_terms()),
                                    reason="needs ex-fuzzy 3.5.0 (ordinal and compound conditions)")
NAMES = {"Test stretch": CompoundLabel(label="baja o media", label_en="low or medium")}


def _fit(rows, mixture):
    y = np.digitize(rows[TARGET].to_numpy(), np.quantile(rows[TARGET], [0.5, 0.85]))
    extra = dict(inference="mixture", mixture_search=True, mixture_non_negative=True) if mixture else {}
    params = FuzzyClassifierParams(nRules=9, nAnts=2, n_gen=8, pop_size=16, ordinal_conditions=("y_t", "exo_t"),
                                   compound_terms={"hour": [("Test stretch", ["Low", "Medium"])]}, **extra)
    return FuzzyClassifier(params, FEATURE_UNITS).fit(rows[FEATURES], y, LABELS, seed=2)


def _force(rb):
    """Rule 0: y_t at least Medium AND hour Test stretch. Rule 1: exo_t at most Medium."""
    by = {str(v.name): v for v in rb.antecedents}
    rules = rb.get_rules()
    for rule in rules[:2]:
        for f in range(len(FEATURES)):
            rule.antecedents[f] = -1
    rules[0].antecedents[FEATURES.index("y_t")] = xf.condition_labels(by["y_t"]).index("at least Medium")
    rules[0].antecedents[FEATURES.index("hour")] = xf.condition_labels(by["hour"]).index("Test stretch")
    rules[1].antecedents[FEATURES.index("exo_t")] = xf.condition_labels(by["exo_t"]).index("at most Medium")


def _expected(rb, rule, values):
    """The memberships a condition must have: the bounded sum of its base terms, from the terms' own memberships."""
    out = {}
    for c in xf.rule_conditions(rule, rb.antecedents):
        var = rb.antecedents[c.feature]
        names = var.linguistic_variable_names()
        base = [var.linguistic_variables[names.index(t)].membership(values[:, c.feature]) for t in c.terms]
        out[c.feature] = np.minimum(1.0, np.sum(base, axis=0)) if len(base) > 1 else base[0]
    return out


@needs_compound
@pytest.mark.parametrize("mixture", [False, True])
def test_the_export_and_the_traces_carry_the_operator_and_the_bounded_sum(complete_rows, mixture):
    rows = complete_rows.reset_index(drop=True)
    model = _fit(rows, mixture)
    rb = get_master_rulebase(model)
    _force(rb)
    if mixture:  # the weights stay; only the check that they belong to these rules is told about the new ones
        from ex_fuzzy import rule_mixture

        estimator = model.estimator
        estimator.mixture_.rule_keys_ = rule_mixture.rule_keys(estimator.rule_base)
    rules = export_classifier_rules(
        model, model_id="mod", task_id="t", domain=m.Domain.AIR, target_label="Y", target_scheme=SCHEME,
        horizon_hours=6, data_version="v", synthetic=True, feature_units=FEATURE_UNITS)
    first, second = rules.rules[0], rules.rules[1]
    got = {a.feature: a for a in first.antecedents}
    assert (got["y_t"].operator, got["y_t"].term, got["y_t"].terms) == ("at_least", "Medium", ["Medium", "High"])
    assert (got["hour"].operator, got["hour"].term, got["hour"].terms) == ("any_of", "Test stretch", ["Low", "Medium"])
    assert got["hour"].label is None  # no name in the config until it is given one
    assert second.antecedents[0].operator == "at_most" and second.antecedents[0].terms == ["Low", "Medium"]
    assert "y_t IS at least Medium" in first.text and "hour IS Test stretch" in first.text
    labelled = apply_labels(rules, NAMES).rules[0]
    assert {a.feature: a for a in labelled.antecedents}["hour"].label_en == "low or medium"
    assert {a.feature: a for a in labelled.antecedents}["y_t"].label is None
    m.ModelRules.model_validate_json(rules.model_dump_json())
    # the traces: the library's memberships, and the firing is the product of them
    X = rows.head(50)
    build = build_mixture_traces if mixture else build_classifier_traces
    traces = build(model, X[FEATURES], ["E"] * len(X), X["issued_at_utc"], class_labels=LABELS, model_id="mod",
                   task_id="t", horizon_hours=6, target_unit="u", data_version="v", synthetic=True)
    expected = _expected(rb, rb.get_rules()[0], X[FEATURES].to_numpy(dtype=float))
    for k, trace in enumerate(traces):
        entry = trace.rules[0]
        by_feature = {a.feature: a for a in entry.antecedents}
        assert by_feature["hour"].operator == "any_of" and by_feature["hour"].terms == ["Low", "Medium"]
        assert by_feature["y_t"].operator == "at_least"
        for f, e in expected.items():
            assert by_feature[FEATURES[f]].membership == pytest.approx(float(e[k]), abs=1e-12)
        assert entry.firing_strength == pytest.approx(
            by_feature["y_t"].membership * by_feature["hour"].membership, abs=1e-12)


@needs_compound
def test_a_regressor_with_ordinal_conditions_is_exported_and_traced(complete_rows):
    rows = complete_rows.reset_index(drop=True)
    model = fit_fuzzy(rows, seed=1, ordinal_conditions=("y_t",))
    rb = model.get_rulebase()
    for f in range(len(FEATURES)):
        rb.rules[0].antecedents[f] = -1
    by = {str(v.name): v for v in rb.antecedents}
    rb.rules[0].antecedents[FEATURES.index("y_t")] = xf.condition_labels(by["y_t"]).index("at most Medium")
    rules = export_model_rules(model, model_id="mod", task_id="t", domain=m.Domain.AIR, target="y", target_unit="u",
                               horizon_hours=6, data_version="v", synthetic=True)
    a = rules.rules[0].antecedents[0]
    assert (a.operator, a.term, a.terms) == ("at_most", "Medium", ["Low", "Medium"])
    X = rows.head(20)
    traces = build_rule_traces(model, X[FEATURES], ["E"] * 20, X["issued_at_utc"], model_id="mod", task_id="t",
                               horizon_hours=6, target_unit="u", data_version="v", synthetic=True)
    expected = _expected(rb, rb.rules[0], X[FEATURES].to_numpy(dtype=float))[FEATURES.index("y_t")]
    got = [t.rules[0].antecedents[0] for t in traces]
    assert all(g.operator == "at_most" for g in got)
    assert [g.membership for g in got] == pytest.approx(list(expected), abs=1e-12)
