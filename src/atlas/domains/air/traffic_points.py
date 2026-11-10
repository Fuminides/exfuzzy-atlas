"""Measurement points of the Madrid traffic network and their honest association with the air stations (AT-012).

A traffic measurement point is an induction loop or camera on ONE road segment (one direction of a street). It is not
an area value and it is not co-located with an air station. For each air station we list the points that lie within
a radius, measured as great-circle distance between the official coordinates, and keep the ones inside the selected
radius of the association rule. A station with no point inside the radius has NO traffic feature (null): nothing is
borrowed from farther away, interpolated or averaged across the city.

The portal publishes one location file per month (the set of points changes over time: points appear, disappear and
move), so the association is built per month from the file of that month, never from a single snapshot.
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from atlas.domains.air.association import Point
from atlas.domains.air.stations import _haversine_m

# Location-file ``tipo_elem`` -> our kind. The history files call the third kind ``C30`` while the location files call
# it ``other``; the data files add a lower-case ``other`` for one junk id that is in no location file.
KIND_BY_LOCATION_TYPE = {"URB": "urban", "M30": "m30", "OTHER": "other", "C30": "other"}
# Madrid municipality bounding box (lon_min, lat_min, lon_max, lat_max), generous; used only to reject placeholders.
MADRID_BBOX = (-3.95, 40.28, -3.50, 40.60)
# A coordinate change below this is treated as numerical noise when tracking points across months.
MOVE_TOLERANCE_M = 10.0


@dataclass(frozen=True)
class TrafficPoint:
    point_id: int
    kind: str  # urban | m30 | other
    lon: float | None
    lat: float | None
    name: str | None = None
    district: str | None = None
    code: str | None = None  # cod_cent, the municipal code of the point


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise AssertionError("latin-1 decodes any byte string")


def _float(text: str) -> float | None:
    text = (text or "").strip().replace(",", ".")
    return float(text) if text else None


def parse_points_csv(raw: bytes) -> list[TrafficPoint]:
    """Parse one monthly location file (``;``-separated, header ``tipo_elem;distrito;id;cod_cent;nombre;...``).

    A point whose coordinates are missing or fall outside the Madrid bounding box gets ``lon = lat = None`` (it cannot
    be associated; coordinates are never inferred). Duplicate ids keep the first row and are reported by the caller via
    :func:`month_summary`.
    """
    text = _decode(raw)
    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter=";")
    rows = [{(k or "").strip().lower(): (v or "").strip() for k, v in row.items()} for row in reader]
    out, seen = [], set()
    for row in rows:
        pid = int(row["id"])
        if pid in seen:
            continue
        seen.add(pid)
        lon, lat = _float(row.get("longitud", "")), _float(row.get("latitud", ""))
        x0, y0, x1, y1 = MADRID_BBOX
        if lon is None or lat is None or not (x0 <= lon <= x1 and y0 <= lat <= y1):
            lon = lat = None
        out.append(
            TrafficPoint(
                point_id=pid,
                kind=KIND_BY_LOCATION_TYPE.get(row.get("tipo_elem", "").upper(), "other"),
                lon=lon,
                lat=lat,
                name=row.get("nombre") or None,
                district=row.get("distrito") or None,
                code=row.get("cod_cent") or None,
            )
        )
    return out


def read_points_csv(path: Path) -> list[TrafficPoint]:
    return parse_points_csv(path.read_bytes())


def within_radius(
    stations: list[Point], points: list[TrafficPoint], radius_m: float, *, kinds: tuple[str, ...] | None = None
) -> list[dict]:
    """Every ``(station, point)`` pair at a great-circle distance ``<= radius_m``.

    Points without coordinates are never candidates. ``kinds`` restricts the point kinds (``None`` = all).
    Order: station id, distance, point id. ``rank`` is the 1-based order of the point around its station.
    """
    rows: list[dict] = []
    for station in sorted(stations, key=lambda s: s.entity_id):
        found = []
        for p in points:
            if p.lon is None or p.lat is None or (kinds is not None and p.kind not in kinds):
                continue
            d = _haversine_m(station.lon, station.lat, p.lon, p.lat)
            if d <= radius_m:
                found.append((d, p))
        for rank, (d, p) in enumerate(sorted(found, key=lambda c: (c[0], c[1].point_id)), 1):
            rows.append(
                {
                    "air_entity_id": station.entity_id,
                    "traffic_point_id": p.point_id,
                    "kind": p.kind,
                    "name": p.name,
                    "distance_m": round(d, 1),
                    "rank": rank,
                }
            )
    return rows


def radius_table(
    stations: list[Point],
    points: list[TrafficPoint],
    radii: tuple[float, ...],
    kinds: tuple[str, ...] = ("urban", "m30", "other"),
) -> list[dict]:
    """Per station: number of points by kind inside each radius, and the distance to the nearest point of any kind."""
    nearest = {s.entity_id: None for s in stations}
    rows_by_radius = {r: within_radius(stations, points, r) for r in radii}
    for row in rows_by_radius[max(radii)]:
        if nearest[row["air_entity_id"]] is None:
            nearest[row["air_entity_id"]] = row["distance_m"]
    out = []
    for station in sorted(stations, key=lambda s: s.entity_id):
        entry: dict = {
            "air_entity_id": station.entity_id,
            "name": station.name,
            "nearest_in_max_radius_m": nearest[station.entity_id],
        }
        for r in radii:
            counts = Counter(row["kind"] for row in rows_by_radius[r] if row["air_entity_id"] == station.entity_id)
            entry[f"n_{int(r)}m"] = sum(counts.values())
            for kind in kinds:
                entry[f"n_{int(r)}m_{kind}"] = counts.get(kind, 0)
        out.append(entry)
    return out


def month_summary(points: list[TrafficPoint]) -> dict:
    """Counts of one location file: points, by kind, without usable coordinates."""
    return {
        "points": len(points),
        "by_kind": dict(sorted(Counter(p.kind for p in points).items())),
        "without_coordinates": sum(p.lon is None for p in points),
    }


def track_changes(by_month: dict[str, list[TrafficPoint]]) -> dict:
    """How the point set changes between consecutive monthly files.

    Returns, per month after the first: ids added, ids removed, ids whose coordinates moved more than
    ``MOVE_TOLERANCE_M`` and ids whose kind changed; and over the whole period the ids that move or change kind at all.
    """
    months = sorted(by_month)
    index = {m: {p.point_id: p for p in by_month[m]} for m in months}
    per_month, moved_ever, kind_changed_ever = {}, set(), set()
    for prev, cur in zip(months, months[1:], strict=False):
        a, b = index[prev], index[cur]
        moved, kind = [], []
        for pid in a.keys() & b.keys():
            pa, pb = a[pid], b[pid]
            if pa.kind != pb.kind:
                kind.append(pid)
            if (
                None not in (pa.lon, pa.lat, pb.lon, pb.lat)
                and _haversine_m(pa.lon, pa.lat, pb.lon, pb.lat) > MOVE_TOLERANCE_M
            ):
                moved.append(pid)
        per_month[cur] = {
            "added": len(b.keys() - a.keys()),
            "removed": len(a.keys() - b.keys()),
            "moved_over_tolerance": len(moved),
            "kind_changed": len(kind),
        }
        moved_ever.update(moved)
        kind_changed_ever.update(kind)
    return {
        "per_month": per_month,
        "ids_ever_moved": sorted(moved_ever),
        "ids_ever_kind_changed": sorted(kind_changed_ever),
        "ids_in_any_month": len(set().union(*(index[m].keys() for m in months))) if months else 0,
        "ids_in_every_month": len(set.intersection(*(set(index[m]) for m in months))) if months else 0,
    }
