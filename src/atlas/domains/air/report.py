"""Markdown rendering of the ingest details (``docs/air/madrid_air_quality.md``) and the limitations text."""

# ruff: noqa: E501  (prose templates)

from __future__ import annotations

from atlas.contracts.models import EntityCollection, QualityReport
from atlas.domains.air.parse import MAGNITUDES, Stats


def _table(header: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def render_markdown(details: dict, report: QualityReport, stations: EntityCollection) -> str:
    c = details["counters"]
    years = details["years"]
    names = {f.id: (f.properties.name or "(sin coordenadas oficiales)") for f in stations.features}
    out = [
        "# Calidad de datos: aire horario de Madrid (`madrid-air`)",
        "",
        "Generado por `python -m atlas.domains.air.ingest` (AT-010). No editar a mano: se regenera con cada ingesta.",
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
        "## Ficheros de entrada (sha256)",
        "",
        _table(["fichero", "sha256"], [[k, f"`{v}`"] for k, v in sorted(details["sha256"].items())]),
        "",
        "## Inventario de formatos",
        "",
        "El intérprete oficial es `interprete_ficheros_calidad_aire_horario.pdf`; el esquema CSV es "
        "`PROVINCIA;MUNICIPIO;ESTACION;MAGNITUD;PUNTO_MUESTREO;ANO;MES;DIA;H01;V01;...;H24;V24` (verificado: idéntico en "
        "todos los ficheros leídos, el lector falla si cambia).",
        "",
        _table(
            ["fichero", "estructura", "miembros", "filas CSV / TXT (años pedidos)"],
            [
                [
                    name,
                    i["layout"],
                    ", ".join(f"{k}: {v}" for k, v in sorted(i["members"].items())) or "-",
                    f"{i['rows_in_selected_years'].get('csv', 0):,} / {i['rows_in_selected_years'].get('txt', 0):,}",
                ]
                for name, i in details["inventory"].items()
            ],
        ),
        "",
        "Diferencias observadas entre años y formatos:",
        "",
        "- 2019-2021: ZIP plano con `mmm_moYY.{csv,txt,xml}`; 2022-2024: los mismos ficheros dentro de `AnioYY/`; "
        "2025 en adelante: un único CSV entrecomillado, con BOM UTF-8, que crece cada mes (aquí hasta septiembre de 2026; "
        "solo se usan los años pedidos).",
        "- Valores: 2019-2021 con ceros a la izquierda (`00023`), 2022+ sin ellos y, según magnitud, con decimales (`0.4`). "
        "Siempre punto decimal; el lector acepta también coma.",
        "- TXT: separado por comas, sin cabecera, 9 campos de identificación (provincia, municipio, estación, magnitud, "
        "técnica, periodo `02`, año, mes, día) y 24 pares valor/código. Los CSV no traen el código de técnica como columna "
        "sino como último elemento de `PUNTO_MUESTREO`.",
        "- El CSV no contiene todas las filas del TXT en 2019-2021: faltan PM2.5/PM10 de algunas estaciones y los "
        "sensores meteorológicos (magnitudes 81-89, fuera de alcance). Se hace la unión con precedencia CSV. En 2019-2022 "
        "el ozono del TXT está redondeado a enteros, el CSV tiene dos decimales. No hay diferencias de valor en NO2.",
        "",
        "Registros-hora que solo existen en el TXT (año/magnitud):",
        "",
        ", ".join(f"{k}: {v:,}" for k, v in details["txt_only_slots"].items()) or "ninguno",
        "",
        "## Convención horaria y horario de verano",
        "",
        "- Los valores horarios están en **hora local de Madrid** (el intérprete, apartado 7). `Hnn` es la hora que **termina** "
        "a las `nn:00` locales: el intérprete define `H24` como la media de los seis valores diezminutales de las 23 h a las "
        "24 h, y los datos lo confirman (abajo).",
        "- `timestamp_utc` es el **inicio** de la hora en UTC: `Hnn` empieza a las `(nn-1):00` locales. "
        "`source_timestamp_local` conserva el texto original, p. ej. `2019-03-31 H03`.",
        "- **Hora inexistente (cambio de marzo, día de 23 h):** la hora local 02:00-03:00 no existe; la fuente deja `H03` "
        "inválido (código N) en todas las estaciones. No tiene instante UTC, así que no se escribe fila "
        f"({c['slots_dst_nonexistent']} huecos descartados; {c['slots_dst_nonexistent_not_flagged_invalid']} de ellos con código V).",
        '- **Hora ambigua (cambio de octubre, día de 25 h):** la fuente trae 24 huecos y, según el intérprete, "se elimina el '
        'dato de la hora en la que se produce el retraso" (la repetida). Se asume que `H03` es la primera ocurrencia '
        "(horario de verano, UTC+2); la segunda (01:00Z) no tiene fila. Esta asunción **no se puede comprobar con los datos**: "
        "en octubre ningún hueco aparece inválido de forma sistemática.",
        "",
        "Evidencia (si `Hnn` fuera [`nn:00`, `nn+1:00`), el hueco inexistente sería `H02`, no `H03`): huecos inválidos (código distinto de V) por hora en los días de cambio, sobre todas las filas "
        "estación x magnitud del día.",
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
    ]
    anomalies = details["dst_anomalies"]
    out += [
        "Días de cambio con un comportamiento distinto del esperado: "
        + (", ".join(f"{d} ({', '.join(s)})" for d, s in anomalies.items()) or "ninguno")
        + ". En esos días la alineación horaria de la fuente es dudosa; conviene excluirlos al construir "
        "features y targets.",
        "",
        "## Códigos de validez, magnitudes y unidades",
        "",
        "- `V` = dato validado (único código que produce `value`). `N` = no validado o anulado en la validación (el intérprete, apartado 7): el fichero conserva un número, "
        f"a veces 0 ({c['invalid_slots_with_zero']:,} huecos) y a veces otro valor ({c['invalid_slots_with_number']:,}), y se descarta. `M` aparece en unos pocos huecos y **no está documentado** en el intérprete; se trata "
        "como no válido. Valor vacío = `no_observation`; código distinto de `V` = `invalid_observation`; nunca se escribe 0.",
        "",
        _table(["código", "huecos"], [[k, f"{v:,}"] for k, v in sorted(details["flags"].items())]),
        "",
    ]
    out += [
        _table(["magnitud (feature_name)", "unidad", "estaciones con datos", "filas válidas"], _feature_rows(details)),
        "",
        "Unidades según el anexo II del intérprete (µg/m³ salvo CO y los hidrocarburos TCH/CH4/NMHC, en mg/m³). "
        "Los valores no se reescalan.",
        "",
        "Magnitudes excluidas (no incluidas en el intérprete): "
        + (", ".join(f"{k}: {v:,} huecos" for k, v in details["unknown_magnitude_slots"].items()) or "ninguna")
        + ".",
        "",
        "## Valores perdidos por columna (salida canónica)",
        "",
        _table(["columna", "nulos"], [[k, f"{v:,}"] for k, v in report.missing_by_column.items()]),
        "",
        "## Cobertura de NO2 por estación y año",
        "",
        "Fracción de horas con valor válido sobre las horas reales del año local "
        + ", ".join(f"{y}: {h:,}" for y, h in details["expected_hours"].items())
        + ". Máximo alcanzable: horas del año menos 1 (la hora repetida de octubre no tiene hueco).",
        "",
    ]
    no2 = details["coverage"].get("no2", {})
    out += [
        _table(
            ["estación", "nombre", *map(str, years)],
            [
                [
                    e,
                    names.get(e, ""),
                    *(
                        f"{100 * no2[e].get(str(y), no2[e].get(y, {})).get('fraction', 0):.1f} %"
                        if (str(y) in no2[e] or y in no2[e])
                        else "sin datos"
                        for y in years
                    ),
                ]
                for e in sorted(no2)
            ],
        ),
        "",
        "## Estaciones y geometría oficial",
        "",
    ]
    st = details["stations"]
    opened = max((f.properties.attributes.get("opened_date") or "" for f in stations.features), default="")
    out += [
        f"- Estaciones en la tabla horaria: {st['stations_in_hourly_data']}; en la capa oficial: {st['official_stations']}.",
        f"- En los datos sin coordenadas oficiales: {st['in_data_without_official_coordinates'] or 'ninguna'}.",
        f"- Oficiales sin datos horarios: {st['official_without_hourly_data'] or 'ninguna'}.",
        f"- `CODIGO_CORTO` no coincide con los tres últimos dígitos del código: {st['short_code_mismatch'] or 'ninguno'}.",
        "- Código de 8 dígitos `28079xxx` = `PROVINCIA`+`MUNICIPIO`+`ESTACION` (3 dígitos con ceros) de la tabla horaria.",
        "- Discrepancias de coordenadas entre la capa del Geoportal y el CSV de datos.madrid.es (> 5 m): "
        + (str(st["coordinate_discrepancies_over_5m"]) if st["coordinate_discrepancies_over_5m"] else "ninguna")
        + ".",
        f"- Altas (CSV oficial de datos.madrid.es): la más reciente es del {opened}, antes del periodo ({years[0]}-{years[-1]}). "
        "Las fuentes no publican bajas ni traslados dentro del periodo.",
        f"- Estaciones oficiales sin NO2 en algún año (año sin datos): {st['years_without_no2'] or 'ninguna'}.",
        "",
        "## Limitaciones conocidas",
        "",
        "(En inglés, tal como figuran en `quality_report.json`.)",
        "",
    ]
    out += [f"- {note}" for note in report.known_limitations]
    return "\n".join(out) + "\n"


def _feature_rows(details: dict) -> list[list]:
    units = {name: unit for name, unit in MAGNITUDES.values()}
    rows = []
    for feature, per_station in sorted(details["coverage"].items()):
        valid = sum(v["valid_hours"] for years in per_station.values() for v in years.values())
        rows.append([feature, units[feature], len(per_station), f"{valid:,}"])
    return rows


def _fmt(n: int) -> str:
    return f"{n:,}"


def build_limitations(stats: Stats, reconciliation: dict, anomalies: dict) -> list[str]:
    c = stats.counters
    notes = [
        "Values are Europe/Madrid local-time slots; 'Hnn' is read as the hour ending at nn:00 (so timestamp_utc, the hour "
        "start, is local time of slot nn-1 converted to UTC). Evidence: slot H03 is invalid on every spring-forward day.",
        f"DST: {_fmt(c['slots_dst_nonexistent'])} source slots fall in the nonexistent spring hour and get no row; the repeated "
        "fall-back hour has no slot in the source, so it is absent for every station (max coverage is 8759/8760 in a "
        "non-leap year). Slot H03 on fall-back days is assumed to be the first occurrence (UTC+2); that assumption is "
        "documented by the interpreter but not verifiable from the data. Transition days with slots invalid for every "
        "row besides the expected spring H03: " + (", ".join(f"{d} {s}" for d, s in anomalies.items()) or "none") + ".",
        f"Validity: only code V is valid. {_fmt(stats.by_flag.get('N', 0))} slots are N (not validated or annulled; the file "
        f"still holds a number, 0 in {_fmt(stats.counters['invalid_slots_with_zero'])} invalid slots and another value in "
        f"{_fmt(stats.counters['invalid_slots_with_number'])}, and it is discarded) and {stats.by_flag.get('M', 0)} slots carry code M, which the interpreter does not "
        "document; both become value=null / invalid_observation.",
        f"{c['valid_negative_rows']} valid readings are negative (NO, NOx, PM2.5 instrument noise); they are kept as "
        "published and counted as outliers_flagged.",
        f"CSV vs TXT: {_fmt(c['overlap_slots_cross_format'])} slots exist in both formats of the annual ZIPs (CSV kept). TXT adds "
        f"{_fmt(sum(stats.txt_only_slots.values()))} slots the CSV lacks (listed per year/feature in ingest_details.json). "
        "Ozone in the TXT of 2019-2022 is rounded to integers; the CSV (kept) has two decimals.",
        f"Excluded: {_fmt(sum(stats.unknown_magnitude_slots.values()))} slots of magnitudes not in the interpreter (81-89, "
        "meteorological sensors that appear in the 2019 files); meteorology is AT-011.",
        f"Impossible calendar dates: {c['rows_impossible_date']} source rows (none expected); they cannot be given a "
        "timestamp_utc, so no canonical row is written.",
        "Absent station-days are not materialised as null rows: coverage is computed against the calendar hours of each year.",
        "Station coordinates are the current official ones; the sources give no dated history of relocations. "
        + (
            "Coordinates disagree between the Geoportal layer and the datos.madrid.es CSV for: "
            + ", ".join(
                f"{k} ({v['distance_m']:.0f} m)" for k, v in reconciliation["coordinate_discrepancies_over_5m"].items()
            )
            + "; the Geoportal value is used."
            if reconciliation["coordinate_discrepancies_over_5m"]
            else "The two official sources agree within 5 m."
        ),
        "Stations without any NO2 reading in some year of the period (listed in the official layer but absent from "
        "that year's published file): "
        + (", ".join(f"{e} {ys}" for e, ys in reconciliation["years_without_no2"].items()) or "none")
        + ".",
        "From 2025 some PM sampling points have technique code 'A' (not defined in the interpreter, whose footnote only says "
        "that since 2024 microbalance and optical-spectrometry analysers coexist) next to 47; the technique is not part of "
        "the canonical key, and no station reports both techniques for the same magnitude.",
    ]
    return notes
