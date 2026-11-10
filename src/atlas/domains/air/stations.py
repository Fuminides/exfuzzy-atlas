"""Official Madrid air-quality station geometry and its reconciliation with the hourly table.

Primary geometry: Madrid Geoportal layer 5 queried with ``outSR=4326`` (the layer is stored in ETRS89 / UTM 30N,
EPSG:25830). Cross-check and metadata (altitude, opening date): datos.madrid.es "Estaciones de control" CSV.
A station present in the hourly data but absent from the official layer gets ``geometry: null``; coordinates are
never inferred.
"""

from __future__ import annotations

import csv
import json
import math
from datetime import datetime
from pathlib import Path

from atlas.contracts.models import (
    Domain,
    EntityCollection,
    EntityFeature,
    EntityProperties,
    GeometrySupport,
    PointGeometry,
)
from atlas.domains.air.parse import TIMEZONE

GEOPORTAL_FILE = "geoportal_layer5_estaciones.geojson"
CROSSCHECK_FILE = "estaciones-control-aire.csv"
POLLUTANT_COLUMNS = {"NO2": "no2", "SO2": "so2", "CO": "co", "PM10": "pm10", "PM2_5": "pm25", "O3": "o3", "BTX": "btx"}


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371008.8 * math.asin(math.sqrt(a))


def _read_geoportal(path: Path) -> dict[str, dict]:
    collection = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for feature in collection["features"]:
        props = feature["properties"]
        out[props["CODIGO_TX"].strip()] = {"props": props, "lonlat": tuple(feature["geometry"]["coordinates"])}
    return out


def _read_crosscheck(path: Path) -> dict[str, dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))
    return {row["CODIGO"].strip(): row for row in rows}


def _to_float(text: str) -> float:
    return float(text.replace(",", "."))


def build_station_collection(
    raw_dir: Path, observed: dict[str, dict], data_version: str, geometry_source: str
) -> tuple[EntityCollection, dict]:
    """Merge official geometry with what the hourly data contain.

    Args:
        raw_dir: ``data/raw/madrid-air-stations``.
        observed: ``entity_id -> {"features": [...], "first_utc": iso, "last_utc": iso}`` from the hourly data.
        data_version: stamped on the collection.
        geometry_source: URL of the official layer, written to every feature.

    Returns:
        The validated :class:`EntityCollection` and a reconciliation report.
    """
    official = _read_geoportal(raw_dir / GEOPORTAL_FILE)
    cross = _read_crosscheck(raw_dir / CROSSCHECK_FILE)

    codes = sorted(set(official) | set(observed))
    features, discrepancies = [], {}
    for code in codes:
        entry = official.get(code)
        extra = cross.get(code)
        attributes: dict = {"in_hourly_data": code in observed, "has_official_coordinates": entry is not None}
        geometry = None
        name = None
        if code in observed:
            attributes["observed_features"] = observed[code]["features"]
            attributes["first_observation_utc"] = observed[code]["first_utc"]
            attributes["last_observation_utc"] = observed[code]["last_utc"]
        if entry is not None:
            props = entry["props"]
            lon, lat = entry["lonlat"]
            geometry = PointGeometry(type="Point", coordinates=(lon, lat))
            name = props["ESTACION"].strip()
            attributes.update(
                short_code=props["CODIGO_CORTO"],
                address=(props["DIRECCION"] or "").strip(),
                station_type_code=props["COD_TIPO"],
                station_type=props["NOM_TIPO"],
                official_pollutants=sorted(v for k, v in POLLUTANT_COLUMNS.items() if props.get(k) == "X"),
                x_etrs89_utm30n=props["COORDENADA_X_ETRS89"],
                y_etrs89_utm30n=props["COORDENADA_Y_ETRS89"],
                geometry_epsg=4326,
                geometry_note="Geoportal layer 5 reprojected by the service (outSR=4326) from ETRS89 / UTM 30N.",
            )
        if extra is not None:
            attributes.update(altitude_m=int(extra["ALTITUD"]), opened_date=_opened(extra["Fecha alta"]))
            if entry is not None:
                other = (float(extra["LONGITUD"]), float(extra["LATITUD"]))
                distance = _haversine_m(*entry["lonlat"], *other)
                attributes["crosscheck_lon_lat"] = list(other)
                attributes["crosscheck_distance_m"] = round(distance, 1)
                if distance > 5:
                    discrepancies[code] = {
                        "distance_m": round(distance, 1),
                        "geoportal": list(entry["lonlat"]),
                        "datos_madrid_csv": list(other),
                    }
        features.append(
            EntityFeature(
                type="Feature",
                id=code,
                geometry=geometry,
                properties=EntityProperties(
                    entity_id=code,
                    domain=Domain.AIR,
                    name=name,
                    geometry_support=GeometrySupport.OBSERVED_POINT,
                    geometry_source=geometry_source,
                    timezone=TIMEZONE,
                    attributes=attributes,
                ),
            )
        )
    collection = EntityCollection(
        type="FeatureCollection", domain=Domain.AIR, data_version=data_version, features=features
    )
    report = {
        "official_stations": len(official),
        "official_station_ids": sorted(official),
        "stations_in_hourly_data": len(observed),
        "in_data_without_official_coordinates": sorted(set(observed) - set(official)),
        "official_without_hourly_data": sorted(set(official) - set(observed)),
        "short_code_mismatch": sorted(c for c, e in official.items() if int(e["props"]["CODIGO_CORTO"]) != int(c[-3:])),
        "not_in_datos_madrid_csv": sorted(set(official) - set(cross)),
        "coordinate_discrepancies_over_5m": discrepancies,
    }
    return collection, report


def _opened(text: str) -> str | None:
    text = text.strip()
    return datetime.strptime(text, "%d/%m/%Y").date().isoformat() if text else None
