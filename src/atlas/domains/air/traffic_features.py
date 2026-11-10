"""Traffic features per air station for the Madrid NO2 t+6h task (AT-012): table ``madrid_no2_h6_traffic``.

    PYTHONPATH=src python -m atlas.domains.air.traffic_features --write-spec

A SEPARATE table with the same keys ``(entity_id, issued_at_utc)`` as ``madrid_no2_h6`` (which is not rewritten), so a
1:1 join gives "with traffic" versus "without traffic" on identical rows. Time convention of ``madrid_no2_h6``: the row
issued at ``t`` reads only finished hours, i.e. hourly keys ``<= t - 1h`` (an hour with key ``s`` covers ``[s, s+1h)``).

* ``traffic_intensity_last``: mean over the associated measurement points with a valid value of the hour with key
  ``t - 1h`` (veh/h). Associated = points of the monthly location file of that hour inside the association radius.
* ``traffic_intensity_lag24h``: the same one day earlier (key ``t - 25h``).
* ``traffic_n_points``: how many points contributed to ``traffic_intensity_last`` (a count: 0 is a true 0).
* ``traffic_n_associated``: how many points the station has in the association that month (context, not for models).

Missing stays NULL: no associated point, none with a valid value, or an hour outside the traffic period -> NULL. A
station is never given another station's or the city's traffic.
"""

# ruff: noqa: E501  (prose templates and SQL)

from __future__ import annotations

import argparse
import json
import resource
import shutil
import sys
from pathlib import Path

import duckdb

from atlas.domains.air.traffic import SOURCE_ID, UNIT, no2_station_ids
from atlas.paths import PROCESSED_DIR, REPO_ROOT

CONFIG_PATH = REPO_ROOT / "configs" / "air" / "madrid_traffic.json"
SPEC_PATH = REPO_ROOT / "configs" / "air" / "feature_spec_traffic.json"
DOC_PATH = REPO_ROOT / "docs" / "air" / "madrid_no2_h6_traffic.md"
MEMORY_LIMIT = "1GB"
FEATURE_UNITS = {"intensity": UNIT, "n_points": "count", "n_associated": "count"}


def load_config() -> dict:
    full = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return full["feature_table"] | {"association": full["association"]}


def lag_hours(feature: dict) -> int:
    """Age at ``issued_at_utc`` of the hour START of the source hour used (key = ``t - lag_hours``)."""
    return -feature["key_offset_hours"]


def feature_spec(config: dict) -> dict:
    """``feature_spec.json`` payload (``docs/api.md``): per feature ``unit``, ``source_id`` and ``lag_hours``."""
    return {
        "features": {
            f["name"]: {"unit": FEATURE_UNITS[f["kind"]], "source_id": SOURCE_ID, "lag_hours": lag_hours(f)}
            for f in config["features"]
        }
    }


def write_feature_spec(config: dict, path: Path = SPEC_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(feature_spec(config), indent=2) + "\n", encoding="utf-8")
    return path


def feature_cards(config: dict) -> list[dict]:
    """The feature card entries, derived from the config so the card and the SQL cannot diverge."""
    assoc = config["association"]
    where = (
        f"measurement points within {assoc['radius_m']:.0f} m of the air station (kinds {assoc['kinds']}) in the location "
        "file of the month of the source hour; distances per station and month in association.parquet"
    )
    out = []
    for f in config["features"]:
        k = lag_hours(f)
        entry = {
            "name": f["name"],
            "kind": f["kind"],
            "recommended": f["recommended"],
            "unit": FEATURE_UNITS[f["kind"]],
            "source": f"{SOURCE_ID} / traffic_intensity (hourly, from 15-minute records)",
            "source_key_offset_hours": f["key_offset_hours"],
            "lag_hours": k,
            "available_at": f"key + 1h = issued_at_utc - {k - 1}h <= issued_at_utc",
            "spatial_association": where,
        }
        if f["kind"] == "intensity":
            entry["definition"] = (
                f"Mean hourly intensity (veh/h) of the associated points that have a valid value in the hour with key "
                f"issued_at_utc - {k}h. NULL if the station has no associated point that month, none has a valid value, or "
                "the hour is outside the traffic period. A mean over road segments of different size, not a flow through the "
                "station's surroundings."
            )
        elif f["kind"] == "n_points":
            entry["definition"] = (
                f"Number of associated points that contributed to traffic_intensity_last (key issued_at_utc - {k}h). "
                "0 means no point contributed: none associated that month or none with a valid value (see traffic_n_associated); NULL only outside the traffic period."
            )
        else:
            entry["definition"] = (
                f"Number of points in the association of the station in the month of the hour with key issued_at_utc - {k}h. "
                "A static station attribute (it identifies the station); not recommended as a model input."
            )
        out.append(entry)
    return out


def build_table_sql(config: dict) -> str:
    """The SELECT that builds the table (grid x stations, exact-key left joins). Pure string, testable."""
    tz = config["timezone"]
    start, end = config["grid"]["start_utc"], config["grid"]["end_utc"]
    by_kind = {f["kind"]: f for f in config["features"] if f["kind"] != "intensity"}
    intensity = [f for f in config["features"] if f["kind"] == "intensity"]
    last = next(f for f in intensity if lag_hours(f) == 1)

    joins, columns = [], []
    for i, f in enumerate(intensity):
        joins.append(
            f"LEFT JOIN per_hour p{i} ON p{i}.entity_id = g.entity_id AND p{i}.ts = g.t + INTERVAL ({f['key_offset_hours']}) HOUR"
        )
        columns.append(f"p{i}.mean_value AS {f['name']}")
    last_i = intensity.index(last)
    if "n_points" in by_kind:
        n = by_kind["n_points"]
        columns.append(
            f"CASE WHEN g.t + INTERVAL ({n['key_offset_hours']}) HOUR BETWEEN bounds.lo AND bounds.hi "
            f"THEN coalesce(p{last_i}.n_points, 0) END AS {n['name']}"
        )
    if "n_associated" in by_kind:
        a = by_kind["n_associated"]
        joins.append(
            f"LEFT JOIN n_assoc na ON na.air_entity_id = g.entity_id "
            f"AND na.month = strftime(timezone('{tz}', g.t + INTERVAL ({a['key_offset_hours']}) HOUR), '%Y-%m')"
        )
        columns.append(f"CASE WHEN na.n IS NULL THEN 0 ELSE na.n END AS {a['name']}")
    return f"""
WITH grid AS (
    SELECT e.entity_id, t FROM entities e,
    generate_series(TIMESTAMPTZ '{start}', TIMESTAMPTZ '{end}', INTERVAL 1 HOUR) AS s(t)),
bounds AS (SELECT min(timestamp_utc) AS lo, max(timestamp_utc) AS hi FROM traffic_obs),
rule AS (SELECT month, air_entity_id, CAST(traffic_point_id AS VARCHAR) AS point_id FROM assoc WHERE in_rule),
n_assoc AS (SELECT air_entity_id, month, count(*) AS n FROM rule GROUP BY ALL),
per_hour AS (
    SELECT r.air_entity_id AS entity_id, o.timestamp_utc AS ts, avg(o.value) AS mean_value, count(*) AS n_points
    FROM traffic_obs o JOIN rule r ON r.point_id = o.entity_id
        AND r.month = strftime(timezone('{tz}', o.timestamp_utc), '%Y-%m')
    WHERE o.value IS NOT NULL GROUP BY ALL),
base AS (
    SELECT g.entity_id, g.t AS issued_at_utc, {", ".join(columns)}
    FROM grid g CROSS JOIN bounds
    {" ".join(joins)})
SELECT *, year(issued_at_utc) AS year, month(issued_at_utc) AS month FROM base ORDER BY entity_id, issued_at_utc"""


def _connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(f"SET memory_limit='{MEMORY_LIMIT}'")
    con.execute("SET threads=2")
    con.execute("SET TimeZone='UTC'")
    return con


def run(
    *,
    processed: Path | None = None,
    traffic_dir: Path | None = None,
    out_dir: Path | None = None,
    doc_path: Path | None = DOC_PATH,
    config: dict | None = None,
    write_spec: Path | None = None,
) -> dict:
    config = config or load_config()
    processed = processed or PROCESSED_DIR / "air"
    traffic_dir = traffic_dir or processed / "traffic"
    out_dir = out_dir or processed / "features" / config["task_id"]
    observations, association = traffic_dir / "observations", traffic_dir / "association.parquet"
    for path in (observations, association, processed / "observations"):
        if not path.exists():
            raise SystemExit(f"{path} is missing: run atlas.domains.air.traffic (and the AT-010 ingestion) first")

    entities = no2_station_ids(processed)
    con = _connect()
    con.execute(
        f"CREATE VIEW traffic_obs AS SELECT * FROM read_parquet('{observations}/**/*.parquet', hive_partitioning=true)"
    )
    con.execute(f"CREATE VIEW assoc AS SELECT * FROM read_parquet('{association}')")
    con.execute("CREATE TABLE entities AS SELECT unnest(?) AS entity_id", [entities])

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    table_dir = out_dir / "table"
    con.execute(
        f"COPY ({build_table_sql(config)}) TO '{table_dir}' (FORMAT PARQUET, COMPRESSION ZSTD, PARTITION_BY (year, month))"
    )
    n_hours = int(
        con.execute(
            f"SELECT count(*) FROM generate_series(TIMESTAMPTZ '{config['grid']['start_utc']}', "
            f"TIMESTAMPTZ '{config['grid']['end_utc']}', INTERVAL 1 HOUR)"
        ).fetchone()[0]
    )
    con.execute(f"CREATE VIEW tbl AS SELECT * FROM read_parquet('{table_dir}/**/*.parquet', hive_partitioning=true)")
    n_rows = int(con.execute("SELECT count(*) FROM tbl").fetchone()[0])
    if n_rows != len(entities) * n_hours:
        raise SystemExit(f"row count {n_rows} != stations x hours {len(entities) * n_hours}: a join multiplied rows")
    if int(con.execute("SELECT count(DISTINCT (entity_id, issued_at_utc)) FROM tbl").fetchone()[0]) != n_rows:
        raise SystemExit("duplicate (entity_id, issued_at_utc) keys in the traffic feature table")

    base_dir = processed / "features" / config["base_task_id"] / "table"
    if base_dir.exists():
        con.execute(
            f"CREATE VIEW base AS SELECT entity_id, issued_at_utc FROM read_parquet('{base_dir}/**/*.parquet', hive_partitioning=true)"
        )
        matched = int(con.execute("SELECT count(*) FROM tbl JOIN base USING (entity_id, issued_at_utc)").fetchone()[0])
        join_check = {
            "base_table_found": True,
            "rows": n_rows,
            "rows_matching_base_keys": matched,
            "one_to_one": matched == n_rows,
        }
        if matched != n_rows:
            raise SystemExit(f"{n_rows - matched} rows of the traffic table have no row in {config['base_task_id']}")
    else:
        join_check = {
            "base_table_found": False,
            "note": f"{config['base_task_id']} not found: the 1:1 join was not verified",
        }

    names = [f["name"] for f in config["features"]]
    per_station_year = con.execute(
        "SELECT entity_id, year, count(*), "
        + ", ".join(f"count({n})" for n in names)
        + " FROM tbl GROUP BY ALL ORDER BY ALL"
    ).fetchall()
    per_year = con.execute(
        "SELECT year, count(*), " + ", ".join(f"count({n})" for n in names) + " FROM tbl GROUP BY year ORDER BY year"
    ).fetchall()
    no_traffic = con.execute(
        "SELECT entity_id, count(*) FILTER (WHERE traffic_intensity_last IS NOT NULL), count(*) FROM tbl GROUP BY ALL ORDER BY ALL"
    ).fetchall()
    summary = {
        "per_station_year": [
            {
                "entity_id": r[0],
                "year": int(r[1]),
                "rows": int(r[2]),
                **{n: int(v) for n, v in zip(names, r[3:], strict=True)},
            }
            for r in per_station_year
        ],
        "per_year": [
            {"year": int(r[0]), "rows": int(r[1]), **{n: int(v) for n, v in zip(names, r[2:], strict=True)}}
            for r in per_year
        ],
        "stations_without_any_intensity": [e for e, n, _ in no_traffic if n == 0],
    }
    specs = feature_cards(config)
    summary_obs = (
        json.loads((traffic_dir / "ingest_details.json").read_text(encoding="utf-8"))
        if (traffic_dir / "ingest_details.json").exists()
        else {}
    )
    card = {
        "task_id": config["task_id"],
        "base_task_id": config["base_task_id"],
        "data_version": config["data_version"],
        "grid": config["grid"],
        "time_convention": (
            "issued_at_utc = t, as in madrid_no2_h6. An hour with key s (timestamp_utc = start of the hour) is available at s+1h, "
            "so inputs read keys <= t-1h. No target column: join the target of madrid_no2_h6 on (entity_id, issued_at_utc)."
        ),
        "key": ["entity_id", "issued_at_utc"],
        "join_with": f"{config['base_task_id']} on (entity_id, issued_at_utc)",
        "join_check": join_check,
        "features": specs,
        "recommended_features": [s["name"] for s in specs if s["recommended"]],
        "other_columns": {"year, month": "hive partition of issued_at_utc (UTC)"},
        "association": config["association"],
        "inputs": {
            "traffic_data_version": summary_obs.get("data_version"),
            "traffic_sha256_files": len(summary_obs.get("sha256", {})),
        },
        "stations": entities,
        "rows": {"total": n_rows, "stations": len(entities), "hours": n_hours},
        "feature_spec": feature_spec(config)["features"],
    }
    (out_dir / "feature_card.json").write_text(json.dumps(card, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "feature_card.md").write_text(render_card(card), encoding="utf-8")
    (out_dir / "coverage.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    if write_spec is not None:
        write_feature_spec(config, write_spec)
    if doc_path is not None:
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        assoc_summary_path = traffic_dir / "association_summary.json"
        names_by_station = {}
        if assoc_summary_path.exists():
            names_by_station = {
                e["air_entity_id"]: e.get("name") or ""
                for e in json.loads(assoc_summary_path.read_text())["per_station_last_month"]
            }
        doc_path.write_text(render_doc(card, summary, names_by_station), encoding="utf-8")
    con.close()
    return {"card": card, "summary": summary}


def _table(header: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def render_card(card: dict) -> str:
    out = [
        f"# Feature card `{card['task_id']}` ({card['data_version']})",
        "",
        card["time_convention"],
        "",
        f"Claves: {card['key']}. Filas: {card['rows']['total']:,} ({card['rows']['stations']} estaciones x {card['rows']['hours']:,} horas de emisión).",
        f"Unión: {card['join_with']}; comprobación: {card['join_check']}.",
        "",
    ]
    for s in card["features"]:
        out += [
            f"## `{s['name']}`" + ("" if s["recommended"] else " (no recomendada)"),
            "",
            f"- Unidad: `{s['unit']}`; `lag_hours` = {s['lag_hours']}; disponible: {s['available_at']}.",
            f"- {s['definition']}",
            f"- Asociación espacial: {s['spatial_association']}.",
            "",
        ]
    return "\n".join(out)


def render_doc(card: dict, summary: dict, names: dict[str, str]) -> str:
    """Spanish coverage tables (``docs/air/madrid_no2_h6_traffic.md``)."""
    feats = [f["name"] for f in card["features"]]
    rows_year = [
        [r["year"], f"{r['rows']:,}"]
        + [f"{100 * r[n] / r['rows']:.1f} %" for n in feats if n != "traffic_n_associated"]
        for r in summary["per_year"]
    ]
    years = sorted({r["year"] for r in summary["per_station_year"]})
    by_station: dict[str, dict] = {}
    for r in summary["per_station_year"]:
        by_station.setdefault(r["entity_id"], {})[r["year"]] = r
    station_rows = [
        [e, names.get(e, "")]
        + [f"{100 * by_station[e][y]['traffic_intensity_last'] / by_station[e][y]['rows']:.1f} %" for y in years]
        for e in sorted(by_station)
    ]
    return "\n".join(
        [
            f"# Cobertura de la tabla `{card['task_id']}`",
            "",
            "Generado por `python -m atlas.domains.air.traffic_features` (AT-012). No editar a mano. Contexto, regla de asociación y limitaciones: [`madrid_traffic.md`](madrid_traffic.md).",
            "",
            f"Versión: `{card['data_version']}`; filas: {card['rows']['total']:,} = {card['rows']['stations']} estaciones x {card['rows']['hours']:,} horas de emisión (UTC), mismas claves que `madrid_no2_h6` restringidas a {card['grid']['start_utc']} - {card['grid']['end_utc']}.",
            "",
            "## Fracción de filas con cada feature no nula, por año de emisión",
            "",
            _table(["año", "filas"] + [n for n in feats if n != "traffic_n_associated"], rows_year),
            "",
            "## Fracción de filas con `traffic_intensity_last` no nulo, por estación y año",
            "",
            _table(["estación", "nombre"] + [str(y) for y in years], station_rows),
            "",
            "Estaciones sin ninguna hora con tráfico válido: "
            + (", ".join(summary["stations_without_any_intensity"]) or "ninguna")
            + ". Para ellas la feature es nula en todas las filas; no se toma tráfico de otra estación ni de la ciudad.",
            "",
            "## Features",
            "",
            _table(
                ["feature", "unidad", "lag_hours", "recomendada"],
                [
                    [f"`{s['name']}`", s["unit"], s["lag_hours"], "sí" if s["recommended"] else "no"]
                    for s in card["features"]
                ],
            ),
            "",
        ]
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build the madrid_no2_h6_traffic feature table.")
    parser.add_argument("--write-spec", action="store_true", help=f"also write {SPEC_PATH.relative_to(REPO_ROOT)}")
    parser.add_argument("--no-doc", action="store_true")
    args = parser.parse_args(argv)
    result = run(doc_path=None if args.no_doc else DOC_PATH, write_spec=SPEC_PATH if args.write_spec else None)
    rows = result["card"]["rows"]
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(
        f"{rows['total']} rows ({rows['stations']} stations x {rows['hours']} hours), peak RSS {peak:.0f} MB",
        file=sys.stdout,
    )


if __name__ == "__main__":
    main()
