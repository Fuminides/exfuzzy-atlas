"""AT-041e: stability selection counts, consensus rule bases built with the public ex_fuzzy classes."""

import numpy as np
import pytest

from atlas.explain.classifier import rule_classes
from atlas.ml import calibration as cal
from atlas.ml import consensus as cons
from atlas.ml.evaluation import classifier_rule_sets
from atlas.ml.fuzzy_classifier import FuzzyClassifier, FuzzyClassifierParams
from atlas.ml.synthetic import FEATURE_UNITS, FEATURES, TARGET

LABELS = ["lo", "mid", "hi"]
R1 = ((("a", "Low"),), "lo")
R2 = ((("a", "High"), ("b", "Low")), "hi")
R3 = ((("b", "High"),), "mid")


def test_frequencies_count_each_fit_once():
    f = cons.selection_frequencies([[R1, R1, R2], [R1], [R2, R3], []])
    assert f == {R1: 0.5, R2: 0.5, R3: 0.25}


def test_consensus_threshold_is_inclusive_and_float_safe():
    f = cons.selection_frequencies([[R1]] * 3 + [[R2]] * 7)  # R1 = 3/10, R2 = 7/10
    assert cons.consensus_keys(f, 0.3) == [R2, R1]  # class label 'hi' < 'lo'
    assert cons.consensus_keys(f, 0.5) == [R2]
    assert cons.consensus_keys(f, 0.8) == []
    with pytest.raises(ValueError):
        cons.consensus_keys(f, 0.0)


def test_consensus_order_is_class_label_then_frequency():
    f = {R2: 0.9, R1: 0.4, R3: 0.9, ((("a", "Mid"),), "lo"): 0.8}
    keys = cons.consensus_keys(f, 0.3)
    assert [k[1] for k in keys] == ["hi", "lo", "lo", "mid"]
    assert [f[k] for k in keys if k[1] == "lo"] == [0.8, 0.4]


def test_jaccard_of_rule_sets():
    assert cons.jaccard([R1, R2], [R2, R3]) == pytest.approx(1 / 3)
    assert cons.jaccard([], []) == 1.0
    assert cons.pairwise_jaccard([[R1], [R1], [R2]]) == [1.0, 0.0, 0.0]


def test_best_of_takes_the_first_k_and_the_earliest_tie():
    assert cons.best_of([0.1, 0.5, 0.5, 0.9], 3) == 1
    assert cons.best_of([0.1, 0.5, 0.5, 0.9], 4) == 3


@pytest.fixture(scope="module")
def pool(complete_rows):
    rows = complete_rows.reset_index(drop=True)
    y = np.digitize(rows[TARGET].to_numpy(), np.quantile(rows[TARGET], [0.5, 0.85]))
    params = FuzzyClassifierParams(nRules=9, nAnts=2, n_gen=10, pop_size=20)
    models = [FuzzyClassifier(params, FEATURE_UNITS).fit(rows[FEATURES], y, LABELS, seed=s) for s in (1, 2, 3)]
    return rows, y, models


def test_the_consensus_rule_base_holds_exactly_the_selected_rules(pool):
    rows, y, models = pool
    cons.check_same_variables(models)
    sets = cons.pool_rule_sets(models, LABELS)
    freqs = cons.selection_frequencies(sets)
    keys = cons.consensus_keys(freqs, 1 / 3)
    consensus = cons.build_consensus_model(models[0], keys, freqs)
    got = classifier_rule_sets(consensus, LABELS)
    assert sorted(got) == sorted(keys) and len(got) == len(set(got))
    classes = rule_classes(consensus.rule_base)
    assert classes == sorted(classes)  # class-major order, as the library's own rule bases
    assert [r.selection_frequency for r in consensus.rule_base.get_rules()] == [
        freqs[(a, c)] for a, c in got]
    scored = cal.rescore(consensus, rows[FEATURES].to_numpy(dtype=float), y)
    assert all(r.score >= 0 for r in scored.rule_base.get_rules())
    assert cal.rule_metric_columns(scored)["selection_frequency"] == [freqs[k] for k in got]
    assert scored.predict(rows[FEATURES]).shape == (len(rows),)


def test_a_class_without_consensus_rules_still_predicts(pool):
    rows, y, models = pool
    sets = cons.pool_rule_sets(models, LABELS)
    freqs = cons.selection_frequencies(sets)
    keys = [k for k in cons.consensus_keys(freqs, 1 / 3) if k[1] != "hi"]
    consensus = cal.rescore(cons.build_consensus_model(models[0], keys, freqs), rows[FEATURES].to_numpy(dtype=float), y)
    pred = consensus.predict(rows[FEATURES])
    assert 2 not in set(pred.tolist()) and len(consensus.rule_base.rule_bases) == 3


def test_variables_that_differ_are_refused(pool, complete_rows):
    rows, y, models = pool
    other = FuzzyClassifier(FuzzyClassifierParams(nRules=9, nAnts=2, n_gen=4, pop_size=10), FEATURE_UNITS).fit(
        rows[FEATURES].iloc[::3], y[::3], LABELS, seed=0, partition_reference=rows[FEATURES].iloc[::3] * 2)
    with pytest.raises(ValueError, match="share linguistic variables"):
        cons.check_same_variables([models[0], other])
