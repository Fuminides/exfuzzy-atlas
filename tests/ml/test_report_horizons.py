"""The horizon report reads summaries of both experiment layouts (ICA / EAQI classes and NYC levels) and ranks nothing on test."""

# ruff: noqa: E501  (long literals)

import json

import pytest

from atlas.ml import report_horizons as R

LABELS = ["a", "b"]


def metrics(f1, nested):
    m = {"macro_f1": f1, "balanced_accuracy": f1 + 0.1, "precision": {"a": 0.5, "b": 0.0}, "recall": {"a": 0.5, "b": 0.0}}
    return {"overall": m, "by_group": {}} if nested else m


def write(root, task, experiment, nested, f1_seeds, persistence):
    base = root / task / "experiments" / experiment
    base.mkdir(parents=True)
    runs = [{"seed": i, "n_rules": 5 + i, "fit_seconds": 10.0, "validation": metrics(f, nested), "test": metrics(f - 0.01, nested)}
            for i, f in enumerate(f1_seeds)]
    both = lambda f: {"validation": metrics(f, nested), "test": metrics(f, nested)}  # noqa: E731
    baselines = {"persistence": both(persistence), ("majority_class" if nested else "climatology_majority_class"): both(0.1),
                 "hist_gradient_boosting": both(0.3), "random_forest": both(0.2)}
    (base / "summary.json").write_text(json.dumps({"labels": LABELS, "chosen": {"nRules": 30, "nAnts": 2, "n_linguistic_variables": 3, "sampling_power": 0.5},
                                                   "runs": runs, "baselines": baselines, "published_seed": 0,
                                                   "rule_stability": {"mean_pairwise_jaccard_rule": 0.1}}))
    period = ({"n_complete": 10, "share": {"a": 0.5, "b": 0.5}} if nested
              else {"n": 10, "used_share": {"a": 0.5, "b": 0.5}})
    (base / "class_distribution.json").write_text(json.dumps({"periods": {p: period for p in ("train", "validation", "test")}}))


def test_f1_by_class_is_zero_when_a_class_is_never_hit():
    assert R.f1_by_class(metrics(0.3, False), LABELS) == [0.5, 0.0]
    assert R.f1_by_class(metrics(0.3, True), LABELS) == [0.5, 0.0]


@pytest.mark.parametrize("territory, nested, task", [("madrid", False, "madrid_no2_h1"), ("nyc", True, "nyc_pickups_h3")])
def test_render_has_a_row_per_horizon_with_the_gap_to_persistence(tmp_path, territory, nested, task):
    write(tmp_path, task, R.TERRITORIES[territory]["experiment"], nested, [0.40, 0.42, 0.44], 0.45)
    text = R.render(territory, tmp_path, None)
    h = int(task.rsplit("_h", 1)[1])
    assert f"| t+{h} h | 0.400 | 0.420 ± 0.020 | 0.450 |" in text  # seed 0, mean ± sd, persistence
    assert "-0.030" in text and "hist_gradient_boosting" in text  # mean − persistence; best tree = highest validation F1


def test_reading_needs_the_same_sign_on_validation_and_a_test_gap_above_the_seed_sd():
    assert R.reading(0.02, 0.03, 0.01) == "above"
    assert R.reading(-0.02, -0.03, 0.01) == "below"
    assert R.reading(0.02, 0.005, 0.01) == "no clear difference"  # inside the seed noise
    assert R.reading(-0.02, 0.03, 0.01) == "no clear difference"  # validation and test disagree


def test_summary_table_has_a_row_per_horizon(tmp_path):
    write(tmp_path, "madrid_no2_h1", "ica2-justified", False, [0.40, 0.42, 0.44], 0.45)
    text = R.summary_table(tmp_path, ["madrid"])
    assert "| Madrid | t+1 h | 0.410 ± 0.020 | 0.450 |" in text  # test F1 = validation F1 - 0.01
