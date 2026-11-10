"""Taxi zones as EntityCollection: reprojection, special IDs, simplified copy (needs shapely>=2.2, pyproj, pyshp)."""

import json

import pytest

pytest.importorskip("shapely", minversion="2.2")
pytest.importorskip("pyproj")
pytest.importorskip("shapefile")

import shapely  # noqa: E402
from mobility_helpers import LOOKUP_CSV, zones_zip  # noqa: E402

from atlas.contracts.models import EntityCollection, GeometrySupport  # noqa: E402
from atlas.domains.mobility.zones import (  # noqa: E402
    NYC_BBOX,
    build_zone_collections,
    read_lookup,
    read_shapefile,
    write_collection,
    zone_ids_with_geometry,
)


@pytest.fixture()
def raw(tmp_path):
    zones_zip(tmp_path / "taxi_zones.zip")
    (tmp_path / "taxi_zone_lookup.csv").write_text(LOOKUP_CSV, encoding="utf-8")
    return tmp_path


def test_lookup_and_shapefile_are_read_without_unpacking(raw):
    lookup = read_lookup(raw / "taxi_zone_lookup.csv")
    assert sorted(lookup) == [1, 2, 3, 4, 5, 264, 265] and lookup[265]["zone"] == "Outside of NYC"
    attrs, geoms, crs = read_shapefile(raw / "taxi_zones.zip")
    assert crs.to_epsg() == 2263 and [a["LocationID"] for a in attrs] == [1, 2, 3]
    assert [g.geom_type for g in geoms] == ["Polygon", "MultiPolygon", "Polygon"]
    assert sorted(p.name for p in raw.iterdir()) == ["taxi_zone_lookup.csv", "taxi_zones.zip"]


def test_reprojection_lands_in_new_york_and_matches_a_known_place(raw):
    full, _, report = build_zone_collections(raw, "t-v1")
    for feature in full.features:
        if feature.geometry is None:
            continue
        x, y = shapely.centroid(shapely.geometry.shape(feature.geometry.model_dump())).coords[0]
        assert NYC_BBOX[0] <= x <= NYC_BBOX[2] and NYC_BBOX[1] <= y <= NYC_BBOX[3], feature.id
    assert report["all_centroids_inside_nyc_bbox"] and report["source_crs"] == "EPSG:2263"
    # the fixture square at (988000, 215500) ft + 300 ft is Times Square: -73.9851, 40.7589
    one = next(f for f in full.features if f.id == "1")
    x, y = shapely.centroid(shapely.geometry.shape(one.geometry.model_dump())).coords[0]
    assert x == pytest.approx(-73.9851, abs=0.003) and y == pytest.approx(40.7589, abs=0.003)
    assert one.properties.attributes["label_lon_lat"] == pytest.approx([x, y], abs=0.002)
    assert one.properties.attributes["area_km2"] == pytest.approx(600 * 600 * (1200 / 3937) ** 2 / 1e6, abs=1e-4)


def test_special_ids_and_missing_polygons_get_null_geometry(raw):
    full, simplified, report = build_zone_collections(raw, "t-v1")
    for collection in (full, simplified):
        by_id = {f.id: f for f in collection.features}
        assert sorted(by_id, key=int) == ["1", "2", "3", "4", "5", "264", "265"]
        for special in ("264", "265"):
            assert by_id[special].geometry is None and by_id[special].properties.attributes["special_id"] is True
        assert by_id["264"].properties.name == "Unknown" and by_id["265"].properties.name == "Outside of NYC"
        assert by_id["4"].geometry is None and by_id["4"].properties.attributes["special_id"] is False  # in lookup only
        assert all(f.properties.geometry_support == GeometrySupport.OBSERVED_POLYGON for f in collection.features)
        assert {f.properties.timezone for f in collection.features} == {"America/New_York"}
    assert report["entities_without_geometry"] == [4, 5, 264, 265]
    assert report["names_shared_by_several_ids"] == {"Alphabet City": [4, 5]}
    attrs = {f.id: f.properties.attributes for f in full.features}
    assert attrs["4"]["display_name"] == "Alphabet City (ID 4)" and "display_name" not in attrs["1"]
    assert zone_ids_with_geometry(full) == [1, 2, 3]


def test_simplified_copy_is_valid_smaller_and_keeps_the_reference_untouched(raw):
    full, simplified, report = build_zone_collections(raw, "t-v1")
    assert report["full"]["all_valid"] and report["simplified"]["all_valid"]
    assert report["simplified"]["vertices"] <= report["full"]["vertices"]
    assert report["simplification"]["coverage_valid_after_simplify"] is True
    assert report["full"]["types"] == {"POLYGON": 2, "MULTIPOLYGON": 1}
    for collection in (full, simplified):
        for feature in collection.features:
            if feature.geometry is not None:
                geom = shapely.geometry.shape(feature.geometry.model_dump())
                assert geom.is_valid and not geom.is_empty
                assert shapely.get_type_id(geom) in (3, 6)
    multi = next(f for f in simplified.features if f.id == "2")
    assert multi.geometry.type == "MultiPolygon" and len(multi.geometry.coordinates) == 2


def test_written_geojson_round_trips_through_the_contract(raw, tmp_path):
    full, simplified, _ = build_zone_collections(raw, "t-v1")
    for name, collection in (("full.geojson", full), ("simple.geojson", simplified)):
        size = write_collection(collection, tmp_path / name)
        assert size == (tmp_path / name).stat().st_size > 0
        back = EntityCollection.model_validate(json.loads((tmp_path / name).read_text(encoding="utf-8")))
        assert back == collection and back.domain.value == "mobility" and back.data_version == "t-v1"
    # RFC 7946: exterior rings are counter-clockwise
    ring = full.features[0].geometry.coordinates[0]
    assert shapely.geometry.LinearRing(ring).is_ccw
