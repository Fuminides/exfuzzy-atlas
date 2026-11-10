"""Madrid air-quality ingestion CLI (AT-010).

    PYTHONPATH=src python -m atlas.domains.air.ingest --years 2019-2025

Steps: idempotent download of the raw files (+ manifests) -> wide-to-long conversion streamed month by month
-> hive-partitioned Parquet ``year=/month=`` (UTC) -> contract validation -> station entities -> quality report.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import zipfile
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow.parquet as pq

from atlas.contracts.models import Domain, QualityReport
from atlas.contracts.observations import validate_observations
from atlas.domains.air.parse import (
    COUNTER_KEYS,
    MAGNITUDES,
    SOURCE_ID,
    TIMEZONE,
    Stats,
    iter_zip_units,
    read_csv_wide,
    wide_to_long,
)
from atlas.domains.air.report import build_limitations, render_markdown
from atlas.domains.air.stations import build_station_collection
from atlas.ingest.sources import MANIFEST_NAME, Fetcher, ensure_source, http_fetch, read_manifest, sha256_file
from atlas.paths import DEFAULT_DATASETS_ROOT, PROCESSED_DIR, RAW_DIR, REPO_ROOT

CONFIG_PATH = REPO_ROOT / "configs" / "air" / "madrid_air.json"
STATIONS_ID = "madrid-air-stations"
DOC_PATH = REPO_ROOT / "docs" / "air" / "madrid_air_quality.md"
CHUNK_ROWS = 20_000


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def parse_years(text: str) -> list[int]:
    """``2019-2025`` -> [2019..2025]; ``2019,2021`` -> [2019, 2021]."""
    years: set[int] = set()
    for part in text.split(","):
        lo, _, hi = part.strip().partition("-")
        years.update(range(int(lo), int(hi or lo) + 1))
    return sorted(years)


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


def download(config: dict, years: list[int], datasets_root: str | None, refresh: bool, fetch: Fetcher = http_fetch):
    """Fetch the raw files for the requested years and the station files. Returns both manifests."""
    manifests = {}
    air = config["air"]
    wanted = [f for f in air["files"] if f["role"] != "data" or set(f["years"]) & set(years)]
    manifests[SOURCE_ID] = ensure_source(
        ensure_raw_dir(SOURCE_ID, datasets_root),
        source_id=SOURCE_ID,
        domain=Domain.AIR,
        title=air["title"],
        landing_url=air["landing_url"],
        license=air["license"],
        attribution=air["attribution"],
        files=wanted,
        period_start=date.fromisoformat(air["period_start"]),
        notes=[
            "Hourly values are Europe/Madrid local time; slot Hnn is the hour ending at nn:00 "
            "(see interprete_ficheros_calidad_aire_horario.pdf, section 7).",
            "The 'desde 2025' CSV is extended monthly by the portal; its sha256 is that of the download time.",
        ],
        fetch=fetch,
        refresh=refresh,
    )
    st = config["stations"]
    manifests[STATIONS_ID] = ensure_source(
        ensure_raw_dir(STATIONS_ID, datasets_root),
        source_id=STATIONS_ID,
        domain=Domain.AIR,
        title=st["title"],
        landing_url=st["landing_url"],
        license=st["license"],
        attribution=st["attribution"],
        files=st["files"],
        notes=[
            f"Geometry: {st['geometry_source']} (query outSR=4326, f=geojson); the layer is stored in EPSG:25830.",
            "estaciones-control-aire.csv (datos.madrid.es) is used only to cross-check coordinates and for metadata.",
        ],
        fetch=fetch,
        refresh=refresh,
    )
    return manifests


def _verify_checksums(raw_dir: Path, source_id: str) -> dict[str, str]:
    manifest = read_manifest(raw_dir)
    if manifest is None:
        raise SystemExit(f"{raw_dir / MANIFEST_NAME} is missing: run without --skip-download first")
    for entry in manifest.files:
        if sha256_file(raw_dir / entry.path) != entry.sha256:
            raise SystemExit(f"{source_id}/{entry.path} does not match its manifest sha256 (raw files are immutable)")
    return {f"{source_id}/{f.path}": f.sha256 for f in manifest.files}


def _expected_hours(year: int) -> int:
    start = pd.Timestamp(year=year, month=1, day=1, tz=TIMEZONE)
    return int((pd.Timestamp(year=year + 1, month=1, day=1, tz=TIMEZONE) - start) / pd.Timedelta(hours=1))


def convert(config: dict, years: list[int], raw_air: Path, staging: Path) -> tuple[Stats, dict]:
    """Stream every input file to staged Parquet parts. Returns the stats and a per-file inventory."""
    stats, seen, inventory, part = Stats(), {}, {}, 0
    version = config["data_version"]
    staging.mkdir(parents=True, exist_ok=True)

    def emit(wide: pd.DataFrame, name: str) -> None:
        nonlocal part
        wide = wide[pd.to_numeric(wide["year"], errors="coerce").isin(years)]
        info = inventory[name]
        for fmt, n in wide["fmt"].value_counts().items():
            info["rows_in_selected_years"][fmt] = info["rows_in_selected_years"].get(fmt, 0) + int(n)
        if wide.empty:
            return
        table, _ = wide_to_long(wide, data_version=version, seen=seen, stats=stats)
        pq.write_table(table, staging / f"part-{part:05d}.parquet", compression="zstd")
        part += 1

    for spec in config["air"]["files"]:
        if spec["role"] != "data" or not set(spec["years"]) & set(years):
            continue
        path = raw_air / spec["path"]
        inventory[spec["path"]] = {"layout": "", "members": {}, "rows_in_selected_years": {}}
        if path.suffix == ".zip":
            with zipfile.ZipFile(path) as archive:
                n_xml = sum(1 for name in archive.namelist() if name.lower().endswith(".xml"))
            if n_xml:
                inventory[spec["path"]]["members"]["xml (ignored)"] = n_xml
            for _, frames in iter_zip_units(path):
                for frame in frames:
                    inventory[spec["path"]]["members"][frame["fmt"].iat[0]] = (
                        inventory[spec["path"]]["members"].get(frame["fmt"].iat[0], 0) + 1
                    )
                emit(pd.concat(frames, ignore_index=True), spec["path"])
            inventory[spec["path"]]["layout"] = "zip: monthly csv (';', header) + txt (',', no header)"
        else:
            inventory[spec["path"]]["layout"] = "single csv (';', quoted, UTF-8 BOM, header), several years"
            for chunk in read_csv_wide(path.read_bytes(), chunksize=CHUNK_ROWS):
                emit(chunk, spec["path"])
    return stats, inventory


def write_partitions(staging: Path, observations: Path, threads: int = 4) -> None:
    if observations.exists():
        shutil.rmtree(observations)
    con = duckdb.connect()
    con.execute("SET memory_limit='1GB'")
    con.execute(f"SET threads={threads}")
    con.execute("SET TimeZone='UTC'")
    con.execute(
        f"COPY (SELECT *, year(timestamp_utc) AS year, month(timestamp_utc) AS month "
        f"FROM read_parquet('{staging}/*.parquet') ORDER BY entity_id, feature_name, timestamp_utc) "
        f"TO '{observations}' (FORMAT PARQUET, COMPRESSION ZSTD, PARTITION_BY (year, month))"
    )
    con.close()


def summarize_output(observations: Path) -> dict:
    """Coverage, null counts and date range from the written dataset (bounded-memory DuckDB)."""
    con = duckdb.connect()
    con.execute("SET memory_limit='2GB'")
    con.execute("SET threads=4")
    con.execute("SET TimeZone='UTC'")
    con.execute(f"CREATE VIEW obs AS SELECT * FROM read_parquet('{observations}/**/*.parquet', hive_partitioning=true)")
    cols = [r[0] for r in con.execute("DESCRIBE obs").fetchall() if r[0] not in ("year", "month")]
    nulls = con.execute(
        "SELECT " + ", ".join(f"count(*) FILTER (WHERE {c} IS NULL)" for c in cols) + " FROM obs"
    ).fetchone()
    total, lo, hi = con.execute("SELECT count(*), min(timestamp_utc), max(timestamp_utc) FROM obs").fetchone()
    coverage = con.execute(
        "SELECT entity_id, feature_name, year(timezone('Europe/Madrid', timestamp_utc)) AS y, "
        "count(*) AS slots, count(value) AS valid, min(timestamp_utc) FILTER (WHERE value IS NOT NULL), "
        "max(timestamp_utc) FILTER (WHERE value IS NOT NULL) FROM obs GROUP BY ALL ORDER BY ALL"
    ).fetchall()
    reasons = dict(con.execute("SELECT coalesce(missing_reason, 'valid'), count(*) FROM obs GROUP BY ALL").fetchall())
    con.close()
    return {
        "rows": total,
        "min_utc": lo,
        "max_utc": hi,
        "missing_by_column": dict(zip(cols, map(int, nulls), strict=True)),
        "coverage_rows": coverage,
        "by_reason": {k: int(v) for k, v in sorted(reasons.items())},
    }


def _coverage_tables(rows: list, years: list[int]) -> tuple[dict, dict, dict]:
    """``{feature: {entity: {year: fraction}}}``, observed-station info, and per-feature totals."""
    expected = {y: _expected_hours(y) for y in years}
    tables: dict = {}
    observed: dict = {}
    for entity, feature, year, slots, valid, first, last in rows:
        tables.setdefault(feature, {}).setdefault(entity, {})[int(year)] = {
            "valid_hours": int(valid),
            "slots": int(slots),
            "fraction": round(valid / expected[int(year)], 4),
        }
        if valid:
            info = observed.setdefault(entity, {"features": set(), "first_utc": first, "last_utc": last})
            info["features"].add(feature)
            info["first_utc"], info["last_utc"] = min(info["first_utc"], first), max(info["last_utc"], last)
    for info in observed.values():
        info["features"] = sorted(info["features"])
        info["first_utc"], info["last_utc"] = info["first_utc"].isoformat(), info["last_utc"].isoformat()
    return tables, observed, expected


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
    out_dir = out_dir or PROCESSED_DIR / "air"
    if skip_download:
        manifests = {
            SOURCE_ID: (read_manifest(RAW_DIR / SOURCE_ID), []),
            STATIONS_ID: (read_manifest(RAW_DIR / STATIONS_ID), []),
        }
    else:
        manifests = download(config, years, datasets_root, refresh, fetch)
    raw_air, raw_stations = RAW_DIR / SOURCE_ID, RAW_DIR / STATIONS_ID
    checksums = _verify_checksums(raw_air, SOURCE_ID) | _verify_checksums(raw_stations, STATIONS_ID)
    air_manifest = manifests[SOURCE_ID][0]

    out_dir.mkdir(parents=True, exist_ok=True)
    staging = out_dir / "_staging"
    if staging.exists():
        shutil.rmtree(staging)
    stats, inventory = convert(config, years, raw_air, staging)
    observations = out_dir / "observations"
    write_partitions(staging, observations)
    shutil.rmtree(staging)

    errors = validate_observations(observations / "**" / "*.parquet")
    if errors:
        raise SystemExit("canonical observations violate the contract: " + "; ".join(errors))

    summary = summarize_output(observations)
    coverage, observed, expected = _coverage_tables(summary["coverage_rows"], years)
    collection, reconciliation = build_station_collection(
        raw_stations, observed, config["data_version"], config["stations"]["geometry_source"]
    )
    reconciliation["years_without_no2"] = {
        e: [y for y in years if y not in coverage["no2"].get(e, {})]
        for e in sorted(set(reconciliation["official_station_ids"]) | set(observed))
        if any(y not in coverage["no2"].get(e, {}) for y in years)
    }
    (out_dir / "stations.geojson").write_text(
        json.dumps(json.loads(collection.model_dump_json()), indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    c = stats.counters
    invalid = {f"flag:{k}": v for k, v in sorted(stats.by_flag.items()) if k != "V"}
    invalid |= {f"magnitude_excluded:{k}": v for k, v in sorted(stats.unknown_magnitude_slots.items())}
    limitations = build_limitations(stats, reconciliation, dst_anomalies(stats.dst_days))
    covered = [e for e in collection.features if e.geometry is not None]
    lons = [e.geometry.coordinates[0] for e in covered]
    lats = [e.geometry.coordinates[1] for e in covered]
    report = QualityReport(
        source_id=SOURCE_ID,
        source_url=config["air"]["landing_url"],
        downloaded_at_utc=air_manifest.downloaded_at_utc,
        period_start=pd.Timestamp(summary["min_utc"]).tz_convert(TIMEZONE).date(),
        period_end=pd.Timestamp(summary["max_utc"]).tz_convert(TIMEZONE).date(),
        license=config["air"]["license"],
        input_sha256=checksums,
        raw_rows=c["canonical_rows"] + c["slots_dst_nonexistent"],
        valid_rows=c["valid_rows"],
        duplicate_rows=c["duplicate_slots_same_format"],
        uniqueness_key=["domain", "entity_id", "timestamp_utc", "feature_name", "source_id"],
        missing_by_column=summary["missing_by_column"],
        invalid_codes=invalid,
        outliers_flagged=c["valid_negative_rows"],
        date_range_utc=(summary["min_utc"], summary["max_utc"]),
        geographic_coverage={
            "stations_in_hourly_data": len(observed),
            "stations_with_official_point": len(covered),
            "stations_without_official_coordinates": reconciliation["in_data_without_official_coordinates"],
            "bbox_lon_lat": [min(lons), min(lats), max(lons), max(lats)],
            "geometry_source": config["stations"]["geometry_source"],
            "geometry_support": "observed_point",
        },
        sampling_frequency="hourly; one slot per station x magnitude x hour; timestamp_utc = start of the hour",
        value_units={name: unit for name, unit in sorted(MAGNITUDES.values())},
        known_limitations=limitations,
    )
    (out_dir / "quality_report.json").write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")

    details = {
        "dst_anomalies": dst_anomalies(stats.dst_days),
        "data_version": config["data_version"],
        "years": years,
        "downloaded_at_utc": air_manifest.downloaded_at_utc.isoformat(),
        "counters": {k: int(c[k]) for k in COUNTER_KEYS},
        "flags": dict(stats.by_flag),
        "unknown_magnitude_slots": dict(stats.unknown_magnitude_slots),
        "txt_only_slots": dict(sorted(stats.txt_only_slots.items())),
        "dst_days": dict(sorted(stats.dst_days.items())),
        "inventory": inventory,
        "by_reason": summary["by_reason"],
        "expected_hours": expected,
        "coverage": coverage,
        "stations": reconciliation,
        "sha256": checksums,
        "date_range_utc": [summary["min_utc"].isoformat(), summary["max_utc"].isoformat()],
    }
    (out_dir / "ingest_details.json").write_text(
        json.dumps(details, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if doc_path is not None:
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(render_markdown(details, report, collection), encoding="utf-8")
    return details


def dst_anomalies(dst_days: dict) -> dict[str, list[str]]:
    """Slots invalid for *every* row of a transition day, other than the expected nonexistent ``H03`` of spring days."""
    out = {}
    for day, info in sorted(dst_days.items()):
        spring = pd.Timestamp(day).month < 6
        slots = [f"H{i + 1:02d}" for i, n in enumerate(info["invalid_per_slot"]) if info["rows"] and n == info["rows"]]
        extra = [slot for slot in slots if not (spring and slot == "H03")]
        if extra or (spring and "H03" not in slots):
            out[day] = slots
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Ingest Madrid hourly air quality into canonical Parquet.")
    parser.add_argument("--years", default="2019-2025", help="e.g. 2019-2025 or 2019,2021 (default: %(default)s)")
    parser.add_argument("--skip-download", action="store_true", help="use data/raw as is (must have manifests)")
    parser.add_argument("--download-only", action="store_true", help="only fetch the raw files and manifests")
    parser.add_argument("--refresh", action="store_true", help="re-download files even if the checksum matches")
    parser.add_argument(
        "--datasets-root",
        default=os.environ.get("ATLAS_DATASETS_ROOT", DEFAULT_DATASETS_ROOT),
        help="machine dataset root; data/raw/<source> is symlinked into it (default: %(default)s)",
    )
    parser.add_argument("--out-dir", type=Path, default=None, help="default: data/processed/air")
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
