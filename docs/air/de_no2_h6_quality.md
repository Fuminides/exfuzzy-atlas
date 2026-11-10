# Calidad de la tabla `de_no2_h6` (NO₂ a +6 h, Alemania)

Generado por `python -m atlas.domains.air.de_features` (AT-070). No editar a mano. Misma tabla, columnas y semántica temporal que `madrid_no2_h6` ([`madrid_no2_h6.md`](madrid_no2_h6.md)); fuentes en [`de_eea_air_quality.md`](de_eea_air_quality.md) y [`de_dwd_meteo_quality.md`](de_dwd_meteo_quality.md).

Versión: `de-no2-h6-v1`; filas: 26,998,840 = 440 estaciones x 61,361 horas de emisión (UTC); completas: 21,228,357 (78.6 %). `completa` = las 9 features recomendadas y el target no nulos (`no2_last`, `no2_lag1h`, `no2_lag3h`, `no2_lag24h`, `wind_speed`, `temperature`, `relative_humidity`, `valid_hour_local`, `valid_weekday`).

## Filas por año de emisión (UTC)

| año | filas | completas | % completas |
|---|---|---|---|
| 2019 | 3,854,400 | 3,070,956 | 79.7 % |
| 2020 | 3,864,960 | 3,045,078 | 78.8 % |
| 2021 | 3,854,400 | 3,037,978 | 78.8 % |
| 2022 | 3,854,400 | 3,023,553 | 78.4 % |
| 2023 | 3,854,400 | 3,044,618 | 79.0 % |
| 2024 | 3,864,960 | 3,048,345 | 78.9 % |
| 2025 | 3,851,320 | 2,957,829 | 76.8 % |

## Fracción de filas con cada columna no nula, por año

| año | no2_last | no2_lag1h | no2_lag3h | no2_lag24h | wind_speed | temperature | relative_humidity | pressure | target |
|---|---|---|---|---|---|---|---|---|---|
| 2019 | 91.4 % | 91.4 % | 91.3 % | 91.1 % | 91.5 % | 99.0 % | 99.0 % | 84.4 % | 91.4 % |
| 2020 | 89.7 % | 89.7 % | 89.7 % | 89.7 % | 91.4 % | 98.9 % | 98.9 % | 84.1 % | 89.7 % |
| 2021 | 89.8 % | 89.8 % | 89.8 % | 89.8 % | 91.6 % | 98.9 % | 98.9 % | 84.0 % | 89.8 % |
| 2022 | 89.9 % | 89.9 % | 89.9 % | 89.9 % | 92.0 % | 99.1 % | 99.1 % | 84.0 % | 89.9 % |
| 2023 | 90.6 % | 90.6 % | 90.6 % | 90.6 % | 91.7 % | 99.2 % | 99.2 % | 84.1 % | 90.6 % |
| 2024 | 90.0 % | 90.0 % | 90.0 % | 90.0 % | 92.1 % | 99.2 % | 99.2 % | 83.9 % | 90.0 % |
| 2025 | 88.2 % | 88.2 % | 88.2 % | 88.2 % | 91.9 % | 99.0 % | 99.0 % | 83.6 % | 88.2 % |

## Splits (protocolo de Madrid)

Ventanas de hora de emisión semiabiertas, embargo 24 h antes de cada periodo posterior. Same boundaries and embargo as the Madrid protocol (configs/ml/madrid_no2_h6_*_experiment.json): periods are half-open issue-hour windows; the 24 h embargo precedes each later period. Train 2019-2023, validation 2024, test 2025.

| split | emisión (UTC) | filas | con target | completas | estaciones con filas completas |
|---|---|---|---|---|---|
| train | 2019-01-01T00:00:00Z – 2023-12-31T00:00:00Z | 19,272,000 | 17,398,524 | 15,213,722 | 400 |
| validation | 2024-01-01T00:00:00Z – 2024-12-31T00:00:00Z | 3,854,400 | 3,468,653 | 3,039,891 | 380 |
| test | 2025-01-01T00:00:00Z – 2026-01-01T00:00:00Z | 3,851,320 | 3,396,608 | 2,957,829 | 371 |

## NO₂ del target por split (µg/m³, filas completas)

| split | n | media | desv. | mín | p05 | p25 | p50 | p75 | p95 | p99 | máx |
|---|---|---|---|---|---|---|---|---|---|---|---|
| train | 15,213,722 | 17.9 | 15.3 | -9.9 | 2.1 | 6.6 | 13.4 | 25.1 | 48.4 | 68.5 | 1015.1 |
| validation | 3,039,891 | 14.6 | 12.3 | -4.8 | 1.9 | 5.4 | 10.9 | 20.3 | 39.5 | 55.5 | 273.2 |
| test | 2,957,829 | 15.6 | 13.1 | -5.7 | 2.0 | 5.7 | 11.7 | 21.8 | 41.5 | 58.8 | 207.2 |

Media del target por tipo de estación y zona (filas completas):

| split | tipo | zona | estaciones | filas completas | media |
|---|---|---|---|---|---|
| train | background | rural | 25 | 986,480 | 5.7 |
| train | background | rural-nearcity | 12 | 460,875 | 11.3 |
| train | background | rural-regional | 26 | 1,073,808 | 6.0 |
| train | background | rural-remote | 6 | 195,390 | 4.2 |
| train | background | suburban | 69 | 2,611,461 | 13.7 |
| train | background | urban | 103 | 3,987,673 | 16.7 |
| train | industrial | rural | 2 | 68,002 | 12.3 |
| train | industrial | rural-nearcity | 2 | 43,496 | 14.9 |
| train | industrial | rural-regional | 1 | 41,897 | 12.1 |
| train | industrial | suburban | 9 | 353,807 | 14.6 |
| train | industrial | urban | 10 | 352,285 | 19.4 |
| train | traffic | rural-nearcity | 1 | 42,889 | 22.1 |
| train | traffic | suburban | 1 | 39,601 | 25.0 |
| train | traffic | urban | 133 | 4,956,058 | 27.5 |
| validation | background | rural | 24 | 191,766 | 4.4 |
| validation | background | rural-nearcity | 12 | 96,415 | 8.8 |
| validation | background | rural-regional | 26 | 213,187 | 4.8 |
| validation | background | rural-remote | 4 | 27,248 | 4.1 |
| validation | background | suburban | 67 | 528,390 | 11.0 |
| validation | background | urban | 98 | 799,000 | 13.4 |
| validation | industrial | rural | 2 | 13,810 | 9.5 |
| validation | industrial | rural-nearcity | 1 | 7,045 | 11.8 |
| validation | industrial | rural-regional | 1 | 8,613 | 9.5 |
| validation | industrial | suburban | 9 | 71,019 | 12.1 |
| validation | industrial | urban | 9 | 61,049 | 15.9 |
| validation | traffic | rural-nearcity | 1 | 8,647 | 17.9 |
| validation | traffic | suburban | 1 | 8,033 | 20.4 |
| validation | traffic | urban | 121 | 979,735 | 22.4 |
| validation | unknown | unknown | 4 | 25,934 | 24.7 |
| test | background | rural | 21 | 170,430 | 5.1 |
| test | background | rural-nearcity | 12 | 96,425 | 10.0 |
| test | background | rural-regional | 25 | 206,515 | 5.4 |
| test | background | rural-remote | 4 | 33,572 | 4.0 |
| test | background | suburban | 67 | 523,760 | 12.2 |
| test | background | urban | 97 | 776,467 | 14.6 |
| test | industrial | rural | 2 | 14,237 | 10.4 |
| test | industrial | rural-nearcity | 1 | 6,972 | 12.5 |
| test | industrial | rural-regional | 1 | 6,905 | 10.9 |
| test | industrial | suburban | 9 | 71,026 | 13.0 |
| test | industrial | urban | 8 | 60,379 | 17.1 |
| test | traffic | rural-nearcity | 1 | 8,250 | 17.6 |
| test | traffic | suburban | 1 | 8,063 | 20.3 |
| test | traffic | urban | 118 | 942,774 | 23.3 |
| test | unknown | unknown | 4 | 32,054 | 21.6 |

## Bandas del Índice Europeo de Calidad del Aire (EAQI) para NO₂

Umbrales (µg/m³, concentración horaria): Good 0-10, Fair 11-25, Moderate 26-60, Poor 61-100, Very poor 101-150, Extremely poor >150. Fuente: <https://airindex.eea.europa.eu/AQI/index.html> (consultada 2026-11-02), tabla de bandas de concentración; copia de la página en `data/raw/eea-air-de/docs/eaqi_airindex.html`.
Convención de frontera (de Atlas, no de la EEA): Atlas convention, not stated by the EEA: the official table lists whole micrograms per cubic metre with both ends inclusive (0-10, 11-25, ...), so a value is rounded to the nearest whole number (half up) and then falls in the band whose closed range contains it; a value below 0 (instrument noise below the detection limit) is not a concentration and is placed in the lowest band; >150 is open-ended (the source gives no upper bound).

**¿Coinciden con las bandas del ICA español de Madrid?** No. Not equal to the Spanish ICA NO2 bands used for Madrid (configs/ml/ica_no2_scheme.json: 0-40, 41-90, 91-120, 121-230, 231-340, 341-1000). All five EAQI thresholds are lower (10/25/60/100/150 against 40/90/120/230/340) and the top band is open. The same concentration can be 'Good' in the ICA and 'Fair' or 'Moderate' in the EAQI, so results by class are NOT comparable between the Madrid and the Germany tasks.

Porcentaje de horas de cada banda por split (filas completas; entre paréntesis, todas las filas con target):

| split | n completas | Good | Fair | Moderate | Poor | Very poor | Extremely poor |
|---|---|---|---|---|---|---|---|
| train | 15,213,722 | 40.8 % (41.8) | 34.8 % (34.5) | 22.4 % (21.9) | 1.8 % (1.8) | 0.1 % (0.1) | 0.0 % (0.0) |
| validation | 3,039,891 | 48.6 % (49.6) | 34.7 % (34.1) | 16.2 % (15.7) | 0.6 % (0.5) | 0.0 % (0.0) | 0.0 % (0.0) |
| test | 2,957,829 | 45.8 % (46.4) | 35.2 % (34.9) | 18.2 % (17.8) | 0.8 % (0.8) | 0.0 % (0.0) | 0.0 % (0.0) |

Para comparar, las mismas filas con las bandas del ICA de Madrid (`configs/ml/ica_no2_scheme.json`):

| split | n completas | Buena | Razonablemente buena | Regular | Desfavorable | Muy desfavorable | Extremadamente desfavorable |
|---|---|---|---|---|---|---|---|
| train | 15,213,722 | 91.00 % | 8.83 % | 0.15 % | 0.02 % | 0.00 % | 0.00 % |
| validation | 3,039,891 | 95.43 % | 4.55 % | 0.02 % | 0.00 % | 0.00 % | 0.00 % |
| test | 2,957,829 | 94.51 % | 5.42 % | 0.06 % | 0.00 % | 0.00 % | 0.00 % |

## Emparejamiento meteorológico (DWD)

Regla: estaciones DWD que miden la variable a ≤ 25 km (círculo máximo), hasta 3 por variable, rango 1 principal y el resto como suplentes hora a hora; sin interpolación. Más allá del tope el input es NULL (`missing_reason = no_observation`; ver `association.json`). El tope es la decisión de este informe (la red DWD está separada ~25 km), no un criterio de Madrid (5 km, red densa).

Distancia (km) a la estación principal, por variable:

| variable | con candidata | sin candidata | mín | p25 | mediana | p75 | p90 | máx |
|---|---|---|---|---|---|---|---|---|
| wind_speed | 407 | 33 | 0.0 | 5.7 | 9.9 | 15.7 | 21.4 | 24.8 |
| temperature | 437 | 3 | 0.0 | 4.5 | 7.6 | 11.1 | 16.4 | 23.9 |
| relative_humidity | 437 | 3 | 0.0 | 4.5 | 7.6 | 11.1 | 16.4 | 23.9 |
| pressure | 372 | 68 | 0.0 | 5.7 | 10.3 | 18.3 | 22.2 | 24.9 |

Estaciones (de 440) con estación DWD con datos a ≤ X km, por variable (sensibilidad al tope):

| variable | ≤ 5 km | ≤ 10 km | ≤ 15 km | ≤ 25 km | ≤ 50 km |
|---|---|---|---|---|---|
| wind_speed | 88 | 205 | 295 | 407 | 437 |
| temperature | 127 | 297 | 380 | 437 | 437 |
| relative_humidity | 127 | 297 | 380 | 437 | 437 |
| pressure | 82 | 179 | 246 | 372 | 437 |

Filas con la feature meteorológica nula, por motivo (todas `no_observation`):

| feature | filas nulas | sin estación dentro del tope | estación pero sin valor válido esa hora |
|---|---|---|---|
| wind_speed | 2,222,968 | 2,024,913 | 198,055 |
| temperature | 260,446 | 184,083 | 76,363 |
| relative_humidity | 262,125 | 184,083 | 78,042 |
| pressure | 4,316,463 | 4,172,548 | 143,915 |

## Convención temporal

Igual que Madrid: una fila por (`entity_id`, `issued_at_utc` = t) en una rejilla UTC horaria regular; entradas con clave ≤ t − 1 h (`timestamp_utc` = inicio de la hora, disponible a +1 h); target = NO₂ de la hora con clave t + 6 h; uniones por igualdad exacta; nulo, nunca 0; calendario local en Europe/Berlin (`valid_hour_local`, `valid_weekday` del instante objetivo). La fuente EEA está en UTC+01 fijo y la del DWD en UTC, así que no hay horas ambiguas ni inexistentes que excluir (`excluded_local_dates` vacío). Diferencia con Madrid: la meteorología del DWD tiene etiqueta tomada como inicio de la hora (+1 h de retraso conservador, ver `de_dwd_meteo_quality.md`).
