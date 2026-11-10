# Calidad de datos: meteorología horaria del DWD (`dwd-meteo-de`)

Generado por `python -m atlas.domains.air.dwd_ingest` (AT-070). No editar a mano: se regenera con cada ingesta.

## Resumen

- Versión de datos: `de-dwd-2019-2025-v1`; rango (UTC): 2018-12-31T00:00:00+00:00 a 2025-12-31T23:00:00+00:00.
- Zips leídos: 1,047; estaciones por producto: tu = 516, ff = 301, p0 = 217.
- Filas leídas: 89,891,558; en el rango de interés: 89,879,191; duplicados históricos/recientes descartados (gana el histórico): 12,367.
- Filas canónicas: 89,879,191; con valor: 89,544,053 (99.6 %). Por motivo: no_observation = 335,138, valid = 89,544,053.
- Estaciones con algún valor (entidades): 593; con punto: 593.
- Fuente: https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/; licencia: CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/) with source attribution; DWD CDC Terms_of_use.pdf (status May 2024) and the dataset descriptions: 'The Creative Commons BY 4.0 - Licence CC BY 4.0 apply'.
- Descarga: 2026-11-02T08:32:20+00:00.

## Variables

| variable | filas | con valor | estaciones | mínimo | máximo |
|---|---|---|---|---|---|
| pressure | 12,801,829 | 12,680,965 | 215 | 676.10 | 1049.00 |
| relative_humidity | 30,329,095 | 30,224,663 | 515 | 3.00 | 100.00 |
| temperature | 30,329,299 | 30,243,554 | 515 | -26.00 | 41.20 |
| wind_speed | 16,418,968 | 16,394,871 | 283 | 0.00 | 38.00 |

Los rangos se informan tal cual vienen; el filtro de plausibilidad se aplica solo al construir la tabla de features (`configs/air/de_no2_h6.json`), nunca a las observaciones canónicas.

## Valores por año

| variable | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|---|---|
| pressure | 4,951 | 1,797,143 | 1,788,145 | 1,802,128 | 1,809,702 | 1,811,847 | 1,841,053 | 1,825,996 |
| relative_humidity | 11,954 | 4,315,227 | 4,324,518 | 4,336,118 | 4,325,836 | 4,298,737 | 4,316,428 | 4,295,845 |
| temperature | 11,959 | 4,316,876 | 4,326,093 | 4,339,438 | 4,328,149 | 4,301,801 | 4,320,889 | 4,298,349 |
| wind_speed | 6,336 | 2,297,147 | 2,318,647 | 2,330,569 | 2,328,086 | 2,337,318 | 2,388,011 | 2,388,757 |

## Convención horaria

- `MESS_DATUM` es UTC salvo donde el propio zip dice otra cosa: cada zip trae `Metadaten_Parameter` con el reloj de cada variable y periodo ('Stundenwerte in UTC' o 'in MEZ'); se leyeron 1,568 combinaciones zip x columna que solapan 2019-2025. Referencias encontradas: MEZ en 17 series, UTC en 1528 series. Referencias aceptadas por la configuración: UTC. Las series declaradas **MEZ** (17: DWD00125:F, DWD00368:F, DWD00766:F, DWD01339:F, DWD02303:F, DWD02315:F, DWD02385:F, DWD02410:F, DWD02773:F, DWD02886:F, DWD02905:F, DWD03254:F, DWD03484:F, DWD03623:F, DWD03639:F, DWD05640:F, DWD05715:F) se **excluyen**: convertidas a UTC (MEZ = UTC+1 fijo) y comparadas con sus vecinas UTC más cercanas, sus valores horarios encajan con desfases de -1 h (14 de 17) y -2 o -3 h (3), frente a 0 h entre vecinas UTC, así que su reloj no se puede verificar. Filas excluidas por ello: 1,024,091; filas sin referencia horaria declarada: 1,956. Una referencia que no es UTC ni MEZ (p. ej. hora legal) detiene la ingesta.
- Los ficheros no dicen si la etiqueta marca el inicio o el final de la ventana. **Se toma como inicio de la hora** (`timestamp_utc = MESS_DATUM`; el valor se usa desde `MESS_DATUM + 1 h`). Si la etiqueta fuera el final de la ventana, esto solo retrasa la información una hora; nunca filtra futuro.

## Limitaciones

- MESS_DATUM is UTC; the files do not say whether the label is the start or the end of the observation window. The label is taken as the START of the hour (value usable from label + 1 h): conservative, it can delay by one hour, never leak.
- Values equal to -999 (missing) are NULL with missing_reason no_observation; the QN quality level of the file is kept in validity_flag (QN_9 temperature/humidity, QN_3 wind, QN_8 pressure). Recent files (quality control not finished) fill only stations without historical files for the end of the period.
- Pressure is station-level pressure (P0, hPa), not reduced to sea level: it depends on station altitude and is not recommended as a feature.
- Stations that moved more than 500 m inside the period: {'DWD00073': 879.5, 'DWD00603': 995.1, 'DWD01473': 4862.5, 'DWD02712': 4860.2, 'DWD03137': 644.1, 'DWD03147': 2018.3, 'DWD03257': 1540.5, 'DWD04261': 769.4, 'DWD04548': 5095.3, 'DWD05149': 791.8, 'DWD05640': 725.8}; the last position is used.
