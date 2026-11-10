# Prueba de volumen (AT-061, #26)

Qué pasa con la publicación y la API cuando el modelo publicado tiene **más de 1 M de filas de entrada y más de 20 M de
registros de activación**: tiempos, RAM, tamaño en disco, latencia por endpoint (frío, cacheado, concurrente), el coste
del validador de observaciones y qué recomendamos a cada propietario. Todo se mide con un script reproducible
(`scripts/qa/volume.py`) y un presupuesto de regresión opt-in (`tests/integration/test_volume_budget.py`, `make
qa-volume`). Las secciones 1–9 son la **medición original** (código de `main` en `5b25b9b`; no se tocó código); la
sección «Correcciones B1–B6» justo debajo recoge los cambios hechos a partir de ella y las cifras antes/después. Donde
una tabla de §1–§9 describe el comportamiento «de hoy» (un único grupo de filas, 20 000 puntos de serie, comprobación del
directorio entero, caché de 256 entradas, validador sin límite), es el de antes de las correcciones.

## Correcciones B1–B6 (antes y después)

Rama `a0/perf-backend` sobre `main` en `f4da98d`. Mismo modelo sintético de §1 (60 entidades x 730 d, 1 045 440 filas,
20 908 800 registros), mismo script, tamaño 1 M, `--scenarios distinct,no_series_full,hot --seconds 45 --n 30`; «antes» =
`f4da98d` sin cambios, «después» = la rama, ambos publicados y medidos con su propio código. Informe completo:
[`volume_report_b1_b6.json`](volume_report_b1_b6.json).

**Carga de la máquina durante la medición.** La estación de trabajo (12 hilos, compartida con otros agentes y navegadores). Antes:
carga 1/5/15 min al empezar 8,6 / 15,7 / 19,6 y 5,6–8,3 al terminar cada escenario de concurrencia; 6,4 GB de RAM
disponibles. Después: 3,8 / 5,9 / 9,8 al empezar y 5,7–8,2 al terminar; 7,4 GB disponibles. El suelo de FastAPI
(`/health` por `TestClient`) fue 2,4 ms antes y 2,2 ms después, así que las latencias en proceso son comparables; las
cifras de concurrencia dependen más de la CPU libre, por eso se repitió **alternando** código antiguo y nuevo en la misma
ventana (tabla inferior). Todas son cotas con la máquina compartida, no latencias de un servidor dedicado.

| Medida (mezcla completa salvo indicación) | antes | después | factor |
|---|---:|---:|---:|
| `series` sin ventana, p50 en proceso (`series_full`) | 556 ms | **37,9 ms** (página de 2 000 puntos) | 14,7x |
| `series` sin ventana, respuesta | 4 249 KiB (17 424 puntos) | **488 KiB** (2 000 puntos) | 8,7x |
| `series` recorrido completo siguiendo `next_cursor` | 556 ms (1 petición) | 438 ms (9 páginas, 4,2 MiB en total) | 1,3x |
| rule-map `mean_activation` 366 d, p50 | 68,5 ms | **20,9 ms** | 3,3x |
| rule-map `activation_frequency` 366 d, p50 | 74,3 ms | **20,6 ms** | 3,6x |
| rule-map `mean_activation` 30 d, p50 | 15,4 ms | 8,9 ms | 1,7x |
| rule-map `firing_strength`, p50 | 9,5 ms | 7,3 ms | 1,3x |
| concurrencia `distinct`, 1 worker | 28,8 req/s, p95 1 133 ms | **148,6 req/s**, p95 158 ms | 5,2x |
| concurrencia `distinct`, 2 workers | 49,6 req/s, p95 708 ms | **303,7 req/s**, p95 73 ms | 6,1x |
| concurrencia `hot`, 1 worker | 33,2 req/s | 237,2 req/s | 7,1x |
| concurrencia `no_series_full`, 1 worker | 197,6 req/s | 240,2 req/s | 1,2x |
| RSS del servidor tras 45 s de carga, 1 worker | 482 MB | 411 MB | |
| publicación: tiempo / pico de RSS | 7,1 s / 865 MB | 14,9 s / 957 MB | 2,1x más lento |
| activaciones en disco / modelo entero | 10,1 / 48,7 MB | 13,7 / 52,3 MB | +36 % / +7 % |

Comparación alternada (mismas condiciones, 40 s, `distinct`, 1 worker, 8 clientes; `load` 4–8): antes 24,8 y 33,6 req/s
(p95 1 132 y 902 ms); después 193,7 y 175,5 req/s (p95 103 y 116 ms): **≈ 6x**, 0 errores en todas las pasadas.

Aislar la disposición de las activaciones (B3) es posible porque el mismo modelo se copia con la disposición anterior
(`--layouts legacy_time_order`, ordenado por tiempo, un grupo de filas por fichero) y se mide en la misma pasada:

| Mediana sin caché | disposición anterior | ordenada por regla, grupos de 100 k | factor |
|---|---:|---:|---:|
| rule-map `firing_strength` | 9,8 ms | 7,3 ms | 1,3x |
| `mean_activation` 30 d | 13,3 ms | 8,9 ms | 1,5x |
| `mean_activation` 366 d | 52,2 ms | 20,9 ms | 2,5x |
| `activation_frequency` 366 d | 49,6 ms | 20,6 ms | 2,4x |

(§4 midió 3,2x en 366 d con la máquina más cargada.) Con los tres modelos reales republicados (3,15 M, 1,37 M y 0,13 M
de registros; los dos primeros pasan de 1 a 3–9 grupos de filas por fichero) el efecto absoluto es pequeño porque
ya eran decenas de ms; la ganancia crece con el volumen.

### Qué se cambió

| # | Cambio | Dónde | Cómo se comprueba |
|---|---|---|---|
| B1 | `/series`: página de **2 000 puntos** (antes 20 000; `next_cursor` igual, compatible hacia atrás). Los puntos se construyen con `model_construct` y la respuesta se serializa una vez con el núcleo Rust de pydantic (`Response(model_dump_json())`), sin volcar, revalidar y recodificar cada punto en FastAPI; se mantiene la comprobación `valid_at - issued_at == horizon_hours` | `ArtifactStore.series_for`, `main.series`, `docs/api.md` §3 | `tests/api/test_series_page.py`: el JSON valida con `SeriesResponse`, es igual a la construcción validada, paginación, OpenAPI |
| B2 | `make demo` / `demo.sh` con `--workers ${ATLAS_API_WORKERS:-2}`, sin `--reload` (queda en `make api`); `make qa-volume`; documentado que las cachés son por worker | `Makefile`, `scripts/qa/demo.sh`, `docs/api.md` | `tests/integration/test_demo_script.py`; arranque real con 2 workers y petición a `/series` |
| B3 | `publish` escribe cada fichero mensual **ordenado por `(rule_id, issued_at_utc, entity_id)`**, grupos de 100 000 filas, un fichero por mes, mismo esquema Arrow (clasificadores también). DuckDB ordena (con `memory_limit` y `temp_directory` propios) y se vuelca por lotes: la memoria sigue acotada | `publish._write_sorted_activations` | `tests/api/test_activation_layout.py`: orden, tamaño de grupo, poda por estadísticas, esquema, y respuestas de rule-map, territorios e historias **iguales** a las de la disposición anterior reconstruida |
| B4 | La API comprueba solo `model.pkl`, `rules.json` y `card.json` contra `SHA256SUMS` antes de deserializar; el directorio entero lo comprueba `publish` (antes de hacerse visible) y `python -m atlas.services.verify <modelo>` (comprueba también que no sobren ficheros). `artifacts.load_model` (A4) no se toca | `atlas.services.verify`, `_Published.model` | `tests/services/test_verify.py`: `model.pkl`/`rules.json`/`card.json` alterados se rechazan sin llamar a `pickle.load`; la carga solo calcula el hash de esos tres; datos alterados los detecta el comando (salida 1) |
| B5 | Cachés de rule-map, territorios e historias acotadas por **bytes aproximados** (64 MB por worker; `ATLAS_CACHE_MB` o `ArtifactStore(cache_bytes=)`), no por 256 entradas. Una entrada ≈ 6 x su JSON, que es lo que crecen 300 copias de un mapa de 31 KiB y de otro de 499 KiB (6,3x); es una cota conservadora (las geometrías se comparten con la colección de entidades: tras llenar la caché con el presupuesto entero el RSS subió 37 MB con 67 MB contabilizados) | `atlas_api.cache.ByteLRU` | `tests/api/test_cache_bytes.py`: expulsión LRU, contabilidad, entrada mayor que el presupuesto, variable de entorno |
| B6 | `validate_observations(source, memory_limit="1GB", temp_directory=None)` y `validate_observations_partitioned(root)`: una llamada por partición hive. Particiones cuyos rangos `[min, max]` de `timestamp_utc` se solapan se validan **juntas**, así que los duplicados son exactos para cualquier partición; el ahorro de memoria exige que la partición sea función del instante (mes UTC o mes local) | `atlas.contracts.observations` | `tests/contracts/test_observations.py`: duplicados exactos, error con su partición, solape, límite pequeño con volcado a disco |

### Validador sobre Madrid/aire (8 330 457 filas, 85 particiones), `volume.py validator`

| Llamada | tiempo | pico de RSS (línea base 123 MB) |
|---|---:|---:|
| de golpe, `memory_limit` 80 % (antes) | 1,5 s | 1 089 MB |
| de golpe, `memory_limit="1GB"` (nuevo valor por defecto) | 1,1 s | 1 018 MB |
| de golpe, `memory_limit="512MB"` | 0,8 s | 645 MB |
| de golpe, `memory_limit="256MB"` (vuelca a disco) | 1,6 s | 400 MB |
| por año (9 llamadas) | 0,8 s | 339 MB |
| **`validate_observations_partitioned`** (85 llamadas) | 6,2 s | **164 MB** |

**Recomendación a A1/A2/A3:** validar en la ingesta con `validate_observations_partitioned(root)` (pico ≈ 40 MB sobre la
línea base y constante con el tamaño del conjunto) y no con un glob de todo el árbol. El límite de 1 GB por defecto
solo protege de crecer sin tope: con este conjunto (8,3 M de filas, 117 B/fila) el pico de golpe sigue siendo ≈ 1 GB, y un
conjunto mayor vuelca a disco en lugar de crecer (comprobado: con 256 MB el pico es 400 MB).
Si un conjunto no particiona por el instante (p. ej. por entidad), `validate_observations_partitioned` lo detecta por el
solape de rangos y valida todo junto: correcto, pero sin ahorro de memoria.

### Modelos reales republicados

Con `--replace` y las órdenes de `scripts/qa/reproduce.sh` (etapas `madrid-7`, `nyc-7` con `--include-unmodelled-entities`
y `water-5`, todas con `--metadata`) en `artifacts/published` de la copia principal, con el código de la rama. Comprobado
contra una copia de antes: `inputs.parquet`, `predictions.parquet`, `entities.geojson`, `rules.json`, `model.pkl`,
`feature_spec.json` y `card.json` **idénticos byte a byte**; mismas filas de activación (ordenadas por la clave);
`registry.json` y `publish.json` iguales salvo la fecha; 432 consultas de rule-map, territorios e historias idénticas
(valores en coma flotante a 1e-12, por el orden de la suma); `python -m atlas.services.verify artifacts/published`
correcto; `ATLAS_PUBLISHED_DIR=… pytest tests/integration`: 113 passed.

## Cómo reproducirlo

```bash
# Todo (≈ 12 min; ~1 GB de disco en el directorio de trabajo; pico de RSS por proceso medido < 1,4 GB, el del cliente de carga)
PYTHONPATH=src:apps/api python scripts/qa/volume.py all --out <scratch> --report <scratch>/volume_report.json
# 130 entidades (2,27 M filas, 45 M registros: una ventana de 366 d lee > 1 M filas de entrada)
PYTHONPATH=src:apps/api python scripts/qa/volume.py all --out <scratch>_x2 --entities 130 --n 20 \
    --layouts sorted_by_rule --skip real,concurrency,validator --report <scratch>_x2/report.json
# humo (6 entidades x 30 días, 5 s por escenario)
PYTHONPATH=src:apps/api python scripts/qa/volume.py all --smoke --out <scratch>
# presupuesto de regresión (opt-in; construye el modelo en un temporal, ≈ 35 s, o usa ATLAS_VOLUME_DIR=<scratch>/published)
make qa-volume          # = ATLAS_QA_VOLUME=1 python -m pytest tests/integration/test_volume_budget.py -q -rs
# validador sobre el mayor conjunto real, con límite de memoria o por particiones
PYTHONPATH=src:apps/api python scripts/qa/volume.py validator --obs data/processed/air/observations \
    --mode partitioned --memory-limit 1GB --json <scratch>/v.json
```

El informe completo de la medición es [`volume_report.json`](volume_report.json) (las secciones `x2_130_entities` y
`profiles.real_models_v0.4_on_a0x_code` son las pasadas aparte descritas abajo).

`--out` es obligatorio y se rechaza si está dentro del repositorio (nunca se escribe en `artifacts/published`). Cada
etapa corre en su propio proceso (así `ru_maxrss` es el pico de esa etapa) bajo un guardián que aborta si
`MemAvailable` < 2 GB o si el RSS de un proceso (el servidor uvicorn incluye sus workers) pasa de 2,5 GB. `--skip
build,relayout,profile,real,concurrency,validator` reutiliza los JSON de una pasada anterior. El script necesita
`psutil` (no es dependencia del proyecto; está en el entorno principal): sin él el test se salta, no falla.

Qué construye: `build` entrena con el motor ex_fuzzy un modelo de **20 reglas** sobre 3 entidades x 45 días sintéticos y
publica con `atlas.services.publish.publish_run` una tabla sintética de **60 entidades x 730 días horarios**
(`atlas.ml.synthetic.make_synthetic_table`; sin tocar `src`). `relayout` copia ese modelo con otras disposiciones de las
activaciones (ver §4). `profile` mide la API (`ArtifactStore` + `TestClient`, dentro del proceso: sin red, con la
serialización de FastAPI/pydantic). `concurrency` arranca uvicorn y lanza 8 hilos cliente.

## Contexto de la máquina y límites honestos de esta medición

La estación de trabajo: 12 hilos, 15,5 GB de RAM compartida (≈ 6,6 GB disponibles al empezar), 4 GB de swap en uso,
Python 3.12.3, DuckDB 2.0.0, commit base `5b25b9b`. **La máquina estaba cargada por otros trabajos durante toda la
medición** (carga media 1/5/15 min entre 6 y 18 sobre 12 hilos: entrenamiento ML, navegadores, otros agentes).
Consecuencias:

- Las latencias absolutas son **cotas superiores**. Como referencia, `/health` por `TestClient` tarda 2,4 ms con la
  máquina menos cargada (carga ≈ 7; pasada de los perfiles sintéticos de 1 M) y 15–25 ms con carga 17 (la pasada de 130
  entidades y la de modelos reales): léanse las tablas relativas a esa fila.
- El 8x concurrente comparte CPU con esos trabajos; los factores de escala con workers son indicativos.
- Se medía a la vez que otros agentes publicaban: los modelos reales se **republicaron con el contrato 0.4.0 a las
  13:48**, durante la medición. La tabla de modelos reales de §5 usa los artefactos 0.3.0 anteriores (13:42, código de
  `main`) y, aparte, los 0.4.0 ejecutados con el código de la rama `a0/contract-v0.4-creative-backend` (el código de
  `main` ya no los carga: `target_scheme.short_name: extra_forbidden`).
- **Los datos son sintéticos.** El firing del modelo de volumen es 0 exacto en el 96,7 % de los registros (el modelo real
  de Madrid: 73,6 %), así que el disco (0,5 B/registro; el real de Madrid, 0,7 B) y el coste de lectura son los de un
  caso favorable. Para acotar el peor caso se mide también una copia con valores aleatorios (14 B/registro, §4).
- El frío se obtiene con `posix_fadvise(DONTNEED)` sobre los ficheros del modelo (sin root); con ficheros de decenas de
  MB frío y caliente apenas se distinguen. No se han medido discos lentos ni red.
- Un solo modelo en volumen, una sola tarea; no hay contención entre modelos.

## 1. Publicar a escala

| | 60 entidades x 730 d | 130 entidades x 730 d |
|---|---:|---:|
| Filas de entrada | 1 045 440 | 2 265 120 |
| Registros de activación (x 20 reglas) | 20 908 800 | 45 302 400 |
| Tiempo de `publish_run` | 14,8 s (70 800 filas/s; 1,42 M registros/s) | 23,0 s (98 500 filas/s) |
| Pico de RSS (muestreo / `ru_maxrss` de la etapa) | 792 / 792 MB | 921 / 928 MB |
| Disco, modelo publicado | 48,7 MB | 102,0 MB |
|   activaciones (24 / 48 ficheros) | 10,1 MB | 18,6 MB |
|   `inputs.parquet` / `predictions.parquet` | 27,9 / 10,6 MB | 60,8 / 22,5 MB |
| Tabla de features de entrada (Parquet) | 34,9 MB | 76,6 MB |

El pico de RSS lo marca un mes de filas (43 k filas x 20 reglas) y no crece con el periodo: pasar de 1 M a 2,3 M de
filas solo lo sube un 16 %. La publicación **escala bien**: el tiempo es lineal en filas. Con modelos reales el
coste por fila depende del motor ex_fuzzy y de la tabla de features (aquí la tabla es un AR(1) sintético con 4 features).

## 2. API bajo volumen (60 entidades, 1 M de filas, 21 M de registros)

`TestClient` en proceso, `ArtifactStore` por defecto (DuckDB 512 MB / 2 hilos, caché de 256 respuestas). «Frío» = tienda
nueva y ficheros del modelo expulsados de la caché de páginas antes de la primera petición de cada tipo; «sin caché» =
claves distintas (regla, instante o ventana aleatorios) sobre ficheros calientes; «con caché» = misma petición repetida.
Ventanas de 30 y 366 días tomadas al azar dentro de los 730 días. Fuente: `volume_report.json`, perfil
`synthetic_as_published`, n = 30 (15 / 6 para ventanas, 7 para series completas).

| Endpoint | frío ms | sin caché p50 / p95 ms | con caché p50 / p95 ms | respuesta máx. |
|---|---:|---:|---:|---:|
| `/health` (suelo de FastAPI + TestClient) | 7 | 2,4 / 4,5 | n/a | 0,1 KiB |
| domains / card / rules | 7 | 2,8 / 6,2 | n/a | 10,9 KiB |
| rule-map `firing_strength` | 22 | 8,8 / 10,7 | 3,6 / 7,8 | 33,0 KiB |
| rule-map `mean_activation` 30 d | 17 | 14,9 / 18,5 | 3,5 / 8,5 | 31,6 KiB |
| rule-map `activation_frequency` 30 d | 18 | 15,9 / 22,3 | n/a | 31,8 KiB |
| rule-map `mean_activation` 366 d | 70 | 65,1 / 69,5 | n/a | 30,8 KiB |
| rule-map `activation_frequency` 366 d | 67 | 61,3 / 69,5 | 3,5 / 7,1 | 31,9 KiB |
| rule-trace | 76 (incluye cargar el modelo) | 9,7 / 12,1 | n/a | 7,6 KiB |
| series, ventana de 7 días | 11 | 11,9 / 17,5 | n/a | 41,2 KiB |
| **series, rango completo** | 540 | **479 / 543** | n/a | **4 249 KiB** |

RSS del proceso de la API: 271 MB tras importar, 368 MB de pico durante todo el perfil (series completas incluidas);
la caché llena (256 entradas) no se distingue del ruido (± 15 MB) con 60 entidades puntuales (§5: 56–116 MB con las
respuestas de 110–263 entidades reales).

**Qué se lee de aquí**

- Una ventana de 366 d lee ≈ 10,5 M registros de activación (523 k filas de entrada x 20 reglas) en **65 ms**; el límite
  de 366 días es lo que acota el peor caso (366 d = 12 ficheros mensuales). Una ventana de 367 d se rechaza con 422 en
  ≈ 2 ms **antes** de tocar ningún fichero. Con 130 entidades (1,13 M de filas de entrada y 22,7 M de registros por
  consulta de 366 d) la misma consulta sube a ≈ 250 ms con carga 17 (§4).
- **Ningún endpoint devuelve historiales por fila salvo `series`**, y ese está acotado: máx. 20 000 puntos por página
  (`SERIES_MAX_POINTS`, paginado con `next_cursor`). rule-map crece con el **número de entidades** (≈ 0,55 KiB por punto,
  ≈ 1,9 KiB por polígono), no con las filas: 33 KiB con 60 puntos, 155 KiB con las 110 zonas NYC de la medición 0.3,
  504 KiB con las 263 zonas de los artefactos 0.4. La traza pesa 5–13 KiB. La comprobación estructural está en el script
  (`check_bounded`: nº de features ≤ nº de entidades, sin propiedades inesperadas, páginas ≤ 20 000 puntos) y en el test
  (límites de bytes). 0 incumplimientos en todas las pasadas.
- La **primera** traza de cada modelo carga el pickle tras comprobar `SHA256SUMS` de **todo el directorio**, activaciones
  incluidas: 65–76 ms con 49 MB, **370–404 ms** con la copia densa de 340 MB (≈ 0,9 GB/s). Es lineal en el tamaño del
  modelo publicado: con varios GB sería segundos en la primera traza tras cada despliegue (hallazgo B4).

## 3. Concurrencia (uvicorn, 8 clientes, 60 s por escenario)

Mezcla de peticiones: 40 % rule-map `firing_strength`, 12+8 % ventanas de 30 d, 3+2 % de 366 d, 15 % traza, 5 % series
completas, 10 % series de 7 d, 5 % domains/card/rules. «hot»: el 80 % repite alguna de 6 peticiones recientes por tipo
(un usuario moviendo un control sobre pocas vistas); «distinct»: todas con claves nuevas. 0 errores en los 7 escenarios
(≈ 50 000 peticiones). Fuente: perfil `concurrency` / `concurrency_2_workers` del informe.

| Escenario | workers | req/s | p50 ms | p95 ms | p99 ms | RSS servidor tras |
|---|---:|---:|---:|---:|---:|---:|
| hot (mezcla completa) | 1 | 25 | 116 | 1 195 | 4 648 | 479 MB |
| distinct (mezcla completa) | 1 | 27 | 141 | 1 214 | 1 869 | 476 MB |
| distinct **sin series completas** | 1 | 157 | 35 | 171 | 287 | 489 MB |
| hot **sin series completas** | 1 | **310** | **17,5** | 58 | 194 | 471 MB |
| solo ventanas de 366 d (mean y freq) | 1 | 40 | 196 | 237 | 263 | 495 MB |
| distinct (mezcla completa) | 2 | 44 | 43 | 792 | 1 699 | 902 MB (2 procesos) |
| distinct sin series completas | 2 | 226 | 24 | 123 | 216 | 902 MB |

Lo que muestran:

1. **Las series completas mandan.** Son el 5 % de las peticiones y el 66 % del tiempo de servidor (0,05 x 479 ms de
   los 36,5 ms que cuesta de media una petición de la mezcla). 1/36,5 ms = 27 req/s, que es lo que mide el servidor de un
   worker: **el servicio es serie** (la construcción pydantic de 17 500 puntos y el JSON de 4 MB retienen el GIL).
   Quitándolas, el mismo servidor pasa de 27 a 157 req/s y el p95 de 1,2 s a 0,17 s.
2. **La caché de rule-map vale el doble** cuando la CPU no está saturada por las series: 310 req/s con p50 de 12,5–13,7 ms
   en los rule-map (frente a 31–200 ms sin repetir). Con las series presentes su efecto queda tapado por la cola del GIL.
   La clave de caché incluye `time`/`from`/`to`, así que arrastrar un control de tiempo son fallos de caché casi siempre.
3. **Memoria estable.** El servidor de un worker va de 255 MB al arrancar a 470–495 MB y **no crece** durante 5 minutos de
   carga (incluidos 2 400 consultas de 366 d con DuckDB al límite de 512 MB): sin fugas observables. Cada worker adicional
   duplica la huella (≈ 450 MB) y su caché.
4. Dos workers dan 1,6x (mezcla completa) y 1,4x (sin series) en una máquina que ya estaba a carga 12–17 sobre 12 hilos.
5. Una ventana de 366 d con 8 clientes concurrentes: p50 ≈ 196 ms, p95 ≈ 237 ms, 40 req/s (DuckDB paraleliza: 25 ms de
   CPU efectiva por consulta frente a 65 ms en serie).
6. El proceso cliente (generador de carga, no la API) llegó a 0,85–1,3 GB de RSS por decodificar respuestas de 4 MB en 8
   hilos; servidor + cliente < 2,3 GB en el peor escenario. `MemAvailable` mínima vista durante todo: 4,0 GB.

## 4. Disposición de las activaciones (comparativa en el mismo modelo de 21 M de registros)

Hoy `publish` escribe cada trozo en el orden (instante, entidad, regla) y un único grupo de filas por fichero mensual
(892 800 registros), de modo que `WHERE rule_id = ?` no puede podar nada dentro del fichero: se descomprimen las 4
columnas de todo el mes. Se ha copiado el modelo ordenando cada fichero por `(rule_id, issued_at_utc, entity_id)` con
grupos de 100 000 filas (DuckDB `COPY`, solo para esta medición) y, para acotar el peor caso, con valores de firing
aleatorios (no es salida de un modelo). Mediana sin caché, ms, 30 consultas (6 las de 366 d):

| Disposición | activaciones en disco | firing | mean 30 d | mean 366 d | freq 366 d | 1.ª traza (frío) |
|---|---:|---:|---:|---:|---:|---:|
| **tal como se publica** | 10,1 MB | 8,8 | 14,9 | 65,1 | 61,3 | 76 |
| ordenada por `rule_id`, grupos de 100 k | 12,9 MB | **6,5** | **8,1** | **20,5** | **18,6** | 74 |
| valores aleatorios, orden publicado | 300 MB | 15,4 | 21,8 | 87,3 | 91,3 | 404 |
| valores aleatorios, ordenada por `rule_id` | 302 MB | 8,1 | 9,5 | 23,7 | 18,8 | 370 |
| 130 entidades, tal cual (carga 18) | 18,6 MB | 29 | 56 | 273 | 254 | |
| 130 entidades, ordenada (carga 18) | | 32 | 30 | 85 | 80 | |

(Filas de 130 entidades con `/health` a 24 ms: léanse relativas; el resto, con `/health` ≈ 2 ms.) Ordenar por regla
cuesta +28 % de disco con datos sintéticos y da 3,2x en ventanas de 366 d y 1,8x en las de 30 d, con **y sin** datos
densos; el factor se mantiene con 130 entidades (3,2x) y el trabajo pasa de «todo el mes» a «una regla de cada veinte», así que el ahorro absoluto crece con el volumen. La API no
cambia: las consultas ya filtran por regla y tiempo.

## 5. Modelos reales publicados

Mismo perfil (n = 30), `artifacts/published` de solo lectura. Dos pasadas porque se republicaron a mitad de la medición
(ver contexto): **A** = artefactos 0.3.0 con el código de `main` (13:42, carga ≈ 10; `/health` 3,5–20 ms);
**B** = artefactos 0.4.0 con el código de `a0/contract-v0.4-creative-backend` (14:08, carga 17, `/health` 17–22 ms).
Todas las medianas sin caché, ms.

| Tarea | filas / registros / entidades / reglas | firing | mean 30 d | mean 366 d | traza | serie 7 d | serie completa | respuesta rule-map |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Madrid NO2 h6 (A) | 210 072 / 3,15 M / 24 / 15 | 8,8 | 10,4 | 29,3 (364 d) | 38 | 34 | 694 (2,0 MiB) | 14 KiB |
| Madrid NO2 h6 (B) | idem | 23,6 | 33,1 | 73,1 | 34,6 | 22,4 | 517 | 14 KiB |
| NYC pickups h1 (A) | 137 170 / 1,37 M / 110 / 10 | 12,7 | 19,4 | 20,9 (51 d) | 11,4 | 11,0 | 38 (0,3 MiB) | 155 KiB |
| NYC pickups h1 (B) | idem, **263** entidades | 43,4 | 62,5 | 51,0 | 31,2 | 31,5 | 93 | **504 KiB** |
| UK agua DO (A) | 3 316 / 129 k / 195 / 39 | 43,6 | 45,3 | 38,3 | 10,2 | 6,5 | 12 | 112 KiB |
| UK agua DO (B) | idem | 34,8 | 34,8 | 42,3 | 37,9 | 29,8 | 19 | 112 KiB |

Las dos pasadas se midieron con la máquina saturada y no en la misma ventana que su propio `/health` (la fila de agua (A)
tiene un firing de 43,6 ms con un suelo de 19,6 ms; Madrid (A), el suelo en 13 ms y el firing en 8,8): **los valores
absolutos de esta tabla son ruido de carga, no latencias del almacén**. Lo que sí dicen: con 0,13–6,3 M de registros
las consultas de ventana (también las de 364–366 d) cuestan lo mismo que el suelo de FastAPI más unos pocos ms; el
volumen real actual no estresa el almacén. Los (B) y los (A) no son comparables entre sí. RSS de la API tras el perfil
de cada modelo: 330–730 MB, incluidas 256 respuestas en caché: tras llenar la caché con 300 ventanas distintas el RSS
subió **56–86 MB** con las respuestas de 110 polígonos NYC (A) y 195 puntos del agua, y **116 MB** con las de 263
polígonos de NYC (B) (medida con ±15 MB de ruido; la caché se cuenta en entradas, no en bytes). El modelo real más
grande (Madrid, 3,15 M de registros) es 6,6x menor que el de 21 M; los números del §2 bajan casi linealmente hasta ahí.

## 6. Validador de observaciones

`validate_observations` (contrato canónico) sobre el mayor conjunto real: **Madrid/aire, 8 330 457 filas en 85
particiones `year=/month=`** (el de movilidad tiene 2,3 M y el de agua 94 k). El validador crea
`duckdb.connect()` sin límite de memoria (DuckDB usa por defecto el 80 % de la RAM y no vuelca a disco hasta superarlo) y
su comprobación de duplicados agrupa por la clave de 5 columnas.

| Cómo se valida | filas | tiempo | pico de RSS (línea base 121 MB) |
|---|---:|---:|---:|
| de golpe, `**/*.parquet` (como hizo A1) | 8 330 457 | 0,8–2,0 s | **1 100 MB** |
| los 48 primeros meses | 4 880 127 | 0,5 s | 710 MB |
| los 24 primeros meses | 2 560 555 | 0,3 s | 467 MB |
| **por año** (9 llamadas) | 8 330 457 | 1,1 s | **321 MB** |
| **por partición mensual** (85 llamadas) | 8 330 457 | 4,2–8,0 s | **160 MB** |

La memoria es lineal: ≈ **117 B por fila** (consistente con el pico de 1,7 GB sobre 10 M de filas de A1, con otra tabla):
30 M de filas serían ≈ 3,6 GB y 100 M ≈ 12 GB, es decir, el validador de golpe no escala ni cabe en la estación de trabajo con otros
trabajos. Por partición el pico es constante. El coste de validar por partición es tiempo (la apertura de una conexión y
una decena de consultas por llamada: 4–5x más lento en reloj, aún 1–2 M filas/s). **Recomendación:** validar **por año o por mes**
en la ingesta (pico de 0,16–0,32 GB y sigue siendo segundos). La comprobación de duplicados por partición sigue siendo
exacta mientras la partición sea función de `timestamp_utc`, que forma parte de la clave: aire particiona por mes UTC;
movilidad por mes **local** de Nueva York (13 676 filas de las primeras horas del mes siguiente en UTC viven en la
partición anterior), lo que también es función de `timestamp_utc`. Si alguna vez se parte por otra cosa, hace falta una
comprobación global aparte sobre la clave. No se ha cambiado el código del contrato.

## 7. Hallazgos, evidencia y propietarios

| # | Hallazgo | Evidencia | Propietario / recomendación |
|---|---|---|---|
| B1 | **`/series` sin ventana devuelve hasta 20 000 puntos (4,2 MiB, 480 ms)** y es el 66 % del tiempo de servidor de la mezcla; con un worker limita todo el servicio a ≈ 27 req/s | §2, §3 (27 → 157 req/s al quitarlo; p95 de 1,2 s a 0,17 s) | A0 / backend (`apps/api`, `ArtifactStore.series_for`): página por defecto mucho menor (p. ej. 2 000–5 000) o `from` obligatorio, construir la respuesta sin un objeto pydantic por punto (DuckDB `to_json` / orjson), gzip. A5: pedir ventanas, no el rango completo |
| B2 | La API sirve **en serie** con un worker (GIL) | §3: req/s = 1 / tiempo medio de servicio | A0 / despliegue: `--workers 2–4` (≈ 450 MB y una caché por worker) y, si se prefiere, un único proceso con `orjson`. Aceptar la caché por worker: las consultas costan decenas de ms |
| B3 | Las activaciones se publican sin poder podar por `rule_id` | §4: ordenar por regla da 3,2x en 366 d y 1,8x en 30 d, y crece con el volumen | A0 (`atlas.services.publish._write_views`; solo cambia el orden de filas y el tamaño de grupo, el contrato no cambia): ordenar cada fichero mensual por `(rule_id, issued_at_utc, entity_id)`, grupos de 100 k. No urgente con los volúmenes reales actuales (≤ 6,3 M registros); necesario antes de ≈ 50 M |
| B4 | La **primera** traza por modelo verifica el SHA-256 de **todo** el directorio (activaciones incluidas) | §2: 65 ms con 49 MB, ≈ 400 ms con 340 MB; lineal | A0 (`ArtifactStore._Published.model`) con A4 (`artifacts.load_model`): comprobar solo `model.pkl` (y `rules.json`) contra `SHA256SUMS` al cargar y dejar la verificación completa para `publish`/CI. Es un cambio de seguridad: decisión humana |
| B5 | El tamaño de rule-map sigue al **nº de entidades x geometría** (504 KiB con 263 zonas NYC); 256 respuestas cacheadas ≈ 56–116 MB por proceso | §2, §5 | A0 (contrato/API): caché con tope en bytes; a medio plazo, no repetir la geometría en cada mapa (contrato v0.5: el cliente ya la tiene de `/entities`). No es un problema de filas |
| B6 | `validate_observations` de golpe: 117 B/fila, sin límite de memoria | §6 | A0 (`atlas.contracts.observations`): fijar `SET memory_limit` y `temp_directory` en su conexión; A1/A2/A3: llamarlo por año o mes en la ingesta |
| B7 | La clave de caché incluye el instante/ventana: arrastrar un control de tiempo no reutiliza caché | §3 (hot vs distinct) | A5/A0: precalentar o cuantizar `time` en la UI; la caché de 256 entradas está bien dimensionada (≤ ≈ 120 MB con respuestas reales) |
| B8 | Los artefactos reales se republicaron a 0.4.0 y `main` ya no los carga | §contexto | A0: normal hasta que se mezcle la rama del contrato 0.4; el script informa `failed` en esa etapa y no aborta |

**Estado tras AT-061** (rama `a0/perf-backend`): B1, B2, B3, B4, B5 y B6 hechos (ver «Correcciones B1–B6» arriba); B4 fue
decisión de A0 (la comprobación completa pasa a `publish` y a `python -m atlas.services.verify`). Siguen abiertos B7
(cuantizar `time` en la UI) y B8 (normal hasta mezclar el contrato 0.4), y el cambio de contrato v0.5 de B5 (no repetir la
geometría en cada mapa). El cliente web ya sigue `next_cursor` (hasta 20 páginas = 40 000 puntos con la página nueva).

Lo que **no** es un cuello de botella a este volumen: la consulta del almacén (65 ms para 10 M de registros, 20–25 ms
ordenada), la memoria del servidor (plana en 5 min de carga), el pico de RAM de la publicación (≤ 0,93 GB), ni el tamaño
de las respuestas de los mapas con 60 entidades.

## 8. Presupuesto de regresión (opt-in)

`tests/integration/test_volume_budget.py` se salta salvo `ATLAS_QA_VOLUME=1` (y sin `psutil`), así que `make test` y la
CI no cambian. Construye el modelo de 60 x 730 x 20 (o usa `ATLAS_VOLUME_DIR`) y exige: más de 1 M de filas y 20 M de
registros; la **mediana de 10 peticiones sin caché** por debajo de un presupuesto (≈ 5x lo medido, para cazar órdenes
de magnitud y no ruido); tamaño de respuesta acotado e independiente de las filas; ventana de 367 d rechazada en
< 100 ms; la respuesta cacheada idéntica y no más lenta; y RSS del proceso < 2,5 GB.

| Endpoint | presupuesto (mediana) | medido (p50, máquina cargada) |
|---|---:|---:|
| rule-map firing | 50 ms | 8,8 |
| rule-map 30 d (mean / freq) | 100 ms | 15–16 |
| rule-map 366 d (mean / freq) | 400 ms | 61–65 |
| rule-trace | 150 ms | 9,7 |
| series 7 d | 100 ms | 11,9 |
| series sin ventana (página de 2 000 puntos) | 250 ms (era 2 500 con 20 000 puntos) | 38 (era 479) |
| domains / card / rules | 50 ms | 2,8 |

`ATLAS_VOLUME_BUDGET_SCALE=2` los duplica en una máquina más lenta; `ATLAS_VOLUME_ENTITIES` / `ATLAS_VOLUME_DAYS`
construyen un modelo menor (el test de tamaño se salta). Pasa en la estación de trabajo con la máquina a carga 17 (13 tests, 16 s con
`ATLAS_VOLUME_DIR`, 34 s construyéndolo). `make qa-volume` lo lanza; tras AT-061 son 16 tests (paginación de `series`,
disposición por regla con grupos de filas y caché acotada en bytes), 16 s en la estación de trabajo con carga 8, y pasan.

## 9. Siguiente paso

1. ~~B1 y B2 antes de poner la API detrás de más de un usuario; B4 antes de publicar modelos de varios GB.~~ Hecho (AT-061, rama `a0/perf-backend`).
2. ~~Repetir §3 con los artefactos reales en `main`.~~ Hecho el 2026-11-05 (§10), con el contrato v0.5.2.
3. ~~Medir con un modelo real de ≥ 20 M de registros.~~ Hecho (§10): Alemania NO₂ h6, 57,4 M de registros.

## 10. Modelos reales con el contrato v0.5.2 (2026-11-05)

`main` en `971be00`; los cuatro modelos servidos de QA en un directorio con su `registry.json` (enlaces a
`artifacts/published`, de solo lectura). Estación de trabajo compartida: carga 1/5/15 de 3,1 / 3,9 / 3,3 al terminar el perfil y
5,3 / 4,4 / 3,5 al terminar la concurrencia; 7,0 GB disponibles como mínimo. Informe:
[`volume_report_real_v052.json`](volume_report_real_v052.json).

```bash
PYTHONPATH=src:apps/api python scripts/qa/volume.py profile --published <dir> --label real_models_v052 --n 30 --json p.json
PYTHONPATH=src:apps/api python scripts/qa/volume.py concurrency --published <dir> --task-id de_no2_h6 --clients 8 --seconds 60 --workers 1 --json c1.json
PYTHONPATH=src:apps/api python scripts/qa/volume.py concurrency --published <dir> --task-id de_no2_h6 --clients 8 --seconds 60 --workers 2 --scenarios distinct,no_series_full --json c2.json
```

**Alemania es el primer modelo real por encima de 20 M de registros**: 3 825 061 filas de entrada, **57 375 915**
activaciones, 437 estaciones, 15 reglas, 8 753 horas de emisión en 364,7 d. Medianas sin caché en proceso (n = 30; las
ventanas de 366 d, n = 6), ms:

| Tarea | filas / registros / entidades / reglas | firing | mean 30 d | mean 366 d | freq 366 d | traza | serie 7 d | serie completa (todas las páginas) | respuesta rule-map |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Alemania NO₂ h6 | 3,83 M / **57,4 M** / 437 / 15 | 19,6 | 25,3 | 84,0 | 87,2 | 19,2 | 11,2 | 270 (5 páginas, 2,0 MiB) | 241 KiB |
| Madrid NO₂ h6 | 210 072 / 3,15 M / 24 / 15 | 6,4 | 7,7 | 13,7 | 12,9 | 9,8 | 7,7 | 193 (5 páginas) | 14 KiB |
| NYC pickups h1 | 137 170 / 1,37 M / 263 / 10 | 24,1 | 25,2 | 24,6 (51 d) | 25,0 | 9,0 | 7,7 | 27 (1 página) | 504 KiB |
| UK agua DO | 3 316 / 129 324 / 195 / 39 | 11,0 | 11,3 | 13,8 | 13,6 | 9,7 | 5,0 | 5,6 (1 página) | 110 KiB |

Suelo de FastAPI (`/health`, p50) 2,3–3,1 ms. Con caché, rule-map de Alemania en 5,1–5,5 ms. Una ventana de 367 d se
rechaza (422) en 2,6–4,9 ms. El pico de RSS del proceso con los cuatro modelos cargados fue 682 MB; tras 300 ventanas
distintas por modelo la caché quedó en su presupuesto de 64 MiB en todos (cuenta en bytes desde B6).

Frente al sintético de 21 M (§«Correcciones B1–B6», 60 entidades): 2,7x registros y 7,3x entidades cuestan 4x en la
ventana de 366 d (84 frente a 20,9 ms) y 2,7x en `firing_strength` (19,6 frente a 7,3 ms): el coste crece con el número
de entidades (el tamaño de la respuesta, 241 KiB frente a ≈ 30 KiB) más que con los registros.

Concurrencia sobre Alemania (uvicorn, 8 clientes, 60 s por escenario, 0 errores en los 7):

| Escenario | workers | req/s | p50 ms | p95 ms | p99 ms | RSS servidor tras |
|---|---:|---:|---:|---:|---:|---:|
| hot (mezcla completa) | 1 | 116 | 42 | 236 | 388 | 539 MB |
| distinct (mezcla completa) | 1 | 58 | 105 | 322 | 480 | 533 MB |
| distinct sin series completas | 1 | 63 | 94 | 304 | 457 | 499 MB |
| hot sin series completas | 1 | 127 | 40 | 236 | 369 | 554 MB |
| solo ventanas de 366 d | 1 | 72 | 17 | 414 | 498 | 570 MB |
| distinct (mezcla completa) | 2 | 101 | 56 | 243 | 316 | 978 MB (2 procesos) |
| distinct sin series completas | 2 | 110 | 50 | 235 | 293 | 929 MB |

Lo que muestran:

1. **El volumen real cabe.** 57 M de registros no rompen ningún presupuesto: ventanas de un año por debajo de 100 ms en
   proceso, memoria estable (< 0,6 GB por worker tras 5 min de carga) y respuestas acotadas por el número de entidades.
2. **Con muchas entidades, el cuello es la respuesta, no la lectura.** Las series completas ya no mandan (B1): quitar
   las series apenas cambia `distinct` (58 → 63 req/s). Lo que pesa son los rule-map de 437 puntos (241 KiB): con
   claves nuevas, p50 de 94 ms en `firing` bajo carga frente a 25 ms cuando la petición se repite (`hot`, caché).
3. Dos workers dan 1,7x en `distinct` (58 → 101 req/s) y doblan la memoria, como en §3.
4. En «solo ventanas de 366 d» la mediana de `mean_activation` (10,6 ms) sale de la caché y la de
   `activation_frequency` (233 ms) no; el p95 de 414 ms es el de las consultas que leen el año entero con 8 clientes a la
   vez.
5. Límite honesto: una sola máquina compartida y una sola pasada por escenario; las cifras son cotas, no latencias de
   un servidor dedicado.

