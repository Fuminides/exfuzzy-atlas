"""Conventions of the static export (docs/static_export.md): names, windows, gzip, allow-list, redaction, privacy."""

from __future__ import annotations

import gzip
import json
import math
import os
import re
import socket
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from atlas.contracts import models as m

FORMAT_VERSION = 1
EXPORTER = f"atlas.services.static {FORMAT_VERSION}"
TAUS = [round(0.05 * k, 2) for k in range(1, 21)]
STORIES_TAU = 0.5
STORIES_LIMIT = 10
WHATIF_STEPS = 41
MAX_WINDOW_DAYS = 366
GRID_TOL = 1e-9
SERIES_MAX_POINTS = 2_000
MISSING_REASONS = [r.value for r in m.MissingReason]
WINDOW_KINDS = ("day", "week", "month", "year")
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
DAY = timedelta(days=1)
# Per-territory periods of the export (issue times, inclusive): Germany is exported for winter only (user decision,
# 2026-11-10). Override per task, model or territory with ``--period KEY=FROM,TO`` (``full`` = the whole coverage).
DEFAULT_PERIODS = {"germany": ("2025-01-01T00:00:00Z", "2025-03-31T23:00:00Z")}

# ---------------------------------------------------------------------------------------------- allow-list
FORBIDDEN_SUFFIXES = (".pkl", ".pickle", ".parquet", ".joblib", ".npy", ".npz", ".pt", ".pth", ".onnx", ".h5", ".bin")
FORBIDDEN_NAMES = ("SHA256SUMS", "publish.json", "run_manifest.json", "metrics.json")


class ForbiddenFile(ValueError):
    """The exporter was asked to write something that is not on the allow-list (a model file, a pickle, …)."""


def check_id(value: str) -> str:
    if not SAFE_ID.match(value):
        raise ValueError(f"{value!r} is not usable in a file name (allowed: A-Z a-z 0-9 . _ -)")
    return value


def check_allowed(rel: str) -> None:
    """``rel`` is a path under ``data/<export_id>/`` or ``golden/<export_id>/``: ``*.json.gz``, ``manifest.json``."""
    name = rel.rsplit("/", 1)[-1]
    low = name.lower()
    if name in FORBIDDEN_NAMES or low.endswith(FORBIDDEN_SUFFIXES):
        raise ForbiddenFile(f"{rel}: model files and pickles are never exported")
    if rel.startswith("/") or ".." in rel.split("/"):
        raise ForbiddenFile(f"{rel}: must be a relative path inside the export")
    if not (low.endswith(".json.gz") or rel == "manifest.json"):
        raise ForbiddenFile(f"{rel}: not on the allow-list (*.json.gz, manifest.json)")


# ---------------------------------------------------------------------------------------------- time
def iso(value: datetime) -> str:
    """The API's spelling of an instant: ``YYYY-MM-DDTHH:MM:SSZ`` (UTC)."""
    value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%SZ") if value.microsecond == 0 else value.isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def day_key(value: datetime | date) -> str:
    return (value.astimezone(timezone.utc) if isinstance(value, datetime) else value).strftime("%Y-%m-%d")


def utc_midnight(day: str | date) -> datetime:
    d = date.fromisoformat(day) if isinstance(day, str) else day
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def window_of(kind: str, at: datetime) -> tuple[datetime, datetime]:
    """The UTC day, ISO week (Monday start), month or year containing ``at`` (``lib/windows.ts``: ``windowFor``)."""
    at = at.astimezone(timezone.utc)
    start = utc_midnight(at.date())
    if kind == "day":
        return start, start + DAY
    if kind == "week":
        monday = start - timedelta(days=at.weekday())
        return monday, monday + 7 * DAY
    if kind == "month":
        first = start.replace(day=1)
        nxt = (first + 32 * DAY).replace(day=1)
        return first, nxt
    if kind == "year":
        return start.replace(month=1, day=1), start.replace(year=at.year + 1, month=1, day=1)
    raise ValueError(f"unknown window kind {kind}")


def close(a: float, b: float) -> bool:
    """The tolerance of every numeric match in the static layer (what-if grid values, tau): relative 1e-9 with an
    absolute floor of 1e-9 for values near 0, i.e. ``|a - b| <= 1e-9 * max(1, |a|, |b|)``."""
    return abs(a - b) <= GRID_TOL * max(1.0, abs(a), abs(b))


def coverage_window(first: datetime, last: datetime, step_hours: int) -> tuple[datetime, datetime]:
    return first, last + timedelta(hours=step_hours)


def coverage_fits(first: datetime, last: datetime, step_hours: int) -> bool:
    lo, hi = coverage_window(first, last, step_hours)
    return (hi - lo) <= timedelta(days=MAX_WINDOW_DAYS)


# ---------------------------------------------------------------------------------------------- json + gzip
def clean(value):
    """Python/numpy containers -> JSON-able, NaN/inf -> None (a missing value is never a number)."""
    import numpy as np

    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


def dumps(obj) -> bytes:
    return json.dumps(clean(obj), separators=(",", ":"), allow_nan=False, ensure_ascii=False).encode("utf-8")


def gz(data: bytes) -> bytes:
    """gzip with a fixed header (mtime 0), so the same data gives the same bytes."""
    import io

    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9, mtime=0, filename="") as fh:
        fh.write(data)
    return buf.getvalue()


def unzip(data: bytes) -> bytes:
    """Decompress only when the gzip magic is there (a server may already have done it)."""
    return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data


# ---------------------------------------------------------------------------------------------- redaction + privacy
PATH_RE = re.compile(r"(?:/home|/Users|/mnt|/root|/tmp|/media)/[^\s\"',;)]+|[A-Za-z]:\\[^\s\"',;)]+")


def _short(match: re.Match) -> str:
    parts = [p for p in re.split(r"[\\/]", match.group(0)) if p]
    return ".../" + "/".join(parts[-2:])


def redact(value):
    """Strings with an absolute local path keep only their last two components behind ``.../`` (docs section 11)."""
    if isinstance(value, str):
        return PATH_RE.sub(_short, value)
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


EXTRA_HOSTS_ENV = "ATLAS_PRIVACY_HOSTS"  # comma list of more host names that must not appear (kept out of the tree)
EMAIL_RE = rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"


PRIVACY_CHECKS = ["absolute local paths", "the user's home directory", "this machine's host name",
                  "configured host names", "a university domain", "a personal mail domain", "e-mail addresses"]


def privacy_patterns() -> list[str]:
    """The literal strings a published file must not contain, plus the e-mail shape."""
    host = socket.gethostname()
    known = [h.strip() for h in os.environ.get(EXTRA_HOSTS_ENV, "").split(",") if h.strip()]
    literals = ["/home/", "/Users/", "/mnt/", "/root/", "C:\\", "essex.ac.uk", "@gmail", str(Path.home()), host,
                *known]
    return sorted({p for p in literals if p and p != "/"})


def privacy_regex() -> re.Pattern:
    literal = b"|".join(re.escape(p.encode()) for p in privacy_patterns())
    return re.compile(b"(?i:" + literal + b")|" + EMAIL_RE)


def scan_privacy(root: Path) -> tuple[int, list[str]]:
    """Decompress and scan every file under ``root``; returns (files scanned, violations ``"path: match"``)."""
    pattern, n, bad = privacy_regex(), 0, []
    for path in sorted(p for p in Path(root).rglob("*") if p.is_file()):
        data = unzip(path.read_bytes()) if path.name.endswith(".gz") else path.read_bytes()
        n += 1
        hit = pattern.search(data)
        if hit:
            bad.append(f"{path.relative_to(root).as_posix()}: {hit.group(0).decode(errors='replace')}")
    return n, bad


def walk_files(root: Path) -> Iterator[Path]:
    for p in sorted(Path(root).rglob("*")):
        if p.is_symlink():
            raise ForbiddenFile(f"{p}: symlinks are not allowed in a Pages artifact")
        if p.is_file():
            yield p


def audit_tree(root: Path) -> None:
    """Re-walk the tree: allow-list on every name, symlinks refused, every .gz is JSON (first byte ``{`` or ``[``)."""
    for p in walk_files(root):
        rel = p.relative_to(root).as_posix()
        if rel.startswith(".work/"):
            continue
        check_allowed(rel)
        if rel.endswith(".gz"):
            with gzip.open(p, "rb") as fh:
                first = fh.read(1)
            if first not in (b"{", b"["):
                raise ForbiddenFile(f"{rel}: not JSON inside (first byte {first!r})")


def env_home() -> str:
    return os.path.expanduser("~")
