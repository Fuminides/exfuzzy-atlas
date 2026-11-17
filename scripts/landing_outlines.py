"""Land outlines for the landing's pictures (apps/web/src/assets/landing/outlines.json).

Germany whole, and Great Britain cropped around the river sampling points, from Natural Earth 1:10m Admin 0
countries (public domain) as redistributed by the npm package world-atlas 2.0.2 (countries-10m.json, TopoJSON).
`fit` says whether a picture is framed on the outline too (Germany) or on its dots alone (the rivers).

    npm pack world-atlas@2.0.2 && tar xzf world-atlas-2.0.2.tgz   # in an empty directory
    python scripts/landing_outlines.py package/countries-10m.json \\
        artifacts/published/<uk_water_do model>/entities.geojson apps/web/src/assets/landing/outlines.json

Then `npm run gen:landing-maps` in apps/web redraws the SVGs.
"""

from __future__ import annotations

import json
import math
import sys
from collections.abc import Callable

Point = tuple[float, float]
SOURCE = (
    "Natural Earth 1:10m Admin 0 countries v4.1.0 (public domain), via world-atlas 2.0.2; simplified, "
    "Great Britain cropped around the river sampling points"
)
GERMANY, UNITED_KINGDOM = "276", "826"


def decode_arcs(topo: dict) -> list[list[Point]]:
    """The topology's arcs in degrees (quantized and delta-encoded in the file)."""
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)
    return arcs


def country_rings(topo: dict, arcs: list[list[Point]], country_id: str) -> list[list[Point]]:
    """Every ring (outer and holes) of one country of the `countries` collection."""
    geometry = next(g for g in topo["objects"]["countries"]["geometries"] if g.get("id") == country_id)
    polygons = geometry["arcs"] if geometry["type"] == "MultiPolygon" else [geometry["arcs"]]
    rings = []
    for polygon in polygons:
        for ring_arcs in polygon:
            pts: list[Point] = []
            for i in ring_arcs:
                arc = arcs[i] if i >= 0 else arcs[~i][::-1]
                pts.extend(arc if not pts else arc[1:])
            rings.append(pts)
    return rings


def simplify(pts: list[Point], tol: float) -> list[Point]:
    """Douglas-Peucker on an open polyline, tolerance in degrees."""
    if len(pts) < 3:
        return pts
    (ax, ay), (bx, by) = pts[0], pts[-1]
    length = math.hypot(bx - ax, by - ay)
    far, dmax = -1, 0.0
    for i in range(1, len(pts) - 1):
        px, py = pts[i]
        if length == 0:
            d = math.hypot(px - ax, py - ay)
        else:
            d = abs((bx - ax) * (ay - py) - (ax - px) * (by - ay)) / length
        if d > dmax:
            dmax, far = d, i
    if dmax <= tol:
        return [pts[0], pts[-1]]
    return simplify(pts[: far + 1], tol)[:-1] + simplify(pts[far:], tol)


def clip(pts: list[Point], x0: float, y0: float, x1: float, y1: float) -> list[Point]:
    """Sutherland-Hodgman: the part of a ring inside a rectangle."""

    def at_x(x: float) -> Callable[[Point, Point], Point]:
        return lambda q, p: (x, q[1] + (p[1] - q[1]) * (x - q[0]) / (p[0] - q[0]))

    def at_y(y: float) -> Callable[[Point, Point], Point]:
        return lambda q, p: (q[0] + (p[0] - q[0]) * (y - q[1]) / (p[1] - q[1]), y)

    edges: list[tuple[Callable[[Point], bool], Callable[[Point, Point], Point]]] = [
        (lambda p: p[0] >= x0, at_x(x0)),
        (lambda p: p[0] <= x1, at_x(x1)),
        (lambda p: p[1] >= y0, at_y(y0)),
        (lambda p: p[1] <= y1, at_y(y1)),
    ]
    for inside, cut in edges:
        out: list[Point] = []
        for i, p in enumerate(pts):
            q = pts[i - 1]
            if inside(p):
                if not inside(q):
                    out.append(cut(q, p))
                out.append(p)
            elif inside(q):
                out.append(cut(q, p))
        pts = out
        if not pts:
            break
    return pts


def area(ring: list[Point]) -> float:
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:], strict=False))) / 2


def rounded(rings: list[list[Point]]) -> list[list[list[float]]]:
    return [[[round(x, 4), round(y, 4)] for x, y in ring] for ring in rings if len(ring) >= 4]


def main(topo_path: str, water_geojson: str, out_path: str) -> None:
    with open(topo_path) as f:
        topo = json.load(f)
    arcs = decode_arcs(topo)

    germany = [simplify(r, 0.01) for r in country_rings(topo, arcs, GERMANY)]
    germany = [r for r in germany if len(r) >= 4 and area(r) > 0.001]  # islands smaller than a dot go

    with open(water_geojson) as f:
        points = [feature["geometry"]["coordinates"] for feature in json.load(f)["features"]]
    lon0, lon1 = min(p[0] for p in points), max(p[0] for p in points)
    lat0, lat1 = min(p[1] for p in points), max(p[1] for p in points)
    mx, my = (lon1 - lon0) * 0.8, (lat1 - lat0) * 0.8
    britain = []
    for ring in country_rings(topo, arcs, UNITED_KINGDOM):
        cut = simplify(clip(ring, lon0 - mx, lat0 - my, lon1 + mx, lat1 + my), 0.002)
        if cut and cut[0] != cut[-1]:
            cut.append(cut[0])
        britain.append(cut)

    doc = {
        "source": SOURCE,
        "air": {"name": "Germany", "fit": True, "rings": rounded(germany)},
        "water": {"name": "Great Britain (part)", "fit": False, "rings": rounded(britain)},
    }
    with open(out_path, "w") as f:
        json.dump(doc, f, separators=(",", ":"))
    for key in ("air", "water"):
        rings = doc[key]["rings"]
        print(f"{key}: {len(rings)} rings, {sum(map(len, rings))} points")


if __name__ == "__main__":
    main(*sys.argv[1:4])
