"""Longer forecast horizons of the NYC pickup tasks (AT-080): same features, the target and calendar move with the horizon."""

# ruff: noqa: E501  (long assertions)

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from atlas.domains.mobility import features as F
from atlas.domains.mobility import levels as L

UTC = timezone.utc
HOUR = timedelta(hours=1)
START = datetime(2025, 1, 6, 5, tzinfo=UTC)  # a Monday, local midnight
WEEK = 168
REPO = Path(__file__).resolve().parents[2]
HORIZONS = (3, 6, 24)


def config(horizon: int, name: str | None = None) -> dict:
    iso = lambda d: d.isoformat().replace("+00:00", "Z")  # noqa: E731
    train_to = START + 4 * WEEK * HOUR
    cfg = {
        "task_id": f"test_h{horizon}",
        "horizon_hours": horizon,
        "zone_filter": {"min_train_mean_pickups_per_hour": 0.0},
        "split": {
            "train": [iso(START), iso(train_to)],
            "validation": [iso(train_to), iso(train_to + WEEK * HOUR)],
            "test": [iso(train_to + WEEK * HOUR), iso(START + 6 * WEEK * HOUR)],
            "embargo_hours": 168,
        },
    }
    return cfg | ({"table_dirname": name} if name else {})


def build(tmp_path: Path, values: list, cfg: dict) -> tuple[pd.DataFrame, Path]:
    rows = [("1", START + i * HOUR, v) for i, v in enumerate(values)]
    obs = tmp_path / "observations"
    obs.mkdir()
    pq.write_table(
        pa.table(
            {
                "entity_id": pa.array([r[0] for r in rows], pa.string()),
                "timestamp_utc": pa.array([r[1] for r in rows], pa.timestamp("us", "UTC")),
                "value": pa.array([float(r[2]) for r in rows], pa.float64()),
                "data_version": pa.array(["test-v1"] * len(rows), pa.string()),
            }
        ),
        obs / "part-0.parquet",
    )
    out = tmp_path / "features"
    F.build_features(obs / "*.parquet", out, cfg, memory_limit="500MB", threads=1)
    name = cfg.get("table_dirname", F.TABLE_DIRNAME)
    frame = pd.read_parquet(out / name).drop(columns=["year", "month"])
    return frame.sort_values("issued_at_utc").reset_index(drop=True), out


@pytest.mark.parametrize("horizon", HORIZONS)
def test_the_target_is_the_hour_that_starts_horizon_minus_one_after_issue(tmp_path, horizon):
    frame, out = build(tmp_path, list(range(1, 2 * WEEK + 1)), config(horizon, f"nyc_pickups_h{horizon}"))
    row = frame[frame.issued_at_utc == pd.Timestamp(START + 200 * HOUR)].iloc[0]
    assert row["target"] == 200 + horizon  # value[i] = i + 1: the hour starting at T + (horizon - 1) h
    assert row["valid_at_utc"] == row["issued_at_utc"] + horizon * HOUR  # the end of the target window
    assert (row["pickups_lag1"], row["pickups_lag2"], row["pickups_lag24"], row["pickups_lag168"]) == (200, 199, 177, 33)
    # the features known at T do not move with the horizon; the calendar refers to the target hour (T + horizon - 1 h)
    local = pd.Timestamp(START + (200 + horizon - 1) * HOUR).tz_convert("America/New_York")
    assert (row["local_dow"], row["local_hour"]) == (local.dayofweek, local.hour)
    assert (out / f"nyc_pickups_h{horizon}_feature_report.json").exists() and not (out / F.TABLE_DIRNAME).exists()
    assert json.loads((out / f"nyc_pickups_h{horizon}_feature_report.json").read_text())["horizon_hours"] == horizon


def test_the_default_table_name_and_the_calendar_of_horizon_one_are_unchanged(tmp_path):
    frame, out = build(tmp_path, list(range(1, 2 * WEEK + 1)), config(1))
    row = frame[frame.issued_at_utc == pd.Timestamp(START + 200 * HOUR)].iloc[0]
    assert row["target"] == 201 and (row["local_dow"], row["local_hour"]) == (1, 8)  # T itself, as in AT-031
    assert (out / F.TABLE_DIRNAME).exists()


@pytest.mark.parametrize("horizon", HORIZONS)
def test_the_level_reference_cell_is_the_one_of_the_target_hour(tmp_path, horizon):
    """Every week repeats the same counts, so each cell holds one value: the target sits in the middle of its own cell
    (percentile 50, "normal") only if the cell is the week-hour of the target hour, not the one of the issue hour."""
    week = 5 + 3 * np.arange(WEEK) % 97  # a different count per week-hour
    values = list(np.tile(week, 6))
    cfg = config(horizon, f"nyc_pickups_h{horizon}")
    frame, _ = build(tmp_path, values, cfg)
    out, ref = L.add_levels(
        frame,
        train_from=L._utc(cfg["split"]["train"][0]),
        train_to=L._utc(cfg["split"]["train"][1]),
        horizon=horizon,
        scheme=L.load_scheme(),
        min_samples=4,
        min_cell_mean=1.0,
        group_edges=[3, 10, 50],
        group_labels=["lt_3", "3_10", "10_50", "ge_50"],
    )
    known = out[out["target"].notna() & (out["issued_at_utc"] >= pd.Timestamp(START + 4 * WEEK * HOUR))]
    assert len(known) > WEEK
    assert (known["target_rel"] == 50.0).all() and (known["target_level"] == "normal").all()


@pytest.mark.parametrize("h", HORIZONS)
def test_the_horizon_configs_only_change_the_task_horizon_and_table_names(h):
    base = json.loads((REPO / "configs/mobility/nyc_pickups_h1.json").read_text())
    level = json.loads((REPO / "configs/mobility/nyc_pickups_h1_level.json").read_text())
    cfg = json.loads((REPO / f"configs/mobility/nyc_pickups_h{h}.json").read_text())
    lvl = json.loads((REPO / f"configs/mobility/nyc_pickups_h{h}_level.json").read_text())
    assert cfg["horizon_hours"] == h and cfg["table_dirname"] == f"nyc_pickups_h{h}"
    for key in ("zone_filter", "split", "timezone", "target", "domain"):
        assert cfg[key] == base[key]  # same zones, same split and embargo
    assert lvl["base_config"] == f"configs/mobility/nyc_pickups_h{h}.json" and lvl["table_dirname"] == f"nyc_pickups_h{h}_level"
    for key in ("scheme", "target", "reference", "volume_groups"):
        assert lvl[key] == level[key]  # same classes, same train-only reference rule
