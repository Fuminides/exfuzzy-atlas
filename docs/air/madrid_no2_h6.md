# Tarea `madrid_no2_h6`: tabla de features y target para NO₂ a +6 h (AT-011)

Para A4 (AT-041). Cobertura y asociación meteorológica, con cifras: [`madrid_no2_h6_coverage.md`](madrid_no2_h6_coverage.md)
(generado). Fuentes y convenciones de la meteorología: [`madrid_meteo.md`](madrid_meteo.md). No se ha entrenado ningún modelo.

## Cómo se genera y se lee

```bash
export ATLAS_DATA_DIR=/path/to/exfuzzy-atlas/data   # opcional; por defecto <repo>/data
PYTHONPATH=src python -m atlas.domains.air.meteo --years 2019-2025   # descarga + observaciones meteo
PYTHONPATH=src python -m atlas.domains.air.features                  # tabla + tarjeta + cobertura
```

Salida en `data/processed/air/features/madrid_no2_h6/`: `table/year=YYYY/month=M/*.parquet` (hive por año/mes UTC de
`issued_at_utc`), `association.parquet|json`, `feature_card.json|md`, `coverage.json`. Lectura:
`pd.read_parquet(".../table")` (añade `year` y `month` como categorías; no son features).
1.472.664 filas = 24 estaciones × 61.361 horas de emisión, ≈ 14 MB en disco, ≈ 280 MB en pandas.

## Convención temporal (lo importante)

- Una fila por (`entity_id`, `issued_at_utc` = **t**) en una rejilla UTC horaria regular, de 2019-01-01T00:00Z a
  2025-12-31T16:00Z (la última t cuyo target, t+6 h, existe). Los 24 `entity_id` son las estaciones con NO₂.
- `timestamp_utc` de una observación es el **inicio** de su hora. Una hora con clave *s* cubre [s, s+1 h) y se considera
  disponible a *s*+1 h (la latencia real de publicación del portal **no se ha medido**; no se afirma tiempo real). Por tanto,
  en t solo se puede leer la hora más reciente completa, clave **t − 1 h**: todas las features de entrada leen claves ≤ t − 1 h.
  Esto difiere deliberadamente de «NO₂ en t»: `no2_last` es la hora [t−1 h, t). Permite al test de fuga exigir
  `clave + 1 h ≤ issued_at_utc` y no solo `clave ≤ issued_at_utc`.
- **target** = NO₂ de la hora con clave **t + 6 h** (el inicio de la hora objetivo); `valid_at_utc = t + 6 h`. Entre el final
  de la última hora observada y el inicio de la hora objetivo hay 6 h.
- Aritmética **en UTC**: `valid_at_utc − issued_at_utc` es exactamente 6 h elapsed incluso en los cambios de hora. El
  calendario local (`valid_hour_local`, `valid_weekday`) sigue el reloj de Madrid, así que en un día de cambio salta o repite
  una hora. `no2_lag24h` son 24 h *transcurridas* (23 o 25 h de reloj local ese día).
- Cada unión es una igualdad exacta `(entity_id, timestamp)` contra tablas con clave única (nunca un `LAG` por posición), así
  que una hora ausente da `null` en vez de desplazar a la vecina. La hora repetida de octubre (01:00Z) no tiene fila en
  ninguna serie: todas las filas que la leen tienen esa feature a `null`. El script falla si el recuento de filas no es
  estaciones × horas o si hay claves duplicadas.
- **Nulo, nunca 0**: entrada o target inválidos/ausentes → `null`. Hay 433 horas de NO₂ con valor válido exactamente 0
  (se conservan, son lecturas).
- **2025-10-26 (hora local)**: sus observaciones se anulan y toda fila cuya ventana de entradas/target [t−25 h, t+7 h) la
  toca lleva `excluded_day_window = true` y `complete = false` (1.344 filas, 56 h × 24 estaciones). Las fechas salen de los
  `dst_anomalies` de los dos informes de ingesta, más `--exclude-date`.
- `complete` = las 9 features recomendadas y el target no nulos, y no `excluded_day_window`. No se descarta ninguna fila: se
  informa de cuántas son completas (ver la cobertura).

## Features (9 recomendadas de 13 columnas)

| feature | rec. | unidad | definición | codificación |
|---|---|---|---|---|
| `no2_last` | sí | µg/m³ | NO₂ de la hora [t−1 h, t) | continua |
| `no2_lag1h` | sí | µg/m³ | NO₂ de la hora [t−2 h, t−1 h) | continua |
| `no2_lag3h` | sí | µg/m³ | NO₂ de la hora [t−4 h, t−3 h) | continua |
| `no2_lag24h` | sí | µg/m³ | NO₂ de la hora [t−25 h, t−24 h) (mismo hueco horario que `no2_last`, un día antes) | continua |
| `wind_speed` | sí | m/s | viento de la hora [t−1 h, t) de la estación meteorológica asociada | continua |
| `temperature` | sí | °C | ídem | continua |
| `relative_humidity` | sí | % | ídem | continua |
| `valid_hour_local` | sí | h (0-23) | hora local del target | entera cruda |
| `valid_weekday` | sí | 0 = lun … 6 = dom | día de la semana local del target | entera cruda |
| `pressure` | no | mbar | ídem meteo; sin candidata en 28079058 y 80 % de cobertura en 2022 | continua |
| `valid_is_weekend` | no | 0/1 | fin de semana (festivos **no** modelados) | indicador |
| `valid_hour_sin`, `valid_hour_cos` | no | – | codificación cíclica de la hora | continua |

Decisiones de codificación (para A4 y para la legibilidad de las reglas):

- **Sin indicadores 0/1 ni columnas de ≤ 5 valores enteros distintos entre las recomendadas.** ex_fuzzy convertiría esas
  columnas en conjuntos categóricos (o, con el wrapper, en particiones cuantílicas degeneradas: `docs/ml/exfuzzy_api_notes.md`).
  `valid_hour_local` (24 valores) y `valid_weekday` (7) los superan. `valid_is_weekend` está en la tabla solo por si A4 lo
  quiere explícitamente.
- **Hora cruda 0-23** en lugar de sin/cos: los términos lingüísticos Bajo/Medio/Alto sobre la hora se leen como «madrugada /
  día / tarde-noche»; sin/cos son difíciles de verbalizar. Coste: 23 h y 0 h quedan lejos en la partición, aunque el tráfico
  es casi igual. Si A4 prefiere continuidad, `valid_hour_sin`/`valid_hour_cos` están en la tabla.
- `valid_weekday` crudo es monótono lun→dom; las particiones trapezoidales no separarán bien «laborable» de «fin de semana»
  (lo que sí hace `valid_is_weekend`). Es un compromiso asumido; no se modelan festivos.
- Calendario referido al **target**, no a la emisión (la hora de emisión es `valid_hour_local − 6` en módulo 24 y no aporta
  información nueva).
- Los lags son de NO₂ de la misma estación; sin transformaciones (ni logaritmo ni escalado): los ajustes pertenecen al train.

## Leakage: qué está garantizado y cómo se comprueba

`tests/air/test_features.py`, sobre observaciones escritas a mano cuyo valor codifica su propia hora (así cada feature dice de
qué instante la leyó): fuente + 1 h ≤ `issued_at_utc` en todas las features; target exactamente en t+6 h y `null` (no
desplazado) cuando esa hora falta; `valid_at − issued_at = 6 h` y hora local correcta en cambios de marzo y octubre;
ninguna estación meteorológica más allá de 5 km (ni siquiera cuando falta el valor de la principal) y suplentes marcados;
filas = estaciones × horas sin duplicados; día excluido anulado y marcado. Además se hizo una comprobación independiente con
pandas sobre 200.000 filas reales al azar (0 discrepancias entre las 5 columnas de NO₂ y las observaciones).
Lo que **no** se comprueba: la latencia real de publicación, y que `H03` de octubre sea la primera ocurrencia (asunción del
intérprete).

## Split cronológico recomendado

Cifras de filas completas por año (UTC) en la cobertura: 2019 91,8 %, 2020 91,9 %, 2021 89,0 %, 2022 76,8 %, 2023 87,5 %,
2024 91,1 %, 2025 85,8 %.

| periodo | emisión (UTC, semiabierto) | filas completas del año (antes de quitar el embargo, ≈ 576 filas) |
|---|---|---|
| train | 2019-01-01T00:00Z – 2023-12-31T00:00Z (embargo 24 h antes de val) | 919.149 |
| validation | 2024-01-01T00:00Z – 2024-12-31T00:00Z (embargo 24 h antes de test) | 191.970 |
| test | 2025-01-01T00:00Z – 2026-01-01T00:00Z | 180.326 |

Límites por frontera de año con `embargo_hours = 24` (≥ el horizonte de 6 h que exige el contrato; 24 h cubre además
`no2_lag24h`). Justificación:

- **El test es el año más reciente y no está en una anomalía**: 2025 completo, sin COVID. Es lo más parecido a un uso real
  («entrenar con el pasado, predecir el siguiente año»). 2024 como validación evita ajustar hiperparámetros sobre el test.
- **COVID-2020**: el confinamiento (marzo-junio) cambió el régimen (NO₂ medio de marzo-junio: 27,7 µg/m³ en 2019, 16,0 en
  2020, 22,6 en 2021). Está en train porque deja a la regla ver un régimen distinto, pero **no** debe estar en
  validación/test, donde sesgaría la selección de modelo y haría la comparación con persistencia/climatología menos
  representativa. Si A4 quiere una sensibilidad: reentrenar sin 2020-03-14…2020-06-21 y comparar.
- **Cobertura**: 2022 es el año flojo (76,8 % completas; sensores meteorológicos 102-115 sin datos entre septiembre y
  diciembre de 2022; NO₂ de 28079004 al 76 % y de 28079016 al 72 %). Va a train, donde solo resta muestras; poner 2022 en
  validación/test haría las métricas por estación poco comparables. 28079004 ya perdía NO₂ (≈ 71-77 %) en 2020-2022 y vuelve
  al 99 % en 2023-2025; el test lo ve completo.
- **Deriva a la baja del NO₂**: media del target 34,6 (2019) → 27,2 → 28,9 → 28,2 → 27,5 → 23,2 → 22,5 µg/m³ (2025). El test
  tendrá niveles menores que el train; es una limitación real (todos los modelos y la persistencia la sufren por igual) y A4 debe
  informar de ella, no corregirla con información del test.
- **Estaciones**: 28079058 (sin viento a ≤ 5 km) no tiene ninguna fila completa y 28079055 no tiene NO₂ en 2025: el test
  completo tiene 23 estaciones sin 28079055 y 22 contando 058. Para generalización espacial, A4 puede retirar estaciones enteras
  del train (holdout por entidad), pero no se recomienda ninguna en concreto.
- 2026 (parcial, solo hasta septiembre) no se usa. Si se reentrena el modelo final, hacerlo con train + validation y reservar
  el test de 2025 intacto.

## Limitaciones

- La meteorología es de otro punto de la ciudad (hasta 4,6 km), con menor representatividad para el viento; nunca se interpola.
- El suplente puede ser una estación a distinta distancia: el 16 % de las filas tiene al menos una variable meteorológica de
  un suplente (`meteo_fallback_n`); un sesgo sistemático entre estaciones (p. ej. unos grados de temperatura) no se corrige.
- No hay festivos ni dirección del viento (circular; el viento se usa solo como velocidad). El tráfico no está en esta tabla sino en la tabla aparte `madrid_no2_h6_traffic` (AT-012; unión 1:1 por `entity_id` e `issued_at_utc`; ver [`madrid_traffic.md`](madrid_traffic.md)).
- Las particiones difusas, imputaciones y escalados se ajustan en train (A4); la tabla no ajusta nada.
