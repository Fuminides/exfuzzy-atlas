"""Parsing and normalisation of Water Quality Explorer payloads into the canonical contract.

* ``parse_result`` turns the API's ``result`` text into ``(value, censoring, missing_reason)``;
* ``local_to_utc`` converts the API's naive Europe/London sample time with a documented DST policy;
* ``observations_frame`` builds canonical long rows (one per sample x determinand) from the CSV pages of one query;
* ``build_entities`` builds the sampling-point :class:`EntityCollection` from the JSON-LD pages.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import pyarrow as pa

from atlas.contracts.models import (
    Domain,
    EntityCollection,
    EntityFeature,
    EntityProperties,
    GeometrySupport,
    MissingReason,
    PointGeometry,
)
from atlas.contracts.observations import OBSERVATION_SCHEMA
from atlas.domains.water.bng import bng_to_wgs84

SOURCE_ID = "uk-water-quality"
TIMEZONE = "Europe/London"
_LONDON = ZoneInfo(TIMEZONE)

CSV_COLUMNS = (
    "id",
    "samplingPoint.notation",
    "samplingPoint.prefLabel",
    "samplingPoint.easting",
    "samplingPoint.northing",
    "samplingPoint.region",
    "samplingPoint.area",
    "samplingPoint.subArea",
    "samplingPoint.samplingPointStatus",
    "samplingPoint.samplingPointType",
    "phenomenonTime",
    "samplingPurpose",
    "sampleMaterialType",
    "determinand.notation",
    "determinand.prefLabel",
    "result",
    "unit",
)
EXTRA_FIELDS = (
    ("sample_id", pa.string()),
    ("observation_id", pa.string()),
    ("determinand_code", pa.string()),
    ("result_raw", pa.string()),
    ("unit_label", pa.string()),
    ("sampling_purpose", pa.string()),
    ("sample_material", pa.string()),
)
OUTPUT_SCHEMA = pa.schema([*OBSERVATION_SCHEMA, *(pa.field(n, t) for n, t in EXTRA_FIELDS)])

_NUMBER = r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"
_PLAIN = re.compile(rf"^({_NUMBER})$")
_CENSORED = re.compile(rf"^([<>])\s*({_NUMBER})$")
_OBS_ID = re.compile(r"/sampling-point/([^/]+)/sample/(\d+)/observation/([^/]+)$")
_WKT_POINT = re.compile(r"^POINT\s*\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)")


@dataclass(frozen=True)
class ParsedResult:
    value: float | None
    censoring: str | None  # "left" for "<", "right" for ">"
    missing_reason: str | None


def parse_result(text: str | None) -> ParsedResult:
    """Interpret the API's ``result`` string.

    ``"<0.03"`` is left-censored at 0.03 (the value kept is the reported limit, not an estimate of the true value);
    ``">20"`` is right-censored; a plain number is a measurement; an empty string is ``no_observation``; anything else
    (or a non-positive detection limit, or a non-finite number) is ``invalid_observation``.
    """
    raw = (text or "").strip()
    if not raw:
        return ParsedResult(None, None, MissingReason.NO_OBSERVATION.value)
    match = _PLAIN.match(raw)
    if match:
        value = float(match.group(1))
        if math.isfinite(value):
            return ParsedResult(value, None, None)
    match = _CENSORED.match(raw)
    if match:
        limit = float(match.group(2))
        if math.isfinite(limit) and limit > 0:
            return ParsedResult(limit, "left" if match.group(1) == "<" else "right", None)
    return ParsedResult(None, None, MissingReason.INVALID_OBSERVATION.value)


def local_to_utc(naive: datetime) -> tuple[datetime, str | None]:
    """Naive Europe/London wall-clock time -> aware UTC, plus ``"ambiguous"`` / ``"nonexistent"`` / ``None``.

    Policy (PEP 495, ``fold=0``): in the autumn repeated hour the *first* occurrence (BST, UTC+1) is assumed; a
    wall-clock time inside the spring gap cannot exist, so it is read with the pre-transition offset (GMT), as if
    the sampler's clock had not yet been advanced. Both cases are counted and reported, never silent. Evidence
    that the API publishes local wall-clock time rather than UTC is in ``docs/water/profile.md``.
    """
    first = naive.replace(tzinfo=_LONDON, fold=0)
    second = naive.replace(tzinfo=_LONDON, fold=1)
    kind = None
    if first.utcoffset() != second.utcoffset():
        kind = "ambiguous" if first.utcoffset() > second.utcoffset() else "nonexistent"
    return first.astimezone(timezone.utc), kind


@dataclass
class Stats:
    """Counters accumulated while normalising; every number in the quality report comes from here."""

    counters: Counter = field(default_factory=Counter)
    unit_labels: Counter = field(default_factory=Counter)
    qualifiers: Counter = field(default_factory=Counter)
    dst_examples: dict[str, list[str]] = field(default_factory=lambda: {"ambiguous": [], "nonexistent": []})
    dropped_duplicates: list[str] = field(default_factory=list)


def read_csv_pages(pages: list[bytes]) -> pd.DataFrame:
    """Concatenate CSV pages of one query (all text; the header of every page must match ``CSV_COLUMNS``)."""
    frames = []
    for body in pages:
        text = body.decode("utf-8-sig")
        header = next(csv.reader(io.StringIO(text)), [])
        if tuple(header) != CSV_COLUMNS:
            raise ValueError(f"unexpected observation CSV header (API schema change?): {header}")
        frames.append(pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=list(CSV_COLUMNS))


def observations_frame(
    raw: pd.DataFrame,
    *,
    features: dict[str, str],
    unit_symbols: dict[str, str],
    data_version: str,
    stats: Stats,
    outlier_rules: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Canonical long rows (``OUTPUT_SCHEMA`` column order) from the raw CSV rows of one query.

    Args:
        raw: output of :func:`read_csv_pages`.
        features: determinand code -> ``feature_name``.
        unit_symbols: API unit label (e.g. ``MILLIGRAM PER LITRE``) -> symbol (``mg/l``) from the unit codelist.
        data_version: stamped on every row.
        stats: counters, updated in place.
        outlier_rules: ``feature_name -> maximum plausible value``; values above it are counted, not altered.

    Rows with the same ``(entity_id, timestamp_utc, feature_name)`` would break the uniqueness key of the contract;
    the one with the smallest ``observation_id`` is kept and the others are counted and listed in ``stats``.
    """
    c = stats.counters
    c["raw_rows"] += len(raw)
    if raw.empty:
        return pd.DataFrame(columns=[f.name for f in OUTPUT_SCHEMA])
    unknown = sorted(set(raw["determinand.notation"]) - set(features))
    if unknown:
        raise ValueError(f"determinands not in the configuration: {unknown}")

    ids = raw["id"].str.extract(_OBS_ID)
    if ids.isna().any().any():
        raise ValueError("observation id does not match .../sampling-point/<pt>/sample/<n>/observation/<det>")
    point, sample, _det = ids[0], ids[1], ids[2]
    if (point != raw["samplingPoint.notation"]).any() or (_det != raw["determinand.notation"]).any():
        raise ValueError("observation id disagrees with samplingPoint.notation / determinand.notation")

    parsed = [parse_result(t) for t in raw["result"]]
    local = pd.to_datetime(raw["phenomenonTime"], format="%Y-%m-%dT%H:%M:%S")
    converted = {t: local_to_utc(t.to_pydatetime()) for t in local.unique()}
    for t, (_, kind) in converted.items():
        if kind:
            stats.dst_examples[kind].append(t.isoformat())
    utc = pd.Series([converted[t][0] for t in local], index=raw.index)
    kinds = pd.Series([converted[t][1] for t in local], index=raw.index)
    c["dst_ambiguous_rows"] += int((kinds == "ambiguous").sum())
    c["dst_nonexistent_rows"] += int((kinds == "nonexistent").sum())

    feature = raw["determinand.notation"].map(features)
    out = pd.DataFrame(
        {
            "domain": Domain.WATER.value,
            "entity_id": point,
            "timestamp_utc": pd.to_datetime(utc, utc=True).astype("datetime64[us, UTC]"),
            "source_timestamp_local": raw["phenomenonTime"],
            "timezone": TIMEZONE,
            "feature_name": feature,
            "value": [p.value for p in parsed],
            "unit": [unit_symbols.get(u, u) for u in raw["unit"]],
            "validity_flag": None,  # the API publishes no validity / QA code
            "missing_reason": [p.missing_reason for p in parsed],
            "censoring": [p.censoring for p in parsed],
            "source_id": SOURCE_ID,
            "data_version": data_version,
            "aggregation_window_start_utc": pd.NaT,
            "aggregation_window_end_utc": pd.NaT,
            "n_records": pd.array([None] * len(raw), dtype="Int64"),
            "sample_id": point + "/" + sample,
            "observation_id": raw["id"].str.extract(r"/sampling-point/(.+)$")[0],
            "determinand_code": raw["determinand.notation"],
            "result_raw": raw["result"],
            "unit_label": raw["unit"],
            "sampling_purpose": raw["samplingPurpose"],
            "sample_material": raw["sampleMaterialType"],
        }
    )
    out["aggregation_window_start_utc"] = pd.Series(pd.NaT, index=out.index, dtype="datetime64[us, UTC]")
    out["aggregation_window_end_utc"] = pd.Series(pd.NaT, index=out.index, dtype="datetime64[us, UTC]")

    out = out.sort_values(["entity_id", "feature_name", "timestamp_utc", "observation_id"], kind="stable")
    duplicate = out.duplicated(["entity_id", "timestamp_utc", "feature_name"], keep="first")
    if duplicate.any():
        c["duplicate_key_rows_dropped"] += int(duplicate.sum())
        stats.dropped_duplicates += out.loc[duplicate, "observation_id"].tolist()
        out = out[~duplicate]

    stats.unit_labels.update(out["unit_label"])
    first_char = out["result_raw"].str[:1]
    stats.qualifiers.update(first_char[first_char.isin(["<", ">"])])
    c["canonical_rows"] += len(out)
    c["valid_rows"] += int(out["value"].notna().sum())
    c["censored_left"] += int((out["censoring"] == "left").sum())
    c["censored_right"] += int((out["censoring"] == "right").sum())
    c["missing_no_observation"] += int((out["missing_reason"] == MissingReason.NO_OBSERVATION.value).sum())
    c["missing_invalid_observation"] += int((out["missing_reason"] == MissingReason.INVALID_OBSERVATION.value).sum())
    c["unit_not_in_codelist"] += int((~out["unit_label"].isin(unit_symbols)).sum())
    c["non_river_sample_material"] += int((out["sample_material"] != "RIVER / RUNNING SURFACE WATER").sum())
    for name, limit in (outlier_rules or {}).items():
        c["outliers_flagged"] += int(((out["feature_name"] == name) & (out["value"] > limit)).sum())
    return out.reset_index(drop=True)


def to_arrow(frame: pd.DataFrame) -> pa.Table:
    """Arrow table with exactly ``OUTPUT_SCHEMA`` (the contract columns plus the identifier extras)."""
    return pa.Table.from_pandas(frame, schema=OUTPUT_SCHEMA, preserve_index=False)


def unit_symbols(pages: list[bytes]) -> dict[str, str]:
    """API unit label -> symbol, from the ``/codelist/unit`` pages (``altLabel``; the label itself if there is none)."""
    out: dict[str, str] = {}
    for body in pages:
        for member in json.loads(body)["member"]:
            out[member["prefLabel"]] = member.get("altLabel") or member["prefLabel"]
    return out


def parse_wkt_point(wkt: str | None) -> tuple[float, float] | None:
    match = _WKT_POINT.match(wkt or "")
    return (float(match.group(1)), float(match.group(2))) if match else None


def read_sampling_points(pages: list[bytes]) -> dict[str, dict]:
    """``notation -> {name, bng, attributes}`` from the JSON-LD ``/sampling-point`` pages."""
    out: dict[str, dict] = {}
    for body in pages:
        for member in json.loads(body)["member"]:
            geometry = member.get("geometry") or {}
            bng = parse_wkt_point(geometry.get("asWKT"))
            if bng and "27700" not in geometry["asWKT"]:
                raise ValueError(f"expected EPSG:27700 coordinates, got {geometry['asWKT']}")
            out[member["notation"]] = {
                "name": member.get("prefLabel"),
                "bng": bng,
                "uri": member["id"],
                "attributes": {
                    "alt_label": member.get("altLabel"),
                    "status": (member.get("samplingPointStatus") or {}).get("prefLabel"),
                    "point_type": (member.get("samplingPointType") or {}).get("notation"),
                    "point_type_label": (member.get("samplingPointType") or {}).get("prefLabel"),
                    "region": (member.get("region") or {}).get("prefLabel"),
                    "area": (member.get("area") or {}).get("prefLabel"),
                    "area_code": (member.get("area") or {}).get("notation"),
                    "sub_area": (member.get("subArea") or {}).get("prefLabel"),
                    "sub_area_code": (member.get("subArea") or {}).get("notation"),
                },
            }
    return out


def build_entities(
    points: dict[str, dict],
    observed: dict[str, dict],
    observation_xy: dict[str, tuple[float, float]],
    *,
    data_version: str,
    api_base: str,
    extent: dict | None = None,
) -> tuple[EntityCollection, dict]:
    """Sampling points as ``observed_point`` entities with WGS84 geometry converted from the official BNG values.

    Args:
        points: output of :func:`read_sampling_points`.
        observed: ``entity_id -> {"n_observations", "n_samples", "first_utc", "last_utc"}`` from the canonical rows.
        observation_xy: BNG easting/northing carried by the observation rows (cross-check and fallback).
        data_version, api_base: stamped on the collection and used to build each ``geometry_source`` URL.
        extent: ``{"lon": [min, max], "lat": [min, max]}``, the dataset's published spatial extent. A published
            coordinate that converts to a place outside it is a placeholder, not a location.

    A point without coordinates, or whose published coordinates fall outside ``extent``, gets ``geometry: null``
    (its raw BNG values stay in the attributes); coordinates are never inferred. Returns the collection and a
    reconciliation report.
    """
    report = {
        "points_in_listing": len(points),
        "points_with_observations": len(observed),
        "observed_not_in_listing": sorted(set(observed) - set(points)),
        "listing_without_coordinates": sorted(k for k, v in points.items() if v["bng"] is None),
        "coordinate_mismatch_listing_vs_observations_m": {},
        "coordinates_outside_extent": {},
    }
    features = []
    for notation in sorted(set(points) | set(observed)):
        entry = points.get(notation)
        bng = entry["bng"] if entry else None
        csv_xy = observation_xy.get(notation)
        if bng and csv_xy and (abs(bng[0] - csv_xy[0]) > 1 or abs(bng[1] - csv_xy[1]) > 1):
            report["coordinate_mismatch_listing_vs_observations_m"][notation] = [bng, csv_xy]
        bng = bng or csv_xy
        geometry, flag = None, None
        if bng:
            lon, lat = bng_to_wgs84(*bng)
            if extent and not (
                extent["lon"][0] <= lon <= extent["lon"][1] and extent["lat"][0] <= lat <= extent["lat"][1]
            ):
                flag = "outside_dataset_extent"
                report["coordinates_outside_extent"][notation] = {"bng": list(bng), "lon_lat": [lon, lat]}
            else:
                geometry = PointGeometry(type="Point", coordinates=(round(lon, 7), round(lat, 7)))
        info = observed.get(notation, {})
        attributes = {
            **(entry["attributes"] if entry else {}),
            "in_listing": entry is not None,
            "coordinate_flag": flag,
            "bng_easting": bng[0] if bng else None,
            "bng_northing": bng[1] if bng else None,
            "coordinate_source": "EPSG:27700 as published (1 m); WGS84 by Helmert (<= 1.5 m from the API's GeoJSON)",
            "n_observations": info.get("n_observations", 0),
            "n_samples": info.get("n_samples", 0),
            "first_sample_utc": info.get("first_utc"),
            "last_sample_utc": info.get("last_utc"),
        }
        features.append(
            EntityFeature(
                type="Feature",
                id=notation,
                geometry=geometry,
                properties=EntityProperties(
                    entity_id=notation,
                    domain=Domain.WATER,
                    name=entry["name"] if entry else None,
                    geometry_support=GeometrySupport.OBSERVED_POINT,
                    geometry_source=f"{api_base.rstrip('/')}/sampling-point/{notation}",
                    timezone=TIMEZONE,
                    attributes=attributes,
                ),
            )
        )
    return EntityCollection(
        type="FeatureCollection", domain=Domain.WATER, data_version=data_version, features=features
    ), report
