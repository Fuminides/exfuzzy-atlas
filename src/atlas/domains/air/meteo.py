"""Madrid hourly meteorology ingestion CLI (AT-011).

    PYTHONPATH=src python -m atlas.domains.air.meteo --years 2019-2025

Same layout as the air-quality files (one record per station x magnitude x day, ``H01..H24`` + ``V01..V24``), so the
air readers and ``wide_to_long`` are reused with the meteorological magnitude table. Output:
``data/processed/air/meteo/{observations/year=/month=, stations.geojson, quality_report.json, ingest_details.json}``.
"""

# ruff: noqa: E501  (prose templates and SQL)

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow.parquet as pq

from atlas.contracts.models import (
    Domain,
    EntityCollection,
    EntityFeature,
    EntityProperties,
    GeometrySupport,
    PointGeometry,
    QualityReport,
)
from atlas.contracts.observations import validate_observations
from atlas.domains.air.ingest import (
    DEFAULT_DATASETS_ROOT,
    _expected_hours,
    _verify_checksums,
    dst_anomalies,
    ensure_raw_dir,
    parse_years,
    summarize_output,
    write_partitions,
)
from atlas.domains.air.meteo_report import render_markdown
from atlas.domains.air.parse import (
    COUNTER_KEYS,
    TIMEZONE,
    Stats,
    read_csv_wide,
    read_txt_wide,
    wide_to_long,
)
from atlas.ingest.sources import Fetcher, ensure_source, http_fetch, read_manifest
from atlas.paths import PROCESSED_DIR, RAW_DIR, REPO_ROOT

CONFIG_PATH = REPO_ROOT / "configs" / "air" / "madrid_meteo.json"
SOURCE_ID = "madrid-meteo"
STATIONS_ID = "madrid-meteo-stations"
STATIONS_FILE = "estaciones-meteorologicas.csv"
DOC_PATH = REPO_ROOT / "docs" / "air" / "madrid_meteo_quality.md"
CHUNK_ROWS = 20_000

# Annex II of ``interprete_datos_meteorologicos.pdf``. Code 80 (ultraviolet radiation, unit written "Mw/m2") is listed
# there and appears only in Jan-May 2019 for stations 24, 54 and 59: it is not ingested and is counted under
# ``unknown_magnitude_slots``. Units written ASCII.
METEO_MAGNITUDES: dict[int, tuple[str, str]] = {
    81: ("wind_speed", "m/s"),
    82: ("wind_direction", "deg"),
    83: ("temperature", "degC"),
    86: ("relative_humidity", "%"),
    87: ("pressure", "mbar"),
    88: ("solar_radiation", "W/m2"),
    89: ("precipitation", "l/m2"),
}
# Official sensor column of the station CSV -> feature name.
STATION_SENSOR_COLUMNS = {
    "VV (81)": "wind_speed",
    "DV (82)": "wind_direction",
    "T (83)": "temperature",
    "HR (86)": "relative_humidity",
    "PB (87)": "pressure",
    "RS (88)": "solar_radiation",
    "P (89)": "precipitation",
}
# Plausible physical ranges, used to FLAG (``outliers_flagged``) valid-coded values here and to null them in the
# feature table (the canonical observations are never altered). Temperature: sentinel-like -55 and -30 appear with code
# V, the real minimum of the series is about -17 degC. Pressure is station level (altitudes 565-706 m: about 920-960
# mbar; sea-level extremes 950-1060 scaled by exp(-h/8400) stay within 880-1000); the library keeps -1..1073 readings.
PLAUSIBLE_RANGE = {
    "wind_speed": (0.0, 50.0),
    "wind_direction": (0.0, 360.0),
    "temperature": (-20.0, 50.0),
    "relative_humidity": (0.0, 100.0),
    "pressure": (880.0, 1000.0),
    "solar_radiation": (0.0, 1500.0),
    "precipitation": (0.0, 100.0),
}


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def download(config: dict, years: list[int], datasets_root: str | None, refresh: bool, fetch: Fetcher = http_fetch):
    """Fetch the raw meteorological files for the requested years and the station files. Returns both manifests."""
    meteo, st = config["meteo"], config["stations"]
    wanted = [f for f in meteo["files"] if f["role"] != "data" or set(f["years"]) & set(years)]
    manifests = {
        SOURCE_ID: ensure_source(
            ensure_raw_dir(SOURCE_ID, datasets_root),
            source_id=SOURCE_ID,
            domain=Domain.AIR,
            title=meteo["title"],
            landing_url=meteo["landing_url"],
            license=meteo["license"],
            attribution=meteo["attribution"],
            files=wanted,
            period_start=date.fromisoformat(meteo["period_start"]),
            notes=[
                "2019-2024: one CSV and one TXT per month (the portal also offers XML, not downloaded); "
                "2025 onwards: a single CSV that the portal extends monthly (its sha256 is that of the download time).",
                "Hourly values are Europe/Madrid local time like the air-quality files; the meteorological "
                "interpreter says nothing about daylight saving time, see docs/air/madrid_meteo.md for the evidence.",
            ],
            fetch=fetch,
            refresh=refresh,
        ),
        STATIONS_ID: ensure_source(
            ensure_raw_dir(STATIONS_ID, datasets_root),
            source_id=STATIONS_ID,
            domain=Domain.AIR,
            title=st["title"],
            landing_url=st["landing_url"],
            license=st["license"],
            attribution=st["attribution"],
            files=st["files"],
            notes=["Official CSV of sensor locations (the PDF documents its columns); last update 2023-05-03."],
            fetch=fetch,
            refresh=refresh,
        ),
    }
    return manifests


def convert(config: dict, years: list[int], raw_meteo: Path, staging: Path) -> tuple[Stats, dict]:
    """Stream every input file to staged Parquet parts. Returns the stats and a per-file inventory."""
    stats, seen, inventory, part = Stats(), {}, {}, 0
    version = config["data_version"]
    staging.mkdir(parents=True, exist_ok=True)

    def emit(wide: pd.DataFrame, name: str, month: int | None = None) -> None:
        nonlocal part
        wide = wide[pd.to_numeric(wide["year"], errors="coerce").isin(years)]
        info = inventory[name]
        for fmt, n in wide["fmt"].value_counts().items():
            info["rows_in_selected_years"][fmt] = info["rows_in_selected_years"].get(fmt, 0) + int(n)
        if month is not None:
            stray = wide[pd.to_numeric(wide["month"], errors="coerce") != month]
            if len(stray):
                raise SystemExit(
                    f"{name}: {len(stray)} rows outside the declared month {month}; the portal mislabelled it"
                )
        if wide.empty:
            return
        table, _ = wide_to_long(
            wide, data_version=version, seen=seen, stats=stats, magnitudes=METEO_MAGNITUDES, source_id=SOURCE_ID
        )
        pq.write_table(table, staging / f"part-{part:05d}.parquet", compression="zstd")
        part += 1

    units: dict[tuple[int, int], list[dict]] = {}
    for spec in config["meteo"]["files"]:
        if spec["role"] != "data" or not set(spec["years"]) & set(years):
            continue
        if "month" in spec:
            units.setdefault((spec["years"][0], spec["month"]), []).append(spec)
    for (_, month), specs in sorted(units.items()):
        frames = []
        for spec in sorted(specs, key=lambda s: s["path"].endswith(".txt")):  # CSV first: it has precedence
            raw = (raw_meteo / spec["path"]).read_bytes()
            inventory[spec["path"]] = {"layout": "monthly " + spec["path"][-3:], "rows_in_selected_years": {}}
            frame = read_csv_wide(raw) if spec["path"].endswith(".csv") else read_txt_wide(raw)
            inventory[spec["path"]]["rows_in_selected_years"][frame["fmt"].iat[0]] = len(frame)
            frames.append(frame)
        emit(pd.concat(frames, ignore_index=True), specs[0]["path"], month)
    for spec in config["meteo"]["files"]:
        if spec["role"] == "data" and "month" not in spec and set(spec["years"]) & set(years):
            inventory[spec["path"]] = {
                "layout": "single csv (';', quoted, UTF-8 BOM), several years",
                "rows_in_selected_years": {},
            }
            for chunk in read_csv_wide((raw_meteo / spec["path"]).read_bytes(), chunksize=CHUNK_ROWS):
                emit(chunk, spec["path"])
    return stats, inventory


# ------------------------------------------------------------------------------------------- stations


def read_station_csv(path: Path) -> list[dict]:
    """Official meteorological sensor locations (UTF-8, ``;``). Coordinates in decimal degrees (WGS84-compatible)."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))
    out = []
    for row in rows:
        code = row["CÓDIGO"].strip()
        out.append(
            {
                "entity_id": code,
                "name": row["ESTACION"].strip(),
                "address": (row["DIRECCION"] or "").strip(),
                "lon": float(row["LONGITUD"].replace(",", ".")),
                "lat": float(row["LATITUD"].replace(",", ".")),
                "altitude_m": int(row["ALTITUD"]) if row["ALTITUD"].strip() else None,
                "official_sensors": sorted(
                    v for k, v in STATION_SENSOR_COLUMNS.items() if row[k].strip().upper() == "X"
                ),
            }
        )
    return out


def build_meteo_station_collection(
    stations: list[dict], observed: dict[str, dict], data_version: str, geometry_source: str
) -> EntityCollection:
    """``EntityCollection`` of the meteorological stations (``observed_point``), with what the hourly data contain."""
    features = []
    for st in sorted(stations, key=lambda s: s["entity_id"]):
        attributes = {
            "in_hourly_data": st["entity_id"] in observed,
            "address": st["address"],
            "altitude_m": st["altitude_m"],
            "official_sensors": st["official_sensors"],
            "geometry_epsg": 4326,
            "geometry_note": "LONGITUD/LATITUD columns of the official CSV (decimal degrees).",
        }
        if st["entity_id"] in observed:
            attributes["observed_features"] = observed[st["entity_id"]]["features"]
            attributes["first_observation_utc"] = observed[st["entity_id"]]["first_utc"]
            attributes["last_observation_utc"] = observed[st["entity_id"]]["last_utc"]
        features.append(
            EntityFeature(
                type="Feature",
                id=st["entity_id"],
                geometry=PointGeometry(type="Point", coordinates=(st["lon"], st["lat"])),
                properties=EntityProperties(
                    entity_id=st["entity_id"],
                    domain=Domain.AIR,
                    name=st["name"],
                    geometry_support=GeometrySupport.OBSERVED_POINT,
                    geometry_source=geometry_source,
                    timezone=TIMEZONE,
                    attributes=attributes,
                ),
            )
        )
    return EntityCollection(type="FeatureCollection", domain=Domain.AIR, data_version=data_version, features=features)


# ---------------------------------------------------------------------------------------------- audit


def plausibility_counts(observations: Path) -> dict[str, int]:
    """Valid-coded readings outside the physical range of ``PLAUSIBLE_RANGE``, per feature (flagged, never altered)."""
    con = duckdb.connect()
    con.execute("SET memory_limit='1GB'")
    con.execute("SET threads=4")
    clauses = " OR ".join(
        f"(feature_name = '{name}' AND (value < {lo} OR value > {hi}))" for name, (lo, hi) in PLAUSIBLE_RANGE.items()
    )
    rows = con.execute(
        f"SELECT feature_name, count(*) FROM read_parquet('{observations}/**/*.parquet', hive_partitioning=true) "
        f"WHERE value IS NOT NULL AND ({clauses}) GROUP BY ALL ORDER BY ALL"
    ).fetchall()
    con.close()
    return {name: int(n) for name, n in rows}


def station_feature_coverage(coverage_rows: list, years: list[int]) -> dict:
    """``{station: {feature: {year: fraction of hours with a valid value}}}``."""
    expected = {y: _expected_hours(y) for y in years}
    out: dict = {}
    for entity, feature, year, _slots, valid, _first, _last in coverage_rows:
        out.setdefault(entity, {}).setdefault(feature, {})[int(year)] = round(valid / expected[int(year)], 4)
    return out


def build_limitations(stats: Stats, dst: dict, plausibility: dict, stations_note: str) -> list[str]:
    c = stats.counters
    notes = [
        "Values are Europe/Madrid local-time slots; 'Hnn' is read as the hour ending at nn:00, as in the air-quality "
        "files. The meteorological interpreter does not state the hour convention or the daylight-saving handling; it "
        f"was inferred from the data. {c['slots_dst_nonexistent']} source slots fall in the nonexistent spring hour "
        "and get no row; the repeated fall-back hour has no slot, so it is absent for every station.",
        f"DST transition days whose invalid slots differ from the expected spring H03: {dst or 'none'}.",
        "Validity: only code V is valid; other codes become value=null / invalid_observation, an empty slot "
        "no_observation. The number stored beside a non-V code is discarded.",
        "Hourly meteorology is a point measurement at the station: it is not an area value and must not be "
        "interpolated into surfaces; AT-011 associates each air station with the nearest meteorological stations.",
        stations_note,
        "Station coordinates are the current official ones (CSV updated 2023-05-03); no dated history of "
        "relocations is published.",
        "The 2025-and-later CSV is extended monthly by the portal; its content depends on the download date.",
        f"Valid-coded readings outside plausible physical ranges (flagged, not altered): {plausibility or 'none'}.",
        f"CSV vs TXT: {c['overlap_slots_cross_format']} slots exist in both formats of the monthly files (CSV kept); "
        f"{sum(stats.txt_only_slots.values())} exist only in the TXT.",
    ]
    return notes


def run(
    years: list[int],
    *,
    skip_download: bool = False,
    refresh: bool = False,
    datasets_root: str | None = None,
    out_dir: Path | None = None,
    doc_path: Path | None = DOC_PATH,
    fetch: Fetcher = http_fetch,
) -> dict:
    config = load_config()
    out_dir = out_dir or PROCESSED_DIR / "air" / "meteo"
    if skip_download:
        manifests = {
            SOURCE_ID: (read_manifest(RAW_DIR / SOURCE_ID), []),
            STATIONS_ID: (read_manifest(RAW_DIR / STATIONS_ID), []),
        }
    else:
        manifests = download(config, years, datasets_root, refresh, fetch)
    raw_meteo, raw_stations = RAW_DIR / SOURCE_ID, RAW_DIR / STATIONS_ID
    checksums = _verify_checksums(raw_meteo, SOURCE_ID) | _verify_checksums(raw_stations, STATIONS_ID)
    meteo_manifest = manifests[SOURCE_ID][0]

    out_dir.mkdir(parents=True, exist_ok=True)
    staging = out_dir / "_staging"
    if staging.exists():
        shutil.rmtree(staging)
    stats, inventory = convert(config, years, raw_meteo, staging)
    observations = out_dir / "observations"
    write_partitions(staging, observations)
    shutil.rmtree(staging)

    errors = validate_observations(observations / "**" / "*.parquet")
    if errors:
        raise SystemExit("canonical observations violate the contract: " + "; ".join(errors))

    summary = summarize_output(observations)
    plausibility = plausibility_counts(observations)
    coverage = station_feature_coverage(summary["coverage_rows"], years)
    observed: dict = {}
    for entity, feature, _y, _slots, valid, first, last in summary["coverage_rows"]:
        if valid:
            info = observed.setdefault(entity, {"features": set(), "first_utc": first, "last_utc": last})
            info["features"].add(feature)
            info["first_utc"], info["last_utc"] = min(info["first_utc"], first), max(info["last_utc"], last)
    for info in observed.values():
        info["features"] = sorted(info["features"])
        info["first_utc"], info["last_utc"] = info["first_utc"].isoformat(), info["last_utc"].isoformat()

    official = read_station_csv(raw_stations / STATIONS_FILE)
    official_ids = {s["entity_id"] for s in official}
    in_data_no_coords = sorted(set(observed) - official_ids)
    official_no_data = sorted(official_ids - set(observed))
    sensors_mismatch = {}
    for s in official:
        seen_features = set(observed.get(s["entity_id"], {}).get("features", []))
        if seen_features != set(s["official_sensors"]):
            sensors_mismatch[s["entity_id"]] = {
                "official_only": sorted(set(s["official_sensors"]) - seen_features),
                "data_only": sorted(seen_features - set(s["official_sensors"])),
            }
    geometry_source = config["stations"]["landing_url"]
    collection = build_meteo_station_collection(official, observed, config["data_version"], geometry_source)
    (out_dir / "stations.geojson").write_text(
        json.dumps(json.loads(collection.model_dump_json()), indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    c = stats.counters
    anomalies = dst_anomalies(stats.dst_days)
    stations_note = (
        f"{len(official)} official sensor locations; stations in the hourly data without official coordinates: "
        f"{in_data_no_coords or 'none'}; official stations without any valid hourly value: {official_no_data or 'none'}; "
        f"stations whose official sensor flags differ from the features actually observed: {sensors_mismatch or 'none'}."
    )
    valid_by_feature: dict[str, int] = {}
    for _e, feature, _y, _slots, valid, _first, _last in summary["coverage_rows"]:
        valid_by_feature[feature] = valid_by_feature.get(feature, 0) + int(valid)
    invalid = {f"flag:{k}": v for k, v in sorted(stats.by_flag.items()) if k != "V"}
    invalid |= {f"magnitude_excluded:{k}": v for k, v in sorted(stats.unknown_magnitude_slots.items())}
    lons = [s["lon"] for s in official]
    lats = [s["lat"] for s in official]
    report = QualityReport(
        source_id=SOURCE_ID,
        source_url=config["meteo"]["landing_url"],
        downloaded_at_utc=meteo_manifest.downloaded_at_utc,
        period_start=pd.Timestamp(summary["min_utc"]).tz_convert(TIMEZONE).date(),
        period_end=pd.Timestamp(summary["max_utc"]).tz_convert(TIMEZONE).date(),
        license=config["meteo"]["license"],
        input_sha256=checksums,
        raw_rows=c["canonical_rows"] + c["slots_dst_nonexistent"],
        valid_rows=c["valid_rows"],
        duplicate_rows=c["duplicate_slots_same_format"],
        uniqueness_key=["domain", "entity_id", "timestamp_utc", "feature_name", "source_id"],
        missing_by_column=summary["missing_by_column"],
        invalid_codes=invalid,
        outliers_flagged=sum(plausibility.values()),
        date_range_utc=(summary["min_utc"], summary["max_utc"]),
        geographic_coverage={
            "stations_in_hourly_data": len(observed),
            "stations_with_official_point": len(official),
            "stations_without_official_coordinates": in_data_no_coords,
            "bbox_lon_lat": [min(lons), min(lats), max(lons), max(lats)],
            "geometry_source": geometry_source,
            "geometry_support": "observed_point",
        },
        sampling_frequency="hourly; one slot per station x magnitude x hour; timestamp_utc = start of the hour",
        value_units={name: unit for name, unit in sorted(METEO_MAGNITUDES.values())},
        known_limitations=build_limitations(stats, anomalies, plausibility, stations_note),
    )
    (out_dir / "quality_report.json").write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")

    details = {
        "dst_anomalies": anomalies,
        "data_version": config["data_version"],
        "years": years,
        "downloaded_at_utc": meteo_manifest.downloaded_at_utc.isoformat(),
        "counters": {k: int(c[k]) for k in COUNTER_KEYS},
        "flags": dict(stats.by_flag),
        "unknown_magnitude_slots": dict(stats.unknown_magnitude_slots),
        "txt_only_slots": dict(sorted(stats.txt_only_slots.items())),
        "dst_days": dict(sorted(stats.dst_days.items())),
        "inventory": inventory,
        "by_reason": summary["by_reason"],
        "plausibility_flagged": plausibility,
        "valid_by_feature": valid_by_feature,
        "stations": {
            "official": len(official),
            "in_data_without_coordinates": in_data_no_coords,
            "official_without_data": official_no_data,
            "sensor_mismatch": sensors_mismatch,
        },
        "coverage_station_feature_year": coverage,
        "sha256": checksums,
        "date_range_utc": [summary["min_utc"].isoformat(), summary["max_utc"].isoformat()],
    }
    (out_dir / "ingest_details.json").write_text(
        json.dumps(details, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if doc_path is not None:
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        names = {f.id: f.properties.name or "" for f in collection.features}
        doc_path.write_text(render_markdown(details, report, names), encoding="utf-8")
    return details


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Ingest Madrid hourly meteorology into canonical Parquet.")
    parser.add_argument("--years", default="2019-2025", help="e.g. 2019-2025 or 2019,2021 (default: %(default)s)")
    parser.add_argument("--skip-download", action="store_true", help="use data/raw as is (must have manifests)")
    parser.add_argument("--download-only", action="store_true", help="only fetch the raw files and manifests")
    parser.add_argument("--refresh", action="store_true", help="re-download files even if the checksum matches")
    parser.add_argument(
        "--datasets-root",
        default=os.environ.get("ATLAS_DATASETS_ROOT", DEFAULT_DATASETS_ROOT),
        help="machine dataset root; data/raw/<source> is symlinked into it (default: %(default)s)",
    )
    parser.add_argument("--out-dir", type=Path, default=None, help="default: data/processed/air/meteo")
    parser.add_argument("--doc", type=Path, default=DOC_PATH, help="where to write the quality markdown")
    parser.add_argument("--no-doc", action="store_true")
    args = parser.parse_args(argv)
    years = parse_years(args.years)
    if args.download_only:
        for source_id, (manifest, fetched) in download(load_config(), years, args.datasets_root, args.refresh).items():
            print(f"{source_id}: {len(manifest.files)} files, fetched now: {fetched or 'none'}")
        return
    details = run(
        years,
        skip_download=args.skip_download,
        refresh=args.refresh,
        datasets_root=args.datasets_root,
        out_dir=args.out_dir,
        doc_path=None if args.no_doc else args.doc,
    )
    c = details["counters"]
    print(
        f"{c['canonical_rows']} canonical rows ({c['valid_rows']} valid), {details['date_range_utc']}", file=sys.stdout
    )


if __name__ == "__main__":
    main()
