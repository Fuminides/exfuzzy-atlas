"""EDA of the 1-hour-ahead NYC pickup table (AT-031) and the generated ``docs/mobility/nyc_pickups_h1_eda.md``.

Everything that informs a modelling decision (distribution, per-zone volume, patterns, in-sample variance shares) is computed on
the **train period** only. The monthly table is the one exception: it covers the whole year because it is what justifies the
split, and it is descriptive (no choice in the table depends on it). No model is trained here.
"""

# ruff: noqa: E501  (prose templates)

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from atlas.domains.mobility import aggregate
from atlas.domains.mobility.features import FEATURE_NAMES, TABLE_DIRNAME, TARGET

WEEKDAYS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def _train_view(con: duckdb.DuckDBPyConnection, table_dir: Path, config: dict) -> None:
    lo, hi = _utc(config["split"]["train"][0]), _utc(config["split"]["train"][1])
    con.execute(f"CREATE VIEW tbl AS SELECT * FROM read_parquet('{table_dir}/**/*.parquet', hive_partitioning=true)")
    con.execute(
        f"CREATE VIEW tr AS SELECT * FROM tbl WHERE issued_at_utc >= TIMESTAMPTZ '{lo.isoformat()}' "
        f"AND issued_at_utc < TIMESTAMPTZ '{hi.isoformat()}' AND {TARGET} IS NOT NULL"
    )


def compute(table_dir: Path, config: dict, *, memory_limit: str = "1500MB", threads: int = 4) -> dict:
    """All statistics of the EDA as a JSON-able dict. ``table_dir`` is ``.../features/nyc_pickups_h1``."""
    features_dir = table_dir.parent
    report = json.loads((features_dir / f"{TABLE_DIRNAME}_feature_report.json").read_text(encoding="utf-8"))
    selection = json.loads((features_dir / f"{TABLE_DIRNAME}_zone_selection.json").read_text(encoding="utf-8"))
    zones = selection["zones"]
    con = aggregate.connect(memory_limit, threads)
    _train_view(con, table_dir, config)

    n, zero, mean, var, skew, q = con.execute(
        f"SELECT count(*), count(*) FILTER (WHERE {TARGET} = 0), avg({TARGET}), var_pop({TARGET}), skewness({TARGET}), "
        f"quantile_cont({TARGET}, [0.5, 0.75, 0.9, 0.99, 0.999]) FROM tr"
    ).fetchall()[0]
    max_y, n100, share_top1 = con.execute(
        f"SELECT max({TARGET}), count(*) FILTER (WHERE {TARGET} >= 100), "
        f"(SELECT sum({TARGET}) FROM (SELECT {TARGET} FROM tr ORDER BY {TARGET} DESC LIMIT (SELECT (count(*) * 0.01)::BIGINT FROM tr))) / sum({TARGET}) FROM tr"
    ).fetchall()[0]
    skew_log = con.execute(f"SELECT skewness(ln(1 + {TARGET})) FROM tr").fetchall()[0][0]
    positive_q = con.execute(f"SELECT quantile_cont({TARGET}, [0.5, 0.9]) FROM tr WHERE {TARGET} > 0").fetchall()[0][0]
    distribution = {
        "rows": n,
        "zero_rows": zero,
        "share_zero": zero / n,
        "mean": mean,
        "variance": var,
        "variance_to_mean": var / mean,
        "skewness": skew,
        "skewness_log1p": skew_log,
        "quantiles": dict(zip(["p50", "p75", "p90", "p99", "p99_9"], q, strict=True)),
        "max": max_y,
        "rows_target_ge_100": n100,
        "share_of_volume_in_top_1pct_rows": share_top1,
        "positive_quantiles": {"p50": positive_q[0], "p90": positive_q[1]},
    }

    per_zone = con.execute(
        f"SELECT entity_id, sum({TARGET}) AS pickups, avg({TARGET}) AS mean_h, avg(({TARGET} = 0)::INT) AS zero_share, count(*) AS n FROM tr "
        f"GROUP BY entity_id ORDER BY pickups DESC"
    ).fetchall()
    total_selected = sum(r[1] for r in per_zone)
    all_zone_pickups = sum(z["train_pickups"] for z in zones)
    cum = {}
    running = 0.0
    for i, r in enumerate(per_zone, 1):
        running += r[1]
        if i in (1, 5, 10, 25, 50) or i == len(per_zone):
            cum[i] = running / total_selected
    names = {z["entity_id"]: z.get("name") for z in zones}
    zone_mean_q = dict(
        zip(
            ["min", "p25", "p50", "p75", "max"],
            con.execute(
                f"SELECT min(m), quantile_cont(m, 0.25), quantile_cont(m, 0.5), quantile_cont(m, 0.75), max(m) "
                f"FROM (SELECT avg({TARGET}) AS m FROM tr GROUP BY entity_id)"
            ).fetchall()[0],
            strict=True,
        )
    )
    volume = {
        "selected_zones": len(per_zone),
        "mean_per_hour_quantiles_selected": zone_mean_q,
        "cumulative_share_of_selected_volume_top_k": cum,
        "top": [
            {"zone": r[0], "name": names.get(r[0]), "pickups": int(r[1]), "mean_per_hour": r[2], "zero_share": r[3]}
            for r in per_zone[:10]
        ],
        "selected_share_of_all_train_pickups": total_selected / all_zone_pickups,
        "sensitivity": [
            {
                "min_mean_per_hour": t,
                "zones": sum(
                    1
                    for z in zones
                    if z["train_mean_pickups_per_hour"] is not None and z["train_mean_pickups_per_hour"] >= t
                ),
                "share_of_train_pickups": sum(
                    z["train_pickups"]
                    for z in zones
                    if z["train_mean_pickups_per_hour"] is not None and z["train_mean_pickups_per_hour"] >= t
                )
                / all_zone_pickups,
            }
            for t in (0.25, 0.5, 1.0, 2.0, 5.0)
        ],
        "excluded": {
            "zones": sum(1 for z in zones if not z["included"]),
            "zero_pickup_all_period": [z["entity_id"] for z in zones if z["train_pickups"] == 0],
            "borough_counts": _borough_counts(zones),
            "all": [
                {
                    "entity_id": z["entity_id"],
                    "name": z.get("name"),
                    "borough": z.get("borough") or "n/a",
                    "rate": z["train_mean_pickups_per_hour"],
                }
                for z in zones
                if not z["included"]
            ],
            "highest_excluded": sorted(
                (z for z in zones if not z["included"] and z["train_mean_pickups_per_hour"] is not None),
                key=lambda z: -z["train_mean_pickups_per_hour"],
            )[:5],
        },
    }
    selected_ids = [z["entity_id"] for z in zones if z["included"]]
    obs_dir = table_dir.parents[1] / "observations"
    filter_cost = {}
    if obs_dir.exists():
        con.execute("CREATE TEMP TABLE sel(entity_id VARCHAR)")
        con.executemany("INSERT INTO sel VALUES (?)", [[e] for e in selected_ids])
        con.execute(
            f"CREATE VIEW obs AS SELECT CAST(entity_id AS VARCHAR) AS entity_id, timestamp_utc AS ts, value "
            f"FROM read_parquet('{obs_dir}/**/*.parquet', hive_partitioning=true)"
        )
        for name in ("train", "validation", "test"):
            lo, hi = _utc(config["split"][name][0]), _utc(config["split"][name][1])
            tot, kept = con.execute(
                "SELECT sum(value), sum(value) FILTER (WHERE entity_id IN (SELECT entity_id FROM sel)) FROM obs WHERE ts >= ? AND ts < ?",
                [lo, hi],
            ).fetchall()[0]
            filter_cost[name] = {
                "all_zone_pickups": int(tot),
                "selected_zone_pickups": int(kept),
                "selected_share": kept / tot,
            }

    hourly = con.execute(
        f"SELECT local_hour, local_dow >= 5 AS weekend, avg({TARGET}), count(*) FROM tr GROUP BY 1, 2 ORDER BY 2, 1"
    ).fetchall()
    weekday = con.execute(f"SELECT local_dow, avg({TARGET}) FROM tr GROUP BY 1 ORDER BY 1").fetchall()
    corr = {}
    for feat in ("pickups_lag1", "pickups_lag2", "pickups_lag24", "pickups_lag168", "pickups_mean24h"):
        pooled = con.execute(
            f"SELECT corr({TARGET}, {feat}), corr(ln(1 + {TARGET}), ln(1 + {feat})) FROM tr WHERE {feat} IS NOT NULL"
        ).fetchall()[0]
        by_zone = con.execute(
            f"SELECT quantile_cont(c, 0.5), min(c), max(c) FROM (SELECT corr({TARGET}, {feat}) c FROM tr WHERE {feat} IS NOT NULL GROUP BY entity_id)"
        ).fetchall()[0]
        corr[feat] = {
            "pooled": pooled[0],
            "pooled_log1p": pooled[1],
            "per_zone_median": by_zone[0],
            "per_zone_min": by_zone[1],
            "per_zone_max": by_zone[2],
        }

    def share(group: str, y: str) -> float:
        return con.execute(
            f"SELECT 1 - sum(pow(y - m, 2)) / sum(pow(y - g, 2)) FROM (SELECT {y} AS y, avg({y}) OVER (PARTITION BY {group}) AS m, avg({y}) OVER () AS g FROM tr)"
        ).fetchall()[0][0]

    in_sample = {
        label: {"raw": share(group, TARGET), "log1p": share(group, f"ln(1 + {TARGET})")}
        for label, group in {
            "zone_mean": "entity_id",
            "zone_x_local_hour": "entity_id, local_hour",
            "zone_x_hour_of_week": "entity_id, local_dow, local_hour",
        }.items()
    }
    months = con.execute(
        f"SELECT year, month, count(*), avg({TARGET}), avg(({TARGET} = 0)::INT) FROM tbl WHERE {TARGET} IS NOT NULL GROUP BY 1, 2 ORDER BY 1, 2"
    ).fetchall()
    group = "CASE WHEN m < 3 THEN '1) < 3/h' WHEN m < 10 THEN '2) 3-10/h' WHEN m < 50 THEN '3) 10-50/h' ELSE '4) >= 50/h' END"
    by_group = con.execute(
        f"WITH zone_train AS (SELECT entity_id, avg({TARGET}) AS m FROM tr GROUP BY entity_id), "
        f"g AS (SELECT entity_id, {group} AS grp FROM zone_train) "
        f"SELECT grp, year, month, avg({TARGET}), avg(({TARGET} = 0)::INT) FROM tbl JOIN g USING (entity_id) "
        f"WHERE {TARGET} IS NOT NULL AND NOT (year = 2025 AND month = 4) GROUP BY 1, 2, 3 ORDER BY 1, 2, 3"
    ).fetchall()
    nulls_by_feature = report["null_counts"]
    con.close()
    return {
        "report": report,
        "config": config,
        "distribution": distribution,
        "volume": volume,
        "filter_cost_by_period": filter_cost,
        "hourly": [{"hour": h, "weekend": bool(w), "mean": m, "n": c} for h, w, m, c in hourly],
        "weekday": [{"dow": d, "mean": m} for d, m in weekday],
        "correlations": corr,
        "in_sample_variance_share": in_sample,
        "months_by_train_volume_group": [
            {"group": g, "month": f"{int(y)}-{int(m):02d}", "mean": a, "zero_share": z} for g, y, m, a, z in by_group
        ],
        "months": [
            {"month": f"{int(y)}-{int(m):02d}", "rows": c, "mean": a, "zero_share": z} for y, m, c, a, z in months
        ],
        "nulls": nulls_by_feature,
    }


def _volume_group_table(rows: list[dict]) -> str:
    months = sorted({r["month"] for r in rows})
    groups = sorted({r["group"] for r in rows})
    cell = {(r["group"], r["month"]): f"{_f(r['mean'], 1)} ({_pct(r['zero_share'], 0)})" for r in rows}
    return _table(["grupo (media de train)", *months], [[g, *[cell.get((g, m), "-") for m in months]] for g in groups])


def _borough_counts(zones: list[dict]) -> dict:
    out: dict[str, dict[str, int]] = {}
    for z in zones:
        key = z.get("borough") or "n/a"
        out.setdefault(key, {"included": 0, "excluded": 0})["included" if z["included"] else "excluded"] += 1
    return dict(sorted(out.items()))


def _table(header: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def _f(x, d=1) -> str:
    return "n/a" if x is None else f"{x:,.{d}f}"


def _pct(x, d=1) -> str:
    return "n/a" if x is None else f"{x:.{d}%}"


def render_markdown(stats: dict) -> str:
    rep, cfg, dist, vol = stats["report"], stats["config"], stats["distribution"], stats["volume"]
    split = cfg["split"]
    p = rep["periods"]
    hourly = {(h["hour"], h["weekend"]): h["mean"] for h in stats["hourly"]}
    lines = [
        "# EDA y recomendación de split: demanda de taxi amarillo a 1 hora (`nyc_pickups_h1`, AT-031)",
        "",
        f"Generado por `python -m atlas.domains.mobility.features --eda` sobre la tabla de `{rep['data_version']}`. No se edita a mano. "
        "Definición de la tabla y de las features en [`nyc_pickups_h1_feature_card.md`](nyc_pickups_h1_feature_card.md). "
        "**Las estadísticas que condicionan decisiones de modelado se calculan solo con el periodo de entrenamiento** "
        f"(emisión en `[{split['train'][0]}, {split['train'][1]})`, filas con target conocido, zonas seleccionadas); la excepción es la tabla mensual, que cubre todo el año "
        "porque es lo que justifica el split y es solo descriptiva. No se ha entrenado ningún modelo: las cifras «in-sample» de abajo son descriptivas de los datos de train, no una evaluación.",
        "",
        "## 1. Tabla",
        "",
        f"- Filas: {rep['rows']:,} = {rep['zones_selected']} zonas × {rep['issue_hours']:,} horas de emisión (comprobado: {rep['rows_expected_zones_x_issue_hours']:,}). "
        f"Completas (target y las {len(FEATURE_NAMES)} features conocidos): **{rep['complete_rows']:,}** ({rep['complete_rows'] / rep['rows']:.2%}); incompletas: {rep['incomplete_rows']:,}, de ellas "
        f"{rep['rows_in_warmup_first_168h']:,} en las primeras 168 h del periodo (el lag semanal cae antes de la cobertura) y {rep['incomplete_rows_after_warmup']:,} por la hora ambigua del cambio de hora de otoño (2024-11-03).",
        "- Nulos por columna: " + ", ".join(f"`{k}`={v:,}" for k, v in stats["nulls"].items()) + ".",
        f"- Zonas: {rep['zones_in_series']} con polígono en la serie; {rep['zones_selected']} entran en la tarea; {vol['excluded']['zones']} quedan como «sin modelo» (lista y motivos en `nyc_pickups_h1_zone_selection.json`).",
        "",
        "## 2. Distribución del target (train, zonas seleccionadas)",
        "",
        _table(
            [
                "filas",
                "% ceros",
                "media",
                "varianza/media",
                "mediana",
                "p75",
                "p90",
                "p99",
                "p99,9",
                "máx",
                "asimetría",
                "asimetría de log1p",
            ],
            [
                [
                    f"{dist['rows']:,}",
                    _pct(dist["share_zero"]),
                    _f(dist["mean"]),
                    _f(dist["variance_to_mean"]),
                    _f(dist["quantiles"]["p50"], 0),
                    _f(dist["quantiles"]["p75"], 0),
                    _f(dist["quantiles"]["p90"], 0),
                    _f(dist["quantiles"]["p99"], 0),
                    _f(dist["quantiles"]["p99_9"], 0),
                    _f(dist["max"], 0),
                    _f(dist["skewness"], 2),
                    _f(dist["skewness_log1p"], 2),
                ]
            ],
        ),
        "",
        f"- Entre las zonas seleccionadas el {_pct(dist['share_zero'])} de las zona-horas es 0 (en las {rep['zones_in_series']} zonas de la serie es el 51 %). "
        f"Entre los valores positivos la mediana es {_f(dist['positive_quantiles']['p50'], 0)} y el p90 {_f(dist['positive_quantiles']['p90'], 0)}.",
        f"- Cola pesada: el 1 % de filas con más recogidas aporta el {_pct(dist['share_of_volume_in_top_1pct_rows'])} del volumen; {dist['rows_target_ge_100']:,} filas ({_pct(dist['rows_target_ge_100'] / dist['rows'])}) tienen ≥ 100 recogidas. "
        f"La varianza es {_f(dist['variance_to_mean'])} veces la media (un conteo de Poisson daría 1): sobredispersión fuerte, en parte porque se mezclan zonas de escala muy distinta.",
        "",
        "## 3. Volumen por zona (train)",
        "",
        f"Filtro de zonas: media de recogidas por hora conocida en train ≥ {cfg['zone_filter']['min_train_mean_pickups_per_hour']:g} (se fija solo con train). "
        f"Las {vol['selected_zones']} zonas seleccionadas reúnen el {_pct(vol['selected_share_of_all_train_pickups'], 2)} de las recogidas de train de las {rep['zones_in_series']} zonas.",
        "",
        _table(
            ["umbral (recogidas/h)", "zonas", "% de las recogidas de train"],
            [
                [f"{s['min_mean_per_hour']:g}", s["zones"], _pct(s["share_of_train_pickups"], 2)]
                for s in vol["sensitivity"]
            ],
        ),
        "",
        "Coste del filtro, en recogidas de las 263 zonas que quedan dentro de las zonas seleccionadas (descriptivo; el filtro no se ha ajustado con esto): "
        + ", ".join(f"{k} {_pct(v['selected_share'], 2)}" for k, v in stats["filter_cost_by_period"].items())
        + ".",
        "",
        "Concentración dentro de las seleccionadas (porcentaje acumulado del volumen): "
        + ", ".join(f"top {k}: {_pct(v)}" for k, v in vol["cumulative_share_of_selected_volume_top_k"].items())
        + f". Recogidas medias por hora entre zonas seleccionadas: mín {_f(vol['mean_per_hour_quantiles_selected']['min'], 2)}, p25 {_f(vol['mean_per_hour_quantiles_selected']['p25'], 1)}, "
        f"mediana {_f(vol['mean_per_hour_quantiles_selected']['p50'], 1)}, p75 {_f(vol['mean_per_hour_quantiles_selected']['p75'], 1)}, máx {_f(vol['mean_per_hour_quantiles_selected']['max'], 0)}: **la escala varía más de dos órdenes de magnitud entre zonas**.",
        "",
        _table(
            ["zona", "nombre", "recogidas (train)", "media/h", "% horas con 0"],
            [
                [t["zone"], t["name"], f"{t['pickups']:,}", _f(t["mean_per_hour"]), _pct(t["zero_share"])]
                for t in vol["top"]
            ],
        ),
        "",
        "Excluidas por barrio (con polígono): "
        + "; ".join(
            f"{b}: {c['excluded']} de {c['included'] + c['excluded']}"
            for b, c in vol["excluded"]["borough_counts"].items()
        )
        + f". Zonas sin ninguna recogida en train: {vol['excluded']['zero_pickup_all_period']}. Las excluidas con más demanda, justo bajo el umbral: "
        + ", ".join(
            f"{z['entity_id']} ({z.get('name')}, {z['train_mean_pickups_per_hour']:.2f}/h)"
            for z in vol["excluded"]["highest_excluded"]
        )
        + ".",
        "",
        "## 4. Patrón horario y semanal (train, media del target por zona-hora seleccionada)",
        "",
        _table(
            ["hora local", "laborable (lun-vie)", "fin de semana (sáb-dom)"],
            [[f"{h:02d}", _f(hourly.get((h, False)), 1), _f(hourly.get((h, True)), 1)] for h in range(24)],
        ),
        "",
        _table(["día", *WEEKDAYS], [["media por zona-hora", *[_f(w["mean"], 1) for w in stats["weekday"]]]]),
        "",
        "Pico vespertino los laborables (17-19 h) y de madrugada los fines de semana (00-02 h, sobre todo la noche del viernes y del sábado): la hora local y el día de la semana **interactúan**, "
        "por eso la feature de hora se acompaña del día. Con la hora codificada 0-23 sin más, la madrugada del sábado y del domingo (00-03 h) queda en el extremo bajo de la escala aunque sea demanda alta; ver la tarjeta de features.",
        "",
        "### Correlación del target con cada feature de historial (train, filas completas)",
        "",
        _table(
            [
                "feature",
                "Pearson agrupada",
                "Pearson agrupada de log1p",
                "mediana por zona",
                "mín por zona",
                "máx por zona",
            ],
            [
                [
                    f"`{k}`",
                    _f(v["pooled"], 3),
                    _f(v["pooled_log1p"], 3),
                    _f(v["per_zone_median"], 3),
                    _f(v["per_zone_min"], 3),
                    _f(v["per_zone_max"], 3),
                ]
                for k, v in stats["correlations"].items()
            ],
        ),
        "",
        "## 5. Varianza explicada «in-sample» por referencias sencillas (train; no es una evaluación)",
        "",
        "Fracción de la varianza total del target en train que explica la media de cada celda calculada sobre esas mismas filas (descriptivo: dice cuánta estructura hay que una climatología por zona ya captura y cuánta escala aporta la identidad de la zona; un modelo real se evalúa fuera de muestra con A4).",
        "",
        _table(
            ["referencia", "R² in-sample (target)", "R² in-sample (log1p del target)"],
            [
                [k.replace("_", " "), _f(v["raw"], 3), _f(v["log1p"], 3)]
                for k, v in stats["in_sample_variance_share"].items()
            ],
        ),
        "",
        "## 6. Evolución mensual (todo el año; solo descriptivo)",
        "",
        _table(
            ["mes (UTC de emisión)", "filas con target", "media por zona-hora", "% ceros"],
            [[m["month"], f"{m['rows']:,}", _f(m["mean"], 1), _pct(m["zero_share"])] for m in stats["months"]],
        ),
        "",
        "Misma evolución por grupo de volumen (el grupo se fija con la media de **train** de cada zona; media del target por zona-hora y, entre paréntesis, % de ceros):",
        "",
        _volume_group_table(stats["months_by_train_volume_group"]),
        "",
        "Las zonas de poco volumen no están estables: en febrero y marzo de 2025 sus medias se multiplican por 2-3 respecto a train mientras las de 10-50/h suben alrededor de un 25 % y las de ≥ 50/h un 5-10 %. Consulta ad hoc sobre los ficheros crudos (no forma parte del pipeline): "
        "en las 57 zonas seleccionadas con < 10 recogidas/h, los viajes del `VendorID` 2 pasan de ~81 k en diciembre a 94 k, 147 k y 206 k en enero, febrero y marzo de 2025, y los del `VendorID` 7 (Helix, ya señalado en la tarjeta de datos por los viajes de duración cero) de 0 en diciembre a 223 en marzo, mientras el `VendorID` 1 cambia poco. "
        "La causa (cambio de proveedor o de cobertura de reporte, más uso de e-hail en barrios exteriores…) **no está verificada**; lo que sí se ve es que el nivel de esas zonas en test no se parece al de train.",
        "",
        "## 7. Split cronológico recomendado para A4",
        "",
        "Por tiempo de emisión (semiabierto `[desde, hasta)`, UTC), con `embargo_hours = 168` (el lag semanal es lo más antiguo que mira una feature; el target y los lags de las filas del periodo siguiente caen así fuera del periodo anterior). "
        "Coincide con `SplitSpec` (`validation_from = train_to + embargo`, `test_from = validation_to + embargo`).",
        "",
        _table(
            ["periodo", "emisión desde (UTC)", "emisión hasta (UTC)", "fechas locales", "filas", "filas completas"],
            [
                [
                    "train",
                    split["train"][0],
                    split["train"][1],
                    "2024-04-01 a 2024-12-31",
                    f"{p['train']['rows']:,}",
                    f"{p['train']['complete_rows']:,}",
                ],
                ["(embargo 168 h)", split["train"][1], split["validation"][0], "2025-01-01 a 2025-01-07", "-", "-"],
                [
                    "validación",
                    split["validation"][0],
                    split["validation"][1],
                    "2025-01-08 a 2025-01-31",
                    f"{p['validation']['rows']:,}",
                    f"{p['validation']['complete_rows']:,}",
                ],
                ["(embargo 168 h)", split["validation"][1], split["test"][0], "2025-02-01 a 2025-02-07", "-", "-"],
                [
                    "test",
                    split["test"][0],
                    split["test"][1],
                    "2025-02-08 a 2025-03-31",
                    f"{p['test']['rows']:,}",
                    f"{p['test']['complete_rows']:,}",
                ],
            ],
        ),
        "",
        "Justificación y límites:",
        "",
        f"- Train son 9 meses (abril a diciembre, 275 días); las {rep['rows_in_warmup_first_168h']:,} filas incompletas del arranque (primeras 168 h, lag semanal) y las {rep['incomplete_rows_after_warmup']:,} de la hora ambigua quedan fuera de las filas completas, de modo que entrenan "
        f"{p['train']['complete_rows']:,} de {p['train']['rows']:,}. Validación y test no tienen filas incompletas ({p['validation']['complete_rows']:,} y {p['test']['complete_rows']:,}).",
        "- **Estacionalidad**: train no incluye ningún invierno y validación/test son enero-marzo. Un modelo que lea el mes (no lo hace: las features son historial y reloj) o que aprenda niveles de verano verá un cambio de nivel. Los lags recientes absorben parte; comparar con una persistencia y con una climatología hora × día de la semana ajustada en train.",
        "- **Peaje de congestión**: la tarifa de entrada a la zona de congestión de Manhattan (`cbd_congestion_fee`) empieza el 2025-01-05, dentro del periodo de validación y antes de todo el test. El test es posterior al cambio de régimen y el train, anterior: es un cambio estructural real, no solo estacional, que afecta sobre todo a Manhattan por debajo de la calle 60. Conviene medir por zona y no solo en agregado.",
        "- **Un solo año**: cada festivo ocurre una vez y cae en un solo periodo. Las features de calendario no codifican festivos (ver tarjeta); Thanksgiving, Navidad y Año Nuevo quedan en train y MLK Day y Presidents' Day en validación y test.",
        "- Las 526 filas ambiguas de la serie (2 h × 263 zonas, 2024-11-03) están en train; `target` nulo y features que las usan, nulas hasta 168 h después. A4 debe entrenar y evaluar solo con filas completas y contar cuántas se descartan.",
        "",
        "## 8. ¿Transformación del target o baseline por zona?",
        "",
        f"- **Transformación**: la asimetría del target es {_f(dist['skewness'], 2)} y la de `log1p(target)` {_f(dist['skewness_log1p'], 2)}; con un 51 % de ceros en el conjunto total de zonas (tarjeta de datos) (y {_pct(dist['share_zero'])} en las seleccionadas) `log1p` es la transformación natural que mantiene el 0 en 0 y comprime la cola. "
        "Es recomendable **como variante a comparar**, no como sustitución: el objetivo del GA de ex_fuzzy es el R² del target tal como se le dé, así que en escala original el error lo dominan unas pocas zonas de Midtown y los aeropuertos; en `log1p` pesan todas. "
        "Hay que invertir (`expm1`) y reportar MAE/RMSE en conteos y por zona, y avisar de que la media de `expm1(E[log1p y])` subestima la media. Si se usa log1p en el target, las features de conteo (`pickups_*`) deberían transformarse igual para que las reglas hablen de la misma escala.",
        "- **Baseline por zona**: sí, imprescindible. La identidad de la zona explica por sí sola gran parte de la varianza (§5) porque la escala difiere en más de dos órdenes de magnitud, y las features de historial son recuentos absolutos, así que un modelo común sin ninguna normalización por zona aprende sobre todo «zona grande / zona pequeña». Referencias mínimas: persistencia (`pickups_lag1`), misma hora la semana anterior (`pickups_lag168`) y media por zona × hora local × día de la semana ajustada en train. "
        "Una alternativa a explorar (no hecha aquí, porque cambiaría el significado de las features) es modelar la razón `target / media_de_zona_en_train` o entrenar con features normalizadas por la media de train de cada zona; esa media tendría que calcularse solo con train.",
        "- **Zonas con poco volumen**: ya se excluyen las de < 1 recogida/hora; incluso las incluidas cercanas al umbral tienen muchos ceros y un ruido de conteo (Poisson) que ningún modelo puede reducir, así que el error relativo por zona crece al bajar el volumen.",
        "",
    ]
    lines += _excluded_appendix(vol["excluded"]["all"])
    return "\n".join(lines)


def _excluded_appendix(excluded: list[dict]) -> list[str]:
    out = [
        "",
        "## Apéndice: zonas excluidas de la tarea («sin modelo» en el mapa)",
        "",
        "Motivo común: media de recogidas por hora conocida en train inferior al umbral (entre paréntesis, la media de cada zona; 0 = ninguna recogida en train). "
        "Siguen en `taxi_zones*.geojson` y en la serie de observaciones; no tienen filas en la tabla de features ni modelo. "
        "Los IDs 264 y 265 (`Unknown`, `Outside of NYC`) no tienen polígono y no están en la serie.",
        "",
    ]
    by_borough: dict[str, list[dict]] = {}
    for z in excluded:
        by_borough.setdefault(z["borough"], []).append(z)
    for borough in sorted(by_borough):
        zs = sorted(by_borough[borough], key=lambda z: int(z["entity_id"]))
        out.append(
            f"- **{borough}** ({len(zs)}): " + "; ".join(f"{z['entity_id']} {z['name']} ({z['rate']:.2f})" for z in zs)
        )
    out.append("")
    return out


def write_eda(table_dir: Path, config: dict, doc_path: Path, *, memory_limit: str = "1500MB", threads: int = 4) -> dict:
    stats = compute(table_dir, config, memory_limit=memory_limit, threads=threads)
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(render_markdown(stats), encoding="utf-8")
    (table_dir.parent / f"{TABLE_DIRNAME}_eda.json").write_text(
        json.dumps(stats, indent=1, default=str) + "\n", encoding="utf-8"
    )
    return stats
