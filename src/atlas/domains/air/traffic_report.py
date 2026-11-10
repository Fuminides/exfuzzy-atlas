"""Markdown rendering of the traffic ingest and correspondence study (``docs/air/madrid_traffic.md``)."""

# ruff: noqa: E501  (prose templates)

from __future__ import annotations

from statistics import median

from atlas.domains.air.report import _table


def _pct(part: float, whole: float) -> str:
    return f"{100 * part / whole:.1f} %" if whole else "-"


def _profile_totals(details: dict) -> dict[tuple[str, str], dict]:
    totals: dict[tuple[str, str], dict] = {}
    for month in details["per_month"]:
        for r in month["file_profile"]:
            t = totals.setdefault(
                (r["tipo_elem"], r["error"]), {"records": 0, "missing": 0, "negative": 0, "over_cap": 0, "points": 0}
            )
            t["records"] += r["records"]
            t["missing"] += r["intensity_missing"]
            t["negative"] += r["intensity_negative"]
            t["over_cap"] += r["intensity_over_cap"]
            t["points"] = max(t["points"], r["points"])
    return totals


def render_markdown(details: dict, summary: dict, config: dict, sizes: dict) -> str:
    assoc, agg = config["association"], config["aggregation"]
    stations = summary["per_station_last_month"]
    radii = [int(r) for r in assoc["study_radii_m"]]
    n_stations = len(stations)
    no_points = summary["stations_without_rule_points_any_month"]
    last = summary["last_month"]
    changes = summary["changes"]
    status = details["selected_status"]
    selected = details["selected_records"]
    flags: dict[str, int] = {}
    for m in details["per_month"]:
        for k, v in m["hourly_by_flag"].items():
            flags[k] = flags.get(k, 0) + v
    hourly = sum(flags.values())
    zero_at = {r: sum(1 for e in stations if e[f"n_{r}m"] == 0) for r in radii}
    few_at = {r: sum(1 for e in stations if 0 < e[f"n_{r}m"] <= 3) for r in radii}
    med = summary["median_distance_by_radius_m"]
    totals = _profile_totals(details)
    over: dict[str, int] = {}
    for (tipo, _err), v in totals.items():
        over[tipo] = over.get(tipo, 0) + v["over_cap"]
    over_by_type = ", ".join(f"{k} {v:,}" for k, v in sorted(over.items()) if v)
    median_rule = median(e["rule_points_last_month"] for e in stations if e["rule_points_last_month"])
    added = sum(v["added"] for v in changes["per_month"].values())
    removed = sum(v["removed"] for v in changes["per_month"].values())
    moved_events = sum(v["moved_over_tolerance"] for v in changes["per_month"].values())

    out = [
        "# Tráfico de Madrid: fuente, correspondencia espacial con las estaciones de aire y agregación horaria (`madrid-traffic`)",
        "",
        "Generado por `python -m atlas.domains.air.traffic` (AT-012). No editar a mano: se regenera con cada ingesta. Features para el modelo: [`madrid_no2_h6_traffic.md`](madrid_no2_h6_traffic.md).",
        "",
        "> **Correlación no es causalidad.** Un punto de medida cuenta vehículos en **un tramo de calle**, no en el entorno de la estación. La asociación es por distancia y es una aproximación. Que el tráfico mejore (o no) un modelo de NO₂ no demuestra que el tráfico cause (o no) el NO₂ medido; el análisis incremental con y sin tráfico es de A4 y no se ha hecho aquí.",
        "",
        "## Resumen",
        "",
        f"- Meses: {details['months'][0]} a {details['months'][-1]} ({len(details['months'])}); versión `{details['data_version']}`; descarga {details['downloaded_at_utc']}.",
        f"- Entrada: {sizes['n_traffic']} zips mensuales de 15 minutos ({sizes['traffic_gb']:.2f} GB, {details['file_records_all_points']:,} registros de todos los puntos) y {sizes['n_points']} ficheros mensuales de ubicación ({sizes['points_mb']:.1f} MB, {sizes['points_in_files']:,}-{sizes['points_in_files_max']:,} puntos por mes).",
        f"- Regla de asociación: puntos a **≤ {assoc['radius_m']:.0f} m** de la estación en el fichero de ubicación **del mismo mes** (tipos {', '.join(assoc['kinds'])}); sin puntos -> feature nula.",
        f"- Agregación: media de los registros válidos de 15 min en veh/h, al menos {agg['min_valid_quarters']} de 4; {hourly:,} filas horarias canónicas (`traffic_intensity`) de los puntos asociados; rango UTC {details['date_range_utc'][0]} a {details['date_range_utc'][1]}.",
        f"- Registros de 15 min de los puntos asociados: {selected:,}; válidos {status.get('valid', 0):,} ({100 * status.get('valid', 0) / selected:.2f} %).",
        f"- Pico de memoria del proceso (RSS) de la ingesta: {details['peak_rss_mb']} MB.",
        "",
        "## Fuentes",
        "",
        _table(
            ["conjunto", "URL", "ficheros", "licencia"],
            [
                [
                    "Tráfico. Histórico de datos del tráfico desde 2013",
                    config["traffic"]["landing_url"],
                    f"{sizes['n_traffic']} zips mensuales (`traffic-AAAA-MM.zip`, un CSV de ~750 MB descomprimido) + PDF de estructura",
                    "CC BY 4.0 (metadatos del portal: `cc-by`)",
                ],
                [
                    "Tráfico. Ubicación de los puntos de medida del tráfico",
                    config["points"]["landing_url"],
                    f"{sizes['n_points']} CSV mensuales (`points-AAAA-MM.csv`) + PDF de estructura",
                    "CC BY 4.0 (metadatos del portal: `cc-by`)",
                ],
            ],
        ),
        "",
        "Atribución: Ayuntamiento de Madrid, datos abiertos (datos.madrid.es). Los tamaños de los ficheros descargados coinciden con los `byteSize` que declara el portal en su RDF (comprobado fichero a fichero). Los sha256 están en `source_manifest.json` de cada carpeta cruda (`data/raw/madrid-traffic`, `data/raw/madrid-traffic-points`) y en `quality_report.json`. El portal ofrece 2013-2022 y 2026; no se han descargado (el rango pedido cubre entrenamiento 2023, validación 2024 y prueba 2025).",
        "",
        "## Esquema, unidades y convenciones (verificado con los datos)",
        "",
        "Cabecera idéntica en los 36 ficheros (el lector falla si cambia): `id;fecha;tipo_elem;intensidad;ocupacion;carga;vmed;error;periodo_integracion`. Documento oficial: `estructura_ds_contenido_trafico_historico.pdf` (versión octubre/2023).",
        "",
        _table(
            ["campo", "contenido", "unidad / valores observados"],
            [
                [
                    "`id`",
                    "punto de medida; «secuencial, único e invariable» según el PDF",
                    "entero; único por fichero; ver estabilidad abajo",
                ],
                [
                    "`fecha`",
                    "inicio del periodo de 15 min, **hora oficial de Madrid sin desfase**",
                    "`AAAA-MM-DD hh:mm:ss` (el PDF dice `dd/mm/yyyy`; los datos usan ISO; el lector acepta ambos)",
                ],
                [
                    "`tipo_elem`",
                    "tipo de punto",
                    "`URB`, `M30`, `C30` (los ficheros de ubicación lo llaman `other`; no documentado) y un `other` suelto",
                ],
                [
                    "`intensidad`",
                    "vehículos del periodo **expresados en veh/h** (dividir entre 4 para vehículos reales)",
                    "veh/h; negativo = sin dato (no aparece), `NaN` = sin dato",
                ],
                ["`ocupacion`", "% de tiempo con el detector ocupado", "%; `NaN` en algunos registros; no se agrega"],
                [
                    "`carga`",
                    "índice sintético de congestión 0-100 (en M30 casi siempre 0)",
                    "adimensional; no se agrega",
                ],
                ["`vmed`", "velocidad media, solo M30", "km/h; 0 en puntos urbanos (no es «sin dato»); no se agrega"],
                [
                    "`error`",
                    "`N` sin errores; `E` muestras no óptimas; `S` muestra errónea no integrada",
                    "observados: `N` y **vacío** (solo M30; no documentado); `E`/`S` no aparecen en 2023-2025",
                ],
                [
                    "`periodo_integracion`",
                    "muestras recibidas en el periodo",
                    "1-15; no se usa como criterio de validez",
                ],
            ],
        ),
        "",
        "Registros de los ficheros por tipo y valor de `error` (los 36 meses, todos los puntos):",
        "",
        _table(
            [
                "tipo_elem",
                "error",
                "registros",
                "puntos (máx. mes)",
                "intensidad NaN",
                "intensidad > " + f"{agg['intensity_max_veh_h']:.0f}",
            ],
            [
                [
                    k[0],
                    f"`{k[1] or '(vacío)'}`",
                    f"{v['records']:,}",
                    v["points"],
                    f"{v['missing']:,}",
                    f"{v['over_cap']:,}",
                ]
                for k, v in sorted(_profile_totals(details).items())
            ],
        ),
        "",
        "Un `error` vacío en M30 marca registros casi siempre en cero (80-89 % de ceros en marzo y octubre de 2023, frente a 0,3-1,1 % con `N`; intensidad media 72-222 frente a ~1,350 veh/h): se consideran **inválidos**. Un cero con `N` se conserva (flujo nocturno real); un sensor atascado en cero con `N` no es detectable.",
        "",
        "### Horario y cambio de hora",
        "",
        "El PDF dice «fecha y hora oficiales de Madrid». Evidencia en los datos: el 2023-03-26 existe la marca `02:00` (una sola, con 4,321 registros) y faltan `02:15-02:45` (93 marcas distintas en el día: 92 reales más esa); el 2023-10-29 la hora local `02:00-02:59` aparece **una sola vez** (4 marcas, sin duplicados) y el día tiene 96 marcas en lugar de 100. Por tanto:",
        "",
        "- Hora local -> UTC con `Europe/Madrid`; `timestamp_utc` = inicio de la hora. Una hora con clave *s* cubre [s, s+1 h) y está disponible en *s*+1 h.",
        f"- Primavera (hora local inexistente): los registros con hora local dentro del hueco se descartan ({status.get('dst_nonexistent_local_time', 0):,}), y la marca `03:00` que sigue al hueco se invalida ({status.get('dst_transition_slot', 0):,}) porque en los datos tiene ~26 % de ceros frente a ~7 % habitual (el periodo integra el salto).",
        f"- Otoño (hora local repetida): no se puede saber qué hora real es la que está en el fichero, así que **las dos horas UTC se escriben con `value=null`, `missing_reason=invalid_observation`, `validity_flag=ambiguous_local_hour`** (CONTRACTS §8.6); {flags.get('ambiguous_local_hour', 0):,} filas.",
        "",
        "## Estabilidad de ids y ubicaciones",
        "",
        f"Los ids son únicos en cada fichero mensual. Entre los {len(summary['months'])} ficheros hay {changes['ids_in_any_month']:,} ids distintos y {changes['ids_in_every_month']:,} están en todos los meses. De un mes al siguiente se **añaden** {added} puntos, se **retiran** {removed} y {moved_events} cambios de coordenadas superan {10:.0f} m (afectan a {len(changes['ids_ever_moved'])} ids; ningún id cambia de tipo). Por eso la asociación se construye con el fichero de ubicación de **cada mes** y no con una foto única: un punto que se mueve entra o sale de la regla en el mes que corresponde. Los puntos por mes (todos los tipos): {min(f['points'] for f in summary['files'].values()):,} en {summary['months'][0]} a {max(f['points'] for f in summary['files'].values()):,} (máx.).",
        "",
        "Comprobado en enero de 2023: 4 ids del fichero de datos (316 registros, uno con id de 10 dígitos que parece basura) no están en el fichero de ubicación de su mes, así que no se pueden situar y no se usan; y 213 puntos del fichero de ubicación no envían ningún dato ese mes.",
        "",
        "## Correspondencia espacial con las estaciones de aire",
        "",
        f"Distancia ortodrómica (haversine) entre las coordenadas oficiales de la estación (AT-010, Geoportal) y las del punto (fichero del mes). Tabla del último mes ({last}); la columna «regla» es el número de puntos a ≤ {assoc['radius_m']:.0f} m ese mes, y los mínimos y máximos son sobre los {len(summary['months'])} meses. «Con datos» son los puntos de la regla con ≥ 50 % de horas válidas en el último mes.",
        "",
        _table(
            ["estación", "nombre"]
            + [f"≤{r} m" for r in radii]
            + [
                "M30 / otro ≤" + f"{int(assoc['radius_m'])}",
                "más cercano (m)",
                "regla",
                "regla mín-máx",
                "mediana dist. regla (m)",
                "con datos",
            ],
            [
                [
                    e["air_entity_id"],
                    e["name"] or "",
                    *[e[f"n_{r}m"] for r in radii],
                    f"{e.get('n_500m_m30', 0)} / {e.get('n_500m_other', 0)}",
                    "-" if e["nearest_in_max_radius_m"] is None else f"{e['nearest_in_max_radius_m']:.0f}",
                    e["rule_points_last_month"],
                    f"{e['rule_points_min_month']}-{e['rule_points_max_month']}",
                    "-" if e.get("rule_median_distance_m") is None else f"{e['rule_median_distance_m']:.0f}",
                    e.get("rule_points_with_data_last_month", "-"),
                ]
                for e in stations
            ],
        ),
        "",
        "### Regla elegida y por qué",
        "",
        f"- **Radio {assoc['radius_m']:.0f} m, todos los tipos juntos, por mes.** Con 250 m, {zero_at[radii[0]]} de las {n_stations} estaciones no tienen ningún punto y {few_at[radii[0]]} tienen 1-3; con 500 m quedan {zero_at[500]} sin puntos ({', '.join(no_points) or 'ninguna'}) y {few_at[500]} con 1-3; con 1 km solo {zero_at[radii[-1]]} sin puntos pero la distancia mediana de los puntos pasa de {med[str(radii[0])]:.0f} m (≤ 250 m) a {med['500']:.0f} m (≤ 500 m) y {med[str(radii[-1])]:.0f} m (≤ 1 km), y el tramo medido deja de estar en el entorno inmediato de la estación. De los tres radios probados, 500 m es el menor que da al menos 3 puntos a todas las estaciones que tienen alguno. La mediana de puntos de la regla por estación es {median_rule:.0f}.",
        "- El radio se eligió **por recuentos y distancias, no por la correlación con el NO₂**, para no ajustar la asociación al resultado. No hay validación independiente de que 500 m sea el radio «correcto»; es una aproximación documentada y la tabla `association.parquet` trae todos los puntos hasta 1 km con su distancia (`in_rule` marca los de la regla), por si A4 quiere un análisis de sensibilidad (requiere repetir la agregación: ~8 s por mes).",
        "- **M30 y urbanos no se separan**: hay puntos M30 a ≤ 500 m solo de 2 estaciones (4 y 2 puntos) y de tipo `other` de ninguna; dos variables por tipo serían nulas en 22 estaciones. Las intensidades M30 son ~5 veces las urbanas (media 1,345 frente a 290 veh/h en octubre de 2023), así que la media mezcla magnitudes distintas en esas dos estaciones; el tipo de cada punto está en `association.parquet`.",
        f"- **Estaciones sin puntos** ({', '.join(no_points) or 'ninguna'}; ambas de tipo suburbana): features de tráfico **nulas** en todas las filas. No se toma tráfico de otra estación ni de la ciudad.",
        "- Estaciones de fondo urbano (p. ej. Villaverde, Farolillo, Retiro, Ensanche de Vallecas, Embajada) tienen solo 3-5 puntos y el más cercano a 213-488 m: la asociación es ahí claramente más débil que en las de tráfico (Plaza de España, Plaza Elíptica, Barrio del Pilar, con 41-50 puntos y alguno a ≤ 60 m).",
        "",
        "Archivos: `association.parquet` (mes, estación, punto, tipo, nombre, distancia, rango, `in_rule`), `association_summary.json`, `points_monthly.parquet` (todos los puntos de cada mes con coordenadas), `point_coverage.parquet` (horas válidas por punto y mes).",
        "",
        "## Agregación horaria y calidad",
        "",
        f"Un registro de 15 min es **válido** si `error = N` y `0 ≤ intensidad ≤ {agg['intensity_max_veh_h']:.0f}` veh/h (un carril satura en ~2,000 veh/h; hay {sum(v['over_cap'] for v in totals.values()):,} registros por encima en los 36 meses: {over_by_type}). La hora es la media de sus registros válidos y solo es valor si hay ≥ {agg['min_valid_quarters']} de 4; si no, es nula (`insufficient_valid_records`), **nunca 0**. Una hora sin ningún registro no tiene fila.",
        "",
        _table(
            ["estado del registro (puntos asociados)", "registros", "% del total"],
            [[k, f"{v:,}", _pct(v, selected)] for k, v in sorted(status.items(), key=lambda kv: -kv[1])],
        ),
        "",
        _table(
            ["filas horarias canónicas por `validity_flag`", "filas", "%"],
            [[k, f"{v:,}", _pct(v, hourly)] for k, v in sorted(flags.items(), key=lambda kv: -kv[1])],
        ),
        "",
        "## Limitaciones",
        "",
        "- Un punto mide **un tramo de calle** (un sentido) o una sección de autovía, no el área que rodea a la estación; la asociación por distancia es una aproximación y no implica que ese tráfico sea la fuente del NO₂ medido. Correlación no es causalidad.",
        "- Los puntos tienen magnitudes muy distintas (calle secundaria frente a M30); la media entre puntos pondera igual a cada uno.",
        "- La calidad de un registro depende solo de la bandera `error` y de un tope de plausibilidad; un sensor atascado con `N` no se detecta. El PDF no explica el significado de `periodo_integracion` en términos de validez.",
        "- Ocupación, carga y velocidad no se agregan (la carga es 0 en casi toda la M30; la velocidad solo existe en M30).",
        "- La latencia real de publicación (el portal publica el mes anterior en la primera quincena) no se ha medido: no se afirma tiempo real. Las features usan solo horas terminadas, pero un uso operativo necesitaría datos más recientes que los mensuales.",
        "- Los ficheros de ubicación son una foto mensual: un movimiento dentro del mes no se refleja hasta el mes siguiente.",
        "- Estos datos son la fuente oficial al descargarlos (2026-10-30); el portal puede revisar ficheros ya publicados (sha256 en el manifiesto).",
        "",
        "## Reproducción",
        "",
        "```bash",
        "export ATLAS_DATA_DIR=/path/to/exfuzzy-atlas/data   # opcional; por defecto <repo>/data",
        "PYTHONPATH=src python -m atlas.domains.air.traffic --months 2023-01:2025-12   # descarga + estudio + horario (~4 min tras la descarga)",
        "PYTHONPATH=src python -m atlas.domains.air.traffic_features --write-spec      # tabla madrid_no2_h6_traffic",
        "```",
        "",
    ]
    return "\n".join(out)
