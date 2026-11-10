# Tráfico de Madrid: fuente, correspondencia espacial con las estaciones de aire y agregación horaria (`madrid-traffic`)

Generado por `python -m atlas.domains.air.traffic` (AT-012). No editar a mano: se regenera con cada ingesta. Features para el modelo: [`madrid_no2_h6_traffic.md`](madrid_no2_h6_traffic.md).

> **Correlación no es causalidad.** Un punto de medida cuenta vehículos en **un tramo de calle**, no en el entorno de la estación. La asociación es por distancia y es una aproximación. Que el tráfico mejore (o no) un modelo de NO₂ no demuestra que el tráfico cause (o no) el NO₂ medido; el análisis incremental con y sin tráfico es de A4 y no se ha hecho aquí.

## Resumen

- Meses: 2023-01 a 2025-12 (36); versión `madrid-traffic-2023-2025-v1`; descarga 2026-10-30T18:44:21+00:00.
- Entrada: 36 zips mensuales de 15 minutos (3.10 GB, 465,951,661 registros de todos los puntos) y 36 ficheros mensuales de ubicación (24.7 MB, 4,715-5,024 puntos por mes).
- Regla de asociación: puntos a **≤ 500 m** de la estación en el fichero de ubicación **del mismo mes** (tipos urban, m30, other); sin puntos -> feature nula.
- Agregación: media de los registros válidos de 15 min en veh/h, al menos 3 de 4; 10,410,810 filas horarias canónicas (`traffic_intensity`) de los puntos asociados; rango UTC 2022-12-31T23:00:00+00:00 a 2025-12-31T22:00:00+00:00.
- Registros de 15 min de los puntos asociados: 41,134,537; válidos 41,127,382 (99.98 %).
- Pico de memoria del proceso (RSS) de la ingesta: 1015 MB.

## Fuentes

| conjunto | URL | ficheros | licencia |
|---|---|---|---|
| Tráfico. Histórico de datos del tráfico desde 2013 | https://datos.madrid.es/dataset/208627-0-transporte-ptomedida-historico | 36 zips mensuales (`traffic-AAAA-MM.zip`, un CSV de ~750 MB descomprimido) + PDF de estructura | CC BY 4.0 (metadatos del portal: `cc-by`) |
| Tráfico. Ubicación de los puntos de medida del tráfico | https://datos.madrid.es/dataset/202468-0-intensidad-trafico | 36 CSV mensuales (`points-AAAA-MM.csv`) + PDF de estructura | CC BY 4.0 (metadatos del portal: `cc-by`) |

Atribución: Ayuntamiento de Madrid, datos abiertos (datos.madrid.es). Los tamaños de los ficheros descargados coinciden con los `byteSize` que declara el portal en su RDF (comprobado fichero a fichero). Los sha256 están en `source_manifest.json` de cada carpeta cruda (`data/raw/madrid-traffic`, `data/raw/madrid-traffic-points`) y en `quality_report.json`. El portal ofrece 2013-2022 y 2026; no se han descargado (el rango pedido cubre entrenamiento 2023, validación 2024 y prueba 2025).

## Esquema, unidades y convenciones (verificado con los datos)

Cabecera idéntica en los 36 ficheros (el lector falla si cambia): `id;fecha;tipo_elem;intensidad;ocupacion;carga;vmed;error;periodo_integracion`. Documento oficial: `estructura_ds_contenido_trafico_historico.pdf` (versión octubre/2023).

| campo | contenido | unidad / valores observados |
|---|---|---|
| `id` | punto de medida; «secuencial, único e invariable» según el PDF | entero; único por fichero; ver estabilidad abajo |
| `fecha` | inicio del periodo de 15 min, **hora oficial de Madrid sin desfase** | `AAAA-MM-DD hh:mm:ss` (el PDF dice `dd/mm/yyyy`; los datos usan ISO; el lector acepta ambos) |
| `tipo_elem` | tipo de punto | `URB`, `M30`, `C30` (los ficheros de ubicación lo llaman `other`; no documentado) y un `other` suelto |
| `intensidad` | vehículos del periodo **expresados en veh/h** (dividir entre 4 para vehículos reales) | veh/h; negativo = sin dato (no aparece), `NaN` = sin dato |
| `ocupacion` | % de tiempo con el detector ocupado | %; `NaN` en algunos registros; no se agrega |
| `carga` | índice sintético de congestión 0-100 (en M30 casi siempre 0) | adimensional; no se agrega |
| `vmed` | velocidad media, solo M30 | km/h; 0 en puntos urbanos (no es «sin dato»); no se agrega |
| `error` | `N` sin errores; `E` muestras no óptimas; `S` muestra errónea no integrada | observados: `N` y **vacío** (solo M30; no documentado); `E`/`S` no aparecen en 2023-2025 |
| `periodo_integracion` | muestras recibidas en el periodo | 1-15; no se usa como criterio de validez |

Registros de los ficheros por tipo y valor de `error` (los 36 meses, todos los puntos):

| tipo_elem | error | registros | puntos (máx. mes) | intensidad NaN | intensidad > 20000 |
|---|---|---|---|---|---|
| C30 | `N` | 11,709,644 | 125 | 0 | 3 |
| M30 | `(vacío)` | 1,198,606 | 311 | 0 | 0 |
| M30 | `N` | 28,226,156 | 299 | 0 | 0 |
| URB | `N` | 424,817,253 | 4341 | 0 | 896 |
| other | `N` | 2 | 1 | 0 | 0 |

Un `error` vacío en M30 marca registros casi siempre en cero (80-89 % de ceros en marzo y octubre de 2023, frente a 0,3-1,1 % con `N`; intensidad media 72-222 frente a ~1,350 veh/h): se consideran **inválidos**. Un cero con `N` se conserva (flujo nocturno real); un sensor atascado en cero con `N` no es detectable.

### Horario y cambio de hora

El PDF dice «fecha y hora oficiales de Madrid». Evidencia en los datos: el 2023-03-26 existe la marca `02:00` (una sola, con 4,321 registros) y faltan `02:15-02:45` (93 marcas distintas en el día: 92 reales más esa); el 2023-10-29 la hora local `02:00-02:59` aparece **una sola vez** (4 marcas, sin duplicados) y el día tiene 96 marcas en lugar de 100. Por tanto:

- Hora local -> UTC con `Europe/Madrid`; `timestamp_utc` = inicio de la hora. Una hora con clave *s* cubre [s, s+1 h) y está disponible en *s*+1 h.
- Primavera (hora local inexistente): los registros con hora local dentro del hueco se descartan (1,194), y la marca `03:00` que sigue al hueco se invalida (1,137) porque en los datos tiene ~26 % de ceros frente a ~7 % habitual (el periodo integra el salto).
- Otoño (hora local repetida): no se puede saber qué hora real es la que está en el fichero, así que **las dos horas UTC se escriben con `value=null`, `missing_reason=invalid_observation`, `validity_flag=ambiguous_local_hour`** (CONTRACTS §8.6); 2,422 filas.

## Estabilidad de ids y ubicaciones

Los ids son únicos en cada fichero mensual. Entre los 36 ficheros hay 5,083 ids distintos y 4,663 están en todos los meses. De un mes al siguiente se **añaden** 368 puntos, se **retiran** 59 y 220 cambios de coordenadas superan 10 m (afectan a 216 ids; ningún id cambia de tipo). Por eso la asociación se construye con el fichero de ubicación de **cada mes** y no con una foto única: un punto que se mueve entra o sale de la regla en el mes que corresponde. Los puntos por mes (todos los tipos): 4,715 en 2023-01 a 5,024 (máx.).

Comprobado en enero de 2023: 4 ids del fichero de datos (316 registros, uno con id de 10 dígitos que parece basura) no están en el fichero de ubicación de su mes, así que no se pueden situar y no se usan; y 213 puntos del fichero de ubicación no envían ningún dato ese mes.

## Correspondencia espacial con las estaciones de aire

Distancia ortodrómica (haversine) entre las coordenadas oficiales de la estación (AT-010, Geoportal) y las del punto (fichero del mes). Tabla del último mes (2025-12); la columna «regla» es el número de puntos a ≤ 500 m ese mes, y los mínimos y máximos son sobre los 36 meses. «Con datos» son los puntos de la regla con ≥ 50 % de horas válidas en el último mes.

| estación | nombre | ≤250 m | ≤500 m | ≤1000 m | M30 / otro ≤500 | más cercano (m) | regla | regla mín-máx | mediana dist. regla (m) | con datos |
|---|---|---|---|---|---|---|---|---|---|---|
| 28079004 | Pza. de España | 18 | 41 | 131 | 0 / 0 | 60 | 41 | 40-42 | 266 | 38 |
| 28079008 | Escuelas Aguirre | 10 | 26 | 104 | 0 / 0 | 75 | 26 | 26-26 | 294 | 25 |
| 28079011 | Ramón y Cajal | 11 | 30 | 121 | 0 / 0 | 52 | 30 | 30-30 | 311 | 27 |
| 28079016 | Arturo Soria | 7 | 34 | 104 | 0 / 0 | 27 | 34 | 29-34 | 330 | 34 |
| 28079017 | Villaverde | 1 | 3 | 38 | 0 / 0 | 213 | 3 | 3-3 | 320 | 3 |
| 28079018 | Farolillo | 0 | 4 | 63 | 0 / 0 | 488 | 4 | 4-4 | 492 | 4 |
| 28079024 | Casa de Campo | 0 | 0 | 0 | 0 / 0 | - | 0 | 0-0 | - | 0 |
| 28079027 | Barajas Pueblo | 1 | 7 | 10 | 0 / 0 | 168 | 7 | 6-7 | 318 | 5 |
| 28079035 | Pza. del Carmen | 8 | 32 | 105 | 0 / 0 | 30 | 32 | 31-32 | 354 | 32 |
| 28079036 | Moratalaz | 7 | 15 | 65 | 0 / 0 | 30 | 15 | 15-15 | 276 | 13 |
| 28079038 | Cuatro Caminos | 5 | 24 | 100 | 0 / 0 | 68 | 24 | 24-24 | 355 | 22 |
| 28079039 | Barrio del Pilar | 13 | 42 | 138 | 4 / 0 | 45 | 42 | 42-42 | 330 | 42 |
| 28079040 | Vallecas | 2 | 12 | 58 | 0 / 0 | 133 | 12 | 12-12 | 358 | 12 |
| 28079047 | Méndez Álvaro | 2 | 16 | 88 | 0 / 0 | 152 | 16 | 16-16 | 371 | 16 |
| 28079048 | Castellana | 8 | 26 | 118 | 0 / 0 | 87 | 26 | 25-26 | 337 | 21 |
| 28079049 | Parque del Retiro | 0 | 3 | 74 | 0 / 0 | 433 | 3 | 3-3 | 471 | 3 |
| 28079050 | Plaza Castilla | 7 | 31 | 133 | 0 / 0 | 149 | 31 | 31-32 | 306 | 30 |
| 28079054 | Ensanche de Vallecas | 0 | 5 | 31 | 0 / 0 | 377 | 5 | 5-5 | 446 | 5 |
| 28079055 | Urb. Embajada | 0 | 4 | 15 | 0 / 0 | 470 | 4 | 4-4 | 478 | 4 |
| 28079056 | Pza. Elíptica | 26 | 50 | 101 | 2 / 0 | 22 | 50 | 50-50 | 230 | 43 |
| 28079057 | Sanchinarro | 5 | 25 | 85 | 0 / 0 | 187 | 25 | 20-25 | 375 | 16 |
| 28079058 | El Pardo | 0 | 0 | 0 | 0 / 0 | - | 0 | 0-0 | - | 0 |
| 28079059 | Juan Carlos I | 4 | 13 | 42 | 0 / 0 | 95 | 13 | 13-14 | 308 | 10 |
| 28079060 | Tres Olivos | 0 | 6 | 59 | 0 / 0 | 283 | 6 | 6-6 | 333 | 6 |

### Regla elegida y por qué

- **Radio 500 m, todos los tipos juntos, por mes.** Con 250 m, 7 de las 24 estaciones no tienen ningún punto y 4 tienen 1-3; con 500 m quedan 2 sin puntos (28079024, 28079058) y 2 con 1-3; con 1 km solo 2 sin puntos pero la distancia mediana de los puntos pasa de 164 m (≤ 250 m) a 322 m (≤ 500 m) y 723 m (≤ 1 km), y el tramo medido deja de estar en el entorno inmediato de la estación. De los tres radios probados, 500 m es el menor que da al menos 3 puntos a todas las estaciones que tienen alguno. La mediana de puntos de la regla por estación es 20.
- El radio se eligió **por recuentos y distancias, no por la correlación con el NO₂**, para no ajustar la asociación al resultado. No hay validación independiente de que 500 m sea el radio «correcto»; es una aproximación documentada y la tabla `association.parquet` trae todos los puntos hasta 1 km con su distancia (`in_rule` marca los de la regla), por si A4 quiere un análisis de sensibilidad (requiere repetir la agregación: ~8 s por mes).
- **M30 y urbanos no se separan**: hay puntos M30 a ≤ 500 m solo de 2 estaciones (4 y 2 puntos) y de tipo `other` de ninguna; dos variables por tipo serían nulas en 22 estaciones. Las intensidades M30 son ~5 veces las urbanas (media 1,345 frente a 290 veh/h en octubre de 2023), así que la media mezcla magnitudes distintas en esas dos estaciones; el tipo de cada punto está en `association.parquet`.
- **Estaciones sin puntos** (28079024, 28079058; ambas de tipo suburbana): features de tráfico **nulas** en todas las filas. No se toma tráfico de otra estación ni de la ciudad.
- Estaciones de fondo urbano (p. ej. Villaverde, Farolillo, Retiro, Ensanche de Vallecas, Embajada) tienen solo 3-5 puntos y el más cercano a 213-488 m: la asociación es ahí claramente más débil que en las de tráfico (Plaza de España, Plaza Elíptica, Barrio del Pilar, con 41-50 puntos y alguno a ≤ 60 m).

Archivos: `association.parquet` (mes, estación, punto, tipo, nombre, distancia, rango, `in_rule`), `association_summary.json`, `points_monthly.parquet` (todos los puntos de cada mes con coordenadas), `point_coverage.parquet` (horas válidas por punto y mes).

## Agregación horaria y calidad

Un registro de 15 min es **válido** si `error = N` y `0 ≤ intensidad ≤ 20000` veh/h (un carril satura en ~2,000 veh/h; hay 899 registros por encima en los 36 meses: C30 3, URB 896). La hora es la media de sus registros válidos y solo es valor si hay ≥ 3 de 4; si no, es nula (`insufficient_valid_records`), **nunca 0**. Una hora sin ningún registro no tiene fila.

| estado del registro (puntos asociados) | registros | % del total |
|---|---|---|
| valid | 41,127,382 | 100.0 % |
| error_flag_blank | 4,620 | 0.0 % |
| dst_nonexistent_local_time | 1,194 | 0.0 % |
| dst_transition_slot | 1,137 | 0.0 % |
| intensity_implausible | 204 | 0.0 % |

| filas horarias canónicas por `validity_flag` | filas | % |
|---|---|---|
| valid | 10,268,107 | 98.6 % |
| insufficient_valid_records | 140,281 | 1.3 % |
| ambiguous_local_hour | 2,422 | 0.0 % |

## Limitaciones

- Un punto mide **un tramo de calle** (un sentido) o una sección de autovía, no el área que rodea a la estación; la asociación por distancia es una aproximación y no implica que ese tráfico sea la fuente del NO₂ medido. Correlación no es causalidad.
- Los puntos tienen magnitudes muy distintas (calle secundaria frente a M30); la media entre puntos pondera igual a cada uno.
- La calidad de un registro depende solo de la bandera `error` y de un tope de plausibilidad; un sensor atascado con `N` no se detecta. El PDF no explica el significado de `periodo_integracion` en términos de validez.
- Ocupación, carga y velocidad no se agregan (la carga es 0 en casi toda la M30; la velocidad solo existe en M30).
- La latencia real de publicación (el portal publica el mes anterior en la primera quincena) no se ha medido: no se afirma tiempo real. Las features usan solo horas terminadas, pero un uso operativo necesitaría datos más recientes que los mensuales.
- Los ficheros de ubicación son una foto mensual: un movimiento dentro del mes no se refleja hasta el mes siguiente.
- Estos datos son la fuente oficial al descargarlos (2026-10-30); el portal puede revisar ficheros ya publicados (sha256 en el manifiesto).

## Reproducción

```bash
export ATLAS_DATA_DIR=/path/to/exfuzzy-atlas/data   # opcional; por defecto <repo>/data
PYTHONPATH=src python -m atlas.domains.air.traffic --months 2023-01:2025-12   # descarga + estudio + horario (~4 min tras la descarga)
PYTHONPATH=src python -m atlas.domains.air.traffic_features --write-spec      # tabla madrid_no2_h6_traffic
```
