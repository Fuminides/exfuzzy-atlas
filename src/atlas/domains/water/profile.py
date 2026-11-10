"""Descriptive profile of the normalised water slice (``docs/water/profile.md``).

    PYTHONPATH=src python -m atlas.domains.water.profile

Everything is computed with DuckDB from the Parquet written by ``atlas.domains.water.ingest`` plus the raw
``api_counts`` file; nothing here fits a model. Numbers are descriptive and the closing section is a *preliminary*
list of candidate problems, not the choice of a target (that is AT-021).
"""

# ruff: noqa: E501  (prose templates and SQL)

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb

from atlas.domains.water import fetch
from atlas.paths import PROCESSED_DIR, REPO_ROOT

DOC_PATH = REPO_ROOT / "docs" / "water" / "profile.md"


def _con(observations: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET memory_limit='1GB'")
    con.execute("SET threads=2")
    con.execute("SET TimeZone='UTC'")
    con.execute(
        f"""CREATE VIEW obs AS SELECT *, timezone('Europe/London', timestamp_utc) AS local_ts,
            year(timezone('Europe/London', timestamp_utc)) AS y FROM read_parquet('{observations}/**/*.parquet', hive_partitioning=true)"""
    )
    con.execute(
        """CREATE VIEW samples AS SELECT sample_id, any_value(entity_id) AS entity_id, any_value(timestamp_utc) AS ts,
           any_value(local_ts) AS local_ts, any_value(y) AS y, any_value(sampling_purpose) AS purpose,
           count(*) AS n_det, bool_or(feature_name = 'dissolved_oxygen') AS has_do,
           bool_or(feature_name = 'ammoniacal_nitrogen') AS has_nh4, bool_or(feature_name = 'orthophosphate_reactive') AS has_po4,
           max(value) FILTER (WHERE feature_name = 'dissolved_oxygen') AS do_mgl,
           max(value) FILTER (WHERE feature_name = 'ammoniacal_nitrogen') AS nh4,
           max(value) FILTER (WHERE feature_name = 'orthophosphate_reactive') AS po4,
           bool_or(censoring IS NOT NULL AND feature_name = 'ammoniacal_nitrogen') AS nh4_cens,
           bool_or(censoring IS NOT NULL AND feature_name = 'orthophosphate_reactive') AS po4_cens
           FROM obs GROUP BY sample_id"""
    )
    return con


def _rows(con, sql: str) -> list[tuple]:
    return con.execute(sql).fetchall()


def build_profile(processed_dir: Path, raw_dir: Path, config: dict) -> dict:
    con = _con(processed_dir / "observations")
    p: dict = {}
    p["totals"] = _rows(
        con,
        "SELECT count(*), count(DISTINCT sample_id), count(DISTINCT entity_id), min(local_ts), max(local_ts) FROM obs",
    )[0]
    p["per_year"] = _rows(
        con,
        """WITH s AS (SELECT y, entity_id, count(*) AS n FROM samples GROUP BY 1, 2)
           SELECT y, count(*) AS points, sum(n) AS samples, median(n), round(avg(n), 1), round(quantile_cont(n, 0.9), 1),
                  round(100 * avg((n >= 12)::INT), 1), round(100 * avg((n >= 26)::INT), 1), max(n)
           FROM s GROUP BY 1 ORDER BY 1""",
    )
    p["points_active_years"] = _rows(
        con,
        """WITH a AS (SELECT entity_id, count(DISTINCT y) AS yrs, count(*) AS n FROM samples GROUP BY 1)
           SELECT yrs, count(*), median(n), sum(n) FROM a GROUP BY 1 ORDER BY 1""",
    )
    p["intervals"] = _rows(
        con,
        """WITH g AS (SELECT entity_id, ts, date_diff('second', lag(ts) OVER (PARTITION BY entity_id ORDER BY ts), ts) / 86400.0 AS gap
                     FROM samples)
           SELECT count(gap), round(quantile_cont(gap, 0.10), 2), round(quantile_cont(gap, 0.25), 2), round(median(gap), 2),
                  round(quantile_cont(gap, 0.75), 2), round(quantile_cont(gap, 0.90), 2), round(quantile_cont(gap, 0.99), 1),
                  round(100 * avg((gap < 1)::INT), 1), round(100 * avg((gap BETWEEN 25 AND 35)::INT), 1),
                  round(100 * avg((gap BETWEEN 13 AND 15)::INT), 1), round(100 * avg((gap > 60)::INT), 1), round(100 * avg((gap > 180)::INT), 1)
           FROM g WHERE gap IS NOT NULL""",
    )
    p["intervals_by_point"] = _rows(
        con,
        """WITH g AS (SELECT entity_id, date_diff('second', lag(ts) OVER (PARTITION BY entity_id ORDER BY ts), ts) / 86400.0 AS gap FROM samples),
                per AS (SELECT entity_id, count(gap) AS n, median(gap) AS med, stddev(gap) / nullif(avg(gap), 0) AS cv FROM g WHERE gap IS NOT NULL GROUP BY 1)
           SELECT count(*) FILTER (WHERE n >= 20), round(median(med) FILTER (WHERE n >= 20), 1),
                  round(median(cv) FILTER (WHERE n >= 20), 2),
                  count(*) FILTER (WHERE n >= 20 AND med BETWEEN 25 AND 35),
                  count(*) FILTER (WHERE n >= 20 AND med BETWEEN 13 AND 15),
                  count(*) FILTER (WHERE n >= 20 AND med < 13), count(*) FILTER (WHERE n >= 20 AND med > 35)
           FROM per""",
    )
    p["same_day_multi"] = _rows(
        con,
        """SELECT count(*) FILTER (WHERE n > 1), count(*) FROM (SELECT entity_id, CAST(local_ts AS DATE) AS d, count(*) AS n FROM samples GROUP BY 1, 2)""",
    )[0]
    p["cooccurrence"] = _rows(
        con,
        """SELECT CASE WHEN has_do THEN 'DO' ELSE '-' END || '+' || CASE WHEN has_nh4 THEN 'NH4' ELSE '-' END || '+' || CASE WHEN has_po4 THEN 'PO4' ELSE '-' END AS combo,
                  count(*), round(100.0 * count(*) / sum(count(*)) OVER (), 1)
           FROM samples GROUP BY 1 ORDER BY 2 DESC""",
    )
    p["cooccurrence_by_year"] = _rows(
        con,
        """SELECT y, count(*), round(100 * avg((has_do AND has_nh4 AND has_po4)::INT), 1), round(100 * avg(has_do::INT), 1),
                  round(100 * avg(has_nh4::INT), 1), round(100 * avg(has_po4::INT), 1) FROM samples GROUP BY 1 ORDER BY 1""",
    )
    p["cooccurrence_by_purpose"] = _rows(
        con,
        """SELECT purpose, count(*), round(100 * avg((has_do AND has_nh4 AND has_po4)::INT), 1), round(100 * avg(has_do::INT), 1)
           FROM samples GROUP BY 1 ORDER BY 2 DESC""",
    )
    p["censoring"] = _rows(
        con,
        """SELECT feature_name, y, count(*), count(*) FILTER (WHERE censoring = 'left'), count(*) FILTER (WHERE censoring = 'right'),
                  round(100.0 * count(*) FILTER (WHERE censoring IS NOT NULL) / count(*), 1)
           FROM obs GROUP BY 1, 2 ORDER BY 1, 2""",
    )
    p["censoring_totals"] = _rows(
        con,
        """SELECT feature_name, count(*), count(*) FILTER (WHERE censoring = 'left'), count(*) FILTER (WHERE censoring = 'right'),
                  round(100.0 * count(*) FILTER (WHERE censoring IS NOT NULL) / count(*), 1)
           FROM obs GROUP BY 1 ORDER BY 1""",
    )
    p["limits"] = _rows(
        con,
        """SELECT feature_name, value, count(*), min(y), max(y) FROM obs WHERE censoring IS NOT NULL
           GROUP BY 1, 2 ORDER BY 1, 3 DESC""",
    )
    p["limits_by_year"] = _rows(
        con,
        """SELECT feature_name || ' <' || value, y, count(*) FROM obs WHERE censoring IS NOT NULL GROUP BY 1, 2 ORDER BY 1, 2""",
    )
    p["limit_share_points"] = _rows(
        con,
        """WITH l AS (SELECT feature_name, entity_id, count(DISTINCT value) AS k FROM obs WHERE censoring IS NOT NULL GROUP BY 1, 2)
           SELECT feature_name, count(*), count(*) FILTER (WHERE k > 1) FROM l GROUP BY 1 ORDER BY 1""",
    )
    p["values"] = _rows(
        con,
        """SELECT feature_name, unit, count(*), round(min(value), 4), round(quantile_cont(value, 0.01), 4), round(median(value), 4),
                  round(quantile_cont(value, 0.99), 3), round(max(value), 3)
           FROM obs WHERE censoring IS NULL GROUP BY 1, 2 ORDER BY 1""",
    )
    p["units"] = _rows(con, "SELECT feature_name, unit, unit_label, count(*) FROM obs GROUP BY ALL ORDER BY 1")
    p["flags"] = _rows(
        con,
        """SELECT coalesce(validity_flag, '(null)'), coalesce(missing_reason, '(value present)'), coalesce(censoring, '(none)'), count(*)
           FROM obs GROUP BY ALL ORDER BY 4 DESC""",
    )
    p["materials"] = _rows(
        con, "SELECT sample_material, count(*), count(DISTINCT sample_id) FROM obs GROUP BY 1 ORDER BY 2 DESC"
    )
    p["purposes"] = _rows(
        con, "SELECT sampling_purpose, count(*), count(DISTINCT sample_id) FROM obs GROUP BY 1 ORDER BY 2 DESC"
    )
    p["hour_season"] = _rows(
        con,
        """SELECT CASE WHEN month(local_ts) IN (12, 1, 2) THEN 'Dec-Feb' WHEN month(local_ts) IN (6, 7, 8) THEN 'Jun-Aug' END AS season,
                  count(*), round(avg(hour(local_ts) + minute(local_ts) / 60.0), 2), round(median(hour(local_ts) + minute(local_ts) / 60.0), 2),
                  round(quantile_cont(hour(local_ts) + minute(local_ts) / 60.0, 0.1), 2), round(quantile_cont(hour(local_ts) + minute(local_ts) / 60.0, 0.9), 2)
           FROM samples WHERE month(local_ts) IN (12, 1, 2, 6, 7, 8) GROUP BY 1 ORDER BY 1 DESC""",
    )
    p["time_of_day"] = _rows(
        con,
        """SELECT count(*) FILTER (WHERE hour(local_ts) = 0 AND minute(local_ts) = 0 AND second(local_ts) = 0), count(*),
                  count(DISTINCT strftime(local_ts, '%H:%M:%S'))
           FROM samples""",
    )[0]
    p["dst_windows"] = _rows(
        con,
        """SELECT count(*) FILTER (WHERE strftime(local_ts, '%m-%d') >= '03-25' AND strftime(local_ts, '%m-%d') <= '03-31'
                                   AND dayofweek(local_ts) = 0 AND hour(local_ts) = 1),
                  count(*) FILTER (WHERE strftime(local_ts, '%m-%d') >= '10-25' AND strftime(local_ts, '%m-%d') <= '10-31'
                                   AND dayofweek(local_ts) = 0 AND hour(local_ts) = 1)
           FROM samples""",
    )[0]
    p["selected_counts"] = _rows(con, "SELECT determinand_code, y, count(*) FROM obs GROUP BY 1, 2 ORDER BY 1, 2")
    p["spatial"] = _rows(
        con,
        """SELECT count(DISTINCT entity_id) FROM obs""",
    )[0][0]
    p["correlations"] = _rows(
        con,
        """SELECT count(*), round(corr(do_r, nh4_r), 2), round(corr(do_r, po4_r), 2), round(corr(nh4_r, po4_r), 2) FROM (
              SELECT rank() OVER (ORDER BY do_mgl) AS do_r, rank() OVER (ORDER BY nh4) AS nh4_r, rank() OVER (ORDER BY po4) AS po4_r
              FROM samples WHERE has_do AND has_nh4 AND has_po4)""",
    )[0]
    p["do_structure"] = _rows(
        con,
        """WITH d AS (SELECT entity_id, do_mgl FROM samples WHERE do_mgl IS NOT NULL),
                big AS (SELECT entity_id FROM d GROUP BY 1 HAVING count(*) >= 20),
                dd AS (SELECT d.* FROM d JOIN big USING (entity_id)),
                pm AS (SELECT entity_id, avg(do_mgl) AS mu FROM dd GROUP BY 1)
           SELECT round(1 - avg((dd.do_mgl - pm.mu) ^ 2) / var_pop(dd.do_mgl), 2), count(DISTINCT dd.entity_id), count(*)
           FROM dd JOIN pm USING (entity_id)""",
    )[0]
    p["next_sample_persistence"] = _rows(
        con,
        """WITH d AS (SELECT entity_id, ts, do_mgl AS v FROM samples WHERE do_mgl IS NOT NULL),
                pairs AS (SELECT v, lag(v) OVER w AS prev, date_diff('day', lag(ts) OVER w, ts) AS gap FROM d WINDOW w AS (PARTITION BY entity_id ORDER BY ts))
           SELECT count(*), round(corr(v, prev), 2), round(median(abs(v - prev)), 2), round(avg(abs(v - prev)), 2)
           FROM pairs WHERE prev IS NOT NULL AND gap BETWEEN 20 AND 45""",
    )[0]
    p["do_stats"] = _rows(
        con,
        """SELECT round(stddev(do_mgl), 2), round(median(abs(do_mgl - (SELECT median(do_mgl) FROM samples))), 2) FROM samples WHERE do_mgl IS NOT NULL""",
    )[0]
    con.close()

    counts_file = raw_dir / "api_counts" / f"{config['slice']['id']}.json"
    api_counts = json.loads(counts_file.read_text(encoding="utf-8"))["counts"] if counts_file.exists() else []
    p["api_counts"] = [  # one row per candidate determinand and year (the half-year windows summed)
        {
            "determinand": code,
            "year": year,
            "total_items": sum(c["total_items"] for c in api_counts if (c["determinand"], c["year"]) == (code, year)),
        }
        for code, year in dict.fromkeys((c["determinand"], c["year"]) for c in api_counts)
    ]
    return p


def _table(header: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def _n(x) -> str:
    return f"{int(x):,}" if x is not None else "-"


def render_markdown(p: dict, config: dict, details: dict) -> str:
    rows, samples, points, first, last = p["totals"]
    s = config["slice"]
    labels = {d["code"]: d["label"] for d in config["determinands"] + config["candidate_determinands"]}
    iv = p["intervals"][0]
    ibp = p["intervals_by_point"][0]
    cooc = {r[0]: r for r in p["cooccurrence"]}
    all3 = cooc.get("DO+NH4+PO4", ("", 0, 0.0))
    n_corr, c_do_nh4, c_do_po4, c_nh4_po4 = p["correlations"]
    n_pers, r_pers, mad_pers, mae_pers = p["next_sample_persistence"]
    out = [
        "# Perfil de datos: calidad del agua de ríos, Northumberland & Tyne (`uk-water-quality`)",
        "",
        "Generado por `python -m atlas.domains.water.profile` (AT-020). No editar a mano: se regenera con cada ingesta.",
        "Es un perfil **descriptivo** para AT-021; no elige el target ni valida ningún modelo.",
        "",
        "## 1. Resumen",
        "",
        f"- Versión de datos: `{details['data_version']}`; descarga: {details['downloaded_at_utc']}.",
        f"- Rebanada: {s['description']} Años {s['year_from']}-{s['year_to']}; determinandos: "
        + ", ".join(f"{d['code']} ({d['feature_name']}, «{d['label']}»)" for d in config["determinands"])
        + ".",
        f"- Filas canónicas (muestra x determinando): {_n(rows)}; muestras: {_n(samples)}; puntos de muestreo con datos: {_n(points)}.",
        f"- Rango (hora local): {first} a {last}.",
        f"- Geometría: {_n(details['entities']['points_in_listing'])} puntos en el listado de la API, {_n(details['entities']['points_with_observations'])} con datos en la rebanada; "
        "coordenadas de relleno (geometría nula, ver `api_notes.md`): "
        + (", ".join(details["entities"]["coordinates_outside_extent"]) or "ninguna")
        + ".",
        f"- Conciliación con la API: suma de `X-Total-Items` por año = {_n(details['api_total_items_all_years'])} = filas CSV = filas canónicas; "
        f"pares (muestra, determinando) distintos = filas ({_n(rows)}); duplicados en la clave del contrato: {details['counters'].get('duplicate_key_rows_dropped', 0)}.",
        "",
        "Por qué estos determinandos (`9924` oxígeno disuelto, `0111` nitrógeno amoniacal, `0180` ortofosfato reactivo, y desde AT-021 `0061` pH y `0076` temperatura del agua, por su relación física con el oxígeno): "
        "son determinandos habituales del seguimiento fisicoquímico de ríos (oxígeno, amoniaco, fósforo reactivo), con cobertura alta en toda la década "
        f"({' / '.join(_n(r[1]) for r in p['censoring_totals'])} observaciones para {' / '.join(r[0] for r in p['censoring_totals'])}), una unidad por determinando (mg/l, °C, pH), y comportamiento muy distinto frente al límite de detección "
        f"({'; '.join(f'{r[0]} {r[4]} % censurado' for r in p['censoring_totals'])}), lo que permite estudiar el tratamiento de la censura. "
        "Otras alternativas con cobertura similar quedan descritas en la sección 8 (nitrato, OD en % de saturación).",
        "",
        "## 2. Muestras por punto y año",
        "",
        _table(
            [
                "año (local)",
                "puntos activos",
                "muestras",
                "mediana muestras/punto",
                "media",
                "p90",
                "% puntos con >= 12",
                "% con >= 26",
                "máx.",
            ],
            [[y, _n(a), _n(b), c, d, e, f, g, h] for y, a, b, c, d, e, f, g, h in p["per_year"]],
        ),
        "",
        "(Una «muestra» es una `sample` de la API: un punto y un instante; varias observaciones cuelgan de ella.) "
        "El año 2020 tiene muchas menos muestras que sus vecinos (coincide con la pandemia; la causa no se ha investigado). El número de puntos activos por año cambia mucho (de 84 a 310): la red de muestreo no es constante.",
        "",
        "Años con datos por punto:",
        "",
        _table(
            ["años con datos", "puntos", "mediana de muestras por punto", "muestras"],
            [[y, _n(a), b, _n(c)] for y, a, b, c in p["points_active_years"]],
        ),
        "",
        "## 3. Intervalos entre muestras (irregulares)",
        "",
        f"Huecos entre muestras consecutivas del mismo punto ({_n(iv[0])} intervalos), en días:",
        "",
        _table(
            ["p10", "p25", "mediana", "p75", "p90", "p99", "< 1 día", "25-35 d", "13-15 d", "> 60 d", "> 180 d"],
            [[*iv[1:7], *(f"{x} %" for x in iv[7:])]],
        ),
        "",
        f"Por punto con >= 20 intervalos ({_n(ibp[0])} puntos): mediana de las medianas = {ibp[1]} días; coeficiente de variación mediano del hueco = {ibp[2]}; "
        f"{_n(ibp[3])} puntos con mediana 25-35 d (mensual), {_n(ibp[4])} con 13-15 d (quincenal), {_n(ibp[5])} más frecuentes y {_n(ibp[6])} más espaciados. "
        f"Días-punto con más de una muestra: {_n(p['same_day_multi'][0])} de {_n(p['same_day_multi'][1])}.",
        "",
        "El muestreo es de campaña (rutina mensual en una parte de los puntos, con huecos y cambios de programa). **No hay serie horaria ni diaria**; "
        "cualquier problema temporal sería de «siguiente muestra del mismo punto», con huecos de semanas.",
        "",
        "## 4. Co-ocurrencia de determinandos en la misma muestra",
        "",
        _table(["OD + amoniaco + ortofosfato", "muestras", "%"], [list(r) for r in p["cooccurrence"]]),
        "",
        f"Las tres a la vez: {_n(all3[1])} muestras ({all3[2]} %). Por año:",
        "",
        _table(
            ["año", "muestras", "% con las 3", "% con OD", "% con amoniaco", "% con ortofosfato"],
            [list(r) for r in p["cooccurrence_by_year"]],
        ),
        "",
        "Por propósito de muestreo:",
        "",
        _table(["propósito", "muestras", "% con las 3", "% con OD"], [list(r) for r in p["cooccurrence_by_purpose"]]),
        "",
        "## 5. Censura (límite de detección)",
        "",
        "`<x` se guarda con `value = x` y `censoring = left`; `>x` con `censoring = right`. `x` es el límite publicado, no una estimación del valor real.",
        "",
        _table(
            ["determinando", "filas", "censuradas «<»", "censuradas «>»", "% censurado"],
            [list(r) for r in p["censoring_totals"]],
        ),
        "",
        "Por año (% censurado):",
        "",
        _censor_matrix(p["censoring"]),
        "",
        "Límites de detección distintos publicados. Coexisten dos límites principales durante todo el periodo y la tabla por año muestra cómo cambia su peso; no se ha determinado si responde a método, laboratorio o programa. Un `<0.03` y un `<0.002` no son comparables:",
        "",
        _table(["determinando", "límite", "filas", "primer año", "último año"], [list(r) for r in p["limits"]]),
        "",
        "Filas censuradas por límite y año:",
        "",
        _limits_matrix(p["limits_by_year"]),
        "",
        "Puntos con más de un límite de detección distinto (determinando, puntos con censura, de ellos con >1 límite): "
        + "; ".join(f"{a}: {b}, {c}" for a, b, c in p["limit_share_points"])
        + ".",
        "",
        "## 6. Unidades, banderas, materiales y propósitos",
        "",
        _table(["determinando", "unidad (símbolo)", "unidad (etiqueta API)", "filas"], [list(r) for r in p["units"]]),
        "",
        "Valores (sin censurados) por determinando:",
        "",
        _table(["determinando", "unidad", "n", "mín.", "p1", "mediana", "p99", "máx."], [list(r) for r in p["values"]]),
        "",
        "La API **no publica bandera de validez** por observación (no existe equivalente a `V`/`N` de Madrid): `validity_flag` es nulo en todas las filas. "
        "Combinaciones observadas (bandera, motivo de nulo, censura):",
        "",
        _table(["validity_flag", "missing_reason", "censoring", "filas"], [list(r) for r in p["flags"]]),
        "",
        "Material de muestra (los puntos son de tipo F6 río, pero hay muestras de otro material; se conservan y se identifican con `sample_material`):",
        "",
        _table(["material", "filas", "muestras"], [list(r) for r in p["materials"]]),
        "",
        "Propósito de muestreo:",
        "",
        _table(["propósito", "filas", "muestras"], [list(r) for r in p["purposes"]]),
        "",
        "## 7. Hora local y horario de verano",
        "",
        "La API entrega `phenomenonTime` sin desfase (p. ej. `2015-02-03T10:28:00`). Se lee como **hora de reloj de Europe/London**, no UTC. "
        "Evidencia: si fuera UTC, el muestreo diurno de verano aparecería ~1 h antes que el de invierno; no es así.",
        "",
        _table(["estación", "muestras", "hora media", "mediana", "p10", "p90"], [list(r) for r in p["hour_season"]]),
        "",
        f"Muestras con hora exactamente 00:00:00 (posible «sin hora»): {p['time_of_day'][0]} de {_n(p['time_of_day'][1])}; horas distintas: {_n(p['time_of_day'][2])}. "
        f"Muestras en la hora 01:xx de un domingo de cambio de hora (primavera / otoño): {p['dst_windows'][0]} / {p['dst_windows'][1]}; "
        f"filas con hora inexistente: {details['counters'].get('dst_nonexistent_rows', 0)}; con hora ambigua: {details['counters'].get('dst_ambiguous_rows', 0)}. "
        "La política implementada (hora ambigua = primera ocurrencia, BST; hora inexistente = con el desfase previo, GMT) está probada con datos sintéticos "
        "porque esta rebanada no contiene ninguna muestra en esas horas.",
        "",
        "## 8. Cobertura de otros determinandos en la rebanada (candidatos: conteos `X-Total-Items` sin descargar los datos)",
        "",
        _coverage_matrix(
            [{"determinand": c, "year": y, "total_items": n} for c, y, n in p["selected_counts"]] + p["api_counts"],
            labels,
        ),
        "",
        "## 9. Estructura descriptiva (no es validación de ningún modelo)",
        "",
        f"- Sobre {_n(n_corr)} muestras con las tres: correlación de rangos (Pearson sobre rangos) OD-amoniaco = {c_do_nh4}, OD-ortofosfato = {c_do_po4}, amoniaco-ortofosfato = {c_nh4_po4} (los censurados empatan en el límite).",
        f"- Fracción de la varianza del OD explicada solo por la media de cada punto ({_n(p['do_structure'][1])} puntos con >= 20 muestras de OD, {_n(p['do_structure'][2])} muestras): {p['do_structure'][0]}.",
        f"- Pares de muestras consecutivas de OD en el mismo punto con 20-45 días de hueco ({_n(n_pers)}): correlación = {r_pers}; |diferencia| mediana = {mad_pers} mg/l (media {mae_pers}); "
        f"desviación típica global del OD = {p['do_stats'][0]} mg/l.",
        "",
        "## 10. Problemas candidatos (preliminar; el target lo decide AT-021)",
        "",
        f"1. **Clasificar la condición de una muestra a partir de determinandos co-medidos** (p. ej. banda de oxígeno disuelto o de ortofosfato a partir de los otros dos + estación + atributos del punto). "
        f"Lo que respalda el dato: {_n(all3[1])} muestras con las tres ({all3[2]} %), {_n(points)} puntos, {s['year_to'] - s['year_from'] + 1} años, unidad única; pocas variables, lo que favorece reglas legibles. "
        "Lo que no: son pocas entradas (dos determinandos y calendario), el OD falta en el ~31 % de las muestras (sobre todo las de seguimiento «UK GOVT POLICY» y las investigaciones locales, ver sección 4), las muestras del mismo punto están muy correlacionadas (hay que partir por punto o por tiempo, no al azar), "
        "y cualquier «banda» sería una convención descriptiva, no una clasificación regulatoria (los estándares de la Directiva Marco del Agua dependen del tipo de masa de agua).",
        f"2. **Inferir un determinando a partir de los demás en la misma muestra** (regresión de ortofosfato o amoniaco, con la censura tratada explícitamente). Soporta: misma estructura de muestra. "
        f"No soporta bien: amoniaco está censurado en un {next(r[4] for r in p['censoring_totals'] if r[0] == 'ammoniacal_nitrogen')} % de las filas y coexisten límites de detección distintos (0.03 y 0.002), así que un target numérico "
        "tendría una masa grande en un límite que no es homogéneo; habría que modelar solo la parte detectada o definir una clase «por encima de un umbral común».",
        f"3. **Valor/categoría en la siguiente muestra del mismo punto** (horizonte = la siguiente campaña, no una hora). Soporta: puntos con ~mensual regularidad ({_n(ibp[3])} puntos con mediana 25-35 d de {_n(ibp[0])} con >= 20 intervalos). Limita: la mediana de muestras por punto y año es baja (sección 2) y el coeficiente de variación del hueco es alto. "
        f"No soporta: horizontes horarios o diarios, ni series regulares; hay que fijar la relación entre `issued_at` (última muestra conocida) y `valid_at` (la siguiente, a un hueco variable) y comparar con persistencia del último valor y climatología por punto y mes. "
        f"Descriptivamente, el OD de muestras consecutivas ya está correlacionado (r = {r_pers}), lo que deja poco margen sobre la persistencia.",
        "",
        "Descartado desde ya: cualquier promesa de predicción horaria, alertas en tiempo real o interpolación entre puntos (ver `AGENTS.md`, invariante 7).",
        "",
    ]
    return "\n".join(out) + "\n"


def _censor_matrix(rows: list[tuple]) -> str:
    years = sorted({r[1] for r in rows})
    by = {(r[0], r[1]): r[5] for r in rows}
    feats = sorted({r[0] for r in rows})
    return _table(["determinando", *map(str, years)], [[f, *(by.get((f, y), "-") for y in years)] for f in feats])


def _limits_matrix(rows: list[tuple]) -> str:
    years = sorted({r[1] for r in rows})
    by = {(r[0], r[1]): r[2] for r in rows}
    labels = sorted({r[0] for r in rows})
    return _table(["límite", *map(str, years)], [[f, *(by.get((f, y), 0) for y in years)] for f in labels])


def _coverage_matrix(counts: list[dict], labels: dict[str, str]) -> str:
    if not counts:
        return "(sin conteos: ejecute la ingesta con `--counts`)"
    years = sorted({c["year"] for c in counts})
    codes = list(dict.fromkeys(c["determinand"] for c in counts))
    by = {(c["determinand"], c["year"]): c["total_items"] for c in counts}
    rows = [
        [
            f"{code} {labels.get(code, '')}",
            *(_n(by.get((code, y), 0)) for y in years),
            _n(sum(by.get((code, y), 0) for y in years)),
        ]
        for code in codes
    ]
    return _table(["determinando", *map(str, years), "total"], rows)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Write docs/water/profile.md from the processed water slice.")
    parser.add_argument("--processed-dir", type=Path, default=PROCESSED_DIR / "water")
    parser.add_argument("--doc", type=Path, default=DOC_PATH)
    parser.add_argument("--datasets-root", default=fetch.DEFAULT_DATASETS_ROOT)
    args = parser.parse_args(argv)
    config = fetch.load_config()
    raw_dir = fetch.default_raw_dir(args.datasets_root)
    details = json.loads((args.processed_dir / "ingest_details.json").read_text(encoding="utf-8"))
    profile = build_profile(args.processed_dir, raw_dir, config)
    args.doc.parent.mkdir(parents=True, exist_ok=True)
    args.doc.write_text(render_markdown(profile, config, details), encoding="utf-8")
    print(f"wrote {args.doc}")


if __name__ == "__main__":
    main()
