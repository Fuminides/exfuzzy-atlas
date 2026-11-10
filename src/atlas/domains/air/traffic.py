"""Madrid traffic ingestion CLI (AT-012): 15-minute measurement-point records -> hourly canonical observations.

    PYTHONPATH=src python -m atlas.domains.air.traffic --months 2023-01:2025-12

Steps: idempotent download of the monthly zips and the monthly measurement-point location files (+ manifests)
-> correspondence study with the air stations -> one month at a time: unzip to a staging directory, aggregate with
bounded-memory DuckDB, delete the CSV -> hive-partitioned Parquet ``year=/month=`` (UTC) -> contract validation
-> quality report.
"""

# ruff: noqa: E501  (prose and SQL)

from __future__ import annotations

import argparse
import json
import os
import resource
import shutil
import sys
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from atlas.contracts.models import Domain, QualityReport
from atlas.contracts.observations import OBSERVATION_SCHEMA, validate_observations
from atlas.domains.air.association import Point
from atlas.domains.air.ingest import DEFAULT_DATASETS_ROOT, _verify_checksums, ensure_raw_dir
from atlas.domains.air.traffic_points import (
    TrafficPoint,
    month_summary,
    radius_table,
    read_points_csv,
    track_changes,
    within_radius,
)
from atlas.domains.air.traffic_report import render_markdown
from atlas.ingest.sources import Fetcher, ensure_source, http_fetch, read_manifest
from atlas.paths import PROCESSED_DIR, RAW_DIR, REPO_ROOT

CONFIG_PATH = REPO_ROOT / "configs" / "air" / "madrid_traffic.json"
DOC_PATH = REPO_ROOT / "docs" / "air" / "madrid_traffic.md"
SOURCE_ID = "madrid-traffic"
POINTS_ID = "madrid-traffic-points"
TIMEZONE = "Europe/Madrid"


FEATURE_NAME = "traffic_intensity"
UNIT = "veh/h"
CSV_HEADER = ("id", "fecha", "tipo_elem", "intensidad", "ocupacion", "carga", "vmed", "error", "periodo_integracion")
CSV_COLUMNS_SQL = (
    "{'id': 'BIGINT', 'fecha': 'VARCHAR', 'tipo_elem': 'VARCHAR', 'intensidad': 'DOUBLE', 'ocupacion': 'DOUBLE', "
    "'carga': 'DOUBLE', 'vmed': 'DOUBLE', 'error': 'VARCHAR', 'periodo_integracion': 'INTEGER'}"
)
VALID_STATUS = "valid"
# Hour flags written to ``validity_flag`` of the canonical observations.
FLAG_VALID, FLAG_INSUFFICIENT, FLAG_AMBIGUOUS = "valid", "insufficient_valid_records", "ambiguous_local_hour"


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def parse_months(text: str) -> list[str]:
    """``2023-01:2025-12`` -> every ``YYYY-MM`` in the range; ``2023-01,2023-03`` -> that list."""
    if ":" in text:
        lo, _, hi = text.partition(":")
        (y0, m0), (y1, m1) = (tuple(map(int, p.split("-"))) for p in (lo, hi))
        out, y, m = [], y0, m0
        while (y, m) <= (y1, m1):
            out.append(f"{y}-{m:02d}")
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return out
    return sorted({p.strip() for p in text.split(",")})


def download(config: dict, months: list[str], datasets_root: str | None, refresh: bool, fetch: Fetcher = http_fetch):
    """Fetch the raw traffic zips and the monthly location CSVs for ``months``. Returns both manifests."""
    out = {}
    for key, source_id in (("traffic", SOURCE_ID), ("points", POINTS_ID)):
        spec = config[key]
        wanted = [f for f in spec["files"] if f["role"] != "data" or f["month"] in months]
        out[source_id] = ensure_source(
            ensure_raw_dir(source_id, datasets_root),
            source_id=source_id,
            domain=Domain.AIR,
            title=spec["title"],
            landing_url=spec["landing_url"],
            license=spec["license"],
            attribution=spec["attribution"],
            files=wanted,
            period_start=date.fromisoformat(f"{min(months)}-01"),
            notes=spec.get("notes", []),
            fetch=fetch,
            refresh=refresh,
        )
    return out


# ---------------------------------------------------------------------------------------------- resources


def available_mb() -> float:
    """``MemAvailable`` of /proc/meminfo in MB (``inf`` where unavailable)."""
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024
    except OSError:
        pass
    return float("inf")


def wait_for_memory(
    min_mb: float, *, poll_s: float = 120.0, max_wait_s: float = 4 * 3600, sleep=time.sleep, read=available_mb
):
    """Block while less than ``min_mb`` is available (the machine is shared); abort after ``max_wait_s``."""
    waited = 0.0
    while read() < min_mb:
        if waited >= max_wait_s:
            raise SystemExit(f"less than {min_mb:.0f} MB available for {max_wait_s:.0f} s; aborting")
        print(f"  waiting for memory: {read():.0f} MB available < {min_mb:.0f} MB", file=sys.stderr, flush=True)
        sleep(poll_s)
        waited += poll_s


# ---------------------------------------------------------------------------------------------- time


def dst_local_hours(month: str, tz: str = TIMEZONE) -> dict:
    """Local wall-clock hours of ``month`` (``YYYY-MM``) affected by a daylight-saving transition.

    The traffic files carry Europe/Madrid wall-clock time without offset (``fecha``), so on a spring-forward day the
    local hour [02:00, 03:00) does not exist and on a fall-back day it happens twice with the same label.

    Returns:
        ``nonexistent``: naive local hour starts that never happen; ``first_slot_after_gap``: the naive local time just
        after each gap; ``ambiguous``: ``(naive local hour start, UTC start)`` pairs, two per repeated hour.
    """
    zone, utc = ZoneInfo(tz), ZoneInfo("UTC")
    year, mon = map(int, month.split("-"))
    first = datetime(year, mon, 1)
    last = datetime(year + (mon == 12), mon % 12 + 1, 1)
    cursor = first.replace(tzinfo=zone).astimezone(utc) - timedelta(hours=3)
    stop = last.replace(tzinfo=zone).astimezone(utc) + timedelta(hours=3)
    previous, seen, nonexistent, ambiguous = None, {}, [], []
    while cursor < stop:
        local = cursor.astimezone(zone).replace(tzinfo=None)
        if previous is not None and local - previous == timedelta(hours=2):
            nonexistent.append(previous + timedelta(hours=1))
        seen.setdefault(local, []).append(cursor)
        previous = local
        cursor += timedelta(hours=1)
    for local, instants in seen.items():
        if len(instants) > 1 and first <= local < last:
            ambiguous += [(local, instant) for instant in instants]
    keep = [h for h in nonexistent if first <= h < last]
    return {
        "nonexistent": keep,
        "first_slot_after_gap": [h + timedelta(hours=1) for h in keep],
        "ambiguous": sorted(ambiguous),
    }


# ---------------------------------------------------------------------------------------------- aggregation


def unzip_month(zip_path: Path, dest_dir: Path) -> tuple[Path, str]:
    """Stream the single CSV member of a monthly zip to ``dest_dir/traffic.csv``. Returns the path and member name."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        members = [i for i in archive.infolist() if not i.is_dir() and i.filename.lower().endswith(".csv")]
        if len(members) != 1:
            raise SystemExit(f"{zip_path.name}: expected exactly one CSV member, found {[m.filename for m in members]}")
        target = dest_dir / "traffic.csv"
        with archive.open(members[0]) as src, target.open("wb") as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
    return target, members[0].filename


def _insert(con: duckdb.DuckDBPyConnection, sql: str, rows: list[tuple]) -> None:
    if rows:  # executemany rejects an empty parameter list
        con.executemany(sql, rows)


def write_partitions(staging: Path, observations: Path) -> None:
    """Staged monthly parts (already sorted by entity and time) -> hive ``year=/month=`` (UTC), in little memory."""
    if observations.exists():
        shutil.rmtree(observations)
    con = duckdb.connect()
    con.execute("SET memory_limit='600MB'")
    con.execute("SET threads=2")
    con.execute("SET TimeZone='UTC'")
    con.execute(
        f"COPY (SELECT *, year(timestamp_utc) AS year, month(timestamp_utc) AS month "
        f"FROM read_parquet('{staging}/*.parquet')) "
        f"TO '{observations}' (FORMAT PARQUET, COMPRESSION ZSTD, PARTITION_BY (year, month))"
    )
    con.close()


def check_header(csv_path: Path) -> None:
    with csv_path.open(encoding="utf-8-sig") as handle:
        header = tuple(handle.readline().strip().replace('"', "").split(";"))
    if header != CSV_HEADER:
        raise SystemExit(f"{csv_path.name}: header {header} != expected {CSV_HEADER} (schema change?)")


def aggregate_month(
    csv_path: Path,
    ids: set[int],
    month: str,
    *,
    data_version: str,
    min_valid: int = 3,
    max_intensity: float = 20_000.0,
    memory_limit: str = "1GB",
    threads: int = 2,
    profile: bool = True,
) -> tuple[pa.Table, dict]:
    """15-minute records of one month -> hourly canonical observations of the points in ``ids``.

    Rules (documented in ``docs/air/madrid_traffic.md``):

    * a 15-minute record is *valid* only if its ``error`` flag is ``N`` and ``0 <= intensidad <= max_intensity``;
      blank/E/S flags, missing, negative or implausible intensities, duplicated slots and the first slot after a
      spring-forward gap are invalid; local times inside the spring gap are dropped (they do not exist);
    * the hour (Europe/Madrid wall clock -> UTC start of hour) is the mean intensity (veh/h) of its valid records and is
      only a value if at least ``min_valid`` of its 4 records are valid; otherwise it is null (never 0);
    * the repeated fall-back hour appears once in the file, so both UTC hours are null (``ambiguous_local_hour``);
    * an hour with no record at all has no row (absence of source slot).

    Returns:
        The canonical observations (``OBSERVATION_SCHEMA``) and the month's statistics.
    """
    check_header(csv_path)
    dst = dst_local_hours(month)
    year, mon = map(int, month.split("-"))
    start = datetime(year, mon, 1)
    end = datetime(year + (mon == 12), mon % 12 + 1, 1)
    con = duckdb.connect()
    con.execute(f"SET memory_limit='{memory_limit}'")
    con.execute(f"SET threads={threads}")
    con.execute("SET TimeZone='UTC'")
    con.execute("CREATE TEMP TABLE sel(point_id BIGINT)")
    _insert(con, "INSERT INTO sel VALUES (?)", [(int(i),) for i in sorted(ids)])
    con.execute("CREATE TEMP TABLE nonexistent(local_hour TIMESTAMP)")
    _insert(con, "INSERT INTO nonexistent VALUES (?)", [(h,) for h in dst["nonexistent"]])
    con.execute("CREATE TEMP TABLE after_gap(slot TIMESTAMP)")
    _insert(con, "INSERT INTO after_gap VALUES (?)", [(h,) for h in dst["first_slot_after_gap"]])
    con.execute("CREATE TEMP TABLE ambiguous_hours(local_hour TIMESTAMP, utc_hour TIMESTAMPTZ)")
    _insert(con, "INSERT INTO ambiguous_hours VALUES (?, ?)", dst["ambiguous"])

    source = (
        f"(SELECT *, coalesce(try_strptime(fecha, '%Y-%m-%d %H:%M:%S'), try_strptime(fecha, '%d/%m/%Y %H:%M:%S')) "
        f"AS local_ts FROM read_csv('{csv_path}', delim=';', quote='\"', header=true, nullstr=['NaN'], "
        f"columns={CSV_COLUMNS_SQL}))"
    )
    stats: dict = {"month": month, "ids_requested": len(ids)}
    if profile:
        stats["file_profile"] = [
            {
                "tipo_elem": r[0],
                "error": r[1],
                "records": int(r[2]),
                "points": int(r[3]),
                "intensity_missing": int(r[4]),
                "intensity_negative": int(r[5]),
                "intensity_over_cap": int(r[6]),
            }
            for r in con.execute(
                f"SELECT tipo_elem, coalesce(error, ''), count(*), count(DISTINCT id), "
                f"count(*) FILTER (WHERE intensidad IS NULL), count(*) FILTER (WHERE intensidad < 0), "
                f"count(*) FILTER (WHERE intensidad > {max_intensity}) FROM {source} GROUP BY ALL ORDER BY ALL"
            ).fetchall()
        ]
    con.execute(
        f"CREATE TEMP TABLE rec AS SELECT id AS point_id, local_ts, intensidad, coalesce(error, '') AS error "
        f"FROM {source} WHERE id IN (SELECT point_id FROM sel)"
    )
    unparseable = con.execute("SELECT count(*) FROM rec WHERE local_ts IS NULL").fetchone()[0]
    if unparseable:
        raise SystemExit(
            f"{csv_path.name}: {unparseable} timestamps in neither '%Y-%m-%d %H:%M:%S' nor '%d/%m/%Y %H:%M:%S'"
        )
    con.execute(
        f"""CREATE TEMP TABLE cls AS SELECT point_id, local_ts, intensidad,
        CASE WHEN local_ts < TIMESTAMP '{start:%Y-%m-%d}' OR local_ts >= TIMESTAMP '{end:%Y-%m-%d}' THEN 'outside_declared_month'
             WHEN date_trunc('hour', local_ts) IN (SELECT local_hour FROM nonexistent) THEN 'dst_nonexistent_local_time'
             WHEN count(*) OVER (PARTITION BY point_id, local_ts) > 1 THEN 'duplicate_slot'
             WHEN error <> 'N' THEN 'error_flag_' || CASE WHEN error = '' THEN 'blank' ELSE error END
             WHEN intensidad IS NULL THEN 'intensity_missing'
             WHEN intensidad < 0 THEN 'intensity_negative'
             WHEN local_ts IN (SELECT slot FROM after_gap) THEN 'dst_transition_slot'
             WHEN intensidad > {max_intensity} THEN 'intensity_implausible'
             ELSE '{VALID_STATUS}' END AS status
        FROM rec"""
    )
    stats["selected_status"] = {
        r[0]: int(r[1]) for r in con.execute("SELECT status, count(*) FROM cls GROUP BY ALL ORDER BY ALL").fetchall()
    }
    con.execute(
        "CREATE TEMP TABLE hourly AS SELECT point_id, date_trunc('hour', local_ts) AS local_hour, count(*) AS n_records, "
        f"count(*) FILTER (WHERE status = '{VALID_STATUS}') AS n_valid, "
        f"avg(intensidad) FILTER (WHERE status = '{VALID_STATUS}') AS mean_intensity "
        "FROM cls WHERE status NOT IN ('outside_declared_month', 'dst_nonexistent_local_time') GROUP BY 1, 2"
    )
    relation = con.sql(
        f"""SELECT 'air' AS domain, CAST(point_id AS VARCHAR) AS entity_id, utc AS timestamp_utc,
        strftime(local_hour, '%Y-%m-%d %H:%M:%S') AS source_timestamp_local, '{TIMEZONE}' AS timezone,
        '{FEATURE_NAME}' AS feature_name,
        CASE WHEN NOT ambiguous AND n_valid >= {min_valid} THEN mean_intensity END AS value, '{UNIT}' AS unit,
        CASE WHEN ambiguous THEN '{FLAG_AMBIGUOUS}' WHEN n_valid >= {min_valid} THEN '{FLAG_VALID}'
             ELSE '{FLAG_INSUFFICIENT}' END AS validity_flag,
        CASE WHEN ambiguous OR n_valid < {min_valid} THEN 'invalid_observation' END AS missing_reason,
        CAST(NULL AS VARCHAR) AS censoring, '{SOURCE_ID}' AS source_id, '{data_version}' AS data_version,
        utc AS aggregation_window_start_utc, utc + INTERVAL 1 HOUR AS aggregation_window_end_utc,
        CAST(n_valid AS BIGINT) AS n_records
        FROM (
            SELECT point_id, local_hour, n_valid, mean_intensity, timezone('{TIMEZONE}', local_hour) AS utc, false AS ambiguous
            FROM hourly WHERE local_hour NOT IN (SELECT local_hour FROM ambiguous_hours)
            UNION ALL
            SELECT h.point_id, h.local_hour, h.n_valid, h.mean_intensity, a.utc_hour, true
            FROM hourly h JOIN ambiguous_hours a ON a.local_hour = h.local_hour)
        ORDER BY entity_id, timestamp_utc"""
    )
    table = relation.to_arrow_table() if hasattr(relation, "to_arrow_table") else relation.arrow()
    con.close()
    table = table.select(OBSERVATION_SCHEMA.names).cast(OBSERVATION_SCHEMA)
    flags = pd.Series(table.column("validity_flag").to_pylist()).value_counts().to_dict()
    stats["hourly_rows"] = table.num_rows
    stats["hourly_by_flag"] = {k: int(v) for k, v in sorted(flags.items())}
    stats["points_with_rows"] = len(set(table.column("entity_id").to_pylist()))
    return table, stats


# ---------------------------------------------------------------------------------------------- correspondence


def no2_station_ids(processed: Path) -> list[str]:
    """Stations with at least one valid NO2 hour: the entities of ``madrid_no2_h6`` (same query as its builder)."""
    con = duckdb.connect()
    ids = [
        r[0]
        for r in con.execute(
            f"SELECT DISTINCT entity_id FROM read_parquet('{processed}/observations/**/*.parquet', hive_partitioning=true) "
            "WHERE feature_name = 'no2' AND value IS NOT NULL ORDER BY 1"
        ).fetchall()
    ]
    con.close()
    return ids


def load_air_stations(processed: Path) -> tuple[list[Point], list[str]]:
    """The ``madrid_no2_h6`` stations that have official coordinates, and the ids of those without (never inferred)."""
    ids = no2_station_ids(processed)
    data = json.loads((processed / "stations.geojson").read_text(encoding="utf-8"))
    located = {
        f["id"]: Point(
            f["id"], f["geometry"]["coordinates"][0], f["geometry"]["coordinates"][1], f["properties"].get("name")
        )
        for f in data["features"]
        if f["geometry"] is not None
    }
    return [located[i] for i in ids if i in located], [i for i in ids if i not in located]


def read_monthly_points(raw_points: Path, months: list[str], files: list[dict]) -> dict[str, list[TrafficPoint]]:
    """``month -> points`` from the location file of that month (the point set changes over time)."""
    by_path = {f["month"]: f["path"] for f in files if f["role"] == "data"}
    return {m: read_points_csv(raw_points / by_path[m]) for m in months}


def build_correspondence(stations: list[Point], by_month: dict[str, list[TrafficPoint]], assoc: dict) -> pd.DataFrame:
    """Every (month, air station, traffic point) pair within the largest study radius, with ``in_rule`` = member of the
    association used by the feature table (distance <= ``radius_m`` and kind in ``kinds``)."""
    frames = []
    for month, points in sorted(by_month.items()):
        rows = within_radius(stations, points, max(assoc["study_radii_m"]))
        frame = pd.DataFrame(
            rows, columns=["air_entity_id", "traffic_point_id", "kind", "name", "distance_m", "rank"]
        ).assign(month=month)
        frames.append(frame)
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    out["in_rule"] = (out["distance_m"] <= assoc["radius_m"]) & out["kind"].isin(assoc["kinds"])
    return out[["month", "air_entity_id", "traffic_point_id", "kind", "name", "distance_m", "rank", "in_rule"]]


def summarize_correspondence(
    stations: list[Point], by_month: dict[str, list[TrafficPoint]], table: pd.DataFrame, assoc: dict
) -> dict:
    """Counts by station, radius and kind for the last month, how they vary over the months, and point-set changes."""
    months = sorted(by_month)
    last = months[-1]
    radii = tuple(float(r) for r in assoc["study_radii_m"])
    per_station = radius_table(stations, by_month[last], radii)
    rule = table[table["in_rule"]]
    counts = (
        rule.groupby(["air_entity_id", "month"])
        .size()
        .unstack(fill_value=0)
        .reindex(index=[s.entity_id for s in stations], columns=months, fill_value=0)
    )
    for entry in per_station:
        row = counts.loc[entry["air_entity_id"]]
        entry["rule_points_last_month"] = int(row[last])
        entry["rule_points_min_month"] = int(row.min())
        entry["rule_points_max_month"] = int(row.max())
        entry["months_without_rule_points"] = int((row == 0).sum())
    return {
        "months": months,
        "last_month": last,
        "rule": {k: assoc[k] for k in ("radius_m", "kinds", "study_radii_m")},
        "files": {m: month_summary(by_month[m]) for m in months},
        "per_station_last_month": per_station,
        "stations_without_rule_points_any_month": sorted(counts.index[(counts == 0).all(axis=1)].tolist()),
        "changes": track_changes(by_month),
    }


def add_data_coverage(summary: dict, table: pd.DataFrame, coverage: pd.DataFrame) -> None:
    """Distance statistics of the rule points and how many of them report data in the last month (in place)."""
    last = summary["last_month"]
    cov = coverage[coverage["month"] == last].set_index("traffic_point_id")
    share = (cov["valid_hours"] / cov["hours_in_month"]).to_dict()
    rule = table[(table["month"] == last) & table["in_rule"]]
    for entry in summary["per_station_last_month"]:
        r = rule[rule["air_entity_id"] == entry["air_entity_id"]]
        entry["rule_median_distance_m"] = float(r["distance_m"].median()) if len(r) else None
        entry["rule_points_with_data_last_month"] = int(
            sum(share.get(int(p), 0.0) >= 0.5 for p in r["traffic_point_id"])
        )


def point_coverage(observations: Path) -> pd.DataFrame:
    """Valid and present hourly rows per (point, local month), from the written observations."""
    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")
    frame = con.execute(
        f"SELECT entity_id AS traffic_point_id, strftime(timezone('{TIMEZONE}', timestamp_utc), '%Y-%m') AS month, "
        "count(*) AS rows, count(value) AS valid_hours "
        f"FROM read_parquet('{observations}/**/*.parquet', hive_partitioning=true) GROUP BY ALL ORDER BY ALL"
    ).fetchdf()
    con.close()
    frame["traffic_point_id"] = frame["traffic_point_id"].astype("int64")
    frame["hours_in_month"] = [
        int(
            (
                pd.Timestamp(f"{m}-01", tz=TIMEZONE) + pd.offsets.MonthBegin(1) - pd.Timestamp(f"{m}-01", tz=TIMEZONE)
            ).total_seconds()
            // 3600
        )
        for m in frame["month"]
    ]
    return frame


# ---------------------------------------------------------------------------------------------- pipeline


def run(
    months: list[str],
    *,
    skip_download: bool = False,
    refresh: bool = False,
    datasets_root: str | None = None,
    out_dir: Path | None = None,
    processed: Path | None = None,
    config: dict | None = None,
    association_only: bool = False,
    min_available_mb: float = 1500.0,
    fetch: Fetcher = http_fetch,
    doc_path: Path | None = None,
) -> dict:
    config = config or load_config()
    processed = processed or PROCESSED_DIR / "air"
    out_dir = out_dir or processed / "traffic"
    version, agg, assoc = config["data_version"], config["aggregation"], config["association"]
    if skip_download:
        manifests = {
            SOURCE_ID: (read_manifest(RAW_DIR / SOURCE_ID), []),
            POINTS_ID: (read_manifest(RAW_DIR / POINTS_ID), []),
        }
    else:
        manifests = download(config, months, datasets_root, refresh, fetch)
    raw_traffic, raw_points = RAW_DIR / SOURCE_ID, RAW_DIR / POINTS_ID
    checksums = _verify_checksums(raw_traffic, SOURCE_ID) | _verify_checksums(raw_points, POINTS_ID)
    manifest = manifests[SOURCE_ID][0]

    stations, no_coordinates = load_air_stations(processed)
    by_month = read_monthly_points(raw_points, months, config["points"]["files"])
    table = build_correspondence(stations, by_month, assoc)
    out_dir.mkdir(parents=True, exist_ok=True)
    table.to_parquet(out_dir / "association.parquet", index=False)
    pts = pd.DataFrame(
        [
            {
                "month": m,
                "traffic_point_id": p.point_id,
                "kind": p.kind,
                "lon": p.lon,
                "lat": p.lat,
                "name": p.name,
                "district": p.district,
            }
            for m, points in sorted(by_month.items())
            for p in points
        ]
    )
    pts.to_parquet(out_dir / "points_monthly.parquet", index=False)
    summary = summarize_correspondence(stations, by_month, table, assoc)
    summary["air_stations_without_coordinates"] = no_coordinates
    (out_dir / "association_summary.json").write_text(
        json.dumps(summary, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if association_only:
        return {"summary": summary}

    staging = out_dir / "_staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    month_stats, inventory = [], {}
    for part, month in enumerate(months):
        ids = set(table.loc[(table["month"] == month) & table["in_rule"], "traffic_point_id"].astype(int))
        wait_for_memory(min_available_mb)
        t0 = time.time()
        csv_path, member = unzip_month(raw_traffic / f"traffic-{month}.zip", staging / "csv")
        try:
            obs, stats = aggregate_month(
                csv_path,
                ids,
                month,
                data_version=version,
                min_valid=agg["min_valid_quarters"],
                max_intensity=agg["intensity_max_veh_h"],
            )
        finally:
            shutil.rmtree(staging / "csv")
        pq.write_table(obs, staging / f"part-{part:05d}.parquet", compression="zstd")
        stats["csv_member"], stats["seconds"] = member, round(time.time() - t0, 1)
        month_stats.append(stats)
        inventory[f"traffic-{month}.zip"] = member
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        print(f"{month}: {stats['hourly_rows']} hourly rows, {stats['seconds']} s, peak RSS {peak:.0f} MB", flush=True)

    observations = out_dir / "observations"
    write_partitions(staging, observations)
    shutil.rmtree(staging)
    # One UTC month at a time: the uniqueness key contains the timestamp, so partitions cannot duplicate each other, and
    # the duplicate check of a 10-million-row dataset in one go needs about 1.7 GB.
    errors = [
        e for part in sorted(observations.glob("year=*/month=*")) for e in validate_observations(part / "*.parquet")
    ]
    if errors:
        raise SystemExit("canonical observations violate the contract: " + "; ".join(errors))

    from atlas.domains.air.ingest import summarize_output  # local import: pulls the heavy summary only when needed

    summ = summarize_output(observations)
    coverage = point_coverage(observations)
    coverage.to_parquet(out_dir / "point_coverage.parquet", index=False)
    add_data_coverage(summary, table, coverage)
    (out_dir / "association_summary.json").write_text(
        json.dumps(summary, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    totals: dict[str, int] = {}
    for s in month_stats:
        for k, v in s["selected_status"].items():
            totals[k] = totals.get(k, 0) + v
    file_rows = sum(r["records"] for s in month_stats for r in s["file_profile"])
    selected = sum(totals.values())
    dropped = totals.get("dst_nonexistent_local_time", 0) + totals.get("outside_declared_month", 0)
    invalid = {k: v for k, v in sorted(totals.items()) if k not in (VALID_STATUS,)}
    lons = [p.lon for pts_ in by_month.values() for p in pts_ if p.lon is not None]
    lats = [p.lat for pts_ in by_month.values() for p in pts_ if p.lat is not None]
    report = QualityReport(
        source_id=SOURCE_ID,
        source_url=config["traffic"]["landing_url"],
        downloaded_at_utc=manifest.downloaded_at_utc,
        period_start=pd.Timestamp(summ["min_utc"]).tz_convert(TIMEZONE).date(),
        period_end=pd.Timestamp(summ["max_utc"]).tz_convert(TIMEZONE).date(),
        license=config["traffic"]["license"],
        input_sha256=checksums,
        raw_rows=selected,
        valid_rows=totals.get(VALID_STATUS, 0),
        duplicate_rows=totals.get("duplicate_slot", 0),
        uniqueness_key=["domain", "entity_id", "timestamp_utc", "feature_name", "source_id"],
        missing_by_column=summ["missing_by_column"],
        invalid_codes=invalid,
        outliers_flagged=totals.get("intensity_implausible", 0),
        date_range_utc=(summ["min_utc"], summ["max_utc"]),
        geographic_coverage={
            "traffic_points_within_max_radius": int(table["traffic_point_id"].nunique()),
            "air_stations_associated": len(stations),
            "air_stations_without_coordinates": no_coordinates,
            "bbox_lon_lat_all_located_points": [min(lons), min(lats), max(lons), max(lats)],
            "geometry_source": config["points"]["landing_url"],
            "geometry_support": "observed_point",
        },
        sampling_frequency=(
            "source: 15-minute records per measurement point; canonical: hourly, timestamp_utc = start of the hour "
            "(UTC), mean of the valid records, at least "
            f"{agg['min_valid_quarters']} of 4"
        ),
        value_units={FEATURE_NAME: UNIT},
        known_limitations=build_limitations(config, summary, dropped, file_rows, selected),
    )
    (out_dir / "quality_report.json").write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    details = {
        "data_version": version,
        "months": months,
        "downloaded_at_utc": manifest.downloaded_at_utc.isoformat(),
        "file_records_all_points": file_rows,
        "selected_records": selected,
        "selected_status": totals,
        "hourly_rows": summ["rows"],
        "by_reason": summ["by_reason"],
        "per_month": month_stats,
        "inventory": inventory,
        "aggregation": agg,
        "association": assoc,
        "sha256": checksums,
        "date_range_utc": [summ["min_utc"].isoformat(), summ["max_utc"].isoformat()],
        "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024),
    }
    (out_dir / "ingest_details.json").write_text(
        json.dumps(details, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if doc_path is not None:
        write_doc(out_dir, config, doc_path, manifests=manifests)
    return {"summary": summary, "details": details, "report": report}


def write_doc(out_dir: Path, config: dict, doc_path: Path, *, manifests: dict | None = None) -> None:
    """Render ``docs/air/madrid_traffic.md`` from the files a previous run wrote into ``out_dir``."""
    details = json.loads((out_dir / "ingest_details.json").read_text(encoding="utf-8"))
    summary = json.loads((out_dir / "association_summary.json").read_text(encoding="utf-8"))
    table = pd.read_parquet(out_dir / "association.parquet")
    last = table[table["month"] == summary["last_month"]]
    summary["median_distance_by_radius_m"] = {
        str(int(r)): float(last.loc[last["distance_m"] <= r, "distance_m"].median())
        for r in config["association"]["study_radii_m"]
    }
    manifests = manifests or {
        SOURCE_ID: (read_manifest(RAW_DIR / SOURCE_ID), []),
        POINTS_ID: (read_manifest(RAW_DIR / POINTS_ID), []),
    }
    data_files = [f for f in manifests[SOURCE_ID][0].files if f.path.endswith(".zip")]
    point_files = [f for f in manifests[POINTS_ID][0].files if f.path.endswith(".csv")]
    counts = [f["points"] for f in summary["files"].values()]
    sizes = {
        "n_traffic": len(data_files),
        "traffic_gb": sum(f.bytes for f in data_files) / 1e9,
        "n_points": len(point_files),
        "points_mb": sum(f.bytes for f in point_files) / 1e6,
        "points_in_files": min(counts),
        "points_in_files_max": max(counts),
    }
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(render_markdown(details, summary, config, sizes), encoding="utf-8")


def build_limitations(config: dict, summary: dict, dropped: int, file_rows: int, selected: int) -> list[str]:
    agg, assoc = config["aggregation"], config["association"]
    return [
        "A measurement point is one road segment (one direction of a street, or a motorway section), not the area around "
        "an air station. The association with a station is by distance only: it is an approximation, not co-location, "
        "and a number correlated with NO2 is not evidence that traffic causes the NO2 concentration.",
        f"Association rule: points within {assoc['radius_m']:.0f} m of the station (kinds {assoc['kinds']}) in the location "
        "file of the same month; a station without such points has null traffic features, nothing is borrowed from farther away.",
        f"Hourly value = mean of the valid 15-minute intensities (veh/h), at least {agg['min_valid_quarters']} of 4; "
        "valid = error flag 'N' and 0 <= intensity <= "
        f"{agg['intensity_max_veh_h']:.0f}. Blank, E and S flags, missing/negative/implausible intensities, duplicated "
        "slots and the first slot after the spring gap are invalid; nothing is filled with 0.",
        "A blank error flag (only M30 points) is treated as invalid: those records are 80-89 % zeros in March and October "
        "2023 against 0.3-1.1 % for flag N. A genuine zero with flag N is kept (night flows) but a stuck-at-zero sensor with flag N "
        "cannot be detected.",
        "Timestamps are Europe/Madrid wall-clock time. The repeated fall-back hour appears once in the files, so both "
        "UTC hours are null (ambiguous_local_hour); local times inside the spring gap are dropped "
        f"({dropped} records in total, including any outside the declared month).",
        f"Records of the selected points: {selected:,} of {file_rows:,} in the files; points outside the study radius are "
        "not aggregated.",
        "Occupancy, load and mean speed are not aggregated (load is 0 for most M30 points, speed exists only for M30).",
        "Point ids that do not appear in the location file of their month cannot be located and are not used.",
    ]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Ingest Madrid traffic into hourly canonical Parquet.")
    parser.add_argument("--months", default=None, help="e.g. 2023-01:2025-12 (default: the config range)")
    parser.add_argument("--skip-download", action="store_true", help="use data/raw as is (must have manifests)")
    parser.add_argument("--download-only", action="store_true", help="only fetch the raw files and manifests")
    parser.add_argument("--association-only", action="store_true", help="stop after the spatial correspondence study")
    parser.add_argument("--doc-only", action="store_true", help="re-render the doc from the files of the last run")
    parser.add_argument("--refresh", action="store_true", help="re-download files even if the checksum matches")
    parser.add_argument(
        "--datasets-root",
        default=os.environ.get("ATLAS_DATASETS_ROOT", DEFAULT_DATASETS_ROOT),
        help="machine dataset root; data/raw/<source> is symlinked into it (default: %(default)s)",
    )
    parser.add_argument("--out-dir", type=Path, default=None, help="default: data/processed/air/traffic")
    parser.add_argument("--no-doc", action="store_true", help=f"do not write {DOC_PATH.relative_to(REPO_ROOT)}")
    parser.add_argument("--min-available-mb", type=float, default=1500.0, help="wait while less RAM than this is free")
    args = parser.parse_args(argv)
    config = load_config()
    months = parse_months(args.months or ":".join(config["default_months"]))
    if args.download_only:
        for source_id, (manifest, fetched) in download(config, months, args.datasets_root, args.refresh).items():
            print(f"{source_id}: {len(manifest.files)} files, fetched now: {len(fetched)}")
        return
    if args.doc_only:
        write_doc(args.out_dir or PROCESSED_DIR / "air" / "traffic", config, DOC_PATH)
        return
    result = run(
        months,
        skip_download=args.skip_download,
        refresh=args.refresh,
        datasets_root=args.datasets_root,
        out_dir=args.out_dir,
        association_only=args.association_only,
        min_available_mb=args.min_available_mb,
        doc_path=None if args.no_doc else DOC_PATH,
    )
    if "details" in result:
        d = result["details"]
        print(f"{d['hourly_rows']} hourly rows, {d['date_range_utc']}, peak RSS {d['peak_rss_mb']} MB", file=sys.stdout)


if __name__ == "__main__":
    main()
