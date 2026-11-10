"""Relative demand levels (AT-031b): train-only references, class boundaries, minimum-volume rule, no leakage."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas.contracts.models import TargetScheme
from atlas.domains.mobility import features as F
from atlas.domains.mobility import levels as L
from atlas.services.layout import FeatureSpec

UTC = timezone.utc
HOUR = timedelta(hours=1)
START = datetime(2025, 1, 6, 5, tzinfo=UTC)  # a Monday, local midnight
WEEK = 168
MIN_SAMPLES = 4  # 4 train weeks give 4 values per week-hour cell


def split_config(train_to: datetime, n_hours: int) -> dict:
    iso = lambda d: d.isoformat().replace("+00:00", "Z")  # noqa: E731
    end = START + n_hours * HOUR
    return {
        "task_id": "test_task",
        "horizon_hours": 1,
        "zone_filter": {"min_train_mean_pickups_per_hour": 0.0},
        "split": {
            "train": [iso(START), iso(train_to)],
            "validation": [iso(train_to), iso(train_to + 7 * 24 * HOUR)],
            "test": [iso(train_to + 7 * 24 * HOUR), iso(end)],
            "embargo_hours": 168,
        },
    }


def base_table(tmp_path: Path, series: dict[str, list], train_weeks: int = 4, name: str = "run"):
    """The AT-031 table of ``series`` ({zone: [count or None per hour from START]}) and the config that built it."""
    n = len(next(iter(series.values())))
    rows = [(e, START + i * HOUR, v) for e, values in series.items() for i, v in enumerate(values)]
    table = pa.table(
        {
            "entity_id": pa.array([r[0] for r in rows], pa.string()),
            "timestamp_utc": pa.array([r[1] for r in rows], pa.timestamp("us", "UTC")),
            "value": pa.array([None if r[2] is None else float(r[2]) for r in rows], pa.float64()),
            "data_version": pa.array(["test-v1"] * len(rows), pa.string()),
        }
    )
    obs = tmp_path / name / "observations"
    obs.mkdir(parents=True)
    pq.write_table(table, obs / "part-0.parquet")
    cfg = split_config(START + train_weeks * WEEK * HOUR, n)
    out = tmp_path / name / "features"
    F.build_features(obs / "*.parquet", out, cfg, memory_limit="500MB", threads=1)
    return out / F.TABLE_DIRNAME, cfg


def read_base(table_dir: Path) -> pd.DataFrame:
    frame = pd.read_parquet(table_dir).drop(columns=["year", "month"])
    return frame.sort_values(["entity_id", "issued_at_utc"]).reset_index(drop=True)


def levels(frame: pd.DataFrame, cfg: dict, min_samples: int = MIN_SAMPLES, min_mean: float = 1.0):
    train = cfg["split"]["train"]
    return L.add_levels(
        frame,
        train_from=L._utc(train[0]),
        train_to=L._utc(train[1]),
        horizon=cfg["horizon_hours"],
        scheme=L.load_scheme(),
        min_samples=min_samples,
        min_cell_mean=min_mean,
        group_edges=[3, 10, 50],
        group_labels=["lt_3", "3_10", "10_50", "ge_50"],
    )


def random_series(seed: int = 0, n: int = 6 * WEEK) -> dict[str, list]:
    rng = np.random.default_rng(seed)
    hod = (np.arange(n) % 24) / 24
    shape = 1 + np.sin(2 * np.pi * hod)
    return {
        "1": list(rng.poisson(30 * shape + 5)),
        "2": list(rng.poisson(6 * shape + 1)),
    }


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("levels")
    series = random_series()
    table_dir, cfg = base_table(tmp, series)
    frame = read_base(table_dir)
    out, ref = levels(frame, cfg)
    return series, table_dir, cfg, frame, out, ref


# ------------------------------------------------------------------------------------------ classes


def test_scheme_file_is_a_valid_target_scheme():
    raw = json.loads(L.SCHEME_PATH.read_text())
    scheme = TargetScheme.model_validate(raw)  # ordered, contiguous, unique labels
    assert [c.label for c in scheme.classes] == ["baja", "normal", "alta", "muy alta"]
    assert scheme.boundary == "lower_inclusive"
    assert L.scheme_cuts(scheme).tolist() == [25, 75, 95]
    assert (scheme.classes[0].lower, scheme.classes[-1].upper) == (0, 100)
    assert len({c.color for c in scheme.classes}) == 4 and all(c.color for c in scheme.classes)
    assert "percentil" in scheme.unit
    # the cited source is this repo's own definition, and it exists
    assert scheme.source_url.endswith("docs/mobility/nyc_pickups_h1_level.md")
    assert (L.REPO_ROOT / "docs" / "mobility" / "nyc_pickups_h1_level.md").exists()


def test_class_assignment_at_the_boundaries():
    cuts = L.scheme_cuts(L.load_scheme())
    pct = [0, 24.999999, 25, 74.999999, 75, 94.999999, 95, 100, np.nan]
    assert L.classify(pct, cuts).tolist() == [0, 0, 1, 1, 2, 2, 3, 3, -1]


def test_percentile_is_mid_rank_and_exact_at_the_cut_points():
    # 40 distinct counts: a query between two of them has an exact percentile
    ref = L.Reference(np.array(["7"] * 40), np.zeros(40, int), np.arange(2, 82, 2), min_samples=30)
    cell = ref.cell(ref.entity_index(np.array(["7"] * 3)), np.zeros(3, int))
    pct = ref.percentile(cell, np.array([19.0, 21.0, 61.0]))  # 9, 10, 30 values below
    assert pct.tolist() == [22.5, 25.0, 75.0]  # exactly 25 and 75, not 24.999...
    cuts = L.scheme_cuts(L.load_scheme())
    assert L.classify(pct, cuts).tolist() == [0, 1, 2]  # 25 -> normal, 75 -> alta
    # ties: 60 % zeros; the usual value is "normal", never "baja", and the top value is "muy alta"
    tied = L.Reference(np.array(["7"] * 10), np.zeros(10, int), np.array([0] * 6 + [1] * 4), min_samples=5)
    cell = tied.cell(tied.entity_index(np.array(["7"] * 3)), np.zeros(3, int))
    pct = tied.percentile(cell, np.array([0.0, 1.0, 2.0]))
    assert pct.tolist() == [30.0, 80.0, 100.0]
    assert L.classify(pct, cuts).tolist() == [1, 2, 3]
    # a count above everything seen is the top of the scale, below everything is the bottom
    assert ref.percentile(cell[:1], np.array([1000.0]))[0] == 100.0
    assert ref.percentile(cell[:1], np.array([0.0]))[0] == 0.0


def test_non_integer_counts_are_rejected():
    with pytest.raises(ValueError, match="whole numbers"):
        L.Reference(np.array(["1"]), np.array([0]), np.array([1.5]), min_samples=1)


# ------------------------------------------------------------------------------------------ rows


def test_row_count_order_and_keys_are_preserved(pipeline):
    _, _, _, frame, out, _ = pipeline
    assert len(out) == len(frame) == 2 * 6 * WEEK
    for col in F.TABLE_COLUMNS:
        pd.testing.assert_series_equal(out[col], frame[col])
    assert list(out.columns) == [*F.TABLE_COLUMNS, *L.LEVEL_COLUMNS]
    assert not out.duplicated(list(F.KEYS)).any()
    assert set(out[L.STATUS]) <= set(L.STATUSES)
    assert (out[L.LEVEL].notna() == (out[L.STATUS] == "ok")).all()


def test_pipeline_percentile_matches_a_brute_force_cell_lookup(pipeline):
    _, _, cfg, frame, out, _ = pipeline
    train_to = pd.Timestamp(L._utc(cfg["split"]["train"][1]))
    slot = L.week_slot(pd.DatetimeIndex(out["issued_at_utc"]))
    keyed = out.assign(slot=slot)
    reference = keyed[(keyed.issued_at_utc < train_to) & keyed.target.notna()]
    cells = {k: g.target.to_numpy() for k, g in reference.groupby(["entity_id", "slot"])}
    for idx in np.random.default_rng(1).choice(len(keyed), 400, replace=False):
        row = keyed.iloc[idx]
        values = cells[(row.entity_id, row.slot)]
        expected = 100 * ((values < row.target).mean() + 0.5 * (values == row.target).mean())
        assert row[L.REL] == pytest.approx(expected, abs=1e-9)
        # the lag is ranked in the cell of its own hour
        lag_slot = L.week_slot(pd.DatetimeIndex([row.issued_at_utc - 24 * HOUR]))[0]
        if not np.isnan(row.pickups_lag24):
            lag_values = cells[(row.entity_id, lag_slot)]
            want = 100 * ((lag_values < row.pickups_lag24).mean() + 0.5 * (lag_values == row.pickups_lag24).mean())
            assert row["rel_lag24"] == pytest.approx(want, abs=1e-9)


def test_cell_slot_follows_the_local_clock_across_a_clock_change():
    winter = pd.DatetimeIndex([pd.Timestamp("2025-03-02T17:00Z")])  # Sunday 12:00 EST
    summer = pd.DatetimeIndex([pd.Timestamp("2025-03-16T16:00Z")])  # Sunday 12:00 EDT
    assert L.week_slot(winter)[0] == L.week_slot(summer)[0] == 6 * 24 + 12
    assert L.week_slot(pd.DatetimeIndex([pd.Timestamp("2025-03-10T04:00Z")]))[0] == 0  # Monday 00:00 EDT


# ------------------------------------------------------------------------------------------ train only


def _perturbed(tmp_path, series, zone, index, delta, name):
    changed = {k: list(v) for k, v in series.items()}
    changed[zone][index] += delta
    table_dir, cfg = base_table(tmp_path, changed, name=name)
    return levels(read_base(table_dir), cfg)


def test_reference_uses_train_data_only(tmp_path, pipeline):
    series, _, cfg, _, out, ref = pipeline
    train_hours = 4 * WEEK
    # a validation / test hour changed by a lot: the reference and every train row are untouched
    for index in (train_hours + 10, 5 * WEEK + 3):
        out2, ref2 = _perturbed(tmp_path, series, "1", index, 5000, f"post{index}")
        assert np.array_equal(ref.n, ref2.n) and np.array_equal(ref._sorted, ref2._sorted)
        assert np.allclose(ref.mean, ref2.mean, equal_nan=True) and np.allclose(ref.zone_mean, ref2.zone_mean)
        in_train = (out.issued_at_utc < pd.Timestamp(L._utc(cfg["split"]["train"][1]))).to_numpy()
        for col in L.LEVEL_COLUMNS:
            a, b = out.loc[in_train, col], out2.loc[in_train, col]
            assert ((a == b) | (a.isna() & b.isna())).all(), col
    # positive control: a train hour changes the reference
    _, ref3 = _perturbed(tmp_path, series, "1", 100, 5000, "inside")
    assert not np.array_equal(ref._sorted, ref3._sorted)


def test_relative_features_do_not_read_hours_that_have_not_ended(tmp_path, pipeline):
    """Perturb one validation-period hour h: ``rel_lagK`` changes first at T = h + K, ``rel_mean24h`` at h + 1 h, the
    target's level only at T = h, and no earlier row changes (the raw ``lag_hours`` holds)."""
    series, _, _, _, out, _ = pipeline
    h_index = 4 * WEEK + 30
    out2, _ = _perturbed(tmp_path, series, "1", h_index, 5000, "leak")
    h = START + h_index * HOUR
    same_zone = (out.entity_id == "1").to_numpy()
    for column, lag in [(L.REL, 0), *[(f.name, f.lag_hours) for f in L.REL_FEATURES]]:
        a, b = out[column], out2[column]
        differs = (~((a == b) | (a.isna() & b.isna()))).to_numpy()
        assert not differs[~same_zone].any(), column  # other zones never move
        ages = [(t.to_pydatetime() - h) / HOUR for t in out.loc[differs & same_zone, "issued_at_utc"]]
        assert min(ages) == lag, (column, ages[:5])
        if column == L.REL:
            assert ages == [0]


# ------------------------------------------------------------------------------------------ small cells


def test_too_few_train_samples_and_low_volume_follow_the_documented_rule(tmp_path):
    series = random_series()
    series["1"] = list(series["1"])
    # zone 1 has no data in the first 10 days: the cells those days fall in have 3 train values (< 4)
    for i in range(10 * 24):
        series["1"][i] = None
    series["3"] = [0] * (6 * WEEK)  # a zone that is never active: reference mean 0
    table_dir, cfg = base_table(tmp_path, series)
    out, ref = levels(read_base(table_dir), cfg, min_samples=MIN_SAMPLES, min_mean=1.0)

    z1 = out[out.entity_id == "1"]
    slot = L.week_slot(pd.DatetimeIndex(z1.issued_at_utc))
    thin = np.isin(slot, np.unique(slot[: 10 * 24]))  # weekly cells touched by the first 10 days
    thin_cells = {s for s in range(WEEK) if ref.n[ref.entity_index(np.array(["1"]))[0] * WEEK + s] < MIN_SAMPLES}
    assert thin_cells and thin_cells <= set(np.unique(slot[: 10 * 24]))
    in_thin = np.isin(slot, list(thin_cells)) & z1.target.notna().to_numpy()
    assert in_thin.any() and thin.any()
    assert (z1.loc[in_thin, L.STATUS] == "insufficient_samples").all()
    assert z1.loc[in_thin, L.LEVEL].isna().all() and z1.loc[in_thin, L.REL].isna().all()
    # their relative inputs are null too, never a made-up percentile
    lag_slot = L.week_slot(pd.DatetimeIndex(z1.issued_at_utc) - pd.Timedelta(hours=1))
    lag_thin = np.isin(lag_slot, list(thin_cells)) & z1.pickups_lag1.notna().to_numpy()
    assert lag_thin.any() and z1.loc[lag_thin, "rel_lag1"].isna().all()
    # well-sampled cells of the same zone are labelled
    assert (z1.loc[~np.isin(slot, list(thin_cells)) & z1.target.notna().to_numpy(), L.STATUS] == "ok").all()

    z3 = out[out.entity_id == "3"]
    assert (z3[L.STATUS] == "low_volume").all() and z3[L.LEVEL].isna().all()
    assert z3[L.REL].notna().all()  # the percentile exists (all zeros -> 50), only the label is withheld
    assert (z3[L.REL] == 50.0).all()
    assert (z3["rel_lag1"].dropna() == 50.0).all()  # inputs are not gated by the volume rule
    z2 = out[out.entity_id == "2"]  # a small zone: its quiet cells (train mean < 1) are low_volume, the rest labelled
    quiet = z2[z2[L.STATUS] == "low_volume"]
    assert len(quiet) and (quiet[L.LEVEL].isna()).all()
    cell_mean = ref.mean[ref.entity_index(np.array(["2"]))[0] * WEEK + L.week_slot(pd.DatetimeIndex(z2.issued_at_utc))]
    assert ((cell_mean < 1.0) == (z2[L.STATUS] == "low_volume").to_numpy()).all()


def test_missing_target_is_not_a_level(tmp_path):
    series = random_series()
    series["1"] = list(series["1"])
    series["1"][5 * WEEK + 7] = None
    table_dir, cfg = base_table(tmp_path, series)
    out, _ = levels(read_base(table_dir), cfg)
    t = START + (5 * WEEK + 7) * HOUR
    row = out[(out.entity_id == "1") & (out.issued_at_utc == pd.Timestamp(t))].iloc[0]
    assert row[L.STATUS] == "target_missing" and pd.isna(row[L.LEVEL]) and pd.isna(row[L.REL])
    nxt = out[(out.entity_id == "1") & (out.issued_at_utc == pd.Timestamp(t + HOUR))].iloc[0]
    assert pd.isna(nxt["rel_lag1"]) and pd.isna(nxt["rel_mean24h"])  # the unknown hour is not 0


def test_relative_mean_is_one_for_a_series_equal_to_its_normal(tmp_path):
    n = 6 * WEEK
    pattern = [3 + (i % 24) for i in range(n)]  # same count at the same clock hour every day: cell mean = value
    series = {"1": pattern, "2": [10] * n}
    table_dir, cfg = base_table(tmp_path, series)
    out, _ = levels(read_base(table_dir), cfg)
    got = out["rel_mean24h"].dropna()
    assert len(got) > 0 and np.allclose(got, 1.0)
    # a zone running at twice its normal: ratio 2 (validation period, reference fixed by train)
    doubled = {"1": [10] * (4 * WEEK) + [20] * (2 * WEEK)}
    table_dir, cfg = base_table(tmp_path, doubled, name="double")
    out, _ = levels(read_base(table_dir), cfg)
    late = out[out.issued_at_utc >= pd.Timestamp(START + (4 * WEEK + 24) * HOUR)]
    assert np.allclose(late["rel_mean24h"].dropna(), 2.0)
    assert (late[L.REL] == 100.0).all() and (late[L.LEVEL].dropna() == "muy alta").all()


# ------------------------------------------------------------------------------------------ outputs


def test_volume_groups_follow_the_train_mean():
    ent = np.array(["a"] * 4 + ["b"] * 4 + ["c"] * 4 + ["d"] * 4)
    vals = np.array([2] * 4 + [3] * 4 + [10] * 4 + [60] * 4)
    ref = L.Reference(ent, np.arange(16) % 4, vals, min_samples=1)
    assert ref.zone_mean.tolist() == [2, 3, 10, 60]
    groups = np.searchsorted(np.array([3, 10, 50.0]), ref.zone_mean, side="right")
    assert groups.tolist() == [0, 1, 2, 3]  # the lower edge belongs to the higher group


def test_build_level_table_writes_the_table_reference_and_report(tmp_path, pipeline):
    series, table_dir, cfg, frame, _, _ = pipeline
    base_cfg = tmp_path / "base.json"
    base_cfg.write_text(json.dumps(cfg))
    level_cfg = L.load_config()
    level_cfg["base_config"] = str(base_cfg)  # absolute: REPO_ROOT / absolute = absolute
    level_cfg["reference"] = {**level_cfg["reference"], "min_samples": MIN_SAMPLES}
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    report = L.build_level_table(table_dir, out_dir, level_cfg, memory_limit="500MB", threads=1)
    written = pd.read_parquet(out_dir / L.TABLE_DIRNAME).drop(columns=["year", "month"])
    assert len(written) == len(frame) == report["rows"]
    assert list(written.columns) == list(L.TABLE_COLUMNS)
    assert set(zip(written.entity_id, written.issued_at_utc, strict=True)) == set(
        zip(frame.entity_id, frame.issued_at_utc, strict=True)
    )
    assert set(written[L.LEVEL].dropna()) <= {"baja", "normal", "alta", "muy alta"}
    summary = pd.read_parquet(out_dir / f"{L.TABLE_DIRNAME}_reference.parquet")
    assert len(summary) == 2 * WEEK
    assert set(summary.columns) >= {"trips_from_normal", "trips_from_alta", "trips_from_muy_alta"}
    # the published cut points reproduce the labels: a count below trips_from_normal is "baja", etc.
    z = written[written.entity_id == "1"].merge(
        summary[summary.entity_id == "1"].assign(
            target_slot=lambda d: d.local_dow * 24 + d.local_hour
        ),
        left_on=["local_dow", "local_hour"],
        right_on=["local_dow", "local_hour"],
    )
    z = z[z[L.LEVEL].notna()]
    got = np.select(
        [z.target >= z.trips_from_muy_alta, z.target >= z.trips_from_alta, z.target >= z.trips_from_normal],
        ["muy alta", "alta", "normal"],
        "baja",
    )
    assert (got == z[L.LEVEL].to_numpy()).all()
    periods = report["periods"]
    assert sum(p["rows"] for p in periods.values()) <= len(frame)
    train = periods["train"]
    assert sum(train["classes_complete_rows"]["counts"].values()) == train["complete_rows"]
    assert json.loads((out_dir / f"{L.TABLE_DIRNAME}_report.json").read_text())["labels"] == report["labels"]


def test_feature_spec_file_matches_code_and_lag_hours_follow_the_raw_features():
    spec = json.loads(F.FEATURE_SPEC_PATH.read_text())
    assert spec == L.feature_spec()
    parsed = FeatureSpec.model_validate(spec)
    assert set(parsed.features) == set(L.MODEL_FEATURE_NAMES)
    for f in L.REL_FEATURES:
        assert parsed.features[f.name].lag_hours == parsed.features[f.source].lag_hours
        assert parsed.features[f.name].source_id == F.SOURCE_ID
    assert set(F.feature_spec()["features"]) < set(spec["features"])  # the AT-031 features are unchanged
    assert all(spec["features"][k] == v for k, v in F.feature_spec()["features"].items())


def test_slot_comparison_crps_is_exact_on_small_samples():
    from atlas.domains.mobility import level_slots as S

    assert S.crps_empirical(np.array([3.0]), np.array([3.0, 5.0])).tolist() == [0.0, 2.0]  # a point forecast: |x - y|
    # sample {0, 2}, y = 1: E|X-y| = 1, E|X-X'| = (0 + 2 + 2 + 0) / 4 = 1 -> CRPS = 1 - 0.5
    assert S.crps_empirical(np.array([0.0, 2.0]), np.array([1.0]))[0] == pytest.approx(0.5)
