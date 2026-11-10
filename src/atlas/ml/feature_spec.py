"""Write the AT-045 ``feature_spec.json`` of a model from the producer's feature card (AT-041).

``FeatureSpec`` (``atlas.services.layout``) says, per model input, its unit, its ``source_id`` and ``lag_hours``
(``observed_at_utc = issued_at_utc - lag_hours``). For observations, ``lag_hours = -source_key_offset_hours`` of the
feature card (``no2_last`` -> 1, ``no2_lag24h`` -> 25, meteorology -> 1). Calendar features are computed
deterministically from the target time, which is itself ``issued_at_utc + horizon``: they have no observation time,
so they get ``lag_hours = 0`` and ``source_id = "calendar"``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from atlas.services.layout import FeatureSource, FeatureSpec

CALENDAR_SOURCE = "calendar"


def feature_spec_from_card(
    card: Mapping, features: Sequence[str], source_ids: Mapping[str, str]
) -> FeatureSpec:
    """``FeatureSpec`` for ``features`` from ``card["features"]`` (``name``, ``kind``, ``unit``, offset).

    ``source_ids`` maps the card's ``kind`` of observed features (e.g. ``no2``, ``meteo``) to a source id; the kind
    ``calendar`` is always ``"calendar"`` with ``lag_hours = 0``.
    """
    by_name = {f["name"]: f for f in card["features"]}
    out: dict[str, FeatureSource] = {}
    for name in features:
        if name not in by_name:
            raise KeyError(f"feature {name!r} is not in the feature card")
        entry = by_name[name]
        kind = entry["kind"]
        if kind == "calendar":
            source_id, lag = CALENDAR_SOURCE, 0.0
        else:
            if kind not in source_ids:
                raise KeyError(f"no source id given for feature kind {kind!r} (feature {name!r})")
            source_id, lag = source_ids[kind], -float(entry["source_key_offset_hours"])
            if lag < 0:
                raise ValueError(f"{name}: source_key_offset_hours must be <= 0 for an observation, got {-lag}")
        out[name] = FeatureSource(unit=entry.get("unit"), source_id=source_id, lag_hours=lag)
    return FeatureSpec(features=out)


def write_feature_spec(spec: FeatureSpec, path: Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(spec.model_dump(mode="json"), indent=2) + "\n")
