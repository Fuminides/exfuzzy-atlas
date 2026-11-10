"""AT-041i: the pre-registered decision rule of the mixture-of-rules experiment, and the opt-in classifier options."""

import numpy as np
import pytest

from atlas.ml import exfuzzy_features as xf
from atlas.ml.experiment_mixture import ARMS, DecisionConfig, decide_arms
from atlas.ml.fuzzy_classifier import FuzzyClassifierParams


def _doc(name, f1, active=8.0):
    seeds = [{"seed": s, "validation": {"macro_f1": v}} for s, v in enumerate(f1)]
    doc = {"arm": name, "seeds": seeds, "mean": float(np.mean(f1)), "sd": float(np.std(f1, ddof=1)),
           "min": float(np.min(f1))}
    if ARMS[name].mixture:
        doc["mean_active"] = active
    return doc


def _docs(**arms):
    base = {"served": [0.40, 0.41, 0.42], "mix_served_nonneg": [0.40, 0.41, 0.42],
            "mix_served_free": [0.40, 0.41, 0.42], "mix_search_nonneg": [0.40, 0.41, 0.42],
            "mix_search_free": [0.40, 0.41, 0.42], "search_winning": [0.40, 0.41, 0.42]}
    base.update({k: v for k, v in arms.items() if not k.startswith("active_")})
    return {n: _doc(n, f, arms.get(f"active_{n}", 8.0)) for n, f in base.items()}


def test_nothing_wins_without_the_margin_and_the_best_mixture_is_named_for_information():
    out = decide_arms(_docs(mix_search_free=[0.415, 0.425, 0.435]), DecisionConfig(), 3)  # +0.015
    assert out["chosen"] is None and out["proposed_seed"] is None
    assert out["information_arm"] == "mix_search_free"
    assert out["arms"]["mix_search_free"]["margin"] == 0.02 and not out["arms"]["mix_search_free"]["wins"]
    assert "search_winning" not in out["arms"] and "served" not in out["arms"]  # not selectable
    # With noisier seeds the margin is two standard errors of the difference of the means.
    out = decide_arms(_docs(served=[0.38, 0.41, 0.44], mix_search_free=[0.44, 0.45, 0.46]), DecisionConfig(), 3)
    arm = out["arms"]["mix_search_free"]
    assert arm["margin"] == pytest.approx(2 * np.sqrt((0.03**2 + 0.01**2) / 3))
    assert arm["gain"] == pytest.approx(0.04) and arm["wins"]
    out = decide_arms(_docs(served=[0.38, 0.41, 0.44], mix_search_free=[0.43, 0.44, 0.45]), DecisionConfig(), 3)
    assert not out["arms"]["mix_search_free"]["wins"]  # +0.03 < 0.0365


def test_a_winner_needs_gain_worst_seed_and_readability():
    docs = _docs(mix_served_free=[0.44, 0.45, 0.46], mix_search_free=[0.40, 0.47, 0.50],
                 mix_search_nonneg=[0.45, 0.46, 0.47], active_mix_search_nonneg=30.0)
    out = decide_arms(docs, DecisionConfig(), 3)
    assert out["arms"]["mix_served_free"]["wins"]
    assert not out["arms"]["mix_search_free"]["wins"]  # its worst seed (0.40) is below the reference mean 0.41
    assert not out["arms"]["mix_search_nonneg"]["wins"] and not out["arms"]["mix_search_nonneg"]["readable"]
    assert out["chosen"] == "mix_served_free" and out["proposed_seed"] == 2 and out["information_arm"] is None


def test_ties_go_to_non_negative_weights_then_fewer_active_rules_then_the_served_rules():
    docs = _docs(mix_served_free=[0.45, 0.46, 0.47], mix_search_nonneg=[0.447, 0.457, 0.467],
                 active_mix_search_nonneg=12.0)
    assert decide_arms(docs, DecisionConfig(), 3)["chosen"] == "mix_search_nonneg"  # within 0.005, non-negative
    docs = _docs(mix_served_nonneg=[0.45, 0.46, 0.47], mix_search_nonneg=[0.452, 0.462, 0.472],
                 active_mix_served_nonneg=6.0, active_mix_search_nonneg=12.0)
    assert decide_arms(docs, DecisionConfig(), 3)["chosen"] == "mix_served_nonneg"  # fewer rules with weight
    docs = _docs(mix_served_nonneg=[0.45, 0.46, 0.47], mix_search_nonneg=[0.452, 0.462, 0.472])
    assert decide_arms(docs, DecisionConfig(), 3)["chosen"] == "mix_served_nonneg"  # served rules over re-searched
    docs = _docs(mix_served_nonneg=[0.45, 0.46, 0.47], mix_search_nonneg=[0.46, 0.47, 0.48])
    assert decide_arms(docs, DecisionConfig(), 3)["chosen"] == "mix_search_nonneg"  # 0.01 apart: not a tie


def test_mixture_options_stay_out_of_the_pinned_manifests():
    plain = FuzzyClassifierParams()
    assert "inference" not in plain.as_dict() and plain.estimator_options() == {}
    mixture = FuzzyClassifierParams(inference="mixture", mixture_non_negative=True)
    assert mixture.as_dict()["inference"] == "mixture" and mixture.as_dict()["mixture_non_negative"] is True
    if xf.has_rule_mixture():
        assert mixture.estimator_options() == {"inference": "mixture", "mixture_C": 1.0,
                                               "mixture_non_negative": True, "mixture_search": False}
    else:
        with pytest.raises(xf.ExFuzzyFeatureError, match="rule_mixture"):
            mixture.estimator_options()
    # The pruning options only exist with the search; the winning-rule pruning has no threshold.
    assert "mixture_pruning" not in mixture.as_dict() and "mixture_prune_threshold" not in mixture.as_dict()
    old = FuzzyClassifierParams(inference="mixture", mixture_search=True)
    assert old.as_dict()["mixture_pruning"] == "winning_rule" and "mixture_prune_threshold" not in old.as_dict()
    new = FuzzyClassifierParams(inference="mixture", mixture_search=True, mixture_pruning="mixture")
    assert new.as_dict()["mixture_prune_threshold"] == 0.02
    if xf.has_mixture_pruning():
        assert new.estimator_options()["mixture_pruning"] == "mixture"
        assert old.estimator_options()["mixture_pruning"] == "winning_rule"
    else:
        with pytest.raises(xf.ExFuzzyFeatureError):
            new.estimator_options()


def test_the_pruning_follow_up_preregisters_new_arms_and_a_gate_per_task():
    import json
    from pathlib import Path

    from atlas.ml.experiment_mixture import MixtureConfig

    configs = sorted(Path("configs/ml").glob("*_mixture_prune_experiment.json"))
    assert len(configs) == 9
    for path in configs:
        cfg = MixtureConfig.model_validate_json(path.read_text())
        assert cfg.experiment_id == "mixture-prune" and cfg.mixture_prune_threshold == 0.02
        assert [ARMS[a].pruning for a in cfg.serve.arms] == ["mixture", "mixture"]
        # Only the pruning differs from the old-pruning arms.
        for a in cfg.serve.arms:
            twin = ARMS[a.removesuffix("_mp")]
            assert ARMS[a].model_dump(exclude={"pruning", "description"}) == twin.model_dump(
                exclude={"pruning", "description"}) and twin.pruning == "winning_rule"
        assert cfg.serve.serve_if_validation_mean_at_least is not None and cfg.serve.current_run
        serve_cfg = json.loads(Path(str(path).replace("_prune_", "_serve_")).read_text())
        assert {k: v for k, v in json.loads(path.read_text()).items() if k not in ("experiment_id", "serve",
                "mixture_prune_threshold", "seeds")} == {k: v for k, v in serve_cfg.items()
                                                         if k not in ("experiment_id", "serve", "seeds")}
    h6 = MixtureConfig.model_validate_json(Path("configs/ml/nyc_pickups_h6_mixture_prune_experiment.json").read_text())
    assert h6.seeds == [0, 1, 2, 3, 4] and h6.serve.params == {"nRules": 60, "nAnts": 2}
    assert h6.serve.serve_if_validation_mean_at_least == 0.324
