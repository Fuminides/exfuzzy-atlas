"""Idempotent download of the NYC TLC raw files plus ``source_manifest.json``.

Reuses the air pipeline's ``ensure_source`` (checksummed, read-only raw files). One extra wrinkle: the
``www.nyc.gov/assets`` PDFs answer HTTP 403 to scripted clients, so a file that cannot be fetched is looked up in
``<raw_dir>/manual/<name>`` (save it there from a browser) before giving up. The CloudFront data files are plain GETs.
"""

from __future__ import annotations

import urllib.error
from datetime import date, timedelta
from pathlib import Path

from atlas.contracts.models import Domain, SourceManifest
from atlas.ingest.sources import Fetcher, ensure_source, http_fetch

SOURCE_ID = "nyc-tlc"
MANUAL_DIR = "manual"


def with_manual_fallback(raw_dir: Path, fetch: Fetcher = http_fetch) -> Fetcher:
    """``fetch`` that falls back to ``raw_dir/manual/<basename>`` when the server refuses (HTTP 401/403/404)."""

    def fetcher(url: str) -> bytes:
        try:
            return fetch(url)
        except urllib.error.HTTPError as error:
            local = raw_dir / MANUAL_DIR / url.rsplit("/", 1)[-1]
            if error.code in (401, 403, 404) and local.exists():
                return local.read_bytes()
            raise

    return fetcher


def download(
    config: dict, months: list[str], raw_dir: Path, refresh: bool = False, fetch: Fetcher = http_fetch
) -> tuple[SourceManifest, list[str]]:
    """Fetch the monthly Parquet files requested plus lookup, shapefile and dictionary. Returns manifest, fetched."""
    spec = config["tlc"]
    wanted = [f for f in spec["files"] if f["role"] != "data" or f["month"] in months]
    missing = sorted(set(months) - {f["month"] for f in wanted if f["role"] == "data"})
    if missing:
        raise SystemExit(f"months not listed in configs/mobility/nyc_tlc.json: {missing}")
    first, last = min(months), max(months)
    end_year, end_month = int(last[:4]), int(last[5:])
    period_end = date(end_year + end_month // 12, end_month % 12 + 1, 1) - timedelta(days=1)  # inclusive
    return ensure_source(
        raw_dir,
        source_id=SOURCE_ID,
        domain=Domain.MOBILITY,
        title=spec["title"],
        landing_url=spec["landing_url"],
        license=spec["license"],
        attribution=spec["attribution"],
        files=[{"path": f["path"], "url": f["url"]} for f in wanted],
        period_start=date(int(first[:4]), int(first[5:]), 1),
        period_end=period_end,
        notes=[
            "Trip timestamps are naive America/New_York wall-clock times (no UTC offset in the Parquet files).",
            "Zone geometry: taxi_zones.zip is an ESRI shapefile in EPSG:2263 "
            "(NAD83 / New York Long Island, US survey feet).",
            "Terms: TLC publishes the data 'as is' and makes no representations as to its accuracy; no explicit "
            "licence is attached to the files (see the license field).",
        ],
        fetch=with_manual_fallback(raw_dir, fetch),
        refresh=refresh,
    )
