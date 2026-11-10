"""AT-041h publication: pruning of rules that decide no row, unweighted export and trace parity with ex_fuzzy."""

import numpy as np
import pytest
from test_calibration import SCHEME

from atlas.contracts import models as m
from atlas.explain import build_classifier_traces
from atlas.explain.classifier import compute_classifier_activations, rule_ids
from atlas.ml.experiment_ica4 import prune_never_deciding
from atlas.ml.fuzzy_classifier import FuzzyClassifier, FuzzyClassifierParams
from atlas.ml.rules_export import export_classifier_rules
from atlas.ml.synthetic import FEATURE_UNITS, FEATURES, TARGET

LABELS = ["lo", "mid", "hi"]


@pytest.fixture(scope="module")
def rows(complete_rows):
    return complete_rows.reset_index(drop=True)


@pytest.fixture(scope="module")
def unweighted(rows) -> FuzzyClassifier:
    y = np.digitize(rows[TARGET].to_numpy(), np.quantile(rows[TARGET], [0.5, 0.85]))
    params = FuzzyClassifierParams(nRules=12, nAnts=2, n_gen=10, pop_size=20, rule_weighting="none")
    return FuzzyClassifier(params, FEATURE_UNITS).fit(rows[FEATURES], y, LABELS, seed=3)


def test_pruning_drops_exactly_the_rules_that_never_win_and_keeps_every_prediction(rows, unweighted):
    X = rows[FEATURES].to_numpy(dtype=float)
    half = X[: len(X) // 2]
    act = compute_classifier_activations(unweighted, half)
    wins = np.bincount(act.winner[act.winner >= 0], minlength=len(act.weights))
    pruned, removed = prune_never_deciding(unweighted, half)
    assert [r["rule_id"] for r in removed] == [rule_ids(unweighted.rule_base)[i] for i in np.flatnonzero(wins == 0)]
    assert len(pruned.rule_base.get_rules()) == len(act.weights) - len(removed)
    np.testing.assert_array_equal(compute_classifier_activations(pruned, half).prediction, act.prediction)
    assert len(unweighted.rule_base.get_rules()) == len(act.weights)  # the original is untouched


def test_unweighted_rules_export_weight_one_and_association_equals_firing(rows, unweighted):
    rules = export_classifier_rules(unweighted, model_id="m", task_id="t", domain=m.Domain.AIR, target_label="ICA",
                                    target_scheme=SCHEME.to_target_scheme(), horizon_hours=6, data_version="v")
    assert rules.inference.rule_weighting == "none"
    assert all(r.weight == 1.0 and "peso" not in r.text for r in rules.rules)
    act = compute_classifier_activations(unweighted, rows[FEATURES].to_numpy(dtype=float)[:200])
    np.testing.assert_array_equal(act.association, act.firing)


def test_trace_winner_is_the_first_rule_with_the_largest_firing_like_native_ex_fuzzy(rows, unweighted):
    X = rows[FEATURES].iloc[:300]
    traces = build_classifier_traces(
        unweighted, X, ["e"] * len(X), rows["issued_at_utc"].iloc[:300], class_labels=LABELS, model_id="m",
        task_id="t", horizon_hours=6, target_unit="u", data_version="v")
    native = unweighted.predict(X)
    firing = compute_classifier_activations(unweighted, X.to_numpy(dtype=float)).firing
    ids = rule_ids(unweighted.rule_base)
    for i, tr in enumerate(traces):
        if native[i] < 0:
            assert tr.prediction.winning_rule_id is None
            continue
        first = int(np.argmax(firing[i]))  # the first of the rules with the largest firing (class-major order)
        assert tr.prediction.winning_rule_id == ids[first] and tr.prediction.label == LABELS[native[i]]
