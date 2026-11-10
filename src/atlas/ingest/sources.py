"""Idempotent download of raw sources plus their ``source_manifest.json``.

Raw files are immutable: a file whose sha256 already matches the manifest is never fetched again
(``refresh=True`` forces it, e.g. for the Madrid file "desde 2025", which the portal extends monthly).
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from datetime import date, datetime, timezone
from pathlib import Path

from atlas.contracts.models import Domain, SourceFile, SourceManifest

MANIFEST_NAME = "source_manifest.json"
USER_AGENT = "exfuzzy-atlas/0.1 (open-data ingestion; https://github.com/Fuminides/exfuzzy-atlas)"

Fetcher = Callable[[str], bytes]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def http_fetch(url: str, *, retries: int = 4, pause: float = 1.5) -> bytes:
    """Plain HTTP GET (the files are at most a few tens of MB).

    The municipal portal answers 403/429 when many files are requested in a row (the meteorological dataset has 144
    monthly files), so each request is followed by a short pause and throttled answers are retried with back-off.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:  # noqa: S310 - fixed https URLs from the config
                payload = response.read()
            time.sleep(pause)
            return payload
        except urllib.error.HTTPError as error:
            if error.code not in (403, 429, 502, 503) or attempt == retries:
                raise
            time.sleep(15 * 2**attempt)
    raise AssertionError("unreachable")


def read_manifest(raw_dir: Path) -> SourceManifest | None:
    path = raw_dir / MANIFEST_NAME
    return SourceManifest.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None


def write_manifest(raw_dir: Path, manifest: SourceManifest) -> None:
    text = json.dumps(json.loads(manifest.model_dump_json()), indent=2, ensure_ascii=False, sort_keys=True)
    (raw_dir / MANIFEST_NAME).write_text(text + "\n", encoding="utf-8")


def ensure_source(
    raw_dir: Path,
    *,
    source_id: str,
    domain: Domain,
    title: str,
    landing_url: str,
    license: str,
    attribution: str,
    files: Iterable[dict],
    period_start: date | None = None,
    period_end: date | None = None,
    notes: list[str] | None = None,
    fetch: Fetcher = http_fetch,
    refresh: bool = False,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> tuple[SourceManifest, list[str]]:
    """Download what is missing or changed, then (re)write the manifest if anything changed.

    Args:
        files: dicts with ``path`` (relative to ``raw_dir``) and ``url``.
        fetch: ``url -> bytes``; injectable so tests need no network.
        refresh: re-download every file even if its checksum matches.
        now: clock, injectable for tests.

    Returns:
        The manifest and the list of paths fetched in this call (empty when everything was up to date).
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    previous = read_manifest(raw_dir)
    known = {f.path: f for f in previous.files} if previous else {}
    entries: list[SourceFile] = []
    fetched: list[str] = []
    files = list(files)
    wanted = {spec["path"] for spec in files}
    stamps = {p: t for p, t in _download_stamps(previous).items() if p in wanted}
    for spec in files:
        path = raw_dir / spec["path"]
        entry = known.get(spec["path"])
        if not refresh and entry and path.exists() and entry.url == spec["url"] and sha256_file(path) == entry.sha256:
            entries.append(entry)
            continue
        payload = fetch(spec["url"])
        tmp = path.with_name(path.name + ".part")
        tmp.write_bytes(payload)
        tmp.chmod(0o444)  # raw files are immutable
        tmp.replace(path)
        entries.append(
            SourceFile(
                path=spec["path"], sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload), url=spec["url"]
            )
        )
        fetched.append(spec["path"])
        stamps[spec["path"]] = now().strftime("%Y-%m-%dT%H:%M:%SZ")
    if previous and not fetched:
        return previous, fetched
    manifest = SourceManifest(
        source_id=source_id,
        domain=domain,
        title=title,
        landing_url=landing_url,
        license=license,
        attribution=attribution,
        downloaded_at_utc=max(datetime.fromisoformat(s.replace("Z", "+00:00")) for s in stamps.values())
        if stamps
        else now(),
        period_start=period_start,
        period_end=period_end,
        files=entries,
        notes=[*(notes or []), *(f"downloaded {p} at {t}" for p, t in sorted(stamps.items()))],
    )
    write_manifest(raw_dir, manifest)
    return manifest, fetched


def _download_stamps(manifest: SourceManifest | None) -> dict[str, str]:
    if manifest is None:
        return {}
    out = {}
    for note in manifest.notes:
        if note.startswith("downloaded ") and " at " in note:
            path, _, stamp = note[len("downloaded ") :].rpartition(" at ")
            out[path] = stamp
    return out


def polite_fetch(*, pause: float = 0.5, retries: int = 5) -> Fetcher:
    """``http_fetch`` with a chosen pause that also retries network errors (resets, timeouts) with back-off.

    ``http_fetch`` retries throttling answers (403/429/502/503) only; hundreds of small files from a blob store also
    meet dropped connections, which should not abort a long, sequential download.
    """

    def fetch(url: str) -> bytes:
        for attempt in range(retries + 1):
            try:
                return http_fetch(url, retries=retries, pause=pause)
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if attempt == retries:
                    raise
                time.sleep(10 * 2**attempt)
        raise AssertionError("unreachable")

    return fetch


def ensure_source_in_batches(
    raw_dir: Path, files: Iterable[dict], *, batch: int = 50, **kwargs
) -> tuple[SourceManifest, list[str]]:
    """``ensure_source`` that rewrites the manifest every ``batch`` downloads.

    A download of hundreds of files that dies half-way then resumes from the last checkpoint instead of starting again
    (``ensure_source`` writes its manifest only at the end, and a file without a manifest entry is fetched again).
    Files that are already in the manifest (same URL, file present) go in every call, so a checkpoint never drops them;
    only the files still to fetch are added ``batch`` at a time. With ``refresh=True`` the manifest is removed first, so
    every file is fetched once.
    """
    files = list(files)
    if kwargs.get("refresh"):
        (raw_dir / MANIFEST_NAME).unlink(missing_ok=True)
        kwargs["refresh"] = False
    previous = read_manifest(raw_dir)
    known = {f.path: f for f in previous.files} if previous else {}

    def is_done(spec: dict) -> bool:
        entry = known.get(spec["path"])
        return entry is not None and entry.url == spec["url"] and (raw_dir / spec["path"]).exists()

    current = [spec for spec in files if is_done(spec)]
    pending = [spec for spec in files if not is_done(spec)]
    fetched: list[str] = []
    manifest = None
    for start in range(0, len(pending), batch):
        current = current + pending[start : start + batch]
        manifest, got = ensure_source(raw_dir, files=current, **kwargs)
        fetched += got
    if manifest is None:
        manifest, fetched = ensure_source(raw_dir, files=files, **kwargs)
    return manifest, fetched
