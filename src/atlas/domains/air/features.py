"""Feature/target table for the Madrid NO2 t+6h task (AT-011, consumed by A4 in AT-041).

    PYTHONPATH=src python -m atlas.domains.air.features

One row per (air station, issue hour ``t``) on a regular **UTC** hourly grid, so ``t + 6 h`` is always exactly six
elapsed hours (daylight saving only changes the local calendar features). Time conventions:

* An observation row's ``timestamp_utc`` is the START of its hour (key ``s``); the value covers ``[s, s+1h)`` and is
  taken as available at ``s + 1h``. At issue time ``t`` the latest complete hour is therefore the one with key
  ``t - 1h``. Every input feature reads a key ``<= t - 1h``; the real publication delay of the portal is not measured
  and no real-time operation is claimed.
* ``target`` is the NO2 hour with key ``t + 6h`` and ``valid_at_utc = t + 6h``.
* Every join is an exact equality on ``(entity, timestamp)`` against tables with a unique key, never a row-offset
  window, so a missing hour yields NULL instead of shifting a neighbour into its place.
* Missing or invalid inputs are NULL, never 0. Local days listed as anomalous by the ingestion reports are nulled and
  rows whose input window touches them carry ``excluded_day_window = true``.
"""

# ruff: noqa: E501  (prose templates and SQL)

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd

from atlas.domains.air.association import ASSOCIATION_COLUMNS, Point, build_association
from atlas.domains.air.meteo import PLAUSIBLE_RANGE
from atlas.paths import PROCESSED_DIR, REPO_ROOT

CONFIG_PATH = REPO_ROOT / "configs" / "air" / "madrid_no2_h6.json"
DOC_PATH = REPO_ROOT / "docs" / "air" / "madrid_no2_h6_coverage.md"
MEMORY_LIMIT = "2GB"

UNITS = {
    "no2": "ug/m3",
    "wind_speed": "m/s",
    "temperature": "degC",
    "relative_humidity": "%",
    "pressure": "mbar",
    "valid_hour_local": "h",
    "valid_weekday": "day",
    "valid_is_weekend": "0/1",
    "valid_hour_sin": "1",
    "valid_hour_cos": "1",
}
CALENDAR_SQL = {
    "valid_hour_local": "hour(timezone('{tz}', valid_at_utc))",
    "valid_weekday": "isodow(timezone('{tz}', valid_at_utc)) - 1",
    "valid_is_weekend": "CASE WHEN isodow(timezone('{tz}', valid_at_utc)) >= 6 THEN 1 ELSE 0 END",
    "valid_hour_sin": "sin(2 * pi() * hour(timezone('{tz}', valid_at_utc)) / 24)",
    "valid_hour_cos": "cos(2 * pi() * hour(timezone('{tz}', valid_at_utc)) / 24)",
}
CALENDAR_TEXT = {
    "valid_hour_local": (
        "Local (Europe/Madrid) hour of day of the target hour, integer 0-23 (a 23/25-hour day repeats or skips one). "
        "Raw hour kept for readable fuzzy terms; it is not cyclic, so 23 and 0 are far apart in a partition: "
        "use valid_hour_sin/valid_hour_cos if that matters more than readability."
    ),
    "valid_weekday": "Local weekday of the target hour, 0 = Monday ... 6 = Sunday (7 distinct values, not auto-categorical).",
    "valid_is_weekend": (
        "1 if the local target day is Saturday or Sunday. Public holidays are NOT modelled. A 0/1 flag gives a "
        "degenerate quantile partition in ex_fuzzy (docs/ml/exfuzzy_api_notes.md), so it is not recommended."
    ),
    "valid_hour_sin": "sin(2 pi h / 24) of valid_hour_local; cyclic encoding, hard to read as a linguistic term.",
    "valid_hour_cos": "cos(2 pi h / 24) of valid_hour_local; cyclic encoding, hard to read as a linguistic term.",
}


def load_config(path: Path | None = None) -> dict:
    """The task config (default: Madrid). Another territory passes its own ``configs/air/<task>.json`` (AT-070: Germany)."""
    return json.loads((path or CONFIG_PATH).read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------------- pure helpers


def excluded_utc_windows(local_dates: list[str], tz: str = "Europe/Madrid") -> list[tuple[datetime, datetime]]:
    """UTC ``[start, end)`` of each excluded local calendar day (23-25 h long on DST days)."""
    zone = ZoneInfo(tz)
    out = []
    for text in sorted(set(local_dates)):
        day = date.fromisoformat(text)
        start = datetime(day.year, day.month, day.day, tzinfo=zone)
        end = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=zone)
        out.append((start.astimezone(ZoneInfo("UTC")), end.astimezone(ZoneInfo("UTC"))))
    return out


def feature_specs(config: dict) -> list[dict]:
    """The feature card entries, derived from the config so the card and the SQL cannot diverge."""
    horizon = config["horizon_hours"]
    max_m = config["association"]["max_distance_m"]
    units = {**UNITS, **config.get("units", {})}
    tz = config["timezone"]
    no2_source, meteo_source = config["no2_source"]["source_id"], config["meteo_source"]["source_id"]
    specs = []
    for feat in config["features"]:
        name, kind = feat["name"], feat["kind"]
        entry = {"name": name, "kind": kind, "recommended": feat["recommended"]}
        if kind == "no2":
            k = -feat["key_offset_hours"]
            hour_end = "t" if k == 1 else f"t-{k - 1}h"
            entry |= {
                "unit": units["no2"],
                "source": f"{no2_source} / no2 (observations, own station)",
                "source_key_offset_hours": feat["key_offset_hours"],
                "definition": (
                    f"NO2 of the hour with key issued_at_utc - {k}h, i.e. the hour [t-{k}h, {hour_end})"
                    + (" (latest complete hour)" if k == 1 else "")
                    + ". NULL if that hour has no valid value."
                    + (f" {feat['note']}" if feat.get("note") else "")
                ),
                "available_at": f"key + 1h = issued_at_utc - {k - 1}h <= issued_at_utc",
                "spatial_association": "own air station (co-located by construction)",
            }
        elif kind == "meteo":
            entry |= {
                "unit": units[feat["variable"]],
                "source": f"{meteo_source} / {feat['variable']} (hourly)",
                "source_key_offset_hours": feat["key_offset_hours"],
                "definition": (
                    f"Hourly {feat['variable']} of the hour with key issued_at_utc - 1h (latest complete hour) from "
                    "the primary associated meteorological station, or the next ranked one when the better one has "
                    "no valid value that hour. NULL if none does."
                ),
                "available_at": "key + 1h = issued_at_utc",
                "spatial_association": (
                    f"nearest meteorological stations that measure it within {max_m:.0f} m (up to "
                    f"{config['association']['max_candidates']} ranked); distance and station per air station in "
                    "association.parquet. A point measurement elsewhere in the city, not co-located unless "
                    "same_station_code is true."
                ),
            }
        else:
            entry |= {
                "unit": units[name],
                "source": f"calendar of valid_at_utc in {tz}",
                "source_key_offset_hours": horizon,
                "definition": CALENDAR_TEXT[name].replace("Europe/Madrid", tz),
                "available_at": "known in advance (calendar)",
                "spatial_association": "none",
            }
        specs.append(entry)
    return specs


def _rank_join_sql(config: dict) -> str:
    return "\n".join(
        f"""chosen_{v} AS (
    SELECT a.air_entity_id AS entity_id, m.ts, arg_min(m.value, a.rank) AS value, min(a.rank) AS rnk
    FROM assoc a JOIN meteo_obs m ON m.entity_id = a.meteo_entity_id AND m.feature_name = a.variable
    WHERE a.variable = '{v}' GROUP BY 1, 2),"""
        for v in config["association"]["variables"]
    )


def build_table_sql(
    config: dict,
    excluded_dates: list[str],
    windows: list[tuple[datetime, datetime]],
    t_from: str | None = None,
    t_to: str | None = None,
) -> str:
    """The SELECT that builds the table (grid x stations, exact-timestamp left joins). Pure string, testable.

    ``t_from``/``t_to`` (issue hours, inclusive) restrict the grid to a chunk of it; the observation CTEs are then
    bounded to the hours that chunk can read (``t - 26 h`` ... ``t + horizon + 1 h``), so a chunk costs memory in proportion
    to its size. The rows of a chunk are exactly the rows of the same hours in the full table.
    """
    tz, horizon = config["timezone"], config["horizon_hours"]
    start, end = t_from or config["grid"]["start_utc"], t_to or config["grid"]["end_utc"]
    bound = (
        (lambda col: f"AND {col} >= TIMESTAMPTZ '{start}' - INTERVAL 26 HOUR AND {col} <= TIMESTAMPTZ '{end}' + INTERVAL {horizon + 1} HOUR")
        if t_from or t_to
        else (lambda col: "")
    )

    def skip(col: str) -> str:
        if not excluded_dates:
            return ""
        dates = ", ".join(f"DATE '{d}'" for d in sorted(set(excluded_dates)))
        return f"AND CAST(timezone('{tz}', {col}) AS DATE) NOT IN ({dates})"

    ranges = {**PLAUSIBLE_RANGE, **{k: tuple(v) for k, v in config.get("plausible_range", {}).items()}}
    plaus = " AND ".join(
        f"(feature_name <> '{name}' OR value BETWEEN {lo} AND {hi})" for name, (lo, hi) in ranges.items()
    )
    joins, columns, meteo_vars = [], [], []
    for i, feat in enumerate(config["features"]):
        name, kind = feat["name"], feat["kind"]
        if kind == "no2":
            joins.append(
                f"LEFT JOIN no2 f{i} ON f{i}.entity_id = g.entity_id "
                f"AND f{i}.ts = g.t + INTERVAL ({feat['key_offset_hours']}) HOUR"
            )
            columns.append(f"f{i}.value AS {name}")
        elif kind == "meteo":
            v = feat["variable"]
            joins.append(
                f"LEFT JOIN chosen_{v} f{i} ON f{i}.entity_id = g.entity_id "
                f"AND f{i}.ts = g.t + INTERVAL ({feat['key_offset_hours']}) HOUR"
            )
            columns.append(f"f{i}.value AS {name}")
            meteo_vars.append(f"coalesce((f{i}.rnk > 1)::INTEGER, 0)")
        else:
            columns.append(f"({CALENDAR_SQL[name].format(tz=tz)}) AS {name}")
    fallback = " + ".join(meteo_vars) if meteo_vars else "0"
    overlap = (
        " OR ".join(
            f"(g.t - INTERVAL 25 HOUR < TIMESTAMPTZ '{b.isoformat()}' AND g.t + INTERVAL {horizon + 1} HOUR > TIMESTAMPTZ '{a.isoformat()}')"
            for a, b in windows
        )
        or "false"
    )
    required = [f["name"] for f in config["features"] if f["recommended"]]
    complete = " AND ".join([*(f"{n} IS NOT NULL" for n in required), "target IS NOT NULL", "NOT excluded_day_window"])
    return f"""
WITH grid AS (
    SELECT e.entity_id, t FROM entities e,
    generate_series(TIMESTAMPTZ '{start}', TIMESTAMPTZ '{end}', INTERVAL 1 HOUR) AS s(t)),
no2 AS (
    SELECT entity_id, timestamp_utc AS ts, value FROM air_obs
    WHERE feature_name = 'no2' AND value IS NOT NULL {skip("timestamp_utc")} {bound("timestamp_utc")}),
meteo_obs AS (
    SELECT entity_id, feature_name, timestamp_utc AS ts, value FROM meteo_raw
    WHERE value IS NOT NULL AND {plaus} {skip("timestamp_utc")} {bound("timestamp_utc")}),
{_rank_join_sql(config)}
base AS (
    SELECT g.entity_id, g.t AS issued_at_utc, g.t + INTERVAL {horizon} HOUR AS valid_at_utc,
        tgt.value AS target,
        {", ".join(columns)},
        {fallback} AS meteo_fallback_n,
        ({overlap}) AS excluded_day_window
    FROM grid g
    LEFT JOIN no2 tgt ON tgt.entity_id = g.entity_id AND tgt.ts = g.t + INTERVAL {horizon} HOUR
    {" ".join(joins)})
SELECT *, ({complete}) AS complete,
    year(issued_at_utc) AS year, month(issued_at_utc) AS month
FROM base ORDER BY entity_id, issued_at_utc"""


# ------------------------------------------------------------------------------------- pipeline


def _connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(f"SET memory_limit='{MEMORY_LIMIT}'")
    con.execute("SET threads=4")
    con.execute("SET TimeZone='UTC'")
    return con


def _read_points(geojson: Path) -> list[Point]:
    data = json.loads(geojson.read_text(encoding="utf-8"))
    return [
        Point(f["id"], f["geometry"]["coordinates"][0], f["geometry"]["coordinates"][1], f["properties"].get("name"))
        for f in data["features"]
        if f["geometry"] is not None
    ]


def month_chunks(config: dict) -> list[tuple[int, int, str, str]]:
    """UTC months of the issue-hour grid: ``(year, month, first issue hour, last issue hour)`` (both inclusive)."""
    first, last = pd.Timestamp(config["grid"]["start_utc"]), pd.Timestamp(config["grid"]["end_utc"])
    out, cursor = [], pd.Timestamp(year=first.year, month=first.month, day=1, tz="UTC")
    while cursor <= last:
        nxt = cursor + pd.offsets.MonthBegin(1)
        out.append((cursor.year, cursor.month, max(cursor, first).isoformat(), min(nxt - pd.Timedelta(hours=1), last).isoformat()))
        cursor = nxt
    return out


def write_table_by_month(con, config, excluded, windows, table_dir: Path) -> None:
    """Write ``table/year=Y/month=M/data_0.parquet`` one UTC month at a time (bounded memory for a large network).

    Same rows and layout as the single ``COPY ... PARTITION_BY (year, month)``: the partition is the UTC month of
    ``issued_at_utc`` either way, and a chunk reads only the hours it needs.
    """
    for year, month, t_from, t_to in month_chunks(config):
        sql = build_table_sql(config, excluded, windows, t_from, t_to)
        target = table_dir / f"year={year}" / f"month={month}"
        target.mkdir(parents=True)
        con.execute(
            f"COPY (SELECT * EXCLUDE (year, month) FROM ({sql})) TO '{target / 'data_0.parquet'}' (FORMAT PARQUET, COMPRESSION ZSTD)"
        )


def run(
    *,
    processed: Path | None = None,
    out_dir: Path | None = None,
    doc_path: Path | None = DOC_PATH,
    extra_excluded: list[str] | None = None,
    config: dict | None = None,
) -> dict:
    config = config or load_config()
    processed = processed or PROCESSED_DIR / "air"
    out_dir = out_dir or processed / "features" / config["task_id"]
    meteo_dir = processed / "meteo"
    air_obs, meteo_obs = processed / "observations", meteo_dir / "observations"
    for path in (air_obs, meteo_obs, processed / "stations.geojson", meteo_dir / "stations.geojson"):
        if not path.exists():
            raise SystemExit(f"{path} is missing: run atlas.domains.air.ingest and atlas.domains.air.meteo first")

    air_details = json.loads((processed / "ingest_details.json").read_text(encoding="utf-8"))
    meteo_details = json.loads((meteo_dir / "ingest_details.json").read_text(encoding="utf-8"))
    excluded = sorted({*air_details["dst_anomalies"], *meteo_details["dst_anomalies"], *(extra_excluded or [])})
    windows = excluded_utc_windows(excluded, config["timezone"])

    con = _connect()
    con.execute(f"CREATE VIEW air_obs AS SELECT * FROM read_parquet('{air_obs}/**/*.parquet', hive_partitioning=true)")
    con.execute(
        f"CREATE VIEW meteo_raw AS SELECT * FROM read_parquet('{meteo_obs}/**/*.parquet', hive_partitioning=true)"
    )
    # Stations of the table: every station with at least one valid NO2 value (24; geometry from the official layer).
    entities = [
        r[0]
        for r in con.execute(
            "SELECT DISTINCT entity_id FROM air_obs WHERE feature_name='no2' AND value IS NOT NULL ORDER BY 1"
        ).fetchall()
    ]
    air_points = {p.entity_id: p for p in _read_points(processed / "stations.geojson")}
    missing_geometry = [e for e in entities if e not in air_points]
    con.execute("CREATE TABLE entities AS SELECT unnest(?) AS entity_id", [entities])

    variables = config["association"]["variables"]
    valid_hours = {
        (r[0], r[1]): int(r[2])
        for r in con.execute(
            "SELECT entity_id, feature_name, count(*) FROM meteo_raw WHERE value IS NOT NULL GROUP BY ALL"
        ).fetchall()
    }
    association = build_association(
        [air_points[e] for e in entities if e in air_points],
        _read_points(meteo_dir / "stations.geojson"),
        valid_hours,
        variables,
        max_distance_m=config["association"]["max_distance_m"],
        max_candidates=config["association"]["max_candidates"],
    )
    assoc_frame = pd.DataFrame(association, columns=list(ASSOCIATION_COLUMNS))
    con.register("assoc", assoc_frame)

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    table_dir = out_dir / "table"
    if config.get("chunk_by_month"):
        write_table_by_month(con, config, excluded, windows, table_dir)
    else:
        sql = build_table_sql(config, excluded, windows)
        con.execute(f"COPY ({sql}) TO '{table_dir}' (FORMAT PARQUET, COMPRESSION ZSTD, PARTITION_BY (year, month))")

    n_hours = int(
        con.execute(
            f"SELECT count(*) FROM generate_series(TIMESTAMPTZ '{config['grid']['start_utc']}', "
            f"TIMESTAMPTZ '{config['grid']['end_utc']}', INTERVAL 1 HOUR)"
        ).fetchone()[0]
    )
    con.execute(f"CREATE VIEW tbl AS SELECT * FROM read_parquet('{table_dir}/**/*.parquet', hive_partitioning=true)")
    n_rows = int(con.execute("SELECT count(*) FROM tbl").fetchone()[0])
    if n_rows != len(entities) * n_hours:
        raise SystemExit(f"row count {n_rows} != stations x hours {len(entities) * n_hours}: a join multiplied rows")
    n_keys = int(con.execute("SELECT count(DISTINCT (entity_id, issued_at_utc)) FROM tbl").fetchone()[0])
    if n_keys != n_rows:
        raise SystemExit("duplicate (entity_id, issued_at_utc) keys in the feature table")

    specs = feature_specs(config)
    summary = summarize(con, config, specs)
    assoc_frame.to_parquet(out_dir / "association.parquet", index=False)
    (out_dir / "association.json").write_text(
        json.dumps(association_summary(assoc_frame, entities, variables, config), indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    card = {
        "task_id": config["task_id"],
        "data_version": config["data_version"],
        "horizon_hours": config["horizon_hours"],
        "grid": config["grid"],
        "time_convention": (
            "issued_at_utc = t. An hour with key s (timestamp_utc = start of the hour) is available at s+1h, so inputs "
            f"read keys <= t-1h. target = NO2 of the hour with key t+{config['horizon_hours']}h; valid_at_utc = t+{config['horizon_hours']}h (UTC arithmetic)."
        ),
        "key": ["entity_id", "issued_at_utc"],
        "target": {
            "name": "target",
            "unit": "ug/m3",
            "source": f"{config['no2_source']['source_id']} / no2",
            "key_offset_hours": config["horizon_hours"],
        },
        "features": specs,
        "recommended_features": [s["name"] for s in specs if s["recommended"]],
        "other_columns": {
            "valid_at_utc": f"issued_at_utc + {config['horizon_hours']}h",
            "meteo_fallback_n": "how many of the meteorological values come from a station ranked below the primary",
            "excluded_day_window": "true if the input/target window touches a local day listed in excluded_local_dates",
            "complete": "all recommended features and the target are non-null and excluded_day_window is false",
            "year, month": "hive partition of issued_at_utc (UTC): the chronological split unit",
        },
        "excluded_local_dates": excluded,
        "inputs": {
            "air_data_version": air_details["data_version"],
            "meteo_data_version": meteo_details["data_version"],
            "air_sha256": air_details["sha256"],
            "meteo_sha256": meteo_details["sha256"],
        },
        "stations": entities,
        "stations_without_official_geometry": missing_geometry,
        "rows": {"total": n_rows, "stations": len(entities), "hours": n_hours},
    }
    (out_dir / "feature_card.json").write_text(json.dumps(card, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "feature_card.md").write_text(render_card(card), encoding="utf-8")
    (out_dir / "coverage.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    if doc_path is not None:
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(
            render_coverage_doc(card, summary, association_summary(assoc_frame, entities, variables, config)),
            encoding="utf-8",
        )
    con.close()
    return {"card": card, "summary": summary}


def summarize(con: duckdb.DuckDBPyConnection, config: dict, specs: list[dict]) -> dict:
    """Row counts and completeness per station/year and the per-feature non-null fractions per year."""
    per_station = con.execute(
        "SELECT entity_id, year, count(*) AS rows, count(*) FILTER (WHERE complete) AS complete, "
        "count(*) FILTER (WHERE target IS NOT NULL) AS with_target FROM tbl GROUP BY ALL ORDER BY ALL"
    ).fetchall()
    names = [s["name"] for s in specs if s["kind"] != "calendar"] + ["target"]
    per_feature = con.execute(
        "SELECT year, count(*), " + ", ".join(f"count({n})" for n in names) + " FROM tbl GROUP BY year ORDER BY year"
    ).fetchall()
    per_year = con.execute(
        "SELECT year, count(*), count(*) FILTER (WHERE complete), count(*) FILTER (WHERE excluded_day_window) "
        "FROM tbl GROUP BY year ORDER BY year"
    ).fetchall()
    fallback = con.execute("SELECT meteo_fallback_n, count(*) FROM tbl GROUP BY ALL ORDER BY ALL").fetchall()
    return {
        "per_station_year": [
            {"entity_id": e, "year": int(y), "rows": int(r), "complete": int(c), "with_target": int(t)}
            for e, y, r, c, t in per_station
        ],
        "per_year": [
            {"year": int(y), "rows": int(r), "complete": int(c), "excluded_day_window": int(x)}
            for y, r, c, x in per_year
        ],
        "feature_non_null_fraction_per_year": {
            str(int(row[0])): {n: round(row[2 + i] / row[1], 4) for i, n in enumerate(names)} for row in per_feature
        },
        "meteo_fallback_n_rows": {str(int(k)): int(v) for k, v in fallback},
    }


def association_summary(frame: pd.DataFrame, entities: list[str], variables: list[str], config: dict) -> dict:
    """Primary station and distance per (air station, variable); stations with no candidate are listed as null."""
    primary = {}
    for e in entities:
        primary[e] = {}
        for v in variables:
            rows = frame[(frame["air_entity_id"] == e) & (frame["variable"] == v)].sort_values("rank")
            primary[e][v] = (
                None
                if rows.empty
                else [
                    {
                        "rank": int(r["rank"]),
                        "meteo_entity_id": r["meteo_entity_id"],
                        "distance_m": float(r["distance_m"]),
                        "same_station_code": bool(r["same_station_code"]),
                    }
                    for _, r in rows.iterrows()
                ]
            )
    return {
        "rule": (
            "For each (air station, variable): meteorological stations that report the variable in the data and lie "
            f"within {config['association']['max_distance_m']:.0f} m (great-circle, official coordinates), ranked by "
            f"distance, at most {config['association']['max_candidates']}; rank 1 primary, others used hour by hour "
            "only when the better ranked one has no valid value. No interpolation, no averaging, no co-location claim."
        ),
        "max_distance_m": config["association"]["max_distance_m"],
        "candidates": primary,
    }


def render_card(card: dict) -> str:
    lines = [
        f"# Feature card: {card['task_id']} ({card['data_version']})",
        "",
        f"Time convention: {card['time_convention']}",
        "",
        f"Rows: {card['rows']['total']:,} = {card['rows']['stations']} stations x {card['rows']['hours']:,} hours.",
        f"Excluded local dates (inputs nulled, rows flagged): {', '.join(card['excluded_local_dates']) or 'none'}.",
        "",
        "| feature | recommended | unit | key offset (h) | definition | availability | spatial association |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in card["features"]:
        lines.append(
            f"| `{s['name']}` | {'yes' if s['recommended'] else 'no'} | {s['unit']} | {s['source_key_offset_hours']:+d} | "
            f"{s['definition']} | {s['available_at']} | {s['spatial_association']} |"
        )
    lines += ["", "Other columns:", ""]
    lines += [f"- `{k}`: {v}" for k, v in card["other_columns"].items()]
    lines += [
        "",
        f"Target `target` ({card['target']['unit']}): NO2 of the hour with key issued_at_utc + {card['target']['key_offset_hours']}h.",
        "",
    ]
    return "\n".join(lines)


def render_coverage_doc(card: dict, summary: dict, assoc: dict) -> str:
    years = [r["year"] for r in summary["per_year"]]
    out = [
        "# Cobertura de la tabla `madrid_no2_h6`",
        "",
        "Generado por `python -m atlas.domains.air.features` (AT-011). No editar a mano. Interpretación y split "
        "recomendado: [`madrid_no2_h6.md`](madrid_no2_h6.md).",
        "",
        f"Versión: `{card['data_version']}`; filas: {card['rows']['total']:,} = {card['rows']['stations']} estaciones x "
        f"{card['rows']['hours']:,} horas de emisión (UTC). Fechas locales excluidas: "
        f"{', '.join(card['excluded_local_dates']) or 'ninguna'}.",
        "",
        "`completa` = todas las features recomendadas y el target no nulos y fuera de las ventanas excluidas "
        f"(recomendadas: {', '.join(f'`{n}`' for n in card['recommended_features'])}).",
        "",
        "## Filas por año de emisión (UTC)",
        "",
        "| año | filas | completas | % completas | en ventana excluida |",
        "|---|---|---|---|---|",
    ]
    for r in summary["per_year"]:
        out.append(
            f"| {r['year']} | {r['rows']:,} | {r['complete']:,} | {100 * r['complete'] / r['rows']:.1f} % | {r['excluded_day_window']:,} |"
        )
    tot_rows = sum(r["rows"] for r in summary["per_year"])
    tot_c = sum(r["complete"] for r in summary["per_year"])
    out.append(f"| total | {tot_rows:,} | {tot_c:,} | {100 * tot_c / tot_rows:.1f} % | |")
    out += [
        "",
        "## Fracción de filas completas por estación y año",
        "",
        "| estación | " + " | ".join(map(str, years)) + " |",
        "|---|" + "---|" * len(years),
    ]
    table: dict[str, dict[int, float]] = {}
    for r in summary["per_station_year"]:
        table.setdefault(r["entity_id"], {})[r["year"]] = r["complete"] / r["rows"]
    for e in sorted(table):
        out.append(f"| {e} | " + " | ".join(f"{100 * table[e].get(y, 0):.1f} %" for y in years) + " |")
    names = list(next(iter(summary["feature_non_null_fraction_per_year"].values())))
    out += [
        "",
        "## Fracción de filas con cada columna no nula, por año",
        "",
        "| año | " + " | ".join(names) + " |",
        "|---|" + "---|" * len(names),
    ]
    for y, vals in summary["feature_non_null_fraction_per_year"].items():
        out.append(f"| {y} | " + " | ".join(f"{100 * vals[n]:.1f} %" for n in names) + " |")
    out += ["", "## Asociación meteorológica (estación principal y distancia)", "", assoc["rule"], ""]
    vs = list(next(iter(assoc["candidates"].values())))
    out += ["| estación aire | " + " | ".join(vs) + " |", "|---|" + "---|" * len(vs)]
    for e, per_var in assoc["candidates"].items():
        cells = []
        for v in vs:
            c = per_var[v]
            cells.append(
                "sin candidata"
                if not c
                else f"{c[0]['meteo_entity_id'][-3:]} ({c[0]['distance_m'] / 1000:.1f} km{', misma' if c[0]['same_station_code'] else ''})"
            )
        out.append(f"| {e} | " + " | ".join(cells) + " |")
    out += [
        "",
        "Filas con valores meteorológicos de una estación de rango inferior (fallback), por número de variables:",
        "",
        "| variables con fallback | filas |",
        "|---|---|",
    ]
    out += [f"| {k} | {v:,} |" for k, v in summary["meteo_fallback_n_rows"].items()]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the madrid_no2_h6 feature/target table.")
    parser.add_argument("--config", type=Path, default=None, help="task config (default: configs/air/madrid_no2_h6.json)")
    parser.add_argument("--processed", type=Path, default=None, help="default: <ATLAS_DATA_DIR>/processed/air")
    parser.add_argument("--out-dir", type=Path, default=None, help="default: <processed>/features/madrid_no2_h6")
    parser.add_argument("--doc", type=Path, default=DOC_PATH)
    parser.add_argument("--no-doc", action="store_true")
    parser.add_argument("--exclude-date", action="append", default=[], help="extra local date to null (YYYY-MM-DD)")
    args = parser.parse_args(argv)
    result = run(
        processed=args.processed,
        out_dir=args.out_dir,
        doc_path=None if args.no_doc else args.doc,
        extra_excluded=args.exclude_date,
        config=load_config(args.config) if args.config else None,
    )
    rows = result["card"]["rows"]["total"]
    complete = sum(r["complete"] for r in result["summary"]["per_year"])
    print(f"{rows} rows, {complete} complete ({100 * complete / rows:.1f} %)", file=sys.stdout)


if __name__ == "__main__":
    main()
