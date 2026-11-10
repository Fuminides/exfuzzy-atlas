# Nivel relativo de demanda de taxi amarillo a 1 hora: «baja / normal / alta / muy alta» (`nyc_pickups_h1_level`, AT-031b)

Decisión de producto (el usuario): el target de NYC no es el número de recogidas sino **cuánto se aleja la demanda de lo habitual en esa zona a esa hora de la semana**, con todo el «habitual» fijado **solo con el periodo de entrenamiento**.
La regresión sobre el conteo bruto se descartó porque en Madrid las reglas de regresión eran ilegibles. El clasificador de reglas ganadoras de ex_fuzzy (contrato v0.3, `CONTRACTS.md` §9) se entrena después (A4).
Se construye con `python -m atlas.domains.mobility.levels` (código en `src/atlas/domains/mobility/levels.py`) a partir de la tabla de AT-031 ([`nyc_pickups_h1_feature_card.md`](nyc_pickups_h1_feature_card.md)).
Las cifras de abajo son de la versión de datos `nyc-tlc-yellow-2024-04_2025-03-v1` y salen de `nyc_pickups_h1_level_report.json`.

**Qué es y qué no.** La etiqueta se lee «demanda observada de taxi amarillo por encima/por debajo de lo habitual de esa zona a esa hora de la semana en abril-diciembre de 2024». No es riesgo, ni probabilidad, ni
demanda total, ni una afirmación causal: «alta» en febrero-marzo de 2025 mezcla demanda realmente inusual con deriva (estación, cambios de reporte de proveedores, peaje de congestión). Los grados de activación de las reglas no son probabilidades.

## 1. Definición

| Elemento | Decisión |
|---|---|
| Celda de referencia («lo habitual») | (zona, **hora de la semana local**): día de la semana × hora de reloj de America/New_York de la hora del target, 168 por zona. Reloj local, de modo que «viernes 19 h» significa lo mismo antes y después de un cambio de hora (test). |
| Muestra de la referencia | Los `target` conocidos de las emisiones de `split.train` (`[2024-04-01T04Z, 2025-01-01T05Z)`): 38-40 valores por celda (mediana 39, 18.480 celdas). Nada de validación ni test. |
| Cantidad relativa `target_rel` | **Percentil de rango medio** (0-100) del conteo dentro de la muestra de su celda: `100·(#ref < x + ½·#ref = x)/n`. |
| Clases | `baja` [0, 25) · `normal` [25, 75) · `alta` [75, 95) · `muy alta` [95, 100], límite inferior incluido (`boundary = lower_inclusive`). `configs/mobility/nyc_level_scheme.json`, validado como `TargetScheme`. |
| Regla de volumen mínimo | Una celda sirve para **etiquetar** solo si tiene ≥ 30 valores de train (`insufficient_samples`) **y** media de train ≥ 1 recogida/hora (`low_volume`). Si no, `target_level` es null (no «normal»). Parámetros en `configs/mobility/nyc_pickups_h1_level.json`. |
| Colores | Azul secuencial de ColorBrewer *Blues*: `#DEEBF7`, `#9ECAE1`, `#4292C6`, `#08306B`. Ordenado por luminosidad (también legible en escala de grises y con daltonismo), sin rojo/verde y sin semáforo: la demanda alta no es «mala». |
| `source_url` y unidad | No hay índice oficial: `source_url` apunta a este documento; `unit` = «percentil (0-100, rango medio) del target en su celda zona × hora de la semana del periodo de train». |

### Por qué hora de la semana (168 celdas) y no hora × tipo de día

Comparación con hold-out **dentro de train** (`python -m atlas.domains.mobility.level_slots`): la referencia se ajusta con abril-septiembre y se puntúa con octubre-diciembre (validación y test no se leen) con el CRPS de la distribución empírica de la celda, dividido por la media de la zona, promedio por zona (menor es mejor). Con solo 26 valores por celda en este experimento:

| celda | celdas/zona | todas | < 3/h | 3-10/h | 10-50/h | ≥ 50/h |
|---|---|---|---|---|---|---|
| zona | 1 | 0,548 | 0,690 | 0,510 | 0,446 | 0,451 |
| hora | 24 | 0,396 | 0,593 | 0,416 | 0,253 | 0,228 |
| hora × laborable/fin de semana | 48 | 0,361 | 0,560 | 0,374 | 0,224 | 0,193 |
| hora × laborable/sáb/dom | 72 | 0,355 | 0,558 | 0,369 | 0,215 | 0,184 |
| **hora × día de la semana** | 168 | **0,351** | 0,564 | **0,364** | **0,203** | **0,172** |

La hora de la semana gana en todos los grupos salvo en las zonas de menos de 3 recogidas/hora, donde 72 celdas la superan por 0,006 (el ruido de 26 muestras pesa más); con las 39 semanas completas de train (en lugar de 26) esa desventaja debería reducirse, aunque no se midió.
Además es la celda que se explica sola («lunes a las 8 h»), y viernes/sábado de madrugada difieren mucho de domingo (EDA §4). Con ~39 valores por celda la resolución del percentil es de ~2,6 puntos y el corte del 95 % equivale a «una de las ~2 semanas más altas»: la etiqueta de una celda concreta es ruidosa, la distribución global no.

### Por qué percentil y no razón con la mediana

Una razón «recogidas / mediana de la celda» con cortes fijos (p. ej. 0,6 / 1,3 / 2) se descartó: la mediana de la celda es 0 en el 12,4 % de las celdas, 1 en el 16,4 % y 2 en el 9,4 %, de modo que la razón no está definida o salta de 1 a 2 con un solo viaje; con conteos tan pequeños el ruido de Poisson domina y los cortes fijos no tienen un significado estadístico común entre zonas.
El percentil lleva la frecuencia de cada clase en train (≈ 25/50/20/5 %) por construcción en todas las zonas, trata los empates (el rango medio: en una celda con 60 % de ceros un 0 es el percentil 30, «normal», y `baja` es imposible porque no hay nada por debajo de lo habitual) y es exacto en las fronteras (enteros divididos por un entero: 25,0 y 75,0 caen en la clase superior, test).
Además se publica, por celda, el **conteo a partir del cual** se alcanza cada clase (`trips_from_normal`, `trips_from_alta`, `trips_from_muy_alta`, en `nyc_pickups_h1_level_reference.parquet`), para que la web pueda decir «alta = 12 o más viajes aquí a esta hora».

### Regla de volumen mínimo: por qué

Con media de celda < 1 recogida/hora un viaje de diferencia mueve el percentil decenas de puntos y «muy alta» significaría dos viajes. 2.829 de las 18.480 celdas (15,3 % de las filas con target) quedan sin etiqueta: 34 % de las filas de las 41 zonas de < 3 recogidas/hora, 12 % de las de 3-10, 4 % de las de 10-50 y 0,2 % de las de ≥ 50 (casi igual en los tres periodos, porque las celdas se fijan con train).
Esas filas **conservan** `target`, `target_rel` y las features, con `level_status = low_volume`; para el mapa son «sin referencia suficiente», un gris distinto de «normal». Es una decisión conservadora: las celdas de menos de 1 viaje/hora son justo donde más sube la demanda en febrero-marzo (ver §3), de modo que la regla no corrige esa deriva pero evita etiquetarla con conteos ínfimos.

## 2. Features relativas

Las siete features de AT-031 siguen igual (los lags se conocen en `T`). Se añaden cinco relativas, **funciones del lag crudo y de constantes de calendario fijadas con train**, así que su `lag_hours` es el del lag crudo:

| feature | unidad | `lag_hours` | definición |
|---|---|---|---|
| `rel_lag1` | percentile | 1 | percentil de `pickups_lag1` en la celda de **su propia hora** (T−1 h): «la última hora fue ALTA respecto a lo normal a esa hora» |
| `rel_lag2` | percentile | 2 | ídem para `pickups_lag2` (T−2 h) |
| `rel_lag24` | percentile | 24 | ídem para `pickups_lag24` (T−24 h transcurridas; la celda es la del día anterior, en hora local) |
| `rel_lag168` | percentile | 168 | ídem para `pickups_lag168`: es la celda del propio target (misma hora de la semana pasada) |
| `rel_mean24h` | ratio | 1 | `pickups_mean24h` dividido por la media de las 24 medias de celda de esas mismas 24 horas; 1 = la última jornada fue como lo normal |

- Un percentil necesita solo ≥ 30 valores en la celda de la hora del lag (no se aplica el filtro de volumen, que es de etiquetas); si el lag crudo es null (arranque, hora ambigua del 3-nov-2024) la relativa también (nunca 0 ni 50).
- `configs/mobility/feature_spec.json` lleva ahora las 12 features (`python -m atlas.domains.mobility.features --write-spec` y `levels --write-spec` escriben el mismo fichero).
- No se añade la «norma» de la hora del target (media de celda) como feature: las relativas eliminan la escala de la zona y las crudas la conservan, y A4 puede derivarla del sidecar si la quiere.

### Fugas (comprobado con tests)

- **La referencia solo lee train**: modificar cualquier hora de validación o test deja idénticas la referencia (`n`, valores ordenados, medias) y todas las filas de train; modificar una hora de train sí la cambia.
- **Las features relativas no leen horas no terminadas**: al perturbar una hora `h`, `rel_lagK` cambia por primera vez en `T = h + K`, `rel_mean24h` en `h + 1 h` y la etiqueta/`target_rel` solo en `T = h`; ninguna fila anterior y ninguna otra zona cambian.
- **Propiedad conocida, no fuga**: las filas de **train** se etiquetan contra una referencia que contiene su propio valor (y valores posteriores de train), así que la distribución de clases en train es ≈ 25/50/20/5 por construcción; validación y test son fuera de muestra. Un umbral climatológico se comporta así siempre. La consecuencia práctica es que el rendimiento en train no es comparable con el de validación/test.

## 3. Tabla y distribución de clases

`data/processed/mobility/features/nyc_pickups_h1_level/year=/month=/` (Parquet, 963.600 filas = 110 zonas × 8.760 horas, las mismas que `nyc_pickups_h1`; test de conservación de filas y orden). Claves `entity_id`, `issued_at_utc`, `valid_at_utc`; `target` crudo; las 7 features de AT-031; y
`target_rel` (percentil, null si la celda tiene < 30 valores o el target es null), `target_level` (etiqueta, null salvo `level_status = ok`), `level_status` (`ok`, `target_missing`, `insufficient_samples`, `low_volume`), `volume_group` (grupo de la **zona** por su media de train: `lt_3`, `3_10`, `10_50`, `ge_50`; 41, 16, 16 y 37 zonas; **es una columna para evaluar por grupo, no una feature**) y las cinco relativas.
Sidecars: `nyc_pickups_h1_level_reference.parquet` (una fila por celda: `n_train`, `train_mean`, `train_median`, `trips_from_*`, `usable_for_level`) y `nyc_pickups_h1_level_report.json` (todas las cifras de esta sección).

**Filas completas** (etiqueta y las 12 features conocidas): train 596.400 de 726.110, validación 53.575 de 63.360, test 116.380 de 137.170. La diferencia con AT-031 (704.550 / 63.360 / 137.170) son las filas `low_volume` (111.293 / 9.785 / 20.790 en target conocido) y el arranque; filas con `target_missing`: 220.

**Clases en filas completas** (split recomendado de AT-031):

| periodo | n | baja | normal | alta | muy alta |
|---|---|---|---|---|---|
| train | 596.400 | 152.096 (25,5 %) | 296.222 (49,7 %) | 120.394 (20,2 %) | 27.688 (4,6 %) |
| validación (8-31 ene 2025) | 53.575 | 14.061 (26,2 %) | 24.843 (46,4 %) | 10.374 (19,4 %) | 4.297 (8,0 %) |
| test (8-feb a 31-mar 2025) | 116.380 | 14.601 (12,5 %) | 44.528 (38,3 %) | 32.955 (28,3 %) | 24.296 (20,9 %) |

Ninguna clase está casi vacía: el mínimo por (periodo, grupo de volumen, clase) es 434 filas (validación, grupo 10-50, `muy alta`). En train el desequilibrio es leve (5,4 : 1 entre `normal` y `muy alta`), así que el muestreo natural es defendible; el muestreo templado de Madrid (`class_sample`, potencia 0,5) sigue disponible.

**Por grupo de volumen** (zona agrupada por su media de train; % por clase):

| periodo | grupo | n | baja | normal | alta | muy alta |
|---|---|---|---|---|---|---|
| train | < 3/h | 171.601 | 26,3 | 48,9 | 20,3 | 4,4 |
| train | 3-10/h | 90.102 | 25,1 | 50,2 | 20,2 | 4,5 |
| train | 10-50/h | 98.138 | 25,1 | 50,1 | 20,1 | 4,7 |
| train | ≥ 50/h | 236.559 | 25,2 | 49,8 | 20,1 | 4,8 |
| validación | < 3/h | 15.380 | 20,4 | 43,0 | 24,4 | 12,1 |
| validación | 3-10/h | 8.090 | 20,9 | 46,1 | 23,5 | 9,5 |
| validación | 10-50/h | 8.829 | 33,6 | 46,6 | 14,9 | 4,9 |
| validación | ≥ 50/h | 21.276 | 29,4 | 48,9 | 16,0 | 5,8 |
| test | < 3/h | 33.592 | 7,3 | 27,1 | 31,8 | 33,8 |
| test | 3-10/h | 17.600 | 5,5 | 27,8 | 34,7 | 32,0 |
| test | 10-50/h | 19.129 | 16,7 | 42,2 | 27,1 | 14,0 |
| test | ≥ 50/h | 46.059 | 17,3 | 48,8 | 23,9 | 10,0 |

### Salto de febrero-marzo y peaje de congestión

Proporción de `alta` + `muy alta` (nominal en train ≈ 25 %) por mes local y grupo, filas completas:

| mes | < 3/h | 3-10/h | 10-50/h | ≥ 50/h | todas |
|---|---|---|---|---|---|
| 2024-07 | 18 | 15 | 14 | 11 | 14 |
| 2024-08 | 19 | 15 | 11 | 8 | 13 |
| 2024-12 | 27 | 26 | 28 | 40 | 32 |
| 2025-01 (tras el peaje, desde el 5-ene; validación = 8-31) | 32 | 28 | 17 | 19 | 24 |
| 2025-02 | 58 | 59 | 36 | 31 | 44 |
| 2025-03 | 69 | 70 | 43 | 35 | 51 |

- **Zonas pequeñas**: como se esperaba, en test el 66 % (< 3/h) y el 67 % (3-10/h) de las filas son `alta` o `muy alta`, frente al 25 % de train: son las zonas cuyo nivel se multiplica por 2-3 en febrero-marzo (EDA §6), con causa no verificada (cambio de proveedor o de cobertura de reporte, e-hail…). En las filas `low_volume` que la regla deja fuera la subida es aún mayor (57 % `alta`+ en < 3/h en test), así que la deriva no se debe a la regla.
- **Zonas grandes** (≥ 50/h): 34 % en test (10 % `muy alta`). Aquí pesa más la estacionalidad que el cambio de reporte: en train, julio-agosto dan solo 8-11 % (baja demanda de verano) y diciembre 40 %; train no contiene ningún invierno, así que enero-marzo se compara con la norma de abril-diciembre.
- **Peaje de congestión** (desde 2025-01-05): la validación (8-31 ene) es entera posterior al peaje y la proporción alta+ en zonas grandes pasa de 40 % (dic) a 19 % (ene). Con un solo invierno **no se puede separar** el efecto del peaje, el de la estación y el de las vacaciones de diciembre. No se afirma causalidad. Por barrios (test, filas `ok`): Manhattan 41 % alta+, Queens 56 %, Brooklyn 68 %, Bronx 70 % (solo 2 zonas), consistente con que el salto está en los barrios exteriores y de poco volumen, aunque barrio y volumen están muy ligados.
- Consecuencia: **la tasa de base de las clases cambia entre train, validación y test**. Un clasificador que aprende «normal es lo más probable» se verá castigado en test por razones ajenas al modelo.

### Línea base descriptiva (no es una evaluación de modelo)

La clase de `rel_lag1` como predicción de la clase del target (persistencia de nivel) acierta el 44,7 % en validación (clase mayoritaria 46,4 %) y el 43,9 % en test (mayoritaria 38,3 %); por grupos, entre 36 % (< 3/h) y 52 % (≥ 50/h) en validación y entre 40 % y 48 % en test.
Quitar la hora del día deja una señal mucho más débil que la del conteo bruto (autocorrelación 0,95): **la tarea relativa es más difícil que la de regresión**, y cualquier modelo debe superar esta persistencia y la clase mayoritaria.

## 4. Recomendaciones para A4

1. Usar solo filas con `target_level` no nulo y las 12 features no nulas (`levels.complete_mask(frame)`). Submuestrear **train** como en AT-031 (200-400 k filas, estratificando por zona, mes y clase) y evaluar validación y test completos.
2. Evaluar **por `volume_group`** (y por mes), no solo en agregado: macro-F1, accuracy balanceada, MAE sobre el índice de clase y, importante, **la proporción predicha frente a la observada por clase y mes**. Ver `volume_group` como columna de segmentación, nunca como feature.
3. Seleccionar solo con validación (enero, tras el peaje); leer test una vez y **reportar febrero y marzo por separado** del agregado, porque la tasa base ya no es la de train.
4. Baselines mínimos: clase mayoritaria de train por grupo; persistencia de nivel (clase de `rel_lag1`, de `rel_lag24` y de `rel_lag168`); HGB sobre las mismas features.
5. Las zonas sin referencia (`low_volume`) y las excluidas por AT-031 deben salir en el mapa como «sin referencia», no como `normal`.
6. `atlas.ml.classification.ClassScheme` asume bandas enteras con límites superiores inclusivos (ICA); aquí las clases ya vienen precalculadas en `target_level` y el esquema es un `TargetScheme` directo (`levels.load_scheme()`), que A4 usa para el orden, los colores y `ModelCard.target_scheme`. `ClassScheme.classify` no sirve para percentiles.

## 5. Límites

- Un solo invierno y ningún invierno en train: la norma es de abril-diciembre de 2024; «alta» en febrero-marzo mezcla demanda inusual con deriva estacional, de proveedores y del peaje. No hay festivos modelados: los de train están dentro de las celdas de referencia.
- ~39 muestras por celda: la etiqueta de una celda y hora concretas es ruidosa (resolución del percentil ~2,6 puntos); lo estable es la distribución por zona y grupo.
- Los percentiles son de la demanda observada de viajes completados de taxi amarillo (suposición de reproducción histórica de AT-031, sin feed vivo); no se afirma capacidad en tiempo real.
- Probado con pandas 2.3.3 (local); la CI usa pandas 3: los tests pasan también con `future.infer_string` y copy-on-write activados, que son los cambios de pandas 3 que afectan a este código.

## Reproducir

```bash
export ATLAS_DATA_DIR=/path/to/exfuzzy-atlas/data      # si se comparte el data/ de otro checkout
PYTHONPATH=src python -m atlas.domains.mobility.features --write-spec    # AT-031 (tabla base)
PYTHONPATH=src python -m atlas.domains.mobility.levels --write-spec      # AT-031b: tabla de niveles, sidecars y feature_spec.json
PYTHONPATH=src python -m atlas.domains.mobility.level_slots              # comparación de celdas (solo train)
PYTHONPATH=src python -m pytest tests/mobility -q
```

La tabla de niveles tarda ~6 s con un pico de RSS de ~1,0 GB (la tabla de AT-031 entera en pandas, 963.600 filas × 20 columnas; la escritura pasa por DuckDB con `memory_limit=1500MB`).
