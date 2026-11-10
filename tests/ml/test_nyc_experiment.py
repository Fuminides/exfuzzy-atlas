"""NYC demand-level classifier (AT-041e): precomputed labels, 'sin referencia' rows, slices and run directories."""

import json

import numpy as np
import pandas as pd
import pytest

from atlas.contracts import models as m
from atlas.ml import artifacts
from atlas.ml.experiment_nyc import (
    NO_REFERENCE,
    LevelPersistence,
    MajorityClass,
    NycData,
    NycExperimentConfig,
    run_final,
    write_runs,
)
from atlas.ml.partitions import load_partition_file, trapezoids
from atlas.ml.split import chronological_split_spec
from atlas.paths import REPO_ROOT

LABELS = ["baja", "normal", "alta", "muy alta"]
FEATURES = ["rel_lag1", "rel_lag2", "local_hour", "local_dow"]
UNITS = {"rel_lag1": "percentile", "rel_lag2": "percentile", "local_hour": "hour", "local_dow": "weekday_index"}


def test_partition_file_follows_the_scheme_and_documents_its_shoulders():
    fixed = load_partition_file(REPO_ROOT / "configs/ml/nyc_partitions.json")
    assert set(fixed) == {"rel_lag1", "rel_lag2", "rel_lag24", "rel_lag168", "local_hour", "local_dow"}
    scheme = m.TargetScheme.model_validate_json((REPO_ROOT / "configs/mobility/nyc_level_scheme.json").read_text())
    assert scheme.boundary == "lower_inclusive"
    for feature in ("rel_lag1", "rel_lag2", "rel_lag24", "rel_lag168"):
        partition = fixed[feature]
        assert partition.follows_target_scheme and [b.name for b in partition.bands] == LABELS
        assert partition.domain == (0, 100) and partition.boundary_shoulders == [7.0, 7.0, 3.5]
        # each core ends just below the next class lower bound (25 / 75 / 95)
        assert [b.lower for b in partition.bands] == [0, *[c.lower for c in scheme.classes[1:]]]
        assert all(b.upper < n.lower for b, n in zip(partition.bands, partition.bands[1:], strict=False))
    terms = dict(trapezoids(fixed["rel_lag1"]))
    assert terms["alta"] == [68.0, 75.0, 94.9, 98.4]
    assert [b.name for b in fixed["local_hour"].bands] == ["Madrugada", "Mañana", "Mediodía", "Tarde-noche"]
    assert [(b.lower, b.upper) for b in fixed["local_dow"].bands] == [(0, 4), (5, 5), (6, 6)]


def test_level_persistence_uses_lower_inclusive_cuts_and_keeps_missing_unknown():
    frame = pd.DataFrame({"p": [0.0, 24.99, 25.0, 74.9, 75.0, 94.99, 95.0, 100.0, np.nan]})
    assert LevelPersistence("p").predict(frame).tolist() == [0, 0, 1, 1, 2, 2, 3, 3, -1]
    assert LevelPersistence("p").name == "persistence_p"
    majority = MajorityClass(4).fit(None, np.array([1, 1, 2, 3, 1]))
    assert majority.predict(pd.DataFrame({"p": [1, 2]})).tolist() == [1, 1]


@pytest.fixture(scope="module")
def nyc_frame() -> pd.DataFrame:
    """3 zones x 40 days of hourly rows: the label depends on rel_lag1 (and is null for part of one zone)."""
    rng = np.random.default_rng(0)
    issued = pd.date_range("2024-05-01", periods=24 * 40, freq="h", tz="UTC")
    frames = []
    for i, group in enumerate(["lt_3", "10_50", "ge_50"]):
        n = len(issued)
        rel = rng.uniform(0, 100, n)
        level = np.searchsorted([25, 75, 95], np.clip(rel + rng.normal(0, 8, n), 0, 100), side="right")
        local = issued.tz_convert("America/New_York")
        frames.append(pd.DataFrame({
            "entity_id": str(100 + i), "issued_at_utc": issued, "target": rng.poisson(5, n).astype(float),
            "rel_lag1": rel, "rel_lag2": rng.uniform(0, 100, n), "rel_lag24": rng.uniform(0, 100, n),
            "rel_lag168": rng.uniform(0, 100, n), "local_hour": local.hour, "local_dow": local.dayofweek,
            "target_level": np.array(LABELS, dtype=object)[level], "level_status": "ok", "volume_group": group,
        }))
    frame = pd.concat(frames, ignore_index=True)
    low = (frame["entity_id"] == "100") & (frame["issued_at_utc"].dt.day % 3 == 0)
    frame.loc[low, ["target_level", "level_status"]] = [None, "low_volume"]
    frame["complete"] = frame["target_level"].notna()
    return frame


@pytest.fixture(scope="module")
def nyc_config(nyc_frame) -> NycExperimentConfig:
    from atlas.ml import pipeline

    split = chronological_split_spec(nyc_frame["issued_at_utc"], horizon_hours=1, embargo_hours=24)
    base = pipeline.RunConfig(
        task_id="nyc_toy_h1", domain=m.Domain.MOBILITY, target="pickups", target_column="target", unit="trips",
        horizon_hours=1, features=FEATURES, feature_units=UNITS, persistence_feature="rel_lag1", split=split, seed=3,
        data_version="synthetic-test", synthetic=True, timezone="America/New_York", gbm_max_iter=10)
    return NycExperimentConfig(
        experiment_id="nyc-test", table="unused", base=base, scheme="configs/mobility/nyc_level_scheme.json",
        partitions={"file": "configs/ml/nyc_partitions.json", "use_features": FEATURES},
        subsample={"n_rows": 500, "seed": 5},
        selection={"candidates": [{"nRules": 6, "nAnts": 2, "sampling_power": 0.5}], "n_gen": 4, "pop_size": 12},
        final={"n_gen": 4, "pop_size": 12, "seeds": [0, 1]})


def test_unlabelled_rows_are_never_complete_nor_a_class(nyc_config, nyc_frame):
    cd = NycData(nyc_config, frame=nyc_frame)
    d = cd.data
    unlabeled = nyc_frame["target_level"].isna().to_numpy()
    assert unlabeled.any() and not d.complete[unlabeled].any()
    assert (cd.y_class[unlabeled] == -1).all() and cd.labels == LABELS
    assert set(cd.y_class[d.complete]) == {0, 1, 2, 3}
    dist = cd.distribution()
    test = dist["periods"]["test"]
    assert NO_REFERENCE in dist["no_reference_label"] and test["n_target_known_without_label"] > 0
    assert test["without_label_by_status"]["low_volume"] == test["n_target_known_without_label"]
    assert sum(test["counts"].values()) == test["n_complete"] and set(test["by_group"]) <= {"lt_3", "10_50", "ge_50"}
    assert all(abs(sum(v["share"].values()) - 1) < 1e-9 for v in test["by_month"].values())


def test_final_reports_group_and_month_slices_and_writes_run_dirs(nyc_config, nyc_frame, tmp_path):
    cd = NycData(nyc_config, frame=nyc_frame)
    out = tmp_path / "exp"
    out.mkdir()
    (out / "selection.json").write_text(json.dumps({"chosen": {"nRules": 6, "nAnts": 2, "sampling_power": 0.5}}))
    summary = run_final(nyc_config, cd, out)
    assert set(summary["baselines"]) >= {"persistence", "persistence_rel_lag24", "majority_class", "random_forest",
                                         "hist_gradient_boosting", "logistic_regression_subsample"}
    n_test = summary["n_complete_rows"]["test"]
    for block in (summary["runs"][0]["test"], summary["baselines"]["persistence"]["test"]):
        assert block["overall"]["n"] == n_test
        assert sum(v["n"] for v in block["by_group"].values()) == n_test
        assert sum(v["n"] for v in block["by_month"].values()) == n_test
        shares = next(iter(block["shares_by_month"].values()))
        assert len(shares["observed"]) == 4 and len(shares["predicted"]) == 5
        assert abs(sum(shares["observed"]) - 1) < 1e-9 and abs(sum(shares["predicted"]) - 1) < 1e-9
    assert summary["published_seed"] == max(
        summary["runs"], key=lambda r: r["validation"]["overall"]["macro_f1"])["seed"]
    from atlas.ml import report_nyc

    assert "persistence" in report_nyc.overall_table(summary, "test")
    assert "lt_3" in report_nyc.slice_table(summary, "test", "by_group", "macro_f1")
    assert "observed" in report_nyc.share_tables(summary, "test", ["persistence"])
    dirs = write_runs(nyc_config, cd, out, tmp_path / "art")
    assert "THEN nivel" in report_nyc.rules_table(dirs[0])
    run = dirs[0]
    artifacts.verify_checksums(run)
    rules = m.ModelRules.model_validate_json((run / "rules.json").read_text())
    assert rules.target_scheme.boundary == "lower_inclusive"
    assert rules.rules[0].text.split(" THEN ")[1].startswith("nivel = ")
    metrics = m.MetricsReport.model_validate_json((run / "metrics.json").read_text())
    slices = {r.slice for r in metrics.rows if r.estimator == "exfuzzy_classifier"}
    assert {"all", "volume_group=lt_3", "validation/volume_group=ge_50"} <= slices
    assert any(s.startswith("month=2024-") or s.startswith("month=2025-") for s in slices)
    preds = pd.read_parquet(run / "predictions.parquet")
    test_rows = nyc_frame[nyc_frame["issued_at_utc"].between(
        nyc_config.base.split.test_from_utc, nyc_config.base.split.test_to_utc, inclusive="left")]
    assert len(preds) == len(test_rows)
    # a row with an observed count but no label is 'sin referencia': no class on either side, never 'normal'
    no_ref = preds["observed_label"].isna() & preds["observed"].notna()
    assert no_ref.any() and preds.loc[no_ref, "prediction_label"].isna().all()
    assert (preds.loc[no_ref, "missing_reason"] == "prediction_unavailable").all()
    assert "normal" not in set(preds.loc[no_ref, "observed_label"].dropna())
