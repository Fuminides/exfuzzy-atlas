# Tarjeta de features: demanda de taxi amarillo de NYC a 1 hora (`nyc_pickups_h1`, AT-031)

Tabla de entrenamiento y evaluación por **(taxi zone, hora de emisión)** para predecir las recogidas de la hora siguiente. Se construye con DuckDB a partir de la serie
de AT-030 (`data/processed/mobility/observations/`) con `python -m atlas.domains.mobility.features` (código en `src/atlas/domains/mobility/features.py`). Las cifras de
abajo corresponden a la versión de datos `nyc-tlc-yellow-2024-04_2025-03-v1` y se regeneran en [`nyc_pickups_h1_eda.md`](nyc_pickups_h1_eda.md) (generado, no se edita).
La definición de la serie, los filtros de viajes y el tratamiento del horario de verano están en [`nyc_tlc_yellow_dataset_card.md`](nyc_tlc_yellow_dataset_card.md) y [`README.md`](README.md).

> AT-031b añade sobre esta tabla el target relativo (`target_level`) y cinco features relativas en `nyc_pickups_h1_level`: ver [`nyc_pickups_h1_level.md`](nyc_pickups_h1_level.md). `feature_spec.json` lleva ahora 12 features; las siete de esta tarjeta no cambian.

## Convención temporal

- `pickups[h]` = recogidas con instante de recogida en la hora UTC `[h, h+1)`; la serie canónica está indexada por el **inicio** de la hora.
- La predicción se **emite** en `issued_at_utc = T`, siempre en punto. Solo puede usar horas que **ya habían terminado** en `T`, es decir, inicios de hora `h ≤ T − 1 h`.
- El **target** es `pickups[T]`, las recogidas en `[T, T+1)`. `valid_at_utc = T + 1 h` (el final de la ventana del target). Es demanda a una hora vista: horizonte
  `horizon_hours = 1` en el manifiesto de A4. No se usa hora de bajada, tarifa, distancia ni propina en ninguna columna (el filtro de viajes corruptos de AT-030 sí
  lee la bajada para descartar registros incoherentes, pero ningún campo de bajada llega a la serie).
- Todo el aritmético temporal es en **UTC con intervalos de horas absolutas** (no «mismo reloj de ayer»): `T − 24 h` es 24 horas transcurridas, también el día del cambio
  de hora, cuando el día local tiene 23 o 25 horas. Tests en `tests/mobility/test_mobility_features.py`.
- Hay una fila por (zona seleccionada, hora UTC de **todo** el periodo cubierto), de modo que `filas = zonas × horas de emisión`. El primer `T` es la primera hora cubierta y
  el último la última, de modo que el target siempre cae dentro de la cobertura. Las filas del arranque (menos de 168 h de historia) existen pero están incompletas.

## Columnas

Parquet particionado `year=/month=` (mes UTC de la emisión) en `data/processed/mobility/features/nyc_pickups_h1/`; dentro de cada partición, ordenado por zona y hora. Al leer el directorio
(DuckDB, pandas, pyarrow) `year` y `month` aparecen como columnas extra: se ignoran. Solo hay ficheros Parquet en el directorio; los sidecars JSON están un nivel más arriba.

| columna | tipo | significado |
|---|---|---|
| `entity_id` | VARCHAR | `PULocationID` como texto (`"4"`, `"161"`…), el mismo `entity_id` de `taxi_zones*.geojson` |
| `issued_at_utc` | TIMESTAMPTZ (UTC) | `T` |
| `valid_at_utc` | TIMESTAMPTZ (UTC) | `T + 1 h` |
| `target` | DOUBLE | recogidas en `[T, T+1)`; null si esa hora es la ambigua del cambio de hora de otoño |

`feature_spec.json` (ruta `configs/mobility/feature_spec.json`, formato de `docs/api.md`) lleva `unit`, `source_id` y `lag_hours` de cada feature. **`lag_hours` es la edad en `T` del inicio de la hora de
origen más reciente que usa la feature**: `observed_at_utc = issued_at_utc − lag_hours`. Para una ventana agregada se toma el inicio de su hora más nueva. Esa hora termina en
`T − lag_hours + 1 h ≤ T`. Un test perturba cada hora de la serie y comprueba que la primera emisión afectada es exactamente `h + lag_hours`, o sea que el valor declarado es el real.

| feature | tipo | unidad | `lag_hours` | definición |
|---|---|---|---|---|
| `pickups_lag1` | DOUBLE | trips | 1 | recogidas en `[T−1 h, T)`, la hora que acaba de terminar |
| `pickups_lag2` | DOUBLE | trips | 2 | recogidas en `[T−2 h, T−1 h)` |
| `pickups_lag24` | DOUBLE | trips | 24 | recogidas en `[T−24 h, T−23 h)`: la hora que corresponde al target, 24 h transcurridas antes («misma hora ayer») |
| `pickups_lag168` | DOUBLE | trips | 168 | recogidas en `[T−168 h, T−167 h)`: «misma hora la semana pasada», 168 h antes |
| `pickups_mean24h` | DOUBLE | trips/hour | 1 | media de los 24 conteos horarios de `[T−24 h, T)`; **solo si los 24 se conocen** |
| `local_hour` | INTEGER | hour | 0 | hora de reloj de America/New_York de `T`, 0-23 (es también la de la ventana del target) |
| `local_dow` | INTEGER | weekday_index | 0 | día de la semana local de `T`, lunes = 0 … domingo = 6 |

### Codificación de calendario

- Son enteros con **24** y **7** valores distintos: no hay flags 0/1. ex_fuzzy auto-detecta como categórica cualquier columna de enteros con ≤ 5 valores distintos (`docs/ml/exfuzzy_api_notes.md` §1); el wrapper
  de A4 lo desactiva (`detect_categorical=False`), pero así tampoco habría riesgo si alguien usase `construct_partitions` directamente. No hay columna de fin de semana ni de festivo.
- **Costuras**: `local_hour` salta de 23 a 0 y `local_dow` de 6 a 0, y la demanda de madrugada del fin de semana (00-03 h) es alta mientras que la de la madrugada laborable es la más baja; con la hora como número plano
  sus particiones difusas parten el pico de las noches de viernes y sábado. La tabla guarda la forma cruda e interpretable. A4 puede derivar sin tocar la tabla algo como `(local_hour − 5) mod 24` (día de servicio que arranca en el
  mínimo de la demanda) o `local_dow·24 + local_hour` (hora de la semana, 168 valores), o sin/cos si prefiere perder interpretabilidad.
- **Hora local en el cambio de hora**: el día de primavera salta de 1 a 3 (no existe la 2); el día de otoño el 1 se repite en dos horas UTC consecutivas. `local_hour` y `local_dow` se calculan siempre desde el instante UTC, por lo que existen
  también en la hora ambigua (donde el target es null).
- **Festivos**: no se codifican (hay que mantener una lista y no hay otra fuente de calendario). Con un solo año, cada festivo cae en un solo periodo del split.

## Semántica de nulos

- Un recuento 0 genuino sigue siendo 0 (`value = 0`, `n_records = 0` en la serie), también en las features.
- **Null** (nunca 0) en cualquier feature o target que necesite una hora que (a) está fuera del periodo cubierto, (b) es la hora local ambigua del cambio de hora de otoño (2024-11-03 05Z y 06Z, `null` para todas las zonas en la serie)
  o (c) no tiene fila. La media `pickups_mean24h` exige **las 24** horas; con una sola nula es null.
- Consecuencia de la hora ambigua (a 2024-11-03 05Z y 06Z): `target` null en esas dos emisiones; `pickups_lag1` null en 06Z y 07Z; `pickups_lag2` en 07Z y 08Z; `pickups_lag24` y `pickups_lag168` en las mismas horas 24 h y 168 h después; `pickups_mean24h`
  de 06Z a 06Z del día siguiente (25 emisiones). Todo comprobado en un test con una serie escrita a mano.
- Filas completas (el target y las 7 features conocidos): **942.040 de 963.600 (97,76 %)**. Incompletas: 21.560 = 18.480 del arranque (las 168 primeras horas de cada una de las 110 zonas, el lag semanal cae antes de la cobertura)
  + 3.080 por la hora ambigua. Por periodo del split recomendado: train 704.550 completas de 726.110, validación 63.360 de 63.360, test 137.170 de 137.170.

## Selección de zonas

La serie tiene 263 zonas con polígono, pero el 51 % de las zona-horas es 0 y la demanda se concentra en pocas zonas (ver el EDA). Entran en la tarea las zonas cuya **media de recogidas por hora conocida en el periodo de entrenamiento
es ≥ 1** (`configs/mobility/nyc_pickups_h1.json`, `zone_filter`). Solo se lee el periodo de train (`split.train`, `[2024-04-01T04:00Z, 2025-01-01T05:00Z)`): nada posterior puede cambiar la selección (test con mutaciones). Por debajo de 1 recogida por hora un
conteo de Poisson tiene ≈ 37 % de ceros solo por azar y el modelo apenas puede aprender estructura; el umbral es un parámetro y el EDA tabula la sensibilidad (0,25 a 5).

- **110 zonas seleccionadas** (el 99,06 % de las recogidas de train de las 263; 98,71 % en validación y 97,91 % en test), **153 excluidas**. Entre las excluidas hay dos zonas sin ninguna recogida en todo el año (103 y 104, islas), otras con un puñado (99, 105, 110), zonas costeras y parques de Queens y Staten Island, y zonas residenciales exteriores de Bronx, Brooklyn y Queens; en Manhattan solo 9. Lista completa por barrio con su media de train en el apéndice del EDA y, con motivos, en `data/processed/mobility/features/nyc_pickups_h1_zone_selection.json`
  (`included`, `reason`, `train_pickups`, `train_known_hours`, `train_mean_pickups_per_hour`, `name`, `borough`).
- Las excluidas **no se borran**: siguen en las `EntityCollection` (`taxi_zones.geojson`, `taxi_zones_simplified.geojson`) y en la serie de observaciones. Para el mapa son «sin modelo»: tienen geometría y recogidas observadas pero ninguna fila en la tabla de
  features, ningún firing y ninguna predicción. La API (`entities` solo publica las entidades presentes en los datos) debería marcar el resto con `missing_reason = prediction_unavailable`; es decisión de A0/A5.
- Los IDs 264 y 265 (`Unknown`, `Outside of NYC`) no tienen polígono y no están en la serie.

## Qué no es y límites

- **Disponibilidad real**: la tabla simula que el recuento final de `[T−1 h, T)` se conoce en `T`. Los ficheros de la TLC se publican por meses y con retraso, y una recogida llega al fichero cuando se registra el viaje: en un sistema vivo, los viajes de la última
  hora que aún no han terminado (mediana de duración ≈ 12 min, pero con cola) llegarían tarde y `pickups_lag1` estaría infracontado. Es una **suposición de reproducción histórica**, igual que en Madrid; no se afirma capacidad en tiempo real ni se ha validado un feed vivo.
  Tampoco el filtro de viajes (duración > 6 h, etc.) es causal: usa la bajada del registro para limpiar datos históricos.
- Es **demanda observada de viajes completados de taxi amarillo** en una zona, no demanda total, ni insatisfecha, ni movilidad, ni emisiones. No hay meteorología ni eventos.
- Sin información del nivel de la zona más allá del historial: un modelo conjunto que no normalice por zona aprende sobre todo «zona grande o pequeña» (ver el EDA). `entity_id` no es una feature.
- Un año de datos: sin comparación interanual, y el régimen del peaje de congestión (`cbd_congestion_fee`, desde 2025-01-05) cae a mitad del periodo; el nivel de las zonas de poco volumen cambia en febrero-marzo de 2025 (EDA §6).
- Las features de conteo son valores brutos (sin log, sin normalizar): cualquier transformación o escalado se ajusta con train en el pipeline de A4.

## Coste de entrenamiento (para A4)

704.550 filas completas de train serían, según las cifras medidas en `docs/ml/exfuzzy_api_notes.md` §7 (≈ 2,3 KB por fila de entrenamiento + 0,24 GB), ≈ 1,9 GB solo en el ajuste: por encima de 1,5 GB. Hay que submuestrear **el train** (p. ej. 200-400 k filas, estratificando por zona y mes) y evaluar
validación y test completos. Estimación extrapolada, no medida con esta tabla.

## Reproducir

```bash
export ATLAS_DATA_DIR=/path/to/exfuzzy-atlas/data      # si se comparte el data/ de otro checkout
PYTHONPATH=src python -m atlas.domains.mobility.ingest --months 2024-04..2025-03     # serie (descarga + zona-hora)
PYTHONPATH=src python -m atlas.domains.mobility.features --write-spec --eda          # tabla + feature_spec.json + EDA
PYTHONPATH=src python -m pytest tests/mobility -q
```

La tabla se construye en 1-2 s con un pico de RSS de ≈ 1,0 GB (2,3 millones de filas de la serie en memoria de DuckDB, `memory_limit=1500MB`, 4 hilos) y ocupa ≈ 6 MB en disco.
Sidecars en `data/processed/mobility/features/`: `nyc_pickups_h1_feature_report.json` (recuentos, nulos, periodos), `nyc_pickups_h1_zone_selection.json` y `nyc_pickups_h1_eda.json` (todas las cifras del EDA).

Para publicar un modelo entrenado sobre esta tabla (`docs/api.md`): `--features 'data/processed/mobility/features/nyc_pickups_h1/**/*.parquet'`, `--entities data/processed/mobility/taxi_zones_simplified.geojson`, `--feature-spec configs/mobility/feature_spec.json`.
