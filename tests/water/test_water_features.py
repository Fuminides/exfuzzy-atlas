# ruff: noqa: E501  (long hand-written sample lines)
"""The uk_water_do table (AT-021) on small hand-written samples: join, censoring, point context, exclusions, splits, spec."""

from __future__ import annotations

import copy
import json

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas.contracts.models import SplitSpec
from atlas.domains.water import features as F
from atlas.services.layout import FeatureSpec

RIVER = "RIVER / RUNNING SURFACE WATER"
VERSION = "uk-wq-test-v1"


def config(**overrides) -> dict:
    cfg = copy.deepcopy(F.load_config())
    cfg["split"] = {
        "train": ["2020-01-01T00:00:00Z", "2020-07-01T00:00:00Z"],
        "validation": ["2020-08-01T00:00:00Z", "2020-10-01T00:00:00Z"],
        "test": ["2020-11-01T00:00:00Z", "2021-03-01T00:00:00Z"],
        "embargo_hours": 720,
    }
    cfg["point_context"]["min_train_samples"] = 2
    cfg.update(overrides)
    return cfg


def sample(point, number, when, *, material=RIVER, purpose="MONITORING", **results):
    """Long observation rows of one sample. A result is ``value`` or ``(value, 'left')`` (value = reported limit)."""
    rows = []
    for feature, result in results.items():
        value, censoring = result if isinstance(result, tuple) else (result, None)
        rows.append(
            {
                "entity_id": point,
                "timestamp_utc": pd.Timestamp(when, tz="UTC"),
                "feature_name": feature,
                "value": float(value),
                "censoring": censoring,
                "sample_id": f"{point}/{number}",
                "sample_material": material,
                "sampling_purpose": purpose,
                "data_version": VERSION,
            }
        )
    return rows


def frame(*samples) -> pd.DataFrame:
    return pd.DataFrame([row for s in samples for row in s])


def all_inputs(do=11.0, nh4=0.1, po4=0.05, temp=8.0, ph=8.0):
    return {
        "dissolved_oxygen": do,
        "ammoniacal_nitrogen": nh4,
        "orthophosphate_reactive": po4,
        "water_temperature": temp,
        "ph": ph,
    }


# ------------------------------------------------------------------------------------------------ join


def test_same_sample_join_gives_one_row_per_kept_do_sample():
    obs = frame(
        sample("A", 1, "2020-02-03 10:00", **all_inputs(do=12.0, nh4=0.5)),
        sample("A", 2, "2020-03-03 10:00", **all_inputs(do=10.0, nh4=0.2)),
        sample("A", 3, "2020-04-03 10:00", ammoniacal_nitrogen=0.9, ph=7.5),  # no DO: not a row
        sample("B", 4, "2020-02-03 10:00", dissolved_oxygen=9.0),  # DO only: a row with null inputs
    )
    table, report = F.build_table(obs, config())
    assert len(table) == 3 == report["sequential"]["table_rows"]
    assert report["samples_without_dissolved_oxygen"] == 1
    by_sample = table.set_index("sample_id")
    assert by_sample.loc["A/1", "ammoniacal_nitrogen"] == 0.5 and by_sample.loc["A/1", F.TARGET] == 12.0
    assert by_sample.loc["A/2", "ammoniacal_nitrogen"] == 0.2  # inputs come from their own sample, never a neighbour
    assert np.isnan(by_sample.loc["B/4", "ammoniacal_nitrogen"]) and by_sample.loc["B/4", F.TARGET] == 9.0
    assert (table["valid_at_utc"] == table["issued_at_utc"]).all()
    assert not table.duplicated(["entity_id", "issued_at_utc"]).any()


def test_repeated_sample_determinand_pair_is_an_error_not_a_multiplied_row():
    obs = frame(sample("A", 1, "2020-02-03 10:00", **all_inputs()))
    with pytest.raises(ValueError, match="more than once"):
        F.build_table(pd.concat([obs, obs.iloc[[0]]]), config())


def test_observations_of_one_sample_must_share_instant_and_material():
    obs = frame(sample("A", 1, "2020-02-03 10:00", **all_inputs()))
    obs.loc[1, "timestamp_utc"] = pd.Timestamp("2020-02-03 11:00", tz="UTC")
    with pytest.raises(ValueError, match="disagree"):
        F.build_table(obs, config())


# ---------------------------------------------------------------------------------------------- censoring


def _encode(values, censoring, limit):
    enc, status = F.encode_input(pd.Series(values, dtype=float), pd.Series(censoring, dtype=object), limit)
    return enc.tolist(), status.tolist()


def test_censoring_encoding_harmonises_to_the_common_limit():
    # (value, censoring): <0.03, <0.002, measured 0.01, measured 0.03, measured 0.5, <0.3, >5, absent
    values = [0.03, 0.002, 0.01, 0.03, 0.5, 0.3, 5.0, np.nan]
    censoring = ["left", "left", None, None, None, "left", "right", None]
    enc, status = _encode(values, censoring, 0.03)
    assert enc[:5] == [0.03, 0.03, 0.03, 0.03, 0.5]
    assert np.isnan(enc[5]) and np.isnan(enc[6]) and np.isnan(enc[7])
    assert status == [
        "censored_at_common_limit",
        "censored_below_common_limit_raised",
        "measured_below_common_limit_raised",
        "measured_at_common_limit",
        "measured",
        "censored_above_common_limit_dropped",
        "right_censored_dropped",
        "missing",
    ]
    assert set(status) <= set(F.STATUSES)


def test_censoring_encoding_never_ranks_a_censored_result_above_a_measured_one_it_may_be_below():
    # raw values would give '<0.03' (0.03) > measured 0.01 although the former may be lower; harmonised they tie
    enc, _ = _encode([0.03, 0.01], ["left", None], 0.03)
    assert enc[0] == enc[1] == 0.03


def test_without_a_common_limit_a_censored_result_is_dropped_and_counted():
    enc, status = _encode([7.9, 8.0, 9.7], ["left", None, "left"], None)
    assert np.isnan(enc[0]) and enc[1] == 8.0 and np.isnan(enc[2])
    assert status == ["censored_dropped", "measured", "censored_dropped"]


def test_table_carries_the_status_of_every_harmonised_row_and_the_report_counts_them():
    obs = frame(
        sample("A", 1, "2020-02-03 10:00", **{**all_inputs(), "ammoniacal_nitrogen": (0.03, "left")}),
        sample("A", 2, "2020-03-03 10:00", **{**all_inputs(), "ammoniacal_nitrogen": (0.002, "left")}),
        sample("A", 3, "2020-04-03 10:00", **{**all_inputs(), "ph": (7.9, "left")}),
    )
    table, report = F.build_table(obs, config())
    assert table["ammoniacal_nitrogen_status"].tolist() == [
        "censored_at_common_limit",
        "censored_below_common_limit_raised",
        "measured",
    ]
    assert table["ammoniacal_nitrogen"].tolist()[:2] == [0.03, 0.03]
    assert report["input_status"]["ammoniacal_nitrogen"]["censored_at_common_limit"] == 1
    assert report["input_status"]["ammoniacal_nitrogen"]["censored_below_common_limit_raised"] == 1
    assert report["input_status"]["ph"] == {"measured": 2, "censored_dropped": 1}
    assert np.isnan(table.loc[2, "ph"])  # a censored pH is null, not 7.9


# ------------------------------------------------------------------------------------------ calendar


def test_season_features_have_no_seam_and_use_local_time():
    t = pd.Series(pd.to_datetime(["2020-12-21 12:00", "2021-01-01 12:00", "2020-06-21 09:30", "2020-12-31 12:00"], utc=True))
    s = F.season_features(t, "Europe/London")
    assert s["days_from_midwinter"].tolist() == [0, 11, 183, 10]  # 31 December and 1 January are 1 day apart
    assert s["local_hour"].tolist() == [12.0, 12.0, 10.5, 12.0]  # 09:30 UTC is 10:30 BST
    assert s["local_day_of_year"].tolist() == [356, 1, 173, 366]


# ----------------------------------------------------------------------------------------- point context


def _context_obs(po4_train=(0.1, 0.3), po4_test=0.9, do_train=(10.0, 11.0), do_test=8.0):
    return frame(
        sample("A", 1, "2020-02-01 10:00", **all_inputs(do=do_train[0], po4=po4_train[0])),
        sample("A", 2, "2020-03-01 10:00", **all_inputs(do=do_train[1], po4=po4_train[1])),
        sample("A", 3, "2020-12-01 10:00", **all_inputs(do=do_test, po4=po4_test)),  # test period
        sample("B", 4, "2020-02-01 10:00", **all_inputs(po4=0.5)),  # one train sample: below min_train_samples
        sample("B", 5, "2020-12-01 10:00", **all_inputs(po4=0.7)),
    )


def test_point_context_uses_train_period_inputs_only():
    base, _ = F.build_table(_context_obs(), config())
    ctx = base.set_index("sample_id")[F.POINT_CONTEXT]
    assert ctx["A/1"] == ctx["A/2"] == ctx["A/3"] == pytest.approx(0.2)  # median of the two train values 0.1, 0.3
    assert ctx.loc[["B/4", "B/5"]].isna().all()  # fewer than min_train_samples train rows: null, never a guess

    after_train, _ = F.build_table(_context_obs(po4_test=5.0), config())  # change a test-period input
    assert after_train.set_index("sample_id")[F.POINT_CONTEXT]["A/3"] == pytest.approx(0.2)
    changed_train, _ = F.build_table(_context_obs(po4_train=(0.1, 0.9)), config())
    assert changed_train.set_index("sample_id")[F.POINT_CONTEXT]["A/3"] == pytest.approx(0.5)


def test_point_context_never_reads_the_target():
    base, _ = F.build_table(_context_obs(), config())
    other, _ = F.build_table(_context_obs(do_train=(2.0, 3.0), do_test=1.0), config())
    pd.testing.assert_series_equal(base[F.POINT_CONTEXT], other[F.POINT_CONTEXT])


def test_point_context_takes_the_median_of_the_harmonised_phosphate():
    obs = frame(
        sample("A", 1, "2020-02-01 10:00", **{**all_inputs(), "orthophosphate_reactive": (0.01, "left")}),
        sample("A", 2, "2020-03-01 10:00", **{**all_inputs(), "orthophosphate_reactive": (0.001, "left")}),
        sample("A", 3, "2020-04-01 10:00", **{**all_inputs(), "orthophosphate_reactive": 0.4}),
    )
    table, _ = F.build_table(obs, config())
    assert table[F.POINT_CONTEXT].eq(0.01).all()  # the two censored results sit at the common limit 0.01


# -------------------------------------------------------------------------------------------- exclusions


def test_exclusions_are_counted_independently_and_in_sequence():
    obs = frame(
        sample("A", 1, "2020-02-03 10:00", **all_inputs()),  # kept
        sample("A", 2, "2020-03-03 10:00", material="SEA WATER", **all_inputs()),  # non-river
        sample("P", 3, "2020-03-03 10:00", **all_inputs()),  # placeholder-coordinate point
        sample("P", 4, "2020-03-04 10:00", material="ANY WATER", **all_inputs()),  # both
        sample("A", 5, "2020-04-03 10:00", **{**all_inputs(), "dissolved_oxygen": 35.35}),  # above the plausible maximum
        sample("A", 6, "2020-05-03 10:00", **{**all_inputs(), "dissolved_oxygen": (5.0, "left")}),  # censored target
        sample("A", 7, "2020-05-04 10:00", ammoniacal_nitrogen=0.1),  # no DO: not part of any count
    )
    table, report = F.build_table(obs, config(), unlocated={"P": "outside_dataset_extent"})
    assert table["sample_id"].tolist() == ["A/1"]
    assert report["independent"] == {
        "target_censored": 1,
        "non_river_sample_material": 2,
        "unlocated_sampling_point": 2,
        "target_above_plausible_max": 1,
    }
    assert report["sequential"] == {
        "samples_with_dissolved_oxygen": 6,
        "removed_target_censored": 1,
        "removed_non_river_sample_material": 2,
        "removed_unlocated_sampling_point": 1,  # P/4 was already removed as non-river
        "removed_target_above_plausible_max": 1,
        "table_rows": 1,
    }
    assert report["unlocated_points"]["P"]["do_samples"] == 2
    assert report["non_river_materials"] == {"ANY WATER": 1, "SEA WATER": 1}


def test_unlocated_entities_come_from_null_geometry(tmp_path):
    collection = {
        "features": [
            {"geometry": {"type": "Point", "coordinates": [-1.6, 55.0]}, "properties": {"entity_id": "A"}},
            {
                "geometry": None,
                "properties": {"entity_id": "P", "attributes": {"coordinate_flag": "outside_dataset_extent"}},
            },
            {"geometry": None, "properties": {"entity_id": "Q", "attributes": {"coordinate_flag": None}}},
        ]
    }
    path = tmp_path / "entities.geojson"
    path.write_text(json.dumps(collection))
    assert F.read_unlocated_entities(path) == {"P": "outside_dataset_extent", "Q": "no_coordinates"}


# ------------------------------------------------------------------------------------------------ splits


def _times(start, n, step_days):
    return pd.Series(pd.date_range(start, periods=n, freq=f"{step_days}D", tz="UTC"))


def test_chronological_split_has_no_overlap_and_respects_the_embargo():
    cfg = F.load_config()
    spec = F.split_spec(cfg)
    issued = _times("2015-01-01", 4000, 1)  # one sample a day through 2025
    assign = F.chronological_assignment(issued, spec)
    gap = pd.Timedelta(hours=spec.embargo_hours)
    for earlier, later in (("train", "validation"), ("validation", "test")):
        assert issued[assign == earlier].max() + gap <= issued[assign == later].min()
    assert set(assign) == {"train", "validation", "test", "gap"}
    # half-open: the boundary instant belongs to the later period, and no row is in two periods
    edges = pd.Series([spec.train_to_utc - pd.Timedelta(seconds=1), spec.train_to_utc, spec.test_from_utc])
    assert F.chronological_assignment(edges, spec).tolist() == ["train", "gap", "test"]
    assert pd.Timestamp(spec.test_to_utc) - pd.Timestamp(spec.test_from_utc) >= pd.Timedelta(days=2 * 365)  # >= 2 years of test
    assert spec.embargo_hours == 720


def test_spatial_split_holds_whole_points_out_and_is_fixed_by_the_seed():
    ids = pd.Series([f"NE-{i}" for i in range(2000)])
    frac = {"train": 0.7, "validation": 0.1, "test": 0.2}
    a = F.spatial_assignment(ids, 7, frac)
    assert a.equals(F.spatial_assignment(pd.concat([ids, ids]).reset_index(drop=True), 7, frac).iloc[:2000])
    assert not a.equals(F.spatial_assignment(ids, 8, frac))
    shares = a.value_counts(normalize=True)
    assert shares["train"] == pytest.approx(0.7, abs=0.04) and shares["test"] == pytest.approx(0.2, abs=0.04)
    rows = pd.Series(["NE-1", "NE-2", "NE-1", "NE-1", "NE-2"])
    by_row = F.spatial_assignment(rows, 7, frac)
    assert by_row.groupby(rows).nunique().max() == 1  # every row of a point is in the same group


def test_split_counts_cover_every_row_once():
    obs = frame(*[sample("A", i, f"2020-{1 + i % 12:02d}-10 10:00", **all_inputs()) for i in range(1, 25)])
    obs = obs.drop_duplicates(["entity_id", "timestamp_utc", "feature_name"])
    table, _ = F.build_table(obs, config())
    spec = F.split_spec(config())
    counts = F.split_counts(table, F.chronological_assignment(table["issued_at_utc"], spec))
    assert sum(c["rows"] for c in counts.values()) == len(table)


# ----------------------------------------------------------------------------------------------- spec


def test_feature_spec_validates_and_matches_the_committed_file():
    spec = FeatureSpec.model_validate(F.feature_spec())
    assert list(spec.features) == F.FEATURE_NAMES
    assert all(f.lag_hours == 0 for f in spec.features.values())  # same-sample / same-instant inputs
    committed = json.loads(F.FEATURE_SPEC_PATH.read_text())
    assert committed == F.feature_spec()
    assert FeatureSpec.model_validate(committed)


def test_config_is_consistent_with_the_code():
    cfg = F.load_config()
    assert set(cfg["inputs"]) == set(F.INPUT_DETERMINANDS)
    assert cfg["horizon_hours"] == 0
    assert isinstance(F.split_spec(cfg), SplitSpec)
    assert set(F.RECOMMENDED) <= set(F.FEATURE_NAMES)
    assert F.POINT_CONTEXT not in F.RECOMMENDED  # null for sparse points: optional
    assert abs(sum(cfg["spatial_split"]["fractions"].values()) - 1) < 1e-9


# ------------------------------------------------------------------------------------------- end to end


@pytest.mark.filterwarnings("ignore::RuntimeWarning")  # correlations of constant columns in a 3-row table
def test_run_writes_the_table_reports_and_spec(tmp_path):
    water = tmp_path / "water"
    obs = frame(
        sample("A", 1, "2020-02-03 10:00", **all_inputs()),
        sample("A", 2, "2020-03-03 10:00", **{**all_inputs(), "ammoniacal_nitrogen": (0.03, "left")}),
        sample("B", 3, "2020-12-03 10:00", **all_inputs()),
    )
    obs["year"], obs["month"] = obs["timestamp_utc"].dt.year, obs["timestamp_utc"].dt.month
    (water / "observations").mkdir(parents=True)
    pq.write_to_dataset(
        pa.Table.from_pandas(obs, preserve_index=False), str(water / "observations"), partition_cols=["year", "month"]
    )
    (water / "entities.geojson").write_text(json.dumps({"features": []}))
    spec_path = tmp_path / "feature_spec.json"
    report = F.run(config=config(), water_dir=water, write_spec=True, spec_path=spec_path, log=lambda _: None)
    table = pd.read_parquet(water / "features" / F.TABLE_DIRNAME)
    assert len(table) == 3 == report["summary"]["rows"]
    assert (water / "features" / f"{F.TABLE_DIRNAME}_feature_report.json").exists()
    split = json.loads((water / "features" / f"{F.TABLE_DIRNAME}_spatial_split.json").read_text())
    assert sorted(p for pts in split["points"].values() for p in pts) == ["A", "B"]
    assert FeatureSpec.model_validate_json(spec_path.read_text())
