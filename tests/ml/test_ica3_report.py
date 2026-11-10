"""AT-041e: the pre-registered decision rule applied to validation arm files (no data, no fits)."""

import json
from types import SimpleNamespace

import numpy as np
import pytest

from atlas.ml import ica3_report as rep
from atlas.ml.experiment_ica3 import DecisionConfig

LABELS = ["Buena", "Razonablemente buena", "Regular", "Desfavorable o peor"]


def _seed(f1, rules=10, cross=None):
    summary = {"macro_f1": f1, "balanced_accuracy": 0.4, "accuracy": 0.7, "mae_class_index": 0.3,
               "share_off_by_2plus": 0.01, "share_unknown": 0.0,
               "recall": dict.fromkeys(LABELS, 0.3), "precision": dict.fromkeys(LABELS, 0.2)}
    out = {"seed": 0, "validation": summary, "n_rules": rules, "rules": []}
    if cross is not None:
        out["crossfit"] = {**summary, "macro_f1": cross}
    return out


def _arm(name, f1s, jaccard, rules=10, cross=None):
    return {"arm": name, "seeds": [_seed(f, rules, None if cross is None else c) for f, c in
                                   zip(f1s, cross or f1s, strict=True)],
            "stability": None if jaccard is None else {"mean_pairwise_jaccard_rule": jaccard}}


def _ctx(tmp_path, arms):
    (tmp_path / "val").mkdir()
    for name, doc in arms.items():
        (tmp_path / "val" / f"{name}.json").write_text(json.dumps(doc))
    return SimpleNamespace(out=tmp_path, cfg=SimpleNamespace(decision=DecisionConfig()),
                           load_json=lambda n: json.loads((tmp_path / "val" / f"{n}.json").read_text()),
                           exists=lambda n: (tmp_path / "val" / f"{n}.json").exists())


def test_calibrated_arms_are_selected_on_the_cross_fitted_score(tmp_path):
    ctx = _ctx(tmp_path, {
        "base": _arm("base", [0.34, 0.33, 0.34], 0.151),
        "calib": _arm("calib", [0.38, 0.37, 0.38], 0.151, cross=[0.335, 0.33, 0.34]),
        "cons": _arm("cons", [0.36, 0.36, 0.36], 0.30, rules=5)})
    rep.decide(ctx)
    decision = json.loads((tmp_path / "val" / "decision.json").read_text())
    by = {r["arm"]: r for r in decision["arms"]}
    assert by["calib"]["f1_select"] == pytest.approx(np.mean([0.335, 0.33, 0.34]))
    assert not by["calib"]["enters_combination"]  # in-sample gain does not count
    assert by["cons"]["enters_combination"] and decision["chosen"] == "cons" == decision["final_arm"]


def test_an_arm_less_stable_than_the_reference_is_not_eligible(tmp_path):
    ctx = _ctx(tmp_path, {"base": _arm("base", [0.34] * 3, 0.151), "wild": _arm("wild", [0.40] * 3, 0.05)})
    rep.decide(ctx)
    decision = json.loads((tmp_path / "val" / "decision.json").read_text())
    assert decision["chosen"] == "base" and decision["best_eligible"] == "base"


def test_a_small_gain_keeps_the_reference_and_ties_go_to_fewer_rules(tmp_path):
    ctx = _ctx(tmp_path, {"base": _arm("base", [0.34] * 3, 0.151), "a": _arm("a", [0.345] * 3, 0.2)})
    rep.decide(ctx)
    assert json.loads((tmp_path / "val" / "decision.json").read_text())["chosen"] == "base"
    assert rep._ms([0.1, 0.2]) == "0.150 ± 0.071"


def test_stability_gain_enters_when_the_score_does_not_drop(tmp_path):
    ctx = _ctx(tmp_path, {"base": _arm("base", [0.34] * 3, 0.151), "s": _arm("s", [0.335] * 3, 0.25)})
    rep.decide(ctx)
    by = {r["arm"]: r for r in json.loads((tmp_path / "val" / "decision.json").read_text())["arms"]}
    assert by["s"]["enters_combination"]


def test_the_committed_config_is_consistent():
    """Seed sets are disjoint, the feature arms use known inputs, the extra terms exist and pass the partition check."""
    from atlas.ml import extra_features as xf
    from atlas.ml.experiment_ica3 import Ica3Config
    from atlas.ml.partitions import load_partition_file
    from atlas.paths import REPO_ROOT

    cfg = Ica3Config.model_validate_json((REPO_ROOT / "configs/ml/madrid_no2_h6_ica3_experiment.json").read_text())
    seeds = [s for ss in cfg.consensus.seed_sets.values() for s in ss]
    assert len(seeds) == len(set(seeds)) and set(cfg.consensus.seed_sets) == {"A", "B", "C"}
    assert not set(seeds) & set(cfg.base_seeds)
    assert {f for fs in cfg.feature_arms.values() for f in fs} == set(xf.EXTRA_FEATURES)
    assert set(load_partition_file(REPO_ROOT / cfg.extra_partitions)) == set(xf.EXTRA_FEATURES)


def test_post_hoc_arms_are_never_selected(tmp_path):
    ctx = _ctx(tmp_path, {"base": _arm("base", [0.34] * 3, 0.151),
                          "posthoc_cons_p20": _arm("posthoc_cons_p20", [0.45] * 3, 0.9)})
    rep.decide(ctx)
    decision = json.loads((tmp_path / "val" / "decision.json").read_text())
    assert [r["arm"] for r in decision["arms"]] == ["base"] and decision["chosen"] == "base"
