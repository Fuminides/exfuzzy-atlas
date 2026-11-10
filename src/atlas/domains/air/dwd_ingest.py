"""DWD hourly meteorology ingestion CLI for the Germany air task (AT-070).

    PYTHONPATH=src python -m atlas.domains.air.dwd_ingest

Reads the station zips of ``dwd-meteo-de`` (air temperature and relative humidity, wind speed, station-level pressure) and
writes, in the layout of the Madrid meteorology (``meteo.py``): ``data/processed/air-de/meteo/{observations/year=/month=,
stations.geojson, quality_report.json, ingest_details.json}``.

Time convention. ``MESS_DATUM`` is UTC for almost every station and variable (each zip's ``Metadaten_Parameter`` file says
"Stundenwerte in UTC"), but the wind series of a few stations recorded on analogue instruments say "Stundenwerte in MEZ"
(the fixed UTC+1, no daylight saving time) for the whole period: those labels are converted (``ts_utc = label - 1 h``) and
the original clock stays in ``source_timestamp_local``. The config chooses which references are accepted
(``accepted_time_references``; Germany: UTC only, see below). A parameter row that says neither stops the ingestion, and
rows with no stated reference or with a refused one are dropped and counted: an unknown clock is not guessed. The DWD files do not say whether the label is the start or
the end of the averaging/observation window (temperature, humidity and pressure come from SYNOP reports at the full hour;
wind is derived from 10-minute means). Atlas needs ``timestamp_utc`` to be the START of an hour whose value is available
at ``timestamp_utc + 1 h``. The label is never later than the end of the data it summarizes, so **the label is taken as
the start of the hour**: the value is then used from ``label + 1 h`` on. If the label is really the end of the window this
only delays the information by one hour; it can never leak the future. (See ``docs/air/de_dwd_meteo.md``.)
"""

# ruff: noqa: E501  (SQL and prose templates)

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import shutil
import sys
import zipfile
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from atlas.contracts.models import (
    Attribution,
    Domain,
    EntityCollection,
    EntityFeature,
    EntityProperties,
    GeometrySupport,
    PointGeometry,
    QualityReport,
)
from atlas.contracts.observations import OBSERVATION_SCHEMA, validate_observations_partitioned
from atlas.domains.air import dwd_download
from atlas.domains.air.eea_ingest import connect, ensure_raw_dir, verify_checksums
from atlas.domains.air.stations import _haversine_m
from atlas.ingest.sources import read_manifest
from atlas.paths import DEFAULT_DATASETS_ROOT, PROCESSED_DIR, REPO_ROOT

CONFIG_PATH = REPO_ROOT / "configs" / "air" / "de_dwd.json"
DOC_PATH = REPO_ROOT / "docs" / "air" / "de_dwd_meteo_quality.md"
MISSING_VALUE = -999.0
RELOCATION_M = 500.0
STATION_PREFIX = "DWD"
# Hours kept: one day before the first grid hour (the grid starts at 2019-01-01T00:00Z and reads key t-1h) up to the end.
KEEP_FROM_UTC = "2018-12-31T00:00:00Z"
KEEP_TO_UTC = "2026-01-01T00:00:00Z"


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def entity_id(station_id: str | int) -> str:
    return f"{STATION_PREFIX}{int(station_id):05d}"


# ------------------------------------------------------------------------------------------ parsing


STATION_LINE = re.compile(
    r"^(?P<id>\d{5})\s+(?P<from>\d{8})\s+(?P<to>\d{8})\s+(?P<height>-?\d+)\s+(?P<lat>-?[\d.]+)\s+(?P<lon>-?[\d.]+)\s+"
    r"(?P<name>.+?)\s{2,}(?P<state>\S+)"
)


def parse_station_list(text: str) -> pd.DataFrame:
    """``*_Stundenwerte_Beschreibung_Stationen.txt``: the data rows are not aligned with the dashed header, so a pattern is used.

    Columns: ``Stations_id, von_datum, bis_datum, Stationshoehe, geoBreite, geoLaenge, Stationsname, Bundesland``.
    """
    rows = []
    for line in text.splitlines()[2:]:
        m = STATION_LINE.match(line)
        if m:
            rows.append([m["id"], m["from"], m["to"], float(m["height"]), float(m["lat"]), float(m["lon"]), m["name"].strip(), m["state"]])
    return pd.DataFrame(
        rows, columns=["Stations_id", "von_datum", "bis_datum", "Stationshoehe", "geoBreite", "geoLaenge", "Stationsname", "Bundesland"]
    )


def read_zip_text(archive: zipfile.ZipFile, prefix: str) -> str:
    members = [n for n in archive.namelist() if n.startswith(prefix) and n.endswith(".txt")]
    if len(members) != 1:
        raise ValueError(f"expected exactly one member {prefix}* in the zip, found {members}")
    return archive.read(members[0]).decode("latin-1")


TIME_REFERENCES = {"UTC": 0, "MEZ": 1}  # label offset from UTC in hours: MEZ is the fixed UTC+1, without daylight saving time


def time_reference_segments(
    parameter_text: str, columns: list[str], period_start: date, period_end: date
) -> dict[str, list[tuple[str, str, str]]]:
    """``{column: [(from YYYYMMDD, to YYYYMMDD, "UTC" | "MEZ")]}`` from a zip's ``Metadaten_Parameter`` file.

    Only the rows of the columns we use that overlap the period count. The reference is what the row's ``Zusatz-Info`` says
    ("Stundenwerte in UTC" / "in MEZ"; the data-source text is the fallback). Anything else, or both at once, is an error:
    an unknown clock must not be guessed.
    """
    reader = csv.reader(io.StringIO(parameter_text), delimiter=";")
    next(reader)
    out: dict[str, list[tuple[str, str, str]]] = {}
    for row in reader:
        if len(row) < 9 or not row[0].strip().isdigit() or row[4].strip() not in columns:
            continue
        begin, end = row[1].strip(), row[2].strip()
        if end < period_start.strftime("%Y%m%d") or begin > period_end.strftime("%Y%m%d"):
            continue
        refs = {ref for ref in TIME_REFERENCES if re.search(rf"\b{ref}\b", row[8])} or {
            ref for ref in TIME_REFERENCES if re.search(rf"\b{ref}\b", row[7])
        }
        if len(refs) != 1:
            raise ValueError(f"time reference of {row[4]} for {begin}-{end} is not UTC or MEZ: {';'.join(row)[:200]}")
        out.setdefault(row[4].strip(), []).append((begin, end, next(iter(refs))))
    return out


def apply_time_reference(
    frame: pd.DataFrame,
    segments: dict[str, list[tuple[str, str, str]]],
    columns: dict[str, str],
    accepted: tuple[str, ...] = tuple(TIME_REFERENCES),
) -> tuple[pd.DataFrame, int, int]:
    """Convert the labels to UTC (a MEZ label is UTC+1: ``ts_utc = label - 1 h``) and add the column ``ref``.

    Dropped, never guessed: rows whose day lies in no stated time-reference segment of their column, and rows whose stated
    reference is not in ``accepted``. Returns the frame, the number of rows without a stated reference and the number of
    rows with a reference that is not accepted.
    """
    frame = frame.copy()
    frame["ref"] = None
    day = frame["label"].str[:8]
    for column, feature in columns.items():
        for begin, end, ref in segments.get(column, []):
            frame.loc[(frame["feature_name"] == feature) & (day >= begin) & (day <= end), "ref"] = ref
    stated = frame["ref"].notna()
    allowed = frame["ref"].isin(accepted)
    frame = frame[allowed].copy()
    frame["ts_utc"] = frame["ts_utc"] - pd.to_timedelta(frame["ref"].map(TIME_REFERENCES).astype(int), unit="h")
    return frame, int((~stated).sum()), int((stated & ~allowed).sum())


def parse_geography(text: str) -> pd.DataFrame:
    """``Metadaten_Geographie_<id>.txt``: height, latitude, longitude and validity range of each station position."""
    rows = []
    for line in text.splitlines()[1:]:
        parts = [p.strip() for p in line.split(";")]
        if len(parts) < 6 or not parts[0].isdigit():
            continue
        rows.append(
            {
                "height_m": float(parts[1]), "lat": float(parts[2]), "lon": float(parts[3]),
                "from": parts[4], "to": parts[5] or "99991231", "name": parts[6] if len(parts) > 6 else "",
            }
        )
    return pd.DataFrame(rows)


def station_position(geo: pd.DataFrame, period_start: date, period_end: date) -> dict | None:
    """Last position overlapping the period, plus the largest displacement among the positions overlapping it."""
    start, end = period_start.strftime("%Y%m%d"), period_end.strftime("%Y%m%d")
    inside = geo[(geo["to"] >= start) & (geo["from"] <= end)].sort_values("from")
    if inside.empty:
        return None
    last = inside.iloc[-1]
    moved = max(
        (_haversine_m(a.lon, a.lat, b.lon, b.lat) for a in inside.itertuples() for b in inside.itertuples()), default=0.0
    )
    return {
        "lon": float(last.lon), "lat": float(last.lat), "height_m": float(last.height_m),
        "name": last["name"], "positions_in_period": int(len(inside)), "max_displacement_m": round(moved, 1),
    }


def parse_product(text: str, columns: dict[str, str]) -> pd.DataFrame:
    """One ``produkt_*`` file as a long frame: ``ts_utc`` (label), ``feature_name``, ``value`` (NaN if missing), ``qn``.

    The label ``MESS_DATUM`` (YYYYMMDDHH, UTC) is returned as it is: see the module docstring for why it is taken as the
    start of the hour. ``qn`` is the quality level column of the file (``QN_*``) as an integer.
    """
    frame = pd.read_csv(io.StringIO(text), sep=";", skipinitialspace=True, dtype=str)
    frame.columns = [c.strip() for c in frame.columns]
    qn_columns = [c for c in frame.columns if c.startswith("QN")]
    if len(qn_columns) != 1:
        raise ValueError(f"expected one QN column, found {qn_columns}")
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise ValueError(f"column(s) {missing} not in the file (columns: {list(frame.columns)})")
    stamp = pd.to_datetime(frame["MESS_DATUM"].str.strip(), format="%Y%m%d%H", utc=True)
    qn = pd.to_numeric(frame[qn_columns[0]], errors="coerce").fillna(-999).astype(int)
    parts = []
    for column, feature in columns.items():
        value = pd.to_numeric(frame[column], errors="coerce")
        value = value.where(value > MISSING_VALUE + 0.5)
        parts.append(pd.DataFrame({"ts_utc": stamp, "feature_name": feature, "value": value, "qn": qn, "label": frame["MESS_DATUM"].str.strip()}))
    return pd.concat(parts, ignore_index=True)


def to_observation_table(frame: pd.DataFrame, station: str, units: dict[str, str], data_version: str, source_id: str, timezone: str) -> pa.Table:
    """Canonical rows: a NaN value is NULL + ``no_observation`` (the file row exists but holds the missing-value code)."""
    n = len(frame)
    value = frame["value"].to_numpy(dtype="float64")
    has = ~np.isnan(value)
    reason = np.where(has, None, "no_observation")
    cols = {
        "domain": pa.array(["air"] * n, pa.string()),
        "entity_id": pa.array([station] * n, pa.string()),
        "timestamp_utc": pa.array(frame["ts_utc"].dt.tz_convert("UTC").dt.as_unit("us"), pa.timestamp("us", tz="UTC")),
        "source_timestamp_local": pa.array((frame["label"] + " " + frame["ref"]).to_numpy(dtype=object), pa.string()),
        "timezone": pa.array([timezone] * n, pa.string()),
        "feature_name": pa.array(frame["feature_name"].to_numpy(dtype=object), pa.string()),
        "value": pa.array(np.where(has, value, np.nan), pa.float64(), mask=~has),
        "unit": pa.array([units[f] for f in frame["feature_name"]], pa.string()),
        "validity_flag": pa.array(frame["qn"].astype(str).to_numpy(dtype=object), pa.string()),
        "missing_reason": pa.array(reason, pa.string()),
        "censoring": pa.array([None] * n, pa.string()),
        "source_id": pa.array([source_id] * n, pa.string()),
        "data_version": pa.array([data_version] * n, pa.string()),
        "aggregation_window_start_utc": pa.array([None] * n, pa.timestamp("us", tz="UTC")),
        "aggregation_window_end_utc": pa.array([None] * n, pa.timestamp("us", tz="UTC")),
        "n_records": pa.array([None] * n, pa.int64()),
    }
    return pa.table(cols, schema=OBSERVATION_SCHEMA)


# ------------------------------------------------------------------------------------------ conversion


def convert(config: dict, raw: Path, staging: Path) -> dict:
    """Parse every selected zip into staged Parquet parts (one per station and product). Returns the inventory."""
    meteo = config["meteo"]
    start, end = date.fromisoformat(meteo["period_start"]), date.fromisoformat(meteo["period_end"])
    keep_from, keep_to = pd.Timestamp(KEEP_FROM_UTC), pd.Timestamp(KEEP_TO_UTC)
    accepted = tuple(meteo.get("accepted_time_references", TIME_REFERENCES))
    manifest = read_manifest(raw)
    by_product: dict[str, dict[str, list[tuple[str, Path]]]] = {}
    for entry in manifest.files:
        if not entry.path.startswith(("historical/", "recent/")):
            continue
        m = re.match(r"(historical|recent)/stundenwerte_([A-Z0-9]+)_(\d{5})_", entry.path)
        kind, code, station = m.groups()
        by_product.setdefault(code, {}).setdefault(station, []).append((kind, raw / entry.path))
    staging.mkdir(parents=True, exist_ok=True)
    inventory = {"zips": 0, "stations": {}, "time_reference_rows_checked": 0, "zips_without_rows_in_period": 0, "rows_without_time_reference_dropped": 0, "rows_with_refused_time_reference": 0, "time_references": {}, "rows_read": 0, "rows_kept": 0, "duplicate_rows_dropped": 0, "positions": {}}
    part = 0
    for product in meteo["products"]:
        stations = by_product.get(product["code"], {})
        inventory["stations"][product["key"]] = len(stations)
        for station, files in sorted(stations.items()):
            frames = []
            for kind, path in sorted(files, key=lambda kf: kf[0] != "historical"):  # historical first: it wins on overlap
                with zipfile.ZipFile(path) as archive:
                    frame = parse_product(read_zip_text(archive, product["product_file"]), product["columns"])
                    parameter_text = read_zip_text(archive, "Metadaten_Parameter")
                    geo = parse_geography(read_zip_text(archive, "Metadaten_Geographie"))
                inventory["zips"] += 1
                # rows of the file that can matter: a day of margin around the kept window, in either clock
                near = frame[(frame["ts_utc"] >= keep_from - pd.Timedelta(days=1)) & (frame["ts_utc"] < keep_to + pd.Timedelta(days=1))]
                if near.empty:  # the file name overlaps the period but the file holds no row in it
                    inventory["zips_without_rows_in_period"] += 1
                    continue
                try:
                    segments = time_reference_segments(parameter_text, list(product["columns"]), start, end)
                    frame, dropped, refused = apply_time_reference(near, segments, product["columns"], accepted)
                    inventory["rows_without_time_reference_dropped"] += dropped
                    inventory["rows_with_refused_time_reference"] += refused
                except ValueError as error:
                    raise ValueError(f"{path.name}: {error}") from error
                for column, segs in segments.items():
                    for ref in {r for *_, r in segs}:
                        inventory["time_references"].setdefault(ref, set()).add(f"{entity_id(station)}:{column}")
                inventory["time_reference_rows_checked"] += sum(len(v) for v in segments.values())
                frame = frame[(frame["ts_utc"] >= keep_from) & (frame["ts_utc"] < keep_to)]
                if frame.empty:
                    inventory["zips_without_rows_in_period"] += 1
                    continue
                inventory["rows_read"] += len(frame)
                frame["kind"] = kind
                frames.append(frame)
                position = station_position(geo, start, end)
                if position:
                    inventory["positions"].setdefault(entity_id(station), position)
            if not frames:
                continue
            both = pd.concat(frames, ignore_index=True)
            kept = both.drop_duplicates(["feature_name", "ts_utc"], keep="first")  # historical rows come first
            inventory["duplicate_rows_dropped"] += len(both) - len(kept)
            inventory["rows_kept"] += len(kept)
            table = to_observation_table(
                kept.sort_values(["feature_name", "ts_utc"]), entity_id(station), meteo["units"],
                config["data_version"], meteo["source_id"], config["timezone"],
            )
            pq.write_table(table, staging / f"part-{part:05d}.parquet", compression="zstd")
            part += 1
    return inventory


def write_partitions(staging: Path, observations: Path) -> None:
    if observations.exists():
        shutil.rmtree(observations)
    con = connect(memory_limit="2GB", temp=staging / "_spill")
    con.execute(
        f"COPY (SELECT *, year(timestamp_utc) AS year, month(timestamp_utc) AS month FROM read_parquet('{staging}/part-*.parquet')) "
        f"TO '{observations}' (FORMAT PARQUET, COMPRESSION ZSTD, PARTITION_BY (year, month))"
    )
    con.close()


def summarize(observations: Path) -> dict:
    con = connect(memory_limit="2GB")
    con.execute(f"CREATE VIEW obs AS SELECT * FROM read_parquet('{observations}/**/*.parquet', hive_partitioning=true)")
    cols = [r[0] for r in con.execute("DESCRIBE obs").fetchall() if r[0] not in ("year", "month")]
    nulls = con.execute("SELECT " + ", ".join(f"count(*) FILTER (WHERE {c} IS NULL)" for c in cols) + " FROM obs").fetchone()
    total, lo, hi = con.execute("SELECT count(*), min(timestamp_utc), max(timestamp_utc) FROM obs").fetchone()
    per_feature = con.execute(
        "SELECT feature_name, count(*), count(value), count(DISTINCT entity_id), min(value), max(value) FROM obs GROUP BY ALL ORDER BY ALL"
    ).fetchall()
    per_station = con.execute(
        "SELECT entity_id, feature_name, count(value), min(timestamp_utc) FILTER (WHERE value IS NOT NULL), "
        "max(timestamp_utc) FILTER (WHERE value IS NOT NULL) FROM obs GROUP BY ALL ORDER BY ALL"
    ).fetchall()
    per_year = con.execute(
        "SELECT feature_name, year(timestamp_utc) AS y, count(value) FROM obs GROUP BY ALL ORDER BY ALL"
    ).fetchall()
    qn = con.execute("SELECT feature_name, validity_flag, count(*) FROM obs GROUP BY ALL ORDER BY ALL").fetchall()
    reasons = dict(con.execute("SELECT coalesce(missing_reason, 'valid'), count(*) FROM obs GROUP BY ALL").fetchall())
    con.close()
    return {
        "rows": int(total), "min_utc": lo, "max_utc": hi,
        "missing_by_column": dict(zip(cols, map(int, nulls), strict=True)),
        "per_feature": [
            {"feature": f, "rows": int(n), "values": int(v), "stations": int(s), "min": lo_, "max": hi_}
            for f, n, v, s, lo_, hi_ in per_feature
        ],
        "per_station": per_station,
        "per_year": [[f, int(y), int(n)] for f, y, n in per_year],
        "qn": [[f, q, int(n)] for f, q, n in qn],
        "by_reason": {k: int(v) for k, v in sorted(reasons.items())},
    }


def build_station_collection(positions: dict[str, dict], station_lists: dict[str, dict], summary: dict, config: dict) -> EntityCollection:
    """One Point per DWD station with at least one value; ``positions`` come from each zip's Metadaten_Geographie."""
    observed: dict[str, dict] = {}
    for entity, feature, n, first, last in summary["per_station"]:
        if not n:
            continue
        info = observed.setdefault(entity, {"features": set(), "first": first, "last": last})
        info["features"].add(feature)
        info["first"], info["last"] = min(info["first"], first), max(info["last"], last)
    meteo = config["meteo"]
    features = []
    for entity in sorted(observed):
        pos = positions.get(entity)
        listed = station_lists.get(entity, {})
        attrs = {
            "in_hourly_data": True,
            "has_official_coordinates": pos is not None,
            "observed_features": sorted(observed[entity]["features"]),
            "first_observation_utc": observed[entity]["first"].isoformat(),
            "last_observation_utc": observed[entity]["last"].isoformat(),
            "dwd_station_id": entity[len(STATION_PREFIX):],
            "bundesland": listed.get("Bundesland"),
        }
        geometry = None
        if pos is not None:
            geometry = PointGeometry(type="Point", coordinates=(pos["lon"], pos["lat"]))
            attrs |= {
                "station_height_m": pos["height_m"], "positions_in_period": pos["positions_in_period"],
                "max_displacement_in_period_m": pos["max_displacement_m"], "geometry_epsg": 4326,
                "geometry_note": "Last position overlapping the period in the zip's Metadaten_Geographie (WGS84).",
            }
        features.append(
            EntityFeature(
                type="Feature", id=entity, geometry=geometry,
                properties=EntityProperties(
                    entity_id=entity, domain=Domain.AIR, name=(pos or {}).get("name") or listed.get("Stationsname") or entity,
                    geometry_support=GeometrySupport.OBSERVED_POINT, geometry_source=meteo["landing_url"],
                    timezone=config["timezone"], attributes=attrs,
                ),
            )
        )
    return EntityCollection(
        type="FeatureCollection", domain=Domain.AIR, data_version=config["data_version"],
        attribution=[Attribution(text=meteo["attribution"], license="CC BY 4.0", url=meteo["landing_url"])], features=features,
    )


def read_station_lists(raw: Path, config: dict) -> dict[str, dict]:
    """Bundesland / name from the recent station lists (historical ones as a fallback)."""
    out: dict[str, dict] = {}
    for kind in ("historical", "recent"):  # recent last: it overrides
        for product in config["meteo"]["products"]:
            path = raw / dwd_download.station_list_path(product, kind)
            if path.exists():
                frame = parse_station_list(path.read_text(encoding="latin-1"))
                for _, row in frame.iterrows():
                    out[entity_id(row["Stations_id"])] = {"Bundesland": row["Bundesland"], "Stationsname": row["Stationsname"]}
    return out


def run(
    *, skip_download: bool = False, refresh: bool = False, datasets_root: str | None = None, out_dir: Path | None = None,
    doc_path: Path | None = DOC_PATH,
) -> dict:
    config = load_config()
    meteo = config["meteo"]
    source_id = meteo["source_id"]
    out_dir = (out_dir or PROCESSED_DIR / "air-de") / "meteo"
    raw = ensure_raw_dir(source_id, datasets_root)
    if not skip_download:
        dwd_download.download(config, raw, refresh=refresh)
    checksums = verify_checksums(raw, source_id)
    manifest = read_manifest(raw)

    out_dir.mkdir(parents=True, exist_ok=True)
    staging = out_dir / "_staging"
    if staging.exists():
        shutil.rmtree(staging)
    inventory = convert(config, raw, staging)
    observations = out_dir / "observations"
    write_partitions(staging, observations)
    shutil.rmtree(staging)

    errors = validate_observations_partitioned(observations, memory_limit="1GB")
    if errors:
        raise SystemExit("canonical meteorological observations violate the contract: " + "; ".join(errors[:10]))
    summary = summarize(observations)
    collection = build_station_collection(inventory["positions"], read_station_lists(raw, config), summary, config)
    (out_dir / "stations.geojson").write_text(
        json.dumps(json.loads(collection.model_dump_json()), indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    covered = [f for f in collection.features if f.geometry is not None]
    lons = [f.geometry.coordinates[0] for f in covered]
    lats = [f.geometry.coordinates[1] for f in covered]
    relocated = {e: p["max_displacement_m"] for e, p in inventory["positions"].items() if p["max_displacement_m"] > RELOCATION_M}
    report = QualityReport(
        source_id=source_id,
        source_url=meteo["landing_url"],
        downloaded_at_utc=manifest.downloaded_at_utc,
        period_start=pd.Timestamp(summary["min_utc"]).date(),
        period_end=pd.Timestamp(summary["max_utc"]).date(),
        license=meteo["license"],
        input_sha256=checksums,
        raw_rows=inventory["rows_read"],
        valid_rows=summary["rows"] - summary["by_reason"].get("no_observation", 0),
        duplicate_rows=inventory["duplicate_rows_dropped"],
        uniqueness_key=["domain", "entity_id", "timestamp_utc", "feature_name", "source_id"],
        missing_by_column=summary["missing_by_column"],
        invalid_codes={},
        outliers_flagged=0,
        date_range_utc=(summary["min_utc"], summary["max_utc"]),
        geographic_coverage={
            "stations_in_hourly_data": len(collection.features),
            "stations_with_official_point": len(covered),
            "bbox_lon_lat": [min(lons), min(lats), max(lons), max(lats)],
            "geometry_source": meteo["landing_url"],
            "geometry_support": "observed_point",
            "stations_relocated_over_500m_in_period": relocated,
        },
        sampling_frequency="hourly; one slot per station x variable x hour; timestamp_utc = label of the DWD hour taken as the start of the hour",
        value_units=dict(meteo["units"]),
        known_limitations=[
            "MESS_DATUM is UTC; the files do not say whether the label is the start or the end of the observation window. The label is "
            "taken as the START of the hour (value usable from label + 1 h): conservative, it can delay by one hour, never leak.",
            "Values equal to -999 (missing) are NULL with missing_reason no_observation; the QN quality level of the file is kept in "
            "validity_flag (QN_9 temperature/humidity, QN_3 wind, QN_8 pressure). Recent files (quality control not finished) fill only "
            "stations without historical files for the end of the period.",
            "Pressure is station-level pressure (P0, hPa), not reduced to sea level: it depends on station altitude and is not recommended as a feature.",
            f"Stations that moved more than {RELOCATION_M:.0f} m inside the period: {relocated or 'none'}; the last position is used.",
        ],
    )
    (out_dir / "quality_report.json").write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    details = {
        "data_version": config["data_version"],
        "downloaded_at_utc": manifest.downloaded_at_utc.isoformat(),
        "dst_anomalies": {},  # UTC source: no local-time anomalies
        "inventory": {
            **{k: v for k, v in inventory.items() if k not in ("positions", "time_references")},
            "time_references": {ref: sorted(items) for ref, items in inventory["time_references"].items()},
            "accepted_time_references": list(meteo.get("accepted_time_references", TIME_REFERENCES)),
        },
        "summary": {k: v for k, v in summary.items() if k not in ("per_station", "min_utc", "max_utc")},
        "relocated_stations": relocated,
        "sha256": checksums,
        "date_range_utc": [summary["min_utc"].isoformat(), summary["max_utc"].isoformat()],
    }
    (out_dir / "ingest_details.json").write_text(json.dumps(details, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    if doc_path is not None:
        from atlas.domains.air.de_report import render_dwd_markdown

        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(render_dwd_markdown(details, report), encoding="utf-8")
    return details


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Ingest DWD hourly meteorology (Germany) into canonical Parquet.")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--download-only", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--datasets-root", default=os.environ.get("ATLAS_DATASETS_ROOT", DEFAULT_DATASETS_ROOT))
    parser.add_argument("--out-dir", type=Path, default=None, help="default: data/processed/air-de (meteo/ below it)")
    parser.add_argument("--doc", type=Path, default=DOC_PATH)
    parser.add_argument("--no-doc", action="store_true")
    args = parser.parse_args(argv)
    if args.download_only:
        config = load_config()
        raw = ensure_raw_dir(config["meteo"]["source_id"], args.datasets_root)
        manifest, fetched = dwd_download.download(config, raw, refresh=args.refresh)
        print(f"{config['meteo']['source_id']}: {len(manifest.files)} files, fetched now: {len(fetched)}")
        return
    details = run(
        skip_download=args.skip_download, refresh=args.refresh, datasets_root=args.datasets_root, out_dir=args.out_dir,
        doc_path=None if args.no_doc else args.doc,
    )
    print(f"{details['summary']['rows']} canonical rows, {details['date_range_utc']}", file=sys.stdout)


if __name__ == "__main__":
    main()
