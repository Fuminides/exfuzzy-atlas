"""Download the configured slice of the Water Quality Explorer API into the immutable raw cache."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from atlas.domains.water.client import CSV_PAGE_LIMIT, JSONLD_PAGE_LIMIT, WaterQualityClient
from atlas.domains.water.download import (
    Collection,
    RawStore,
    build_store,
    count_csv_rows,
    count_jsonld_members,
    fetch_collection,
)
from atlas.paths import DEFAULT_DATASETS_ROOT, RAW_DIR, REPO_ROOT

SOURCE_ID = "uk-water-quality"
CONFIG_PATH = REPO_ROOT / "configs" / "water" / "uk_water_quality.json"


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def ensure_raw_dir(datasets_root: str | None) -> Path:
    """``data/raw/uk-water-quality`` -> ``<datasets_root>/uk-water-quality`` (symlink created when absent)."""
    link = RAW_DIR / SOURCE_ID
    if link.exists() or link.is_symlink():
        return link
    link.parent.mkdir(parents=True, exist_ok=True)
    if datasets_root:
        target = Path(datasets_root) / SOURCE_ID
        target.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target, target_is_directory=True)
    else:
        link.mkdir()
    return link


def years_of(config: dict, years: list[int] | None) -> list[int]:
    s = config["slice"]
    return years or list(range(s["year_from"], s["year_to"] + 1))


def windows(year: int) -> list[tuple[str, str, str]]:
    """Date windows ``(label, dateFrom, dateTo)`` that cover one calendar year.

    ``dateTo`` is **exclusive** (``dateFrom=dateTo`` returns nothing) and a multi-point query must span strictly less
    than one year (``2015-01-01`` to ``2016-01-01`` is rejected with HTTP 400), so a year is two half-year windows.
    """
    return [(f"{year}-H1", f"{year}-01-01", f"{year}-07-01"), (f"{year}-H2", f"{year}-07-01", f"{year + 1}-01-01")]


def observation_params(config: dict, determinands: list[str], date_from: str, date_to: str) -> dict[str, str]:
    """Query of observations for ``[date_from, date_to)`` (see :func:`windows`)."""
    return {
        **config["slice"]["filters"],
        "determinand": ",".join(determinands),
        "dateFrom": date_from,
        "dateTo": date_to,
    }


def download(
    config: dict,
    raw_dir: Path,
    client: WaterQualityClient,
    years: list[int],
    *,
    refresh: bool = False,
    now: Callable[[], datetime] | None = None,
    log: Callable[[str], None] = lambda _: None,
) -> tuple[RawStore, dict[str, Collection]]:
    """Fetch sampling points, the unit codelist and two half-year queries per year. Returns store and collections."""
    store = build_store(raw_dir, config, period=(min(years), max(years)), now=now)
    slice_id = config["slice"]["id"]
    out: dict[str, Collection] = {}

    def run(key: str, **kwargs) -> None:
        out[key] = fetch_collection(store, client, refresh=refresh, **kwargs)
        c = out[key]
        log(f"{key}: {c.index['rows']} rows in {len(c.index['pages'])} pages ({'fetched' if c.fetched else 'cached'})")

    run(
        "sampling-point",
        rel_dir=f"sampling-point/{slice_id}",
        method="GET",
        path="sampling-point",
        params=config["slice"]["filters"],
        accept="application/ld+json",
        limit=JSONLD_PAGE_LIMIT,
        extension="jsonld",
        count_rows=count_jsonld_members,
    )
    run(
        "codelist/unit",
        rel_dir="codelists/unit",
        method="GET",
        path="codelist/unit",
        params={},
        accept="application/ld+json",
        limit=JSONLD_PAGE_LIMIT,
        extension="jsonld",
        count_rows=count_jsonld_members,
    )
    codes = [d["code"] for d in config["determinands"]]
    for year in years:
        for label, date_from, date_to in windows(year):
            run(
                f"observations/{label}",
                rel_dir=f"observations/{slice_id}/{label}",
                method="POST",
                path="data/observation",
                params=observation_params(config, codes, date_from, date_to),
                accept="text/csv",
                limit=CSV_PAGE_LIMIT,
                extension="csv",
                count_rows=count_csv_rows,
            )
    store.commit()
    return store, out


def default_raw_dir(datasets_root: str | None = None) -> Path:
    return ensure_raw_dir(datasets_root or os.environ.get("ATLAS_DATASETS_ROOT", DEFAULT_DATASETS_ROOT))


def fetch_counts(
    config: dict,
    store: RawStore,
    client: WaterQualityClient,
    years: list[int],
    *,
    refresh: bool = False,
    log: Callable[[str], None] = lambda _: None,
) -> dict:
    """``X-Total-Items`` per candidate determinand and half-year window (``limit=1``), for coverage profiling.

    Covers the ``candidate_determinands`` of the config (the selected ones are counted from the downloaded data), so the
    feasibility study can compare coverage without downloading them. Stored once as ``api_counts/<slice>.json``
    (immutable, in the manifest).
    """
    rel = f"api_counts/{config['slice']['id']}.json"
    if not refresh and store.is_intact(rel):
        return json.loads((store.raw_dir / rel).read_text(encoding="utf-8"))
    rows = []
    for code in [d["code"] for d in config["candidate_determinands"]]:
        for year in years:
            for label, date_from, date_to in windows(year):
                params = {**observation_params(config, [code], date_from, date_to), "limit": 1}
                url, response = client.request("POST", "data/observation", params, accept="text/csv")
                total = int(response.headers.get("x-total-items", 0))  # a 204 (no rows) carries no header
                rows.append({"determinand": code, "year": year, "window": label, "total_items": total, "url": url})
        log(f"counts {code}: {sum(r['total_items'] for r in rows if r['determinand'] == code)}")
    payload = {"slice": config["slice"]["id"], "counts": rows}
    store.write(rel, (json.dumps(payload, indent=1) + "\n").encode(), None)
    store.stamp(rel)
    store.commit()
    return payload
