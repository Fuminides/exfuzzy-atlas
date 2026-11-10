"""Extra inputs with a natural vocabulary for the Madrid NO2 task (AT-041e): trend, anomaly, official station type.

All three are derived from columns of the AT-041d table (plus the official station metadata) and none uses anything
published after the issue time ``t`` (the table's ``no2_last`` is the hour ``[t-1h, t)``, ``no2_lag3h`` the hour
``[t-4h, t-3h)``; both are finished hours, see the feature card).

* ``no2_trend_3h`` = ``no2_last - no2_lag3h`` (ug/m3). Terms Bajando / Estable / Subiendo.
* ``no2_anomaly`` = ``no2_last`` minus the **training-period** median of ``no2_last`` of the same station at the same
  local hour of the observed hour (``t - 1h``) (ug/m3). The reference table is computed from the rows of the training
  split only and never from validation or test. Terms Por debajo / Normal / Por encima.
* ``station_type`` = official type of the station from ``stations.geojson`` (``station_type_code`` UT / UF / S of the
  Madrid geoportal layer): 0 Trafico, 1 Fondo urbano, 2 Suburbana. A station without a type raises; a type is never
  inferred.

``configs/ml/madrid_partitions_extra.json`` holds the terms of the three inputs and their rationale.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

TREND = "no2_trend_3h"
ANOMALY = "no2_anomaly"
STATION_TYPE = "station_type"
EXTRA_FEATURES = (TREND, ANOMALY, STATION_TYPE)
STATION_TYPE_CODES = {"UT": 0, "UF": 1, "S": 2}  # Urbana trafico, Urbana fondo, Suburbana
STATION_TYPE_NAMES = {0: "Tráfico", 1: "Fondo urbano", 2: "Suburbana"}
UNITS = {TREND: "ug/m3", ANOMALY: "ug/m3", STATION_TYPE: "code"}


def trend(frame: pd.DataFrame) -> np.ndarray:
    """``no2_last - no2_lag3h`` (NaN where either is missing)."""
    return frame["no2_last"].to_numpy(dtype=float) - frame["no2_lag3h"].to_numpy(dtype=float)


def observed_local_hour(issued_at_utc, timezone: str) -> np.ndarray:
    """Local hour of the hour ``no2_last`` measures: ``[t-1h, t)`` is the hour with start ``t - 1h``."""
    stamps = pd.DatetimeIndex(issued_at_utc) - timedelta(hours=1)
    return np.asarray(stamps.tz_convert(timezone).hour)


def station_hour_medians(frame: pd.DataFrame, train_mask: np.ndarray, timezone: str) -> pd.Series:
    """Median ``no2_last`` per ``(entity_id, local hour of the observed hour)`` over the rows of ``train_mask`` only."""
    rows = np.asarray(train_mask, dtype=bool)
    sub = frame.loc[rows, ["entity_id", "issued_at_utc", "no2_last"]]
    keys = pd.DataFrame({
        "entity_id": sub["entity_id"].to_numpy(), "hour": observed_local_hour(sub["issued_at_utc"], timezone),
        "no2": sub["no2_last"].to_numpy(dtype=float)})
    return keys.dropna(subset=["no2"]).groupby(["entity_id", "hour"])["no2"].median()


def anomaly(frame: pd.DataFrame, reference: pd.Series, timezone: str) -> np.ndarray:
    """``no2_last`` minus the reference median of its station and local hour (NaN without a reference)."""
    index = pd.MultiIndex.from_arrays([frame["entity_id"].to_numpy(),
                                       observed_local_hour(frame["issued_at_utc"], timezone)])
    median = reference.reindex(index).to_numpy(dtype=float)
    return frame["no2_last"].to_numpy(dtype=float) - median


def station_types(stations_geojson: Path) -> dict[str, int]:
    """Code per station from the official ``station_type_code`` attribute; raises on a missing or unknown type."""
    out: dict[str, int] = {}
    for feature in json.loads(Path(stations_geojson).read_text())["features"]:
        entity = str(feature["properties"]["entity_id"])
        code = feature["properties"].get("attributes", {}).get("station_type_code")
        if code not in STATION_TYPE_CODES:
            raise ValueError(f"station {entity}: unknown or missing official station_type_code {code!r}")
        out[entity] = STATION_TYPE_CODES[code]
    return out


def add_extra_features(frame: pd.DataFrame, train_mask: np.ndarray, *, timezone: str, stations_geojson: Path
                       ) -> tuple[pd.DataFrame, dict]:
    """A copy of ``frame`` with the three inputs, and an audit dict (reference size, rows without a value).

    ``train_mask`` (aligned with ``frame``) selects the only rows allowed to define the anomaly reference.
    """
    out = frame.copy()
    reference = station_hour_medians(frame, train_mask, timezone)
    types = station_types(stations_geojson)
    entities = out["entity_id"].astype(str)
    missing_types = sorted(set(entities) - set(types))
    if missing_types:
        raise ValueError(f"stations without an official type: {missing_types}")
    out[TREND] = trend(out)
    out[ANOMALY] = anomaly(out, reference, timezone)
    out[STATION_TYPE] = entities.map(types).to_numpy(dtype=float)
    audit = {
        "reference_cells": int(len(reference)), "reference_rows": int(np.asarray(train_mask).sum()),
        "station_types": {e: STATION_TYPE_NAMES[t] for e, t in sorted(types.items())},
    }
    return out, audit
