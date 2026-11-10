"""Markdown rendering of the Germany ingest details and of the ``de_no2_h6`` quality report (AT-070)."""

# ruff: noqa: E501  (prose templates)

from __future__ import annotations

from atlas.contracts.models import EntityCollection, QualityReport


def table(header: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def pct(part: float, whole: float) -> str:
    return f"{100 * part / whole:.1f} %" if whole else "-"


def render_eea_markdown(details: dict, report: QualityReport, stations: EntityCollection) -> str:
    years = details["years"]
    inv, prec = details["inventory"], details["precedence"]
    flags: dict = {}
    for source, year, flag, n in details["flags"]:
        flags.setdefault(source, {}).setdefault(year, {})[flag] = n
    rows = details["rows_written"]
    stats = details["value_stats"]
    cov = details["coverage"]
    per_year = {y: [v[y]["valid_hours"] for v in cov.values() if y in v] for y in years}
    st = details["stations"]
    types: dict = {}
    for f in stations.features:
        a = f.properties.attributes
        types[(a.get("station_type"), a.get("station_area"))] = types.get((a.get("station_type"), a.get("station_area")), 0) + 1
    out = [
        "# Calidad de datos: NO2 horario de Alemania (`eea-air-de`)",
        "",
        "Generado por `python -m atlas.domains.air.eea_ingest` (AT-070). No editar a mano: se regenera con cada ingesta.",
        "",
        "## Resumen",
        "",
        f"- Versión de datos: `{details['data_version']}`; años (reloj de la fuente, UTC+01): {years[0]}-{years[-1]}.",
        f"- Rango (UTC): {details['date_range_utc'][0]} a {details['date_range_utc'][1]}.",
        f"- Filas canónicas: {rows:,}; con valor: {report.valid_rows:,} ({pct(report.valid_rows, rows)}). "
        "Por motivo: " + ", ".join(f"{k} = {v:,}" for k, v in sorted(details["by_reason"].items())) + ".",
        f"- Estaciones con algún valor válido (entidades): {len(stations.features)}; con punto oficial: {st['with_geometry']}.",
        f"- Fuente: {report.source_url}; licencia: {report.license}.",
        f"- Descarga: {details['downloaded_at_utc']}.",
        "",
        "## Origen de cada valor: E1a (verificado) y E2a (al día)",
        "",
        table(
            ["dataset", "ficheros", "primer y último `Start` en los ficheros", "estaciones", "puntos de muestreo", "filas en los años pedidos", "estaciones con varios puntos de muestreo"],
            [
                [k, v["files"], f"{v['first_start_in_files'][:16]} – {v['last_start_in_files'][:16]}", v["stations"], v["sampling_points"], f"{v['rows_in_selected_years']:,}", ", ".join(v["stations_with_several_sampling_points"]) or "ninguna"]
                for k, v in inv.items()
            ],
        ),
        "",
        f"Precedencia: por (estación, hora) se escribe **una** fila canónica, la de E1a si existe y si no la de E2a. Horas presentes en ambos: "
        f"{prec['hours_in_both_datasets']:,} (con valor distinto: {prec['hours_in_both_with_different_value']:,}). Filas de E2a usadas: {prec['e2a_rows_used']:,}. "
        "`source_id` de cada fila dice de qué dataset sale (`eea-air-de-e1a` o `eea-air-de-e2a`).",
        "",
        "## Banderas EEA (`validity_flag = <Validity>:<Verification>`)",
        "",
        "Validity: 1 válido; 2 válido, bajo el límite de detección y con el valor medido; 3 válido, sustituido por 0,5 x límite de detección; "
        "-1 no válido; -99 no válido por mantenimiento o calibración. Verification: 1 verificado; 2 verificado preliminar; 3 no verificado "
        "(vocabularios en `data/raw/eea-air-de/vocabulary`). Los inválidos llevan el valor centinela -999 en el fichero, que **nunca** se escribe.",
        "",
    ]
    all_flags = sorted({f for s in flags.values() for y in s.values() for f in y})
    for source in sorted(flags):
        out += [
            f"`{source}`: filas por año y bandera",
            "",
            table(["año", *all_flags], [[y, *[f"{flags[source].get(y, {}).get(f, 0):,}" for f in all_flags]] for y in sorted(flags[source])]),
            "",
        ]
    out += [
        "## Valores",
        "",
        f"- Mínimo {stats['min']:.3f}, máximo {stats['max']:.3f} µg/m³. Negativos (válidos con bandera 2, ruido bajo el límite de detección): {stats['negative']:,}; "
        f"exactamente 0: {stats['exact_zero']:,}; por encima de 1000: {stats['above_1000']:,}; censurados a la izquierda (bandera 3): {stats['censored_left']:,}.",
        "- Unidad: todos los ficheros traen `ug.m-3` (se verifica; otra unidad se convierte si es conocida y si no se marca inválida, nunca se mezcla).",
        "",
        "## Cobertura por año (horas válidas por estación)",
        "",
        table(
            ["año", "horas posibles", "estaciones con filas", "mediana de horas válidas", "cobertura media"],
            [
                [y, f"{details['expected_hours'][y]:,}", len(per_year[y]), f"{sorted(per_year[y])[len(per_year[y]) // 2]:,}" if per_year[y] else "-",
                 pct(sum(per_year[y]), details["expected_hours"][y] * len(per_year[y])) if per_year[y] else "-"]
                for y in years
            ],
        ),
        "",
        "## Convención horaria",
        "",
        f"- `Start` y `End` están en el desfase fijo **{details['source_timezone']}** todo el año (la columna `Timezone` de todos los puntos de muestreo alemanes en "
        "el fichero de metadatos de la EEA es esa entrada del vocabulario; no hay horario de verano en la fuente). El valor cubre `[Start, End)` con `End = Start + 1 h`.",
        "- `timestamp_utc = Start - 1 h` es el **inicio** de la hora. `source_timestamp_local` conserva `AAAA-MM-DD HH:MM UTC+01`; `timezone = Europe/Berlin` es la zona de la estación.",
        "- No hay horas inexistentes ni ambiguas: cada día tiene 24 filas.",
    ]
    d = details.get("diurnal_check") or {}
    if d:
        out += [
            f"- Comprobación empírica ({d['year']}, {d['stations']} estaciones de tráfico urbanas, laborables): el ciclo diario medio de julio-agosto se alinea con el de enero-febrero "
            f"desplazándolo {d['best_lag_hours']} h UTC (mínimo error cuadrático circular entre -3 y 3 h). El reloj local pasa de UTC+1 a UTC+2 en verano, "
            f"así que, si las etiquetas son UTC+01 fijo, el ciclo de verano debe llegar **una hora UTC antes**: {'se cumple' if d['summer_cycle_one_hour_earlier'] else 'NO se cumple'}.",
        ]
    out += [
        "",
        "## Estaciones",
        "",
        table(["tipo", "zona", "estaciones"], [[t or "?", a or "?", n] for (t, a), n in sorted(types.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1])))]),
        "",
        f"- Ausentes del fichero de metadatos de la EEA: {st['absent_from_metadata_file'] or 'ninguna'}; con coordenadas de la capa de estaciones de la EEA (4 decimales): {sorted(st['coordinates_from_stations_layer']) or 'ninguna'}; "
        f"sin ninguna coordenada (geometría nula): {st['without_official_coordinates'] or 'ninguna'}. Fuera de la caja de Alemania {st['bbox_lon_lat']}: {st['outside_bbox'] or 'ninguna'}.",
        f"- Estaciones con varias coordenadas distintas en los metadatos: {st['several_distinct_coordinates_in_metadata'] or 'ninguna'}.",
        f"- Pares a menos de {st['colocated_within_m']:.0f} m: {len(st['colocated_pairs'])} (coordenadas idénticas: {len(st['identical_coordinates'])}). "
        + (", ".join(f"{a}-{b} ({d} m)" for a, b, d in st["colocated_pairs"][:20]) or "ninguno") + ".",
        f"- Estaciones sin ningún valor válido en el periodo (no son entidades): {len(details['stations_without_valid_values'])}.",
        "",
        "## Ficheros de entrada (sha256)",
        "",
        f"{len(details['sha256'])} ficheros; la lista completa está en `ingest_details.json` y en `source_manifest.json` del directorio raw.",
        "",
        "## Limitaciones",
        "",
    ]
    out += [f"- {limitation}" for limitation in report.known_limitations]
    return "\n".join(out) + "\n"


def render_dwd_markdown(details: dict, report: QualityReport) -> str:
    inv, summary = details["inventory"], details["summary"]
    years: dict = {}
    for feature, year, n in summary["per_year"]:
        years.setdefault(feature, {})[year] = n
    all_years = sorted({y for f in years.values() for y in f})
    out = [
        "# Calidad de datos: meteorología horaria del DWD (`dwd-meteo-de`)",
        "",
        "Generado por `python -m atlas.domains.air.dwd_ingest` (AT-070). No editar a mano: se regenera con cada ingesta.",
        "",
        "## Resumen",
        "",
        f"- Versión de datos: `{details['data_version']}`; rango (UTC): {details['date_range_utc'][0]} a {details['date_range_utc'][1]}.",
        f"- Zips leídos: {inv['zips']:,}; estaciones por producto: " + ", ".join(f"{k} = {v}" for k, v in inv["stations"].items()) + ".",
        f"- Filas leídas: {inv['rows_read']:,}; en el rango de interés: {inv['rows_kept']:,}; duplicados históricos/recientes descartados (gana el histórico): {inv['duplicate_rows_dropped']:,}.",
        f"- Filas canónicas: {summary['rows']:,}; con valor: {report.valid_rows:,} ({pct(report.valid_rows, summary['rows'])}). Por motivo: "
        + ", ".join(f"{k} = {v:,}" for k, v in summary["by_reason"].items()) + ".",
        f"- Estaciones con algún valor (entidades): {report.geographic_coverage['stations_in_hourly_data']}; con punto: {report.geographic_coverage['stations_with_official_point']}.",
        f"- Fuente: {report.source_url}; licencia: {report.license}.",
        f"- Descarga: {details['downloaded_at_utc']}.",
        "",
        "## Variables",
        "",
        table(
            ["variable", "filas", "con valor", "estaciones", "mínimo", "máximo"],
            [[f["feature"], f"{f['rows']:,}", f"{f['values']:,}", f["stations"], f"{f['min']:.2f}", f"{f['max']:.2f}"] for f in summary["per_feature"]],
        ),
        "",
        "Los rangos se informan tal cual vienen; el filtro de plausibilidad se aplica solo al construir la tabla de features (`configs/air/de_no2_h6.json`), "
        "nunca a las observaciones canónicas.",
        "",
        "## Valores por año",
        "",
        table(["variable", *map(str, all_years)], [[f, *[f"{years[f].get(y, 0):,}" for y in all_years]] for f in sorted(years)]),
        "",
        "## Convención horaria",
        "",
        f"- `MESS_DATUM` es UTC salvo donde el propio zip dice otra cosa: cada zip trae `Metadaten_Parameter` con el reloj de cada variable y periodo ('Stundenwerte in UTC' o 'in MEZ'); "
        f"se leyeron {inv['time_reference_rows_checked']:,} combinaciones zip x columna que solapan 2019-2025. Referencias encontradas: "
        + ", ".join(f"{ref} en {len(items)} series" for ref, items in sorted(inv["time_references"].items()))
        + f". Referencias aceptadas por la configuración: {', '.join(inv['accepted_time_references'])}. Las series declaradas **MEZ** ({len(inv['time_references'].get('MEZ', []))}: "
        + (", ".join(inv["time_references"].get("MEZ", [])) or "ninguna")
        + f") se **excluyen**: convertidas a UTC (MEZ = UTC+1 fijo) y comparadas con sus vecinas UTC más cercanas, sus valores horarios encajan con desfases de -1 h (14 de 17) y -2 o -3 h (3), frente a 0 h entre vecinas UTC, así que su reloj no se puede verificar. "
        f"Filas excluidas por ello: {inv['rows_with_refused_time_reference']:,}; filas sin referencia horaria declarada: {inv['rows_without_time_reference_dropped']:,}. Una referencia que no es UTC ni MEZ (p. ej. hora legal) detiene la ingesta.",
        "- Los ficheros no dicen si la etiqueta marca el inicio o el final de la ventana. **Se toma como inicio de la hora** (`timestamp_utc = MESS_DATUM`; "
        "el valor se usa desde `MESS_DATUM + 1 h`). Si la etiqueta fuera el final de la ventana, esto solo retrasa la información una hora; nunca filtra futuro.",
        "",
        "## Limitaciones",
        "",
    ]
    out += [f"- {limitation}" for limitation in report.known_limitations]
    return "\n".join(out) + "\n"


def render_features_markdown(card: dict, summary: dict, quality: dict, eaqi: dict) -> str:
    """Quality report of the ``de_no2_h6`` table: coverage, splits, NO2 per split, EAQI bands, meteorological matches."""
    split = quality["splits"]["windows"]
    tot_rows = sum(r["rows"] for r in summary["per_year"])
    tot_c = sum(r["complete"] for r in summary["per_year"])
    out = [
        "# Calidad de la tabla `de_no2_h6` (NO₂ a +6 h, Alemania)",
        "",
        "Generado por `python -m atlas.domains.air.de_features` (AT-070). No editar a mano. Misma tabla, columnas y semántica temporal que "
        "`madrid_no2_h6` ([`madrid_no2_h6.md`](madrid_no2_h6.md)); fuentes en [`de_eea_air_quality.md`](de_eea_air_quality.md) y [`de_dwd_meteo_quality.md`](de_dwd_meteo_quality.md).",
        "",
        f"Versión: `{card['data_version']}`; filas: {card['rows']['total']:,} = {card['rows']['stations']} estaciones x {card['rows']['hours']:,} horas de emisión (UTC); "
        f"completas: {tot_c:,} ({pct(tot_c, tot_rows)}). `completa` = las 9 features recomendadas y el target no nulos "
        f"({', '.join(f'`{n}`' for n in card['recommended_features'])}).",
        "",
        "## Filas por año de emisión (UTC)",
        "",
        table(["año", "filas", "completas", "% completas"], [[r["year"], f"{r['rows']:,}", f"{r['complete']:,}", pct(r["complete"], r["rows"])] for r in summary["per_year"]]),
        "",
        "## Fracción de filas con cada columna no nula, por año",
        "",
    ]
    names = list(next(iter(summary["feature_non_null_fraction_per_year"].values())))
    out += [table(["año", *names], [[y, *[pct(vals[n], 1) for n in names]] for y, vals in summary["feature_non_null_fraction_per_year"].items()]), ""]
    out += [
        "## Splits (protocolo de Madrid)",
        "",
        f"Ventanas de hora de emisión semiabiertas, embargo {quality['splits']['embargo_hours']} h antes de cada periodo posterior. {quality['splits']['note']}",
        "",
        table(
            ["split", "emisión (UTC)", "filas", "con target", "completas", "estaciones con filas completas"],
            [[k, f"{v['issued_from_utc']} – {v['issued_to_utc']}", f"{v['rows']:,}", f"{v['rows_with_target']:,}", f"{v['complete_rows']:,}", v["stations_with_complete_rows"]] for k, v in split.items()],
        ),
        "",
        "## NO₂ del target por split (µg/m³, filas completas)",
        "",
        table(
            ["split", "n", "media", "desv.", "mín", "p05", "p25", "p50", "p75", "p95", "p99", "máx"],
            [[k, f"{d['n']:,}", *[f"{d[c]:.1f}" for c in ("mean", "std", "min", "p05", "p25", "p50", "p75", "p95", "p99", "max")]] for k, v in split.items() for d in [v["target_distribution"]["complete"]]],
        ),
        "",
        "Media del target por tipo de estación y zona (filas completas):",
        "",
    ]
    rows = []
    for k, items in quality["mean_target_by_station_type"].items():
        for it in items:
            rows.append([k, it["station_type"], it["station_area"], it["stations"], f"{it['complete_rows']:,}", f"{it['mean_target']:.1f}"])
    out += [table(["split", "tipo", "zona", "estaciones", "filas completas", "media"], rows), ""]
    e = quality["eaqi"]
    labels = [c["label"] for c in eaqi["classes"]]
    bands = ", ".join(f"{c['label']} {c['lower']}-{c['upper']}" if c["upper"] is not None else f"{c['label']} >{c['lower'] - 1}" for c in eaqi["classes"])
    out += [
        "## Bandas del Índice Europeo de Calidad del Aire (EAQI) para NO₂",
        "",
        f"Umbrales (µg/m³, concentración horaria): {bands}. Fuente: <{e['source_url']}> (consultada {e['accessed']}), tabla de bandas de concentración; copia de la página en `data/raw/eea-air-de/docs/eaqi_airindex.html`.",
        f"Convención de frontera (de Atlas, no de la EEA): {e['boundary_convention']}",
        "",
        f"**¿Coinciden con las bandas del ICA español de Madrid?** {'Sí' if e['equals_ica_no2_madrid'] else 'No'}. {e['comparison_with_ica']}",
        "",
        "Porcentaje de horas de cada banda por split (filas completas; entre paréntesis, todas las filas con target):",
        "",
    ]
    rows = []
    for k, per in e["shares"].items():
        rows.append([k, f"{per['complete']['n']:,}", *[f"{100 * per['complete']['bands'][b]['share']:.1f} % ({100 * per['target_not_null']['bands'][b]['share']:.1f})" for b in labels]])
    out += [table(["split", "n completas", *labels], rows), "", "Para comparar, las mismas filas con las bandas del ICA de Madrid (`configs/ml/ica_no2_scheme.json`):", ""]
    ica = quality["ica_shares_for_comparison"]["shares"]
    ica_labels = list(next(iter(ica.values()))["complete"]["bands"])
    rows = [[k, f"{per['complete']['n']:,}", *[f"{100 * per['complete']['bands'][b]['share']:.2f} %" for b in ica_labels]] for k, per in ica.items()]
    out += [table(["split", "n completas", *ica_labels], rows), ""]
    m = quality["meteo"]
    out += [
        "## Emparejamiento meteorológico (DWD)",
        "",
        f"Regla: estaciones DWD que miden la variable a ≤ {m['max_distance_m'] / 1000:.0f} km (círculo máximo), hasta 3 por variable, rango 1 principal y el resto como suplentes hora a hora; "
        "sin interpolación. Más allá del tope el input es NULL (`missing_reason = no_observation`; ver `association.json`). El tope es la decisión de este informe (la red DWD está separada ~25 km), no un criterio de Madrid (5 km, red densa).",
        "",
        "Distancia (km) a la estación principal, por variable:",
        "",
        table(
            ["variable", "con candidata", "sin candidata", "mín", "p25", "mediana", "p75", "p90", "máx"],
            [
                [v, d["stations_with_candidate"], d["stations_without_candidate"], *[(f"{d['distance_m'][k] / 1000:.1f}" if d["distance_m"][k] is not None else "-") for k in ("min", "p25", "p50", "p75", "p90", "max")]]
                for v, d in m["per_variable"].items()
            ],
        ),
        "",
        f"Estaciones (de {m['stations']}) con estación DWD con datos a ≤ X km, por variable (sensibilidad al tope):",
        "",
    ]
    caps = list(next(iter(m["stations_within_cap_by_cap_m"].values())))
    out += [table(["variable", *[f"≤ {int(c) // 1000} km" for c in caps]], [[v, *[d[c] for c in caps]] for v, d in m["stations_within_cap_by_cap_m"].items()]), ""]
    out += [
        "Filas con la feature meteorológica nula, por motivo (todas `no_observation`):",
        "",
        table(
            ["feature", "filas nulas", "sin estación dentro del tope", "estación pero sin valor válido esa hora"],
            [[c, f"{d['rows_null']:,}", f"{d['no_station_within_cap']['rows']:,}", f"{d['candidate_without_valid_value_that_hour']['rows']:,}"] for c, d in m["meteo_null_rows_by_reason"].items()],
        ),
        "",
        "## Convención temporal",
        "",
        "Igual que Madrid: una fila por (`entity_id`, `issued_at_utc` = t) en una rejilla UTC horaria regular; entradas con clave ≤ t − 1 h (`timestamp_utc` = inicio de la hora, disponible a +1 h); "
        "target = NO₂ de la hora con clave t + 6 h; uniones por igualdad exacta; nulo, nunca 0; calendario local en Europe/Berlin (`valid_hour_local`, `valid_weekday` del instante objetivo). "
        "La fuente EEA está en UTC+01 fijo y la del DWD en UTC, así que no hay horas ambiguas ni inexistentes que excluir (`excluded_local_dates` vacío). "
        "Diferencia con Madrid: la meteorología del DWD tiene etiqueta tomada como inicio de la hora (+1 h de retraso conservador, ver `de_dwd_meteo_quality.md`).",
        "",
    ]
    return "\n".join(out)
