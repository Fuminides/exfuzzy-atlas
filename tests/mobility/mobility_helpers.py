"""Builders for tiny hand-written TLC-shaped inputs (no network, no real data)."""

from __future__ import annotations

import io
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

LOOKUP_CSV = (
    '"LocationID","Borough","Zone","service_zone"\n'
    '1,"EWR","Newark Airport","EWR"\n'
    '2,"Queens","Jamaica Bay","Boro Zone"\n'
    '3,"Bronx","Allerton/Pelham Gardens","Boro Zone"\n'
    '4,"Manhattan","Alphabet City","Yellow Zone"\n'
    '5,"Manhattan","Alphabet City","Yellow Zone"\n'
    '264,"Unknown","N/A","N/A"\n'
    '265,"N/A","Outside of NYC","N/A"\n'
)
LOOKUP_IDS = [1, 2, 3, 4, 5, 264, 265]
ZONE_IDS = [1, 2, 3, 4, 5]


def trip(pickup: str, minutes: float | None = 10, zone: int | None = 1, *, dropoff: str | None = None):
    """One trip as (pickup, dropoff, PULocationID); ``dropoff`` overrides ``minutes``."""
    start = datetime.fromisoformat(pickup)
    if dropoff is not None:
        end = datetime.fromisoformat(dropoff)
    else:
        end = None if minutes is None else start + timedelta(minutes=minutes)
    return start, end, zone


def write_trips(path: Path, trips: list, *, extra_column: bool = False) -> Path:
    columns = {
        "VendorID": pa.array([1] * len(trips), pa.int32()),
        "tpep_pickup_datetime": pa.array([t[0] for t in trips], pa.timestamp("us")),
        "tpep_dropoff_datetime": pa.array([t[1] for t in trips], pa.timestamp("us")),
        "PULocationID": pa.array([t[2] for t in trips], pa.int32()),
        "total_amount": pa.array([12.5] * len(trips), pa.float64()),
    }
    if extra_column:
        columns["cbd_congestion_fee"] = pa.array([0.75] * len(trips), pa.float64())
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(columns), path)
    return path


def zones_zip(path: Path) -> Path:
    """A 3-polygon shapefile in EPSG:2263 (a Polygon, a MultiPolygon and a small square) zipped like the TLC one."""
    import shapefile
    from pyproj import CRS

    def square(x: float, y: float, side: float = 600.0):
        return [(x, y), (x, y + side), (x + side, y + side), (x + side, y), (x, y)]  # clockwise, like ESRI exteriors

    parts = {
        1: [square(988000, 215500)],  # around Times Square
        2: [square(988000, 211700), square(989500, 211700, 300)],  # Empire State area, two parts
        3: [square(980000, 190000)],
    }
    buffers = {k: io.BytesIO() for k in ("shp", "shx", "dbf")}
    writer = shapefile.Writer(**buffers, shapeType=shapefile.POLYGON)
    writer.field("OBJECTID", "N", 9)
    writer.field("zone", "C", 80)
    writer.field("LocationID", "N", 9)
    writer.field("borough", "C", 80)
    names = {1: ("Newark Airport", "EWR"), 2: ("Jamaica Bay", "Queens"), 3: ("Allerton/Pelham Gardens", "Bronx")}
    for location_id, polygons in parts.items():
        writer.poly(polygons)
        writer.record(location_id, names[location_id][0], location_id, names[location_id][1])
    writer.close()
    prj = CRS.from_epsg(2263).to_wkt(version="WKT1_ESRI")
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("taxi_zones/taxi_zones.shp", buffers["shp"].getvalue())
        archive.writestr("taxi_zones/taxi_zones.shx", buffers["shx"].getvalue())
        archive.writestr("taxi_zones/taxi_zones.dbf", buffers["dbf"].getvalue())
        archive.writestr("taxi_zones/taxi_zones.prj", prj)
        archive.writestr("taxi_zones/taxi_zones.cpg", "UTF-8")
    return path
