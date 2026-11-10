"""Relative demand level of yellow-taxi pickups per taxi zone (AT-031b): "baja / normal / alta / muy alta".

    PYTHONPATH=src python -m atlas.domains.mobility.levels --write-spec

The target of the classification task is not the count but **how unusual the count is for its own zone at that time of the
week**. Definitions (every one is pinned by a test):

* **Cell.** (zone, week-hour): America/New_York day of week x clock hour of the *target hour* (168 per zone). Local clock, so
  a 19:00 Friday cell means the same thing before and after a clock change.
* **Reference.** For each cell, the multiset of train-period targets (issue hours in ``[train_from, train_to)``, target
  known). Nothing after ``train_to`` enters, whatever the row being labelled.
* **Relative quantity** ``target_rel`` (percent, 0-100): the *mid-rank* percentile of the count within its cell reference,
  ``100 * (#ref < x + 0.5 * #ref == x) / n``. The mid-rank makes ties symmetric, which matters for counts: in a cell where
  60 % of the hours are 0, a 0 sits at percentile 30 ("normal"), not at 0 or 60, and ``baja`` is impossible, because there
  is nothing lower than the usual. The scheme (``configs/mobility/nyc_level_scheme.json``) cuts this quantity at 25, 75
  and 95, lower bound inclusive.
* **Minimum-volume rule.** A cell is usable for a *label* only if it has at least ``min_samples`` train values (otherwise
  ``level_status = insufficient_samples``) and a train mean of at least ``min_cell_mean_pickups_per_hour`` (otherwise
  ``low_volume``: with that few trips a one-trip difference moves the percentile by tens of points and "muy alta" would
  mean two trips). Rows in such cells keep their raw data but have ``target_level = null``; they are not "normal".
* **Relative inputs** (``rel_lag1`` ...) rank a lag against the reference of the cell *of the lagged hour itself*; they
  need only ``min_samples`` (the volume rule applies to labels, not to inputs). ``rel_mean24h`` is the 24-hour mean over
  the sum of the cell means of those same 24 hours. They are functions of the raw lag and of calendar constants fixed by
  train, so ``lag_hours`` equals the raw feature's.

Train rows are labelled against a reference that contains their own value, so the train class shares are close to
25/50/20/5 *by construction*; validation and test are out of sample. That is a property of any climatological threshold,
not a leak of validation or test into train (a perturbation test checks that).
"""

# ruff: noqa: E501  (prose)

from __future__ import annotations

import argparse
import json
import os
import resource
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from atlas.contracts.models import TargetScheme
from atlas.domains.mobility import aggregate
from atlas.domains.mobility import features as F
from atlas.paths import PROCESSED_DIR, REPO_ROOT

CONFIG_PATH = REPO_ROOT / "configs" / "mobility" / "nyc_pickups_h1_level.json"
SCHEME_PATH = REPO_ROOT / "configs" / "mobility" / "nyc_level_scheme.json"
TABLE_DIRNAME = "nyc_pickups_h1_level"
SLOTS = 168
_BIG = 10_000_000  # composite sort key = cell * _BIG + count; counts are whole numbers below this

LEVEL = "target_level"
REL = "target_rel"
STATUS = "level_status"
GROUP = "volume_group"
STATUSES = ("ok", "target_missing", "insufficient_samples", "low_volume")


@dataclass(frozen=True)
class RelFeature:
    name: str
    source: str  # raw feature it re-expresses
    unit: str
    lag_hours: int
    description: str


REL_FEATURES: tuple[RelFeature, ...] = (
    RelFeature(
        "rel_lag1", "pickups_lag1", "percentile", 1, "percentile of pickups_lag1 in the cell of its own hour (T-1h)"
    ),
    RelFeature(
        "rel_lag2", "pickups_lag2", "percentile", 2, "percentile of pickups_lag2 in the cell of its own hour (T-2h)"
    ),
    RelFeature(
        "rel_lag24",
        "pickups_lag24",
        "percentile",
        24,
        "percentile of pickups_lag24 in the cell of its own hour (T-24h elapsed)",
    ),
    RelFeature(
        "rel_lag168",
        "pickups_lag168",
        "percentile",
        168,
        "percentile of pickups_lag168 in the cell of its own hour (T-168h): the target's own cell",
    ),
    RelFeature(
        "rel_mean24h",
        "pickups_mean24h",
        "ratio",
        1,
        "pickups_mean24h divided by the mean of the 24 cell train means of the same hours [T-24h, T)",
    ),
)
REL_NAMES = tuple(f.name for f in REL_FEATURES)
# Columns appended to the AT-031 table, after its ``TABLE_COLUMNS``.
LEVEL_COLUMNS = (REL, LEVEL, STATUS, GROUP, *REL_NAMES)
TABLE_COLUMNS = (*F.TABLE_COLUMNS, *LEVEL_COLUMNS)
MODEL_FEATURE_NAMES = (*F.FEATURE_NAMES, *REL_NAMES)


def feature_spec() -> dict:
    """``feature_spec.json``: the AT-031 features plus the relative ones (``docs/api.md``)."""
    spec = F.feature_spec()
    for f in REL_FEATURES:
        spec["features"][f.name] = {"unit": f.unit, "source_id": F.SOURCE_ID, "lag_hours": f.lag_hours}
    return spec


def write_feature_spec(path: Path = F.FEATURE_SPEC_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(feature_spec(), indent=2) + "\n", encoding="utf-8")
    return path


def load_config(path: Path = CONFIG_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_scheme(path: Path = SCHEME_PATH) -> TargetScheme:
    return TargetScheme.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def scheme_cuts(scheme: TargetScheme) -> np.ndarray:
    """The inner class bounds (lower of every class but the first) of a ``lower_inclusive`` scheme."""
    if scheme.boundary != "lower_inclusive":
        raise ValueError("the relative-level scheme must be lower_inclusive")
    return np.array([c.lower for c in scheme.classes[1:]], dtype=float)


def classify(pct, cuts: np.ndarray) -> np.ndarray:
    """Class index per percentile (``-1`` for NaN): ``[cut_i, cut_{i+1})`` with the lower bound inclusive."""
    pct = np.asarray(pct, dtype=float)
    idx = np.searchsorted(cuts, pct, side="right")  # = number of cuts <= pct
    return np.where(np.isnan(pct), -1, idx).astype(int)


def week_slot(ts: pd.DatetimeIndex) -> np.ndarray:
    """Local day of week x 24 + clock hour (Monday 00:00 = 0 ... Sunday 23:00 = 167) of UTC instants."""
    local = ts.tz_convert(aggregate.TIMEZONE)
    return (local.dayofweek * 24 + local.hour).to_numpy().astype(np.int64)


class Reference:
    """Train-period distribution of the count in each (zone, week-hour) cell; ranks any count against it."""

    def __init__(self, entity_id: np.ndarray, slot: np.ndarray, value: np.ndarray, min_samples: int):
        value = np.asarray(value, dtype=float)
        if not np.isfinite(value).all():
            raise ValueError("the reference needs known counts only")
        _check_counts(value)
        self.entity_ids, e = np.unique(np.asarray(entity_id).astype(str), return_inverse=True)
        self.min_samples = int(min_samples)
        cell = e.astype(np.int64) * SLOTS + np.asarray(slot, dtype=np.int64)
        n_cells = len(self.entity_ids) * SLOTS
        self._sorted = np.sort(cell * _BIG + np.rint(value).astype(np.int64))
        self.n = np.bincount(cell, minlength=n_cells)
        self._start = np.concatenate([[0], np.cumsum(self.n)])
        total = np.bincount(cell, weights=value, minlength=n_cells)
        self.mean = np.where(self.n > 0, total / np.maximum(self.n, 1), np.nan)
        zone_n = self.n.reshape(-1, SLOTS).sum(1)
        self.zone_mean = total.reshape(-1, SLOTS).sum(1) / np.maximum(zone_n, 1)

    @property
    def n_cells(self) -> int:
        return len(self.n)

    def entity_index(self, entity_id: np.ndarray) -> np.ndarray:
        """Position of each entity in ``entity_ids``; ``-1`` for a zone without a reference."""
        entity_id = np.asarray(entity_id).astype(str)
        pos = np.searchsorted(self.entity_ids, entity_id)
        pos = np.minimum(pos, len(self.entity_ids) - 1)
        return np.where(self.entity_ids[pos] == entity_id, pos, -1)

    def cell(self, entity_idx: np.ndarray, slot: np.ndarray) -> np.ndarray:
        return np.where(entity_idx >= 0, entity_idx * SLOTS + slot, -1)

    def n_samples(self, cell: np.ndarray) -> np.ndarray:
        return np.where(cell >= 0, self.n[np.maximum(cell, 0)], 0)

    def percentile(self, cell: np.ndarray, value: np.ndarray) -> np.ndarray:
        """Mid-rank percentile (0-100) of ``value`` in each row's cell; NaN if the count is unknown or the cell has
        fewer than ``min_samples`` reference values. ``value`` need not occur in the reference."""
        value = np.asarray(value, dtype=float)
        known = np.isfinite(value)
        _check_counts(value[known])
        ok = known & (cell >= 0) & (self.n_samples(cell) >= self.min_samples)
        out = np.full(len(value), np.nan)
        c = cell[ok].astype(np.int64)
        q = c * _BIG + np.rint(value[ok]).astype(np.int64)
        lt = np.searchsorted(self._sorted, q, side="left") - self._start[c]
        le = np.searchsorted(self._sorted, q, side="right") - self._start[c]
        out[ok] = (lt + le) * 50.0 / self.n[c]  # exact at the cut points: ints divided by an int
        return out

    def cell_values(self, cell: int) -> np.ndarray:
        return self._sorted[self._start[cell] : self._start[cell + 1]] - cell * _BIG

    def summary(self, cuts: np.ndarray, class_slugs: list[str], min_mean: float) -> pd.DataFrame:
        """One row per cell with data: its size, mean and median and, per class above the first, the smallest count
        that reaches it (``trips_from_<class>``); the count below ``trips_from_<second class>`` is the first class."""
        rows = []
        for cell in np.flatnonzero(self.n > 0):
            vals = self.cell_values(cell)
            cand = np.arange(0, int(vals[-1]) + 2)
            lt = np.searchsorted(vals, cand, side="left")
            le = np.searchsorted(vals, cand, side="right")
            pct = (lt + le) * 50.0 / len(vals)
            from_count = [int(cand[np.argmax(pct >= c)]) for c in cuts]
            e, s = divmod(int(cell), SLOTS)
            rows.append(
                (
                    self.entity_ids[e],
                    s,
                    s // 24,
                    s % 24,
                    int(self.n[cell]),
                    float(self.mean[cell]),
                    float(np.median(vals)),
                    *from_count,
                )
            )
        names = ["entity_id", "week_slot", "local_dow", "local_hour", "n_train", "train_mean", "train_median"]
        out = pd.DataFrame(rows, columns=[*names, *[f"trips_from_{slug}" for slug in class_slugs]])
        out["usable_for_level"] = (out["n_train"] >= self.min_samples) & (out["train_mean"] >= min_mean)
        return out


def _check_counts(v: np.ndarray) -> None:
    if len(v) and (v.min() < 0 or v.max() >= _BIG or not np.array_equal(v, np.rint(v))):
        raise ValueError("counts must be whole numbers in [0, 1e7)")


def _utc(text: str) -> pd.Timestamp:
    return pd.Timestamp(datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc))


def add_levels(
    frame: pd.DataFrame,
    *,
    train_from: pd.Timestamp,
    train_to: pd.Timestamp,
    horizon: int,
    scheme: TargetScheme,
    min_samples: int,
    min_cell_mean: float,
    group_edges: list[float],
    group_labels: list[str],
) -> tuple[pd.DataFrame, Reference]:
    """The AT-031 ``frame`` plus ``LEVEL_COLUMNS`` (same rows, same order) and the train-only ``Reference``.

    Only rows with ``issued_at_utc`` in ``[train_from, train_to)`` and a known target feed the reference.
    """
    issued = pd.DatetimeIndex(frame["issued_at_utc"])
    entity = frame["entity_id"].to_numpy().astype(str)
    target = frame[F.TARGET].to_numpy(dtype=float)
    in_train = (issued >= train_from) & (issued < train_to) & np.isfinite(target)
    hours = issued.unique().sort_values()
    h_idx = hours.get_indexer(issued)

    def slots_at(offset_hours: int) -> np.ndarray:  # cell slot of the hour T + offset, per row
        return week_slot(hours + pd.Timedelta(hours=offset_hours))[h_idx]

    target_offset = horizon - 1  # the target hour starts at T + horizon - 1
    ref = Reference(entity[in_train], slots_at(target_offset)[in_train], target[in_train], min_samples)
    e_idx = ref.entity_index(entity)
    cuts = scheme_cuts(scheme)
    labels = np.array([c.label for c in scheme.classes], dtype=object)

    out = frame.copy()
    cell = ref.cell(e_idx, slots_at(target_offset))
    rel = ref.percentile(cell, target)
    n_cell = ref.n_samples(cell)
    cell_mean = np.where(cell >= 0, ref.mean[np.maximum(cell, 0)], np.nan)
    status = np.full(len(out), "ok", dtype=object)
    status[cell_mean < min_cell_mean] = "low_volume"
    status[n_cell < min_samples] = "insufficient_samples"
    status[~np.isfinite(target)] = "target_missing"
    level = np.where(status == "ok", labels[np.maximum(classify(rel, cuts), 0)], None)
    out[REL] = rel
    out[LEVEL] = pd.Series(level, index=out.index, dtype=object)
    out[STATUS] = pd.Series(status, index=out.index, dtype=object)
    group = np.searchsorted(np.asarray(group_edges, dtype=float), ref.zone_mean, side="right")
    out[GROUP] = pd.Series(
        np.where(e_idx >= 0, np.array(group_labels, dtype=object)[group[np.maximum(e_idx, 0)]], None),
        index=out.index,
        dtype=object,
    )
    for f in REL_FEATURES:
        if f.name == "rel_mean24h":
            continue
        out[f.name] = ref.percentile(ref.cell(e_idx, slots_at(-f.lag_hours)), frame[f.source].to_numpy(dtype=float))
    out["rel_mean24h"] = _relative_mean(frame["pickups_mean24h"].to_numpy(dtype=float), ref, e_idx, hours, h_idx)
    return out, ref


def _relative_mean(mean24: np.ndarray, ref: Reference, e_idx: np.ndarray, hours: pd.DatetimeIndex, h_idx: np.ndarray):
    """``pickups_mean24h`` over the average of the cell means of the 24 hours it covers; NaN without a full reference."""
    window = np.stack([week_slot(hours - pd.Timedelta(hours=j)) for j in range(1, F.MEAN_WINDOW_HOURS + 1)], axis=1)
    usable = np.where(ref.n >= ref.min_samples, ref.mean, np.nan).reshape(-1, SLOTS)
    expected = np.stack([usable[e][window].mean(axis=1) for e in range(len(ref.entity_ids))])  # (zones, hours)
    exp_row = np.where(e_idx >= 0, expected[np.maximum(e_idx, 0), h_idx], np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(exp_row > 0, mean24 / exp_row, np.nan)


# ------------------------------------------------------------------------------------------------- report


def _split_masks(issued: pd.DatetimeIndex, split: dict) -> dict[str, np.ndarray]:
    return {
        name: np.asarray((issued >= _utc(split[name][0])) & (issued < _utc(split[name][1])))
        for name in ("train", "validation", "test")
    }


def complete_mask(frame: pd.DataFrame) -> np.ndarray:
    """Rows with a class and every model input known (raw and relative)."""
    ok = frame[LEVEL].notna().to_numpy().copy()  # to_numpy() is read-only under copy-on-write (pandas 3)
    for name in MODEL_FEATURE_NAMES:
        ok &= frame[name].notna().to_numpy()
    return ok


def _shares(levels: pd.Series, labels: list[str]) -> dict:
    counts = levels.value_counts().reindex(labels, fill_value=0)
    n = int(counts.sum())
    return {
        "n": n,
        "counts": {k: int(v) for k, v in counts.items()},
        "share": {k: (round(float(v) / n, 5) if n else None) for k, v in counts.items()},
    }


def level_report(frame: pd.DataFrame, config: dict, scheme: TargetScheme, ref: Reference) -> dict:
    split = json.loads(Path(REPO_ROOT / config["base_config"]).read_text())["split"]
    labels = [c.label for c in scheme.classes]
    masks = _split_masks(pd.DatetimeIndex(frame["issued_at_utc"]), split)
    complete = complete_mask(frame)
    groups = config["volume_groups"]["labels"]
    local = pd.DatetimeIndex(frame["issued_at_utc"]).tz_convert(aggregate.TIMEZONE)
    month = (local.year * 100 + local.month).to_numpy()
    in_group = {g: (frame[GROUP] == g).to_numpy() for g in groups}
    periods = {}
    for name, m in masks.items():
        sub = frame[m]
        periods[name] = {
            "rows": int(m.sum()),
            "complete_rows": int((m & complete).sum()),
            "status_counts": {s: int((sub[STATUS] == s).sum()) for s in STATUSES},
            "classes_complete_rows": _shares(frame.loc[m & complete, LEVEL], labels),
            "classes_by_volume_group": {
                g: _shares(frame.loc[m & complete & in_group[g], LEVEL], labels) for g in groups
            },
        }
    by_month = {}
    for mo in sorted(set(month.tolist())):
        sel = (month == mo) & complete
        by_month[f"{mo // 100}-{mo % 100:02d}"] = {
            "all": _shares(frame.loc[sel, LEVEL], labels),
            **{g: _shares(frame.loc[sel & in_group[g], LEVEL], labels) for g in groups},
        }
    zone_groups = frame.drop_duplicates("entity_id").groupby(GROUP)["entity_id"].count()
    cells = int((ref.n > 0).sum())
    usable = int(((ref.n >= ref.min_samples) & (ref.mean >= config["reference"]["min_cell_mean_pickups_per_hour"])).sum())
    return {
        "task_id": config["task_id"],
        "labels": labels,
        "cuts": scheme_cuts(scheme).tolist(),
        "reference": config["reference"],
        "cells": {
            "with_train_data": cells,
            "usable_for_level": usable,
            "min_n": int(ref.n[ref.n > 0].min()),
            "median_n": float(np.median(ref.n[ref.n > 0])),
        },
        "zones_per_volume_group": {g: int(zone_groups.get(g, 0)) for g in groups},
        "periods": periods,
        "by_local_month_complete_rows": by_month,
    }


# ------------------------------------------------------------------------------------------------- build


def _peak_rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def build_level_table(
    base_table_dir: Path,
    out_dir: Path,
    config: dict,
    *,
    memory_limit: str = "1500MB",
    threads: int = 4,
) -> dict:
    """Read the AT-031 table in ``base_table_dir`` and write ``<out_dir>/nyc_pickups_h1_level/year=/month=/`` plus the
    sidecars ``nyc_pickups_h1_level_reference.parquet`` and ``nyc_pickups_h1_level_report.json``."""
    started = time.perf_counter()
    base = json.loads((REPO_ROOT / config["base_config"]).read_text())
    scheme = load_scheme(REPO_ROOT / config["scheme"])
    ref_cfg, groups = config["reference"], config["volume_groups"]
    frame = pd.read_parquet(base_table_dir, columns=list(F.TABLE_COLUMNS)).reset_index(drop=True)
    n_in = len(frame)
    frame["entity_id"] = frame["entity_id"].astype(str)
    out, ref = add_levels(
        frame,
        train_from=_utc(base["split"]["train"][0]),
        train_to=_utc(base["split"]["train"][1]),
        horizon=int(base["horizon_hours"]),
        scheme=scheme,
        min_samples=int(ref_cfg["min_samples"]),
        min_cell_mean=float(ref_cfg["min_cell_mean_pickups_per_hour"]),
        group_edges=groups["edges"],
        group_labels=groups["labels"],
    )
    if len(out) != n_in:
        raise SystemExit("the level table lost or gained rows")
    name = config.get("table_dirname", TABLE_DIRNAME)  # another horizon writes next to the h1 table, never over it
    table_dir = out_dir / name
    if table_dir.exists():
        shutil.rmtree(table_dir)
    table_dir.mkdir(parents=True)
    _write_partitioned(out, table_dir, memory_limit, threads, out_dir / "_duckdb_tmp")
    summary = ref.summary(
        scheme_cuts(scheme),
        [c.label.replace(" ", "_") for c in scheme.classes[1:]],
        float(ref_cfg["min_cell_mean_pickups_per_hour"]),
    )
    pq.write_table(pa.Table.from_pandas(summary, preserve_index=False), out_dir / f"{name}_reference.parquet")
    report = level_report(out, config, scheme, ref)
    report["rows"] = n_in
    report["columns"] = list(TABLE_COLUMNS)
    report["built_at_utc"] = datetime.now(timezone.utc).isoformat()
    report["perf"] = {"seconds": round(time.perf_counter() - started, 2), "peak_rss_mb": round(_peak_rss_mb(), 1)}
    (out_dir / f"{name}_report.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    return report


def _write_partitioned(frame: pd.DataFrame, table_dir: Path, memory_limit: str, threads: int, tmp: Path) -> None:
    arrays = {c: pa.Array.from_pandas(frame[c]) for c in TABLE_COLUMNS}
    for c in ("entity_id", LEVEL, STATUS, GROUP):
        arrays[c] = pa.array(frame[c].astype(object).where(frame[c].notna(), None), pa.string(), from_pandas=True)
    table = pa.table(arrays)
    con = aggregate.connect(memory_limit, threads, temp_dir=tmp)
    try:
        con.register("lvl", table)
        cols = ", ".join(TABLE_COLUMNS)
        con.execute(
            f"""
            COPY (
                SELECT {cols},
                       CAST(year(issued_at_utc AT TIME ZONE 'UTC') AS INTEGER) AS year,
                       CAST(month(issued_at_utc AT TIME ZONE 'UTC') AS INTEGER) AS month
                FROM lvl ORDER BY CAST(entity_id AS INTEGER), issued_at_utc
            ) TO '{table_dir}' (FORMAT PARQUET, COMPRESSION ZSTD, PARTITION_BY (year, month))
            """
        )
    finally:
        con.close()
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the NYC relative-level pickup table (AT-031b).")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--processed-dir", type=Path, default=PROCESSED_DIR / "mobility")
    parser.add_argument("--out-dir", type=Path, default=None, help="default: <processed-dir>/features (also where the AT-031 table is read)")
    parser.add_argument("--memory-limit", default="1500MB")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--write-spec", action="store_true", help=f"also rewrite {F.FEATURE_SPEC_PATH.name}")
    args = parser.parse_args(argv)
    features_dir = args.processed_dir / "features"
    out_dir = args.out_dir or features_dir
    base_name = json.loads((REPO_ROOT / load_config(args.config)["base_config"]).read_text()).get("table_dirname", F.TABLE_DIRNAME)
    report = build_level_table(
        features_dir / base_name, out_dir, load_config(args.config), memory_limit=args.memory_limit, threads=args.threads
    )
    if args.write_spec:
        write_feature_spec()
    print(
        f"{report['rows']:,} rows; cells usable for a level {report['cells']['usable_for_level']:,} of "
        f"{report['cells']['with_train_data']:,}; {report['perf']['seconds']} s, peak RSS {report['perf']['peak_rss_mb']} MB",
        flush=True,
    )


if __name__ == "__main__":
    os.environ.setdefault("OMP_NUM_THREADS", "4")
    main()
