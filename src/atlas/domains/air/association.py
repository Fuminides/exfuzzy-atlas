"""Honest spatial association between air stations and meteorological stations (AT-011).

The meteorological network is not co-located with the air network. Some sensors share a station code with an air
station (the sensors of the air-quality system hang on the same masts) and many do not. For each
``(air station, variable)`` we rank the meteorological stations that really report the variable and lie within
``max_distance_m`` by great-circle distance, and keep the closest ``max_candidates``. Rank 1 is the *primary*
source; rank 2 and 3 are fallbacks used **hour by hour** only when the better-ranked station has no valid value.

Nothing is interpolated, averaged between stations, or extrapolated beyond the maximum distance: if no candidate
qualifies the feature is missing (null) for that air station. ``distance_m`` and ``same_station_code`` are recorded
and shipped with the feature table (``association.parquet`` / ``association.json``).
"""

from __future__ import annotations

from dataclasses import dataclass

from atlas.domains.air.stations import _haversine_m

ASSOCIATION_COLUMNS = (
    "air_entity_id",
    "variable",
    "rank",
    "meteo_entity_id",
    "meteo_name",
    "distance_m",
    "same_station_code",
    "valid_hours",
    "max_distance_m",
)


@dataclass(frozen=True)
class Point:
    entity_id: str
    lon: float
    lat: float
    name: str | None = None


def build_association(
    air: list[Point],
    meteo: list[Point],
    valid_hours: dict[tuple[str, str], int],
    variables: list[str],
    *,
    max_distance_m: float,
    max_candidates: int = 3,
) -> list[dict]:
    """Rank candidate meteorological stations for every ``(air station, variable)``.

    Args:
        air: air stations with official coordinates (a station without them cannot be associated).
        meteo: meteorological stations with official coordinates.
        valid_hours: ``(meteo_entity_id, variable) -> number of hours with a valid value`` in the data. A station that
            does not appear (or has 0) does not measure the variable and is never a candidate.
        variables: variable names to associate.
        max_distance_m: hard limit; a farther station is never used, whatever the alternative.
        max_candidates: primary plus fallbacks kept per ``(air station, variable)``.

    Returns:
        One dict per kept candidate with the columns of :data:`ASSOCIATION_COLUMNS`; an air station for which a
        variable has no candidate has no row for it. Order: air station, variable, rank.
    """
    rows: list[dict] = []
    for station in sorted(air, key=lambda p: p.entity_id):
        for variable in variables:
            candidates = []
            for m in meteo:
                hours = valid_hours.get((m.entity_id, variable), 0)
                if hours <= 0:
                    continue
                distance = _haversine_m(station.lon, station.lat, m.lon, m.lat)
                if distance <= max_distance_m:
                    candidates.append((distance, m.entity_id, m, hours))
            for rank, (distance, _, m, hours) in enumerate(sorted(candidates, key=lambda c: c[:2])[:max_candidates], 1):
                rows.append(
                    {
                        "air_entity_id": station.entity_id,
                        "variable": variable,
                        "rank": rank,
                        "meteo_entity_id": m.entity_id,
                        "meteo_name": m.name,
                        "distance_m": round(distance, 1),
                        "same_station_code": m.entity_id == station.entity_id,
                        "valid_hours": int(hours),
                        "max_distance_m": float(max_distance_m),
                    }
                )
    return rows
