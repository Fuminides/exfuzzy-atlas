"""Known limitations (QualityReport) and the generated dataset card ``docs/mobility/nyc_tlc_yellow_dataset_card.md``."""

# ruff: noqa: E501  (prose templates)

from __future__ import annotations

from atlas.contracts.models import QualityReport
from atlas.domains.mobility.aggregate import REASONS

REASON_LABELS = {
    "null_timestamp": "timestamp nulo",
    "pickup_outside_file_month": "recogida fuera del mes del fichero",
    "dropoff_before_pickup": "bajada anterior a la recogida",
    "zero_duration": "duración cero",
    "duration_over_max": "duración mayor que el máximo",
    "pickup_zone_invalid": "PULocationID nulo o fuera del lookup",
    "pickup_zone_unknown_or_outside": "PULocationID 264/265 o sin polígono",
    "pickup_nonexistent_local_hour": "hora local inexistente (primavera)",
    "pickup_ambiguous_local_hour": "hora local ambigua (otoño)",
}
WEEKDAYS = {1: "lun", 2: "mar", 3: "mié", 4: "jue", 5: "vie", 6: "sáb", 7: "dom"}


def _fmt(n) -> str:
    return f"{n:,}" if isinstance(n, int) else str(n)


def _pct(value) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _table(header: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def _coverage_note(summary: dict) -> str:
    months = [m["month"] for m in summary["by_month"]]
    span = f"{len(months)} consecutive months ({months[0]} to {months[-1]})"
    if len(months) >= 12:
        return (
            f"{span}: a single year, so no year-over-year comparison, one occurrence of each holiday and no weather. "
            "The cbd_congestion_fee regime (congestion pricing in Manhattan below 60th St) began 2025-01-05 and is inside the "
            "window: the first months of the period are before it, the last ones after it."
        )
    return (
        f"Only {span} (they include the cbd_congestion_fee regime that began 2025-01-05 when they reach 2025): seasonality, "
        "most holidays and weather are not represented."
    )


def build_limitations(config: dict, zones: dict, summary: dict, filtered: dict) -> list[str]:
    n_filtered = sum(filtered.values())
    total = n_filtered + summary["total_pickups"]
    ambiguous = filtered.get("pickup_ambiguous_local_hour", 0)
    return [
        "Completed yellow-taxi trips only (vendor-reported). Not unmet demand, not all urban mobility (no green cabs, FHV, "
        "ride-hailing or transit), and not an emissions or congestion measure.",
        "Timestamps are naive local wall-clock times (no UTC offset in the files; the data dictionary does not state the zone). "
        "Nonexistent spring-forward hours are dropped and counted; the repeated fall-back hour cannot be split between its two "
        "occurrences, so both UTC hours are written as null (invalid_observation, validity_flag=ambiguous_local_hour) and the pooled "
        f"trips are excluded. In the ingested months: {ambiguous} pickups in an ambiguous hour, "
        f"{filtered.get('pickup_nonexistent_local_hour', 0)} in a nonexistent hour.",
        f"Zero versus missing: every zone-hour inside the covered period has a row; no pickup means value=0 and n_records=0 "
        f"({summary['share_zero_zone_hours']:.1%} of zone-hours, {_pct(summary['share_zero_zone_hours_active_zones'])} among the "
        f"{summary['active_zones']} zones with at least {summary['active_zone_min_trips']} pickups). Hours outside the period "
        "have no rows. A zero means no recorded yellow-taxi pickup, not that nobody travelled there.",
        f"{n_filtered:,} of {total:,} trips ({n_filtered / total:.2%}) are filtered (incoherent time, duration above "
        f"{config['max_trip_hours']} h, or LocationID 264/265). The filter reads the dropoff time of the record, which would not be known "
        "at prediction time, but it only removes corrupt records; no dropoff or fare field enters the series.",
        "Zero-duration trips jump between months and are concentrated in VendorID 7 (Helix); they may be cancelled or test meter "
        "activations, so month-to-month totals carry a vendor-reporting component (per-month counts in the dataset card).",
        "Exact duplicate trip rows: none found with SELECT DISTINCT over all columns; near-duplicates cannot be detected because the "
        "files have no trip identifier.",
        f"Zones: {zones['entities_with_geometry']} polygons; LocationIDs {zones['entities_without_geometry']} have no polygon "
        "(geometry null) and their pickups are not in the series. "
        f"{len(zones['names_shared_by_several_ids'])} zone names are shared by several IDs. {len(summary['zones_without_pickups'])} polygons "
        f"({summary['zones_without_pickups']}) have no pickup at all in the period. Boundaries are the current TLC shapefile applied to "
        "the whole period; its Shape_Leng/Shape_Area attributes are in degrees and are ignored (areas are recomputed in EPSG:2263).",
        "The TLC publishes the data as is and makes no representation as to its accuracy; no explicit open licence is attached. "
        "Review the terms before redistributing derived data.",
        _coverage_note(summary),
    ]


def _schema_section(details: dict) -> str:
    schemas = details["schemas"]
    months = list(schemas)
    columns = list(dict.fromkeys(c for s in schemas.values() for c in s))
    rows = []
    for column in columns:
        types = [schemas[m].get(column, "-") for m in months]
        rows.append([f"`{column}`", *types, "igual" if len(set(types)) == 1 else "**distinto**"])
    only = [c for c in columns if any(c not in schemas[m] for m in months)]
    note = (
        "Columnas que no están en todos los meses: " + ", ".join(f"`{c}`" for c in only) + "."
        if only
        else "Los ficheros tienen exactamente las mismas columnas y tipos. `cbd_congestion_fee` (tasa de la zona de congestión, desde "
        "2025-01-05) existe en todos; los ficheros de 2024 no la tienen y, según los metadatos Parquet remotos, 2026-07/08/09 añaden además "
        "`request_source` (no se ingieren)."
    )
    return _table(["columna", *months, "entre meses"], rows) + "\n\n" + note


def render_markdown(details: dict, report: QualityReport) -> str:
    s = details["summary"]
    c = details["counters"]
    z = details["zones"]
    months = details["months_detail"]
    filtered_rows = [
        [m["month"], _fmt(m["raw_rows"]), *[_fmt(m["filtered"][r]) for r in REASONS], _fmt(m["kept_rows"])] for m in months
    ]
    filtered_rows.append(["total", _fmt(c["raw_rows"]), *[_fmt(c["filtered"][r]) for r in REASONS], _fmt(c["valid_rows"])])
    hourly = {(h["day_type"], h["local_hour"]): h["mean_citywide_trips"] for h in s["hourly_profile"]}
    sd = z["simplification"]
    dist = s["count_distribution_nonzero"]

    def zone_table(rows: list[dict]) -> str:
        return _table(
            ["zona", "nombre", "recogidas", "horas con recogidas", "% horas con 0"],
            [[t["zone"], t["name"], _fmt(t["trips"]), _fmt(t["hours_with_pickups"]), _pct(t['share_zero_hours'])] for t in rows],
        )

    dst_lines = [
        f"- **{day}**: {info['utc_hours_in_local_day']} horas UTC en el día local. Recogidas de toda la ciudad por hora local: "
        + ", ".join(f"{h}h={'-' if v is None else _fmt(v)}" for h, v in info["citywide_trips_by_local_hour"].items())
        + (
            f". Recogidas en la hora inexistente 02h: {_fmt(sum(m['nonexistent_trips_by_hour'].get(f'{day} 02:00:00', 0) for m in months))}."
            if info["utc_hours_in_local_day"] < 24
            else ". La hora local 01h es ambigua: sus dos horas UTC son null para todas las zonas (recogidas de ese rótulo local excluidas: "
            f"{_fmt(sum(m['ambiguous_trips_by_hour'].get(f'{day} 01:00:00', 0) for m in months))})."
        )
        for day, info in s["dst_days"].items()
    ]
    zero_vendor = "; ".join(
        f"{m['month']}: " + ", ".join(f"{k}={_fmt(v)}" for k, v in m["zero_duration_by_vendor"].items()) for m in months
    )
    special = "; ".join(
        f"{m['month']}: " + ", ".join(f"{k}={_fmt(v)}" for k, v in sorted(m["special_zone_counts"].items())) for m in months
    )
    lines = [
        "# Tarjeta de datos: taxi amarillo de Nueva York por zona y hora (`nyc-tlc`)",
        "",
        "Generado por `python -m atlas.domains.mobility.ingest` (AT-030). No editar a mano: se regenera con cada ingesta. "
        "Decisiones de diseño y nota de escalado en [`README.md`](README.md).",
        "",
        "## Resumen",
        "",
        f"- Versión de datos: `{details['data_version']}`; meses locales: {', '.join(details['months'])} "
        f"(periodo cubierto UTC `[{details['covered_period_utc'][0]}, {details['covered_period_utc'][1]})`).",
        f"- Viajes en bruto: {_fmt(c['raw_rows'])}; filtrados: {_fmt(c['filtered_total'])} ({c['filtered_total'] / c['raw_rows']:.2%}); "
        f"contados en la serie: {_fmt(c['valid_rows'])}.",
        f"- Filas zona-hora: {_fmt(s['rows'])} ({s['zones']} zonas × {_fmt(s['utc_hours'])} horas UTC); con valor 0: {_fmt(s['zero_rows'])} "
        f"({s['share_zero_zone_hours']:.1%}); nulas (hora local ambigua): {_fmt(s['null_rows'])}.",
        f"- Fuente: {report.source_url}; descarga: {details['downloaded_at_utc']}.",
        f"- Licencia / condiciones: {report.license}",
        "- Atribución: NYC Taxi & Limousine Commission (TLC) Trip Record Data y Taxi Zones.",
        "- **Qué es y qué no**: viajes completados de taxi amarillo con taxímetro. No es demanda insatisfecha, ni movilidad total, ni emisiones, ni congestión.",
        "",
        "## Ficheros de entrada (sha256)",
        "",
        _table(["fichero", "sha256"], [[k, f"`{v}`"] for k, v in sorted(details["sha256"].items())]),
        "",
        "## Esquema por fichero",
        "",
        _schema_section(details),
        "",
        "## Viajes por mes y filtros",
        "",
        "Cada viaje se cuenta bajo **el primer** motivo que cumple (en este orden), así que las columnas suman exactamente `bruto - contados`. "
        f"Umbral de duración: {details['max_trip_hours']} h (medido en enero y marzo de 2025: la mediana de las duraciones positivas es de ~12 min, el percentil 99,9 de ~1,7 h y "
        "solo ~170-200 viajes/mes están entre 3 h y 6 h; por encima de 12 h son casi siempre medidores que se dejaron encendidos).",
        "",
        _table(["mes", "bruto", *[REASON_LABELS[r] for r in REASONS], "contados"], filtered_rows),
        "",
        "Conteo independiente de cada filtro (un viaje puede cumplir varios):",
        "",
        _table(
            ["mes", *[r for r in REASONS if r != "null_timestamp"], "fuera de mes pero dentro del periodo cubierto"],
            [
                [m["month"], *[_fmt(m["flags_independent"][r]) for r in REASONS if r != "null_timestamp"], _fmt(m["out_of_month_inside_covered_period"])]
                for m in months
            ],
        ),
        "",
        f"Duración cero por `VendorID` (1 CMT, 2 Curb, 6 Myle, 7 Helix): {zero_vendor}. PULocationID 264/265 filtrados: {special}. "
        f"Duplicados exactos detectados (se conservarían): {_fmt(c['duplicate_rows_kept'])}.",
        "",
        "## Serie zona-hora",
        "",
        "Una fila por zona (polígonos del shapefile) y hora UTC de **todo** el periodo cubierto: `value` = nº de recogidas (`feature_name=pickups`, `unit=trips`), "
        "`timestamp_utc` = inicio de la hora, `aggregation_window_*_utc` = esa hora, `n_records` = recogidas, `source_timestamp_local` = hora local con desfase.",
        "",
        "**0 ≠ null.** Una zona-hora sin recogidas dentro del periodo cubierto es un 0 genuino (`n_records=0`). Fuera del periodo no hay filas. "
        "Solo la hora local ambigua de otoño produce `null` (`missing_reason=invalid_observation`, `validity_flag=ambiguous_local_hour`).",
        "",
        _table(
            ["mes local", "horas UTC", "filas zona-hora", "recogidas", "filas con 0", "filas null"],
            [[m["month"], m["hours"], _fmt(m["zone_hours"]), _fmt(m["trips"]), _fmt(m["zero_zone_hours"]), m["null_zone_hours"]] for m in s["by_month"]],
        ),
        "",
        f"Zona-horas con 0: **{s['share_zero_zone_hours']:.1%}** en total y {_pct(s['share_zero_zone_hours_active_zones'])} entre las {s['active_zones']} zonas con "
        f"≥ {s['active_zone_min_trips']} recogidas en el periodo. Recuentos > 0 por zona-hora: mediana {dist['p50']:.0f}, p90 {dist['p90']:.0f}, "
        f"p99 {dist['p99']:.0f}, máximo {dist['max']:.0f}. Serie muy asimétrica y con muchos ceros: pocas zonas concentran la demanda.",
        "",
        "### Zonas con más recogidas",
        "",
        zone_table(s["top_zones"]),
        "",
        "### Zonas con menos recogidas (entre las que tienen alguna)",
        "",
        zone_table(s["bottom_zones_with_pickups"]),
        "",
        f"Zonas con polígono y **cero** recogidas en todo el periodo: {s['zones_without_pickups']}.",
        "",
        "### Patrón horario y semanal (total de la ciudad, hora local)",
        "",
        "Media de recogidas por hora local sobre horas completas; laborable = lun-vie, fin de semana = sáb-dom.",
        "",
        _table(
            ["hora", "laborable", "fin de semana"],
            [[f"{h:02d}", f"{hourly.get(('weekday', h), 0):,.0f}", f"{hourly.get(('weekend', h), 0):,.0f}"] for h in range(24)],
        ),
        "",
        _table(
            ["día", *[WEEKDAYS[w["isodow"]] for w in s["weekday_profile"]]],
            [["media diaria de recogidas", *[f"{w['mean_daily_citywide_trips']:,}" for w in s["weekday_profile"]]]],
        ),
        "",
        "## Horario de verano (DST)",
        "",
        "Estrategia (detalle en `aggregate.py` y `README.md`): la malla de horas UTC se construye con `zoneinfo`. La hora local inexistente (02:00-02:59 del "
        "día de primavera, p. ej. 9 de marzo de 2025) no puede mostrarla un taxímetro: esas recogidas se descartan y se cuentan. La hora local ambigua (01:00-01:59 del "
        "día de otoño, p. ej. 3 de noviembre de 2024) se escribe como `null` en sus dos horas UTC y sus viajes se excluyen. Ambos casos están cubiertos por tests sintéticos; "
        "los días con cambio que caen en los meses ingeridos se detallan abajo.",
        "",
        *(dst_lines or ["- No hay días con desplazamiento horario en los meses ingeridos."]),
        "",
        "## Zonas y geometría",
        "",
        f"- Fuente: `taxi_zones.zip` (shapefile ESRI, {z['source_crs']} «{z['source_crs_name']}», {z['shapefile_polygons']} polígonos, {_fmt(z['source_total_vertices'])} vértices). "
        f"Lookup: {z['lookup_rows']} filas; en el shapefile pero no en el lookup: {z['in_shapefile_not_in_lookup'] or 'ninguna'}; "
        f"nombre/borough distinto entre lookup y shapefile: {z['name_or_borough_differs_lookup_vs_shapefile'] or 'ninguna'}.",
        f"- Sin polígono (geometría `null`, por diseño): {z['entities_without_geometry']} (264 «Unknown», 265 «Outside of NYC»). Nombres compartidos por varios IDs: "
        + "; ".join(f"«{n}» → {ids}" for n, ids in z["names_shared_by_several_ids"].items())
        + f". Polígonos de origen inválidos: {z['source_invalid_polygons']}; el recubrimiento original {'sí' if z['source_coverage_valid'] else 'no'} es un coverage válido (solapes/huecos mínimos).",
        f"- `taxi_zones.geojson` (referencia, WGS84, 1e-7°): {_fmt(z['full']['vertices'])} vértices, {z['files']['taxi_zones.geojson'] / 1e6:.2f} MB, {z['full']['types']}. "
        f"`taxi_zones_simplified.geojson` (frontend): {_fmt(z['simplified']['vertices'])} vértices ({sd['vertex_reduction_pct']} % menos), {z['files']['taxi_zones_simplified.geojson'] / 1e3:.0f} kB.",
        f"- Simplificación: {sd['method']}; tolerancia {sd['tolerance_ft']:.0f} ft ({sd['tolerance_m']} m), redondeo 1e-5° (~1 m). Polígonos válidos: {z['simplified']['all_valid']}; "
        f"vacíos: {z['simplified']['any_empty']}; coverage válido tras simplificar: {sd['coverage_valid_after_simplify']} (bordes compartidos idénticos a ambos lados); "
        f"cambio de área total {sd['total_area_change_pct']} %, máximo por zona {sd['max_zone_area_change_pct']} %.",
        f"- Reproyección: bbox {z['bbox_lon_lat']}; todos los centroides dentro del bbox de NYC: {z['all_centroids_inside_nyc_bbox']}.",
        "",
        "## Rendimiento",
        "",
        f"DuckDB con `memory_limit={details['memory_limit']}` y {details['threads']} hilos, un mes cada vez; los viajes nunca pasan por pandas.",
        "",
        _table(
            ["mes", "viajes", "segundos", "RSS tras el mes (MB)", "pico RSS hasta ahora (MB)"],
            [[p["month"], _fmt(p["raw_rows"]), p["seconds"], p["rss_mb_after"], p["peak_rss_mb_so_far"]] for p in details["perf"]["per_month"]],
        ),
        "",
        f"Total (zonas + meses): {details['perf']['total_seconds']} s; pico RSS del proceso {details['perf']['peak_rss_mb']} MB (al inicio {details['perf']['start_rss_mb']} MB).",
        "",
        "## Limitaciones conocidas",
        "",
        *[f"- {note}" for note in report.known_limitations],
        "",
    ]
    return "\n".join(lines)
