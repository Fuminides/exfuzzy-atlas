"""Profile of the written pickup series (bounded-memory DuckDB over the Parquet output)."""

from __future__ import annotations

from pathlib import Path

import duckdb

from atlas.domains.mobility.aggregate import TIMEZONE

ACTIVE_ZONE_MIN_TRIPS = 100  # "active" zone for the share-of-zeros statistic: at least this many pickups in the period


def summarize_output(observations: Path, zone_names: dict[int, str | None] | None = None, top: int = 10) -> dict:
    """Counts, coverage and temporal pattern of the zone-hour pickup series (no raw data needed)."""
    zone_names = zone_names or {}
    con = duckdb.connect()
    con.execute("SET memory_limit='1GB'")
    con.execute("SET threads=4")
    con.execute("SET TimeZone='UTC'")
    con.execute(f"CREATE VIEW obs AS SELECT * FROM read_parquet('{observations}/**/*.parquet', hive_partitioning=true)")
    cols = [r[0] for r in con.execute("DESCRIBE obs").fetchall() if r[0] not in ("year", "month")]
    null_sql = ", ".join(f"count(*) FILTER (WHERE {c} IS NULL)" for c in cols)
    nulls = con.execute(f"SELECT {null_sql} FROM obs").fetchall()[0]
    rows, lo, hi, zeros, null_rows, total, zones, hours = con.execute(
        "SELECT count(*), min(timestamp_utc), max(timestamp_utc), count(*) FILTER (WHERE value = 0), "
        "count(*) FILTER (WHERE value IS NULL), coalesce(sum(value), 0)::BIGINT, "
        "count(DISTINCT entity_id), count(DISTINCT timestamp_utc) FROM obs"
    ).fetchall()[0]
    con.execute(
        f"""
        CREATE TEMP TABLE local AS
        SELECT CAST(entity_id AS INTEGER) AS zone, value, timestamp_utc,
               timezone('{TIMEZONE}', timestamp_utc) AS lt
        FROM obs
        """
    )
    by_month = [
        {"month": m, "zone_hours": r, "hours": h, "trips": int(t), "zero_zone_hours": z, "null_zone_hours": n}
        for m, r, h, t, z, n in con.execute(
            "SELECT strftime(lt, '%Y-%m'), count(*), count(DISTINCT timestamp_utc), coalesce(sum(value), 0), "
            "count(*) FILTER (WHERE value = 0), count(*) FILTER (WHERE value IS NULL) FROM local GROUP BY 1 ORDER BY 1"
        ).fetchall()
    ]
    per_zone = con.execute(
        "SELECT zone, coalesce(sum(value), 0)::BIGINT AS trips, count(*) FILTER (WHERE value > 0) AS active_hours, "
        "count(*) FILTER (WHERE value = 0) AS zero_hours, count(value) AS valid_hours FROM local GROUP BY zone"
    ).fetchall()

    def zone_row(zone: int, trips: int, active: int, zero: int, valid: int) -> dict:
        return {
            "zone": zone,
            "name": zone_names.get(zone),
            "trips": int(trips),
            "hours_with_pickups": int(active),
            "share_zero_hours": round(zero / valid, 4) if valid else None,
        }

    ranked = sorted(per_zone, key=lambda r: (-r[1], r[0]))
    with_pickups = [r for r in ranked if r[1] > 0]
    active = [r for r in per_zone if r[1] >= ACTIVE_ZONE_MIN_TRIPS]
    active_zero = sum(r[3] for r in active)
    active_valid = sum(r[4] for r in active)
    quantiles = con.execute(
        "SELECT quantile_cont(value, [0.5, 0.9, 0.99, 0.999]), max(value) FROM local WHERE value > 0"
    ).fetchall()[0]
    # citywide totals per UTC hour, only for hours with every zone observed (ambiguous hours are null)
    con.execute(
        "CREATE TEMP TABLE city AS SELECT timestamp_utc, any_value(lt) AS lt, sum(value) AS trips, "
        "count(value) = count(*) AS complete FROM local GROUP BY timestamp_utc"
    )
    hourly = con.execute(
        "SELECT hour(lt) AS h, isodow(lt) >= 6 AS weekend, avg(trips), count(*) FROM city WHERE complete "
        "GROUP BY 1, 2 ORDER BY 2, 1"
    ).fetchall()
    weekday = con.execute(
        "SELECT isodow(d), avg(t), count(*) FROM (SELECT CAST(lt AS DATE) AS d, sum(trips) AS t, count(*) AS n "
        "FROM city WHERE complete GROUP BY 1) WHERE n = 24 GROUP BY 1 ORDER BY 1"
    ).fetchall()
    dst_days = {}
    for day, n_hours in con.execute(
        "SELECT CAST(lt AS DATE), count(DISTINCT timestamp_utc) AS n FROM city GROUP BY 1 HAVING n <> 24"
    ).fetchall():
        dst_days[str(day)] = {
            "utc_hours_in_local_day": n_hours,
            "citywide_trips_by_local_hour": {
                f"{h:02d}": None if t is None else int(t)
                for h, t in con.execute(
                    "SELECT hour(lt), sum(trips) FROM city WHERE CAST(lt AS DATE) = ? GROUP BY 1 ORDER BY 1", [day]
                ).fetchall()
            },
        }
    busiest_hour = con.execute(
        "SELECT timestamp_utc, trips FROM city WHERE complete ORDER BY trips DESC LIMIT 1"
    ).fetchall()[0]
    con.close()
    valid_rows = rows - null_rows
    return {
        "rows": rows,
        "min_utc": lo,
        "max_utc": hi,
        "zones": zones,
        "utc_hours": hours,
        "missing_by_column": dict(zip(cols, map(int, nulls), strict=True)),
        "zero_rows": zeros,
        "null_rows": null_rows,
        "total_pickups": int(total),
        "share_zero_zone_hours": round(zeros / valid_rows, 4),
        "share_zero_zone_hours_active_zones": round(active_zero / active_valid, 4) if active_valid else None,
        "active_zone_min_trips": ACTIVE_ZONE_MIN_TRIPS,
        "active_zones": len(active),
        "zones_without_pickups": sorted(r[0] for r in per_zone if r[1] == 0),
        "by_month": by_month,
        "top_zones": [zone_row(*r) for r in ranked[:top]],
        "bottom_zones_with_pickups": [zone_row(*r) for r in with_pickups[-top:]],
        "count_distribution_nonzero": {
            "p50": quantiles[0][0],
            "p90": quantiles[0][1],
            "p99": quantiles[0][2],
            "p99_9": quantiles[0][3],
            "max": quantiles[1],
        },
        "hourly_profile": [
            {
                "local_hour": h,
                "day_type": "weekend" if weekend else "weekday",
                "mean_citywide_trips": round(m, 1),
                "n_hours": n,
            }
            for h, weekend, m, n in hourly
        ],
        "weekday_profile": [
            {"isodow": d, "mean_daily_citywide_trips": round(m), "n_days": n} for d, m, n in weekday
        ],
        "dst_days": dst_days,
        "busiest_complete_hour": {"timestamp_utc": busiest_hour[0], "trips": int(busiest_hour[1])},
    }
