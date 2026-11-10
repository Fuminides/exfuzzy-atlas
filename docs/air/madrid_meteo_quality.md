# Calidad de datos: meteorología horaria de Madrid (`madrid-meteo`)

Generado por `python -m atlas.domains.air.meteo` (AT-011). No editar a mano: se regenera con cada ingesta.

## Resumen

- Versión de datos: `madrid-meteo-2019-2025-v1`; años: 2019-2025.
- Rango (UTC): 2018-12-31T23:00:00+00:00 a 2025-12-31T22:00:00+00:00.
- Filas canónicas: 5,375,388; con valor válido: 5,281,934 (98.3 %).
- Filas por motivo: invalid_observation = 93,454, valid = 5,281,934.
- Duplicados descartados en el mismo formato: 0; solapes CSV/TXT (se conserva el CSV): 4,563,456 registros-hora.
- Fuente: https://datos.madrid.es/dataset/300352-0-meteorologicos-horarios; licencia: CC BY 4.0 (Creative Commons Attribution 4.0 International), https://creativecommons.org/licenses/by/4.0/legalcode.es.
- Descarga: 2026-10-30T17:17:38+00:00.

## Ficheros de entrada (resumen; sha256 por fichero en `quality_report.json`)

148 ficheros: monthly csv: 72, monthly txt: 72, single csv (';', quoted, UTF-8 BOM), several years: 1. El intérprete es `interprete_datos_meteorologicos.pdf`; el esquema es el mismo que el del aire (`PROVINCIA;MUNICIPIO;ESTACION;MAGNITUD;PUNTO_MUESTREO;ANO;MES;DIA;H01;V01;...;H24;V24`).

Registros-hora que solo existen en el TXT (año/magnitud): ninguno.

## Convención horaria y horario de verano

El intérprete meteorológico **no dice** en qué huso están los datos ni cómo trata el cambio de hora (solo que «H01 corresponde al dato de la 1 de la mañana»). Se aplica la misma convención que al aire (hora local de Madrid; `Hnn` es la hora que termina a las `nn:00`) y se comprueba con los datos: en cada cambio de marzo el hueco `H03` debe ser inválido en todas las filas.

| día | cambio | filas | huecos inválidos en todas las filas | máx. inválidos en un hueco |
|---|---|---|---|---|
| 2019-03-31 | marzo (23 h) | 92 | H03 | 92 |
| 2019-10-27 | octubre (25 h) | 85 | ninguno | 0 |
| 2020-03-29 | marzo (23 h) | 89 | H03 | 89 |
| 2020-10-25 | octubre (25 h) | 92 | ninguno | 6 |
| 2021-03-28 | marzo (23 h) | 89 | H03 | 89 |
| 2021-10-31 | octubre (25 h) | 85 | ninguno | 9 |
| 2022-03-27 | marzo (23 h) | 91 | H03 | 91 |
| 2022-10-30 | octubre (25 h) | 43 | ninguno | 0 |
| 2023-03-26 | marzo (23 h) | 92 | H03 | 92 |
| 2023-10-29 | octubre (25 h) | 91 | ninguno | 8 |
| 2024-03-31 | marzo (23 h) | 92 | H03 | 92 |
| 2024-10-27 | octubre (25 h) | 93 | ninguno | 1 |
| 2025-03-30 | marzo (23 h) | 91 | H03 | 91 |
| 2025-10-26 | octubre (25 h) | 92 | H24 | 92 |

Días de cambio con un comportamiento distinto del esperado: 2025-10-26 (H24).

## Códigos de validez, magnitudes y unidades

Solo `V` genera `value`; cualquier otro código → `null` con `invalid_observation`; hueco vacío → `no_observation`. El número que acompaña a un código no válido se descarta (0 en 62,237 huecos, otro valor en 31,217).

| código | huecos |
|---|---|
| N | 93,454 |
| V | 5,281,934 |

| magnitud (feature_name) | unidad | estaciones con datos | filas válidas | valores válidos fuera de rango (marcados) |
|---|---|---|---|---|
| precipitation | l/m2 | 11 | 577,406 | 0 |
| pressure | mbar | 9 | 452,547 | 1074 |
| relative_humidity | % | 24 | 1,291,963 | 37 |
| solar_radiation | W/m2 | 9 | 458,532 | 35 |
| temperature | degC | 26 | 1,358,917 | 36 |
| wind_direction | deg | 10 | 571,263 | 0 |
| wind_speed | m/s | 10 | 571,306 | 14 |

Magnitudes excluidas (no incluidas en el intérprete): 80: 20,160 huecos.

## Cobertura por estación y magnitud

Fracción de las horas del periodo con valor válido (media de los años pedidos; un año sin datos cuenta como 0; `-` = la estación no mide la magnitud en los datos). Detalle por año en `ingest_details.json`.

| estación | nombre | precipitation | pressure | relative_humidity | solar_radiation | temperature | wind_direction | wind_speed |
|---|---|---|---|---|---|---|---|---|
| 28079004 | Plaza España | - | - | - | - | 89 % | - | - |
| 28079008 | Escuelas Aguirre | - | - | 98 % | - | 98 % | - | - |
| 28079016 | Arturo Soria | - | - | 96 % | - | 52 % | - | - |
| 28079018 | Farolillo | - | - | - | - | 99 % | - | - |
| 28079024 | Casa de Campo | 98 % | 94 % | 98 % | 98 % | 98 % | 98 % | 98 % |
| 28079035 | Plaza del Carmen | - | - | 97 % | - | 97 % | - | - |
| 28079036 | Moratalaz | - | - | 99 % | - | 99 % | - | - |
| 28079038 | Cuatro Caminos | - | - | 99 % | - | 99 % | - | - |
| 28079039 | Barrio del Pilar | 99 % | - | 99 % | - | 56 % | - | - |
| 28079054 | Ensanche de Vallecas | 99 % | - | 100 % | 100 % | 100 % | 100 % | 100 % |
| 28079056 | Plaza Elíptica | 99 % | 99 % | 99 % | - | 99 % | 97 % | 98 % |
| 28079058 | El Pardo | - | - | 99 % | - | 99 % | - | - |
| 28079059 | Juan Carlos I | 98 % | 99 % | 99 % | 98 % | 99 % | 96 % | 96 % |
| 28079102 | J.M.D. Moratalaz | 93 % | 93 % | 93 % | 93 % | 93 % | 93 % | 93 % |
| 28079103 | J.M.D. Villaverde | 91 % | 92 % | 92 % | 92 % | 92 % | 92 % | 92 % |
| 28079104 | E.D.A.R. La China | 3 % | 3 % | 3 % | 3 % | 3 % | 91 % | 91 % |
| 28079106 | Centro Mpal. De Acústica | 85 % | 85 % | 85 % | 85 % | 85 % | 85 % | 85 % |
| 28079107 | J.M.D. Hortaleza | 90 % | 87 % | 87 % | 90 % | 88 % | 90 % | 90 % |
| 28079108 | Peñagrande | 88 % | 87 % | 85 % | 88 % | 88 % | 88 % | 88 % |
| 28079109 | J.M.D.Chamberí | - | - | 80 % | - | 83 % | - | - |
| 28079110 | J.M.D.Centro | - | - | 83 % | - | 83 % | - | - |
| 28079111 | J.M.D.Chamartin | - | - | 68 % | - | 68 % | - | - |
| 28079112 | J.M.D.Vallecas 1 | - | - | 87 % | - | 87 % | - | - |
| 28079113 | J.M.D.Vallecas 2 | - | - | 87 % | - | 90 % | - | - |
| 28079114 | Matadero 01 | - | - | 83 % | - | 83 % | - | - |
| 28079115 | Matadero 02 | - | - | 89 % | - | 89 % | - | - |

## Estaciones y geometría oficial

- Ubicaciones oficiales (CSV `Meteorológicos. Estaciones de control`): 26.
- En los datos sin coordenadas oficiales: ninguna.
- Oficiales sin datos horarios: ninguna.
- Sensores declarados distintos de las magnitudes con datos: {'28079104': {'official_only': [], 'data_only': ['precipitation', 'pressure', 'relative_humidity', 'solar_radiation', 'temperature']}}.

## Limitaciones conocidas

(En inglés, tal como figuran en `quality_report.json`.)

- Values are Europe/Madrid local-time slots; 'Hnn' is read as the hour ending at nn:00, as in the air-quality files. The meteorological interpreter does not state the hour convention or the daylight-saving handling; it was inferred from the data. 636 source slots fall in the nonexistent spring hour and get no row; the repeated fall-back hour has no slot, so it is absent for every station.
- DST transition days whose invalid slots differ from the expected spring H03: {'2025-10-26': ['H24']}.
- Validity: only code V is valid; other codes become value=null / invalid_observation, an empty slot no_observation. The number stored beside a non-V code is discarded.
- Hourly meteorology is a point measurement at the station: it is not an area value and must not be interpolated into surfaces; AT-011 associates each air station with the nearest meteorological stations.
- 26 official sensor locations; stations in the hourly data without official coordinates: none; official stations without any valid hourly value: none; stations whose official sensor flags differ from the features actually observed: {'28079104': {'official_only': [], 'data_only': ['precipitation', 'pressure', 'relative_humidity', 'solar_radiation', 'temperature']}}.
- Station coordinates are the current official ones (CSV updated 2023-05-03); no dated history of relocations is published.
- The 2025-and-later CSV is extended monthly by the portal; its content depends on the download date.
- Valid-coded readings outside plausible physical ranges (flagged, not altered): {'pressure': 1074, 'relative_humidity': 37, 'solar_radiation': 35, 'temperature': 36, 'wind_speed': 14}.
- CSV vs TXT: 4563456 slots exist in both formats of the monthly files (CSV kept); 0 exist only in the TXT.
