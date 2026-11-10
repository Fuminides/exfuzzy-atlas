"""AT-041h: the pre-registered decision rules of experiment_ica4 (stage-2 entry, final choice, rounds 2-3, slots)."""

import json
from types import SimpleNamespace

import pytest

from atlas.ml import experiment_ica4 as e4

BASE = ["no2_last", "no2_lag1h", "no2_lag3h", "no2_lag24h", "wind_speed", "temperature", "relative_humidity",
        "valid_hour_local", "valid_weekday"]


class FakeCtx:
    def __init__(self, tmp_path, docs, stage1, round2=(), extra=None):
        self.out = tmp_path
        (tmp_path / "val").mkdir()
        self.cfg = e4.Ica4Config(base_config="x", candidate_inputs=[], stage1=list(stage1), round2=list(round2),
                                 extra_arms=extra or {})
        self.base_features = BASE
        for name, (seeds, rules) in docs.items():
            self.save(name, seeds, rules)
        self.cd = SimpleNamespace(fixed={f: SimpleNamespace(bands=[0, 1, 2, 3]) for f in
                                         ["no2_last", "no2_lag1h", "no2_lag3h", "no2_lag24h", "wind_speed",
                                          "valid_hour_local", "valid_weekday", "no2_yday_valid", "no2_expected_valid",
                                          "no2_mean_24h"]},
                                  config=SimpleNamespace(selection=SimpleNamespace(
                                      candidates=[SimpleNamespace(n_linguistic_variables=3)])))
        self.cd.fixed["valid_weekday"] = SimpleNamespace(bands=[0, 1, 2])

    def save(self, name, seeds, rules=10.0):
        doc = {"arm": name, "spec": {"features": BASE}, "mean": sum(seeds) / len(seeds),
               "sd": 0.01, "min": min(seeds), "mean_rules": rules,
               "seeds": [{"seed": i, "validation": {"macro_f1": s}} for i, s in enumerate(seeds)]}
        (self.out / "val" / f"{name}.json").write_text(json.dumps(doc))

    def load_json(self, name):
        return json.loads((self.out / "val" / f"{name}.json").read_text())

    def arm_specs(self):
        return e4.Context.arm_specs(self)


def _ctx(tmp_path, singles, **kw):
    docs = {"base_published": ([0.34, 0.33, 0.33], 13), "base_refit": ([0.32, 0.33, 0.33], 17), **singles}
    return FakeCtx(tmp_path, docs, ["base_refit", *[k for k in singles]], **kw)


def test_entry_needs_the_margin_over_the_larger_reference_and_one_expectation_input_at_most(tmp_path):
    ctx = _ctx(tmp_path, {"no2_yday_valid": ([0.38, 0.37, 0.37], 18), "no2_expected_valid": ([0.35, 0.35, 0.35], 13),
                          "no2_clim_valid": ([0.35, 0.34, 0.35], 13), "no2_mean_24h": ([0.34, 0.34, 0.35], 13)})
    doc = e4.stage2_arms(ctx)
    assert doc["reference_mean"] == pytest.approx(1.0 / 3)  # base_published (0.3333) > base_refit (0.3267)
    assert set(doc["entered"]) == {"no2_yday_valid", "no2_expected_valid", "no2_clim_valid"}
    assert doc["combo_inputs"] == ["no2_yday_valid", "no2_expected_valid"]  # clim_valid is the same family
    compact = doc["arms"]["compact"]["features"]
    assert compact[:3] == ["no2_last", "no2_yday_valid", "no2_expected_valid"]
    assert not set(e4.LAGS) & set(compact)
    assert compact.index("valid_weekday") > compact.index("valid_hour_local")  # 4-term inputs first


def test_no_combo_with_one_entered_input(tmp_path):
    ctx = _ctx(tmp_path, {"no2_yday_valid": ([0.38, 0.37, 0.37], 18), "no2_mean_24h": ([0.34, 0.34, 0.35], 13)})
    doc = e4.stage2_arms(ctx)
    assert "combo" not in doc["arms"] and "compact" in doc["arms"]


def test_win_needs_gain_and_worst_seed_and_ties_go_to_fewer_rules(tmp_path):
    ctx = _ctx(tmp_path, {"no2_yday_valid": ([0.38, 0.37, 0.37], 18),
                          "a_wide": ([0.40, 0.40, 0.33], 10),  # mean gain ok but worst seed below the reference
                          "a_rules": ([0.43, 0.43, 0.43], 30)})  # too many rules
    ctx.save("compact", [0.43, 0.42, 0.42], 11)
    ctx.save("compact_r30a2", [0.43, 0.42, 0.418], 9)
    (tmp_path / "stage2_arms.json").write_text(json.dumps({"arms": {"compact": {"features": BASE}}}))
    (tmp_path / "shape_arms.json").write_text(json.dumps({"arms": {"compact_r30a2": {"features": BASE, "nRules": 30,
                                                                                     "nAnts": 2}}}))
    out = e4.decide(ctx)
    assert not out["arms"]["a_wide"]["wins"] and not out["arms"]["a_rules"]["eligible"]
    assert out["chosen"] == "compact_r30a2" and out["published_seed"] == 0


def test_round2_replaces_only_by_the_margin_over_the_round1_choice(tmp_path):
    extra = {"r2_x": e4.ArmSpec(features=BASE), "r2_y": e4.ArmSpec(features=BASE)}
    ctx = _ctx(tmp_path, {"no2_yday_valid": ([0.38, 0.37, 0.37], 18)}, round2=list(extra), extra=extra)
    ctx.save("r2_x", [0.39, 0.39, 0.39], 5)  # only +0.013 over the round-1 choice
    ctx.save("r2_y", [0.50, 0.49, 0.49], 30)  # too many rules
    out = e4.decide(ctx)
    assert out["chosen"] == "no2_yday_valid" and "r2_x" not in out["arms"]
    assert out["round2"]["chosen"] is None
    ctx.save("r2_x", [0.40, 0.40, 0.395], 5)
    assert e4.decide(ctx)["round2"]["chosen"] == "r2_x"


def test_slot_bound_refuses_a_three_term_input_among_the_first_slots():
    cd = SimpleNamespace(fixed={f: SimpleNamespace(bands=[0, 1, 2, 3]) for f in ["no2_last", "no2_yday_valid"]},
                         config=SimpleNamespace(selection=SimpleNamespace(
                             candidates=[SimpleNamespace(n_linguistic_variables=3)])))
    e4.check_slot_bounds(cd, e4.ArmSpec(features=["no2_last", "no2_yday_valid", "temperature"], nAnts=2))
    with pytest.raises(ValueError, match="could never be used"):
        e4.check_slot_bounds(cd, e4.ArmSpec(features=["no2_last", "temperature", "no2_yday_valid"], nAnts=2))
