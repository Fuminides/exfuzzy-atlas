"""Water dissolved-oxygen regressor (AT-041f): detection-limit terms, both splits, horizon 0 run directories."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from ex_fuzzy import fuzzy_sets as fs

from atlas.contracts import models as m
from atlas.ml import artifacts, pipeline
from atlas.ml import exfuzzy_features as xf
from atlas.ml.experiment_water import (
    SEASON_CUTS,
    GlobalMean,
    PointMean,
    SeasonOnlyMean,
    WaterConfig,
    WaterData,
    run_final,
    run_selection,
)
from atlas.ml.partitions import load_partition_file
from atlas.ml.split import chronological_split_spec
from atlas.ml.water_fuzzy import WaterFuzzyRegressor, censored_variable, load_censored
from atlas.paths import REPO_ROOT

FEATURES = ["ammoniacal_nitrogen", "orthophosphate_reactive", "water_temperature", "days_from_midwinter"]
UNITS = {"ammoniacal_nitrogen": "mg/l", "orthophosphate_reactive": "mg/l", "water_temperature": "degC",
         "days_from_midwinter": "days"}
PARTITIONS = REPO_ROOT / "configs/ml/water_partitions.json"


def _membership(variable, x):
    return {s.name: float(s.membership(np.array([x]))[0]) for s in variable.linguistic_variables}


@pytest.mark.parametrize("limit,resolution", [(0.03, 4e-4), (0.01, 1e-4)])
def test_censored_variable_has_a_term_exactly_for_the_limit(limit, resolution):
    rng = np.random.default_rng(0)
    above = limit + resolution + np.round(rng.exponential(0.1, 500), 4)
    reference = np.concatenate([np.full(1500, limit), above, [np.nan]])
    variable = censored_variable("x", reference, limit, 3, "mg/l")
    assert [s.name for s in variable.linguistic_variables] == ["<=L", "Bajo>L", "Medio>L", "Alto>L"]
    at_limit = _membership(variable, limit)
    assert at_limit == {"<=L": 1.0, "Bajo>L": 0.0, "Medio>L": 0.0, "Alto>L": 0.0}
    first = _membership(variable, float(above.min()))
    assert first["<=L"] == 0.0 and first["Bajo>L"] == 1.0
    assert _membership(variable, float(above.max()))["Alto>L"] == 1.0
    assert all(isinstance(s, fs.FS) for s in variable.linguistic_variables)
    with pytest.raises(ValueError, match="above the limit"):
        censored_variable("x", np.full(100, limit), limit, 3, None)


def test_partition_file_season_terms_and_censored_limits():
    fixed = load_partition_file(PARTITIONS)
    assert list(fixed) == ["days_from_midwinter"]
    bands = fixed["days_from_midwinter"].bands
    assert [b.name for b in bands] == ["Invierno", "Primavera-otoño", "Verano"]
    assert bands[0].upper < SEASON_CUTS[0] < bands[1].lower and bands[1].upper < SEASON_CUTS[1] < bands[2].lower
    censored = load_censored(PARTITIONS)
    assert censored["ammoniacal_nitrogen"]["limit"] == 0.03 and censored["orthophosphate_reactive"]["limit"] == 0.01


def test_baselines_by_hand():
    frame = pd.DataFrame({"entity_id": ["a", "a", "b"], "days_from_midwinter": [0.0, 183.0, 0.0]})
    y = np.array([1.0, 3.0, 5.0])
    assert GlobalMean().fit(frame, y).predict(frame).tolist() == [3.0, 3.0, 3.0]
    point = PointMean().fit(frame, y)
    assert point.predict(pd.DataFrame({"entity_id": ["a", "b", "new"]})).tolist() == [2.0, 5.0, 3.0]
    season = SeasonOnlyMean().fit(frame, y)
    assert season.predict(frame).tolist() == [3.0, 3.0, 3.0]  # bin 0 mean (1, 5), bin 11 mean (3)


@pytest.fixture(scope="module")
def water_frame() -> pd.DataFrame:
    rng = np.random.default_rng(1)
    rows = []
    for i in range(24):
        n = 60
        days = np.sort(rng.choice(365 * 11, n, replace=False))
        issued = pd.to_datetime("2015-01-01", utc=True) + pd.to_timedelta(days, "D")
        doy_distance = np.abs(((issued.dayofyear.to_numpy() - 355 + 182) % 365) - 182)
        temp = 10 - 7 * np.cos(2 * np.pi * (issued.dayofyear.to_numpy() - 15) / 365) + rng.normal(0, 1.5, n)
        nh3 = np.where(rng.random(n) < 0.6, 0.03, np.round(0.03 + rng.exponential(0.1, n) + 4e-4, 4))
        po4 = np.where(rng.random(n) < 0.4, 0.01, np.round(0.01 + rng.exponential(0.05, n) + 1e-4, 4))
        rows.append(pd.DataFrame({
            "entity_id": f"NE-{i:03d}", "issued_at_utc": issued, "ammoniacal_nitrogen": nh3,
            "orthophosphate_reactive": po4, "water_temperature": temp,
            "days_from_midwinter": doy_distance.astype(float),
            "target": 13 - 0.4 * temp - 0.8 * (nh3 > 0.03) + rng.normal(0, 0.4, n)}))
    return pd.concat(rows, ignore_index=True)


def _config(frame, kind, features, tmp_path) -> tuple[WaterConfig, dict]:
    split = chronological_split_spec(frame["issued_at_utc"], horizon_hours=0, embargo_hours=24)
    base = pipeline.RunConfig(
        task_id="water_toy", domain=m.Domain.WATER, target="dissolved_oxygen", target_column="target", unit="mg/l",
        horizon_hours=0, features=features, feature_units={f: UNITS[f] for f in features}, split=split, seed=3,
        data_version="synthetic-test", synthetic=True, timezone="Europe/London", gbm_max_iter=10)
    ids = sorted(frame["entity_id"].unique())
    assignment = {e: ("train" if i % 4 < 2 else "validation" if i % 4 == 2 else "test") for i, e in enumerate(ids)}
    config = WaterConfig(
        experiment_id=f"w-{kind}", table="unused", split_kind=kind, base=base, require_columns=FEATURES,
        partitions={"file": "configs/ml/water_partitions.json", "use_features": ["days_from_midwinter"]},
        selection={"nRules": [6], "nAnts": [2], "n_gen": 3, "pop_size": 10},
        final={"n_gen": 3, "pop_size": 10, "seeds": [0, 1]})
    return config, assignment


def test_spatial_masks_are_entity_masks_and_chrono_uses_the_period_split(water_frame, tmp_path):
    config, assignment = _config(water_frame, "spatial", FEATURES, tmp_path)
    spatial = WaterData(config, frame=water_frame, assignment=assignment)
    ids = {p: set(spatial.frame.loc[spatial.masks[p], "entity_id"]) for p in ("train", "validation", "test")}
    assert not (ids["train"] & ids["validation"]) and not (ids["train"] & ids["test"]) and ids["test"]
    assert sum(len(spatial.positions(p)) for p in ids) == int(spatial.complete.sum())
    config, _ = _config(water_frame, "chrono", FEATURES, tmp_path)
    chrono = WaterData(config, frame=water_frame)
    last_train = chrono.issued[chrono.masks["train"]].max()
    assert last_train < chrono.issued[chrono.masks["test"]].min()
    with pytest.raises(ValueError, match="split_kind"):
        WaterData(config.model_copy(update={"split_kind": "random"}), frame=water_frame)


NO_TEMPERATURE = [f for f in FEATURES if f != "water_temperature"]


@pytest.mark.parametrize("kind,features", [("chrono", FEATURES), ("spatial", NO_TEMPERATURE)])
def test_select_final_and_horizon_zero_run_directory(water_frame, tmp_path, kind, features):
    config, assignment = _config(water_frame, kind, features, tmp_path)
    wd = WaterData(config, frame=water_frame, assignment=assignment if kind == "spatial" else None)
    out = tmp_path / "exp"
    selection = run_selection(config, wd, out)
    assert len(selection["fits"]) == 1 and selection["chosen"]["nRules"] == 6
    summary = run_final(config, wd, out, tmp_path / "art")
    expected = {"global_mean", "season_only", "ridge", "random_forest", "hist_gradient_boosting"}
    expected |= {"point_mean"} if kind == "chrono" else set()
    expected |= {"temperature_only_quadratic"} if "water_temperature" in features else set()
    assert set(summary["baselines"]) == expected
    n_test = summary["n_complete_rows"]["test"]
    for block in (summary["runs"][0]["test"], summary["baselines"]["ridge"]["test"]):
        assert block["overall"]["n"] == n_test
        for name in ("season", "low_do"):
            assert sum(v["n"] for v in block["slices"][name].values()) == n_test
        assert ("point_in_train" in block["slices"]) == (kind == "chrono")
    partitions = summary["runs"][0]["partitions"]
    assert list(partitions["ammoniacal_nitrogen"]) == ["<=L", "Bajo>L", "Medio>L", "Alto>L"]
    assert list(partitions["days_from_midwinter"]) == ["Invierno", "Primavera-otoño", "Verano"]
    assert summary["published_seed"] == min(summary["runs"], key=lambda r: r["validation_rmse"])["seed"]
    from atlas.ml import report_water

    assert "ridge" in report_water.overall_table(summary, "test") and "RMSE" in report_water.seeds_table(summary)
    assert "<=L" in report_water.partitions_table(summary)
    if kind == "spatial":
        assert "run_dir" not in summary["runs"][0]
        return
    assert "dissolved_oxygen" in report_water.rules_table(Path(summary["runs"][0]["run_dir"]))
    run = Path(summary["runs"][0]["run_dir"])
    artifacts.verify_checksums(run)
    loaded = pipeline.load_run(run)  # the pickle must not depend on __main__: publish unpickles it
    assert type(loaded.model) is WaterFuzzyRegressor and WaterFuzzyRegressor.__module__ == "atlas.ml.water_fuzzy"
    manifest = m.RunManifest.model_validate_json((run / "run_manifest.json").read_text())
    assert manifest.horizon_hours == 0 and "same-sample" in manifest.warnings[0]
    preds = pd.read_parquet(run / "predictions.parquet")
    assert (preds["valid_at_utc"] == preds["issued_at_utc"]).all()
    rules = m.ModelRules.model_validate_json((run / "rules.json").read_text())
    assert rules.inference.family != m.InferenceFamily.WINNING_RULE_CLASSIFIER
    json.loads((run / "metrics.json").read_text())


def test_validation_only_final_reads_no_test_rows_and_names_the_exfuzzy_source(water_frame, tmp_path):
    """FX retrain: ``test=False`` scores validation only, writes no run directory; the source reaches the files."""
    source = "local atlas/local-integration @ 2ffcfb9 (3.3.1 + PRs #27 #29 #31 #32)"
    config, _ = _config(water_frame, "chrono", FEATURES, tmp_path)
    config = config.model_copy(update={"exfuzzy_source": source})
    wd = WaterData(config, frame=water_frame)
    out = tmp_path / "exp"
    assert run_selection(config, wd, out)["exfuzzy_source"] == source
    summary = run_final(config, wd, out, tmp_path / "art", test=False)
    assert "test" not in summary["n_complete_rows"] and "test" not in summary["runs"][0]
    assert all("test" not in block for block in summary["baselines"].values())
    assert summary["exfuzzy_source"] == source and "run_dir" not in summary["runs"][0]
    assert (out / "summary_validation.json").exists() and not (out / "summary.json").exists()
    assert not (tmp_path / "art").exists()
    with_runs = run_final(config, wd, out, tmp_path / "art")  # the normal path still writes the run directories
    run = Path(with_runs["runs"][0]["run_dir"])
    manifest = m.RunManifest.model_validate_json((run / "run_manifest.json").read_text())
    assert manifest.hyperparameters["exfuzzy_source"] == source
    assert any(f"exfuzzy_source = {source!r}" in w for w in manifest.warnings)


def test_a_config_that_needs_a_missing_fix_is_refused_before_any_fit(water_frame, tmp_path, monkeypatch):
    from atlas.ml import exfuzzy_features as xf

    monkeypatch.setitem(xf._PROBES, "unique_antecedents", lambda: False)
    config, _ = _config(water_frame, "chrono", FEATURES, tmp_path)
    config = config.model_copy(update={"unique_antecedents": True, "requires_exfuzzy": ["unique_antecedents"]})
    wd = WaterData(config, frame=water_frame)
    with pytest.raises(xf.ExFuzzyFeatureError, match="unique_antecedents"):
        run_selection(config, wd, tmp_path / "exp")
    assert not (tmp_path / "exp").exists()


@pytest.mark.skipif(not xf.has_unique_antecedents(), reason="needs ex_fuzzy PR 30 (integration build)")
def test_unique_antecedents_fits_have_no_duplicate_rules(water_frame, tmp_path):
    config, _ = _config(water_frame, "chrono", FEATURES, tmp_path)
    config = config.model_copy(update={"unique_antecedents": True, "rule_mode": "sufficient",
                                       "requires_exfuzzy": ["unique_antecedents"]})
    wd = WaterData(config, frame=water_frame)
    summary = run_final(config, wd, tmp_path / "exp", tmp_path / "art",
                        selection={"chosen": {"nRules": 12, "nAnts": 2, "n_linguistic_variables": 3}}, test=False)
    for run in summary["runs"]:
        assert len(run["rules"]) == len({tuple(map(tuple, r)) for r in run["rules"]}) > 0
