# Calidad de datos: aire horario de Madrid (`madrid-air`)

Generado por `python -m atlas.domains.air.ingest` (AT-010). No editar a mano: se regenera con cada ingesta.

## Resumen

- Versión de datos: `madrid-air-2019-2025-v1`; años: 2019-2025.
- Rango (UTC): 2018-12-31T23:00:00+00:00 a 2025-12-31T22:00:00+00:00.
- Filas canónicas: 8,330,457; con valor válido: 8,179,876 (98.2 %).
- Filas por motivo: invalid_observation = 150,581, valid = 8,179,876.
- Duplicados descartados en el mismo formato: 0; solapes CSV/TXT (se conserva el CSV): 7,201,536 registros-hora.
- Fuente: https://datos.madrid.es/dataset/201200-0-calidad-aire-horario; licencia: CC BY 4.0 (Creative Commons Attribution 4.0 International), https://creativecommons.org/licenses/by/4.0/legalcode.es.
- Descarga: 2026-10-30T16:37:20+00:00.

## Ficheros de entrada (sha256)

| fichero | sha256 |
|---|---|
| madrid-air-stations/estaciones-control-aire-estructura.pdf | `413700ce656f3f4612ec7f8d23560361000ff947074c18f984fd90f6d711b580` |
| madrid-air-stations/estaciones-control-aire.csv | `2c84ca974088a6d5de13509489196ddefeee83fcae4999798b00603aa951cd1b` |
| madrid-air-stations/geoportal_layer5_estaciones.geojson | `d4f7174dcb5929b65021753fd56e232eeb550b0976d1c71c935169e03274e6fa` |
| madrid-air-stations/geoportal_layer5_metadata.json | `dd429a318a272631426328658040b5f4127b480c26c529b034f240f9a8423950` |
| madrid-air/calidad-aire-horario-2019.zip | `7ff02c08efaf8409cd9a5cabedeb457364cfaf5a9ed0fe78de2a43125ea8d9c9` |
| madrid-air/calidad-aire-horario-2020.zip | `b9eb7e9fabf7da526e4d4a559b172ca4911772344f7a651718327ce522fd8e89` |
| madrid-air/calidad-aire-horario-2021.zip | `92caf78b31c432d4474a4c737fcac1a576d31d584d17a001598cdff8749eb19e` |
| madrid-air/calidad-aire-horario-2022.zip | `2f4aae4def995821763afd8fe586944e63d404819b1a24e5e8a37d1fa07f9d02` |
| madrid-air/calidad-aire-horario-2023.zip | `b3ee481e0a787239dd07b33e93b2da97e31e6b5123d3c659f49e14549fb62b2e` |
| madrid-air/calidad-aire-horario-2024.zip | `f8b7f3090feafcb9175bcd4187e1cf14cc9c965c0baad3af8fcf9d843d326bcd` |
| madrid-air/calidad-aire-horario-desde-2025.csv | `76dd40cc95bc514b0e03295e880128822a18e6490c2821670c479d6888301eea` |
| madrid-air/interprete_ficheros_calidad_aire_horario.pdf | `29a274b439e31c3f2c6d4ef29691152b8fd30cbafc04d222357f0deee2b6e73e` |

## Inventario de formatos

El intérprete oficial es `interprete_ficheros_calidad_aire_horario.pdf`; el esquema CSV es `PROVINCIA;MUNICIPIO;ESTACION;MAGNITUD;PUNTO_MUESTREO;ANO;MES;DIA;H01;V01;...;H24;V24` (verificado: idéntico en todos los ficheros leídos, el lector falla si cambia).

| fichero | estructura | miembros | filas CSV / TXT (años pedidos) |
|---|---|---|---|
| calidad-aire-horario-2019.zip | zip: monthly csv (';', header) + txt (',', no header) | csv: 12, txt: 12, xml (ignored): 12 | 54,956 / 61,522 |
| calidad-aire-horario-2020.zip | zip: monthly csv (';', header) + txt (',', no header) | csv: 12, txt: 12, xml (ignored): 12 | 55,537 / 55,903 |
| calidad-aire-horario-2021.zip | zip: monthly csv (';', header) + txt (',', no header) | csv: 12, txt: 12, xml (ignored): 12 | 48,369 / 48,672 |
| calidad-aire-horario-2022.zip | zip: monthly csv (';', header) + txt (',', no header) | csv: 12, txt: 12, xml (ignored): 12 | 47,223 / 47,223 |
| calidad-aire-horario-2023.zip | zip: monthly csv (';', header) + txt (',', no header) | csv: 12, txt: 12, xml (ignored): 12 | 47,242 / 47,242 |
| calidad-aire-horario-2024.zip | zip: monthly csv (';', header) + txt (',', no header) | csv: 12, txt: 12, xml (ignored): 12 | 46,737 / 46,737 |
| calidad-aire-horario-desde-2025.csv | single csv (';', quoted, UTF-8 BOM, header), several years | - | 45,968 / 0 |

Diferencias observadas entre años y formatos:

- 2019-2021: ZIP plano con `mmm_moYY.{csv,txt,xml}`; 2022-2024: los mismos ficheros dentro de `AnioYY/`; 2025 en adelante: un único CSV entrecomillado, con BOM UTF-8, que crece cada mes (aquí hasta septiembre de 2026; solo se usan los años pedidos).
- Valores: 2019-2021 con ceros a la izquierda (`00023`), 2022+ sin ellos y, según magnitud, con decimales (`0.4`). Siempre punto decimal; el lector acepta también coma.
- TXT: separado por comas, sin cabecera, 9 campos de identificación (provincia, municipio, estación, magnitud, técnica, periodo `02`, año, mes, día) y 24 pares valor/código. Los CSV no traen el código de técnica como columna sino como último elemento de `PUNTO_MUESTREO`.
- El CSV no contiene todas las filas del TXT en 2019-2021: faltan PM2.5/PM10 de algunas estaciones y los sensores meteorológicos (magnitudes 81-89, fuera de alcance). Se hace la unión con precedencia CSV. En 2019-2022 el ozono del TXT está redondeado a enteros, el CSV tiene dos decimales. No hay diferencias de valor en NO2.

Registros-hora que solo existen en el TXT (año/magnitud):

2019/pm10: 5,040, 2019/pm25: 5,544, 2020/pm25: 8,784, 2021/pm25: 7,272

## Convención horaria y horario de verano

- Los valores horarios están en **hora local de Madrid** (el intérprete, apartado 7). `Hnn` es la hora que **termina** a las `nn:00` locales: el intérprete define `H24` como la media de los seis valores diezminutales de las 23 h a las 24 h, y los datos lo confirman (abajo).
- `timestamp_utc` es el **inicio** de la hora en UTC: `Hnn` empieza a las `(nn-1):00` locales. `source_timestamp_local` conserva el texto original, p. ej. `2019-03-31 H03`.
- **Hora inexistente (cambio de marzo, día de 23 h):** la hora local 02:00-03:00 no existe; la fuente deja `H03` inválido (código N) en todas las estaciones. No tiene instante UTC, así que no se escribe fila (951 huecos descartados; 0 de ellos con código V).
- **Hora ambigua (cambio de octubre, día de 25 h):** la fuente trae 24 huecos y, según el intérprete, "se elimina el dato de la hora en la que se produce el retraso" (la repetida). Se asume que `H03` es la primera ocurrencia (horario de verano, UTC+2); la segunda (01:00Z) no tiene fila. Esta asunción **no se puede comprobar con los datos**: en octubre ningún hueco aparece inválido de forma sistemática.

Evidencia (si `Hnn` fuera [`nn:00`, `nn+1:00`), el hueco inexistente sería `H02`, no `H03`): huecos inválidos (código distinto de V) por hora en los días de cambio, sobre todas las filas estación x magnitud del día.

| día | cambio | filas | huecos inválidos en todas las filas | máx. inválidos en un hueco |
|---|---|---|---|---|
| 2019-03-31 | marzo (23 h) | 153 | H03 | 153 |
| 2019-10-27 | octubre (25 h) | 153 | ninguno | 1 |
| 2020-03-29 | marzo (23 h) | 149 | H03 | 149 |
| 2020-10-25 | octubre (25 h) | 154 | ninguno | 14 |
| 2021-03-28 | marzo (23 h) | 136 | H03 | 136 |
| 2021-10-31 | octubre (25 h) | 127 | ninguno | 14 |
| 2022-03-27 | marzo (23 h) | 127 | H03 | 127 |
| 2022-10-30 | octubre (25 h) | 132 | ninguno | 1 |
| 2023-03-26 | marzo (23 h) | 132 | H03 | 132 |
| 2023-10-29 | octubre (25 h) | 126 | ninguno | 1 |
| 2024-03-31 | marzo (23 h) | 128 | H03 | 128 |
| 2024-10-27 | octubre (25 h) | 125 | ninguno | 0 |
| 2025-03-30 | marzo (23 h) | 126 | H03 | 126 |
| 2025-10-26 | octubre (25 h) | 126 | H02, H24 | 126 |

Días de cambio con un comportamiento distinto del esperado: 2025-10-26 (H02, H24). En esos días la alineación horaria de la fuente es dudosa; conviene excluirlos al construir features y targets.

## Códigos de validez, magnitudes y unidades

- `V` = dato validado (único código que produce `value`). `N` = no validado o anulado en la validación (el intérprete, apartado 7): el fichero conserva un número, a veces 0 (55,169 huecos) y a veces otro valor (95,412), y se descarta. `M` aparece en unos pocos huecos y **no está documentado** en el intérprete; se trata como no válido. Valor vacío = `no_observation`; código distinto de `V` = `invalid_observation`; nunca se escribe 0.

| código | huecos |
|---|---|
| M | 58 |
| N | 150,523 |
| V | 8,179,876 |

| magnitud (feature_name) | unidad | estaciones con datos | filas válidas |
|---|---|---|---|
| ben | ug/m3 | 6 | 326,403 |
| ch4 | mg/m3 | 3 | 51,308 |
| co | mg/m3 | 10 | 344,750 |
| ebe | ug/m3 | 6 | 324,530 |
| nmhc | mg/m3 | 3 | 51,306 |
| no | ug/m3 | 24 | 1,434,945 |
| no2 | ug/m3 | 24 | 1,434,945 |
| nox | ug/m3 | 24 | 1,434,946 |
| o3 | ug/m3 | 14 | 801,886 |
| pm10 | ug/m3 | 15 | 778,971 |
| pm25 | ug/m3 | 11 | 491,201 |
| so2 | ug/m3 | 10 | 328,055 |
| tch | mg/m3 | 3 | 51,308 |
| tol | ug/m3 | 6 | 325,322 |

Unidades según el anexo II del intérprete (µg/m³ salvo CO y los hidrocarburos TCH/CH4/NMHC, en mg/m³). Los valores no se reescalan.

Magnitudes excluidas (no incluidas en el intérprete): 83: 34,032 huecos, 86: 34,032 huecos, 81: 17,544 huecos, 82: 17,544 huecos, 87: 14,616 huecos, 88: 14,616 huecos, 89: 14,616 huecos.

## Valores perdidos por columna (salida canónica)

| columna | nulos |
|---|---|
| domain | 0 |
| entity_id | 0 |
| timestamp_utc | 0 |
| source_timestamp_local | 0 |
| timezone | 0 |
| feature_name | 0 |
| value | 150,581 |
| unit | 0 |
| validity_flag | 0 |
| missing_reason | 8,179,876 |
| censoring | 8,330,457 |
| source_id | 0 |
| data_version | 0 |
| aggregation_window_start_utc | 8,330,457 |
| aggregation_window_end_utc | 8,330,457 |
| n_records | 8,330,457 |

## Cobertura de NO2 por estación y año

Fracción de horas con valor válido sobre las horas reales del año local 2019: 8,760, 2020: 8,784, 2021: 8,760, 2022: 8,760, 2023: 8,760, 2024: 8,784, 2025: 8,760. Máximo alcanzable: horas del año menos 1 (la hora repetida de octubre no tiene hueco).

| estación | nombre | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|---|---|
| 28079004 | Pza. de España | 98.7 % | 77.3 % | 71.1 % | 75.7 % | 98.9 % | 98.9 % | 99.0 % |
| 28079008 | Escuelas Aguirre | 95.2 % | 98.5 % | 97.2 % | 99.2 % | 99.0 % | 98.7 % | 98.3 % |
| 28079011 | Ramón y Cajal | 99.7 % | 99.9 % | 99.4 % | 99.4 % | 83.6 % | 99.1 % | 98.6 % |
| 28079016 | Arturo Soria | 99.7 % | 99.3 % | 99.6 % | 71.9 % | 99.3 % | 99.1 % | 98.8 % |
| 28079017 | Villaverde | 99.6 % | 99.6 % | 99.1 % | 99.0 % | 98.7 % | 99.1 % | 98.7 % |
| 28079018 | Farolillo | 99.1 % | 99.1 % | 98.5 % | 99.1 % | 98.7 % | 98.2 % | 98.7 % |
| 28079024 | Casa de Campo | 99.1 % | 99.4 % | 95.6 % | 98.7 % | 94.0 % | 97.6 % | 97.5 % |
| 28079027 | Barajas Pueblo | 99.8 % | 99.8 % | 99.5 % | 99.2 % | 99.0 % | 98.9 % | 98.1 % |
| 28079035 | Pza. del Carmen | 98.3 % | 99.6 % | 99.1 % | 98.6 % | 77.2 % | 98.0 % | 98.6 % |
| 28079036 | Moratalaz | 99.6 % | 99.8 % | 99.3 % | 96.3 % | 99.0 % | 99.0 % | 98.6 % |
| 28079038 | Cuatro Caminos | 95.7 % | 99.6 % | 98.9 % | 99.3 % | 98.9 % | 98.6 % | 98.2 % |
| 28079039 | Barrio del Pilar | 99.3 % | 98.7 % | 99.6 % | 98.9 % | 98.5 % | 98.3 % | 98.4 % |
| 28079040 | Vallecas | 99.8 % | 99.4 % | 99.5 % | 99.4 % | 99.3 % | 99.1 % | 98.6 % |
| 28079047 | Méndez Álvaro | 97.7 % | 99.8 % | 97.7 % | 98.5 % | 98.8 % | 99.1 % | 98.4 % |
| 28079048 | Castellana | 99.8 % | 99.8 % | 99.8 % | 99.3 % | 99.3 % | 99.3 % | 98.7 % |
| 28079049 | Parque del Retiro | 99.6 % | 99.7 % | 98.9 % | 98.6 % | 97.6 % | 98.5 % | 98.4 % |
| 28079050 | Plaza Castilla | 99.7 % | 99.9 % | 99.3 % | 99.0 % | 99.1 % | 99.0 % | 98.3 % |
| 28079054 | Ensanche de Vallecas | 99.8 % | 99.6 % | 99.5 % | 99.1 % | 99.0 % | 99.0 % | 98.7 % |
| 28079055 | Urb. Embajada | 99.4 % | 99.4 % | 98.0 % | 97.8 % | 98.5 % | 98.5 % | sin datos |
| 28079056 | Pza. Elíptica | 98.4 % | 99.0 % | 97.4 % | 99.3 % | 99.1 % | 99.0 % | 97.6 % |
| 28079057 | Sanchinarro | 98.2 % | 99.5 % | 99.8 % | 99.5 % | 99.1 % | 99.2 % | 98.7 % |
| 28079058 | El Pardo | 99.7 % | 99.7 % | 99.7 % | 99.5 % | 98.6 % | 98.1 % | 97.9 % |
| 28079059 | Juan Carlos I | 95.4 % | 99.8 % | 99.5 % | 99.4 % | 96.8 % | 99.3 % | 98.7 % |
| 28079060 | Tres Olivos | 99.4 % | 99.7 % | 99.7 % | 99.5 % | 96.6 % | 98.9 % | 98.6 % |

## Estaciones y geometría oficial

- Estaciones en la tabla horaria: 24; en la capa oficial: 24.
- En los datos sin coordenadas oficiales: ninguna.
- Oficiales sin datos horarios: ninguna.
- `CODIGO_CORTO` no coincide con los tres últimos dígitos del código: ninguno.
- Código de 8 dígitos `28079xxx` = `PROVINCIA`+`MUNICIPIO`+`ESTACION` (3 dígitos con ceros) de la tabla horaria.
- Discrepancias de coordenadas entre la capa del Geoportal y el CSV de datos.madrid.es (> 5 m): {'28079059': {'distance_m': 789.8, 'geoportal': [-3.6163407459790506, 40.4607255244499], 'datos_madrid_csv': [-3.609031, 40.465144]}}.
- Altas (CSV oficial de datos.madrid.es): la más reciente es del 2010-02-08, antes del periodo (2019-2025). Las fuentes no publican bajas ni traslados dentro del periodo.
- Estaciones oficiales sin NO2 en algún año (año sin datos): {'28079055': [2025]}.

## Limitaciones conocidas

(En inglés, tal como figuran en `quality_report.json`.)

- Values are Europe/Madrid local-time slots; 'Hnn' is read as the hour ending at nn:00 (so timestamp_utc, the hour start, is local time of slot nn-1 converted to UTC). Evidence: slot H03 is invalid on every spring-forward day.
- DST: 951 source slots fall in the nonexistent spring hour and get no row; the repeated fall-back hour has no slot in the source, so it is absent for every station (max coverage is 8759/8760 in a non-leap year). Slot H03 on fall-back days is assumed to be the first occurrence (UTC+2); that assumption is documented by the interpreter but not verifiable from the data. Transition days with slots invalid for every row besides the expected spring H03: 2025-10-26 ['H02', 'H24'].
- Validity: only code V is valid. 150,523 slots are N (not validated or annulled; the file still holds a number, 0 in 55,169 invalid slots and another value in 95,412, and it is discarded) and 58 slots carry code M, which the interpreter does not document; both become value=null / invalid_observation.
- 66 valid readings are negative (NO, NOx, PM2.5 instrument noise); they are kept as published and counted as outliers_flagged.
- CSV vs TXT: 7,201,536 slots exist in both formats of the annual ZIPs (CSV kept). TXT adds 26,640 slots the CSV lacks (listed per year/feature in ingest_details.json). Ozone in the TXT of 2019-2022 is rounded to integers; the CSV (kept) has two decimals.
- Excluded: 147,000 slots of magnitudes not in the interpreter (81-89, meteorological sensors that appear in the 2019 files); meteorology is AT-011.
- Impossible calendar dates: 0 source rows (none expected); they cannot be given a timestamp_utc, so no canonical row is written.
- Absent station-days are not materialised as null rows: coverage is computed against the calendar hours of each year.
- Station coordinates are the current official ones; the sources give no dated history of relocations. Coordinates disagree between the Geoportal layer and the datos.madrid.es CSV for: 28079059 (790 m); the Geoportal value is used.
- Stations without any NO2 reading in some year of the period (listed in the official layer but absent from that year's published file): 28079055 [2025].
- From 2025 some PM sampling points have technique code 'A' (not defined in the interpreter, whose footnote only says that since 2024 microbalance and optical-spectrometry analysers coexist) next to 47; the technique is not part of the canonical key, and no station reports both techniques for the same magnitude.
