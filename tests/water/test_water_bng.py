"""British National Grid -> WGS84, against coordinates recorded from the API and (if installed) pyproj."""

import json
import math

import pytest
from water_helpers import FIXTURES

from atlas.domains.water.bng import bng_to_wgs84


def metres(lon1, lat1, lon2, lat2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371008.8 * math.asin(math.sqrt(a))


def test_matches_wgs84_that_the_api_itself_computes():
    """``Accept: application/geo+json`` returns the same points in WGS84 with 9 decimals (converted by the service)."""
    recorded = json.loads((FIXTURES / "bng_recorded.json").read_text())
    assert len(recorded) >= 5
    for point in recorded:
        lon, lat = bng_to_wgs84(*point["bng"])
        assert metres(lon, lat, *point["api_wgs84_geojson"]) < 3, point[
            "notation"
        ]  # observed max over 772 points: 1.5 m


def test_origin_of_the_grid():
    # The false origin (E 400000, N -100000) is 49N 2W on OSGB36; the Helmert shift moves it by about 100 m.
    lon, lat = bng_to_wgs84(400000, -100000)
    assert abs(lon - -2.0) < 3e-3 and abs(lat - 49.0) < 3e-3


def test_agrees_with_pyproj_to_the_millimetre_when_available():
    pyproj = pytest.importorskip("pyproj")
    transformer = pyproj.Transformer.from_crs(27700, 4326, always_xy=True)
    for east, north in [(407291, 643492), (395710, 652590), (530000, 180000), (240000, 790000)]:
        lon, lat = bng_to_wgs84(east, north)
        # pyproj may use OSTN15 grids if they are installed; with the default Helmert they coincide to < 1 mm
        assert metres(lon, lat, *transformer.transform(east, north)) < 10
