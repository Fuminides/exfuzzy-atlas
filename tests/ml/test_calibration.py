"""AT-041e: per-class factors, recomputed dominance scores, and the exported weights keeping trace parity."""

import numpy as np
import pytest

from atlas.contracts import models as m
from atlas.explain import build_classifier_traces
from atlas.explain.classifier import compute_classifier_activations, rule_classes
from atlas.ml import calibration as cal
from atlas.ml.classification import ClassScheme
from atlas.ml.fuzzy_classifier import FuzzyClassifier, FuzzyClassifierParams
from atlas.ml.rules_export import export_classifier_rules
from atlas.ml.synthetic import FEATURE_UNITS, FEATURES, TARGET

LABELS = ["lo", "mid", "hi"]
SCHEME = ClassScheme.model_validate({
    "name": "toy", "source_url": "https://example.org/toy", "unit": "u",
    "classes": [{"label": "lo", "lower": 0, "upper": 10, "color": "#00FFFF", "description": "d"},
                {"label": "mid", "lower": 11, "upper": 20, "color": "#FFCC00", "description": "d"},
                {"label": "hi", "lower": 21, "upper": 30, "color": "#FF3300", "description": "d"}]})


@pytest.fixture(scope="module")
def rows(complete_rows):
    return complete_rows.reset_index(drop=True)


@pytest.fixture(scope="module")
def y(rows):
    return np.digitize(rows[TARGET].to_numpy(), np.quantile(rows[TARGET], [0.5, 0.85]))


@pytest.fixture(scope="module")
def model(rows, y) -> FuzzyClassifier:
    params = FuzzyClassifierParams(nRules=9, nAnts=2, n_gen=10, pop_size=20)
    return FuzzyClassifier(params, FEATURE_UNITS).fit(rows[FEATURES], y, LABELS, seed=2)


def test_predict_with_factors_scales_columns_and_keeps_unknown():
    assoc = np.array([[0.5, 0.1, 0.0], [0.0, 0.0, 0.0], [0.2, 0.3, 0.9]])
    assert cal.predict_with_factors(assoc, [1, 1, 1]).tolist() == [0, -1, 2]
    assert cal.predict_with_factors(assoc, [1, 10, 1]).tolist() == [1, -1, 1]


def test_coordinate_ascent_recovers_a_threshold():
    """Class 1 always has a smaller association than class 0 (ratio 5 on its own rows): only a factor > 5 separates."""
    rng = np.random.default_rng(0)
    y = rng.integers(0, 2, 2000)
    u = rng.uniform(0.9, 1.1, 2000)
    assoc = np.stack([0.5 * u, np.where(y == 1, 0.1 * u, 0.0)], axis=1)
    assert cal.tune_class_factors(assoc, y, anchor=0).tolist()[0] == 1.0
    f = cal.tune_class_factors(assoc, y, anchor=0)
    assert f[1] > 5.5
    pred = cal.predict_with_factors(assoc, f)
    assert (pred == y).all()


def test_tuning_leaves_a_flat_score_alone():
    assoc = np.array([[1.0, 0.0], [0.0, 1.0]] * 50)
    y = np.array([0, 1] * 50)
    assert cal.tune_class_factors(assoc, y).tolist() == [1.0, 1.0]


def test_cross_fit_uses_the_other_group_only():
    rng = np.random.default_rng(1)
    groups = np.repeat([0, 1], 500)
    y = rng.integers(0, 2, 1000)
    u = rng.uniform(0.9, 1.1, 1000)
    # group 0 needs a large factor for class 1, group 1 needs none: held-out predictions must use the other group's.
    assoc = np.stack([0.5 * u, np.where(y == 1, np.where(groups == 0, 0.1, 0.9) * u, 0.0)], axis=1)
    pred = cal.cross_fit_predictions(assoc, y, groups)
    f0 = cal.tune_class_factors(assoc[groups == 0], y[groups == 0])
    f1 = cal.tune_class_factors(assoc[groups == 1], y[groups == 1])
    assert (pred[groups == 1] == cal.predict_with_factors(assoc[groups == 1], f0)).all()
    assert (pred[groups == 0] == cal.predict_with_factors(assoc[groups == 0], f1)).all()


def test_week_parity_alternates_weeks():
    stamps = np.array(["2024-01-01", "2024-01-08", "2024-01-09", "2024-01-15"], dtype="datetime64[ns]")
    import pandas as pd

    parity = cal.week_parity(pd.DatetimeIndex(stamps, tz="UTC"))
    assert parity[0] != parity[1] and parity[1] == parity[2] and parity[0] == parity[3]


def test_class_max_association_matches_the_library_winner(model, rows):
    X = rows[FEATURES].to_numpy(dtype=float)
    assoc = cal.class_max_association(model, X, 3)
    act = compute_classifier_activations(model, X)
    assert (cal.predict_with_factors(assoc, [1, 1, 1]) == act.prediction).all()


def test_applied_factors_are_rule_weights_and_keep_trace_parity(model, rows):
    """association = firing x weight for the calibrated model, and its prediction is the factor-scaled argmax."""
    factors = np.array([1.0, 2.0, 0.5])  # powers of two: the product is exact, no tie can flip
    scaled = cal.apply_class_factors(model, factors)
    raw = [r.score for r in model.rule_base.get_rules()]
    classes = rule_classes(scaled.rule_base)
    for r, base, c in zip(scaled.rule_base.get_rules(), raw, classes, strict=True):
        assert r.score == base * factors[c] and r.score_raw == base and r.class_factor == factors[c]
    assert [r.score for r in model.rule_base.get_rules()] == raw  # the input model is untouched
    X = rows[FEATURES].head(80)
    traces = build_classifier_traces(
        scaled, X, rows["entity_id"].head(80).tolist(), rows["issued_at_utc"].head(80), class_labels=LABELS,
        model_id="t", task_id="t", horizon_hours=6, target_unit="u", data_version="synthetic-test", synthetic=True)
    for trace in traces:
        for entry in trace.rules:
            assert entry.association_degree == entry.firing_strength * entry.weight
    expected = cal.predict_with_factors(cal.class_max_association(model, X.to_numpy(dtype=float), 3), factors)
    assert (scaled.predict(X) == expected).all()
    assert [t.prediction.label for t in traces] == [None if p < 0 else LABELS[p] for p in expected]


def test_export_carries_the_raw_score_and_the_adjusted_weight(model, rows):
    scaled = cal.apply_class_factors(model, [1.0, 4.0, 0.25])
    columns = cal.rule_metric_columns(scaled)
    assert set(columns) == {"dominance_score_raw", "class_factor"}
    rules = export_classifier_rules(
        scaled, model_id="t", task_id="t", domain=m.Domain.AIR, target_label="T",
        target_scheme=SCHEME.to_target_scheme(),
        horizon_hours=6, data_version="synthetic-test", synthetic=True, feature_units=FEATURE_UNITS,
        rule_metrics=columns)
    for rule, raw, factor in zip(rules.rules, columns["dominance_score_raw"], columns["class_factor"], strict=True):
        assert rule.weight == pytest.approx(raw * factor)
        assert rule.metrics["dominance_score_raw"] == raw and rule.metrics["class_factor"] == factor


def test_factors_need_the_dominance_score_mode(rows, y):
    params = FuzzyClassifierParams(nRules=6, nAnts=2, n_gen=4, pop_size=10, rule_weighting="none")
    unweighted = FuzzyClassifier(params, FEATURE_UNITS).fit(rows[FEATURES], y, LABELS, seed=0)
    with pytest.raises(ValueError, match="ds_mode"):
        cal.apply_class_factors(unweighted, [1, 1, 1])


def test_rescore_uses_the_library_score_on_the_given_rows(model, rows, y):
    from ex_fuzzy import eval_rules

    sub = np.arange(0, len(rows), 2)
    X, yy = rows[FEATURES].to_numpy(dtype=float)[sub], y[sub]
    out = cal.rescore(model, X, yy)
    reference = eval_rules.evalRuleBase(model.rule_base.copy(), X, yy)
    expected = reference.dominance_scores()
    assert np.allclose([r.score for r in out.rule_base.get_rules()], expected)
    assert [tuple(r.antecedents) for r in out.rule_base.get_rules()] == [
        tuple(r.antecedents) for r in model.rule_base.get_rules()]
    assert out.rule_base.get_consequents() == model.rule_base.get_consequents()
