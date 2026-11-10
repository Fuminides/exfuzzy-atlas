"""FX retrain checks: term usage of a classifier, consequent support of a TSK rule base, breakpoint parity."""

import numpy as np
import pytest
from ml_helpers import build_rulebase

from atlas.ml import exfuzzy_features as xf
from atlas.ml.evaluation import classifier_rule_sets
from atlas.ml.fuzzy_classifier import FuzzyClassifier, FuzzyClassifierParams
from atlas.ml.fx_checks import (
    breakpoint_parity,
    classifier_term_usage,
    consequent_support,
    decoded_term_table,
)
from atlas.ml.partitions import Band, FixedPartition, load_partition_file
from atlas.ml.synthetic import FEATURE_UNITS, FEATURES, TARGET
from atlas.paths import REPO_ROOT


@pytest.fixture(scope="module")
def classifier(complete_rows):
    rows = complete_rows.reset_index(drop=True)
    y = np.digitize(rows[TARGET].to_numpy(), np.quantile(rows[TARGET], [0.5, 0.85]))
    params = FuzzyClassifierParams(nRules=9, nAnts=2, n_gen=8, pop_size=16)
    return FuzzyClassifier(params, FEATURE_UNITS).fit(rows[FEATURES], y, ["lo", "mid", "hi"], seed=2)


def test_term_usage_lists_every_term_and_counts_every_antecedent(classifier):
    usage = classifier_term_usage(classifier)
    assert list(usage) == FEATURES
    assert all(len(terms) == 3 for terms in usage.values())  # three quantile terms per input
    n_antecedents = sum(len(a) for a, _ in classifier_rule_sets(classifier, ["lo", "mid", "hi"]))
    assert sum(sum(terms.values()) for terms in usage.values()) == n_antecedents > 0


def test_consequent_support_flags_rules_outside_the_rows_they_cover():
    # rule 0 covers a == Low rows (a < 2); rule 1 covers a == High rows (a > 6); b is unused
    rb = build_rulebase([[0, -1], [1, -1], [-1, 1]], [10.0, 50.0, 30.0])
    rng = np.random.default_rng(0)
    X = np.column_stack([rng.uniform(0, 10, 600), rng.uniform(0, 10, 600)])
    y = np.where(X[:, 0] < 4, rng.normal(10, 0.5, 600), rng.normal(20, 0.5, 600))
    result = consequent_support(rb, X, y, min_rows=30)
    assert [r["status"] for r in result] == ["within", "outside", "outside"]
    assert result[0]["lo"] < 10 < result[0]["hi"] and result[1]["consequent"] == 50.0
    assert all(r["n_covered"] > 30 for r in result)
    sparse = consequent_support(rb, X[:20], y[:20], min_rows=30)
    assert {r["status"] for r in sparse} == {"no_support"} and sparse[0]["lo"] is None


NEEDS_PR31 = pytest.mark.skipif(not xf.has_breakpoint_partition(), reason="needs ex_fuzzy PR 31 (integration build)")


@NEEDS_PR31
def test_breakpoint_parity_is_exact_when_shoulder_and_gap_make_the_ramps_complementary():
    bands = [Band(name="Noche", lower=0, upper=6), Band(name="Dia", lower=7, upper=16),
             Band(name="Tarde", lower=17, upper=23)]
    hour = FixedPartition(feature="hour", shoulder=1.0, domain=(0, 23), bands=bands)
    result = breakpoint_parity(hour)
    assert result["identical_parameters"] and result["max_abs_difference"] < 1e-9


@NEEDS_PR31
def test_ica_terms_are_not_a_breakpoint_partition():
    """The Atlas terms keep membership 1 on the whole band and overlap over the shoulders: another family."""
    ica = load_partition_file(REPO_ROOT / "configs/ml/madrid_partitions.json")["no2_last"]
    result = breakpoint_parity(ica)
    assert not result["identical_parameters"] and result["max_abs_difference"] > 0.3


def test_decoded_term_table_follows_the_decoder_of_the_installed_library():
    three, five = decoded_term_table([3, 5, 3])[:2]
    if xf.has_proportional_term_remap():
        assert (three, five) == ([0, 0, 1, 1, 2], [0, 1, 2, 3, 4])  # (g * 3) // 5; identity for n == M
    elif xf.has_term_bound_fix():
        assert (three, five) == ([0, 1, 2, 2, 2], [0, 1, 2, 3, 4])  # clipped to the last term
    else:  # 3.3.1: slot 0 is bounded by the 3 terms of the first feature
        assert three == [0, 1, 2]
