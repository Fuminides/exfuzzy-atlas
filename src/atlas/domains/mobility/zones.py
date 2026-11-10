"""Official NYC TLC taxi zones as :class:`EntityCollection` (full-resolution reference and a simplified frontend copy).

Source: ``taxi_zones.zip`` (ESRI shapefile, EPSG:2263 = NAD83 / New York Long Island, US survey feet, 263 polygons) and
``taxi_zone_lookup.csv`` (265 rows). LocationIDs 264 ("Unknown") and 265 ("Outside of NYC") have no polygon in the
shapefile: they become entities with ``geometry: null`` and are never given a made-up shape.

Reference file: every vertex of the source, reprojected to WGS84 (EPSG:4326) and rounded to 1e-7 degrees (~1 cm).
Frontend file: the same polygons run through GEOS ``coverage_clean`` (snap 0.5 ft) so the coverage is edge-matched, then
``coverage_simplify`` (tolerance 50 ft in the projected CRS) so shared borders stay identical on both sides, then
reprojected and rounded to 1e-5 degrees (~1 m). Needs ``shapely>=2.2`` (GEOS 3.14), ``pyproj`` and ``pyshp``.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path

import numpy as np
import shapefile
import shapely
from pyproj import CRS, Transformer

from atlas.contracts.models import Domain, EntityCollection, GeometrySupport

TIMEZONE = "America/New_York"
SPECIAL_IDS = {264: "Unknown", 265: "Outside of NYC"}
SIMPLIFY_TOLERANCE_FT = 50.0
SNAP_DISTANCE_FT = 0.5
US_FT_M = 1200 / 3937  # US survey foot in metres
FULL_DECIMALS = 7
SIMPLIFIED_DECIMALS = 5
# Generous bbox around the five boroughs plus Newark airport (EWR, zone 1); used as a reprojection sanity check.
NYC_BBOX = (-74.35, 40.45, -73.55, 40.95)


def read_lookup(path: Path) -> dict[int, dict]:
    """``LocationID -> {borough, zone, service_zone}`` from taxi_zone_lookup.csv."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {
            int(row["LocationID"]): {
                "borough": row["Borough"],
                "zone": row["Zone"],
                "service_zone": row["service_zone"],
            }
            for row in csv.DictReader(handle)
        }


def read_shapefile(zip_path: Path) -> tuple[list[dict], list, CRS]:
    """Read the zipped shapefile in memory (the raw archive is never unpacked). Returns attrs, geometries, CRS."""
    with zipfile.ZipFile(zip_path) as archive:
        members = {Path(n).suffix.lower(): n for n in archive.namelist() if not n.endswith("/")}
        for needed in (".shp", ".shx", ".dbf", ".prj"):
            if needed not in members:
                raise ValueError(f"{zip_path.name} has no {needed} member")
        encoding = archive.read(members[".cpg"]).decode("ascii").strip() if ".cpg" in members else "utf-8"
        crs = CRS.from_wkt(archive.read(members[".prj"]).decode("ascii"))
        reader = shapefile.Reader(
            shp=io.BytesIO(archive.read(members[".shp"])),
            shx=io.BytesIO(archive.read(members[".shx"])),
            dbf=io.BytesIO(archive.read(members[".dbf"])),
            encoding=encoding,
        )
        attrs = [dict(record.as_dict()) for record in reader.records()]
        geoms = [shapely.geometry.shape(s.__geo_interface__) for s in reader.shapes()]
    return attrs, geoms, crs


def _to_wgs84(geoms: np.ndarray, crs: CRS, decimals: int) -> np.ndarray:
    transformer = Transformer.from_crs(crs, CRS.from_epsg(4326), always_xy=True)
    out = shapely.transform(geoms, lambda c: np.column_stack(transformer.transform(c[:, 0], c[:, 1])))
    out = shapely.set_precision(out, 10.0**-decimals)
    return shapely.orient_polygons(out, exterior_cw=False)  # RFC 7946: exterior rings counter-clockwise


def _geometry_stats(geoms: np.ndarray) -> dict:
    return {
        "polygons": int(len(geoms)),
        "vertices": int(shapely.get_num_coordinates(geoms).sum()),
        "all_valid": bool(shapely.is_valid(geoms).all()),
        "any_empty": bool(shapely.is_empty(geoms).any()),
        "types": {
            shapely.GeometryType(int(k)).name: int(v)
            for k, v in zip(*np.unique(shapely.get_type_id(geoms), return_counts=True), strict=True)
        },
    }


def _entity_dicts(
    ids: list[int],
    lookup: dict[int, dict],
    by_id: dict[int, dict],
    geoms_4326: dict[int, object],
    areas_km2: dict[int, float],
    data_version: str,
) -> dict:
    name_count: dict[str, int] = {}
    for info in lookup.values():
        name_count[info["zone"]] = name_count.get(info["zone"], 0) + 1
    features = []
    for location_id in ids:
        info = lookup.get(location_id, {})
        attrs = by_id.get(location_id)
        geom = geoms_4326.get(location_id)
        special = location_id in SPECIAL_IDS
        zone = info.get("zone")
        name = SPECIAL_IDS[location_id] if special else zone
        attributes: dict = {
            "location_id": location_id,
            "borough": info.get("borough"),
            "zone": zone,
            "service_zone": info.get("service_zone"),
            "special_id": special,
            "has_geometry": geom is not None,
            "in_lookup": location_id in lookup,
        }
        if name and name_count.get(zone, 0) > 1 and not special:
            attributes["name_shared_with_other_ids"] = True
            attributes["display_name"] = f"{name} (ID {location_id})"
        if attrs is not None:
            attributes["shapefile_objectid"] = attrs["OBJECTID"]
            if (attrs["zone"], attrs["borough"]) != (info.get("zone"), info.get("borough")):
                attributes["shapefile_zone"] = attrs["zone"]
                attributes["shapefile_borough"] = attrs["borough"]
        if special:
            attributes["note"] = (
                "TLC placeholder LocationID with no polygon in the official shapefile; geometry is null by design."
            )
        if geom is not None:
            point = shapely.point_on_surface(geom)
            attributes["label_lon_lat"] = [round(point.x, 5), round(point.y, 5)]
            attributes["area_km2"] = round(areas_km2[location_id], 4)
        features.append(
            {
                "type": "Feature",
                "id": str(location_id),
                "geometry": None if geom is None else json.loads(shapely.to_geojson(geom)),
                "properties": {
                    "entity_id": str(location_id),
                    "domain": Domain.MOBILITY.value,
                    "name": name,
                    "geometry_support": GeometrySupport.OBSERVED_POLYGON.value,
                    "geometry_source": "taxi_zones.zip" if geom is not None else "none (special LocationID)",
                    "timezone": TIMEZONE,
                    "attributes": attributes,
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "domain": Domain.MOBILITY.value,
        "data_version": data_version,
        "features": features,
    }


def build_zone_collections(
    raw_dir: Path, data_version: str, geometry_source: str | None = None
) -> tuple[EntityCollection, EntityCollection, dict]:
    """Return (full-resolution collection, simplified frontend collection, report).

    Both collections are validated by :class:`EntityCollection` (which also checks that polygon geometry matches
    ``geometry_support=observed_polygon``). The report holds the reconciliation with the lookup and the simplification
    evidence (vertices, validity, area change, coverage overlap).
    """
    lookup = read_lookup(raw_dir / "taxi_zone_lookup.csv")
    attrs, geoms_src, crs = read_shapefile(raw_dir / "taxi_zones.zip")
    ids_shp = [int(a["LocationID"]) for a in attrs]
    if len(set(ids_shp)) != len(ids_shp):
        raise ValueError("duplicate LocationID in the shapefile")
    by_id = {int(a["LocationID"]): a for a in attrs}
    src = np.array(geoms_src, dtype=object)
    area_src = shapely.area(src)
    areas_km2 = {i: float(a * US_FT_M**2 / 1e6) for i, a in zip(ids_shp, area_src, strict=True)}

    full = _to_wgs84(src, crs, FULL_DECIMALS)
    cleaned = shapely.coverage_clean(src, snapping_distance=SNAP_DISTANCE_FT)
    coverage_valid_source = bool(shapely.coverage_is_valid(src))
    simplified_proj = shapely.coverage_simplify(cleaned, SIMPLIFY_TOLERANCE_FT)
    simplified = _to_wgs84(simplified_proj, crs, SIMPLIFIED_DECIMALS)

    all_ids = sorted(set(lookup) | set(ids_shp))
    collections = []
    for geoms in (full, simplified):
        mapping = {i: g for i, g in zip(ids_shp, geoms, strict=True)}
        collections.append(
            EntityCollection.model_validate(_entity_dicts(all_ids, lookup, by_id, mapping, areas_km2, data_version))
        )
    full_c, simple_c = collections

    area_simplified = shapely.area(simplified_proj)
    stats_full, stats_simple = _geometry_stats(full), _geometry_stats(simplified)
    bounds = shapely.total_bounds(full)
    centroid_ok = all(
        NYC_BBOX[0] <= x <= NYC_BBOX[2] and NYC_BBOX[1] <= y <= NYC_BBOX[3]
        for x, y in zip(*shapely.get_coordinates(shapely.centroid(full)).T[:2], strict=True)
    )
    report = {
        "source_crs": crs.to_string() if crs.to_epsg() is None else f"EPSG:{crs.to_epsg()}",
        "source_crs_name": crs.name,
        "geometry_source": geometry_source,
        "shapefile_polygons": len(ids_shp),
        "lookup_rows": len(lookup),
        "entities": len(all_ids),
        "entities_with_geometry": len(ids_shp),
        "entities_without_geometry": sorted(set(all_ids) - set(ids_shp)),
        "in_shapefile_not_in_lookup": sorted(set(ids_shp) - set(lookup)),
        "name_or_borough_differs_lookup_vs_shapefile": sorted(
            i
            for i in ids_shp
            if i in lookup and (by_id[i]["zone"], by_id[i]["borough"]) != (lookup[i]["zone"], lookup[i]["borough"])
        ),
        "names_shared_by_several_ids": {
            name: sorted(i for i, v in lookup.items() if v["zone"] == name)
            for name in sorted({v["zone"] for v in lookup.values()})
            if sum(1 for v in lookup.values() if v["zone"] == name) > 1 and name != "N/A"
        },
        "boroughs": sorted({v["borough"] for v in lookup.values()}),
        "source_coverage_valid": coverage_valid_source,
        "source_total_vertices": int(shapely.get_num_coordinates(src).sum()),
        "source_invalid_polygons": int((~shapely.is_valid(src)).sum()),
        "full": stats_full,
        "simplified": stats_simple,
        "simplification": {
            "method": "GEOS coverage_clean (snap 0.5 ft) + coverage_simplify in EPSG:2263",
            "tolerance_ft": SIMPLIFY_TOLERANCE_FT,
            "tolerance_m": round(SIMPLIFY_TOLERANCE_FT * US_FT_M, 2),
            "snap_distance_ft": SNAP_DISTANCE_FT,
            "decimals_full": FULL_DECIMALS,
            "decimals_simplified": SIMPLIFIED_DECIMALS,
            "vertex_reduction_pct": round(100 * (1 - stats_simple["vertices"] / stats_full["vertices"]), 1),
            "coverage_valid_after_simplify": bool(shapely.coverage_is_valid(simplified_proj)),
            "max_zone_area_change_pct": round(float(np.max(np.abs(area_simplified - area_src) / area_src) * 100), 4),
            "total_area_change_pct": round(
                float(abs(area_simplified.sum() - area_src.sum()) / area_src.sum() * 100), 5
            ),
        },
        "bbox_lon_lat": [round(float(b), 5) for b in bounds],
        "all_centroids_inside_nyc_bbox": centroid_ok,
        "total_area_km2": round(float(area_src.sum() * US_FT_M**2 / 1e6), 2),
    }
    return full_c, simple_c, report


def write_collection(collection: EntityCollection, path: Path) -> int:
    """Write compact GeoJSON; returns the size in bytes."""
    text = json.dumps(json.loads(collection.model_dump_json()), separators=(",", ":"), ensure_ascii=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")
    return path.stat().st_size


def zone_ids_with_geometry(collection: EntityCollection) -> list[int]:
    return sorted(int(f.id) for f in collection.features if f.geometry is not None)

