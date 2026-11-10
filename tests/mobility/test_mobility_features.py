"""Leakage and null-semantics tests of the 1-hour-ahead pickup table (AT-031) on small hand-written series."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas.contracts.models import SplitSpec
from atlas.domains.mobility import features as F
from atlas.ml.split import assert_no_temporal_leakage, split_masks
from atlas.services.layout import FeatureSpec

UTC = timezone.utc
HOUR = timedelta(hours=1)
PICKUP_FEATURES = [f for f in F.FEATURES if f.source_id == F.SOURCE_ID]


def config(train_to: datetime, min_rate: float = 0.0, train_from: datetime | None = None) -> dict:
    first = train_from or datetime(2000, 1, 1, tzinfo=UTC)
    iso = lambda d: d.isoformat().replace("+00:00", "Z")  # noqa: E731
    far = datetime(2100, 1, 1, tzinfo=UTC)
    return {
        "task_id": "test_task",
        "horizon_hours": 1,
        "zone_filter": {"min_train_mean_pickups_per_hour": min_rate},
        "split": {
            "train": [iso(first), iso(train_to)],
            "validation": [iso(train_to), iso(train_to)],
            "test": [iso(train_to), iso(far)],
            "embargo_hours": 168,
        },
    }


def hours(start: datetime, n: int) -> list[datetime]:
    return [start + i * HOUR for i in range(n)]


def build(
    tmp_path: Path, series: dict[str, list], start: datetime, cfg: dict | None = None, name: str = "run"
) -> pd.DataFrame:
    """Write ``series`` ({entity: [value or None per hour from ``start``]}) as observations and build the table."""
    rows = [(e, start + i * HOUR, v) for e, values in series.items() for i, v in enumerate(values)]
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
    out = tmp_path / name / "features"
    n_hours = len(next(iter(series.values())))
    cfg = cfg or config(start + n_hours * HOUR)
    F.build_features(obs / "*.parquet", out, cfg, memory_limit="500MB", threads=1)
    frame = pd.read_parquet(out / F.TABLE_DIRNAME)
    return frame.drop(columns=["year", "month"]).sort_values(["entity_id", "issued_at_utc"]).reset_index(drop=True)


def at(frame: pd.DataFrame, entity: str, t: datetime) -> pd.Series:
    sel = frame[(frame.entity_id == entity) & (frame.issued_at_utc == pd.Timestamp(t))]
    assert len(sel) == 1
    return sel.iloc[0]


def test_hand_computed_values_and_target_window(tmp_path):
    """value[i] = i + 1 for the hour starting at start + i h: every column has a closed form."""
    start = datetime(2025, 1, 6, 5, tzinfo=UTC)  # a Monday, local midnight
    frame = build(tmp_path, {"1": [i + 1 for i in range(240)]}, start)
    row = at(frame, "1", start + 200 * HOUR)
    assert row["target"] == 201  # the pickups of [T, T+1)
    assert row["pickups_lag1"] == 200  # [T-1, T)
    assert row["pickups_lag2"] == 199
    assert row["pickups_lag24"] == 201 - 24
    assert row["pickups_lag168"] == 201 - 168
    assert row["pickups_mean24h"] == pytest.approx(np.mean(np.arange(201 - 24, 201)))  # hours T-24 .. T-1
    assert row["valid_at_utc"] == row["issued_at_utc"] + HOUR
    # 200 h after local Monday 00:00 EST: 8 days (a Tuesday) and 8 h
    assert (row["local_dow"], row["local_hour"]) == (1, 8)
    first = frame.iloc[0]
    assert first["issued_at_utc"] == pd.Timestamp(start) and first["target"] == 1
    assert frame["issued_at_utc"].dt.tz is not None and str(frame["issued_at_utc"].dt.tz) == "UTC"
    assert (frame["valid_at_utc"] - frame["issued_at_utc"] == pd.Timedelta(hours=1)).all()


def test_table_schema_and_keys(tmp_path):
    start = datetime(2025, 1, 6, 5, tzinfo=UTC)
    frame = build(tmp_path, {"1": [1] * 200}, start)
    assert list(frame.columns) == list(F.TABLE_COLUMNS)
    for col in ("target", *[f.name for f in PICKUP_FEATURES]):
        assert frame[col].dtype == np.float64
    assert not (frame[["local_hour", "local_dow"]].isna().any().any())


def test_no_feature_uses_an_hour_ending_after_issue_time(tmp_path):
    """Perturb one pickup hour h; a feature may change only at issue times T with h + 1h <= T (the hour has ended).

    This also pins ``lag_hours``: the nearest affected issue time is exactly ``h + lag_hours`` for each feature, so
    ``T - lag_hours`` is the most recent hour start the feature reads. The target changes at T = h and nowhere else.
    """
    rng = np.random.default_rng(0)
    start = datetime(2025, 1, 6, 5, tzinfo=UTC)
    n = 14 * 24
    base = {"1": list(rng.integers(1, 50, n)), "2": list(rng.integers(0, 5, n))}
    reference = build(tmp_path, base, start, name="ref")
    for entity in ("1", "2"):
        for h_index in (30, 200, 330):
            variant = {k: list(v) for k, v in base.items()}
            variant[entity][h_index] += 1000
            changed = build(tmp_path, variant, start, name=f"v{entity}_{h_index}")
            h = start + h_index * HOUR
            for other in ("1", "2"):
                same = changed[changed.entity_id == other].reset_index(drop=True)
                ref = reference[reference.entity_id == other].reset_index(drop=True)
                for column in ("target", *[f.name for f in F.FEATURES]):
                    differs = ~((same[column] == ref[column]) | (same[column].isna() & ref[column].isna()))
                    ages = [(t.to_pydatetime() - h) / HOUR for t in ref.loc[differs, "issued_at_utc"]]
                    if other != entity or column in ("local_hour", "local_dow"):
                        assert ages == [], (entity, other, column)
                    elif column == "target":
                        assert ages == [0]  # T = h: the window [T, T+1) is the perturbed hour
                    else:
                        lag = next(f.lag_hours for f in F.FEATURES if f.name == column)
                        if h_index + lag >= n:
                            assert ages == []  # the first affected issue time is past the end of the series
                            continue
                        assert min(ages) == lag, (column, ages)  # newest source hour start is T - lag_hours
                        assert all(a >= 1 for a in ages)  # the perturbed hour had ended by T


def test_zero_counts_stay_zero_and_missing_stays_null(tmp_path):
    start = datetime(2025, 1, 6, 5, tzinfo=UTC)
    values = [5] * 240
    values[100] = 0  # genuine zero
    values[150] = None  # unknown hour
    frame = build(tmp_path, {"1": values}, start)
    assert at(frame, "1", start + 101 * HOUR)["pickups_lag1"] == 0.0
    assert at(frame, "1", start + 100 * HOUR)["target"] == 0.0
    assert pd.isna(at(frame, "1", start + 150 * HOUR)["target"])
    assert pd.isna(at(frame, "1", start + 151 * HOUR)["pickups_lag1"])
    assert pd.isna(at(frame, "1", start + 151 * HOUR)["pickups_mean24h"])
    assert at(frame, "1", start + 100 * HOUR + 24 * HOUR)["pickups_lag24"] == 0.0
    # outside the covered period: lags before the first hour are null, not 0
    first = frame.iloc[0]
    assert pd.isna(first["pickups_lag1"]) and pd.isna(first["pickups_lag168"]) and pd.isna(first["pickups_mean24h"])
    assert pd.isna(at(frame, "1", start + 23 * HOUR)["pickups_mean24h"])  # 23 h of history: window incomplete
    assert not pd.isna(at(frame, "1", start + 24 * HOUR)["pickups_mean24h"])
    assert pd.isna(at(frame, "1", start + 167 * HOUR)["pickups_lag168"])
    assert not pd.isna(at(frame, "1", start + 168 * HOUR)["pickups_lag168"])


def _dst_frame(tmp_path, start, n, ambiguous_utc=()):
    """value = number of UTC hours since ``start`` + 1, so UTC arithmetic is visible; ambiguous hours are null."""
    values = [None if (start + i * HOUR) in ambiguous_utc else i + 1 for i in range(n)]
    return build(tmp_path, {"1": values, "2": list(values)}, start), values


def test_dst_spring_forward_uses_utc_arithmetic(tmp_path):
    start = datetime(2025, 3, 3, 5, tzinfo=UTC)
    frame, _ = _dst_frame(tmp_path, start, 14 * 24)
    for k in range(0, 14 * 24):
        t = start + k * HOUR
        row = at(frame, "1", t)
        if k >= 24:
            assert row["pickups_lag24"] == k - 24 + 1  # exactly 24 elapsed hours, not "same local clock hour"
        if k >= 168:
            assert row["pickups_lag168"] == k - 168 + 1
    # 2025-03-09: clocks jump from 01:59 EST (06:59Z) to 03:00 EDT (07:00Z)
    assert at(frame, "1", datetime(2025, 3, 9, 5, tzinfo=UTC))["local_hour"] == 0
    assert at(frame, "1", datetime(2025, 3, 9, 6, tzinfo=UTC))["local_hour"] == 1
    assert at(frame, "1", datetime(2025, 3, 9, 7, tzinfo=UTC))["local_hour"] == 3  # 02:00 does not exist
    assert at(frame, "1", datetime(2025, 3, 9, 7, tzinfo=UTC))["local_dow"] == 6  # Sunday
    day = frame[
        (frame.entity_id == "1")
        & (frame.issued_at_utc >= pd.Timestamp("2025-03-09T05:00Z"))
        & (frame.issued_at_utc < pd.Timestamp("2025-03-10T04:00Z"))
    ]
    assert len(day) == 23  # a 23-hour local day
    # lag24 across the jump is still 24 UTC hours: 2025-03-10 04:00Z (00:00 EDT) looks back to 03-09 04:00Z (23:00 EST)
    row = at(frame, "1", datetime(2025, 3, 10, 4, tzinfo=UTC))
    k = int((datetime(2025, 3, 10, 4, tzinfo=UTC) - start) / HOUR)
    assert row["pickups_lag24"] == k - 24 + 1 and row["local_hour"] == 0
    assert row["pickups_mean24h"] == pytest.approx(np.mean([j + 1 for j in range(k - 24, k)]))


def null_at(sub: pd.DataFrame, column: str, lo: datetime, hi: datetime) -> bool:
    """``column`` is null at every issue time in ``[lo, hi]`` (hours) and those rows exist."""
    window = sub.loc[pd.Timestamp(lo) : pd.Timestamp(hi), column]
    return bool(window.isna().all()) and len(window) == int((hi - lo) / HOUR) + 1


def non_null_at(sub: pd.DataFrame, column: str, t: datetime) -> bool:
    return not pd.isna(sub.loc[pd.Timestamp(t), column])


def test_dst_fall_back_ambiguous_hour_propagates_null_not_zero(tmp_path):
    start = datetime(2024, 10, 30, 4, tzinfo=UTC)
    # local 01:xx EDT (05Z) and 01:xx EST (06Z) of 2024-11-03: the naive local hour pools both, so both are null
    a, b = datetime(2024, 11, 3, 5, tzinfo=UTC), datetime(2024, 11, 3, 6, tzinfo=UTC)
    frame, _ = _dst_frame(tmp_path, start, 16 * 24, (a, b))
    for entity in ("1", "2"):
        sub = frame[frame.entity_id == entity].set_index("issued_at_utc")
        # the target is the null hour itself
        assert null_at(sub, "target", a, b)
        assert non_null_at(sub, "target", a - HOUR) and non_null_at(sub, "target", b + HOUR)
        # lag1 / lag2 / lag24 / lag168 are null exactly at T = h + lag for both ambiguous hours
        for column, lag in (("pickups_lag1", 1), ("pickups_lag2", 2), ("pickups_lag24", 24), ("pickups_lag168", 168)):
            assert null_at(sub, column, a + lag * HOUR, b + lag * HOUR), column
            assert non_null_at(sub, column, a + (lag - 1) * HOUR) or lag > 1
            assert non_null_at(sub, column, b + (lag + 1) * HOUR)
        # the 24 h mean needs every hour: null while either ambiguous hour is inside [T-24h, T)
        assert null_at(sub, "pickups_mean24h", a + HOUR, b + 24 * HOUR)
        assert non_null_at(sub, "pickups_mean24h", a)  # T = a: the window ends at a - 1h
        assert non_null_at(sub, "pickups_mean24h", b + 25 * HOUR)
        # calendar features never vanish; the repeated local hour is 1 for both ambiguous UTC hours
        assert sub.loc[pd.Timestamp(a - HOUR), "local_hour"] == 0
        assert sub.loc[pd.Timestamp(a), "local_hour"] == 1 and sub.loc[pd.Timestamp(b), "local_hour"] == 1
        assert sub.loc[pd.Timestamp(b + HOUR), "local_hour"] == 2
        # nulls are never turned into zeros anywhere in the affected week
        week = sub.loc[pd.Timestamp(a) : pd.Timestamp(b) + 169 * HOUR]
        assert (
            not (week[["target", "pickups_lag1", "pickups_lag2", "pickups_lag24", "pickups_lag168"]] == 0).any().any()
        )
    assert frame.dropna().shape[0] < len(frame)


def test_row_count_is_zones_times_issue_hours(tmp_path):
    start = datetime(2025, 1, 6, 5, tzinfo=UTC)
    n = 200
    series = {str(z): [z + (i % 7) for i in range(n)] for z in (1, 2, 3, 4)}
    series["5"] = [0] * n  # never any pickup: excluded by a positive threshold
    cfg = config(start + n * HOUR, min_rate=1.0)
    frame = build(tmp_path, series, start, cfg)
    assert sorted(frame.entity_id.unique()) == ["1", "2", "3", "4"]
    assert len(frame) == 4 * n
    assert not frame.duplicated(["entity_id", "issued_at_utc"]).any()
    assert (frame.groupby("entity_id").size() == n).all()
    report = json.loads((tmp_path / "run" / "features" / f"{F.TABLE_DIRNAME}_feature_report.json").read_text())
    assert report["rows"] == report["rows_expected_zones_x_issue_hours"] == 4 * n
    assert report["complete_rows"] == (4 * n) - 4 * 168  # only the weekly-lag warm-up is incomplete
    assert report["zones_selected"] == 4 and report["zones_excluded"] == ["5"]


def test_duplicate_observation_rows_are_refused(tmp_path):
    start = datetime(2025, 1, 6, 5, tzinfo=UTC)
    obs = tmp_path / "observations"
    obs.mkdir()
    stamps = [start, start, start + HOUR]  # the first hour appears twice
    pq.write_table(
        pa.table(
            {
                "entity_id": ["1"] * 3,
                "timestamp_utc": pa.array(stamps, pa.timestamp("us", "UTC")),
                "value": pa.array([1.0, 1.0, 2.0]),
            }
        ),
        obs / "part-0.parquet",
    )
    with pytest.raises(SystemExit, match="several rows"):
        F.build_features(obs / "*.parquet", tmp_path / "out", config(start + 3 * HOUR), memory_limit="500MB", threads=1)


def test_zone_filter_uses_train_period_only(tmp_path):
    start = datetime(2025, 1, 6, 5, tzinfo=UTC)
    n, n_train = 20 * 24, 10 * 24
    train_to = start + n_train * HOUR
    cfg = config(train_to, min_rate=5.0, train_from=start)

    def series(post_big: bool, edge: int = 0) -> dict:
        rng = np.random.default_rng(1)
        return {
            "1": [10] * n,  # big all the time
            "2": [1] * n_train + [(1000 if post_big else 1)] * (n - n_train),  # small in train, huge afterwards
            "3": [30] * n_train + [(0 if post_big else 30)] * (n - n_train),  # big in train, silent afterwards
            "4": [2] * (n_train - 1)
            + [edge]
            + list(rng.integers(0, 3, n - n_train)),  # `edge` sits in the last train hour
            "5": [2] * n_train
            + [10_000_000]
            + [0] * (n - n_train - 1),  # a spike at train_to: outside the train period
        }

    def selected(post_big: bool, edge: int = 0, name: str = "x") -> list[str]:
        build(tmp_path, series(post_big, edge), start, cfg, name=name)
        sel = json.loads((tmp_path / name / "features" / f"{F.TABLE_DIRNAME}_zone_selection.json").read_text())
        assert sel["train_period_utc"] == cfg["split"]["train"]
        return [z["entity_id"] for z in sel["zones"] if z["included"]]

    quiet = selected(False, name="quiet")
    assert quiet == ["1", "3"]
    # changing anything at or after train_to cannot change the selection
    assert selected(True, name="loud") == quiet
    # ... while a change inside train does (the last train hour is part of the period, train_to itself is not)
    assert selected(False, edge=10_000_000, name="edge") == ["1", "3", "4"]
    sel = json.loads((tmp_path / "quiet" / "features" / f"{F.TABLE_DIRNAME}_zone_selection.json").read_text())
    excluded = {z["entity_id"]: z["reason"] for z in sel["zones"] if not z["included"]}
    assert set(excluded) == {"2", "4", "5"} and all(
        r.startswith("train_mean_pickups_per_hour_below") for r in excluded.values()
    )
    # the table keeps only the selected zones; the excluded ones are listed, not silently dropped
    frame = pd.read_parquet(tmp_path / "quiet" / "features" / F.TABLE_DIRNAME)
    assert sorted(frame.entity_id.unique()) == ["1", "3"]


def test_calendar_features_are_not_binary_flags(tmp_path):
    start = datetime(2025, 1, 6, 5, tzinfo=UTC)  # Monday 00:00 local
    frame = build(tmp_path, {"1": [3] * (8 * 24)}, start)
    assert (
        frame["local_hour"].nunique() == 24 and frame["local_dow"].nunique() == 7
    )  # ex_fuzzy auto-categorizes <= 5 levels
    assert frame["local_hour"].between(0, 23).all() and frame["local_dow"].between(0, 6).all()
    assert at(frame, "1", start)["local_dow"] == 0 and at(frame, "1", start)["local_hour"] == 0
    assert at(frame, "1", start + 5 * 24 * HOUR)["local_dow"] == 5  # Saturday


def test_feature_spec_file_matches_code_and_is_valid():
    spec = json.loads(F.FEATURE_SPEC_PATH.read_text())
    assert spec["features"].items() >= F.feature_spec()["features"].items()  # AT-031b adds the relative features
    parsed = FeatureSpec.model_validate(spec)
    assert set(F.FEATURE_NAMES) <= set(parsed.features) and 6 <= len(F.FEATURE_NAMES) <= 8
    assert all(v.lag_hours >= 0 for v in parsed.features.values())
    assert set(F.FEATURE_NAMES) | {F.TARGET, *F.KEYS} == set(F.TABLE_COLUMNS)


def test_recommended_split_is_valid_for_the_ml_pipeline():
    cfg = F.load_config()
    split = cfg["split"]
    parse = F._utc
    spec = SplitSpec(
        train_from_utc=parse(split["train"][0]),
        train_to_utc=parse(split["train"][1]),
        validation_from_utc=parse(split["validation"][0]),
        validation_to_utc=parse(split["validation"][1]),
        test_from_utc=parse(split["test"][0]),
        test_to_utc=parse(split["test"][1]),
        embargo_hours=split["embargo_hours"],
    )
    assert spec.embargo_hours >= 168 and cfg["horizon_hours"] == 1
    stamps = pd.date_range(spec.train_from_utc, spec.test_to_utc, freq="h", inclusive="left")
    masks = split_masks(stamps, spec)
    assert_no_temporal_leakage(stamps, masks, cfg["horizon_hours"])
    # the weekly lag of the first issue time of a later period never reads an hour of the earlier period's issue window
    for earlier, later in (("train", "validation"), ("validation", "test")):
        last_earlier = stamps[masks[earlier]].max()
        first_later = stamps[masks[later]].min()
        assert first_later - HOUR * 168 > last_earlier
