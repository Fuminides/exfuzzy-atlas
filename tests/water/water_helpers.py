"""Shared test doubles for the water tests: a scripted transport and a small in-memory Water Quality Explorer API."""

from __future__ import annotations

import csv
import io
import json
import urllib.parse
from collections.abc import Callable
from datetime import date
from pathlib import Path

from atlas.domains.water.client import Response, WaterQualityClient
from atlas.domains.water.parse import CSV_COLUMNS

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://environment.data.gov.uk/water-quality"


class ScriptedTransport:
    """Returns the queued responses in order and records every call. Exceptions in the queue are raised."""

    def __init__(self, *responses: Response | Exception):
        self.queue = list(responses)
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, method, url, headers, timeout):
        self.calls.append((method, url, dict(headers)))
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class Clock:
    """Fake monotonic clock + sleep: ``sleep`` advances time and records the delays."""

    def __init__(self):
        self.now = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_client(transport: Callable, clock: Clock | None = None, **kwargs) -> tuple[WaterQualityClient, Clock]:
    clock = clock or Clock()
    kwargs.setdefault("min_interval_s", 0.0)
    client = WaterQualityClient(transport, sleep=clock.sleep, monotonic=clock.monotonic, **kwargs)
    return client, clock


def ok(body: bytes = b"", total: int | None = None, next_url: str | None = None, **headers) -> Response:
    head = {k.lower().replace("_", "-"): v for k, v in headers.items()}
    if total is not None:
        head["x-total-items"] = str(total)
    if next_url is not None:
        head["link"] = f'<{next_url}>; rel="next", <{BASE}/x>; rel="first"'
    elif total is not None:
        head["link"] = f'<{BASE}/x>; rel="self", <{BASE}/x>; rel="first"'
    return Response(200, head, body)


def obs_row(
    point,
    sample,
    det,
    when,
    result,
    *,
    easting=409570,
    northing=639530,
    unit="MILLIGRAM PER LITRE",
    purpose="ENVIRONMENTAL MONITORING STATUTORY (EU DIRECTIVES)",
    material="RIVER / RUNNING SURFACE WATER",
) -> dict:
    """One CSV row of ``POST /data/observation`` (same columns as the real API)."""
    return {
        "id": f"{BASE}/sampling-point/{point}/sample/{sample}/observation/{det}",
        "samplingPoint.notation": point,
        "samplingPoint.prefLabel": f"POINT {point}",
        "samplingPoint.easting": "" if easting is None else easting,
        "samplingPoint.northing": "" if northing is None else northing,
        "samplingPoint.region": "NorthEast",
        "samplingPoint.area": "NORTH EAST - NORTHUMBERLAND DURHAM AND TEES",
        "samplingPoint.subArea": "NORTHUMBERLAND & TYNE",
        "samplingPoint.samplingPointStatus": "OPEN",
        "samplingPoint.samplingPointType": "FRESHWATER - RIVERS",
        "phenomenonTime": when,
        "samplingPurpose": purpose,
        "sampleMaterialType": material,
        "determinand.notation": det,
        "determinand.prefLabel": {"9924": "Oxygen, Dissolved as O2", "0111": "Ammoniacal Nitrogen as N"}.get(det, det),
        "result": result,
        "unit": unit,
    }


def csv_bytes(rows: list[dict]) -> bytes:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(CSV_COLUMNS), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode()


def point_member(notation: str, easting: int | None, northing: int | None) -> dict:
    geometry = (
        {
            "id": f"{BASE}/sampling-point/{notation}#Geometry",
            "@type": "geo:Geometry",
            "asWKT": f"POINT({easting} {northing}) <http://www.opengis.net/def/crs/EPSG/0/27700>",
        }
        if easting is not None
        else None
    )
    concept = lambda code, label: {"@id": f"_:{code}", "prefLabel": label, "notation": code}  # noqa: E731
    return {
        "id": f"{BASE}/sampling-point/{notation}",
        "notation": notation,
        "prefLabel": f"POINT {notation}",
        "altLabel": f"P {notation}",
        "geometry": geometry,
        "samplingPointStatus": concept("O", "OPEN"),
        "samplingPointType": concept("F6", "FRESHWATER - RIVERS"),
        "region": concept("NE", "NorthEast"),
        "area": concept("X", "NORTH EAST - NORTHUMBERLAND DURHAM AND TEES"),
        "subArea": concept("X-H", "NORTHUMBERLAND & TYNE"),
    }


class FakeApi:
    """Serves ``/sampling-point``, ``/codelist/unit`` and ``/data/observation`` from memory, with real paging."""

    def __init__(self, points: list[dict], observations: list[dict], units: dict[str, str] | None = None):
        self.points = points
        self.observations = observations
        self.units = units or {"MILLIGRAM PER LITRE": "mg/l"}
        self.calls: list[tuple[str, str]] = []

    def __call__(self, method, url, headers, timeout) -> Response:
        self.calls.append((method, url))
        parsed = urllib.parse.urlparse(url)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        path = parsed.path.removeprefix("/water-quality/")
        skip, limit = int(q.get("skip", 0)), int(q["limit"])
        if path == "sampling-point" and method == "GET":
            items = self.points
            wrap = lambda page: json.dumps({"member": page}).encode()  # noqa: E731
        elif path == "codelist/unit" and method == "GET":
            items = [{"prefLabel": k, "altLabel": v, "notation": str(i)} for i, (k, v) in enumerate(self.units.items())]
            wrap = lambda page: json.dumps({"member": page}).encode()  # noqa: E731
        elif path == "data/observation" and method == "POST":
            dets = set(q["determinand"].split(","))
            span = (date.fromisoformat(q["dateTo"]) - date.fromisoformat(q["dateFrom"])).days
            if span >= 365:  # the real API: "maximum temporal range is 1 year" for multi-point queries
                return Response(400, {}, b'{"detail":"the maximum temporal range is 1 year."}')
            items = [
                r
                for r in self.observations
                if r["determinand.notation"] in dets and q["dateFrom"] <= r["phenomenonTime"][:10] < q["dateTo"]
            ]  # dateTo is exclusive
            items.sort(key=lambda r: r["id"])
            wrap = csv_bytes
        else:
            return Response(404, {}, b"not found")
        if not items:
            return Response(204, {}, b"")
        page = items[skip : skip + limit]
        has_next = skip + limit < len(items)
        return ok(wrap(page) if page else b"", total=len(items), next_url=f"{url}&next" if has_next else None)
