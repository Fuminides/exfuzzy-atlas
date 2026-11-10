"""AT-041g: nested class sampler, timing helpers and the learning-curve config. Synthetic data only."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from atlas.ml import eval_timing
from atlas.ml.classification import class_counts, class_quotas, class_sample, nested_class_sample
from atlas.ml.learning_curve import Arm, LearningCurveConfig, arm_rows

CONFIG = Path(__file__).resolve().parents[2] / "configs" / "ml" / "madrid_no2_h6_learning_curve.json"


def _rows(n=40000, seed=0):
    rng = np.random.default_rng(seed)
    y = rng.choice(4, n, p=[0.7, 0.2, 0.08, 0.02])
    stamps = pd.DatetimeIndex(pd.Timestamp("2020-01-01", tz="UTC") + pd.to_timedelta(rng.permutation(n), unit="h"))
    return y, rng.choice(["A", "B", "C"], n), stamps


# ---------------------------------------------------------------------------------------------- sampler


def test_class_quotas_match_class_sample_sizes_and_cap_at_class_size():
    y, e, t = _rows()
    counts = class_counts(y, 4)
    for power in (1.0, 0.5, 0.0):
        quota = class_quotas(counts, 3000, power)
        assert quota.sum() == 3000 and (quota <= counts).all()
        assert np.bincount(y[class_sample(y, e, t, 3000, seed=2, power=power)], minlength=4).tolist() == quota.tolist()
    # a class with 30 rows is taken whole and the rest redistributed
    assert class_quotas(np.array([5000, 3000, 30]), 1000, 0.0).tolist()[2] == 30
    assert class_quotas(np.array([5000, 3000, 30]), 1000, 0.0).sum() == 1000


def test_nested_sample_sizes_are_exact_and_samples_are_nested():
    y, e, t = _rows()
    sizes = (3000, 6000, 12000)
    samples = [nested_class_sample(y, e, t, n, seed=7, power=0.5) for n in sizes]
    for n, s in zip(sizes, samples, strict=True):
        assert len(s) == n and len(np.unique(s)) == n and (np.diff(s) > 0).all()
        assert np.bincount(y[s], minlength=4).tolist() == class_quotas(class_counts(y, 4), n, 0.5).tolist()
    assert set(samples[0]) <= set(samples[1]) <= set(samples[2])
    again = nested_class_sample(y, e, t, 6000, seed=7, power=0.5)
    assert (again == samples[1]).all()  # reproducible
    other = nested_class_sample(y, e, t, 6000, seed=8, power=0.5)
    assert len(set(other) & set(samples[1])) < 6000  # the seed changes the draw


def test_nested_sample_class_shares_follow_the_power():
    y, e, t = _rows()
    nat = np.bincount(y[nested_class_sample(y, e, t, 4000, seed=1, power=1.0)], minlength=4)
    sq = np.bincount(y[nested_class_sample(y, e, t, 4000, seed=1, power=0.5)], minlength=4)
    assert np.abs(nat / 4000 - class_counts(y, 4) / len(y)).max() < 0.01
    assert nat[3] < sq[3] and nat[0] > sq[0]


def test_nested_sample_is_stratified_over_entity_x_month_blocks():
    y, e, t = _rows()
    for n in (3000, 9000):
        s = nested_class_sample(y, e, t, n, seed=3, power=0.5)
        block = pd.Series(e).astype(str) + "|" + pd.Series(t.year * 100 + t.month).astype(str)
        for k in range(4):
            members = np.flatnonzero(y == k)
            quota = int((y[s] == k).sum())
            size = block.iloc[members].value_counts()
            got = block.iloc[s[y[s] == k]].value_counts().reindex(size.index).fillna(0)
            expected = size * quota / len(members)
            assert (got - expected).abs().max() <= 1.0 + 1e-9  # proportional to within one row


def test_nested_sample_needs_utc_times():
    y, e, t = _rows(500)
    with pytest.raises(ValueError):
        nested_class_sample(y, e, t.tz_localize(None), 100, seed=0, power=0.5)


# ---------------------------------------------------------------------------------------------- timing


def test_time_repeated_counts_calls_and_reports_median():
    calls = []
    synced = []
    out = eval_timing.time_repeated(lambda: calls.append(1), repeats=4, warmup=2, sync=lambda: synced.append(1))
    assert len(calls) == 6 and len(synced) == 6 and len(out["seconds"]) == 4
    assert out["min"] <= out["median"] and out["repeats"] == 4
    with pytest.raises(ValueError):
        eval_timing.time_repeated(lambda: None, repeats=0)


def test_cost_and_extrapolation_are_linear():
    cost = eval_timing.cost_per_row(0.6, 30_000, 60)
    assert cost == pytest.approx(0.6 / 1_800_000)
    evaluations = eval_timing.n_evaluations(150, 60)
    assert evaluations == 9060
    assert eval_timing.extrapolate_fit(cost, 60_000, evaluations) == pytest.approx(
        2 * eval_timing.extrapolate_fit(cost, 30_000, evaluations))
    assert eval_timing.extrapolate_fit(cost, 30_000, evaluations) == pytest.approx(0.6 * 9060 / 60)
    assert eval_timing.linearity([1, 2, 4], [1.0, 2.0, 4.0]) == [1.0, 1.0, 1.0]
    assert eval_timing.linearity([1, 2], [1.0, 3.0]) == [1.0, 1.5]
    with pytest.raises(ValueError):
        eval_timing.cost_per_row(1.0, 0, 5)


def test_time_generation_on_a_toy_problem_runs_the_cpu_routes():
    from ex_fuzzy import utils

    rng = np.random.default_rng(0)
    X = rng.random((400, 4))
    y = (X[:, 0] + X[:, 1] > 1).astype(int) + (X[:, 2] > 0.8).astype(int)
    variables = utils.construct_partitions(pd.DataFrame(X, columns=list("abcd")), n_partitions=3)
    problem = eval_timing.build_problem(X, y, variables, n_rules=6, n_ants=2, n_classes=3)
    genes = eval_timing.random_population(problem, 8, seed=0)
    assert genes.shape == (8, len(problem.xl)) and (genes >= problem.xl).all() and (genes <= problem.xu).all()
    out = eval_timing.time_generation(problem, genes, repeats=2, routes=["cpu_batched", "cpu_scalar"])
    assert out["n_rows"] == 400 and out["n_candidates"] == 8
    for route in ("cpu_batched", "cpu_scalar"):
        assert out[route]["median"] > 0 and out[route]["per_row_candidate"] > 0
    # the two exact CPU routes agree (scores versus fitness = 1 - score)
    from ex_fuzzy._fitness import _fitness_cache_scope

    with _fitness_cache_scope(problem, True, 8):
        assert np.array_equal(1 - problem._batched_scores(genes), problem._scalar_scores(genes))


def test_device_row_limit_follows_the_library_formula():
    class P:
        nRules = 60
        X = np.zeros((1, 9))

    limit = eval_timing.device_row_limit(P(), free_bytes=7 * 2**30)
    per_row = 8 * 16 * 60
    assert 0 < limit < 918_601  # the whole training period does not fit with 60 rules
    assert limit * per_row + 2 * 60**2 * 9 <= int(7 * 2**30 * 0.35) < (limit + 1) * per_row + 2 * 60**2 * 9
    assert eval_timing.device_row_limit(P(), free_bytes=1000) == 0


# ---------------------------------------------------------------------------------------------- config


def test_committed_config_is_the_at041d_shape_with_distinct_arms():
    config = LearningCurveConfig.model_validate_json(CONFIG.read_text())
    assert (config.shape.nRules, config.shape.nAnts, config.n_gen, config.pop_size) == (60, 4, 150, 60)
    assert config.seeds == [0, 1, 2] and config.experiment_id.startswith("lc-")
    names = [a.name for a in config.arms]
    assert len(set(names)) == len(names) and {"n30k", "n60k", "n120k", "n30k_pub", "full_natural"} <= set(names)
    base = json.loads((CONFIG.parents[2] / config.base_config).read_text())
    assert base["experiment_id"] != config.experiment_id  # nothing existing is overwritten


def test_arm_rows_uses_training_positions_and_the_requested_sampler():
    y, e, t = _rows(8000)

    class D:
        frame = pd.DataFrame({"entity_id": e})
        issued = t
        train_pos = np.arange(1000, 8000)

    class CD:
        data = D()
        y_class = y

    nested = arm_rows(CD(), Arm(name="a", sampler="nested", n_rows=1200), 5)
    assert len(nested) == 1200 and nested.min() >= 1000
    assert len(arm_rows(CD(), Arm(name="b", sampler="published", n_rows=1200), 5)) == 1200
    assert (arm_rows(CD(), Arm(name="c", sampler="all"), 5) == D.train_pos).all()
    with pytest.raises(ValueError):
        arm_rows(CD(), Arm(name="d", sampler="nested"), 5)
