"""EEA Germany hourly NO2 ingestion CLI (AT-070).

    PYTHONPATH=src python -m atlas.domains.air.eea_ingest --years 2019-2025

Steps: idempotent download (``eea_download``) -> staging of both datasets (E1a verified, E2a up-to-date) to Parquet with
the time already in UTC -> one canonical observation per (station, hour), E1a over E2a -> hive-partitioned Parquet
``year=/month=`` (UTC) -> contract validation (partition by partition) -> station entities with the EEA coordinates
-> quality report. Same output layout as the Madrid pipeline, under ``data/processed/air-de``.

Time convention (EEA, verified in ``docs/air/de_eea_air_quality.md``): ``Start``/``End`` of a value are in the fixed
offset ``UTC+01`` all year (the ``Timezone`` of every German sampling point in the station metadata is the vocabulary
entry ``UTC+01``; the Parquet carries naive timestamps), the value covers ``[Start, End)`` with ``End = Start + 1 h``.
So ``timestamp_utc = Start - 1 h`` is the START of the hour, as everywhere in Atlas. There is no daylight saving time in
the source: no nonexistent or ambiguous hours.
"""

# ruff: noqa: E501  (SQL and prose templates)

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from atlas.contracts.models import (
    Attribution,
    Domain,
    EntityCollection,
    EntityFeature,
    EntityProperties,
    GeometrySupport,
    PointGeometry,
    QualityReport,
)
from atlas.contracts.observations import validate_observations_partitioned
from atlas.domains.air import eea_download
from atlas.domains.air.stations import _haversine_m
from atlas.ingest.sources import MANIFEST_NAME, read_manifest, sha256_file
from atlas.paths import DEFAULT_DATASETS_ROOT, PROCESSED_DIR, RAW_DIR, REPO_ROOT

CONFIG_PATH = REPO_ROOT / "configs" / "air" / "de_eea.json"
DOC_PATH = REPO_ROOT / "docs" / "air" / "de_eea_air_quality.md"
MEMORY_LIMIT = "2GB"
THREADS = 4
UNIT_FACTORS = {"ug.m-3": 1.0, "ug/m3": 1.0, "mg.m-3": 1000.0, "ng.m-3": 0.001}
VALID_CODES = (1, 2, 3)  # EEA observation validity: 1 valid, 2 valid below detection limit (value measured), 3 valid, replaced by 0.5*DL
INVALID_CODES = (-1, -99)  # -1 not valid, -99 not valid due to station maintenance or calibration
SENTINEL = -999.0  # the value the EEA files carry for the invalid rows
COLOCATED_M = 100.0
NO2_URI_SUFFIX = "/pollutant/8"


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def parse_years(text: str) -> list[int]:
    years: set[int] = set()
    for part in text.split(","):
        lo, _, hi = part.strip().partition("-")
        years.update(range(int(lo), int(hi or lo) + 1))
    return sorted(years)


def utc_offset_hours(notation: str) -> int:
    """``UTC+01`` -> 1, ``UTC`` -> 0, ``UTC-02`` -> -2 (the EEA ``timezone`` vocabulary notation)."""
    match = re.fullmatch(r"UTC(?:([+-])(\d{2}))?", notation)
    if not match:
        raise ValueError(f"unsupported EEA timezone notation {notation!r}")
    return 0 if match.group(1) is None else int(match.group(1) + match.group(2))


def offset_label(hours: int) -> str:
    return "UTC" if hours == 0 else f"UTC{hours:+03d}"


def ensure_raw_dir(source_id: str, datasets_root: str | None) -> Path:
    """``data/raw/<source>`` -> ``<datasets_root>/<source>`` (symlink created when absent)."""
    link = RAW_DIR / source_id
    if link.exists() or link.is_symlink():
        return link
    link.parent.mkdir(parents=True, exist_ok=True)
    if datasets_root:
        target = Path(datasets_root) / source_id
        target.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target, target_is_directory=True)
    else:
        link.mkdir()
    return link


def verify_checksums(raw_dir: Path, source_id: str) -> dict[str, str]:
    manifest = read_manifest(raw_dir)
    if manifest is None:
        raise SystemExit(f"{raw_dir / MANIFEST_NAME} is missing: run without --skip-download first")
    for entry in manifest.files:
        if sha256_file(raw_dir / entry.path) != entry.sha256:
            raise SystemExit(f"{source_id}/{entry.path} does not match its manifest sha256 (raw files are immutable)")
    return {f"{source_id}/{f.path}": f.sha256 for f in manifest.files}


def connect(threads: int = THREADS, memory_limit: str = MEMORY_LIMIT, temp: Path | None = None) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(f"SET memory_limit='{memory_limit}'")
    con.execute(f"SET threads={threads}")
    con.execute("SET TimeZone='UTC'")
    if temp is not None:
        con.execute(f"SET temp_directory='{temp}'")
    return con


# ------------------------------------------------------------------------------------------ staging


def stage_dataset(
    con: duckdb.DuckDBPyConnection, glob: str, out: Path, years: list[int], offset_hours: int
) -> dict:
    """All rows of the dataset's files whose ``Start`` falls in the requested years (UTC+01 clock), time converted.

    ``ts_utc = Start - offset`` (start of the hour). The EEA ``Value`` of the invalid rows is the sentinel -999; it is
    kept here and removed when the canonical rows are built.
    """
    year_list = ", ".join(str(y) for y in years)
    con.execute(
        f"""COPY (
            SELECT regexp_extract(filename, 'SPO\\.[A-Za-z]{{2}}_([A-Za-z0-9]+)_NO2_dataGroup', 1) AS entity_id,
                   regexp_extract(filename, '(SPO\\.[A-Za-z0-9_]+)\\.parquet$', 1) AS sampling_point,
                   CAST("Start" - INTERVAL {offset_hours} HOUR AS TIMESTAMPTZ) AS ts_utc,
                   "Start" AS start_local, "End" AS end_local,
                   CAST("Value" AS DOUBLE) AS value, "Unit" AS unit, "AggType" AS agg_type,
                   CAST("Validity" AS INTEGER) AS validity, CAST("Verification" AS INTEGER) AS verification,
                   CAST("Pollutant" AS INTEGER) AS pollutant
            FROM read_parquet('{glob}', filename = true)
            WHERE year("Start") IN ({year_list})
            ORDER BY ts_utc, entity_id
        ) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)"""
    )
    q = f"FROM read_parquet('{out}')"
    rows = con.execute(f"SELECT count(*) {q}").fetchone()[0]
    checks = {
        "agg_type_not_hour": "agg_type <> 'hour'",
        "interval_not_one_hour": "end_local - start_local <> INTERVAL 1 HOUR OR minute(start_local) <> 0 OR second(start_local) <> 0",
        "pollutant_not_no2": "pollutant <> 8",
        "empty_station_code": "entity_id = '' OR sampling_point = ''",
    }
    bad = {name: int(con.execute(f"SELECT count(*) {q} WHERE {cond}").fetchone()[0]) for name, cond in checks.items()}
    return {"rows_in_years": int(rows), "schema_violations": bad}


def primary_sampling_points(con: duckdb.DuckDBPyConnection, staged: Path) -> pd.DataFrame:
    """One sampling point per station and dataset: the one with most rows carrying a number (ties: smallest name)."""
    return con.execute(
        f"""SELECT entity_id, sampling_point, n_numbers, n_sampling_points FROM (
              SELECT entity_id, sampling_point, n_numbers,
                     row_number() OVER (PARTITION BY entity_id ORDER BY n_numbers DESC, sampling_point) AS rk,
                     count(*) OVER (PARTITION BY entity_id) AS n_sampling_points
              FROM (SELECT entity_id, sampling_point, count(*) FILTER (WHERE validity IN (1, 2, 3) AND value IS NOT NULL AND value <> {SENTINEL}) AS n_numbers
                    FROM read_parquet('{staged}') GROUP BY ALL)) WHERE rk = 1 ORDER BY entity_id"""
    ).df()


def unit_factor_sql(column: str = "unit") -> str:
    cases = " ".join(f"WHEN '{u}' THEN {f}" for u, f in UNIT_FACTORS.items())
    return f"CASE {column} {cases} ELSE NULL END"


def canonical_select_sql(staged_sources: dict[str, Path], cfg: dict, offset_hours: int, month_start: str, month_end: str) -> str:
    """SELECT of the canonical observation rows of one UTC month, E1a over E2a.

    Rows of a dataset are restricted to the station's primary sampling point (registered tables ``primary_<key>``).
    Value semantics: validity 1/2/3 with a number -> value (units converted to ug/m3); validity -1/-99 or an
    unsupported unit -> NULL + ``invalid_observation``; a valid row without a number -> NULL + ``no_observation``;
    validity 3 (replaced by 0.5*detection limit) -> ``censoring = 'left'``.
    """
    air = cfg["air"]
    factor = unit_factor_sql("unit")
    parts = []
    for ds in air["datasets"]:
        key = ds["key"]
        parts.append(
            f"""SELECT '{key}' AS ds, '{ds['source_id']}' AS source_id, s.* FROM read_parquet('{staged_sources[key]}') s
                JOIN primary_{key} p ON p.entity_id = s.entity_id AND p.sampling_point = s.sampling_point
                WHERE s.ts_utc >= TIMESTAMPTZ '{month_start}' AND s.ts_utc < TIMESTAMPTZ '{month_end}'"""
        )
    order = " ".join(f"WHEN '{ds['key']}' THEN {i}" for i, ds in enumerate(air["datasets"]))
    return f"""
    WITH rows AS ({" UNION ALL ".join(parts)}),
    ranked AS (SELECT *, row_number() OVER (PARTITION BY entity_id, ts_utc ORDER BY CASE ds {order} END) AS rk FROM rows)
    SELECT 'air' AS domain, entity_id, ts_utc AS timestamp_utc,
        strftime(start_local, '%Y-%m-%d %H:%M') || ' {offset_label(offset_hours)}' AS source_timestamp_local,
        '{cfg['timezone']}' AS timezone, '{cfg['pollutant']['feature_name']}' AS feature_name,
        CASE WHEN validity IN (1, 2, 3) AND value IS NOT NULL AND value <> {SENTINEL} AND ({factor}) IS NOT NULL
             THEN value * ({factor}) END AS value,
        '{cfg['pollutant']['unit']}' AS unit,
        CAST(validity AS VARCHAR) || ':' || CAST(verification AS VARCHAR) AS validity_flag,
        CASE WHEN validity IN (1, 2, 3) AND value IS NOT NULL AND value <> {SENTINEL} AND ({factor}) IS NOT NULL THEN NULL
             WHEN validity IN (1, 2, 3) AND value IS NULL THEN 'no_observation'
             ELSE 'invalid_observation' END AS missing_reason,
        CASE WHEN validity = 3 THEN 'left' END AS censoring,
        source_id, '{cfg['data_version']}' AS data_version,
        CAST(NULL AS TIMESTAMPTZ) AS aggregation_window_start_utc, CAST(NULL AS TIMESTAMPTZ) AS aggregation_window_end_utc,
        CAST(NULL AS BIGINT) AS n_records
    FROM ranked WHERE rk = 1 ORDER BY entity_id, timestamp_utc"""


def month_ranges(years: list[int], offset_hours: int) -> list[tuple[int, int, str, str]]:
    """UTC months that hold the hours of the requested years in the source clock: (year, month, start, end)."""
    first = pd.Timestamp(year=min(years), month=1, day=1, tz="UTC") - pd.Timedelta(hours=offset_hours)
    last = pd.Timestamp(year=max(years) + 1, month=1, day=1, tz="UTC") - pd.Timedelta(hours=offset_hours)
    out = []
    cursor = pd.Timestamp(year=first.year, month=first.month, day=1, tz="UTC")
    while cursor < last:
        nxt = cursor + pd.offsets.MonthBegin(1)
        out.append((cursor.year, cursor.month, cursor.isoformat(), nxt.isoformat()))
        cursor = nxt
    return out


def convert(cfg: dict, years: list[int], raw: Path, staging: Path, observations: Path, offset_hours: int) -> dict:
    """Stage both datasets, then write the canonical observations month by month. Returns the inventory/statistics."""
    staging.mkdir(parents=True, exist_ok=True)
    con = connect(temp=staging / "_spill")
    staged: dict[str, Path] = {}
    inventory: dict[str, dict] = {}
    primary_points: dict[str, str] = {}  # station -> sampling point (E1a's first, E2a's for stations only there)
    for ds in cfg["air"]["datasets"]:
        key = ds["key"]
        files = sorted((raw / key).glob("*.parquet"))
        staged[key] = staging / f"{key}.parquet"
        info = stage_dataset(con, str(raw / key / "*.parquet"), staged[key], years, offset_hours)
        bad = {k: v for k, v in info["schema_violations"].items() if v}
        if bad:
            raise SystemExit(f"{key}: the files violate the expected schema: {bad}")
        primary = primary_sampling_points(con, staged[key])
        for entity, point in zip(primary["entity_id"], primary["sampling_point"], strict=True):
            primary_points.setdefault(entity, point)
        con.register(f"primary_{key}_df", primary)
        con.execute(f"CREATE TABLE primary_{key} AS SELECT entity_id, sampling_point FROM primary_{key}_df")
        sp_total = con.execute(f"SELECT count(DISTINCT sampling_point) FROM read_parquet('{staged[key]}')").fetchone()[0]
        span = con.execute(f"""SELECT min("Start"), max("Start") FROM read_parquet('{raw / key / "*.parquet"}')""").fetchone()
        inventory[key] = {
            "files": len(files),
            "first_start_in_files": span[0].isoformat(),
            "last_start_in_files": span[1].isoformat(),
            "rows_in_selected_years": info["rows_in_years"],
            "stations": int(len(primary)),
            "sampling_points": int(sp_total),
            "stations_with_several_sampling_points": primary.loc[primary["n_sampling_points"] > 1, "entity_id"].tolist(),
        }
    if observations.exists():
        shutil.rmtree(observations)
    written = 0
    precedence = {"hours_in_both_datasets": 0, "hours_in_both_with_different_value": 0, "e2a_rows_used": 0}
    first, second = cfg["air"]["datasets"][0]["key"], cfg["air"]["datasets"][1]["key"]
    for year, month, start, end in month_ranges(years, offset_hours):
        sql = canonical_select_sql(staged, cfg, offset_hours, start, end)
        n = con.execute(f"SELECT count(*) FROM ({sql})").fetchone()[0]
        if not n:
            continue
        target = observations / f"year={year}" / f"month={month}"
        target.mkdir(parents=True)
        con.execute(f"COPY ({sql}) TO '{target / 'data_0.parquet'}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        written += n
        both = con.execute(
            f"""SELECT count(*), count(*) FILTER (WHERE a.value IS DISTINCT FROM b.value) FROM read_parquet('{staged[first]}') a
                JOIN primary_{first} pa ON pa.entity_id = a.entity_id AND pa.sampling_point = a.sampling_point
                JOIN read_parquet('{staged[second]}') b ON b.entity_id = a.entity_id AND b.ts_utc = a.ts_utc
                JOIN primary_{second} pb ON pb.entity_id = b.entity_id AND pb.sampling_point = b.sampling_point
                WHERE a.ts_utc >= TIMESTAMPTZ '{start}' AND a.ts_utc < TIMESTAMPTZ '{end}'"""
        ).fetchone()
        precedence["hours_in_both_datasets"] += int(both[0])
        precedence["hours_in_both_with_different_value"] += int(both[1])
    precedence["e2a_rows_used"] = int(
        con.execute(f"SELECT count(*) FROM read_parquet('{observations}/**/*.parquet', hive_partitioning = true) WHERE source_id = '{cfg['air']['datasets'][1]['source_id']}'").fetchone()[0]
    )
    con.close()
    return {"inventory": inventory, "rows_written": written, "precedence": precedence, "primary_points": primary_points}


# --------------------------------------------------------------------------------------- summaries


def summarize_output(observations: Path, timezone: str) -> dict:
    """Coverage, flag mixes and date range from the written dataset (bounded-memory DuckDB)."""
    con = connect(memory_limit="2GB")
    con.execute(f"CREATE VIEW obs AS SELECT * FROM read_parquet('{observations}/**/*.parquet', hive_partitioning=true)")
    cols = [r[0] for r in con.execute("DESCRIBE obs").fetchall() if r[0] not in ("year", "month")]
    nulls = con.execute("SELECT " + ", ".join(f"count(*) FILTER (WHERE {c} IS NULL)" for c in cols) + " FROM obs").fetchone()
    total, lo, hi = con.execute("SELECT count(*), min(timestamp_utc), max(timestamp_utc) FROM obs").fetchone()
    coverage = con.execute(
        f"SELECT entity_id, year(timezone('{timezone}', timestamp_utc)) AS y, count(*) AS slots, count(value) AS valid, "
        "min(timestamp_utc) FILTER (WHERE value IS NOT NULL), max(timestamp_utc) FILTER (WHERE value IS NOT NULL), "
        "list(DISTINCT source_id) FILTER (WHERE value IS NOT NULL) FROM obs GROUP BY ALL ORDER BY ALL"
    ).fetchall()
    reasons = dict(con.execute("SELECT coalesce(missing_reason, 'valid'), count(*) FROM obs GROUP BY ALL").fetchall())
    flags = con.execute(
        f"SELECT source_id, year(timezone('{timezone}', timestamp_utc)) AS y, validity_flag, count(*) FROM obs GROUP BY ALL ORDER BY ALL"
    ).fetchall()
    value_stats = con.execute(
        "SELECT count(*) FILTER (WHERE value < 0), count(*) FILTER (WHERE value = 0), count(*) FILTER (WHERE value > 1000), "
        "min(value), max(value), count(*) FILTER (WHERE censoring IS NOT NULL) FROM obs"
    ).fetchone()
    con.close()
    return {
        "rows": int(total),
        "min_utc": lo,
        "max_utc": hi,
        "missing_by_column": dict(zip(cols, map(int, nulls), strict=True)),
        "coverage_rows": coverage,
        "by_reason": {k: int(v) for k, v in sorted(reasons.items())},
        "flags": [[s, int(y), f, int(n)] for s, y, f, n in flags],
        "value_stats": {
            "negative": int(value_stats[0]),
            "exact_zero": int(value_stats[1]),
            "above_1000": int(value_stats[2]),
            "min": value_stats[3],
            "max": value_stats[4],
            "censored_left": int(value_stats[5]),
        },
    }


def diurnal_check(observations: Path, stations: EntityCollection, year: int) -> dict:
    """Evidence for the time convention: weekday NO2 of urban traffic stations by UTC hour, January-February versus July-August.

    The source clock is fixed at UTC+01 while the local clock moves to UTC+02 in summer, so the daily cycle (a local-clock
    phenomenon: rush hours) must sit one UTC hour EARLIER in July-August than in January-February. The shift is
    estimated as the circular lag in -3..3 h that best aligns the (mean-scaled) summer curve with the winter one.
    """
    ids = [
        f.id for f in stations.features
        if f.properties.attributes.get("station_type") == "traffic" and f.properties.attributes.get("station_area") == "urban"
    ]
    if not ids:
        return {}
    con = connect(memory_limit="1GB")
    con.register("ids", pd.DataFrame({"entity_id": ids}))
    con.execute(f"CREATE VIEW obs AS SELECT * FROM read_parquet('{observations}/**/*.parquet', hive_partitioning=true)")
    out: dict = {"year": year, "stations": len(ids)}
    curves = {}
    for label, months in (("winter", (1, 2)), ("summer", (7, 8))):
        rows = con.execute(
            f"""SELECT hour(timestamp_utc) AS h, avg(value) FROM obs JOIN ids USING (entity_id)
                WHERE value IS NOT NULL AND month(timestamp_utc) IN {months} AND year(timestamp_utc) = {year}
                  AND isodow(timestamp_utc) IN (2, 3, 4, 5) GROUP BY h ORDER BY h"""
        ).fetchall()
        curves[label] = [r[1] for r in rows]
        out[label] = {"mean_by_utc_hour": [round(v, 1) for v in curves[label]]}
    con.close()
    winter = [v / (sum(curves["winter"]) / 24) for v in curves["winter"]]
    summer = [v / (sum(curves["summer"]) / 24) for v in curves["summer"]]
    sse = {lag: sum((winter[h] - summer[(h - lag) % 24]) ** 2 for h in range(24)) for lag in range(-3, 4)}
    out["best_lag_hours"] = min(sse, key=sse.get)
    out["sse_by_lag"] = {str(k): round(v, 3) for k, v in sse.items()}
    out["summer_cycle_one_hour_earlier"] = out["best_lag_hours"] == 1
    return out


# ----------------------------------------------------------------------------------------- stations


def read_metadata(csv_path: Path, country: str) -> pd.DataFrame:
    """NO2 rows of the EEA station/sampling-point metadata for one country."""
    con = duckdb.connect()
    frame = con.execute(
        f"""SELECT * FROM read_csv('{csv_path}', delim = '\t', header = true, all_varchar = true, quote = '')
            WHERE Countrycode = '{country}' AND AirPollutantCode LIKE '%{NO2_URI_SUFFIX}'"""
    ).df()
    con.close()
    return frame


def read_esri_stations(path: Path) -> dict[str, dict]:
    """EEA monitoring-stations layer: ``{EoI code: {"name", "lon_lat"}}`` (names; coordinates rounded to 4 decimals)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        f["properties"]["AirQualityStationEoICode"]: {
            "name": f["properties"]["AQStationName"],
            "lon_lat": tuple(f["geometry"]["coordinates"]) if f.get("geometry") else None,
        }
        for f in data["features"]
    }


def build_station_collection(
    metadata: pd.DataFrame, esri: dict[str, dict], observed: dict[str, dict], cfg: dict, attribution: list[Attribution]
) -> tuple[EntityCollection, dict]:
    """Merge the EEA coordinates and station attributes with what the hourly data contain.

    Geometry is the EEA ``Longitude``/``Latitude`` of the sampling point (EPSG:4979 -> WGS84 lon/lat). A station absent
    from the metadata falls back to the point of the EEA monitoring-stations layer (``esri``), if that has it; a station
    with neither, or whose point falls outside the Germany bounding box, gets ``geometry: null`` (the rejected
    coordinates stay in ``attributes``). Coordinates are never inferred.
    """
    lon_min, lat_min, lon_max, lat_max = cfg["stations"]["bbox_lon_lat"]
    by_station: dict[str, pd.DataFrame] = {code: g for code, g in metadata.groupby("AirQualityStationEoICode")}
    features, outside, multi_coord, points, fallback = [], {}, {}, {}, {}
    for code in sorted(set(observed) | set(by_station)):
        info = observed.get(code)
        rows = by_station.get(code)
        if info is None:
            continue  # only stations with data in the period become entities
        attrs: dict = {
            "in_hourly_data": True,
            "has_official_coordinates": rows is not None,
            "observed_features": [cfg["pollutant"]["feature_name"]],
            "first_observation_utc": info["first_utc"],
            "last_observation_utc": info["last_utc"],
            "datasets": info["datasets"],
            "eea_station_name": (esri.get(code) or {}).get("name"),
        }
        geometry = None
        geometry_source = cfg["stations"]["geometry_source"]
        if rows is None and (esri.get(code) or {}).get("lon_lat"):
            lon, lat = esri[code]["lon_lat"]
            fallback[code] = [lon, lat]
            geometry_source = cfg["stations"]["names_source"]
            attrs.update(
                geometry_epsg=4326,
                geometry_note="Station absent from the EEA metadata file; point of the EEA monitoring-stations layer (4 decimals).",
            )
            if lon_min <= lon <= lon_max and lat_min <= lat <= lat_max:
                geometry = PointGeometry(type="Point", coordinates=(lon, lat))
                points[code] = (lon, lat)
            else:
                attrs["rejected_coordinates_lon_lat"] = [lon, lat]
                outside[code] = [lon, lat]
        if rows is not None:
            first = rows.iloc[0]
            lonlats = {(round(float(r["Longitude"]), 6), round(float(r["Latitude"]), 6)) for _, r in rows.iterrows()}
            lon, lat = float(first["Longitude"]), float(first["Latitude"])
            if len(lonlats) > 1:
                multi_coord[code] = sorted(lonlats)
            attrs.update(
                station_type=first["AirQualityStationType"],
                station_area=first["AirQualityStationArea"],
                altitude_m=float(first["Altitude"]) if first["Altitude"] not in (None, "", "NULL") else None,
                network=first["AirQualityNetwork"],
                sampling_point=info["sampling_point"],
                measurement_type=sorted(set(rows["MeasurementType"])),
                source_timezone=str(first["Timezone"]).rsplit("/", 1)[-1],
                metadata_observation_begin=first["ObservationDateBegin"],
                metadata_observation_end=first["ObservationDateEnd"],
                geometry_epsg=4326,
                geometry_note="EEA metadata Longitude/Latitude (EPSG:4979 horizontal part = WGS84 lon/lat).",
            )
            if lon_min <= lon <= lon_max and lat_min <= lat <= lat_max:
                geometry = PointGeometry(type="Point", coordinates=(lon, lat))
                points[code] = (lon, lat)
            else:
                attrs["rejected_coordinates_lon_lat"] = [lon, lat]
                outside[code] = [lon, lat]
        features.append(
            EntityFeature(
                type="Feature",
                id=code,
                geometry=geometry,
                properties=EntityProperties(
                    entity_id=code,
                    domain=Domain.AIR,
                    name=(esri.get(code) or {}).get("name") or code,
                    geometry_support=GeometrySupport.OBSERVED_POINT,
                    geometry_source=geometry_source,
                    timezone=cfg["timezone"],
                    attributes=attrs,
                ),
            )
        )
    colocated = colocated_pairs(points)
    for feature in features:
        near = colocated.get(feature.id)
        if near:
            feature.properties.attributes["colocated_within_100m"] = near
    codes = sorted(points)
    report = {
        "entities": len(features),
        "with_geometry": len(points),
        "absent_from_metadata_file": sorted(c for c in observed if c not in by_station),
        "coordinates_from_stations_layer": fallback,
        "without_official_coordinates": sorted(c for c in observed if c not in points and c not in outside),
        "outside_bbox": outside,
        "bbox_lon_lat": cfg["stations"]["bbox_lon_lat"],
        "several_distinct_coordinates_in_metadata": multi_coord,
        "colocated_within_m": COLOCATED_M,
        "colocated_pairs": sorted({tuple(sorted((a, b["id"]))) + (b["distance_m"],) for a, v in colocated.items() for b in v}),
        "identical_coordinates": sorted(
            {tuple(sorted((a, b["id"]))) for a, v in colocated.items() for b in v if b["distance_m"] == 0.0}
        ),
        "stations_with_geometry_sorted": codes,
    }
    collection = EntityCollection(
        type="FeatureCollection", domain=Domain.AIR, data_version=cfg["data_version"], attribution=attribution, features=features
    )
    return collection, report


def colocated_pairs(points: dict[str, tuple[float, float]], within_m: float = COLOCATED_M) -> dict[str, list[dict]]:
    """Station pairs at most ``within_m`` apart (great circle), both directions: ``{id: [{"id", "distance_m"}]}``."""
    out: dict[str, list[dict]] = {}
    codes = sorted(points)
    for i, a in enumerate(codes):
        for b in codes[i + 1 :]:
            (lon1, lat1), (lon2, lat2) = points[a], points[b]
            if abs(lat1 - lat2) > 0.01 or abs(lon1 - lon2) > 0.02:
                continue
            d = _haversine_m(lon1, lat1, lon2, lat2)
            if d <= within_m:
                out.setdefault(a, []).append({"id": b, "distance_m": round(d, 1)})
                out.setdefault(b, []).append({"id": a, "distance_m": round(d, 1)})
    return out


def observed_stations(coverage_rows: list, primary: dict[str, dict[str, str]]) -> dict[str, dict]:
    """``entity_id -> first/last valid hour, datasets that supplied values, primary sampling point``."""
    observed: dict[str, dict] = {}
    for entity, _y, _slots, valid, first, last, sources in coverage_rows:
        if not valid:
            continue
        info = observed.setdefault(entity, {"first_utc": first, "last_utc": last, "datasets": set()})
        info["first_utc"], info["last_utc"] = min(info["first_utc"], first), max(info["last_utc"], last)
        info["datasets"].update(s.rsplit("-", 1)[-1] for s in sources)
    for entity, info in observed.items():
        info["first_utc"], info["last_utc"] = info["first_utc"].isoformat(), info["last_utc"].isoformat()
        info["datasets"] = sorted(info["datasets"])
        info["sampling_point"] = primary.get(entity, {}).get("sampling_point")
    return observed


def expected_hours(year: int) -> int:
    """Hours of a calendar year of the fixed-offset source clock (no daylight saving time)."""
    return (date(year + 1, 1, 1) - date(year, 1, 1)).days * 24


def coverage_tables(rows: list, years: list[int]) -> dict:
    """``{entity: {year: {valid_hours, slots, fraction}}}`` (calendar year of the source clock)."""
    expected = {y: expected_hours(y) for y in years}
    table: dict = {}
    for entity, year, slots, valid, *_ in rows:
        if int(year) in expected:
            table.setdefault(entity, {})[int(year)] = {
                "valid_hours": int(valid), "slots": int(slots), "fraction": round(valid / expected[int(year)], 4),
            }
    return table


# ------------------------------------------------------------------------------------------ driver


def run(
    years: list[int],
    *,
    skip_download: bool = False,
    refresh: bool = False,
    datasets_root: str | None = None,
    out_dir: Path | None = None,
    doc_path: Path | None = DOC_PATH,
) -> dict:
    cfg = load_config()
    air = cfg["air"]
    source_id = air["source_id"]
    out_dir = out_dir or PROCESSED_DIR / "air-de"
    raw = ensure_raw_dir(source_id, datasets_root)
    if not skip_download:
        eea_download.download(cfg, years, raw, refresh=refresh)
    checksums = verify_checksums(raw, source_id)
    manifest = read_manifest(raw)

    meta = read_metadata(raw / "stations" / "PanEuropean_metadata.csv", cfg["country"])
    tz_values = sorted(set(meta["Timezone"]))
    if len(tz_values) != 1:
        raise SystemExit(f"German sampling points do not share one EEA timezone: {tz_values}")
    metadata_notation = tz_values[0].rsplit("/", 1)[-1]
    offset = utc_offset_hours(metadata_notation)
    if metadata_notation != cfg["source_timezone"]:
        raise SystemExit(f"EEA metadata says {metadata_notation}, config {cfg['source_timezone']}: check the time convention")

    out_dir.mkdir(parents=True, exist_ok=True)
    staging = out_dir / "_staging"
    if staging.exists():
        shutil.rmtree(staging)
    observations = out_dir / "observations"
    conv = convert(cfg, years, raw, staging, observations, offset)
    shutil.rmtree(staging)

    errors = validate_observations_partitioned(observations, memory_limit="1GB")
    if errors:
        raise SystemExit("canonical observations violate the contract: " + "; ".join(errors[:10]))

    summary = summarize_output(observations, cfg["timezone"])
    primary = {e: {"sampling_point": p} for e, p in conv["primary_points"].items()}
    observed = observed_stations(summary["coverage_rows"], primary)
    esri = read_esri_stations(raw / "stations" / "esri_stations_de.geojson")
    attribution = [
        Attribution(text=air["attribution"], license="CC BY 4.0", url=air["landing_url"]),
        Attribution(
            text="European Environment Agency (EEA), e-Reporting station and sampling point metadata (PanEuropean_metadata.csv) "
            "and Air Quality Download Service monitoring stations layer (station names).",
            license="CC BY 4.0",
            url=cfg["stations"]["geometry_source"],
        ),
    ]
    collection, station_report = build_station_collection(meta, esri, observed, cfg, attribution)
    (out_dir / "stations.geojson").write_text(
        json.dumps(json.loads(collection.model_dump_json()), indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    coverage = coverage_tables(summary["coverage_rows"], years)
    diurnal = diurnal_check(observations, collection, 2019 if 2019 in years else years[0])

    n_stations_no_valid = sorted(
        {e for e, *_ in summary["coverage_rows"]} - set(observed)
    )
    covered = [f for f in collection.features if f.geometry is not None]
    lons = [f.geometry.coordinates[0] for f in covered]
    lats = [f.geometry.coordinates[1] for f in covered]
    c = summary["value_stats"]
    flags_invalid = {
        f"validity:{flag.split(':')[0]}": 0 for _s, _y, flag, _n in summary["flags"] if flag.split(":")[0] not in ("1",)
    }
    for _s, _y, flag, n in summary["flags"]:
        key = f"validity:{flag.split(':')[0]}"
        if key in flags_invalid:
            flags_invalid[key] += n
    valid_rows = summary["rows"] - sum(v for k, v in summary["by_reason"].items() if k != "valid")
    report = QualityReport(
        source_id=source_id,
        source_url=air["landing_url"],
        downloaded_at_utc=manifest.downloaded_at_utc,
        period_start=pd.Timestamp(summary["min_utc"]).tz_convert(cfg["timezone"]).date(),
        period_end=pd.Timestamp(summary["max_utc"]).tz_convert(cfg["timezone"]).date(),
        license=air["license"],
        input_sha256=checksums,
        raw_rows=summary["rows"],
        valid_rows=valid_rows,
        duplicate_rows=0,
        uniqueness_key=["domain", "entity_id", "timestamp_utc", "feature_name", "source_id"],
        missing_by_column=summary["missing_by_column"],
        invalid_codes=flags_invalid,
        outliers_flagged=c["negative"] + c["above_1000"],
        date_range_utc=(summary["min_utc"], summary["max_utc"]),
        geographic_coverage={
            "stations_in_hourly_data": len(observed),
            "stations_with_official_point": len(covered),
            "stations_without_official_coordinates": station_report["without_official_coordinates"],
            "stations_outside_bbox": station_report["outside_bbox"],
            "bbox_lon_lat": [min(lons), min(lats), max(lons), max(lats)],
            "germany_bbox_lon_lat": cfg["stations"]["bbox_lon_lat"],
            "geometry_source": cfg["stations"]["geometry_source"],
            "geometry_support": "observed_point",
        },
        sampling_frequency="hourly; one slot per station x hour; timestamp_utc = start of the hour",
        value_units={cfg["pollutant"]["feature_name"]: cfg["pollutant"]["unit"]},
        known_limitations=build_limitations(conv, summary, station_report, cfg),
    )
    (out_dir / "quality_report.json").write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    details = {
        "data_version": cfg["data_version"],
        "years": years,
        "timezone": cfg["timezone"],
        "source_timezone": metadata_notation,
        "source_utc_offset_hours": offset,
        "downloaded_at_utc": manifest.downloaded_at_utc.isoformat(),
        "dst_anomalies": {},  # fixed-offset source clock: no daylight saving time, no excluded local days
        "inventory": conv["inventory"],
        "precedence": conv["precedence"],
        "rows_written": conv["rows_written"],
        "by_reason": summary["by_reason"],
        "flags": summary["flags"],
        "value_stats": summary["value_stats"],
        "expected_hours": {y: expected_hours(y) for y in years},
        "coverage": coverage,
        "stations": station_report,
        "stations_without_valid_values": n_stations_no_valid,
        "diurnal_check": diurnal,
        "sha256": checksums,
        "date_range_utc": [summary["min_utc"].isoformat(), summary["max_utc"].isoformat()],
    }
    (out_dir / "ingest_details.json").write_text(json.dumps(details, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    if doc_path is not None:
        from atlas.domains.air.de_report import render_eea_markdown

        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(render_eea_markdown(details, report, collection), encoding="utf-8")
    return details


def build_limitations(conv: dict, summary: dict, stations: dict, cfg: dict) -> list[str]:
    inv, prec = conv["inventory"], conv["precedence"]
    out = [
        f"{inv['e1a']['stations']} stations in E1a (verified) and {inv['e2a']['stations']} in E2a (up-to-date) within the selected years; "
        f"E2a supplies {prec['e2a_rows_used']:,} of the {summary['rows']:,} canonical rows; where both exist E1a wins "
        f"({prec['hours_in_both_datasets']:,} hours in both, {prec['hours_in_both_with_different_value']:,} with a different value).",
        "validity_flag is '<EEA Validity>:<EEA Verification>' (Validity 1 valid, 2 valid below the detection limit with the measured "
        "value given, 3 replaced by 0.5*DL, -1 not valid, -99 maintenance/calibration; Verification 1 verified, 2 preliminary, 3 not verified).",
        "The invalid rows carry the sentinel -999 in the EEA files; it is never written as a value (value is NULL).",
        f"{summary['value_stats']['negative']:,} valid values are negative (instrument noise below the detection limit, Validity 2) and "
        f"{summary['value_stats']['above_1000']} exceed 1000 ug/m3; they are kept as reported and counted in outliers_flagged.",
        "Coordinates are the EEA sampling-point coordinates (WGS84); stations differ in type and area (traffic, background, industrial; "
        "urban, suburban, rural): the type is an entity attribute, not a model input.",
    ]
    if stations["outside_bbox"]:
        out.append(f"Stations whose coordinates fall outside the Germany bounding box get no geometry: {sorted(stations['outside_bbox'])}.")
    if stations["colocated_pairs"]:
        out.append(f"{len(stations['colocated_pairs'])} station pairs lie within {COLOCATED_M:.0f} m of each other (listed in ingest_details.json); both are kept.")
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Ingest EEA hourly NO2 for Germany into canonical Parquet.")
    parser.add_argument("--years", default="2019-2025", help="e.g. 2019-2025 (default: %(default)s)")
    parser.add_argument("--skip-download", action="store_true", help="use data/raw as is (must have the manifest)")
    parser.add_argument("--download-only", action="store_true", help="only fetch the raw files and the manifest")
    parser.add_argument("--refresh", action="store_true", help="re-download files even if the checksum matches")
    parser.add_argument("--datasets-root", default=os.environ.get("ATLAS_DATASETS_ROOT", DEFAULT_DATASETS_ROOT))
    parser.add_argument("--out-dir", type=Path, default=None, help="default: data/processed/air-de")
    parser.add_argument("--doc", type=Path, default=DOC_PATH, help="where to write the quality markdown")
    parser.add_argument("--no-doc", action="store_true")
    args = parser.parse_args(argv)
    years = parse_years(args.years)
    if args.download_only:
        cfg = load_config()
        raw = ensure_raw_dir(cfg["air"]["source_id"], args.datasets_root)
        manifest, fetched = eea_download.download(cfg, years, raw, refresh=args.refresh)
        print(f"{cfg['air']['source_id']}: {len(manifest.files)} files, fetched now: {len(fetched)}")
        return
    details = run(
        years, skip_download=args.skip_download, refresh=args.refresh, datasets_root=args.datasets_root,
        out_dir=args.out_dir, doc_path=None if args.no_doc else args.doc,
    )
    print(f"{details['rows_written']} canonical rows, {details['date_range_utc']}", file=sys.stdout)


if __name__ == "__main__":
    main()
