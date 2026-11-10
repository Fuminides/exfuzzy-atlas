# Calidad de datos: NO2 horario de Alemania (`eea-air-de`)

Generado por `python -m atlas.domains.air.eea_ingest` (AT-070). No editar a mano: se regenera con cada ingesta.

## Resumen

- Versión de datos: `de-eea-2019-2025-v1`; años (reloj de la fuente, UTC+01): 2019-2025.
- Rango (UTC): 2018-12-31T23:00:00+00:00 a 2025-12-31T22:00:00+00:00.
- Filas canónicas: 24,915,384; con valor: 24,285,506 (97.5 %). Por motivo: invalid_observation = 629,878, valid = 24,285,506.
- Estaciones con algún valor válido (entidades): 440; con punto oficial: 437.
- Fuente: https://www.eea.europa.eu/en/datahub/datahubitem-view/778ef9f5-6293-4846-badd-56a29c70880d; licencia: CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/); copyright holder: European Environment Agency (EEA), per the metadata record of the dataset.
- Descarga: 2026-11-02T09:01:28+00:00.

## Origen de cada valor: E1a (verificado) y E2a (al día)

| dataset | ficheros | primer y último `Start` en los ficheros | estaciones | puntos de muestreo | filas en los años pedidos | estaciones con varios puntos de muestreo |
|---|---|---|---|---|---|---|
| e1a | 489 | 2013-01-01T00:00 – 2025-12-31T23:00 | 440 | 440 | 24,915,384 | ninguna |
| e2a | 402 | 2026-01-01T00:00 – 2026-11-02T23:00 | 0 | 0 | 0 | ninguna |

Precedencia: por (estación, hora) se escribe **una** fila canónica, la de E1a si existe y si no la de E2a. Horas presentes en ambos: 0 (con valor distinto: 0). Filas de E2a usadas: 0. `source_id` de cada fila dice de qué dataset sale (`eea-air-de-e1a` o `eea-air-de-e2a`).

## Banderas EEA (`validity_flag = <Validity>:<Verification>`)

Validity: 1 válido; 2 válido, bajo el límite de detección y con el valor medido; 3 válido, sustituido por 0,5 x límite de detección; -1 no válido; -99 no válido por mantenimiento o calibración. Verification: 1 verificado; 2 verificado preliminar; 3 no verificado (vocabularios en `data/raw/eea-air-de/vocabulary`). Los inválidos llevan el valor centinela -999 en el fichero, que **nunca** se escribe.

`eea-air-de-e1a`: filas por año y bandera

| año | -1:1 | -99:1 | 1:1 | 2:1 |
|---|---|---|---|---|
| 2019 | 74,803 | 3,706 | 3,285,525 | 236,326 |
| 2020 | 77,536 | 3,745 | 3,192,289 | 275,166 |
| 2021 | 80,522 | 3,974 | 3,208,730 | 254,574 |
| 2022 | 97,499 | 3,644 | 3,188,737 | 275,440 |
| 2023 | 79,581 | 3,266 | 3,123,982 | 367,251 |
| 2024 | 94,232 | 2,680 | 3,133,071 | 345,105 |
| 2025 | 98,706 | 5,984 | 3,063,570 | 335,740 |

## Valores

- Mínimo -9.871, máximo 1015.146 µg/m³. Negativos (válidos con bandera 2, ruido bajo el límite de detección): 26,205; exactamente 0: 933; por encima de 1000: 1; censurados a la izquierda (bandera 3): 0.
- Unidad: todos los ficheros traen `ug.m-3` (se verifica; otra unidad se convierte si es conocida y si no se marca inválida, nunca se mezcla).

## Cobertura por año (horas válidas por estación)

| año | horas posibles | estaciones con filas | mediana de horas válidas | cobertura media |
|---|---|---|---|---|
| 2019 | 8,760 | 411 | 8,687 | 97.8 % |
| 2020 | 8,784 | 404 | 8,715 | 97.7 % |
| 2021 | 8,760 | 405 | 8,678 | 97.6 % |
| 2022 | 8,760 | 407 | 8,664 | 97.2 % |
| 2023 | 8,760 | 408 | 8,649 | 97.7 % |
| 2024 | 8,784 | 407 | 8,694 | 97.3 % |
| 2025 | 8,760 | 400 | 8,663 | 97.0 % |

## Convención horaria

- `Start` y `End` están en el desfase fijo **UTC+01** todo el año (la columna `Timezone` de todos los puntos de muestreo alemanes en el fichero de metadatos de la EEA es esa entrada del vocabulario; no hay horario de verano en la fuente). El valor cubre `[Start, End)` con `End = Start + 1 h`.
- `timestamp_utc = Start - 1 h` es el **inicio** de la hora. `source_timestamp_local` conserva `AAAA-MM-DD HH:MM UTC+01`; `timezone = Europe/Berlin` es la zona de la estación.
- No hay horas inexistentes ni ambiguas: cada día tiene 24 filas.
- Comprobación empírica (2019, 140 estaciones de tráfico urbanas, laborables): el ciclo diario medio de julio-agosto se alinea con el de enero-febrero desplazándolo 1 h UTC (mínimo error cuadrático circular entre -3 y 3 h). El reloj local pasa de UTC+1 a UTC+2 en verano, así que, si las etiquetas son UTC+01 fijo, el ciclo de verano debe llegar **una hora UTC antes**: se cumple.

## Estaciones

| tipo | zona | estaciones |
|---|---|---|
| ? | ? | 8 |
| background | rural | 31 |
| background | rural-nearcity | 12 |
| background | rural-regional | 27 |
| background | rural-remote | 7 |
| background | suburban | 74 |
| background | urban | 113 |
| industrial | rural | 2 |
| industrial | rural-nearcity | 3 |
| industrial | rural-regional | 1 |
| industrial | suburban | 10 |
| industrial | urban | 10 |
| traffic | rural-nearcity | 1 |
| traffic | suburban | 1 |
| traffic | urban | 140 |

- Ausentes del fichero de metadatos de la EEA: ['DEBB126', 'DEBB127', 'DEBW249', 'DEHB014', 'DEHE175', 'DEHH083', 'DENW074', 'DEST144']; con coordenadas de la capa de estaciones de la EEA (4 decimales): ['DEBW249', 'DEHB014', 'DEHH083', 'DENW074', 'DEST144']; sin ninguna coordenada (geometría nula): ['DEBB126', 'DEBB127', 'DEHE175']. Fuera de la caja de Alemania [5.8, 47.2, 15.1, 55.1]: ninguna.
- Estaciones con varias coordenadas distintas en los metadatos: ninguna.
- Pares a menos de 100 m: 1 (coordenadas idénticas: 0). DEBE063-DEBE127 (30.9 m).
- Estaciones sin ningún valor válido en el periodo (no son entidades): 0.

## Ficheros de entrada (sha256)

899 ficheros; la lista completa está en `ingest_details.json` y en `source_manifest.json` del directorio raw.

## Limitaciones

- 440 stations in E1a (verified) and 0 in E2a (up-to-date) within the selected years; E2a supplies 0 of the 24,915,384 canonical rows; where both exist E1a wins (0 hours in both, 0 with a different value).
- validity_flag is '<EEA Validity>:<EEA Verification>' (Validity 1 valid, 2 valid below the detection limit with the measured value given, 3 replaced by 0.5*DL, -1 not valid, -99 maintenance/calibration; Verification 1 verified, 2 preliminary, 3 not verified).
- The invalid rows carry the sentinel -999 in the EEA files; it is never written as a value (value is NULL).
- 26,205 valid values are negative (instrument noise below the detection limit, Validity 2) and 1 exceed 1000 ug/m3; they are kept as reported and counted in outliers_flagged.
- Coordinates are the EEA sampling-point coordinates (WGS84); stations differ in type and area (traffic, background, industrial; urban, suburban, rural): the type is an entity attribute, not a model input.
- 1 station pairs lie within 100 m of each other (listed in ingest_details.json); both are kept.
