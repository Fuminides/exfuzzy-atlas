"""British National Grid (EPSG:27700) to WGS84 (EPSG:4326) without extra dependencies.

The API serves sampling-point coordinates as BNG eastings/northings in metres (1 m resolution) in JSON-LD and CSV, as
WGS84 rounded to 4 decimals (~8 m) in JSON-LD with ``Accept-Crs: EPSG/0/4326``, and as WGS84 with 9 decimals in GeoJSON.
We keep the BNG values as the official ones and convert them here, so the library needs no extra dependency.

Method (Ordnance Survey, "A guide to coordinate systems in Great Britain", annexe C): inverse Transverse Mercator on the
Airy 1830 ellipsoid, then the 7-parameter Helmert shift OSGB36 -> WGS84. Helmert is accurate to about 2-5 m over Great
Britain in general (OSTN15 would be centimetric but needs a grid file). Against the API's own 9-decimal GeoJSON the
difference over all 772 points of the AT-020 slice is at most 1.5 m (mean 0.9 m); it equals pyproj's default
transformation. ``tests/water/test_water_bng.py`` checks both.
"""

from __future__ import annotations

import math

# Airy 1830
_A, _B = 6377563.396, 6356256.909
_F0 = 0.9996012717
_LAT0, _LON0 = math.radians(49.0), math.radians(-2.0)
_N0, _E0 = -100000.0, 400000.0
_E2 = 1 - (_B * _B) / (_A * _A)
_N = (_A - _B) / (_A + _B)

# OSGB36 -> WGS84 Helmert (position vector convention): metres, ppm, arc-seconds
_TX, _TY, _TZ = 446.448, -125.157, 542.060
_S = -20.4894e-6
_RX, _RY, _RZ = (math.radians(v / 3600) for v in (0.1502, 0.2470, 0.8421))
# WGS84
_WA, _WB = 6378137.0, 6356752.314245
_WE2 = 1 - (_WB * _WB) / (_WA * _WA)


def _meridian_arc(lat: float) -> float:
    n = _N
    return (
        _B
        * _F0
        * (
            (1 + n + 1.25 * n**2 + 1.25 * n**3) * (lat - _LAT0)
            - (3 * n + 3 * n**2 + 21 / 8 * n**3) * math.sin(lat - _LAT0) * math.cos(lat + _LAT0)
            + (15 / 8 * n**2 + 15 / 8 * n**3) * math.sin(2 * (lat - _LAT0)) * math.cos(2 * (lat + _LAT0))
            - 35 / 24 * n**3 * math.sin(3 * (lat - _LAT0)) * math.cos(3 * (lat + _LAT0))
        )
    )


def _grid_to_osgb36(easting: float, northing: float) -> tuple[float, float]:
    lat, m = _LAT0, 0.0
    while True:
        lat = (northing - _N0 - m) / (_A * _F0) + lat
        m = _meridian_arc(lat)
        if abs(northing - _N0 - m) < 1e-5:
            break
    sin, cos, tan = math.sin(lat), math.cos(lat), math.tan(lat)
    nu = _A * _F0 / math.sqrt(1 - _E2 * sin**2)
    rho = _A * _F0 * (1 - _E2) / (1 - _E2 * sin**2) ** 1.5
    eta2 = nu / rho - 1
    de = easting - _E0
    vii = tan / (2 * rho * nu)
    viii = tan / (24 * rho * nu**3) * (5 + 3 * tan**2 + eta2 - 9 * tan**2 * eta2)
    ix = tan / (720 * rho * nu**5) * (61 + 90 * tan**2 + 45 * tan**4)
    x = 1 / (cos * nu)
    xi = 1 / (cos * 6 * nu**3) * (nu / rho + 2 * tan**2)
    xii = 1 / (cos * 120 * nu**5) * (5 + 28 * tan**2 + 24 * tan**4)
    xiia = 1 / (cos * 5040 * nu**7) * (61 + 662 * tan**2 + 1320 * tan**4 + 720 * tan**6)
    lat_out = lat - vii * de**2 + viii * de**4 - ix * de**6
    lon_out = _LON0 + x * de - xi * de**3 + xii * de**5 - xiia * de**7
    return lat_out, lon_out


def _helmert_to_wgs84(lat: float, lon: float) -> tuple[float, float]:
    sin, cos = math.sin(lat), math.cos(lat)
    nu = _A / math.sqrt(1 - _E2 * sin**2)
    x1, y1, z1 = nu * cos * math.cos(lon), nu * cos * math.sin(lon), nu * (1 - _E2) * sin
    x2 = _TX + (1 + _S) * x1 - _RZ * y1 + _RY * z1
    y2 = _TY + _RZ * x1 + (1 + _S) * y1 - _RX * z1
    z2 = _TZ - _RY * x1 + _RX * y1 + (1 + _S) * z1
    p = math.hypot(x2, y2)
    lat2 = math.atan2(z2, p * (1 - _WE2))
    for _ in range(10):
        nu2 = _WA / math.sqrt(1 - _WE2 * math.sin(lat2) ** 2)
        new = math.atan2(z2 + _WE2 * nu2 * math.sin(lat2), p)
        if abs(new - lat2) < 1e-12:
            lat2 = new
            break
        lat2 = new
    return lat2, math.atan2(y2, x2)


def bng_to_wgs84(easting: float, northing: float) -> tuple[float, float]:
    """``(easting, northing)`` in BNG metres -> ``(lon, lat)`` in WGS84 degrees (GeoJSON order)."""
    lat, lon = _helmert_to_wgs84(*_grid_to_osgb36(easting, northing))
    return math.degrees(lon), math.degrees(lat)
