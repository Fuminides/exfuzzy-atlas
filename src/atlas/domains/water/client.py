"""Small typed client for the Environment Agency Water Quality Explorer API (``/water-quality``).

Facts it relies on (verified 2026-10-30, see ``docs/water/api_notes.md``):

* paging is ``skip``/``limit``; every page carries ``X-Total-Items`` and a ``Link`` header, and the last page has no
  ``rel="next"``; a page past the end is a 200 with an empty body and a filter that matches nothing is a 204;
* ``limit`` is at most 250 (JSON-LD) or 2500 (CSV / JSON Lines) for observations;
* no key is needed and no rate limit is documented, so the client paces itself and backs off on 429 / 5xx.

The transport is injectable, so tests never touch the network.
"""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

BASE_URL = "https://environment.data.gov.uk/water-quality"
USER_AGENT = "exfuzzy-atlas/0.1 (open-data research ingestion; https://github.com/Fuminides/exfuzzy-atlas)"
OK_STATUSES = frozenset({200, 204})  # 204: the filter matches nothing (empty body)
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
CSV_PAGE_LIMIT = 2500  # observations as text/csv or application/x-jsonlines
JSONLD_PAGE_LIMIT = 250  # observations / sampling points as application/ld+json
_REL_NEXT = re.compile(r'rel="?next"?', re.IGNORECASE)


@dataclass(frozen=True)
class Response:
    """What a transport returns. ``headers`` keys are lower-case."""

    status: int
    headers: Mapping[str, str]
    body: bytes


Transport = Callable[[str, str, Mapping[str, str], float], Response]
"""``(method, url, headers, timeout_s) -> Response``. Network failures must raise ``OSError``."""


class ApiError(RuntimeError):
    """A request failed for good (non-retryable status, or retries exhausted)."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def urllib_transport(method: str, url: str, headers: Mapping[str, str], timeout: float) -> Response:
    """Default transport (stdlib only). HTTP error statuses are returned, not raised."""
    data = b"" if method == "POST" else None  # POST /data/* takes an optional GeoJSON body; empty means "no polygon"
    request = urllib.request.Request(url, data=data, headers=dict(headers), method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as handle:  # noqa: S310 - https URL built from BASE_URL
            return Response(handle.status, {k.lower(): v for k, v in handle.headers.items()}, handle.read())
    except urllib.error.HTTPError as error:
        return Response(error.code, {k.lower(): v for k, v in error.headers.items()}, error.read())
    except urllib.error.URLError as error:
        raise OSError(str(error.reason)) from error


@dataclass
class ClientStats:
    requests: int = 0  # HTTP requests sent, including retries
    retries: int = 0
    bytes_received: int = 0
    waited_s: float = 0.0
    statuses: dict[int, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Page:
    """One page of a paginated collection."""

    url: str
    skip: int
    limit: int
    total_items: int | None  # ``X-Total-Items`` of this response
    has_next: bool
    body: bytes
    content_type: str


class WaterQualityClient:
    """GET/POST with pacing, timeout, retry/backoff and ``skip``/``limit`` pagination.

    Args:
        transport: injectable HTTP layer.
        min_interval_s: minimum time between the start of two requests (politeness; there is no documented limit).
        max_attempts: tries per request before :class:`ApiError`.
        backoff_s: first retry delay; it doubles each attempt up to ``max_backoff_s``. ``Retry-After`` wins if longer.
        sleep, monotonic: clocks, injectable for tests.
    """

    def __init__(
        self,
        transport: Transport = urllib_transport,
        *,
        base_url: str = BASE_URL,
        user_agent: str = USER_AGENT,
        timeout_s: float = 120.0,
        min_interval_s: float = 0.5,
        max_attempts: int = 5,
        backoff_s: float = 2.0,
        max_backoff_s: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self.transport = transport
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.timeout_s = timeout_s
        self.min_interval_s = min_interval_s
        self.max_attempts = max_attempts
        self.backoff_s = backoff_s
        self.max_backoff_s = max_backoff_s
        self._sleep = sleep
        self._monotonic = monotonic
        self._last_start: float | None = None
        self.stats = ClientStats()

    def url(self, path: str, params: Mapping[str, object] | None = None) -> str:
        """Absolute URL with a deterministic query string (insertion order, ``None`` values dropped)."""
        query = urllib.parse.urlencode([(k, str(v)) for k, v in (params or {}).items() if v is not None])
        return f"{self.base_url}/{path.lstrip('/')}" + (f"?{query}" if query else "")

    def request(
        self,
        method: str,
        path: str,
        params: Mapping[str, object] | None = None,
        *,
        accept: str = "application/ld+json",
    ) -> tuple[str, Response]:
        """One logical request. Retries 429 / 5xx / network errors; any other non-200 status raises."""
        url = self.url(path, params)
        headers = {
            "User-Agent": self.user_agent,
            "Accept": accept,
            "Accept-Crs": "http://www.opengis.net/def/crs/EPSG/0/27700",
            "API-Version": "1",
        }
        for attempt in range(1, self.max_attempts + 1):
            self._pace()
            self.stats.requests += 1
            try:
                response = self.transport(method, url, headers, self.timeout_s)
            except OSError as error:  # timeouts, resets, DNS
                failure, retry_after, status = f"network error: {error}", None, None
            else:
                self.stats.statuses[response.status] = self.stats.statuses.get(response.status, 0) + 1
                self.stats.bytes_received += len(response.body)
                if response.status in OK_STATUSES:
                    return url, response
                status = response.status
                failure = f"HTTP {status}: {response.body[:300].decode('utf-8', 'replace')}"
                retry_after = _retry_after_s(response.headers.get("retry-after"))
                if status not in RETRY_STATUSES:
                    raise ApiError(f"{method} {url} -> {failure}", status)
            if attempt == self.max_attempts:
                raise ApiError(f"{method} {url} failed after {attempt} attempts; last: {failure}", status)
            delay = min(self.max_backoff_s, self.backoff_s * 2 ** (attempt - 1))
            self._wait(max(delay, retry_after or 0.0))
            self.stats.retries += 1
        raise AssertionError("unreachable")  # pragma: no cover

    def pages(
        self,
        method: str,
        path: str,
        params: Mapping[str, object],
        *,
        accept: str,
        limit: int,
        start_skip: int = 0,
        max_pages: int = 10_000,
    ) -> Iterator[Page]:
        """Yield consecutive pages until the server stops advertising ``rel="next"``.

        The stop rule is, in order: no ``rel="next"`` in ``Link``; an empty body; ``skip + limit >= X-Total-Items``
        when the server sends no ``Link`` at all. ``max_pages`` only guards against a server that never ends.
        """
        skip = start_skip
        for _ in range(max_pages):
            url, response = self.request(method, path, {**params, "limit": limit, "skip": skip}, accept=accept)
            total = _int_or_none(response.headers.get("x-total-items"))
            link = response.headers.get("link")
            if link is not None:
                has_next = bool(_REL_NEXT.search(link))
            else:
                has_next = total is not None and skip + limit < total
            if not response.body.strip():
                has_next = False
            yield Page(
                url=url,
                skip=skip,
                limit=limit,
                total_items=total,
                has_next=has_next,
                body=response.body,
                content_type=response.headers.get("content-type", ""),
            )
            if not has_next:
                return
            skip += limit
        raise ApiError(f"pagination of {path} did not end after {max_pages} pages")

    def _pace(self) -> None:
        if self._last_start is not None:
            gap = self.min_interval_s - (self._monotonic() - self._last_start)
            if gap > 0:
                self._wait(gap)
        self._last_start = self._monotonic()

    def _wait(self, seconds: float) -> None:
        self.stats.waited_s += seconds
        self._sleep(seconds)


def _int_or_none(text: str | None) -> int | None:
    try:
        return int(text) if text is not None else None
    except ValueError:
        return None


def _retry_after_s(text: str | None) -> float | None:
    """``Retry-After`` as seconds (delta or HTTP-date); ``None`` if absent or unparseable."""
    if not text:
        return None
    if text.strip().isdigit():
        return float(text)
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
