# Reproducción local

`PYTHON` es `python` por defecto. En una máquina nueva: `pip install -e ".[dev]"` y luego `make <target>` (o
`make <target> PYTHON=<intérprete>` para usar otro).

## Dependencia de ex_fuzzy desde el contrato v0.8: ex-fuzzy 3.5.0

`pyproject.toml` fija desde v0.8 `ex-fuzzy==3.5.0` (PyPI): el código del commit `7a0844a` (PR 45: condiciones ordinales
«al menos / como mucho» y términos compuestos, `docs/ml/ordinal_conditions.md`) más el cambio de versión (`diff -r` de los
dos árboles `ex_fuzzy/`: solo `_version.py`). Con las opciones apagadas es bit a bit la 3.4.0. Los cuatro modelos que usan
esas condiciones se ajustaron con `7a0844a` y lo registran (`3.4.0+g7a0844a`); sus tablas se recalculan con la 3.5.0 sin
ninguna diferencia (`python -m atlas.ml.publish_parity --tables`). Lo que sigue de esta sección (3.4.0) sigue valiendo
para los modelos anteriores.

## Dependencia de ex_fuzzy desde el contrato v0.7: ex-fuzzy 3.4.0

Los clasificadores de la demo usan la inferencia «mezcla de reglas» (`inference='mixture'`, PR 44 de ex-fuzzy). La
primera versión publicada que la tiene es **ex-fuzzy 3.4.0** (PyPI; etiqueta `v3.4.0` = commit `10d811b`), y
`pyproject.toml` la fija:

    ex-fuzzy==3.4.0

La CI (`pip install -e ".[dev]"`) la instala y también el entorno de desarrollo. Su código es el del commit `5409bb8` de la
rama del PR (`git diff 5409bb8 v3.4.0` solo toca `_version.py` y el changelog), con el que se hicieron las
comprobaciones de abajo; antes, mientras no había versión, `pyproject.toml` fijaba ese commit (y, antes, `20c1095`).

- `5409bb8` (2026-11-09) es `20c1095` más la poda de la búsqueda bajo la mezcla por el papel de cada regla en ella
  (`mixture_pruning`, `docs/ml/rule_mixture_serve.md` §8). Comprobado con él: los 18 modelos servidos (los diez de antes de
  v0.7 y los ocho de mezcla de v0.7, ajustados con `20c1095`) cargan y reproducen bit a bit sus tablas de activación y sus
  predicciones publicadas (562 M de registros de activación y 39,2 M predicciones, ninguno distinto;
  `python -m atlas.ml.publish_parity --tables <modelo>`; `artifacts/mixture-serve-logs/tables_*_5409bb8*.json`,
  y los de la máquina grande). Antes, con `20c1095`, lo mismo para los diez modelos de antes de v0.7 (246 M de registros,
  19,7 M predicciones).
- `exfuzzy_version()` registra `3.4.0` con la versión de PyPI y `3.4.0+g<commit>` desde un checkout (`EXFUZZY_SRC`). Cada
  modelo conserva la versión con la que se ajustó: `3.3.1+g20c1095` las ocho mezclas servidas, `3.3.1` el de regla ganadora
  de Nueva York +6 h, `3.3.1+g2ffcfb9` el de Water. Nada compara esa versión con la instalada: las trazas que la API
  calcula llevan en `inference.exfuzzy_version` la versión instalada (la que las calculó).
- **Otro ex_fuzzy:** `EXFUZZY_SRC=<checkout>` lo antepone al `PYTHONPATH` de **todos** los objetivos del Makefile (y de
  `scripts/qa/demo.sh`) y su commit queda en cada manifiesto:

  ```bash
  make test EXFUZZY_SRC=$PWD/ex-fuzzy        # también fixtures, api, api-artifacts, demo, qa, reproduce
  make exfuzzy-info                          # <ruta de ex_fuzzy> 3.4.0
  ```

  Las fixtures sintéticas registran la versión importada: se regeneran con la de PyPI (sin `EXFUZZY_SRC`), como en la CI.
- **Máquina grande sin Internet:** un venv existente en solo lectura y el código de ex-fuzzy copiado con `rsync`, como en
  AT-041i (`docs/ml/rule_mixture_serve.md`).

| Comando | Qué hace |
|---|---|
| `make test` | pytest: contratos, validador de observaciones, paridad de fixtures y API mock |
| `make lint` | ruff |
| `make schemas` | regenera `src/atlas/contracts/schemas/*.schema.json` |
| `make fixtures` | regenera `fixtures/synthetic/` con el motor ex_fuzzy fijado |
| `make api` | API mock en http://127.0.0.1:8000 (`/docs` para OpenAPI) |

Ejemplo de consulta:

```bash
curl 'http://127.0.0.1:8000/api/v1/rule-map?model_id=synthetic-no2-h6-v0&rule_id=R01&metric=firing_strength&time=2025-01-15T08:00:00Z'
```

## Datos

| Comando | Qué hace |
|---|---|
| `PYTHONPATH=src python -m atlas.domains.air.ingest --years 2019-2025` | AT-010: aire horario de Madrid y estaciones oficiales. Descarga a `Datasets/madrid-air*` y escribe `data/processed/air/` (unos 35 s) |

| `PYTHONPATH=src python -m atlas.domains.mobility.ingest --months 2024-04..2025-03` | AT-030: taxi amarillo de NYC (12 meses, 42,8M viajes) y zonas oficiales (completa y simplificada). Escribe `data/processed/mobility/` (unos 13 s, 1,2 GB de RSS). `--download-only` y `--skip-download` |
| `PYTHONPATH=src python -m atlas.domains.mobility.features --write-spec --eda` | AT-031: tabla `nyc_pickups_h1` (110 zonas × 8.760 horas de emisión), `configs/mobility/feature_spec.json` y EDA (unos 3 s) |

| `PYTHONPATH=src python -m atlas.domains.air.meteo --years 2019-2025` | AT-011: meteorología horaria de Madrid. Escribe `data/processed/air/meteo/` (unos 24 s; la primera descarga tarda unos 10 min por el límite del portal) |
| `PYTHONPATH=src python -m atlas.domains.air.features` | AT-011: tabla de features y target `madrid_no2_h6` con la asociación meteo y la ficha de features. Escribe `data/processed/air/features/madrid_no2_h6/` (unos 4 s, 1,8 GB de RSS) |
| `PYTHONPATH=src python -m atlas.domains.air.traffic --months 2023-01:2025-12` | AT-012: tráfico de Madrid. Descarga 3,1 GB (unos 9 min por el límite del portal), cruza los puntos de medida con las estaciones y escribe `data/processed/air/traffic/` (unos 4 min, 1 GB de RSS). Opciones: `--download-only`, `--skip-download`, `--association-only` |
| `PYTHONPATH=src python -m atlas.domains.air.traffic_features --write-spec` | AT-012: tabla `madrid_no2_h6_traffic` (se une 1:1 con `madrid_no2_h6`; 2023-2025) y `configs/air/feature_spec_traffic.json` (unos 3 s) |

| `PYTHONPATH=src python -m atlas.domains.water.ingest --counts` | AT-020: descarga paginada (unas 125 peticiones, 1 min) y Parquet en `data/processed/water/`. `--skip-download` normaliza desde la caché sin red |
| `PYTHONPATH=src python -m atlas.domains.water.profile` | AT-020: perfil de la muestra en `docs/water/profile.md` |
| `PYTHONPATH=src python -m atlas.domains.water.features --write-spec` | AT-021: tabla `uk_water_do` (oxígeno disuelto inferido de la misma muestra; 14.025 filas), `configs/water/feature_spec.json` y splits por fecha y por puntos (unos 2 s) |

Detalles en `docs/air/README.md`, `docs/mobility/README.md` y `docs/water/README.md`.

## ML

| Comando | Qué hace |
|---|---|
| `PYTHONPATH=src python -m atlas.ml demo` | Run sintético de extremo a extremo: split, baselines, ex_fuzzy, artefactos |
| `PYTHONPATH=src python -m atlas.ml.benchmark --sizes 10000 50000 --n-gen 20 --pop-size 30` | Coste del fit de ex_fuzzy |

Detalles en `docs/ml/exfuzzy_api_notes.md`.

AT-041i (inferencia «mixture of rules», ex-fuzzy PR 44, sin publicar): `python -m atlas.ml.experiment_mixture arms|decide|final --test|report --config configs/ml/<tarea>_mixture_experiment.json` con `EXFUZZY_SRC` delante en `PYTHONPATH`; protocolo y resultados en `docs/ml/rule_mixture.md`.

AT-041j (la mezcla en los nueve clasificadores de la demo, contrato v0.7): `python -m atlas.ml.experiment_mixture arms|decide|final --test|runs --config configs/ml/<tarea>_mixture_serve_experiment.json [más configs]`; protocolo, resultados, comandos de publicación y paridad en `docs/ml/rule_mixture_serve.md`.

Publicar el modelo servido de Madrid +6 h (AT-041h, desde el 2026-11-06: «NO₂ ayer a la hora de validez», reglas sin
peso; `docs/ml/madrid_no2_h6_ica_v4.md` §9.6). El modelo anterior (`ica2-justified-seed0`) sigue en
`artifacts/published` y se publicaba con el mismo comando y su `--run-dir`:

```bash
R=$PWD; PYTHONPATH=src:apps/api ATLAS_DATA_DIR=$R/data ATLAS_ARTIFACTS_DIR=$R/artifacts \
python -m atlas.services.publish --run-dir $R/artifacts/madrid_no2_h6/ica4-yday-seed1 \
  --features $R/data/processed/air/features/madrid_no2_h6/table --entities $R/data/processed/air/stations.geojson \
  --feature-spec configs/ml/madrid_no2_h6_feature_spec.json --from 2025-01-01T00:00:00Z --to 2026-01-01T00:00:00Z \
  --task-id madrid_no2_h6 --title "Madrid air quality" --metadata configs/air/attribution.json \
  --territory madrid --territory-title Madrid --published-dir $R/artifacts/published
python -m atlas.ml.publish_parity $R/artifacts/published/exfuzzy-madrid_no2_h6-ica4-yday-seed1   # paridad con ex_fuzzy
```

NYC y Water: ver `docs/ml/nyc_pickups_h1_level_ica.md` y `docs/ml/water_uk_do_regression.md`. Desde el contrato v0.4 hay que añadir `--metadata configs/<dominio>/attribution.json`, y en NYC además `--include-unmodelled-entities` (sirve las 263 zonas; 153 quedan como «sin modelo»). La cadena completa de las tres tareas está en `scripts/qa/reproduce.sh` (`make reproduce`).

## ex_fuzzy de integración local (modelos ajustados con correcciones aún sin publicar)

> Histórico (antes de v0.7). Desde v0.7 la dependencia es ex-fuzzy 3.4.0 (antes los commits `20c1095` y `5409bb8`, sobre ex-fuzzy `main`,
> que ya contiene los PR #29, #30, #31, #32, #34 y #35); el modelo de Water servido se ajustó con `2ffcfb9` y con
> `20c1095` reproduce sus tablas bit a bit.

Decisión del autor (2026-10-31): hasta que exista una versión de `ex_fuzzy` con las correcciones, Atlas **ajusta con la
construcción local y puede publicar modelos ajustados con ella**. Entonces el entorno principal conservaba el `ex_fuzzy` 3.3.1 de
PyPI y `make test`, `make lint` y la CI seguían con él (desde v0.7, 3.4.0: arriba); **no se instalaba `ex_fuzzy` con pip
en ningún sitio**. La construcción se
usa solo con `PYTHONPATH`, y `EXFUZZY_SRC` (Makefile) la antepone en los comandos que ajustan o publican:

```bash
make fit-water-unique publish-water-unique EXFUZZY_SRC=/ruta/a/ex-fuzzy-integracion \
  ATLAS_DATA_DIR=<repo principal>/data ATLAS_ARTIFACTS_DIR=<repo principal>/artifacts   # vacío = la biblioteca fijada
make exfuzzy-info EXFUZZY_SRC=/ruta/a/ex-fuzzy-integracion   # <ruta de ex_fuzzy> <versión que Atlas registra>
```

**Qué construcción ajustó cada modelo.** Hay dos construcciones, y la versión que registra el modelo dice cuál:

| construcción | contenido | modelos |
|---|---|---|
| `2ffcfb9` (`3.3.1+g2ffcfb9`) | `c52fdb8` (origin/main + PR #30) + PR #27, #29, #31, #32 | el modelo de Water servido (`exfuzzy-uk_water_do-fx-w-unique-seed0`) y los ajustes del documento FX (Madrid y NYC no publicados) |
| `915b836` (`3.3.1+g915b836`) | `2ffcfb9` + PR #35 (mapa proporcional de términos; contiene el #32) + PR #34 (diagnóstico de estabilidad del conjunto de reglas) | actual; los ajustes de FX2 (`docs/ml/fx2_proportional_remap.md`). Todavía no hay un modelo publicado con ella |

El #35 no cambia los ajustes de Water (el decodificador de regresión no usa el mapa) ni ningún ajuste cuyas variables tengan todas el
mismo número de términos (la identidad); sí cambia los de clasificación con variables de 3 y 4 términos, por eso el modelo de Water de
`2ffcfb9` sigue siendo el servido y la receta de `2ffcfb9` se conserva abajo. Un modelo nuevo ajustado con `915b836` registra
`3.3.1+g915b836`.

**Recrear la construcción** (`atlas/local-integration`; la actual está en `915b836`, la anterior en `2ffcfb9`):

```bash
git clone https://github.com/Fuminides/ex-fuzzy.git ex-fuzzy-integracion && cd ex-fuzzy-integracion
git checkout -b atlas/local-integration c52fdb8                       # origin/main + PR #30 (unique_antecedents)
echo 'docs/source/changelog.rst merge=union' >> .git/info/attributes  # el changelog de cada PR añade líneas en el mismo sitio
for b in warn-no-rule-fires store-pruning-tolerance trapezoid-from-breakpoints fix-term-index-bound; do
  git merge --no-edit origin/atlas/$b; done                          # PR #27, #29, #31, #32, en este orden
git rev-parse HEAD:ex_fuzzy HEAD:tests     # 2ffcfb9: 1b85703175eed2076db094cc737bda881b816a52 / 4bf1352a11068fa170314bd1b8006649a9bea29b
for b in proportional-term-remap rule-set-stability; do
  git merge --no-edit origin/atlas/$b; done                          # PR #35 (contiene el #32; va después de él) y PR #34
git rev-parse HEAD:ex_fuzzy HEAD:tests     # 915b836: 7890c838457be048c88c04e84594b64d844e01d5 / 7b9e959027210d1724f5622cf5c6abfb0dd4d5a4
```

Las seis ramas están en GitHub (`Fuminides/ex-fuzzy`, PR #27, #29, #31, #32, #35 y #34; la #30 ya está en `c52fdb8`) y la construcción no se sube. Para `2ffcfb9` basta parar tras el primer bucle. Sin la línea de
`attributes` el changelog da un conflicto de contenido (solo ahí); se resuelve conservando las líneas de las dos partes. Los
hashes de los commits de fusión no se pueden reproducir (llevan fecha), por eso **la comprobación es el código**: los hashes de
árbol de `ex_fuzzy/` y `tests/` de arriba son los de `2ffcfb9` y `915b836` (el segundo par se recalculó rehaciendo la receta en un clon limpio,
sin conflictos, 2026-10-31) y salen iguales en cualquier orden de fusión (solo `docs/source/changelog.rst` difiere). `ex_fuzzy.__version__` sigue diciendo `3.3.1`, así que la versión no prueba nada:
`atlas.ml.exfuzzy_features` detecta qué hace la biblioteca (`has_term_bound_fix`, `has_unique_antecedents`,
`has_breakpoint_partition`, `has_proportional_term_remap`) y los experimentos que las necesitan se niegan a correr sin ellas.

**Qué registra Atlas.** Todo sitio que graba la versión (`run_manifest.json`, `card.json`, el bloque `inference` de
`rules.json`) llama a `atlas.ml.exfuzzy_features.exfuzzy_version()`. Si el `ex_fuzzy` importado es un checkout de git (la raíz
del repositorio contiene la carpeta `ex_fuzzy` importada) registra una versión local PEP 440 con el commit leído en ese
momento: `3.3.1+g915b836`, o `3.3.1+g915b836.dirty` si el árbol de trabajo tiene cambios sin confirmar o ficheros sin
seguimiento. Una instalación de PyPI registra `3.3.1`, como los artefactos ya publicados. Además el manifiesto (y la ficha del
modelo) lleva un aviso con `exfuzzy_source`, el commit y cómo reconstruirlo, y `hyperparameters.exfuzzy_source` /
`exfuzzy_module_path`. Un checkout no se distingue de una publicación con etiqueta de versión: cuando haya una versión, se
fija en `pyproject.toml` y esta sección se sustituye. El commit es el del checkout, no el hash de fusión que se reproduciría
(véase arriba): a igual `ex_fuzzy/` el modelo es el mismo.

## Explicación del modelo (contrato v0.6.2)

Después de publicar o republicar un modelo servido, se escribe la explicación de sus reglas que sale en Patrones
(«Qué hacen estas reglas»):

```bash
make explain MODEL_ID=exfuzzy-madrid_no2_h6-ica4-yday-seed1                        # escribe configs/explanations/<id>.json
make explain MODEL_ID=exfuzzy-madrid_no2_h6-ica4-yday-seed1 EXPLAIN_ARGS=--dry-run  # solo imprime el prompt
```

`scripts/explain_model.py` construye un JSON de contexto solo con los ficheros publicados del modelo (`rules.json`,
`importance.json`, las métricas de `card.json`, `summary.json` y `registry.json`), con cada cifra ya escrita como la
muestra la web (`display`: «0,41» / "0.41", «24 %» / "24%") y la comparación del Informe de rendimiento con su veredicto
(mejor / a la par / peor) ya calculado. Llama a Claude con la CLI de Claude Code en modo headless (`claude -p`, salida
JSON con esquema, sin herramientas, `--permission-mode dontAsk`, `--safe-mode`, en un directorio vacío), con la
plantilla `configs/explanations/TEMPLATE.md` seguida de ese contexto. Antes de guardar valida la respuesta: esquema y
límites de la plantilla, auditoría de redacción (`scripts/qa/wording_audit.py` y la guarda de Patrones de la web), que
cada número sea uno de los `display` del contexto (±1 en la última cifra) y que las reglas citadas existan. Si falla,
lo intenta una vez más con los errores; si vuelve a fallar no escribe nada y sale con código 1. `--model <modelo>` elige
el modelo de Claude (por defecto, el de la CLI).

El fichero queda con `reviewed: false` y se commitea. Una persona lo lee contra las reglas y métricas antes de marcarlo
`reviewed: true`. Si hay que corregirlo, se regenera; los números no se editan a mano. `make qa`
(`tests/integration/test_explanations.py`) falla si un modelo servido no tiene explicación o si su `input_sha256` ya no
coincide con el contexto que sale de los ficheros publicados actuales (un modelo republicado con la explicación vieja).
La API la lee de `configs/explanations/` (`ATLAS_EXPLANATIONS_DIR` para otro directorio).

La plantilla tiene secciones aparte para los clasificadores de mezcla de reglas (contrato v0.7, `rule_mixture_classifier`:
las reglas suman su apoyo a cada categoría y ninguna decide sola) y para las reglas con condiciones ordinales o compuestas
(contrato v0.8: «al menos» / «como mucho» y términos compuestos; el contexto añade `operator` y `covers` solo a esas
condiciones, así que el de un modelo sin ellas no cambia). El script describe las dos. Al reentrenar un modelo, su
explicación queda desfasada (`input_sha256`) y hay que regenerarla.

## Demo y QA

| Comando | Qué hace |
|---|---|
| `make demo` | Sirve los modelos publicados (API en modo artifacts en el puerto 8000 + web en el 4173). Ctrl-C para los dos |
| `make qa` | Tests de integración sobre los modelos publicados y auditoría de redacción |
| `make qa-web` | Smoke con Chrome headless y capturas |
| `make qa-volume` | Prueba de volumen opcional (≥ 1M filas, presupuestos de latencia); ver `docs/qa/volume.md` |
| `make export-static OUT=<dir>` | Exporta los modelos publicados como ficheros JSON gzip para un sitio estático (formato en `docs/static_export.md`; Alemania solo ene-mar 2025; `ARGS="--base <export anterior>"` reexporta solo lo que cambió). Escribe `data/<export_id>/` y `golden/<export_id>/` |
| `PYTHONPATH=src python -m atlas.services.verify artifacts/published` | Verifica los `SHA256SUMS` completos de los modelos publicados. Al cargar, la API solo verifica `model.pkl`, `rules.json` y `card.json`; conviene ejecutarlo tras copiar o desplegar |

`make demo` arranca la API con 2 procesos (`ATLAS_API_WORKERS`) y cada proceso tiene su propia caché, acotada a `ATLAS_CACHE_MB` (64 MB por defecto).

Detalles y checklist del MVP en `docs/qa/README.md` y `docs/qa/mvp_checklist.md`.

## Web

`cd apps/web && npm ci && npm run dev`, con `make api` en marcha. Ver `apps/web/README.md`.
