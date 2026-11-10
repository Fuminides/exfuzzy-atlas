"""Tables of the FX retrain from hand-made summaries (no fitting)."""

import numpy as np

from atlas.ml.report_fx import (
    WATER_HEAD,
    classifier_row,
    classifier_table,
    mean_sd,
    pm,
    usage_comparison_table,
    usage_of_features,
    validation_block,
    water_row,
)


def _block(f1):
    return {"macro_f1": f1, "balanced_accuracy": 0.4, "accuracy": 0.7, "recall": {"Regular": 0.2},
            "precision": {"Regular": 0.1}}


def _summary(f1s, nested=False):
    runs = [{"seed": i, "n_rules": 10 + i, "validation": {"overall": _block(f)} if nested else _block(f),
             "rules": [{"antecedents": [["local_hour", "Mañana"], ["rel_lag1", "alta"]], "class": "alta"},
                       {"antecedents": [["rel_lag1", "baja"]], "class": "baja"}]} for i, f in enumerate(f1s)]
    return {"runs": runs, "rule_stability": {"mean_pairwise_jaccard_rule": 0.15}}


def test_mean_and_sample_sd():
    assert mean_sd([1, 2, 3]) == (2.0, 1.0)
    assert mean_sd([5]) == (5.0, 0.0) and pm([0.3, 0.5]) == "0.400 ± 0.141"


def test_classifier_row_reads_both_summary_layouts():
    for nested in (False, True):
        summary = _summary([0.30, 0.34, 0.32], nested)
        assert validation_block(summary["runs"][0])["macro_f1"] == 0.30
        row = classifier_row("a", summary, ("Regular",))
        assert row[1] == "0.320 ± 0.020" and row[-3] == "11.0" and row[-1] == "0.300, 0.340, 0.320"
    table = classifier_table({"a": _summary([0.3, 0.4]), "b": _summary([0.5, 0.5])}, ("Regular",))
    assert "Regular recall" in table and table.count("\n") == 3


def test_usage_of_features_counts_rules_per_seed():
    assert usage_of_features(_summary([0.3, 0.3]), ["local_hour", "local_dow"]) == [1, 1]
    assert usage_of_features(_summary([0.3]), ["local_dow"]) == [0]


def test_water_row_counts_duplicates_and_outside_rules():
    rule_a, rule_b = [["ph", "Low"]], [["ph", "High"]]
    runs = [{"seed": 0, "validation_rmse": 0.9, "validation": {"overall": {"rmse": 0.9, "mae": 0.6, "r2": 0.7}},
             "rules": [rule_a, rule_a, rule_b]},
            {"seed": 1, "validation_rmse": 1.0, "validation": {"overall": {"rmse": 1.0, "mae": 0.7, "r2": 0.6}},
             "rules": [rule_a, rule_b]}]
    support = {0: [{"status": "within"}, {"status": "outside"}, {"status": "no_support"}],
               1: [{"status": "outside"}, {"status": "outside"}]}
    row = water_row("x", {"runs": runs}, support)
    assert len(row) == len(WATER_HEAD)
    assert row[4:9] == ["3/2", "2/2", "1/0", "1/2", "1/0"] and np.isclose(float(row[1].split()[0]), 0.95)


def test_usage_comparison_sums_the_seeds_and_marks_missing_terms():
    clip = {"hour": {"Noche": [1, 0, 2], "Tarde": [0, 0, 0]}}
    remap = {"hour": {"Noche": [0, 1, 0], "Tarde": [3, 1, 0]}}
    table = usage_comparison_table({"clip": clip, "remap": remap}, ["hour", "absent"])
    assert table.splitlines()[0] == "| feature | term index | term | clip | remap |"
    assert "| hour | 0 | Noche | 3 | 1 |" in table and "| hour | 1 | Tarde | 0 | 4 |" in table
    assert "absent" not in table
