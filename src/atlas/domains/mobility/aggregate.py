"""Clean one month of TLC Yellow Taxi trips and aggregate pickups per taxi zone and hour (DuckDB, streaming).

Only the pickup time and ``PULocationID`` feed the demand series; dropoff time is read **only** to count and drop
incoherent records (dropoff before pickup, zero or very long durations). No fare or dropoff field is carried forward.

Time handling. TLC timestamps are naive America/New_York wall-clock times (the Parquet columns carry no offset and the
data dictionary does not say otherwise; the November duplicate hour in the data confirms it, see the dataset card).
For each file month we build the hour grid in UTC with ``zoneinfo`` and map every UTC hour to its local wall-clock hour:

* **nonexistent** local hours (spring-forward 02:00-02:59): a taximeter cannot legitimately show them, so such pickups
  are dropped and counted (``pickup_nonexistent_local_hour``). No UTC hour is lost: the UTC grid is complete.
* **ambiguous** local hours (fall-back 01:00-01:59, which happens twice): a naive timestamp cannot say which of the two
  occurrences it belongs to, and the naive hour pools both. Splitting or picking one would invent counts, so those
  pickups are dropped and counted (``pickup_ambiguous_local_hour``) and both UTC hours are written with
  ``value = null``, ``missing_reason = invalid_observation`` and ``validity_flag = ambiguous_local_hour``.

Zero versus missing. Inside the covered period (every UTC hour of every ingested local month) each zone-hour with no
recorded pickup is a genuine ``0`` with ``n_records = 0``; hours outside the covered period have no rows at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pyarrow as pa

SOURCE_ID = "nyc-tlc-yellow"
TIMEZONE = "America/New_York"
FEATURE = "pickups"
UNIT = "trips"
MAX_TRIP_HOURS = 6.0
SPECIAL_IDS = (264, 265)
REQUIRED_COLUMNS = ("tpep_pickup_datetime", "tpep_dropoff_datetime", "PULocationID")

# Exclusive filter reasons in precedence order: each trip is counted under the first one that applies.
REASONS = (
    "null_timestamp",
    "pickup_outside_file_month",
    "dropoff_before_pickup",
    "zero_duration",
    "duration_over_max",
    "pickup_zone_invalid",
    "pickup_zone_unknown_or_outside",  # 264/265, or a valid lookup ID that has no polygon
    "pickup_nonexistent_local_hour",
    "pickup_ambiguous_local_hour",
)


@dataclass
class HourGrid:
    """UTC hours of one local month with their local wall-clock hour, plus the nonexistent local hours."""

    month: str
    local_start: datetime  # naive, inclusive
    local_end: datetime  # naive, exclusive
    utc_hours: list[datetime]  # tz-aware UTC
    local_hours: list[datetime]  # naive, same length
    offsets: list[str]  # "+0000"-style UTC offset of each local hour
    ambiguous: list[bool]
    nonexistent_local_hours: list[datetime] = field(default_factory=list)

    @property
    def ambiguous_local_hours(self) -> list[datetime]:
        return sorted({lh for lh, amb in zip(self.local_hours, self.ambiguous, strict=True) if amb})


def month_bounds(month: str) -> tuple[datetime, datetime]:
    """``'2025-03'`` -> naive local ``[2025-03-01 00:00, 2025-04-01 00:00)``."""
    year, mon = int(month[:4]), int(month[5:7])
    start = datetime(year, mon, 1)
    return start, datetime(year + mon // 12, mon % 12 + 1, 1)


def build_hour_grid(month: str, tz_name: str = TIMEZONE) -> HourGrid:
    """Localize a calendar month: the complete UTC hour grid and the local hours that are ambiguous or nonexistent."""
    tz = ZoneInfo(tz_name)
    start, end = month_bounds(month)
    utc_start = start.replace(tzinfo=tz).astimezone(timezone.utc)  # midnight is never in a DST transition
    utc_end = end.replace(tzinfo=tz).astimezone(timezone.utc)
    utc_hours, local_hours, offsets = [], [], []
    moment = utc_start
    while moment < utc_end:
        local = moment.astimezone(tz)
        utc_hours.append(moment)
        local_hours.append(local.replace(tzinfo=None))
        offsets.append(local.strftime("%z"))
        moment += timedelta(hours=1)
    counts: dict[datetime, int] = {}
    for lh in local_hours:
        counts[lh] = counts.get(lh, 0) + 1
    present = set(local_hours)
    nonexistent, naive = [], start
    while naive < end:
        if naive not in present:
            nonexistent.append(naive)
        naive += timedelta(hours=1)
    return HourGrid(
        month, start, end, utc_hours, local_hours, offsets, [counts[lh] > 1 for lh in local_hours], nonexistent
    )


def covered_range_utc(months: list[str], tz_name: str = TIMEZONE) -> tuple[datetime, datetime]:
    """UTC ``[start, end)`` of the ingested months (first local midnight to the last month's end)."""
    tz = ZoneInfo(tz_name)
    start = month_bounds(min(months))[0].replace(tzinfo=tz).astimezone(timezone.utc)
    end = month_bounds(max(months))[1].replace(tzinfo=tz).astimezone(timezone.utc)
    return start, end


def connect(memory_limit: str = "1500MB", threads: int = 4, temp_dir: Path | None = None) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(f"SET memory_limit='{memory_limit}'")
    con.execute(f"SET threads={threads}")
    con.execute("SET TimeZone='UTC'")
    if temp_dir is not None:
        temp_dir.mkdir(parents=True, exist_ok=True)
        con.execute(f"SET temp_directory='{temp_dir}'")
    return con


def inventory_schema(con: duckdb.DuckDBPyConnection, parquet: Path) -> dict[str, str]:
    """``column -> DuckDB type`` of one Parquet file; fails when a column this pipeline needs is missing."""
    rows = con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(parquet)]).fetchall()
    schema = {r[0]: r[1] for r in rows}
    absent = [c for c in REQUIRED_COLUMNS if c not in schema]
    if absent:
        raise ValueError(f"{parquet.name} lacks required columns {absent}")
    return schema


def _hours_table(grid: HourGrid) -> pa.Table:
    return pa.table(
        {
            "hour_utc": pa.array([h.replace(tzinfo=None) for h in grid.utc_hours], pa.timestamp("us")),
            "local_hour": pa.array(grid.local_hours, pa.timestamp("us")),
            "utc_offset": pa.array(grid.offsets, pa.string()),
            "ambiguous": pa.array(grid.ambiguous, pa.bool_()),
        }
    )


@dataclass
class MonthResult:
    month: str
    raw_rows: int
    filtered: dict[str, int]  # exclusive, sums with `kept` to raw_rows
    flags_independent: dict[str, int]  # each reason counted on its own (a trip can have several)
    kept_rows: int  # trips counted into the pickups series
    duplicate_rows: int | None
    out_of_month_inside_covered_period: int
    output_rows: int
    zero_rows: int
    null_rows: int
    special_zone_counts: dict[int, int]  # LocationID -> trips filtered as unknown/outside/no polygon
    zero_duration_by_vendor: dict[int | None, int]
    ambiguous_trips_by_hour: dict[str, int]
    nonexistent_trips_by_hour: dict[str, int]
    schema: dict[str, str]
    min_pickup: str | None
    max_pickup: str | None
    seconds: float = 0.0


def aggregate_month(
    con: duckdb.DuckDBPyConnection,
    parquet: Path,
    month: str,
    zone_ids: list[int],
    lookup_ids: list[int],
    out_file: Path,
    *,
    data_version: str,
    covered_local: tuple[datetime, datetime] | None = None,
    max_trip_hours: float = MAX_TRIP_HOURS,
    count_duplicates: bool = True,
) -> MonthResult:
    """Classify every trip of one file, then write the dense zone x UTC-hour table of that month to ``out_file``.

    Args:
        zone_ids: zones that get a row for every hour (the polygons of the official shapefile).
        lookup_ids: every LocationID of the TLC lookup; a pickup outside this set is invalid, 264/265 are
            valid-but-unknown/outside and are counted apart.
        covered_local: naive local ``[start, end)`` of all ingested months, only used to tell whether a trip that is
            outside this file's month still falls in the covered period (informational).
        count_duplicates: also count exact duplicate trip rows (they are reported, not removed).
    """
    started = datetime.now()
    schema = inventory_schema(con, parquet)
    grid = build_hour_grid(month)
    cov_start, cov_end = covered_local or (grid.local_start, grid.local_end)
    con.register("grid_hours", _hours_table(grid))
    con.register("lookup_zones", pa.table({"zone_id": pa.array(lookup_ids, pa.int32())}))
    con.register("amb_hours", pa.table({"h": pa.array(grid.ambiguous_local_hours, pa.timestamp("us"))}))
    con.register("gap_hours", pa.table({"h": pa.array(grid.nonexistent_local_hours, pa.timestamp("us"))}))
    con.register("out_zones", pa.table({"zone_id": pa.array(sorted(zone_ids), pa.int32())}))

    vendor = "TRY_CAST(VendorID AS INTEGER)" if "VendorID" in schema else "CAST(NULL AS INTEGER)"
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE flagged AS
        SELECT
            tpep_pickup_datetime AS pu_ts,
            {vendor} AS vendor,
            TRY_CAST(PULocationID AS INTEGER) AS zone_id,
            (tpep_pickup_datetime IS NULL OR tpep_dropoff_datetime IS NULL) AS f_null_timestamp,
            (tpep_pickup_datetime < ? OR tpep_pickup_datetime >= ?) AS f_pickup_outside_file_month,
            (tpep_dropoff_datetime < tpep_pickup_datetime) AS f_dropoff_before_pickup,
            (tpep_dropoff_datetime = tpep_pickup_datetime) AS f_zero_duration,
            (date_diff('second', tpep_pickup_datetime, tpep_dropoff_datetime) > ? * 3600) AS f_duration_over_max,
            (TRY_CAST(PULocationID AS INTEGER) IS NULL
             OR TRY_CAST(PULocationID AS INTEGER) NOT IN (SELECT zone_id FROM lookup_zones)) AS f_pickup_zone_invalid,
            (TRY_CAST(PULocationID AS INTEGER) IN (SELECT zone_id FROM lookup_zones)
             AND (TRY_CAST(PULocationID AS INTEGER) IN (264, 265)
                  OR TRY_CAST(PULocationID AS INTEGER) NOT IN (SELECT zone_id FROM out_zones))
            ) AS f_pickup_zone_unknown_or_outside,
            (date_trunc('hour', tpep_pickup_datetime) IN (SELECT h FROM gap_hours)) AS f_pickup_nonexistent_local_hour,
            (date_trunc('hour', tpep_pickup_datetime) IN (SELECT h FROM amb_hours)) AS f_pickup_ambiguous_local_hour
        FROM read_parquet(?)
        """,
        [grid.local_start, grid.local_end, max_trip_hours, str(parquet)],
    )
    flag_cols = [f"f_{r}" for r in REASONS]
    # null comparisons yield NULL; treat them as "flag not raised" so the CASE below stays well defined
    case = " ".join(f"WHEN coalesce({c}, false) THEN '{r}'" for c, r in zip(flag_cols, REASONS, strict=True))
    con.execute(
        f"CREATE OR REPLACE TEMP TABLE classified AS "
        f"SELECT pu_ts, zone_id, vendor, CASE {case} ELSE 'kept' END AS reason FROM flagged"
    )

    raw_rows = con.execute("SELECT count(*) FROM classified").fetchall()[0][0]
    by_reason = dict(con.execute("SELECT reason, count(*) FROM classified GROUP BY reason").fetchall())
    independent = con.execute(
        "SELECT " + ", ".join(f"count(*) FILTER (WHERE coalesce({c}, false))" for c in flag_cols) + " FROM flagged"
    ).fetchall()[0]
    outside_covered = con.execute(
        "SELECT count(*) FROM flagged WHERE coalesce(f_pickup_outside_file_month, false) "
        "AND pu_ts >= ? AND pu_ts < ?",
        [cov_start, cov_end],
    ).fetchall()[0][0]
    special_zones = dict(
        con.execute(
            "SELECT zone_id, count(*) FROM classified WHERE reason = 'pickup_zone_unknown_or_outside' GROUP BY 1"
        ).fetchall()
    )
    zero_by_vendor = dict(
        con.execute(
            "SELECT vendor, count(*) FROM classified WHERE reason = 'zero_duration' GROUP BY 1 ORDER BY 1"
        ).fetchall()
    )
    first, last = con.execute("SELECT min(pu_ts), max(pu_ts) FROM flagged").fetchall()[0]
    hourly = {
        reason: {
            str(h): n
            for h, n in con.execute(
                "SELECT date_trunc('hour', pu_ts), count(*) FROM classified WHERE reason = ? GROUP BY 1 ORDER BY 1",
                [reason],
            ).fetchall()
        }
        for reason in ("pickup_ambiguous_local_hour", "pickup_nonexistent_local_hour")
    }
    duplicates = None
    if count_duplicates:
        duplicates = con.execute(
            "SELECT (SELECT count(*) FROM read_parquet(?)) "
            "- (SELECT count(*) FROM (SELECT DISTINCT * FROM read_parquet(?)))",
            [str(parquet), str(parquet)],
        ).fetchall()[0][0]

    out_file.parent.mkdir(parents=True, exist_ok=True)
    if out_file.exists():
        out_file.unlink()
    con.execute(
        f"""
        COPY (
            WITH counts AS (
                SELECT g.hour_utc, c.zone_id, count(*) AS n
                FROM classified c JOIN grid_hours g ON date_trunc('hour', c.pu_ts) = g.local_hour AND NOT g.ambiguous
                WHERE c.reason = 'kept' AND c.zone_id IN (SELECT zone_id FROM out_zones)
                GROUP BY 1, 2
            )
            SELECT
                'mobility' AS domain,
                CAST(z.zone_id AS VARCHAR) AS entity_id,
                CAST(g.hour_utc AS TIMESTAMP) AT TIME ZONE 'UTC' AS timestamp_utc,
                strftime(g.local_hour, '%Y-%m-%d %H:%M') || g.utc_offset AS source_timestamp_local,
                '{TIMEZONE}' AS timezone,
                '{FEATURE}' AS feature_name,
                CASE WHEN g.ambiguous THEN NULL ELSE CAST(coalesce(k.n, 0) AS DOUBLE) END AS value,
                '{UNIT}' AS unit,
                CASE WHEN g.ambiguous THEN 'ambiguous_local_hour' END AS validity_flag,
                CASE WHEN g.ambiguous THEN 'invalid_observation' END AS missing_reason,
                CAST(NULL AS VARCHAR) AS censoring,
                '{SOURCE_ID}' AS source_id,
                '{data_version}' AS data_version,
                CAST(g.hour_utc AS TIMESTAMP) AT TIME ZONE 'UTC' AS aggregation_window_start_utc,
                (CAST(g.hour_utc AS TIMESTAMP) + INTERVAL 1 HOUR) AT TIME ZONE 'UTC' AS aggregation_window_end_utc,
                CASE WHEN g.ambiguous THEN NULL ELSE CAST(coalesce(k.n, 0) AS BIGINT) END AS n_records
            FROM out_zones z CROSS JOIN grid_hours g
            LEFT JOIN counts k ON k.zone_id = z.zone_id AND k.hour_utc = g.hour_utc
            ORDER BY z.zone_id, g.hour_utc
        ) TO '{out_file}' (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    output_rows, zeros, nulls = con.execute(
        "SELECT count(*), count(*) FILTER (WHERE value = 0), count(*) FILTER (WHERE value IS NULL) "
        "FROM read_parquet(?)",
        [str(out_file)],
    ).fetchall()[0]
    for name in ("grid_hours", "lookup_zones", "amb_hours", "gap_hours", "out_zones"):
        con.unregister(name)
    con.execute("DROP TABLE flagged")
    con.execute("DROP TABLE classified")

    filtered = {r: int(by_reason.get(r, 0)) for r in REASONS}
    return MonthResult(
        month=month,
        raw_rows=int(raw_rows),
        filtered=filtered,
        flags_independent={r: int(n) for r, n in zip(REASONS, independent, strict=True)},
        kept_rows=int(by_reason.get("kept", 0)),
        duplicate_rows=None if duplicates is None else int(duplicates),
        out_of_month_inside_covered_period=int(outside_covered),
        output_rows=int(output_rows),
        zero_rows=int(zeros),
        null_rows=int(nulls),
        special_zone_counts={int(k): int(v) for k, v in special_zones.items()},
        zero_duration_by_vendor={None if k is None else int(k): int(v) for k, v in zero_by_vendor.items()},
        ambiguous_trips_by_hour=hourly["pickup_ambiguous_local_hour"],
        nonexistent_trips_by_hour=hourly["pickup_nonexistent_local_hour"],
        schema=schema,
        min_pickup=None if first is None else str(first),
        max_pickup=None if last is None else str(last),
        seconds=(datetime.now() - started).total_seconds(),
    )
