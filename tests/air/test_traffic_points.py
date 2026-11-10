"""Spatial association of traffic measurement points with air stations (AT-012)."""

import math

import pytest

from atlas.domains.air.association import Point
from atlas.domains.air.stations import _haversine_m
from atlas.domains.air.traffic_points import (
    TrafficPoint,
    parse_points_csv,
    radius_table,
    track_changes,
    within_radius,
)

LON0, LAT0 = -3.70, 40.42
M_PER_DEG_LAT = 111_195.0


def north(metres: float) -> tuple[float, float]:
    """A coordinate ``metres`` north of the origin (great-circle, so the haversine distance is exact enough)."""
    return LON0, LAT0 + metres / M_PER_DEG_LAT


def point(pid, metres, kind="urban"):
    lon, lat = north(metres)
    return TrafficPoint(pid, kind, lon, lat, name=f"p{pid}")


STATION = Point("S1", LON0, LAT0, "station one")


def test_haversine_helper_is_metric():
    assert _haversine_m(LON0, LAT0, *north(1000)) == pytest.approx(1000, rel=2e-3)


def test_radius_is_respected_and_boundary_inclusive():
    points = [point(1, 100), point(2, 249), point(3, 251), point(4, 499), point(5, 501), point(6, 999), point(7, 1001)]
    assert [r["traffic_point_id"] for r in within_radius([STATION], points, 250)] == [1, 2]
    assert [r["traffic_point_id"] for r in within_radius([STATION], points, 500)] == [1, 2, 3, 4]
    assert len(within_radius([STATION], points, 1000)) == 6
    rows = within_radius([STATION], points, 1000)
    assert all(r["distance_m"] <= 1000 for r in rows)
    assert [r["rank"] for r in rows] == [1, 2, 3, 4, 5, 6]  # ranked by distance
    exact = _haversine_m(LON0, LAT0, *north(500))
    assert [r["traffic_point_id"] for r in within_radius([STATION], [point(9, 500)], exact + 0.05)] == [9]
    assert within_radius([STATION], [point(9, 500)], exact - 0.05) == []


def test_station_without_nearby_points_gets_no_rows():
    far = Point("S2", LON0 + 0.2, LAT0, "far")
    rows = within_radius([STATION, far], [point(1, 100)], 1000)
    assert {r["air_entity_id"] for r in rows} == {"S1"}
    table = {t["air_entity_id"]: t for t in radius_table([STATION, far], [point(1, 100)], (250.0, 500.0, 1000.0))}
    assert table["S2"]["n_1000m"] == 0 and table["S2"]["nearest_in_max_radius_m"] is None
    assert table["S1"]["n_250m"] == 1


def test_points_without_coordinates_and_kind_filter():
    unlocated = TrafficPoint(5, "urban", None, None)
    points = [unlocated, point(1, 100, "m30"), point(2, 150, "urban")]
    assert [r["traffic_point_id"] for r in within_radius([STATION], points, 500)] == [1, 2]
    assert [r["traffic_point_id"] for r in within_radius([STATION], points, 500, kinds=("urban",))] == [2]


def test_radius_table_counts_by_kind():
    points = [point(1, 100, "m30"), point(2, 300, "urban"), point(3, 700, "other")]
    (row,) = radius_table([STATION], points, (250.0, 500.0, 1000.0))
    assert (row["n_250m"], row["n_500m"], row["n_1000m"]) == (1, 2, 3)
    assert (row["n_500m_m30"], row["n_500m_urban"], row["n_1000m_other"]) == (1, 1, 1)
    assert row["nearest_in_max_radius_m"] == pytest.approx(100, rel=5e-3)


CSV = (
    '"tipo_elem";"distrito";"id";"cod_cent";"nombre";"utm_x";"utm_y";"longitud";"latitud"\r\n'
    '"URB";4;3840;"01001";"Jose Ortega y Gasset E-O";441615.34;4475767.94;-3.6883232754856;40.4305018691825\r\n'
    '"M30";5;3500;"M-1";"Nudo";1;2;-3,6;40,4\r\n'
    '"other";5;9;"x";"C30 punto";0;0;0;0\r\n'
    '"URB";5;3840;"dup";"duplicate id";0;0;-3.7;40.4\r\n'
)


def test_parse_points_csv():
    points = {p.point_id: p for p in parse_points_csv(CSV.encode("utf-8"))}
    assert set(points) == {3840, 3500, 9}  # the duplicate id keeps the first row
    assert points[3840].kind == "urban" and points[3840].name == "Jose Ortega y Gasset E-O"
    assert points[3500].kind == "m30" and (points[3500].lon, points[3500].lat) == (-3.6, 40.4)  # decimal comma
    assert points[9].kind == "other" and points[9].lon is None  # a (0, 0) placeholder is not a coordinate
    latin = CSV.replace("Jose", "José").encode("latin-1")
    assert {p.point_id: p for p in parse_points_csv(latin)}[3840].name == "José Ortega y Gasset E-O"


def test_changes_between_monthly_files_and_per_month_association():
    jan = [point(1, 100), point(2, 200), point(3, 300, "urban")]
    feb = [point(1, 100), point(2, 900), point(3, 300, "m30"), point(4, 50)]  # 2 moved, 3 changed kind, 4 added
    changes = track_changes({"2023-01": jan, "2023-02": feb})
    assert changes["per_month"]["2023-02"] == {"added": 1, "removed": 0, "moved_over_tolerance": 1, "kind_changed": 1}
    assert changes["ids_ever_moved"] == [2] and changes["ids_ever_kind_changed"] == [3]
    assert changes["ids_in_any_month"] == 4 and changes["ids_in_every_month"] == 3
    # the association follows the file of each month: point 2 is a neighbour in January, not in February
    near = {
        m: {r["traffic_point_id"] for r in within_radius([STATION], pts, 500)}
        for m, pts in (("jan", jan), ("feb", feb))
    }
    assert near["jan"] == {1, 2, 3} and near["feb"] == {1, 3, 4}
    assert math.isclose(sum(1 for _ in near["feb"]), 3)
