"""AT-041e: Frank and Hall threshold targets, the monotone combiner and the inconsistency rate."""

import numpy as np

from atlas.ml import ordinal as ordn


def test_threshold_targets_are_cumulative():
    y = np.array([0, 1, 2, 3, -1])
    assert ordn.threshold_targets(y, 4).tolist() == [[0, 0, 0], [1, 0, 0], [1, 1, 0], [1, 1, 1], [0, 0, 0]]


def test_combine_highest_and_count_agree_on_consistent_patterns():
    dec = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [1, 1, 1]])
    assert ordn.combine(dec, "highest").tolist() == [0, 1, 2, 3]
    assert ordn.combine(dec, "count").tolist() == [0, 1, 2, 3]
    assert ordn.inconsistency_rate(dec) == 0.0


def test_inconsistent_patterns_are_resolved_by_the_documented_rule():
    dec = np.array([[0, 1, 0], [1, 0, 1], [0, 0, 1]])
    assert ordn.combine(dec, "highest").tolist() == [2, 3, 3]  # the highest threshold decided as exceeded
    assert ordn.combine(dec, "count").tolist() == [1, 2, 1]
    assert ordn.inconsistency_rate(dec) == 1.0
    assert ordn.inconsistency_rate(np.array([[0, 1, 0], [1, 1, 0]])) == 0.5


def test_no_decision_counts_as_not_exceeded_and_all_unknown_is_unknown():
    dec = np.array([[-1, -1, -1], [-1, 1, -1], [1, -1, -1]])
    assert ordn.combine(dec, "highest").tolist() == [-1, 2, 1]
    assert ordn.inconsistency_rate(dec) == 1 / 3  # the unknown first threshold counts as not exceeded


def test_unknown_combiner_is_refused():
    try:
        ordn.combine(np.zeros((1, 3)), "median")
    except ValueError as exc:
        assert "median" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_decisions_with_factors_and_tuning():
    rng = np.random.default_rng(0)
    y = rng.integers(0, 3, 600)  # 3 classes, 2 thresholds
    u = rng.uniform(0.9, 1.1, 600)
    # the 'exceeded' side is five times too weak at both thresholds
    assoc = [np.stack([0.5 * u, np.where(y > t, 0.1 * u, 0.0)], axis=1) for t in range(2)]
    dec = ordn.decisions_with_factors(assoc, [1.0, 1.0])
    assert (ordn.combine(dec) != y).any()
    f = ordn.tune_threshold_factors(assoc, y, 3)
    assert (f > 5.5).all()
    assert (ordn.combine(ordn.decisions_with_factors(assoc, f)) == y).all()
    none = [np.zeros((2, 2)), np.zeros((2, 2))]
    assert (ordn.decisions_with_factors(none, [1, 1]) == -1).all()
