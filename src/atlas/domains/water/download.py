"""Immutable, idempotent raw cache for paginated API collections, plus ``source_manifest.json``.

Layout under ``<raw_dir>`` (``data/raw/uk-water-quality`` -> the machine dataset root)::

    source_manifest.json                       SourceManifest, sha256 of every file below
    sampling-point/<slice>/page-0000.jsonld    one file per API page, byte-for-byte what the server sent
    observations/<slice>/<year>/page-0000.csv
    observations/<slice>/<year>/request.json   index: query, per-page row counts, X-Total-Items, fetch time

Rules: a collection enters the manifest only after every page arrived and the row counts reconcile with
``X-Total-Items``; a collection whose index and pages match the manifest is never fetched again (zero requests)
unless ``refresh=True``; files are written read-only through a temporary name. The archive is refreshed monthly
by the Environment Agency, so ``refresh`` is how you take a newer snapshot on purpose.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from atlas.contracts.models import Domain, SourceFile, SourceManifest
from atlas.domains.water.client import ApiError, WaterQualityClient

MANIFEST_NAME = "source_manifest.json"
INDEX_NAME = "request.json"


class InconsistentPaging(ApiError):
    """Row counts do not add up to ``X-Total-Items``, or the total moved while paging (archive refreshed?)."""


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def count_csv_rows(body: bytes) -> int:
    """Data rows of a CSV page (header excluded). An empty body has none."""
    if not body.strip():
        return 0
    return max(0, sum(1 for _ in csv.reader(io.StringIO(body.decode("utf-8-sig")))) - 1)


def count_jsonld_members(body: bytes) -> int:
    return len(json.loads(body)["member"]) if body.strip() else 0


class RawStore:
    """Files of one source directory and their manifest."""

    def __init__(self, raw_dir: Path, meta: Mapping[str, object], now: Callable[[], datetime] | None = None):
        self.raw_dir = raw_dir
        self.meta = dict(meta)
        self.now = now or (lambda: datetime.now(timezone.utc))
        raw_dir.mkdir(parents=True, exist_ok=True)
        path = raw_dir / MANIFEST_NAME
        previous = SourceManifest.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None
        self.files: dict[str, SourceFile] = {f.path: f for f in previous.files} if previous else {}
        self.stamps: dict[str, str] = _stamps(previous)
        self.meta_notes: list[str] = []
        self.dirty = False

    def is_intact(self, rel: str) -> bool:
        """Listed in the manifest, present on disk and still matching its sha256."""
        entry = self.files.get(rel)
        path = self.raw_dir / rel
        return bool(
            entry and path.is_file() and path.stat().st_size == entry.bytes and sha256_file(path) == entry.sha256
        )

    def write(self, rel: str, payload: bytes, url: str | None) -> None:
        """Store ``payload`` read-only (atomic replace) and stage its manifest entry."""
        path = self.raw_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        if tmp.exists():
            tmp.chmod(0o644)
        tmp.write_bytes(payload)
        tmp.chmod(0o444)
        tmp.replace(path)
        self.files[rel] = SourceFile(path=rel, sha256=sha256_bytes(payload), bytes=len(payload), url=url)
        self.dirty = True

    def drop(self, rel: str) -> None:
        self.files.pop(rel, None)
        self.stamps.pop(rel, None)
        path = self.raw_dir / rel
        if path.exists():
            path.chmod(0o644)
            path.unlink()
        self.dirty = True

    def stamp(self, rel: str) -> None:
        self.stamps[rel] = self.now().strftime("%Y-%m-%dT%H:%M:%SZ")

    def commit(self) -> SourceManifest | None:
        """Write the manifest if anything changed (or if it does not exist yet)."""
        if not self.dirty and (self.raw_dir / MANIFEST_NAME).exists():
            return None
        manifest = SourceManifest(
            **self.meta,
            downloaded_at_utc=max(
                (datetime.fromisoformat(s.replace("Z", "+00:00")) for s in self.stamps.values()), default=self.now()
            ),
            files=sorted(self.files.values(), key=lambda f: f.path),
            notes=[*self.meta_notes, *(f"downloaded {p} at {t}" for p, t in sorted(self.stamps.items()))],
        )
        text = json.dumps(json.loads(manifest.model_dump_json()), indent=2, ensure_ascii=False, sort_keys=True)
        (self.raw_dir / MANIFEST_NAME).write_text(text + "\n", encoding="utf-8")
        self.dirty = False
        return manifest


@dataclass(frozen=True)
class Collection:
    """The outcome of :func:`fetch_collection`."""

    rel_dir: str
    index: dict
    fetched: bool  # False when the cache satisfied it with no request

    @property
    def total_items(self) -> int:
        return self.index["total_items"]

    @property
    def page_paths(self) -> list[str]:
        return [f"{self.rel_dir}/{p['file']}" for p in self.index["pages"]]


def fetch_collection(
    store: RawStore,
    client: WaterQualityClient,
    *,
    rel_dir: str,
    method: str,
    path: str,
    params: Mapping[str, object],
    accept: str,
    limit: int,
    extension: str,
    count_rows: Callable[[bytes], int],
    refresh: bool = False,
) -> Collection:
    """Fetch every page of one query into ``rel_dir`` unless the cache already holds it intact."""
    index_rel = f"{rel_dir}/{INDEX_NAME}"
    if not refresh and store.is_intact(index_rel):
        index = json.loads((store.raw_dir / index_rel).read_text(encoding="utf-8"))
        if index["query"] == _query(method, path, params, accept, limit) and all(
            store.is_intact(f"{rel_dir}/{p['file']}") for p in index["pages"]
        ):
            return Collection(rel_dir, index, fetched=False)

    pages, totals, payloads = [], set(), []
    for page in client.pages(method, path, params, accept=accept, limit=limit):
        totals.add(page.total_items)
        if not page.body.strip():
            continue  # 204, or a page past the end: nothing to store
        name = f"page-{len(pages):04d}.{extension}"
        payloads.append((f"{rel_dir}/{name}", page.body, page.url))
        pages.append(
            {
                "file": name,
                "skip": page.skip,
                "rows": count_rows(page.body),
                "total_items": page.total_items,
                "url": page.url,
            }
        )
    totals.discard(None)
    rows = sum(p["rows"] for p in pages)
    expected = totals.pop() if len(totals) == 1 else (0 if not totals and not pages else None)
    if expected is None or rows != expected:
        raise InconsistentPaging(
            f"{rel_dir}: {rows} rows in {len(pages)} pages but X-Total-Items says "
            f"{sorted(map(str, totals)) or expected}; "
            "the archive may have refreshed while paging - run again"
        )
    written = [rel for rel, _, _ in payloads]
    for rel, body, url in payloads:  # nothing reaches the cache until the whole collection reconciled
        store.write(rel, body, url)
    stale = [p for p in store.files if p.startswith(rel_dir + "/") and p not in written and p != index_rel]
    for old in stale:
        store.drop(old)
    index = {
        "query": _query(method, path, params, accept, limit),
        "total_items": expected,
        "rows": rows,
        "pages": pages,
        "fetched_at_utc": store.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    store.write(index_rel, (json.dumps(index, indent=1, sort_keys=True) + "\n").encode(), None)
    store.stamp(index_rel)
    store.commit()
    return Collection(rel_dir, index, fetched=True)


def _query(method: str, path: str, params: Mapping[str, object], accept: str, limit: int) -> dict:
    return {
        "method": method,
        "path": path,
        "params": {k: str(v) for k, v in params.items()},
        "accept": accept,
        "limit": limit,
    }


def _stamps(manifest: SourceManifest | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for note in manifest.notes if manifest else []:
        if note.startswith("downloaded ") and " at " in note:
            path, _, stamp = note[len("downloaded ") :].rpartition(" at ")
            out[path] = stamp
    return out


def build_store(
    raw_dir: Path, config: Mapping, *, period: tuple[int, int], now: Callable[[], datetime] | None = None
) -> RawStore:
    """A :class:`RawStore` carrying the static manifest fields from the config."""
    store = RawStore(
        raw_dir,
        {
            "source_id": config["source_id"],
            "domain": Domain.WATER,
            "title": config["title"],
            "landing_url": config["landing_url"],
            "license": config["license"],
            "attribution": config["attribution"],
            "period_start": date(period[0], 1, 1),
            "period_end": date(period[1], 12, 31),
        },
        now,
    )
    store.meta_notes = list(config["manifest_notes"])
    return store
