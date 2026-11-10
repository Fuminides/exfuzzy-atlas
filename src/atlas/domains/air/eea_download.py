"""Download of the EEA Air Quality Download Service files for one country and pollutant (AT-070).

The API (``POST /ParquetFile/urls``) answers with the list of Parquet files (one per sampling point, pollutant and
dataset, whole history) for a request; the files themselves are plain blobs. Two datasets are needed:

* ``dataset=2`` (blob container ``airquality-p-e1a``): E1a, verified data reported by 30 September of the following year;
* ``dataset=1`` (container ``airquality-p``): E2a, up-to-date data, transmitted continuously, mostly unverified.

The resolved URL lists are stored in the raw directory next to the files, so the file set is part of the manifest.
"""

# ruff: noqa: E501  (SQL, URLs and prose templates)

from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from datetime import date
from pathlib import Path

from atlas.contracts.models import Domain
from atlas.ingest.sources import (
    USER_AGENT,
    Fetcher,
    SourceManifest,
    ensure_source_in_batches,
    polite_fetch,
)

URL_LIST_HEADER = "ParquetFileUrl"
BLOB_HOST = "https://eeadmz1batchservice02.blob.core.windows.net/"

PostJson = Callable[[str, dict], bytes]


def post_json(url: str, body: dict) -> bytes:
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=180) as response:  # noqa: S310 - fixed https URL from the config
        return response.read()


def url_request(config: dict, dataset: dict, years: list[int]) -> dict:
    """The ``/ParquetFile/urls`` request body (hourly aggregation; the files hold the whole history anyway)."""
    return {
        "countries": [config["country"]],
        "cities": [],
        "pollutants": [config["pollutant"]["notation"]],
        "dataset": dataset["api_dataset"],
        "source": "Api",
        "dateTimeStart": f"{min(years)}-01-01T00:00:00Z",
        "dateTimeEnd": f"{max(years)}-12-31T23:59:59Z",
        "aggregationType": "hour",
    }


def parse_url_list(payload: bytes) -> list[str]:
    """The API's CSV answer (BOM, header ``ParquetFileUrl``) as a sorted list of URLs."""
    lines = [line.strip() for line in payload.decode("utf-8-sig").splitlines() if line.strip()]
    if not lines or lines[0] != URL_LIST_HEADER:
        raise ValueError(f"unexpected answer from /ParquetFile/urls: {lines[:2]}")
    urls = sorted(set(lines[1:]))
    bad = [u for u in urls if not u.startswith(BLOB_HOST) or not u.endswith(".parquet")]
    if bad:
        raise ValueError(f"unexpected URLs in the answer: {bad[:3]}")
    return urls


def file_name(url: str) -> str:
    return url.rsplit("/", 1)[1]


def download(
    config: dict,
    years: list[int],
    raw_dir: Path,
    *,
    fetch: Fetcher | None = None,
    post: PostJson = post_json,
    refresh: bool = False,
) -> tuple[SourceManifest, list[str]]:
    """Resolve the URL lists, fetch every missing file and the station metadata; (re)write the manifest."""
    fetch = fetch or polite_fetch(pause=0.4)
    air = config["air"]
    raw_dir.mkdir(parents=True, exist_ok=True)
    files: list[dict] = []
    for dataset in air["datasets"]:
        list_path = raw_dir / f"urls_{dataset['key']}.txt"
        if refresh or not list_path.exists():
            list_path.write_bytes(post(f"{air['api_base']}/ParquetFile/urls", url_request(config, dataset, years)))
        urls = parse_url_list(list_path.read_bytes())
        files += [
            {"path": f"{dataset['key']}/{file_name(u)}", "url": u, "role": "data", "dataset": dataset["key"]}
            for u in urls
        ]
    meta = config["stations"]["files"]
    common = dict(
        source_id=air["source_id"],
        domain=Domain.AIR,
        title=air["title"],
        landing_url=air["landing_url"],
        license=air["license"],
        attribution=air["attribution"],
        period_start=date.fromisoformat(air["period_start"]),
        notes=[
            "E1a = airquality-p-e1a (API dataset 2), E2a = airquality-p (API dataset 1); one Parquet file per sampling "
            "point holds the whole history. File lists: urls_e1a.txt, urls_e2a.txt (answers of POST /ParquetFile/urls).",
            "Start/End are in the fixed offset UTC+01 (the station metadata Timezone column of every German sampling "
            "point is the vocabulary entry UTC+01), see docs/air/de_eea_air_quality.md.",
            "E2a files are extended continuously by the EEA; their sha256 is that of the download time.",
        ],
        fetch=fetch,
        refresh=refresh,
    )
    for spec in (*meta, *files):
        (raw_dir / spec["path"]).parent.mkdir(parents=True, exist_ok=True)
    # Metadata first, then the data files, with a checkpoint every 50 downloads.
    return ensure_source_in_batches(raw_dir, [*meta, *files], batch=50, **common)
