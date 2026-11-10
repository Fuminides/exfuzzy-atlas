"""Germany NO2 t+6h task: feature table, feature spec, splits and quality report (AT-070).

    PYTHONPATH=src python -m atlas.domains.air.de_features

Builds ``de_no2_h6`` with the same code, columns and time semantics as ``madrid_no2_h6`` (``features.run``, driven by
``configs/air/de_no2_h6.json``) and adds what A4 needs to rerun the Madrid protocol unchanged:
``feature_spec.json`` (the format of ``configs/ml/madrid_no2_h6_feature_spec.json``), ``splits.json`` (boundaries,
embargo and row counts) and ``quality.json`` (NO2 per split, share of hours in each EAQI NO2 band, meteorological matches).
"""

# ruff: noqa: E501  (SQL, URLs and prose templates)

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from atlas.contracts.models import SCHEMA_VERSION
from atlas.domains.air import features
from atlas.domains.air.association import ASSOCIATION_COLUMNS, Point, build_association
from atlas.paths import PROCESSED_DIR, REPO_ROOT

CONFIG_PATH = REPO_ROOT / "configs" / "air" / "de_no2_h6.json"
SPEC_PATH = REPO_ROOT / "configs" / "air" / "de_no2_h6_feature_spec.json"
DOC_PATH = REPO_ROOT / "docs" / "air" / "de_no2_h6_quality.md"
ICA_PATH = REPO_ROOT / "configs" / "ml" / "ica_no2_scheme.json"
CAP_SENSITIVITY_M = (5_000, 10_000, 15_000, 25_000, 50_000)
SPLITS = ("train", "validation", "test")


def load_config(path: Path | None = None) -> dict:
    return json.loads((path or CONFIG_PATH).read_text(encoding="utf-8"))


# ----------------------------------------------------------------------------------------- spec/splits


def feature_spec(config: dict) -> dict:
    """``feature_spec.json`` payload (``docs/api.md``): per recommended feature (and per feature with ``in_spec``: an
    input of a published model that ``complete`` does not require, e.g. ``no2_yday_valid``) ``unit``, ``source_id`` and
    ``lag_hours``."""
    sources = {"no2": config["no2_source"]["source_id"], "meteo": config["meteo_source"]["source_id"], "calendar": "calendar"}
    units = {**features.UNITS, **config.get("units", {})}
    out = {}
    for feat in config["features"]:
        if not (feat["recommended"] or feat.get("in_spec")):
            continue
        kind = feat["kind"]
        lag = float(-feat["key_offset_hours"]) if kind != "calendar" else 0.0
        unit_key = {"no2": "no2", "meteo": feat.get("variable"), "calendar": feat["name"]}[kind]
        out[feat["name"]] = {"unit": units[unit_key], "source_id": sources[kind], "lag_hours": lag}
    return {"schema_version": SCHEMA_VERSION, "features": out}


def split_windows(config: dict) -> dict[str, tuple[str, str]]:
    sp = config["split"]
    return {name: (sp[f"{name}_from_utc"], sp[f"{name}_to_utc"]) for name in SPLITS}


def band_sql(scheme: dict, column: str = "target") -> str:
    """CASE expression classifying ``column``: round half up, then the first band whose upper limit is >= the value."""
    v = f"floor({column} + 0.5)"
    parts = [f"WHEN {column} IS NULL THEN NULL"]
    for c in scheme["classes"]:
        if c["upper"] is None:
            parts.append(f"ELSE '{c['label']}'")
        else:
            parts.append(f"WHEN {v} <= {c['upper']} THEN '{c['label']}'")
    return "CASE " + " ".join(parts) + " END"


# ------------------------------------------------------------------------------------------- quality


def split_summary(con, config: dict) -> dict:
    """Rows, targets and complete rows per split (issue-hour windows), with the NO2 distribution of the target."""
    out = {}
    for name, (lo, hi) in split_windows(config).items():
        where = f"issued_at_utc >= TIMESTAMPTZ '{lo}' AND issued_at_utc < TIMESTAMPTZ '{hi}'"
        rows, with_target, complete, stations = con.execute(
            f"SELECT count(*), count(target), count(*) FILTER (WHERE complete), count(DISTINCT entity_id) FILTER (WHERE complete) FROM tbl WHERE {where}"
        ).fetchone()
        dist = {}
        for label, cond in (("target_not_null", "target IS NOT NULL"), ("complete", "complete")):
            r = con.execute(
                f"SELECT count(*), avg(target), stddev_samp(target), min(target), quantile_cont(target, [0.05, 0.25, 0.5, 0.75, 0.95, 0.99]), max(target) "
                f"FROM tbl WHERE {where} AND {cond}"
            ).fetchone()
            dist[label] = {
                "n": int(r[0]), "mean": r[1], "std": r[2], "min": r[3],
                "p05": r[4][0], "p25": r[4][1], "p50": r[4][2], "p75": r[4][3], "p95": r[4][4], "p99": r[4][5], "max": r[5],
            }
        out[name] = {
            "issued_from_utc": lo, "issued_to_utc": hi, "rows": int(rows), "rows_with_target": int(with_target),
            "complete_rows": int(complete), "stations_with_complete_rows": int(stations), "target_distribution": dist,
        }
    return out


def band_shares(con, config: dict, scheme: dict) -> dict:
    """Share of rows (target not null / complete) in each band of ``scheme``, per split."""
    expr = band_sql(scheme)
    labels = [c["label"] for c in scheme["classes"]]
    out = {}
    for name, (lo, hi) in split_windows(config).items():
        where = f"issued_at_utc >= TIMESTAMPTZ '{lo}' AND issued_at_utc < TIMESTAMPTZ '{hi}'"
        per = {}
        for label, cond in (("target_not_null", "target IS NOT NULL"), ("complete", "complete")):
            counts = dict(con.execute(f"SELECT {expr} AS band, count(*) FROM tbl WHERE {where} AND {cond} GROUP BY ALL").fetchall())
            total = sum(counts.values())
            per[label] = {
                "n": int(total),
                "bands": {b: {"n": int(counts.get(b, 0)), "share": (counts.get(b, 0) / total) if total else None} for b in labels},
            }
        out[name] = per
    return out


def mean_target_by_station_type(con, config: dict, stations: dict) -> dict:
    types = pd.DataFrame(
        [{"entity_id": f["id"], "station_type": f["properties"]["attributes"].get("station_type") or "unknown",
          "station_area": f["properties"]["attributes"].get("station_area") or "unknown"} for f in stations["features"]]
    )
    con.register("station_types", types)
    out = {}
    for name, (lo, hi) in split_windows(config).items():
        rows = con.execute(
            f"SELECT station_type, station_area, count(DISTINCT entity_id), count(*), avg(target) FROM tbl JOIN station_types USING (entity_id) "
            f"WHERE issued_at_utc >= TIMESTAMPTZ '{lo}' AND issued_at_utc < TIMESTAMPTZ '{hi}' AND complete GROUP BY ALL ORDER BY ALL"
        ).fetchall()
        out[name] = [{"station_type": t, "station_area": a, "stations": int(s), "complete_rows": int(n), "mean_target": m} for t, a, s, n, m in rows]
    return out


def meteo_matches(con, config: dict, processed: Path, entities: list[str], assoc: pd.DataFrame) -> dict:
    """Distance of the primary meteorological station per variable, cap sensitivity and why meteo inputs are NULL."""
    variables = config["association"]["variables"]
    cap = float(config["association"]["max_distance_m"])
    primary = assoc[assoc["rank"] == 1]
    per_variable = {}
    for v in variables:
        d = primary[primary["variable"] == v]["distance_m"]
        per_variable[v] = {
            "stations_with_candidate": int(len(d)), "stations_without_candidate": int(len(entities) - len(d)),
            "distance_m": {k: (float(x) if len(d) else None) for k, x in zip(
                ("min", "p25", "p50", "p75", "p90", "max"), d.quantile([0, .25, .5, .75, .9, 1]).tolist() if len(d) else [None] * 6, strict=True)},
        }
    # Sensitivity of the station coverage to the cap: nearest station with valid values at any distance up to the largest cap.
    air_geo = json.loads((processed / "stations.geojson").read_text(encoding="utf-8"))["features"]
    meteo_geo = json.loads((processed / "meteo" / "stations.geojson").read_text(encoding="utf-8"))["features"]
    pts = lambda fs: [Point(f["id"], *f["geometry"]["coordinates"][:2], f["properties"].get("name")) for f in fs if f["geometry"]]  # noqa: E731
    valid_hours = {
        (r[0], r[1]): int(r[2])
        for r in con.execute(f"SELECT entity_id, feature_name, count(*) FROM read_parquet('{processed / 'meteo' / 'observations'}/**/*.parquet') WHERE value IS NOT NULL GROUP BY ALL").fetchall()
    }
    air_points = [p for p in pts(air_geo) if p.entity_id in set(entities)]
    far = build_association(air_points, pts(meteo_geo), valid_hours, variables, max_distance_m=max(CAP_SENSITIVITY_M), max_candidates=1)
    nearest = pd.DataFrame(far, columns=list(ASSOCIATION_COLUMNS))
    sensitivity = {}
    for v in variables:
        d = nearest[nearest["variable"] == v].set_index("air_entity_id")["distance_m"]
        sensitivity[v] = {str(int(c)): int((d <= c).sum()) for c in CAP_SENSITIVITY_M}
    con.register("assoc_primary", primary[["air_entity_id", "variable"]])
    reasons = {}
    recommended = {f["variable"]: f["name"] for f in config["features"] if f["kind"] == "meteo"}
    for v, column in recommended.items():
        total_null, no_candidate = con.execute(
            f"SELECT count(*) FILTER (WHERE {column} IS NULL), "
            f"count(*) FILTER (WHERE {column} IS NULL AND entity_id NOT IN (SELECT air_entity_id FROM assoc_primary WHERE variable = '{v}')) FROM tbl"
        ).fetchone()
        reasons[column] = {
            "rows_null": int(total_null),
            "no_station_within_cap": {"rows": int(no_candidate), "missing_reason": "no_observation"},
            "candidate_without_valid_value_that_hour": {"rows": int(total_null - no_candidate), "missing_reason": "no_observation"},
        }
    return {
        "max_distance_m": cap, "per_variable": per_variable, "stations_within_cap_by_cap_m": sensitivity,
        "stations": len(entities), "meteo_null_rows_by_reason": reasons,
    }


def annotate_unassociated(association: dict) -> dict:
    """Add ``unassociated``: every (station, variable) with no meteorological station within the cap, with its missing reason.

    The feature is NULL for those stations at every hour; the canonical reason is ``no_observation`` (there is no record
    for that entity), and the detail says why.
    """
    cap_km = association["max_distance_m"] / 1000
    association["unassociated"] = {
        entity: {
            variable: {
                "missing_reason": "no_observation",
                "detail": f"no DWD station that measures {variable} within {cap_km:g} km: the input is NULL at every hour",
            }
            for variable, candidates in per_variable.items()
            if not candidates
        }
        for entity, per_variable in association["candidates"].items()
        if any(not candidates for candidates in per_variable.values())
    }
    return association


def run(*, processed: Path | None = None, doc_path: Path | None = DOC_PATH, spec_path: Path | None = SPEC_PATH,
        config_path: Path | None = None) -> dict:
    config = load_config(config_path)
    processed = processed or PROCESSED_DIR / "air-de"
    result = features.run(processed=processed, config=config, doc_path=None)
    out_dir = processed / "features" / config["task_id"]
    association_path = out_dir / "association.json"
    association_path.write_text(
        json.dumps(annotate_unassociated(json.loads(association_path.read_text(encoding="utf-8"))), indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    spec = feature_spec(config)
    for path in (out_dir / "feature_spec.json", spec_path):
        if path is not None:
            path.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")

    con = features._connect()
    con.execute(f"CREATE VIEW tbl AS SELECT * FROM read_parquet('{out_dir / 'table'}/**/*.parquet', hive_partitioning=true)")
    ica = json.loads(ICA_PATH.read_text(encoding="utf-8"))
    eaqi = json.loads((REPO_ROOT / config["target_scheme"]).read_text(encoding="utf-8"))
    stations = json.loads((processed / "stations.geojson").read_text(encoding="utf-8"))
    entities = result["card"]["stations"]
    assoc = pd.read_parquet(out_dir / "association.parquet")
    splits = split_summary(con, config)
    quality = {
        "task_id": config["task_id"],
        "data_version": config["data_version"],
        "splits": {"embargo_hours": config["split"]["embargo_hours"], "note": config["split"]["note"], "windows": splits},
        "eaqi": {
            "scheme": config["target_scheme"], "source_url": eaqi["source_url"], "accessed": eaqi["accessed"],
            "equals_ica_no2_madrid": eaqi["equals_ica_no2_madrid"], "comparison_with_ica": eaqi["comparison_with_ica"],
            "boundary_convention": eaqi["boundary_convention"], "shares": band_shares(con, config, eaqi),
        },
        "ica_shares_for_comparison": {"scheme": str(ICA_PATH.relative_to(REPO_ROOT)), "shares": band_shares(con, config, ica)},
        "mean_target_by_station_type": mean_target_by_station_type(con, config, stations),
        "meteo": meteo_matches(con, config, processed, entities, assoc),
    }
    (out_dir / "splits.json").write_text(json.dumps({"embargo_hours": config["split"]["embargo_hours"], "windows": splits}, indent=1) + "\n", encoding="utf-8")
    (out_dir / "quality.json").write_text(json.dumps(quality, indent=1, default=str) + "\n", encoding="utf-8")
    if doc_path is not None:
        from atlas.domains.air.de_report import render_features_markdown

        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(render_features_markdown(result["card"], result["summary"], quality, eaqi), encoding="utf-8")
    con.close()
    return {"card": result["card"], "summary": result["summary"], "quality": quality}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the de_no2_h6 feature/target table and its quality report.")
    parser.add_argument("--config", type=Path, default=None,
                        help="task config of another horizon (default: configs/air/de_no2_h6.json); its spec goes to "
                             "configs/air/<task_id>_feature_spec.json and no markdown report is written")
    parser.add_argument("--processed", type=Path, default=None, help="default: <ATLAS_DATA_DIR>/processed/air-de")
    parser.add_argument("--doc", type=Path, default=DOC_PATH)
    parser.add_argument("--no-doc", action="store_true")
    parser.add_argument("--no-spec", action="store_true", help="do not write configs/air/de_no2_h6_feature_spec.json")
    args = parser.parse_args(argv)
    other = args.config is not None and args.config.resolve() != CONFIG_PATH.resolve()  # never overwrite the h6 files
    task_id = load_config(args.config)["task_id"]
    spec_path = REPO_ROOT / "configs" / "air" / f"{task_id}_feature_spec.json" if other else SPEC_PATH
    result = run(processed=args.processed, doc_path=None if args.no_doc or other else args.doc,
                 spec_path=None if args.no_spec else spec_path, config_path=args.config)
    rows = result["card"]["rows"]["total"]
    complete = sum(r["complete"] for r in result["summary"]["per_year"])
    print(f"{rows} rows, {complete} complete ({100 * complete / rows:.1f} %)", file=sys.stdout)


if __name__ == "__main__":
    main()
