"""Feature/target table for 1-hour-ahead yellow-taxi pickup demand per taxi zone (AT-031).

    PYTHONPATH=src python -m atlas.domains.mobility.features

Timing convention (the leakage tests pin it):

* ``pickups[h]`` is the number of trips picked up in the UTC hour ``[h, h+1)`` (the canonical series of AT-030, keyed by
  the hour *start*).
* A forecast is issued at ``issued_at_utc = T``, always on the hour, and may use only hours that ended by ``T``, i.e. hour
  starts ``h <= T - 1h``.
* Its target is ``pickups[T]``, the pickups in ``[T, T+1)``, so ``valid_at_utc = T + 1h`` (the end of the target window).
* ``lag_hours`` of a feature is the age at ``T`` of the **most recent hour start** it uses (``T - lag_hours``); for a
  window aggregate that is the start of its newest hour.
* Null semantics: genuine zero counts stay 0. A feature or target that needs an hour outside the covered period, or the
  ambiguous DST hour (null in the series), is null; a window aggregate needs every hour of its window.

The table has one row per (selected zone, issue hour); the issue hours are all the hours of the covered period, so the first
168 h of each zone are present but incomplete. Zones enter the task by a train-period-only rate threshold; the others are
listed in ``nyc_pickups_h1_zone_selection.json`` and stay on the map as "no model".
"""

# ruff: noqa: E501  (prose and long SQL)

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

import duckdb

from atlas.domains.mobility import aggregate
from atlas.paths import PROCESSED_DIR, REPO_ROOT

CONFIG_PATH = REPO_ROOT / "configs" / "mobility" / "nyc_pickups_h1.json"
FEATURE_SPEC_PATH = REPO_ROOT / "configs" / "mobility" / "feature_spec.json"
TABLE_DIRNAME = "nyc_pickups_h1"
SOURCE_ID = aggregate.SOURCE_ID
CALENDAR_SOURCE_ID = "calendar-america-new-york"
MEAN_WINDOW_HOURS = 24
KEYS = ("entity_id", "issued_at_utc", "valid_at_utc")
TARGET = "target"


@dataclass(frozen=True)
class Feature:
    name: str
    unit: str
    source_id: str
    lag_hours: int  # age at T of the most recent source hour start used
    description: str


FEATURES: tuple[Feature, ...] = (
    Feature("pickups_lag1", "trips", SOURCE_ID, 1, "pickups in [T-1h, T): the hour that has just ended"),
    Feature("pickups_lag2", "trips", SOURCE_ID, 2, "pickups in [T-2h, T-1h)"),
    Feature(
        "pickups_lag24", "trips", SOURCE_ID, 24, "pickups in [T-24h, T-23h): the target hour, 24 elapsed hours earlier"
    ),
    Feature(
        "pickups_lag168",
        "trips",
        SOURCE_ID,
        168,
        "pickups in [T-168h, T-167h): the target hour, 168 elapsed hours earlier",
    ),
    Feature(
        "pickups_mean24h",
        "trips/hour",
        SOURCE_ID,
        1,
        f"mean of the {MEAN_WINDOW_HOURS} hourly counts in [T-{MEAN_WINDOW_HOURS}h, T); null unless all {MEAN_WINDOW_HOURS} are known",
    ),
    Feature(
        "local_hour",
        "hour",
        CALENDAR_SOURCE_ID,
        0,
        "America/New_York clock hour of the target window's start, T + (horizon - 1) h (0-23); T itself at horizon 1",
    ),
    Feature(
        "local_dow", "weekday_index", CALENDAR_SOURCE_ID, 0, "America/New_York weekday of the target window's start, T + (horizon - 1) h, Monday=0 ... Sunday=6"
    ),
)
FEATURE_NAMES = tuple(f.name for f in FEATURES)
TABLE_COLUMNS = (*KEYS, TARGET, *FEATURE_NAMES)


def load_config(path: Path = CONFIG_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def feature_spec() -> dict:
    """The ``feature_spec.json`` payload (``docs/api.md``): per feature unit, source_id and lag_hours."""
    return {
        "features": {f.name: {"unit": f.unit, "source_id": f.source_id, "lag_hours": f.lag_hours} for f in FEATURES}
    }


def write_feature_spec(path: Path = FEATURE_SPEC_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(feature_spec(), indent=2) + "\n", encoding="utf-8")
    return path


def _peak_rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # KiB on Linux


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def _zone_names(zones_geojson: Path | None) -> dict[str, dict]:
    if zones_geojson is None or not zones_geojson.exists():
        return {}
    collection = json.loads(zones_geojson.read_text(encoding="utf-8"))
    out = {}
    for feature in collection.get("features", []):
        props = feature.get("properties", {})
        out[str(feature.get("id"))] = {"name": props.get("name"), "borough": props.get("attributes", {}).get("borough")}
    return out


def select_zones(
    con: duckdb.DuckDBPyConnection, train_from: datetime, train_to: datetime, min_mean_per_hour: float
) -> list[dict]:
    """Zones whose mean pickups per known hour in ``[train_from, train_to)`` reach the threshold.

    Reads only train-period hours of ``obs``: nothing after ``train_to`` can change the selection.
    """
    rows = con.execute(
        """
        SELECT e.entity_id, coalesce(sum(o.value), 0), count(o.value)
        FROM (SELECT DISTINCT entity_id FROM obs) e
        LEFT JOIN obs o ON o.entity_id = e.entity_id AND o.ts >= ? AND o.ts < ?
        GROUP BY e.entity_id
        """,
        [train_from, train_to],
    ).fetchall()
    out = []
    for entity_id, pickups, hours in sorted(rows, key=lambda r: (len(r[0]), r[0])):
        rate = pickups / hours if hours else None
        included = rate is not None and rate >= min_mean_per_hour
        out.append(
            {
                "entity_id": entity_id,
                "train_pickups": int(pickups),
                "train_known_hours": int(hours),
                "train_mean_pickups_per_hour": None if rate is None else round(rate, 4),
                "included": bool(included),
                "reason": None
                if included
                else (
                    "no_known_train_hours" if not hours else f"train_mean_pickups_per_hour_below_{min_mean_per_hour:g}"
                ),
            }
        )
    return out


def build_features(
    observations: str | Path,
    out_dir: Path,
    config: dict,
    *,
    zones_geojson: Path | None = None,
    memory_limit: str = "1500MB",
    threads: int = 4,
) -> dict:
    """Write ``<out_dir>/nyc_pickups_h1/year=/month=/part-*.parquet`` (Parquet only, so a directory read works) plus the
    sidecars ``<out_dir>/nyc_pickups_h1_zone_selection.json`` and ``<out_dir>/nyc_pickups_h1_feature_report.json``.

    ``observations`` is a Parquet glob of the canonical series (needs ``entity_id``, ``timestamp_utc``, ``value``).
    """
    started = time.perf_counter()
    horizon = int(config["horizon_hours"])
    split = config["split"]
    train_from, train_to = _utc(split["train"][0]), _utc(split["train"][1])
    min_rate = float(config["zone_filter"]["min_train_mean_pickups_per_hour"])
    name = config.get("table_dirname", TABLE_DIRNAME)  # another horizon writes next to the h1 table, never over it
    table_dir = out_dir / name
    if table_dir.exists():
        shutil.rmtree(table_dir)
    table_dir.mkdir(parents=True)
    con = aggregate.connect(memory_limit, threads, temp_dir=out_dir / "_duckdb_tmp")
    try:
        version_sql = "CAST(data_version AS VARCHAR)" if _has_column(con, observations, "data_version") else "NULL"
        con.execute(
            "CREATE TEMP TABLE obs AS SELECT CAST(entity_id AS VARCHAR) AS entity_id, timestamp_utc AS ts, "
            f"CAST(value AS DOUBLE) AS value, {version_sql} AS data_version FROM read_parquet(?, hive_partitioning=true)",
            [str(observations)],
        )
        n_obs, n_unique, n_off_hour, n_hours, n_entities, first_ts, last_ts = con.execute(
            "SELECT count(*), count(DISTINCT (entity_id, ts)), count(*) FILTER (WHERE ts <> date_trunc('hour', ts)), "
            "count(DISTINCT ts), count(DISTINCT entity_id), min(ts), max(ts) FROM obs"
        ).fetchall()[0]
        if n_obs == 0:
            raise SystemExit(f"no observations under {observations}")
        if n_obs != n_unique:
            raise SystemExit(
                "the series has several rows for one (entity_id, timestamp_utc): a join would multiply rows"
            )
        if n_off_hour:
            raise SystemExit("the series has timestamps that are not on the hour")
        data_version = [
            r[0] for r in con.execute("SELECT DISTINCT data_version FROM obs").fetchall() if r[0] is not None
        ]

        zones = select_zones(con, train_from, train_to, min_rate)
        names = _zone_names(zones_geojson)
        for z in zones:
            z.update(names.get(z["entity_id"], {}))
        selected = [z["entity_id"] for z in zones if z["included"]]
        con.execute("CREATE TEMP TABLE sel(entity_id VARCHAR)")
        con.executemany("INSERT INTO sel VALUES (?)", [[e] for e in selected])
        if not selected:
            raise SystemExit("the zone filter left no zone")

        target_offset = horizon - 1  # target hour start = T + (horizon - 1) h = valid_at - 1 h
        f = {x.name: x for x in FEATURES}
        con.execute(
            f"""
            COPY (
                WITH hours AS (SELECT DISTINCT ts AS t FROM obs),
                base AS (SELECT s.entity_id, h.t FROM sel s CROSS JOIN hours h),
                roll AS (
                    SELECT entity_id, ts,
                           CASE WHEN count(*) OVER w = {MEAN_WINDOW_HOURS} AND count(value) OVER w = {MEAN_WINDOW_HOURS}
                                THEN avg(value) OVER w END AS mean_v
                    FROM obs WHERE entity_id IN (SELECT entity_id FROM sel)
                    WINDOW w AS (PARTITION BY entity_id ORDER BY ts
                                 RANGE BETWEEN INTERVAL {MEAN_WINDOW_HOURS} HOUR PRECEDING AND INTERVAL 1 HOUR PRECEDING)
                )
                SELECT
                    b.entity_id,
                    b.t AS issued_at_utc,
                    b.t + INTERVAL {horizon} HOUR AS valid_at_utc,
                    y.value AS {TARGET},
                    l1.value AS pickups_lag1,
                    l2.value AS pickups_lag2,
                    l24.value AS pickups_lag24,
                    l168.value AS pickups_lag168,
                    r.mean_v AS pickups_mean24h,
                    CAST(hour(timezone('{aggregate.TIMEZONE}', b.t + INTERVAL {target_offset} HOUR)) AS INTEGER) AS local_hour,
                    CAST(isodow(timezone('{aggregate.TIMEZONE}', b.t + INTERVAL {target_offset} HOUR)) - 1 AS INTEGER) AS local_dow,
                    CAST(year(b.t AT TIME ZONE 'UTC') AS INTEGER) AS year,
                    CAST(month(b.t AT TIME ZONE 'UTC') AS INTEGER) AS month
                FROM base b
                LEFT JOIN obs y ON y.entity_id = b.entity_id AND y.ts = b.t + INTERVAL {target_offset} HOUR
                LEFT JOIN obs l1 ON l1.entity_id = b.entity_id AND l1.ts = b.t - INTERVAL {f["pickups_lag1"].lag_hours} HOUR
                LEFT JOIN obs l2 ON l2.entity_id = b.entity_id AND l2.ts = b.t - INTERVAL {f["pickups_lag2"].lag_hours} HOUR
                LEFT JOIN obs l24 ON l24.entity_id = b.entity_id AND l24.ts = b.t - INTERVAL {f["pickups_lag24"].lag_hours} HOUR
                LEFT JOIN obs l168 ON l168.entity_id = b.entity_id AND l168.ts = b.t - INTERVAL {f["pickups_lag168"].lag_hours} HOUR
                LEFT JOIN roll r ON r.entity_id = b.entity_id AND r.ts = b.t
                ORDER BY CAST(b.entity_id AS INTEGER), b.t
            ) TO '{table_dir}' (FORMAT PARQUET, COMPRESSION ZSTD, PARTITION_BY (year, month))
            """
        )
        report = _report(con, table_dir, config, zones, selected, first_ts, last_ts, n_hours, n_entities, data_version)
    finally:
        con.close()
        shutil.rmtree(out_dir / "_duckdb_tmp", ignore_errors=True)
    report["perf"] = {"seconds": round(time.perf_counter() - started, 2), "peak_rss_mb": round(_peak_rss_mb(), 1)}
    (out_dir / f"{name}_zone_selection.json").write_text(
        json.dumps({"filter": config["zone_filter"], "train_period_utc": split["train"], "zones": zones}, indent=1)
        + "\n",
        encoding="utf-8",
    )
    (out_dir / f"{name}_feature_report.json").write_text(
        json.dumps(report, indent=1, default=str) + "\n", encoding="utf-8"
    )
    return report


def _has_column(con: duckdb.DuckDBPyConnection, observations: str | Path, column: str) -> bool:
    names = [
        r[0]
        for r in con.execute(
            "DESCRIBE SELECT * FROM read_parquet(?, hive_partitioning=true)", [str(observations)]
        ).fetchall()
    ]
    return column in names


def _report(con, table_dir, config, zones, selected, first_ts, last_ts, n_hours, n_entities, data_version) -> dict:
    split = config["split"]
    con.execute(
        f"CREATE TEMP VIEW tbl AS SELECT * FROM read_parquet('{table_dir}/**/*.parquet', hive_partitioning=true)"
    )
    feat_ok = " AND ".join(f"{n} IS NOT NULL" for n in FEATURE_NAMES)
    complete = f"({TARGET} IS NOT NULL AND {feat_ok})"
    rows, complete_rows, warmup = con.execute(
        f"SELECT count(*), count(*) FILTER (WHERE {complete}), "
        f"count(*) FILTER (WHERE issued_at_utc - INTERVAL {max(f.lag_hours for f in FEATURES)} HOUR < ?) FROM tbl",
        [first_ts],
    ).fetchall()[0]
    null_counts = dict(
        zip(
            [TARGET, *FEATURE_NAMES],
            con.execute(
                "SELECT "
                + ", ".join(f"count(*) FILTER (WHERE {c} IS NULL)" for c in [TARGET, *FEATURE_NAMES])
                + " FROM tbl"
            ).fetchall()[0],
            strict=True,
        )
    )
    after_warmup_incomplete = con.execute(
        f"SELECT count(*) FROM tbl WHERE NOT {complete} AND "
        f"issued_at_utc - INTERVAL {max(f.lag_hours for f in FEATURES)} HOUR >= ?",
        [first_ts],
    ).fetchall()[0][0]
    periods = {}
    for name in ("train", "validation", "test"):
        lo, hi = _utc(split[name][0]), _utc(split[name][1])
        n, c, z = con.execute(
            f"SELECT count(*), count(*) FILTER (WHERE {complete}), "
            f"count(*) FILTER (WHERE {TARGET} IS NOT NULL AND {TARGET} = 0) FROM tbl WHERE issued_at_utc >= ? AND issued_at_utc < ?",
            [lo, hi],
        ).fetchall()[0]
        periods[name] = {
            "issued_from_utc": split[name][0],
            "issued_to_utc": split[name][1],
            "rows": n,
            "complete_rows": c,
            "target_zero_rows": z,
        }
    n_issue_hours = con.execute("SELECT count(DISTINCT issued_at_utc) FROM tbl").fetchall()[0][0]
    return {
        "task_id": config["task_id"],
        "horizon_hours": config["horizon_hours"],
        "data_version": data_version[0] if len(data_version) == 1 else data_version,
        "table_path": str(table_dir),
        "columns": list(TABLE_COLUMNS),
        "features": feature_spec()["features"],
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "series_coverage_utc": [first_ts.isoformat(), last_ts.isoformat()],
        "zones_in_series": n_entities,
        "zones_selected": len(selected),
        "zones_excluded": [z["entity_id"] for z in zones if not z["included"]],
        "zone_filter": config["zone_filter"],
        "issue_hours": n_issue_hours,
        "rows": rows,
        "rows_expected_zones_x_issue_hours": len(selected) * n_hours,
        "complete_rows": complete_rows,
        "incomplete_rows": rows - complete_rows,
        "rows_in_warmup_first_168h": warmup,  # the weekly lag falls before the covered period: always incomplete
        "incomplete_rows_after_warmup": after_warmup_incomplete,
        "null_counts": null_counts,
        "periods": periods,
        "split": split,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the NYC 1-hour-ahead pickup demand table (AT-031).")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--processed-dir", type=Path, default=PROCESSED_DIR / "mobility", help="holds observations/")
    parser.add_argument("--out-dir", type=Path, default=None, help="default: <processed-dir>/features")
    parser.add_argument("--memory-limit", default="1500MB")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--write-spec", action="store_true", help=f"also rewrite {FEATURE_SPEC_PATH.name}")
    parser.add_argument(
        "--eda",
        type=Path,
        nargs="?",
        const=Path("docs/mobility/nyc_pickups_h1_eda.md"),
        default=None,
        help="also write the EDA markdown (default path docs/mobility/nyc_pickups_h1_eda.md)",
    )
    args = parser.parse_args(argv)
    config = load_config(args.config)
    out_dir = args.out_dir or args.processed_dir / "features"
    out_dir.mkdir(parents=True, exist_ok=True)
    report = build_features(
        args.processed_dir / "observations" / "**" / "*.parquet",
        out_dir,
        config,
        zones_geojson=args.processed_dir / "taxi_zones.geojson",
        memory_limit=args.memory_limit,
        threads=args.threads,
    )
    if args.write_spec:
        from atlas.domains.mobility import levels  # the file also lists the relative features of AT-031b

        levels.write_feature_spec()
    if args.eda is not None:
        from atlas.domains.mobility import eda

        eda.write_eda(
            Path(report["table_path"]), config, args.eda, memory_limit=args.memory_limit, threads=args.threads
        )
    print(
        f"{report['rows']:,} rows ({report['complete_rows']:,} complete) = {report['zones_selected']} zones x "
        f"{report['issue_hours']:,} issue hours; {report['perf']['seconds']} s, peak RSS {report['perf']['peak_rss_mb']} MB",
        flush=True,
    )


if __name__ == "__main__":
    os.environ.setdefault("OMP_NUM_THREADS", "4")
    main()
