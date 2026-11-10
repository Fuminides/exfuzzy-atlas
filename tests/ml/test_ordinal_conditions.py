"""AT-041k: ordinal conditions (ex-fuzzy PR 45) in the Atlas code, and the decision rule of the experiment.

The helpers must give the same answer on the pinned ex-fuzzy 3.4.0 (no ordinal conditions, the CI) and on a build with
the option; the tests that need the option are skipped on the pinned release.
"""

import numpy as np
import pytest
from ml_helpers import fit_fuzzy

from atlas.explain.classifier import get_master_rulebase
from atlas.ml import consensus as cons
from atlas.ml import exfuzzy_features as xf
from atlas.ml.evaluation import classifier_rule_sets, rule_signatures
from atlas.ml.experiment_ordinal import (
    ARMS,
    CompoundTerm,
    arm_b_library_options,
    arm_summary,
    check_compound_terms,
    condition_stats,
    decide_task,
    load_config,
    outcome,
    quantity_variables,
)
from atlas.ml.fuzzy import FuzzyParams
from atlas.ml.fuzzy_classifier import FuzzyClassifier, FuzzyClassifierParams
from atlas.ml.fx_checks import classifier_term_usage
from atlas.ml.rules_export import _conditions
from atlas.ml.synthetic import FEATURE_UNITS, FEATURES, TARGET
from atlas.paths import REPO_ROOT

LABELS = ["lo", "mid", "hi"]
needs_ordinal = pytest.mark.skipif(not xf.has_ordinal_conditions(), reason="needs ex-fuzzy PR 45 (ordinal_conditions)")


def _fit(rows, **options) -> FuzzyClassifier:
    y = np.digitize(rows[TARGET].to_numpy(), np.quantile(rows[TARGET], [0.5, 0.85]))
    params = FuzzyClassifierParams(nRules=9, nAnts=2, n_gen=8, pop_size=16, **options)
    return FuzzyClassifier(params, FEATURE_UNITS).fit(rows[FEATURES], y, LABELS, seed=2)


@pytest.fixture(scope="module")
def classifier(complete_rows):
    return _fit(complete_rows.reset_index(drop=True))


# ------------------------------------------------------------------------------------------ the option off


def test_the_option_is_left_out_of_the_hyperparameters_when_off():
    assert "ordinal_conditions" not in FuzzyClassifierParams().as_dict()
    assert "ordinal_conditions" not in FuzzyClassifierParams(inference="mixture", mixture_search=True).as_dict()
    assert "ordinal_conditions" not in FuzzyParams().as_dict()
    assert FuzzyClassifierParams().estimator_options() == {} and FuzzyParams().estimator_options() == {}
    on = FuzzyParams(unique_antecedents=False, ordinal_conditions=True).as_dict()
    assert on["ordinal_conditions"] is True and "unique_antecedents" not in on


@pytest.mark.skipif(xf.has_ordinal_conditions(), reason="the library has the option")
def test_the_option_is_refused_by_a_library_without_it():
    with pytest.raises(xf.ExFuzzyFeatureError, match="ordinal_conditions"):
        FuzzyClassifierParams(ordinal_conditions=True).estimator_options()
    with pytest.raises(xf.ExFuzzyFeatureError, match="ordinal_conditions"):
        FuzzyParams(ordinal_conditions=True).estimator_options()


def test_rule_conditions_are_the_single_terms_when_the_option_is_off(classifier):
    rb = get_master_rulebase(classifier)
    n_checked = 0
    for rule in rb.get_rules():
        got = xf.rule_conditions(rule, rb.antecedents)
        expected = [(f, str(rb.antecedents[f].linguistic_variable_names()[t]))
                    for f, t in enumerate(rule.antecedents) if t >= 0]
        assert [(c.feature, c.text) for c in got] == expected
        assert {c.operator for c in got} <= {"is"} and [c.term for c in got] == [c.text for c in got]
        n_checked += len(got)
    assert n_checked > 0
    assert [xf.condition_labels(v) for v in rb.antecedents] == [
        [str(n) for n in v.linguistic_variable_names()] for v in rb.antecedents]


def test_rule_sets_and_term_usage_are_unchanged_by_the_option_helpers(classifier):
    rb = get_master_rulebase(classifier)
    names = [str(v.name) for v in rb.antecedents]
    sets = classifier_rule_sets(classifier, LABELS)
    for rule, (antecedents, _) in zip(rb.get_rules(), sets, strict=True):
        assert antecedents == tuple(sorted((names[f], str(rb.antecedents[f].linguistic_variable_names()[t]))
                                           for f, t in enumerate(rule.antecedents) if t >= 0))
    usage = classifier_term_usage(classifier)
    assert all(len(terms) == 3 for terms in usage.values())  # no ordinal key appears with the option off
    assert sum(sum(t.values()) for t in usage.values()) == sum(len(a) for a, _ in sets)


def test_the_regressor_signatures_are_the_single_terms(complete_rows):
    rb = fit_fuzzy(complete_rows.reset_index(drop=True), seed=1).get_rulebase()
    names = [str(v.name) for v in rb.antecedents]
    for rule, signature in zip(rb.rules, rule_signatures(rb), strict=True):
        assert signature == tuple(sorted((names[f], str(rb.antecedents[f].linguistic_variable_names()[t]))
                                         for f, t in enumerate(rule.antecedents) if t >= 0))
    stats = condition_stats(rb.rules, rb.antecedents, names)
    assert stats["total_conditions"] == sum(len(s) for s in rule_signatures(rb))
    assert stats["n_conditions_ordinal"] == 0 and stats["n_rules_ordinal"] == 0


def test_the_consensus_model_finds_a_term_in_the_condition_labels(classifier):
    rb = get_master_rulebase(classifier)
    names = [str(v.name) for v in rb.antecedents]
    key = (((names[0], str(rb.antecedents[0].linguistic_variable_names()[1])),), "mid")
    model = cons.build_consensus_model(classifier, [key], {key: 1.0})
    assert classifier_rule_sets(model, LABELS) == [key]


# ----------------------------------------------------------------------------------------- the option on


@needs_ordinal
def test_the_probe_and_the_capability_error_agree():
    assert xf.has_ordinal_conditions()
    xf.require("ordinal_conditions")
    assert "ordinal_conditions" in xf.FEATURES


MIXTURE = {"inference": "mixture", "mixture_search": True, "mixture_non_negative": True}


@needs_ordinal
@pytest.mark.parametrize("options", [{}, MIXTURE])
def test_a_model_fitted_with_the_option_reads_its_ordinal_conditions(complete_rows, options):
    model = _fit(complete_rows.reset_index(drop=True), ordinal_conditions=True, **options)
    rb = get_master_rulebase(model)
    assert all(v.ordinal for v in rb.antecedents)  # 3 terms each: 3n - 4 = 5 conditions
    assert all(len(xf.condition_labels(v)) == 5 for v in rb.antecedents)
    # force one rule to "x IS at least <second term>" and one to "x IS at most <second term>"
    rules = rb.get_rules()
    rules[0].antecedents[0], rules[1].antecedents[1] = 3, 4
    name0, name1 = str(rb.antecedents[0].name), str(rb.antecedents[1].name)
    term0, term1 = (str(rb.antecedents[i].linguistic_variable_names()[1]) for i in (0, 1))
    sets = classifier_rule_sets(model, LABELS)
    assert (name0, f"at least {term0}") in sets[0][0] and (name1, f"at most {term1}") in sets[1][0]
    stats = condition_stats(rules, rb.antecedents, [str(v.name) for v in rb.antecedents])
    assert stats["n_conditions_ordinal"] >= 2 and stats["conditions_by_input"][name0]["at_least"] >= 1
    usage = classifier_term_usage(model)
    assert usage[name0][f"at least {term0}"] >= 1 and usage[name1][f"at most {term1}"] >= 1
    assert sum(sum(t.values()) for t in usage.values()) == sum(len(a) for a, _ in sets)
    exported = dict(_conditions(rules[0], rb.antecedents, [str(v.name) for v in rb.antecedents], {}))
    assert (exported[0].operator, exported[0].term, exported[0].terms) == ("at_least", term0, [term0, "High"])
    key = (((name0, f"at least {term0}"),), "mid")  # the consensus finds the condition by its text, as a code
    consensus = cons.build_consensus_model(model, [key], {key: 1.0})
    assert classifier_rule_sets(consensus, LABELS) == [key]
    rb_c = get_master_rulebase(consensus)
    assert xf.rule_conditions(rb_c.get_rules()[0], rb_c.antecedents)[0].operator == "at_least"


@needs_ordinal
def test_a_regressor_fitted_with_the_option_has_ordinal_variables(complete_rows):
    model = fit_fuzzy(complete_rows.reset_index(drop=True), seed=1, ordinal_conditions=True)
    rb = model.get_rulebase()
    assert all(v.ordinal for v in rb.antecedents)
    rb.rules[0].antecedents[0] = 3
    assert any("at least" in term for _, term in rule_signatures(rb)[0])
    exported = dict(_conditions(rb.rules[0], rb.antecedents, [str(v.name) for v in rb.antecedents], {}))
    assert exported[0].operator == "at_least" and len(exported[0].terms) == 2


# ------------------------------------------------------------------------------------ the decision rule


def _arm(values, conditions, water=False, rmse=None):
    metric = "mae" if water else "macro_f1"
    return [{"seed": s, "total_conditions": c, "n_rules": 5, "mean_conditions": c / 5, "n_rules_ordinal": 0,
             "n_conditions_ordinal": 0, "n_rules_compound": 0, "n_conditions_compound": 0, "shape": [10, 2],
             "fit_seconds": 1.0,
             "validation": {metric: v, **({"rmse": rmse[s]} if water else {})}}
            for s, (v, c) in enumerate(zip(values, conditions, strict=True))]


def test_outcome_follows_the_registered_rule():
    assert outcome(0.0101, 0.01, 10, 20) == "B"  # a gain beyond the tolerance wins whatever the size
    assert outcome(0.0100, 0.01, 10, 20) == "A"  # exactly the tolerance is a tie, and B has more conditions
    assert outcome(0.0100, 0.01, 10, 9) == "B"  # a tie with strictly fewer conditions
    assert outcome(-0.01, 0.01, 10, 9) == "B"  # the worst tie is still a tie
    assert outcome(0.003, 0.01, 10, 10) == "A"  # equal conditions: A stays
    assert outcome(-0.0101, 0.01, 10, 1) == "A"  # clearly worse never wins


def test_the_selected_fit_is_the_best_seed_and_ties_go_to_the_lowest_seed():
    s = arm_summary(_arm([0.50, 0.55, 0.55], [10, 20, 5]), water=False)
    assert s["selected_seed"] == 1 and s["M"] == 0.55 and s["C"] == 20
    assert s["median_M"] == 0.55 and s["median_C"] == 10
    w = arm_summary(_arm([0.62, 0.61, 0.64], [9, 8, 7], water=True, rmse=[0.95, 0.99, 0.93]), water=True)
    assert w["selected_seed"] == 2 and w["M"] == 0.64  # the published seed is the lowest RMSE; M is the MAE


def test_a_classifier_decision_uses_the_selected_seed_and_checks_the_medians():
    a = arm_summary(_arm([0.50, 0.49, 0.48], [10, 10, 10]), water=False)
    b = arm_summary(_arm([0.53, 0.47, 0.46], [12, 12, 12]), water=False)
    d = decide_task(a, b, water=False, tau_f1=0.01, tau_share=0.01)
    assert d["winner"] == "B" and d["primary"]["D"] == pytest.approx(0.03)  # best seed against best seed
    assert d["median_check"]["outcome"] == "A" and d["robust"] is False  # medians 0.49 against 0.47


def test_a_water_decision_is_a_one_percent_reduction_of_the_reference_mae():
    rmse = [0.9, 0.9, 0.9]
    a = arm_summary(_arm([0.620, 0.630, 0.640], [30, 30, 30], water=True, rmse=rmse), water=True)
    b = arm_summary(_arm([0.613, 0.620, 0.650], [30, 30, 30], water=True, rmse=rmse), water=True)
    d = decide_task(a, b, water=True, tau_f1=0.01, tau_share=0.01)  # selected seed 0: 0.620 against 0.613
    assert d["primary"]["D"] == pytest.approx(0.007) and d["primary"]["tau"] == pytest.approx(0.0062)
    assert d["winner"] == "B"  # 1.13 % lower error
    b2 = arm_summary(_arm([0.615, 0.620, 0.650], [31, 30, 30], water=True, rmse=rmse), water=True)
    assert decide_task(a, b2, water=True, tau_f1=0.01, tau_share=0.01)["winner"] == "A"  # 0.8 % and more conditions
    b3 = arm_summary(_arm([0.615, 0.620, 0.650], [29, 30, 30], water=True, rmse=rmse), water=True)
    assert decide_task(a, b3, water=True, tau_f1=0.01, tau_share=0.01)["winner"] == "B"  # a tie with fewer conditions


def test_the_experiment_config_lists_the_ten_published_tasks_and_their_configs():
    cfg = load_config()
    assert ARMS == ("A", "B") and cfg.seeds == [0, 1, 2]
    assert [t.kind for t in cfg.tasks].count("mixture") == 8
    assert {t.task_id for t in cfg.tasks if t.kind != "mixture"} == {"nyc_pickups_h6", "uk_water_do"}
    assert all((REPO_ROOT / t.config).exists() for t in cfg.tasks)


# ------------------------------------------------------------------------- Amendment 1: roles of the inputs


def test_the_roles_of_the_inputs_follow_amendment_1():
    cfg = load_config()
    by_id = {t.task_id: t for t in cfg.tasks}
    de1, de6, nyc, water = by_id["de_no2_h1"], by_id["de_no2_h6"], by_id["nyc_pickups_h3"], by_id["uk_water_do"]
    nine = ["no2_last", "no2_lag1h", "no2_lag3h", "no2_lag24h", "wind_speed", "temperature", "relative_humidity",
            "valid_hour_local", "valid_weekday"]
    assert quantity_variables(de1, nine) == nine[:7]
    assert quantity_variables(de6, ["no2_yday_valid", "no2_last", "valid_hour_local", "wind_speed"]) == [
        "no2_yday_valid", "no2_last", "wind_speed"]
    assert "local_hour" not in quantity_variables(nyc, ["rel_lag1", "local_hour", "local_dow", "rel_mean24h"])
    assert quantity_variables(water, ["ammoniacal_nitrogen", "water_temperature", "days_from_midwinter", "ph",
                                      "local_hour"]) == ["ammoniacal_nitrogen", "water_temperature",
                                                         "days_from_midwinter", "ph"]  # the season is a quantity
    with pytest.raises(ValueError):
        quantity_variables(de6, ["no2_last"])  # the clock inputs of the config are not inputs of this model


def test_compound_terms_are_runs_of_adjacent_terms_with_the_partition_files_names():
    import json

    def terms(path, feature):
        doc = json.loads((REPO_ROOT / path).read_text())
        return [t["name"] for v in doc["variables"] if feature in v["features"] for t in v["terms"]]

    for spec in load_config().tasks:
        base = {}
        for variable in spec.compound_terms:
            if spec.task_id.startswith("de_"):
                base[variable] = terms("configs/ml/de_partitions.json", variable)
            elif spec.task_id.startswith("nyc_"):
                base[variable] = terms("configs/ml/nyc_partitions.json", variable)
            else:
                base[variable] = ["Low", "Medium", "High"]  # quantile terms of the sampling hour
        check_compound_terms(spec, base)
    de = {t.task_id: t for t in load_config().tasks}["de_no2_h1"]
    hour = de.compound_terms["valid_hour_local"]
    assert [u.terms for u in hour] == [["Night", "Morning rush"], ["Morning rush", "Midday"], ["Midday", "Evening"],
                                       ["Evening", "Night"]]  # four unions, the last wraps midnight
    assert [u.terms for u in de.compound_terms["valid_weekday"]] == [["Saturday", "Sunday"]]
    # the sampling hour of Water covers daytime only (domain 5.4-15.6 h): no union wraps, "High or Low" is not offered
    water = {t.task_id: t for t in load_config().tasks}["uk_water_do"]
    assert [u.terms for u in water.compound_terms["local_hour"]] == [["Low", "Medium"], ["Medium", "High"]]
    assert water.cyclic_variables == [] and all(t.cyclic_variables for t in load_config().tasks if t != water)
    wrap = water.model_copy(update={"compound_terms": {"local_hour": [
        CompoundTerm(terms=["High", "Low"], name="High or Low", name_es="x", name_en="x")]}})
    with pytest.raises(ValueError, match="adjacent"):
        check_compound_terms(wrap, {"local_hour": ["Low", "Medium", "High"]})


def test_a_bad_compound_term_is_refused():
    spec = load_config().tasks[0]
    bad = spec.model_copy(update={"compound_terms": {"valid_hour_local": [
        CompoundTerm(terms=["Night", "Midday"], name="Odd", name_es="x", name_en="x")]}})
    with pytest.raises(ValueError, match="adjacent"):
        check_compound_terms(bad, {"valid_hour_local": ["Night", "Morning rush", "Midday", "Evening"]})
    clash = spec.model_copy(update={"compound_terms": {"valid_hour_local": [
        CompoundTerm(terms=["Night", "Morning rush"], name="Night", name_es="x", name_en="x")]}})
    with pytest.raises(ValueError, match="unique"):
        check_compound_terms(clash, {"valid_hour_local": ["Night", "Morning rush", "Midday", "Evening"]})


def test_arm_b_options_are_the_quantity_inputs_and_the_compound_terms_of_the_config():
    spec = {t.task_id: t for t in load_config().tasks}["de_no2_h3"]
    nine = ["no2_last", "no2_lag1h", "no2_lag3h", "no2_lag24h", "wind_speed", "temperature", "relative_humidity",
            "valid_hour_local", "valid_weekday"]
    got = arm_b_library_options(spec, nine)
    assert got["ordinal_conditions"] == tuple(nine[:7])
    assert got["compound_terms"]["valid_hour_local"][3] == ("Long night", ["Evening", "Night"])
    assert got["compound_terms"]["valid_weekday"] == [("Weekend", ["Saturday", "Sunday"])]
    params = FuzzyClassifierParams(**got)
    assert params.as_dict()["ordinal_conditions"] == tuple(nine[:7])  # recorded with the fit
    assert "compound_terms" not in FuzzyClassifierParams().as_dict()


@needs_ordinal
def test_a_fit_with_per_variable_options_and_compound_terms_reads_any_of(complete_rows):
    if not xf.has_compound_terms():
        pytest.skip("needs ex-fuzzy 7a0844a")
    rows = complete_rows.reset_index(drop=True)
    y = np.digitize(rows[TARGET].to_numpy(), np.quantile(rows[TARGET], [0.5, 0.85]))
    params = FuzzyClassifierParams(nRules=9, nAnts=2, n_gen=8, pop_size=16, ordinal_conditions=("y_t", "exo_t"),
                                   compound_terms={"hour": [("Low or Medium", ["Low", "Medium"])]})
    model = FuzzyClassifier(params, FEATURE_UNITS).fit(rows[FEATURES], y, LABELS, seed=2)
    rb = get_master_rulebase(model)
    by_name = {str(v.name): v for v in rb.antecedents}
    assert by_name["y_t"].ordinal and by_name["exo_t"].ordinal and not by_name["hour"].ordinal
    assert not by_name["y_lag3"].ordinal and "Low or Medium" in xf.condition_labels(by_name["hour"])
    rules = rb.get_rules()
    hour = FEATURES.index("hour")
    labels = xf.condition_labels(by_name["hour"])
    rules[0].antecedents[hour] = labels.index("Low or Medium")
    conds = xf.rule_conditions(rules[0], rb.antecedents)
    assert [c.text for c in conds if c.feature == hour] == ["Low or Medium"]
    assert [c.operator for c in conds if c.feature == hour] == ["any_of"]
    stats = condition_stats(rules, rb.antecedents, [str(v.name) for v in rb.antecedents], clock=["hour"])
    assert stats["n_conditions_compound"] >= 1 and stats["n_ordinal_on_clock_inputs"] == 0
    exported = dict(_conditions(rules[0], rb.antecedents, [str(v.name) for v in rb.antecedents], {}))
    assert (exported[hour].operator, exported[hour].term, exported[hour].terms) == (
        "any_of", "Low or Medium", ["Low", "Medium"])


def test_the_report_writes_terms_with_their_labels_and_not_the_names_the_fit_gave_them():
    from atlas.compound_terms import CompoundLabel
    from atlas.ml.experiment_ordinal import condition_sentence, term_labels

    water = term_labels("uk_water_do")["ammoniacal_nitrogen"]
    at_most = xf.RuleCondition(0, "at_most", "Medio>L", "at most Medio>L", ("<=L", "Bajo>L", "Medio>L"), 5)
    limit = xf.RuleCondition(0, "is", "<=L", "<=L", ("<=L",), 0)
    assert condition_sentence(at_most, "ammoniacal_nitrogen", water, {}) == (
        "ammoniacal_nitrogen IS at most medium (above the limit)")
    assert condition_sentence(limit, "ammoniacal_nitrogen", water, {}) == "ammoniacal_nitrogen IS ≤ detection limit"
    hour = xf.RuleCondition(1, "any_of", "Early hours", "Early hours", ("Night", "Morning rush"), 4)
    named = {"Early hours": CompoundLabel(label="Madrugada y mañana", label_en="Night and morning")}
    assert condition_sentence(hour, "valid_hour_local", {}, named) == "valid_hour_local IS Night and morning"
    assert condition_sentence(hour, "valid_hour_local", {}, {}) == "valid_hour_local IS Early hours"
