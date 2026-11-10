"""NYC TLC Yellow Taxi ingestion CLI (AT-030).

    PYTHONPATH=src python -m atlas.domains.mobility.ingest --months 2025-01..2025-03

Steps: idempotent download of the raw files (+ manifest) -> official taxi zones as ``EntityCollection`` (full and
simplified) -> one pass per month with DuckDB (clean, localize, count pickups per zone and UTC hour, zero-fill) ->
hive-partitioned Parquet ``year=/month=`` (local file month) -> contract validation -> quality report and dataset card.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import shutil
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from atlas.contracts.models import QualityReport
from atlas.contracts.observations import validate_observations
from atlas.domains.mobility import aggregate
from atlas.domains.mobility.download import SOURCE_ID as RAW_SOURCE_ID
from atlas.domains.mobility.download import download
from atlas.domains.mobility.profile import summarize_output
from atlas.domains.mobility.report import build_limitations, render_markdown
from atlas.domains.mobility.zones import build_zone_collections, read_lookup, write_collection, zone_ids_with_geometry
from atlas.ingest.sources import MANIFEST_NAME, Fetcher, http_fetch, read_manifest, sha256_file
from atlas.paths import DEFAULT_DATASETS_ROOT, PROCESSED_DIR, RAW_DIR, REPO_ROOT

CONFIG_PATH = REPO_ROOT / "configs" / "mobility" / "nyc_tlc.json"
DOC_PATH = REPO_ROOT / "docs" / "mobility" / "nyc_tlc_yellow_dataset_card.md"


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def parse_months(text: str) -> list[str]:
    """``2025-01..2025-03`` -> three months; ``2025-01,2025-03`` -> those two."""
    months: list[str] = []
    for part in text.split(","):
        lo, _, hi = part.strip().partition("..")
        year, month = int(lo[:4]), int(lo[5:7])
        end = (int((hi or lo)[:4]), int((hi or lo)[5:7]))
        while (year, month) <= end:
            months.append(f"{year:04d}-{month:02d}")
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return sorted(set(months))


def ensure_raw_dir(datasets_root: str | None) -> Path:
    """``data/raw/nyc-tlc`` -> ``<datasets_root>/nyc-tlc`` (symlink created when absent)."""
    link = RAW_DIR / RAW_SOURCE_ID
    if link.exists() or link.is_symlink():
        return link
    link.parent.mkdir(parents=True, exist_ok=True)
    if datasets_root:
        target = Path(datasets_root) / RAW_SOURCE_ID
        target.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target, target_is_directory=True)
    else:
        link.mkdir()
    return link


def _current_rss_mb() -> float:
    with open("/proc/self/statm") as handle:
        return int(handle.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 2**20


def _peak_rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # KiB on Linux


def run(
    months: list[str],
    *,
    skip_download: bool = False,
    refresh: bool = False,
    datasets_root: str | None = None,
    out_dir: Path | None = None,
    doc_path: Path | None = DOC_PATH,
    fetch: Fetcher = http_fetch,
    memory_limit: str = "1500MB",
    threads: int = 4,
    config: dict | None = None,
) -> dict:
    config = config or load_config()
    raw_dir = ensure_raw_dir(datasets_root)
    out_dir = out_dir or PROCESSED_DIR / "mobility"
    version = config["data_version"]
    if skip_download:
        manifest = read_manifest(raw_dir)
        if manifest is None:
            raise SystemExit(f"{raw_dir / MANIFEST_NAME} is missing: run without --skip-download first")
    else:
        manifest, _ = download(config, months, raw_dir, refresh, fetch)
    wanted = {f["path"] for f in config["tlc"]["files"] if f["role"] != "data" or f["month"] in months}
    entries = {f.path: f for f in manifest.files if f.path in wanted}
    if wanted - set(entries):
        raise SystemExit(f"manifest lacks files: {sorted(wanted - set(entries))}")
    for entry in entries.values():
        if sha256_file(raw_dir / entry.path) != entry.sha256:
            raise SystemExit(f"{entry.path} does not match its manifest sha256 (raw files are immutable)")
    checksums = {f"{RAW_SOURCE_ID}/{p}": e.sha256 for p, e in sorted(entries.items())}

    out_dir.mkdir(parents=True, exist_ok=True)
    marks = {"start_rss_mb": round(_current_rss_mb(), 1)}
    t0 = time.perf_counter()
    full, simplified, zones_report = build_zone_collections(
        raw_dir, version, config["tlc"]["geometry_source"]
    )
    zones_report["files"] = {
        "taxi_zones.geojson": write_collection(full, out_dir / "taxi_zones.geojson"),
        "taxi_zones_simplified.geojson": write_collection(simplified, out_dir / "taxi_zones_simplified.geojson"),
    }
    zone_ids = zone_ids_with_geometry(full)
    lookup_ids = sorted(read_lookup(raw_dir / "taxi_zone_lookup.csv"))
    marks["zones_seconds"] = round(time.perf_counter() - t0, 2)

    observations = out_dir / "observations"
    if observations.exists():
        shutil.rmtree(observations)
    con = aggregate.connect(memory_limit, threads, temp_dir=out_dir / "_duckdb_tmp")
    covered_utc = aggregate.covered_range_utc(months)
    covered_local = (aggregate.month_bounds(min(months))[0], aggregate.month_bounds(max(months))[1])
    results, perf = [], []
    for month in months:
        started = time.perf_counter()
        result = aggregate.aggregate_month(
            con,
            raw_dir / f"yellow_tripdata_{month}.parquet",
            month,
            zone_ids,
            lookup_ids,
            observations / f"year={month[:4]}" / f"month={int(month[5:])}" / "part-0.parquet",
            data_version=version,
            covered_local=covered_local,
            max_trip_hours=config["max_trip_hours"],
        )
        results.append(result)
        perf.append(
            {
                "month": month,
                "seconds": round(time.perf_counter() - started, 2),
                "raw_rows": result.raw_rows,
                "rss_mb_after": round(_current_rss_mb(), 1),
                "peak_rss_mb_so_far": round(_peak_rss_mb(), 1),
            }
        )
    con.close()
    shutil.rmtree(out_dir / "_duckdb_tmp", ignore_errors=True)

    errors = validate_observations(observations / "**" / "*.parquet")
    if errors:
        raise SystemExit("canonical observations violate the contract: " + "; ".join(errors))

    summary = summarize_output(observations, zone_names={int(f.id): f.properties.name for f in full.features})
    raw_rows = sum(r.raw_rows for r in results)
    valid_rows = sum(r.kept_rows for r in results)
    filtered = {k: sum(r.filtered[k] for r in results) for k in aggregate.REASONS}
    if raw_rows - sum(filtered.values()) != valid_rows or summary["total_pickups"] != valid_rows:
        raise SystemExit(
            f"counts do not reconcile: raw {raw_rows} - filtered {sum(filtered.values())} != "
            f"valid {valid_rows} (aggregated {summary['total_pickups']})"
        )
    invalid = {f"filtered:{k}": v for k, v in filtered.items() if v}
    invalid |= {"ambiguous_local_hour_zone_hours_null": summary["null_rows"]}
    limitations = build_limitations(config, zones_report, summary, filtered)
    lons = zones_report["bbox_lon_lat"]
    first_day = date.fromisoformat(f"{min(months)}-01")
    last_day = aggregate.month_bounds(max(months))[1].date() - timedelta(days=1)
    stamps = manifest.downloaded_at_utc
    report = QualityReport(
        source_id=aggregate.SOURCE_ID,
        source_url=config["tlc"]["landing_url"],
        downloaded_at_utc=stamps,
        period_start=first_day,
        period_end=last_day,
        license=config["tlc"]["license"],
        input_sha256=checksums,
        raw_rows=raw_rows,
        valid_rows=valid_rows,
        duplicate_rows=sum(r.duplicate_rows or 0 for r in results),
        uniqueness_key=["domain", "entity_id", "timestamp_utc", "feature_name", "source_id"],
        missing_by_column=summary["missing_by_column"],
        invalid_codes=invalid,
        outliers_flagged=0,
        date_range_utc=(summary["min_utc"], summary["max_utc"]),
        geographic_coverage={
            "zones_with_polygon": zones_report["entities_with_geometry"],
            "special_ids_without_polygon": zones_report["entities_without_geometry"],
            "zones_with_zero_pickups_in_period": summary["zones_without_pickups"],
            "bbox_lon_lat": lons,
            "geometry_source": config["tlc"]["geometry_source"],
            "geometry_support": "observed_polygon",
            "source_crs": zones_report["source_crs"],
        },
        sampling_frequency="hourly; one row per taxi zone x UTC hour for every hour of the covered period "
        "(zero-filled); timestamp_utc = start of the hour",
        value_units={aggregate.FEATURE: aggregate.UNIT},
        known_limitations=limitations,
    )
    (out_dir / "quality_report.json").write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")

    marks["total_seconds"] = round(time.perf_counter() - t0, 2)
    marks["peak_rss_mb"] = round(_peak_rss_mb(), 1)
    details = {
        "data_version": version,
        "months": months,
        "downloaded_at_utc": stamps.isoformat(),
        "covered_period_utc": [covered_utc[0].isoformat(), covered_utc[1].isoformat()],
        "max_trip_hours": config["max_trip_hours"],
        "memory_limit": memory_limit,
        "threads": threads,
        "counters": {
            "raw_rows": raw_rows,
            "valid_rows": valid_rows,
            "filtered_total": raw_rows - valid_rows,
            "filtered": filtered,
            "duplicate_rows_kept": report.duplicate_rows,
        },
        "months_detail": [
            {k: v for k, v in vars(r).items() if k != "schema"} | {"schema_columns": len(r.schema)} for r in results
        ],
        "schemas": {r.month: r.schema for r in results},
        "perf": {"per_month": perf, **marks},
        "summary": summary,
        "zones": zones_report,
        "sha256": checksums,
        "output_files": sorted(str(p.relative_to(out_dir)) for p in observations.rglob("*.parquet")),
    }
    (out_dir / "ingest_details.json").write_text(
        json.dumps(details, indent=1, ensure_ascii=False, default=_json_default) + "\n", encoding="utf-8"
    )
    if doc_path is not None:
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(render_markdown(details, report), encoding="utf-8")
    return details


def _json_default(value):
    if isinstance(value, datetime) and value.tzinfo:
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, datetime | date):
        return value.isoformat()
    raise TypeError(f"not JSON serializable: {type(value)}")


def main(argv: list[str] | None = None) -> None:
    config = load_config()
    parser = argparse.ArgumentParser(description="Ingest NYC TLC Yellow Taxi pickups per zone and hour.")
    parser.add_argument(
        "--months", default="..".join(config["default_months"]), help="e.g. 2025-01..2025-03 (default: %(default)s)"
    )
    parser.add_argument("--skip-download", action="store_true", help="use data/raw as is (must have a manifest)")
    parser.add_argument("--download-only", action="store_true", help="only fetch the raw files and the manifest")
    parser.add_argument("--refresh", action="store_true", help="re-download files even if the checksum matches")
    parser.add_argument(
        "--datasets-root",
        default=os.environ.get("ATLAS_DATASETS_ROOT", DEFAULT_DATASETS_ROOT),
        help="machine dataset root; data/raw/nyc-tlc is symlinked into it (default: %(default)s)",
    )
    parser.add_argument("--out-dir", type=Path, default=None, help="default: data/processed/mobility")
    parser.add_argument("--doc", type=Path, default=DOC_PATH, help="where to write the dataset card")
    parser.add_argument("--no-doc", action="store_true")
    parser.add_argument("--memory-limit", default="1500MB", help="DuckDB memory_limit (default: %(default)s)")
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args(argv)
    months = parse_months(args.months)
    if args.download_only:
        manifest, fetched = download(config, months, ensure_raw_dir(args.datasets_root), args.refresh)
        print(f"{RAW_SOURCE_ID}: {len(manifest.files)} files, fetched now: {fetched or 'none'}")
        return
    details = run(
        months,
        skip_download=args.skip_download,
        refresh=args.refresh,
        datasets_root=args.datasets_root,
        out_dir=args.out_dir,
        doc_path=None if args.no_doc else args.doc,
        memory_limit=args.memory_limit,
        threads=args.threads,
        config=config,
    )
    c = details["counters"]
    perf = details["perf"]
    print(
        f"{c['raw_rows']:,} trips -> {c['valid_rows']:,} counted pickups ({c['filtered_total']:,} filtered); "
        f"{details['summary']['rows']:,} zone-hour rows; {perf['total_seconds']} s, peak RSS {perf['peak_rss_mb']} MB",
        file=sys.stdout,
    )


if __name__ == "__main__":
    main()
