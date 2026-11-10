"""Download of the DWD Climate Data Center hourly station observations (AT-070).

One zip per station and product: ``historical/stundenwerte_<CODE>_<id>_<from>_<to>_hist.zip`` (versioned, quality
control finished, updated annually) and ``recent/stundenwerte_<CODE>_<id>_akt.zip`` (the last ~500 days, quality control
not finished). The directory listings are stored in the raw directory, so the file set that was used is part of the
inputs; a file is taken when

* it is a historical file whose time range overlaps the period, or
* it is a recent file of a station whose historical files do not reach the end of the period (it fills the gap).
"""

# ruff: noqa: E501  (SQL, URLs and prose templates)

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from atlas.contracts.models import Domain
from atlas.ingest.sources import Fetcher, ensure_source_in_batches, polite_fetch, read_manifest

LISTING_DIRS = ("historical", "recent")


def listing_path(product: dict, kind: str) -> str:
    return f"listings/{product['directory']}_{kind}.html"


def station_list_path(product: dict, kind: str) -> str:
    return f"stations/{product['code']}_Stundenwerte_Beschreibung_Stationen_{kind}.txt"


def parse_listing(html: str, code: str) -> tuple[list[tuple[str, str, str, str]], list[tuple[str, str]]]:
    """``(historical, recent)`` file names of a directory listing: ``(name, station, from, to)`` and ``(name, station)``."""
    hist = sorted(
        {(m.group(0), m.group(1), m.group(2), m.group(3))
         for m in re.finditer(rf"stundenwerte_{code}_(\d{{5}})_(\d{{8}})_(\d{{8}})_hist\.zip", html)}
    )
    recent = sorted({(m.group(0), m.group(1)) for m in re.finditer(rf"stundenwerte_{code}_(\d{{5}})_akt\.zip", html)})
    return hist, recent


def select_files(
    hist: list[tuple[str, str, str, str]], recent: list[tuple[str, str]], period_start: date, period_end: date
) -> list[tuple[str, str]]:
    """``(kind, name)`` of the files to download for one product, historical first."""
    start, end = period_start.strftime("%Y%m%d"), period_end.strftime("%Y%m%d")
    chosen = [("historical", name) for name, _, begin, last in hist if last >= start and begin <= end]
    reaches_end = {station for _, station, begin, last in hist if last >= end and begin <= end}
    chosen += [("recent", name) for name, station in recent if station not in reaches_end]
    return chosen


def download(config: dict, raw_dir: Path, *, fetch: Fetcher | None = None, refresh: bool = False):
    """Fetch listings, station lists, documents and every selected zip; (re)write the manifest."""
    fetch = fetch or polite_fetch(pause=0.4)
    meteo = config["meteo"]
    base = meteo["base_url"]
    start, end = date.fromisoformat(meteo["period_start"]), date.fromisoformat(meteo["period_end"])
    raw_dir.mkdir(parents=True, exist_ok=True)
    for sub in ("listings", "stations", "docs", "historical", "recent"):
        (raw_dir / sub).mkdir(exist_ok=True)

    side: list[dict] = list(meteo["documents"])
    for product in meteo["products"]:
        for kind in LISTING_DIRS:
            side.append({"path": listing_path(product, kind), "url": f"{base}/{product['directory']}/{kind}/", "role": "listing"})
            side.append(
                {
                    "path": station_list_path(product, kind),
                    "url": f"{base}/{product['directory']}/{kind}/{product['code']}_Stundenwerte_Beschreibung_Stationen.txt",
                    "role": "stations",
                }
            )
    common = dict(
        source_id=meteo["source_id"],
        domain=Domain.AIR,
        title=meteo["title"],
        landing_url=meteo["landing_url"],
        license=meteo["license"],
        attribution=meteo["attribution"],
        period_start=start,
        period_end=end,
        notes=[
            "Listings and station lists are the directory state at download time; files named in the listings of that "
            "day were selected (see dwd_download.select_files). Recent (akt) files are rolling and unverified; their "
            "sha256 is that of the download time.",
            "MESS_DATUM is UTC for the period used ('Stundenwerte in UTC' in each zip's Metadaten_Parameter file).",
        ],
        fetch=fetch,
        refresh=refresh,
    )
    # Pass 1: listings and station lists (needed to know which zips to take). Listings are volatile: only fetched when
    # absent (or on refresh), so that a re-run with the same raw directory selects the same files.
    previous = read_manifest(raw_dir)
    kept = [{"path": f.path, "url": f.url} for f in previous.files if f.path.startswith(("historical/", "recent/"))] if previous else []
    _, fetched_side = ensure_source_in_batches(raw_dir, [*side, *kept], batch=50, **common)  # `kept` zips stay in the manifest
    files: list[dict] = []
    for product in meteo["products"]:
        parsed = {}
        for kind in LISTING_DIRS:
            html = (raw_dir / listing_path(product, kind)).read_text(encoding="utf-8", errors="replace")
            parsed[kind] = parse_listing(html, product["code"])
        for kind, name in select_files(parsed["historical"][0], parsed["recent"][1], start, end):
            files.append({"path": f"{kind}/{name}", "url": f"{base}/{product['directory']}/{kind}/{name}", "role": "data", "product": product["key"]})
    manifest, fetched = ensure_source_in_batches(raw_dir, [*side, *files], batch=50, **common)
    return manifest, [*fetched_side, *fetched]
