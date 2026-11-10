"""Water Quality Explorer ingestion CLI (AT-020).

    PYTHONPATH=src python -m atlas.domains.water.ingest

Steps: idempotent download of the raw API pages (+ ``source_manifest.json``) -> normalisation to canonical long rows
-> hive-partitioned Parquet ``year=/month=`` (UTC) -> contract validation -> sampling-point entities -> quality report.
"""

# ruff: noqa: E501  (prose templates and SQL)

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow.parquet as pq

from atlas.contracts.models import QualityReport
from atlas.contracts.observations import validate_observations
from atlas.domains.water import fetch
from atlas.domains.water.client import WaterQualityClient
from atlas.domains.water.download import RawStore, sha256_file
from atlas.domains.water.parse import (
    SOURCE_ID,
    Stats,
    build_entities,
    observations_frame,
    read_csv_pages,
    read_sampling_points,
    to_arrow,
    unit_symbols,
)
from atlas.paths import PROCESSED_DIR

# Heuristic plausibility bound, counted in ``outliers_flagged`` and never applied to the values: dissolved oxygen above
# 20 mg/l exceeds even the saturation of pure water at 0 C (14.6 mg/l) by far.
OUTLIER_RULES = {"dissolved_oxygen": 20.0}
UNIQUENESS_KEY = ["domain", "entity_id", "timestamp_utc", "feature_name", "source_id"]


def _pages(raw_dir: Path, collection) -> list[bytes]:
    return [(raw_dir / rel).read_bytes() for rel in collection.page_paths]


def data_version(config: dict, downloaded_at, years: list[int]) -> str:
    return f"uk-wq-{config['slice']['id']}-{min(years)}-{max(years)}-{downloaded_at:%Y%m%d}"


def verify_checksums(store: RawStore) -> dict[str, str]:
    """Every file in the manifest must still match its sha256 (raw files are immutable)."""
    bad = [p for p in store.files if sha256_file(store.raw_dir / p) != store.files[p].sha256]
    if bad:
        raise SystemExit(f"raw files do not match source_manifest.json: {bad}")
    return {f"{SOURCE_ID}/{p}": f.sha256 for p, f in sorted(store.files.items())}


def convert(config: dict, store: RawStore, collections: dict, years: list[int], version: str, staging: Path):
    """Raw CSV pages -> staged Parquet parts (one per year). Returns the stats and per-year reconciliation."""
    stats, per_year, observation_xy = Stats(), {}, {}
    symbols = unit_symbols(_pages(store.raw_dir, collections["codelist/unit"]))
    features = {d["code"]: d["feature_name"] for d in config["determinands"]}
    staging.mkdir(parents=True, exist_ok=True)
    for year in years:
        year_collections = [collections[f"observations/{label}"] for label, _, _ in fetch.windows(year)]
        raw = read_csv_pages([page for c in year_collections for page in _pages(store.raw_dir, c)])
        api_total = sum(c.total_items for c in year_collections)
        frame = observations_frame(
            raw, features=features, unit_symbols=symbols, data_version=version, stats=stats, outlier_rules=OUTLIER_RULES
        )
        points = raw.drop_duplicates("samplingPoint.notation")
        for notation, easting, northing in zip(
            points["samplingPoint.notation"],
            points["samplingPoint.easting"],
            points["samplingPoint.northing"],
            strict=True,
        ):
            if easting.strip() and northing.strip():  # blank when the point has no coordinates: never invented
                observation_xy[notation] = (float(easting), float(northing))
        per_year[year] = {
            "api_total_items": api_total,
            "csv_rows": len(raw),
            "canonical_rows": len(frame),
            "pages": sum(len(c.index["pages"]) for c in year_collections),
            "distinct_samples": int(frame["sample_id"].nunique()),
            "distinct_sample_determinand": int(frame[["sample_id", "feature_name"]].drop_duplicates().shape[0]),
        }
        if len(raw) != api_total:
            raise SystemExit(f"{year}: {len(raw)} CSV rows but the API announced {api_total}")
        if len(frame):
            pq.write_table(to_arrow(frame), staging / f"part-{year}.parquet", compression="zstd")
    return stats, per_year, observation_xy


def write_partitions(staging: Path, observations: Path, threads: int = 2) -> None:
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
    """Totals, null counts, date range, per-entity facts and sample reconciliation, from the written dataset."""
    con = duckdb.connect()
    con.execute("SET memory_limit='1GB'")
    con.execute("SET threads=2")
    con.execute("SET TimeZone='UTC'")
    con.execute(f"CREATE VIEW obs AS SELECT * FROM read_parquet('{observations}/**/*.parquet', hive_partitioning=true)")
    cols = [r[0] for r in con.execute("DESCRIBE obs").fetchall() if r[0] not in ("year", "month")]
    nulls = con.execute(
        "SELECT " + ", ".join(f"count(*) FILTER (WHERE {c} IS NULL)" for c in cols) + " FROM obs"
    ).fetchone()
    total, lo, hi = con.execute("SELECT count(*), min(timestamp_utc), max(timestamp_utc) FROM obs").fetchone()
    entities = {
        row[0]: {
            "n_observations": int(row[1]),
            "n_samples": int(row[2]),
            "first_utc": row[3].isoformat(),
            "last_utc": row[4].isoformat(),
        }
        for row in con.execute(
            "SELECT entity_id, count(*), count(DISTINCT sample_id), min(timestamp_utc), max(timestamp_utc) FROM obs GROUP BY 1"
        ).fetchall()
    }
    pairs, distinct_pairs, samples = con.execute(
        "SELECT count(*), count(DISTINCT (sample_id, feature_name)), count(DISTINCT sample_id) FROM obs"
    ).fetchone()
    reasons = dict(con.execute("SELECT coalesce(missing_reason, 'valid'), count(*) FROM obs GROUP BY 1").fetchall())
    units = dict(
        con.execute("SELECT feature_name || ' [' || unit || ']', count(*) FROM obs GROUP BY 1 ORDER BY 1").fetchall()
    )
    local_dates = con.execute(
        "SELECT min(CAST(timezone('Europe/London', timestamp_utc) AS DATE)), max(CAST(timezone('Europe/London', timestamp_utc) AS DATE)) FROM obs"
    ).fetchone()
    con.close()
    return {
        "rows": total,
        "min_utc": lo,
        "max_utc": hi,
        "local_dates": local_dates,
        "missing_by_column": dict(zip(cols, map(int, nulls), strict=True)),
        "entities": entities,
        "rows_vs_distinct_sample_determinand": [pairs, distinct_pairs],
        "distinct_samples": samples,
        "by_reason": {k: int(v) for k, v in sorted(reasons.items())},
        "units": {k: int(v) for k, v in units.items()},
    }


def limitations(config: dict, stats: Stats, per_feature_censoring: dict, outside: dict) -> list[str]:
    c = stats.counters
    s = config["slice"]
    return [
        f"Slice, not the archive: Environment Agency {s['description']} Years {s['year_from']}-{s['year_to']}; "
        "the API caps multi-point queries below one year and dateTo is exclusive, so each year is two half-year queries.",
        "Sample times are naive Europe/London wall-clock times (the API sends no UTC offset); evidence that they are local "
        "rather than UTC: the hour-of-day distribution of samples is the same in winter and summer (docs/water/profile.md). "
        f"DST policy: autumn repeated hour read as the first occurrence ({c['dst_ambiguous_rows']} rows), spring gap read with "
        f"the pre-transition offset ({c['dst_nonexistent_rows']} rows). No sample time is available for a sample taken "
        "at an unknown time of day (none found in this slice).",
        "Sampling is irregular and campaign-driven (compliance, national monitoring, investigations): there is no regular "
        "series, no hourly data, and not every determinand is measured in every sample.",
        "Values below/above a detection limit are published as '<x' / '>x': value holds the limit x and censoring is "
        "'left'/'right'; x is not an estimate of the true concentration. "
        + "; ".join(f"{k}: {v['censored']}/{v['rows']} censored" for k, v in per_feature_censoring.items())
        + ". Two detection limits coexist for each censored determinand throughout the period (see docs/water/profile.md), so "
        "censored values are not directly comparable with each other.",
        "The API publishes no validity or QA flag per observation: validity_flag is null for every row and no row is "
        "excluded on quality grounds. Corrections are applied by the monthly archive refresh, so a later snapshot may differ.",
        f"{c['non_river_sample_material']} rows are samples whose material is not 'RIVER / RUNNING SURFACE WATER' although taken at "
        "river sampling points (effluent, mine water, sea water, 'any water'); they are kept and identified by sample_material.",
        f"{c['outliers_flagged']} dissolved-oxygen values above {OUTLIER_RULES['dissolved_oxygen']} mg/l are counted in outliers_flagged "
        "and kept as published.",
        f"Duplicates on the contract key (entity, time, feature): {c['duplicate_key_rows_dropped']} (the row with the smallest "
        "observation_id would be kept).",
        "Coordinates are the published BNG (EPSG:27700, 1 m) values converted to WGS84 with a Helmert transformation "
        "(at most 1.5 m from the WGS84 that the API itself returns in GeoJSON, checked on all 772 points of the slice); sampling "
        "points can be moved or re-coded over time and the API gives only the current position.",
        "Placeholder coordinates: "
        + (
            "; ".join(
                f"{k} has published BNG {v['bng'][0]:.0f},{v['bng'][1]:.0f} (outside the dataset extent, so geometry is null)"
                for k, v in outside.items()
            )
            or "none"
        )
        + ". The name of such a point says 'SEE SAMPLE SPECIFIC GRID REF', but the sample / sampling resources of the API carry "
        "no geometry (checked for one such point), so no per-sample location is available.",
        "Entities are sampling points, not river reaches: nothing here supports colouring a stretch of river.",
    ]


def acquire(
    *,
    years: list[int] | None = None,
    skip_download: bool = False,
    refresh: bool = False,
    counts: bool = False,
    datasets_root: str | None = None,
    client: WaterQualityClient | None = None,
    log=print,
):
    """Download (or just open) the raw cache. Returns ``(config, years, store, collections, client)``."""
    config = fetch.load_config()
    years = fetch.years_of(config, years)
    raw_dir = fetch.default_raw_dir(datasets_root)
    if skip_download:
        client = WaterQualityClient(transport=_no_network)  # reads the cache only: any request would stop the run
    client = client or WaterQualityClient()
    store, collections = fetch.download(config, raw_dir, client, years, refresh=refresh, log=log)
    if counts:
        fetch.fetch_counts(config, store, client, years, refresh=refresh, log=log)
    return config, years, store, collections, client


def run(
    *,
    years: list[int] | None = None,
    skip_download: bool = False,
    refresh: bool = False,
    counts: bool = False,
    datasets_root: str | None = None,
    out_dir: Path | None = None,
    client: WaterQualityClient | None = None,
    log=print,
) -> dict:
    config, years, store, collections, client = acquire(
        years=years,
        skip_download=skip_download,
        refresh=refresh,
        counts=counts,
        datasets_root=datasets_root,
        client=client,
        log=log,
    )
    raw_dir = store.raw_dir
    checksums = verify_checksums(store)
    # the data snapshot is the observation downloads (not the optional coverage counts)
    manifest_time = max(
        pd.Timestamp(t) for p, t in store.stamps.items() if p.startswith("observations/")
    ).to_pydatetime()
    version = data_version(config, manifest_time, years)

    out_dir = out_dir or PROCESSED_DIR / "water"
    out_dir.mkdir(parents=True, exist_ok=True)
    staging = out_dir / "_staging"
    if staging.exists():
        shutil.rmtree(staging)
    stats, per_year, observation_xy = convert(config, store, collections, years, version, staging)
    observations = out_dir / "observations"
    write_partitions(staging, observations)
    shutil.rmtree(staging)

    errors = validate_observations(observations / "**" / "*.parquet")
    if errors:
        raise SystemExit("canonical observations violate the contract: " + "; ".join(errors))
    summary = summarize_output(observations)
    c = stats.counters
    if summary["rows"] != c["canonical_rows"]:
        raise SystemExit(f"Parquet has {summary['rows']} rows, normalisation produced {c['canonical_rows']}")
    pairs, distinct_pairs = summary["rows_vs_distinct_sample_determinand"]
    if pairs != distinct_pairs:
        raise SystemExit(f"{pairs - distinct_pairs} (sample, determinand) pairs appear more than once")

    points = read_sampling_points(_pages(raw_dir, collections["sampling-point"]))
    collection, reconciliation = build_entities(
        points,
        summary["entities"],
        observation_xy,
        data_version=version,
        api_base=config["api_base"],
        extent=config["dataset_extent_wgs84"],
    )
    (out_dir / "entities.geojson").write_text(
        json.dumps(json.loads(collection.model_dump_json()), indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    per_feature = _censoring_by_feature(observations)
    located = [f for f in collection.features if f.geometry is not None and f.properties.attributes["n_observations"]]
    lons = [f.geometry.coordinates[0] for f in located]
    lats = [f.geometry.coordinates[1] for f in located]
    api_total = sum(v["api_total_items"] for v in per_year.values())
    report = QualityReport(
        source_id=SOURCE_ID,
        source_url=config["landing_url"],
        downloaded_at_utc=manifest_time,
        period_start=summary["local_dates"][0],
        period_end=summary["local_dates"][1],
        license=f"{config['license']}; attribution: {config['attribution']}",
        input_sha256=checksums,
        raw_rows=c["raw_rows"],
        valid_rows=c["valid_rows"],
        duplicate_rows=c["duplicate_key_rows_dropped"],
        uniqueness_key=UNIQUENESS_KEY,
        missing_by_column=summary["missing_by_column"],
        invalid_codes={
            **{f"censoring:{k}": v for k, v in sorted(stats.qualifiers.items())},
            **{f"missing_reason:{k}": v for k, v in summary["by_reason"].items() if k != "valid"},
        },
        outliers_flagged=c["outliers_flagged"],
        date_range_utc=(summary["min_utc"], summary["max_utc"]),
        geographic_coverage={
            "sampling_points_in_listing": reconciliation["points_in_listing"],
            "sampling_points_with_observations": reconciliation["points_with_observations"],
            "points_without_coordinates": reconciliation["listing_without_coordinates"],
            "points_with_placeholder_coordinates": reconciliation["coordinates_outside_extent"],
            "bbox_lon_lat": [min(lons), min(lats), max(lons), max(lats)] if located else None,
            "geometry_source": f"{config['api_base']}/sampling-point",
            "geometry_support": "observed_point",
            "slice": config["slice"]["filters"],
        },
        sampling_frequency="irregular, campaign-driven; one row per sample x determinand; timestamp_utc = sample time",
        value_units={
            k: v for k, v in sorted({u.split(" [")[0]: u.split(" [")[1].rstrip("]") for u in summary["units"]}.items())
        },
        known_limitations=limitations(config, stats, per_feature, reconciliation["coordinates_outside_extent"]),
    )
    (out_dir / "quality_report.json").write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")

    details = {
        "data_version": version,
        "years": years,
        "downloaded_at_utc": manifest_time.isoformat(),
        "api_total_items_all_years": api_total,
        "counters": dict(sorted(c.items())),
        "per_year": per_year,
        "distinct_samples": summary["distinct_samples"],
        "by_reason": summary["by_reason"],
        "units": summary["units"],
        "unit_labels": dict(stats.unit_labels),
        "dst_examples": stats.dst_examples,
        "dropped_duplicates": stats.dropped_duplicates,
        "entities": reconciliation,
        "censoring_by_feature": per_feature,
        "http": {
            "requests": client.stats.requests,
            "retries": client.stats.retries,
            "bytes": client.stats.bytes_received,
        },
    }
    (out_dir / "ingest_details.json").write_text(
        json.dumps(details, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )
    return details


def _censoring_by_feature(observations: Path) -> dict:
    con = duckdb.connect()
    con.execute(f"CREATE VIEW obs AS SELECT * FROM read_parquet('{observations}/**/*.parquet', hive_partitioning=true)")
    rows = con.execute(
        "SELECT feature_name, count(*), count(*) FILTER (WHERE censoring IS NOT NULL) FROM obs GROUP BY 1 ORDER BY 1"
    ).fetchall()
    con.close()
    return {name: {"rows": int(n), "censored": int(k)} for name, n, k in rows}


def _no_network(method, url, headers, timeout):
    raise SystemExit(f"--skip-download: the cache is incomplete, would have requested {method} {url}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Ingest the configured Water Quality Explorer slice into canonical Parquet."
    )
    parser.add_argument("--years", default=None, help="e.g. 2015-2025 or 2019,2021 (default: the config period)")
    parser.add_argument("--skip-download", action="store_true", help="use the raw cache as is (no HTTP request at all)")
    parser.add_argument("--download-only", action="store_true", help="fetch the raw pages and manifest, then stop")
    parser.add_argument(
        "--counts", action="store_true", help="also fetch X-Total-Items per candidate determinand and year"
    )
    parser.add_argument("--refresh", action="store_true", help="re-download everything (a newer archive snapshot)")
    parser.add_argument(
        "--datasets-root",
        default=os.environ.get("ATLAS_DATASETS_ROOT", fetch.DEFAULT_DATASETS_ROOT),
        help="machine dataset root; data/raw/uk-water-quality is symlinked into it (default: %(default)s)",
    )
    parser.add_argument("--out-dir", type=Path, default=None, help="default: data/processed/water")
    args = parser.parse_args(argv)
    years = parse_years(args.years) if args.years else None
    if args.download_only:
        _, _, _, _, client = acquire(
            years=years, refresh=args.refresh, counts=args.counts, datasets_root=args.datasets_root
        )
        print(
            f"HTTP requests: {client.stats.requests} (retries {client.stats.retries}), {client.stats.bytes_received:,} bytes"
        )
        return
    details = run(
        years=years,
        skip_download=args.skip_download,
        refresh=args.refresh,
        counts=args.counts,
        datasets_root=args.datasets_root,
        out_dir=args.out_dir,
    )
    c = details["counters"]
    print(f"{c['canonical_rows']} canonical rows ({c['valid_rows']} with value), {details['distinct_samples']} samples")
    print(f"HTTP requests in this run: {details['http']['requests']}")


def parse_years(text: str) -> list[int]:
    """``2015-2025`` -> [2015..2025]; ``2019,2021`` -> [2019, 2021]."""
    years: set[int] = set()
    for part in text.split(","):
        lo, _, hi = part.strip().partition("-")
        years.update(range(int(lo), int(hi or lo) + 1))
    return sorted(years)


if __name__ == "__main__":
    main()
