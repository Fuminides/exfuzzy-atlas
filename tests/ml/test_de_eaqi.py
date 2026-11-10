"""AT-070: Germany EAQI classifier support in the shared ML modules.

Synthetic data only (invented, says nothing about Germany); the scheme, partitions and experiment configs are the
committed ones. Madrid must not change: the ICA tests of ``test_classification.py`` / ``test_partitions.py`` still run.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from test_classification import class_experiment  # noqa: F401 - fixture reused by the bounded-baseline test

from atlas.contracts import models as m
from atlas.ml.classification import load_scheme
from atlas.ml.experiment_class import ClassData, ClassExperimentConfig
from atlas.ml.partitions import load_partition_file, scheme_partition
from atlas.ml.subsample import stratified_subsample

ROOT = Path(__file__).resolve().parents[2]
EAQI = ROOT / "configs" / "air" / "eaqi_no2_scheme.json"
DE_CONFIG = ROOT / "configs" / "ml" / "de_no2_h6_eaqi_experiment.json"
MADRID_CONFIG = ROOT / "configs" / "ml" / "madrid_no2_h6_ica2_justified_experiment.json"
# complete training rows per official EAQI class of the real Germany table (quality.json), used as merge input
DE_TRAIN_COUNTS = [6211047, 5299313, 3410860, 280570, 11664, 268]


# -------------------------------------------------------------------------------------------- the scheme


def test_eaqi_scheme_merges_to_poor_or_worse_with_one_percent():
    eaqi = load_scheme(EAQI)
    assert eaqi.labels == ["Good", "Fair", "Moderate", "Poor", "Very poor", "Extremely poor"]
    assert eaqi.classes[-1].upper is None  # EEA viewer colours (configs/air/eaqi_no2_scheme.json colors_note)
    assert [c.color for c in eaqi.classes] == ["#50F0E6", "#50CCAA", "#F0E641", "#FF5050", "#960032", "#7D2181"]
    merged = eaqi.merge_rare_upper_tail(DE_TRAIN_COUNTS, min_share=0.01)
    assert merged.labels == ["Good", "Fair", "Moderate", "Poor or worse"]
    last = merged.classes[-1]
    assert (last.lower, last.upper) == (61, None) and last.merged_from == ["Poor", "Very poor", "Extremely poor"]
    # the share is of the total of the counts; a class exactly at the share is kept (rule is "fewer than")
    assert eaqi.merge_rare_upper_tail([40, 25, 15, 10, 5, 5], min_share=0.10).labels == [
        "Good", "Fair", "Moderate", "Poor or worse"]
    assert eaqi.merge_rare_upper_tail([40, 25, 16, 9, 5, 5], min_share=0.10).labels[-1] == "Moderate or worse"


def test_merge_rules_are_exclusive_and_one_is_required():
    eaqi = load_scheme(EAQI)
    with pytest.raises(ValueError, match="exactly one"):
        eaqi.merge_rare_upper_tail(DE_TRAIN_COUNTS, 500, min_share=0.01)
    with pytest.raises(ValueError, match="exactly one"):
        eaqi.merge_rare_upper_tail(DE_TRAIN_COUNTS)
    with pytest.raises(ValueError, match="min_share"):
        eaqi.merge_rare_upper_tail(DE_TRAIN_COUNTS, min_share=1.5)
    # the row rule is unchanged: with 500 rows only "Extremely poor" (268 rows) is merged; Germany needs a share
    assert eaqi.merge_rare_upper_tail(DE_TRAIN_COUNTS, 500).labels[-1] == "Very poor or worse"


def test_suffix_is_a_scheme_property_and_madrid_keeps_o_peor():
    ica = load_scheme(ROOT / "configs" / "ml" / "ica_no2_scheme.json")
    assert ica.merged_label_suffix == " o peor" and ica.below_first_as_first is False
    assert ica.merge_rare_upper_tail([683216, 207285, 20750, 7323, 27, 0], 500).labels[-1] == "Desfavorable o peor"
    eaqi = load_scheme(EAQI)
    assert eaqi.merged_label_suffix == " or worse" and eaqi.below_first_as_first is True


def test_eaqi_classify_open_top_and_negative_noise():
    eaqi = load_scheme(EAQI)
    values = [-9.9, 0, 10, 10.4, 10.5, 25, 60, 61, 100, 101, 150, 151, 1015.1, 1e7]
    assert eaqi.classify(values).tolist() == [0, 0, 0, 0, 1, 1, 2, 3, 3, 4, 4, 5, 5, 5]
    assert eaqi.classify([np.nan, np.inf]).tolist() == [-1, -1]
    # without the flag a value under the first lower bound is "no class", as for the ICA
    ica = load_scheme(ROOT / "configs" / "ml" / "ica_no2_scheme.json")
    assert ica.classify([-1]).tolist() == [-1]
    # chunked classification equals the one-shot result
    big = np.random.default_rng(0).gamma(2, 10, 5000)
    assert eaqi.classify(big).tolist() == np.concatenate(
        [eaqi.classify(big[:1700]), eaqi.classify(big[1700:])]).tolist()


def test_merged_eaqi_scheme_is_a_valid_contract_scheme_with_the_eea_colours():
    merged = load_scheme(EAQI).merge_rare_upper_tail(DE_TRAIN_COUNTS, min_share=0.01)
    scheme = merged.to_target_scheme()
    assert isinstance(scheme, m.TargetScheme)
    assert [(c.label, c.lower, c.upper, c.color) for c in scheme.classes] == [
        ("Good", None, 10, "#50F0E6"), ("Fair", 10, 25, "#50CCAA"), ("Moderate", 25, 60, "#F0E641"),
        ("Poor or worse", 60, None, "#FF5050")]  # a merged class keeps the colour of its best member, as in Madrid


# --------------------------------------------------------------------------------------------- the config


def test_config_merge_rules_are_mutually_exclusive():
    text = json.loads(DE_CONFIG.read_text())
    de = ClassExperimentConfig.model_validate(text)
    assert de.merge_min_train_share == 0.01 and de.merge_min_train_rows is None and de.target_label == "EAQI NO2"
    with pytest.raises(ValueError, match="mutually exclusive"):
        ClassExperimentConfig.model_validate({**text, "merge_min_train_rows": 500})
    with pytest.raises(ValueError, match="merge_min_train_share"):
        ClassExperimentConfig.model_validate({**text, "merge_min_train_share": 1.2})
    madrid = ClassExperimentConfig.model_validate_json(MADRID_CONFIG.read_text())  # the Madrid configs are unchanged
    assert madrid.merge_min_train_rows == 500 and madrid.merge_min_train_share is None
    assert madrid.target_label == "ICA" and madrid.baseline_train_rows is None and madrid.compact_load is False
    base_text = {k: v for k, v in json.loads(MADRID_CONFIG.read_text()).items() if k != "merge_min_train_rows"}
    assert ClassExperimentConfig.model_validate(base_text).merge_min_train_rows == 500  # the default


# ----------------------------------------------------------------------------------- Germany partitions


def _de_table(rows_per_station: int = 4000) -> pd.DataFrame:
    """Invented Germany-like table: three stations, issue hours across 2019-2025, NO2 ~ gamma, some rows incomplete."""
    rng = np.random.default_rng(7)
    frames = []
    for e in ("DEAA001", "DEB0002", "DEX03"):
        start = pd.Timestamp("2019-01-01", tz="UTC")
        end = pd.Timestamp("2025-12-31 16:00", tz="UTC")
        issued = start + pd.to_timedelta(np.sort(rng.choice(int((end - start) / pd.Timedelta(hours=1)),
                                                            rows_per_station, replace=False)), unit="h")
        valid = (issued + pd.Timedelta(hours=6)).tz_convert("Europe/Berlin")
        n = len(issued)
        frame = pd.DataFrame({
            "entity_id": e, "issued_at_utc": issued, "valid_at_utc": issued + pd.Timedelta(hours=6),
            "target": rng.gamma(2, 10, n), "no2_last": rng.gamma(2, 10, n), "no2_lag1h": rng.gamma(2, 10, n),
            "no2_lag3h": rng.gamma(2, 10, n), "no2_lag24h": rng.gamma(2, 10, n),
            "wind_speed": rng.gamma(3, 1.2, n), "temperature": rng.normal(10, 8, n),
            "relative_humidity": rng.uniform(30, 100, n), "pressure": 990.0,
            "valid_hour_local": valid.hour.astype("int64"), "valid_weekday": valid.weekday.astype("int64"),
        })
        frame.loc[rng.choice(n, 5, replace=False), "target"] = rng.uniform(-8, -0.1, 5)  # detection-limit noise
        frame.loc[rng.choice(n, 3, replace=False), "no2_last"] = 1015.1
        frame["complete"] = True
        bad = rng.choice(n, n // 10, replace=False)
        frame.loc[bad[: len(bad) // 2], "complete"] = False
        frame.loc[bad[len(bad) // 2:], "wind_speed"] = np.nan  # flagged complete in the file but not finite
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


@pytest.fixture(scope="module")
def de_files(tmp_path_factory):
    root = tmp_path_factory.mktemp("de_table")
    table = _de_table()
    half = len(table) // 2
    table.iloc[:half].to_parquet(root / "part-0.parquet", index=False)
    table.iloc[half:].to_parquet(root / "part-1.parquet", index=False)
    return root, table


def _de_config(root: Path, **updates) -> ClassExperimentConfig:
    text = json.loads(DE_CONFIG.read_text())
    text.update(table=str(root), subsample={"n_rows": 400, "seed": 11, "partition_rows": None},
                baseline_train_rows=None, **updates)
    return ClassExperimentConfig.model_validate(text)


def test_germany_partitions_validate_and_no2_terms_are_the_merged_target_classes(de_files):
    root, _ = de_files
    loaded = load_partition_file(ROOT / "configs" / "ml" / "de_partitions.json")
    assert set(loaded) == {"no2_last", "no2_lag1h", "no2_lag3h", "no2_lag24h", "wind_speed", "valid_hour_local",
                           "valid_weekday"}
    cd = ClassData(_de_config(root))  # raises if a follows_target_scheme partition differs from the merged classes
    assert cd.labels == ["Good", "Fair", "Moderate", "Poor or worse"]
    for feature in ("no2_last", "no2_lag1h", "no2_lag3h", "no2_lag24h"):
        assert [b.name for b in cd.fixed[feature].bands] == cd.labels
        assert cd.fixed[feature].follows_target_scheme
    no2 = cd.fixed["no2_last"]
    assert [(b.lower, b.upper) for b in no2.bands] == [(-10, 10), (11, 25), (26, 60), (61, 1100)]
    assert no2.boundary_shoulders == [1.5, 3.75, 9.0]  # 15 % of 10, 25 and 60 ug/m3
    assert [b.name for b in cd.fixed["valid_weekday"].bands] == ["Weekday", "Saturday", "Sunday"]
    assert [b.name for b in cd.fixed["wind_speed"].bands][0] == "Calm to light air"
    # every term name is English (no Spanish left from the Madrid file)
    names = {b.name for p in cd.fixed.values() for b in p.bands}
    assert not names & {"Noche", "Mediodía", "Laborable", "Brisa ligera", "Buena"}
    # negative detection-limit noise in the target is class 0 (Good), not "no class"
    assert (cd.y_class[cd.data.y < 0] == 0).all() and (cd.y_class >= 0).all()


def test_a_partition_that_does_not_follow_the_merged_classes_is_refused(de_files):
    root, _ = de_files
    config = _de_config(root, merge_min_train_share=None, merge_min_train_rows=1000)  # 3 classes: terms no longer match
    with pytest.raises(ValueError, match="not the classes of the target scheme"):
        ClassData(config)


def test_scheme_partition_for_an_open_top_class_needs_a_domain_end():
    merged = load_scheme(EAQI).merge_rare_upper_tail(DE_TRAIN_COUNTS, min_share=0.01)
    with pytest.raises(ValueError, match="domain_upper"):
        scheme_partition("no2_last", merged, relative_shoulder=0.15)
    p = scheme_partition("no2_last", merged, relative_shoulder=0.15, domain_upper=1100, domain_lower=-10)
    assert p.domain == (-10, 1100) and p.bands[0].lower == -10 and p.bands[-1].upper == 1100
    committed = load_partition_file(ROOT / "configs" / "ml" / "de_partitions.json")["no2_last"]
    assert p.model_dump() == committed.model_dump()
    with pytest.raises(ValueError, match="below_first_as_first"):
        scheme_partition("x", load_scheme(ROOT / "configs" / "ml" / "ica_no2_scheme.json"), shoulder=1.0,
                         domain_lower=-5)


# ----------------------------------------------------------------------------- memory-bounded loading


def test_compact_load_equals_the_full_load_restricted_to_complete_rows(de_files):
    root, table = de_files
    old = ClassData(_de_config(root))
    new = ClassData(_de_config(root, compact_load=True))
    complete = old.data.complete
    assert complete.sum() == len(new.data.frame) < len(table)
    keys = ["entity_id", "issued_at_utc"]
    pd.testing.assert_frame_equal(
        old.data.frame.loc[complete, keys].reset_index(drop=True).astype({"entity_id": str}),
        new.data.frame[keys].astype({"entity_id": str}))
    base = old.config.base
    got, want = new.data.frame, old.data.frame.loc[complete].reset_index(drop=True)
    for column in (base.target_column, base.persistence_feature):  # kept in float64: bit-identical
        assert got[column].dtype == np.float64 and np.array_equal(got[column], want[column])
    for column in base.features:
        np.testing.assert_allclose(got[column], want[column], rtol=1e-6, atol=0)
    assert new.labels == old.labels
    assert np.array_equal(new.y_class, old.y_class[complete])
    assert new.distribution() == old.distribution()  # the class counts / merge / shares of every period

    def row_keys(cd, pos):
        f = cd.data.frame.loc[pos, keys]
        return list(zip(f["entity_id"].astype(str), f["issued_at_utc"], strict=True))

    assert row_keys(new, new.data.train_pos) == row_keys(old, old.data.train_pos)
    for period in ("validation", "test"):
        assert row_keys(new, new.data.positions(period)) == row_keys(old, old.data.positions(period))
    for seed, power in ((11, 0.5), (3, 1.0)):  # the class-tempered subsample draws the same rows
        assert row_keys(new, new.train_sample(400, seed, power)) == row_keys(old, old.train_sample(400, seed, power))


def test_compact_load_refuses_extra_tables(de_files):
    from atlas.ml.experiment_class import load_class_frame

    root, _ = de_files
    config = _de_config(root, compact_load=True, require_columns=["pressure"])
    with pytest.raises(ValueError, match="compact_load"):
        load_class_frame(config)


def _old_stratified(entity_id, issued_at_utc, n_target, seed):
    """The block coding of ``stratified_subsample`` before AT-070 (one string per row), as the reference."""
    from atlas.ml.subsample import _allocate

    stamps = pd.DatetimeIndex(issued_at_utc)
    month = np.asarray(stamps.tz_convert("UTC").year * 100 + stamps.tz_convert("UTC").month)
    block = pd.Series(np.asarray(entity_id).astype(str)) + "|" + pd.Series(month.astype(str))
    codes, uniques = pd.factorize(block, sort=True)
    sizes = np.bincount(codes, minlength=len(uniques))
    counts = _allocate(sizes, n_target)
    order = np.argsort(codes, kind="stable")
    starts = np.concatenate([[0], np.cumsum(sizes)])
    rng = np.random.default_rng(seed)
    chosen = []
    for b, take in enumerate(counts):
        if take:
            members = order[starts[b]:starts[b + 1]]
            chosen.append(members if take == len(members) else rng.choice(members, size=take, replace=False))
    return np.sort(np.concatenate(chosen))


def test_stratified_subsample_is_unchanged_by_the_numeric_block_codes():
    rng = np.random.default_rng(2)
    n = 6000
    issued = pd.Timestamp("2022-11-20", tz="UTC") + pd.to_timedelta(rng.integers(0, 24 * 120, n), unit="h")
    # ids of different lengths: "A|..." sorts after "A1|..." as a string but before it as a tuple
    ids = rng.choice(np.array(["A", "A1", "A10", "B", "DEBE063", "DEB"], dtype=object), n)
    for target in (50, 700, 5999):
        expected = _old_stratified(ids, issued, target, 4)
        assert np.array_equal(stratified_subsample(ids, issued, target, 4), expected)
        cat = pd.Categorical(ids)  # a categorical entity column (the compact frame) draws the same rows
        assert np.array_equal(stratified_subsample(cat, issued, target, 4), expected)


# ---------------------------------------------------------------------------- chunked evaluation code


def test_chunked_prediction_readability_and_climatology_equal_the_one_shot_results(table, monkeypatch):
    from atlas.ml import class_baselines, evaluation, fuzzy_classifier
    from atlas.ml.class_baselines import ClimatologyMajorityClass
    from atlas.ml.evaluation import classifier_readability_rows
    from atlas.ml.fuzzy_classifier import FuzzyClassifier, FuzzyClassifierParams
    from atlas.ml.synthetic import FEATURE_UNITS, FEATURES, TARGET

    rows = table.dropna().reset_index(drop=True)
    y = np.minimum(np.digitize(rows[TARGET], np.quantile(rows[TARGET], [0.3, 0.6, 0.9])), 3)
    labels = ["a", "b", "c", "d"]
    model = FuzzyClassifier(FuzzyClassifierParams(nRules=6, nAnts=2, n_gen=4, pop_size=12, patience=None),
                            FEATURE_UNITS).fit(rows[FEATURES], y, labels, seed=0)
    X = rows[FEATURES]
    one_shot = model.predict(X)
    readability = classifier_readability_rows("e", model, X.to_numpy(float), labels, y)
    clim = ClimatologyMajorityClass(6, "Europe/Berlin", 4).fit(rows, y)
    monkeypatch.setattr(fuzzy_classifier, "PREDICT_CHUNK", 97)
    monkeypatch.setattr(evaluation, "ACTIVATION_CHUNK", 97)
    monkeypatch.setattr(class_baselines, "FIT_CHUNK", 211)
    assert np.array_equal(model.predict(X), one_shot) and (one_shot >= -1).all()
    assert classifier_readability_rows("e", model, X.to_numpy(float), labels, y) == readability
    chunked = ClimatologyMajorityClass(6, "Europe/Berlin", 4).fit(rows, y)
    assert np.array_equal(chunked.predict(rows), clim.predict(rows))


def test_bounded_baseline_sample_keeps_the_summary_and_marks_the_sample(class_experiment, tmp_path):  # noqa: F811
    from atlas.ml.experiment_class import run_final, run_selection

    config, table = class_experiment
    bounded = config.model_copy(update={"baseline_train_rows": 700})
    cd = ClassData(bounded, frame=table)
    out = tmp_path / "exp"
    run_selection(bounded, cd, out)
    summary = run_final(bounded, cd, out)
    rows = summary["n_complete_rows"]
    assert rows["train_baselines_bounded_sample"] == 700 < rows["train_full"]
    assert "hist_gradient_boosting" in summary["baselines"] and "climatology_majority_class" in summary["baselines"]
    full = run_final(config, ClassData(config, frame=table), tmp_path / "exp_full",
                     selection=json.loads((out / "selection.json").read_text()))
    assert "train_baselines_bounded_sample" not in full["n_complete_rows"]  # Madrid-style summary is unchanged
    # persistence does not depend on the fit rows at all
    assert summary["baselines"]["persistence"] == full["baselines"]["persistence"]


def test_duplicate_keys_check_agrees_with_pandas_for_categorical_and_plain_entities():
    from atlas.ml.experiment import _has_duplicate_keys

    issued = pd.date_range("2024-01-01", periods=5, freq="h", tz="UTC")
    frame = pd.DataFrame({"entity_id": ["a", "a", "b", "b", "a"], "issued_at_utc": issued[[0, 1, 0, 1, 2]]})
    for entity in (frame["entity_id"], frame["entity_id"].astype("category")):
        ok = frame.assign(entity_id=entity)
        assert _has_duplicate_keys(ok) is False
        dup = pd.concat([ok, ok.iloc[[1]]], ignore_index=True)
        assert _has_duplicate_keys(dup) is True and dup.duplicated(["entity_id", "issued_at_utc"]).any()
