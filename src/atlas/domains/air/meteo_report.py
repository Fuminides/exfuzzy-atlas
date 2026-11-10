"""Markdown rendering of the meteorology ingest details (``docs/air/madrid_meteo_quality.md``)."""

# ruff: noqa: E501  (prose templates)

from __future__ import annotations

from atlas.contracts.models import QualityReport
from atlas.domains.air.report import _table


def render_markdown(details: dict, report: QualityReport, names: dict[str, str]) -> str:
    c = details["counters"]
    years = details["years"]
    st = details["stations"]
    out = [
        "# Calidad de datos: meteorología horaria de Madrid (`madrid-meteo`)",
        "",
        "Generado por `python -m atlas.domains.air.meteo` (AT-011). No editar a mano: se regenera con cada ingesta.",
        "",
        "## Resumen",
        "",
        f"- Versión de datos: `{details['data_version']}`; años: {years[0]}-{years[-1]}.",
        f"- Rango (UTC): {details['date_range_utc'][0]} a {details['date_range_utc'][1]}.",
        f"- Filas canónicas: {c['canonical_rows']:,}; con valor válido: {c['valid_rows']:,} "
        f"({100 * c['valid_rows'] / c['canonical_rows']:.1f} %).",
        "- Filas por motivo: " + ", ".join(f"{k} = {v:,}" for k, v in sorted(details["by_reason"].items())) + ".",
        f"- Duplicados descartados en el mismo formato: {c['duplicate_slots_same_format']}; solapes CSV/TXT "
        f"(se conserva el CSV): {c['overlap_slots_cross_format']:,} registros-hora.",
        f"- Fuente: {report.source_url}; licencia: {report.license}.",
        f"- Descarga: {details['downloaded_at_utc']}.",
        "",
        "## Ficheros de entrada (resumen; sha256 por fichero en `quality_report.json`)",
        "",
        f"{len(details['sha256'])} ficheros: "
        + ", ".join(
            f"{layout}: {n}"
            for layout, n in sorted(
                {
                    lay: sum(1 for i in details["inventory"].values() if i["layout"] == lay)
                    for lay in {i["layout"] for i in details["inventory"].values()}
                }.items()
            )
        )
        + ". El intérprete es `interprete_datos_meteorologicos.pdf`; el esquema es el mismo que el del aire "
        "(`PROVINCIA;MUNICIPIO;ESTACION;MAGNITUD;PUNTO_MUESTREO;ANO;MES;DIA;H01;V01;...;H24;V24`).",
        "",
        "Registros-hora que solo existen en el TXT (año/magnitud): "
        + (", ".join(f"{k}: {v:,}" for k, v in details["txt_only_slots"].items()) or "ninguno")
        + ".",
        "",
        "## Convención horaria y horario de verano",
        "",
        "El intérprete meteorológico **no dice** en qué huso están los datos ni cómo trata el cambio de hora (solo que «H01 "
        "corresponde al dato de la 1 de la mañana»). Se aplica la misma convención que al aire (hora local de Madrid; `Hnn` "
        "es la hora que termina a las `nn:00`) y se comprueba con los datos: en cada cambio de marzo el hueco `H03` debe "
        "ser inválido en todas las filas.",
        "",
    ]
    rows = []
    for day, info in details["dst_days"].items():
        full = [f"H{i + 1:02d}" for i, n in enumerate(info["invalid_per_slot"]) if info["rows"] and n == info["rows"]]
        rows.append(
            [
                day,
                "marzo (23 h)" if day[5:7] < "06" else "octubre (25 h)",
                info["rows"],
                ", ".join(full) or "ninguno",
                max(info["invalid_per_slot"]),
            ]
        )
    out += [
        _table(["día", "cambio", "filas", "huecos inválidos en todas las filas", "máx. inválidos en un hueco"], rows),
        "",
        "Días de cambio con un comportamiento distinto del esperado: "
        + (", ".join(f"{d} ({', '.join(s)})" for d, s in details["dst_anomalies"].items()) or "ninguno")
        + ".",
        "",
        "## Códigos de validez, magnitudes y unidades",
        "",
        "Solo `V` genera `value`; cualquier otro código → `null` con `invalid_observation`; hueco vacío → `no_observation`. "
        f"El número que acompaña a un código no válido se descarta (0 en {c['invalid_slots_with_zero']:,} huecos, otro valor en "
        f"{c['invalid_slots_with_number']:,}).",
        "",
        _table(["código", "huecos"], [[k, f"{v:,}"] for k, v in sorted(details["flags"].items())]),
        "",
        _table(
            [
                "magnitud (feature_name)",
                "unidad",
                "estaciones con datos",
                "filas válidas",
                "valores válidos fuera de rango (marcados)",
            ],
            _feature_rows(details, report),
        ),
        "",
        "Magnitudes excluidas (no incluidas en el intérprete): "
        + (", ".join(f"{k}: {v:,} huecos" for k, v in details["unknown_magnitude_slots"].items()) or "ninguna")
        + ".",
        "",
        "## Cobertura por estación y magnitud",
        "",
        "Fracción de las horas del periodo con valor válido (media de los años pedidos; un año sin datos cuenta como 0; "
        "`-` = la estación no mide la magnitud en los datos). Detalle por año en `ingest_details.json`.",
        "",
    ]
    features = sorted({f for per in details["coverage_station_feature_year"].values() for f in per})
    cover_rows = []
    for e in sorted(details["coverage_station_feature_year"]):
        per = details["coverage_station_feature_year"][e]
        cells = []
        for f in features:
            if f not in per:
                cells.append("-")
            else:
                vals = [per[f].get(str(y), per[f].get(y, 0.0)) for y in years]
                cells.append(f"{100 * sum(vals) / len(vals):.0f} %")
        cover_rows.append([e, names.get(e, ""), *cells])
    out += [_table(["estación", "nombre", *features], cover_rows), ""]
    out += [
        "## Estaciones y geometría oficial",
        "",
        f"- Ubicaciones oficiales (CSV `Meteorológicos. Estaciones de control`): {st['official']}.",
        f"- En los datos sin coordenadas oficiales: {st['in_data_without_coordinates'] or 'ninguna'}.",
        f"- Oficiales sin datos horarios: {st['official_without_data'] or 'ninguna'}.",
        f"- Sensores declarados distintos de las magnitudes con datos: {st['sensor_mismatch'] or 'ninguno'}.",
        "",
        "## Limitaciones conocidas",
        "",
        "(En inglés, tal como figuran en `quality_report.json`.)",
        "",
    ]
    out += [f"- {note}" for note in report.known_limitations]
    return "\n".join(out) + "\n"


def _feature_rows(details: dict, report: QualityReport) -> list[list]:
    per_feature: dict[str, set] = {}
    for entity, feats in details["coverage_station_feature_year"].items():
        for feature in feats:
            per_feature.setdefault(feature, set()).add(entity)
    flagged = details["plausibility_flagged"]
    return [
        [
            feature,
            report.value_units[feature],
            len(per_feature[feature]),
            f"{details['valid_by_feature'].get(feature, 0):,}",
            flagged.get(feature, 0),
        ]
        for feature in sorted(per_feature)
    ]
