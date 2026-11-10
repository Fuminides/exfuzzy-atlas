# API v1: modos `mock` y `artifacts` (AT-045)

Los mismos endpoints y los mismos modelos de respuesta (`src/atlas/contracts/models.py`) en los dos modos. La validación de
consultas (los 422) vive en `apps/api/atlas_api/main.py` y es común; cada modo solo implementa `atlas_api.store.Store`.

| Modo | Variable | Datos | `Health.mode` |
|---|---|---|---|
| `mock` (por defecto) | `ATLAS_API_MODE=mock` | `fixtures/synthetic/`, todo `synthetic: true` | `mock` |
| `artifacts` | `ATLAS_API_MODE=artifacts` | modelos publicados bajo `ATLAS_PUBLISHED_DIR` (por defecto `artifacts/published`) | `artifacts` |

La API nunca entrena, optimiza ni recalcula firing por fila para pintar un mapa: lee vistas precalculadas por el paso de
publicación y, solo para `rule-trace`, ejecuta el motor ex_fuzzy verificado sobre **una** fila.

## 1. Publicar un run

```bash
PYTHONPATH=src python -m atlas.services.publish \
  --run-dir artifacts/<task_id>/<run_id> \
  --features 'data/processed/air/features/*.parquet' \
  --entities data/processed/air/stations.geojson \
  --feature-spec configs/air/feature_spec.json \
  --from 2023-01-01T00:00:00Z --to 2025-01-01T00:00:00Z [--synthetic] [--replace] [--title "Madrid air quality"]
```

| Opción | Significado |
|---|---|
| `--run-dir` | directorio de A4 (`train_run`). Se comprueba su `SHA256SUMS` **antes** de deserializar nada |
| `--features` | tabla de features (A1): fichero Parquet, glob o directorio, leída con DuckDB. Necesita `entity_id`, `issued_at_utc` (TIMESTAMPTZ), las features del modelo y, si existe, la columna objetivo (`observed`) |
| `--entities` | `EntityCollection` (para Madrid, `stations.geojson` de A1). Se publican solo las entidades presentes en los datos; si una entidad de los datos no tiene registro, falla |
| `--feature-spec` | JSON `{"features": {"<feature>": {"unit", "source_id", "lag_hours"}}}`, una entrada por feature del modelo. `lag_hours >= 0`: `observed_at_utc = issued_at_utc - lag_hours`, nunca posterior a la emisión |
| `--from/--to` | periodo de **emisión** `[from, to)`, UTC explícito |
| `--synthetic` | etiqueta todos los payloads como sintéticos. Es un OR con la marca del run: un run sintético no se puede publicar como real |
| `--task-id` | opcional; solo comprueba que coincide con la tarea del run |
| `--replace` | permite republicar un `model_id` existente (si no, `FileExistsError`) |
| `--chunk-size` | filas de entrada por trozo de la tabla de firing (50 000) |
| `--irregular-times` | las emisiones son instantes de muestreo, no una rejilla horaria (Water): `coverage.step_hours = 1`, `coverage.regular = false` (v0.4) y un aviso en la tarjeta |
| `--metadata` | v0.4: JSON `layout.PublishMetadata` (`configs/<dominio>/attribution.json`): `attribution` (a `entities.geojson` y `card.json`) y, en clasificadores, `target_scheme` (`kind`, `short_name`, y por clase `merged_from` / `description`). Se aplica a la **copia publicada** de `rules.json`; el run no se toca (sección 6). v0.5: `features` (nombre, descripción y `lag_hours` declarado de cada entrada, que van a `variables[].label/description` de la copia publicada; un nombre que no está en el `feature_spec`, o un `lag_hours` que el spec contradice, hace fallar el publish) y `summary` (qué variable observada resume `summary.json`; sección 7) |
| `--territory`, `--territory-title` | v0.5: id y nombre visible del territorio (`madrid` / «Madrid»). Las tareas con el mismo `territory` difieren solo en `horizon_hours`; van al registro y salen en `TaskInfo.territory` / `.territory_title` de `/domains`. Un republish sin ellos conserva los de la entrada anterior de la tarea |
| `--include-unmodelled-entities` | v0.4: publica también las entidades del fichero de geometrías sin datos (y con geometría), con `modelled = false`. Las entidades con datos llevan `modelled = true` |

Memoria: la tabla se lee mes UTC a mes UTC y la tabla de firing se escribe por trozos que DuckDB ordena después (con el
`memory_limit` de 1 GB y desbordando a disco); el pico es un mes de filas, no el periodo entero. Si el periodo solapa el entrenamiento, `card.json` lo avisa («in-sample»).

### Layout publicado

```
artifacts/published/
  registry.json                 task_id -> {model_id, domain, title, task_type, target, unit, horizon_hours, data_version, synthetic, territory, territory_title}
  <model_id>/
    model.pkl run_manifest.json metrics.json rules.json     copiados del run y verificados con su SHA256SUMS
    entities.geojson                 EntityCollection restringida a las entidades publicadas
    inputs.parquet                   entity_id, issued_at_utc, features (las trazas se recalculan desde aquí)
    activations/year=YYYY/month=MM/part-000000.parquet
                                     entity_id, issued_at_utc, rule_id, firing_strength, effective_firing, missing_reason
                                     un fichero por mes, ordenado por (rule_id, issued_at_utc, entity_id), grupos de ~100 000 filas
    predictions.parquet              entity_id, issued_at_utc, valid_at_utc, prediction, observed, missing_reason
                                     (clasificador: ver la sección 4)
    feature_spec.json                unidad, fuente y lag por feature
    card.json                        ModelCard: manifest, metrics, coverage (primera/última emisión, step_hours)
    importance.json                  v0.5: RuleImportanceResponse precalculado (sección 7)
    summary.json                     v0.5: SummaryResponse precalculado (sección 7)
    publish.json                     periodo, filas, entidades, ruta de la tabla de features, fecha de publicación
    SHA256SUMS                       todos los ficheros anteriores (rutas relativas)
```

- Escritura atómica: se escribe en `.tmp-<model_id>-*` y se renombra; un fallo no deja un directorio a medias ni toca el
  registro. `registry.json` se reemplaza con `os.replace`. Con `--replace` el directorio anterior se aparta, se renombra el
  nuevo y se borra el viejo.
- **Disposición de `activations/`** (AT-061, B3): cada fichero mensual va ordenado por `(rule_id, issued_at_utc,
  entity_id)` y escrito en grupos de filas de 100 000 (`ACTIVATION_SORT`, `ACTIVATION_ROW_GROUP_SIZE`; el último grupo
  de cada fichero es el resto). Así `WHERE rule_id = ?` poda grupos de filas con las estadísticas min/max y lee ≈ una
  regla de cada `n_reglas`, no el mes entero. Solo cambia el orden de las filas: contrato, esquema y respuestas de la API
  son los mismos (los clasificadores usan la misma disposición). Los modelos publicados antes de AT-061 se siguen
  sirviendo igual, más despacio; para pasarlos a la nueva disposición hay que republicarlos con `--replace`.
- Los valores ausentes son `null` en Parquet (nunca NaN ni 0). En `activations`, una entrada ausente produce un registro
  por regla con `firing_strength` nulo y `missing_reason = missing_input`.
- `registry.json` alimenta `/api/v1/domains`: `TaskInfo.model_id` es lo que la web usa para descubrir el modelo. Publicar
  otro modelo para la misma `task_id` cambia el modelo servido (el anterior queda en disco).
- `model.pkl` es un pickle (ejecuta código al cargarse). Antes de deserializarlo, la API (primera traza de cada modelo)
  comprueba contra `SHA256SUMS` solo `model.pkl`, `rules.json` y `card.json` (`atlas.services.verify.load_verified_model`);
  un `model.pkl` alterado se rechaza con `ValueError: checksum mismatch`. Las activaciones, predicciones y entradas son
  datos: se verifican al publicar (el directorio nuevo se comprueba entero contra su `SHA256SUMS` antes de hacerse
  visible) y con el comando explícito
  `python -m atlas.services.verify <artifacts/published/model_id | artifacts/published>` (código de salida 1 si algo no
  coincide, falta o sobra respecto a `SHA256SUMS`). Conviene lanzarlo tras copiar o desplegar un directorio publicado.
  Publica únicamente runs propios.

Para probar el modo `artifacts` sin datos reales, hay un run sintético completo:

```bash
PYTHONPATH=src python -m atlas.services.synthetic --out artifacts/published-demo
ATLAS_API_MODE=artifacts ATLAS_PUBLISHED_DIR=artifacts/published-demo make api
```

## 2. Servir los modelos publicados

```bash
ATLAS_API_MODE=artifacts make api
# equivalente:
PYTHONPATH=src:apps/api ATLAS_API_MODE=artifacts ATLAS_PUBLISHED_DIR=artifacts/published \
  python -m uvicorn atlas_api.main:app --port 8000
```

El registro y el `SHA256SUMS` de cada modelo se vuelven a mirar en cada petición: publicar un modelo nuevo o con
`--replace` se ve sin reiniciar (el cache de rule-map incluye un token del `SHA256SUMS`, así que no sirve resultados
viejos). Lo que no hay que hacer es publicar dos modelos a la vez en el mismo directorio.

## 3. Semántica de los endpoints en modo `artifacts`

| Endpoint | Origen |
|---|---|
| `/domains` | `registry.json`; los dominios sin tareas salen `planned` |
| `/entities?domain=&task_id=` | `entities.geojson` del modelo de la tarea (ver «Varias tareas en un dominio»); 404 si no hay ninguna |
| `/models/{id}`, `/models/{id}/rules` | `card.json`, `rules.json` (con `synthetic` del `card.json`). Contrato v0.8: cada antecedente lleva `operator` (`is` / `at_least` / `at_most` / `any_of`), `terms` (términos base que cubre) y, en un compuesto, `label` / `label_en` (`CONTRACTS.md` §19) |
| `/series` | `predictions.parquet`; `from`/`to` semiabierto `[from, to)` por emisión |
| `/rule-map` | DuckDB sobre `activations/` (ver abajo) |
| `/entities/{id}/rule-trace` | fila de `inputs.parquet` + `atlas.explain.build_rule_traces` con el modelo publicado; `observed_at_utc` y `source_id` salen de `feature_spec.json`. v0.8: cada antecedente de la traza lleva `operator` y `terms`, y su `membership` es la suma acotada que calcula ex_fuzzy para una condición `at_least` / `at_most` / `any_of` |

**Varias tareas en un dominio.** La unidad que se elige es la tarea, no el dominio: `/entities` acepta `task_id` opcional
y sirve exactamente las entidades de esa tarea (nunca la unión de varias: dos países en un mapa serían dos modelos
mezclados). Los demás endpoints ya van por `task_id` (`/series`, `/predictions`, `/observations`) o por `model_id`
(`/models/*`, `/rule-map`, `/rule-territories`, `/rule-stories`, `/entities/{id}/rule-trace`, `/scenarios`) y no cambian.

| `/entities?domain=D` | sin `task_id` | con `task_id` |
|---|---|---|
| D tiene 1 tarea | 200, igual que antes | 200 si es esa tarea; 404 si el `task_id` no existe; 422 si es de otro dominio |
| D tiene varias tareas | **422** (ambiguo; el detalle lista los `task_id`) | 200 con las entidades de esa tarea; 404 / 422 como arriba |
| D no tiene tareas | 404 | 404 (id desconocido) o 422 (de otro dominio) |

Se rechaza en vez de elegir un valor por defecto porque cualquier regla («la primera», «la unión») ocultaría una tarea
o mezclaría mapas sin que el cliente lo note. Un cliente antiguo que no envía `task_id` sigue funcionando mientras el
dominio tenga una sola tarea. El cache de respuestas (`cache.py`) solo guarda vistas por `model_id`, así que no hay clave
que ampliar; `/entities` se lee de `entities.geojson` sin cache. El modo `mock` aplica las mismas reglas con las tareas
de `fixtures/synthetic/domains.json`.

**rule-map.** `firing_strength` con `time` = un instante de emisión; `mean_activation` y `activation_frequency`
(con `tau`, `>=`) sobre la ventana semiabierta `[from, to)`. `n_valid` cuenta los registros no ausentes. Una entidad sin
ningún registro en la ventana es `no_observation`; con registros pero todos con entrada ausente, `missing_input`
(`value: null`); `0.0` es siempre un número. El mismo cálculo que `FixtureStore`, verificado en `tests/api/`.
Nunca se devuelven historias por fila: una `Feature` por entidad.

**rule-trace.** 404 si la entidad no existe o no hay fila de entrada para ese `at` exacto. Con entradas NaN la traza es
`missing_input` (sin reglas), igual que en el motor.

### Límites y caché

| Qué | Límite |
|---|---|
| Ventana de `rule-map` agregado | 366 días como máximo, si no 422 (en ambos modos); `to > from` |
| `/series` | **2 000 puntos por página** (`SERIES_MAX_POINTS`; hasta AT-061 eran 20 000). Sin `from`/`to` se devuelve la primera página del rango completo; si hay más, `next_cursor` es la siguiente emisión, que se pasa como `cursor` hasta que sea `null`. Compatible hacia atrás: el esquema no cambia, un cliente que ya seguía `next_cursor` solo hace más peticiones. Para una ventana conocida, pedir `from`/`to` |
| DuckDB | `memory_limit` 512 MB, 2 hilos; un cursor por petición |
| Cachés (rule-map, territorios, historias) | LRU en proceso **acotada por bytes aproximados**: 64 MB por worker (`ATLAS_CACHE_MB`, o `ArtifactStore(cache_bytes=)`). El tamaño de una entrada es ≈ 6 × la longitud de su JSON (lo que ocupan los objetos pydantic en memoria, medido 6,3x con mapas de 60 puntos y de 263 polígonos), de modo que 64 MB son ≈ 64 MB de RAM y caben ≈ 330 mapas de 60 puntos o ≈ 20 de 263 polígonos; una respuesta mayor que todo el presupuesto se sirve pero no se guarda |

Clave de caché del rule-map: `model_id + data_version + token(SHA256SUMS) + rule_id + metric + time/from/to + tau`. Es
**por proceso**: con `uvicorn --workers N` cada worker tiene su propia caché (y su propio `ArtifactStore`, DuckDB y modelo
cargado), así que la huella de memoria es N veces la de uno (≈ 450 MB por worker medidos en AT-061 más hasta
`ATLAS_CACHE_MB`) y una petición repetida puede ser un fallo en otro worker. Es aceptable porque las consultas cuestan
decenas de ms. No se invalida sola con el tiempo: los datos publicados son inmutables hasta una republicación, que cambia
el token.

### Workers y rendimiento

Un worker sirve en serie (el GIL retiene la construcción y la serialización de las respuestas). `make demo` y
`scripts/qa/demo.sh` arrancan uvicorn con `--workers 2`; `ATLAS_API_WORKERS=4 make demo` lo cambia. `--reload` queda solo
en `make api` / `make api-artifacts` (desarrollo, un proceso). Para servir a mano:
`ATLAS_API_MODE=artifacts uvicorn atlas_api.main:app --workers 2` (no combinar con `--reload`). Mediciones y
presupuesto: `docs/qa/volume.md`, `make qa-volume`.

## 4. Clasificadores (contrato v0.3, `winning_rule_classifier`)

`publish` detecta el tipo de tarea por `rules.json` (`inference.family == winning_rule_classifier`) y lo guarda en
`registry.json` como `task_type = "classification"` (`/domains` lo muestra). Los runs de regresión se publican igual que
antes (mismo layout, mismos ficheros). Para un clasificador cambian tres cosas:

| Fichero | Contenido |
|---|---|
| `activations/` | `atlas.explain.iter_classifier_firing_tables`: `entity_id, issued_at_utc, rule_id, firing_strength, weight, association_degree, is_winner, missing_reason`. Entrada ausente: números `null`, `is_winner=false`, `missing_reason=missing_input` |
| `predictions.parquet` | `entity_id, issued_at_utc, valid_at_utc, prediction, observed, observed_label, prediction_label, missing_reason`. **`prediction` es `null` en todas las filas**: un índice de clase nunca se publica como número. `prediction_label` sale de `predict_labels` y debe ser una etiqueta de `target_scheme` (si no, el publish falla). `observed_label` clasifica `observed` con el esquema del run (redondeo a entero y frontera `upper_inclusive`, igual que `ClassScheme.classify`; `null` si falta o queda fuera del esquema). Sin etiqueta: `prediction_unavailable` (entradas presentes pero ninguna regla se activa) o `missing_input` |
| `card.json` | `target_scheme` copiado del `rules.json` del run |

| Endpoint | Clasificador |
|---|---|
| `/domains` | `TaskInfo.task_type = "classification"` |
| `/models/{id}` | `ModelCard.target_scheme` (clases, límites, colores, fuente) |
| `/models/{id}/rules` | tal cual el run: consecuentes `class`, `weight` por regla, `target_scheme` |
| `/series` | cada punto lleva `observed` (valor), `observed_label` y `predicted_label`; `prediction` es `null` y `missing_reason` solo aparece cuando no hay etiqueta |
| `/rule-map` | misma semántica de métricas, siempre sobre **`firing_strength`** (el grado de emparejamiento de la regla elegida, no la asociación ni la probabilidad de clase). Un mapa de `association_degree` o de «regla ganadora» sería un valor nuevo de `RuleMapMetric` (cambio de contrato) y queda como trabajo futuro; los datos ya están en `activations/` |
| `/entities/{id}/rule-trace` | `atlas.explain.build_classifier_traces` con las etiquetas del esquema: cada regla con `weight` y `association_degree`, `prediction.label` y `winning_rule_id` (regla de mayor asociación positiva; el validador del contrato lo comprueba). Sin regla activa: `label=null`, `missing_reason=prediction_unavailable`. Si la fila se publicó sin etiqueta porque el target no tiene nivel de referencia (p. ej. NYC `low_volume`), la traza también da `label=null`, `winning_rule_id=null`, `missing_reason=prediction_unavailable` y un aviso de calidad; las reglas, sus activaciones y sus grados de asociación siguen siendo los que da el motor (#51). `observed_at_utc` y `source_id` salen de `feature_spec.json` como siempre |

Ni el firing ni el grado de asociación son probabilidades, contribuciones ni riesgos; la etiqueta es la categoría
prevista según el esquema del modelo, no un riesgo sanitario.

### 4.1 Mezcla de reglas (contrato v0.7, `rule_mixture_classifier`)

La clase es la de mayor `b_c + Σ_r W[r, c] · firing_r` (ex_fuzzy `inference='mixture'`): **ninguna regla decide sola**,
y nada lo dice. Se publica como un clasificador (`task_type = "classification"`, etiquetas y no números) con estas
diferencias (`CONTRACTS.md` §18):

| Fichero / endpoint | Mezcla de reglas |
|---|---|
| `activations/` | `atlas.explain.iter_mixture_firing_tables`: `entity_id, issued_at_utc, rule_id, firing_strength, centred_contribution, is_decisive, missing_reason`. `centred_contribution` = pesos centrados de la regla × firing para la **clase predicha** (> 0 la apoya, < 0 la suprime; null sin predicción); `is_decisive`: con los pesos de la regla a cero, ex_fuzzy predice otra clase |
| `predictions.parquet` | lo de un clasificador más `top_rule_id` y `top_rule_share` (la regla que más apoya la clase predicha y su fracción de los apoyos positivos; null donde no hay etiqueta o se retiene) |
| `/models/{id}/rules` | `class_weights` (tal como se ajustaron), `class_weights_centred`, `strongest_class` por regla y `class_bias`; `weight` es null; `consequent` es solo la clase de la búsqueda genética (no entra en la predicción) |
| `/entities/{id}/rule-trace` | `atlas.explain.build_mixture_traces`: por regla `class_weights`, `class_contributions` (`W·firing`, ex_fuzzy `mixture_contributions`) y `class_contributions_centred`; `prediction.class_scores` (ex_fuzzy `mixture_scores`), `class_bias`, `label`, `top_rule_id`, `top_rule_share`; `winning_rule_id` siempre null. Nunca el softmax |
| `/predictions` | `top_rule_id` / `top_rule_share`; `decided_by_rule_id` null |
| `/rule-territories` | `winner_share` → 422; `mean_activation` y `activation_frequency` como siempre |
| `/scenarios` | vuelve a ejecutar ex_fuzzy; `prediction_change.original_top_rule_id` / `scenario_top_rule_id` |
| `/models/{id}/importance` | `measure = rule_mixture` (abajo) |

Paridad de cada fila publicada: `python -m atlas.ml.publish_parity <modelo>` (etiqueta, firing, contribución centrada,
decisivo y regla principal exactos contra ex_fuzzy; trazas de muestra contra `mixture_scores` / `mixture_contributions`).

**Etiqueta observada desde una columna (`--observed-label-column`, AT-041e).** Cuando el esquema no está expresado en las
unidades del `observed` (NYC: `observed` es un conteo de recogidas y los límites son percentiles de una referencia por
zona y hora de la semana), aplicar los límites al valor numérico daría una etiqueta falsa. Con
`--observed-label-column target_level` el publish toma `observed_label` de esa columna de la tabla de entrada (debe ser una
etiqueta de `target_scheme` o nula; si no, falla) y no llama a `classify_observed`, así que también funciona con
`boundary = lower_inclusive`. Una fila con `observed` numérico pero etiqueta nula no tiene nivel de referencia («sin
referencia»): se publica con `prediction_label = null` y `missing_reason = prediction_unavailable` (con entrada ausente
sigue siendo `missing_input`), de modo que nunca se pinta como clase ni como «normal». Una fila sin `observed` (sin
observación) conserva su predicción. Las filas de `activations/` y la traza de esas filas siguen siendo las del motor: el
firing de una regla es un grado de emparejamiento aunque la clase no se publique. Solo aplica a clasificadores.

Demo sintética de un clasificador (tres bandas inventadas, ajuste de segundos):

```bash
PYTHONPATH=src python -m atlas.services.synthetic --out artifacts/published-demo-class --task classification
ATLAS_API_MODE=artifacts ATLAS_PUBLISHED_DIR=artifacts/published-demo-class/published make api
```

En código: `build_synthetic(root, task="classification")` (tarea `synthetic_class_h6`); la fixture `built_class` de
`tests/api` y `tests/services` lo usa. La demo de regresión por defecto no cambia.

## 5. Pruebas

`tests/services/` (publicación) y `tests/api/test_artifacts_api.py` entrenan un run sintético diminuto con
`atlas.ml.train_run`, lo publican en un directorio temporal y comprueban: validez de todos los payloads contra el contrato;
paridad valor del mapa == traza == registro de `activations`; agregados == recomputación con pandas (incluida una ventana
que cruza dos meses y otra que desborda la cobertura); `0 ≠ null`; semántica `[from, to)`; los 422 comunes a los dos modos;
`registry` → `/domains`; checksum y atomicidad del publish; serie y traza == `predict`. Los clasificadores tienen sus propios
ficheros (`tests/services/test_publish_classifier.py`, `tests/api/test_artifacts_api_classifier.py`): payloads válidos,
valor del mapa == traza == tabla de firing, ganadora y etiqueta de la traza == `predict_labels`, etiquetas de la serie ==
predicciones, ninguna predicción numérica, `task_type` del registro. Ejecutar:
`make test` o `PYTHONPATH=src:apps/api python -m pytest -q tests/services tests/api`.

## 6. Contrato v0.4: vistas nuevas (issue #56, `CONTRACTS.md` §10)

Mismos modelos en los modos `mock` y `artifacts` (en `mock` salen de `fixtures/synthetic/`; sus cuatro estaciones
tienen modelo, porque los tests de la web leen esas fixtures: para ver una entidad `modelled: false` hay que servir
`python -m atlas.services.synthetic --v04 --out <dir>` en modo `artifacts`, que añade la entidad `E9`). Referencia de respuestas, generada por el backend: `fixtures/synthetic/v04_responses.json`
(`{method, path, query, response}`; el escenario lleva además `body`). Nada de lo siguiente se calcula en el navegador.

| Endpoint | Parámetros | Respuesta (`m.*`) |
|---|---|---|
| `GET /api/v1/predictions` | `task_id`, y `time` **o** `from`+`to` | `PredictionsResponse`: `Feature` por entidad con `prediction`, `prediction_label`, `observed`, `observed_label`, `unit`, `issued_at_utc`, `valid_at_utc`, `missing_reason` |
| `GET /api/v1/observations` | igual | `ObservationsResponse`: por entidad `target` (el objetivo observado **en `valid_at_utc`**), `target_label`, `inputs` (valores de entrada de esa emisión, con unidad, fuente y `observed_at_utc`) |
| `GET /api/v1/rule-territories` | `model_id`, `from`, `to`, `measure` (`mean_activation`\|`activation_frequency`\|`winner_share`), `tau` (0,5) | `RuleTerritoriesResponse`: por entidad `n_valid`, `n_records`, `dominant_rule_id`, `dominant_value` y `rules[]` (las tres medidas) |
| `GET /api/v1/rule-stories` | `model_id`, `from`, `to`, `tau` (0,5), `limit` (10, máx. 50) | `RuleStoriesResponse`: historias ordenadas por puntuación, cada una con `text`, `numbers`, `queries`, `checks` |
| `POST /api/v1/scenarios` | cuerpo `ScenarioRequest`: `model_id`, `entity_id`, `at`, `overrides` | `ScenarioResponse`: `original`, `modified`, `inputs`, `rule_deltas`, `prediction_change`, `synthetic_what_if`, `label` |

**Reglas comunes (422).** Instantes en UTC explícito. `predictions` y `observations`: `time` o una ventana completa
`[from, to)`, nunca las dos ni ninguna. Ventanas: `to > from` y como mucho 366 días. `tau` en (0, 1]. `winner_share` solo
para clasificadores. 404: tarea, modelo, entidad o emisión inexistentes. Una entidad `modelled: false` devuelve null con
`missing_reason = not_modelled` en `rule-map`, `predictions`, `observations`, `rule-territories` y `rule-trace` (sin
reglas); `series` da 404 y `scenarios` 422.

**Con `time` o con ventana.** `time` es un `issued_at_utc` exacto. Una ventana devuelve, por entidad, su **última** muestra
`[from, to)` y cada `Feature` lleva su propio `issued_at_utc`/`valid_at_utc`: es lo que hay que usar en tareas con
`coverage.regular = false` (Water), donde un instante casi no cubre entidades.

**Observaciones (modo Data).** Los valores son los publicados (`inputs.parquet`, `predictions.parquet`). `inputs` son las
entradas del modelo en la emisión (`observed_at_utc = emisión − lag`, nunca posterior). El objetivo es el valor observado
en `valid_at_utc` (emisión + horizonte): no se conocía al emitir, salvo con horizonte 0. No es una predicción ni una
interpolación. Un hueco es null con `no_observation`; nunca 0.

**Territorios.** `n_valid` = registros de la entidad en la ventana con todas las entradas presentes; todas las medidas se
dividen por él. La regla dominante es el argmax de `measure` y nada más: desempate por la menor posición de regla
(valores a menos de 1e-12 empatan), y null si `n_valid = 0` o la medida es 0 en todas. Los territorios se solapan y no son
una partición. En un regresor TSK «dominante» significa mayor firing medio, no «contribución». Caché LRU por proceso con clave
`model_id + data_version + token(SHA256SUMS) + medida + tau + ventana`.

**Historias.** Texto con plantilla (sin LLM), solo sobre activaciones. Para auditar una historia: ejecutar sus `queries`
y, para cada `check`, contar las `Feature` de `queries[check.query]` cuya propiedad `property` cumple `op` (`gte`
operando, `eq` operando, `not_null`); el recuento tiene que ser `expected`. Tipos: ráfaga de coactivación (solo emisiones
consecutivas de una rejilla regular), regla localizada y regla líder. La puntuación y las condiciones están en
`score_definition` y en `atlas.services.stories`. No se devuelven historias de ráfaga para tareas irregulares.

**Escenarios.** `overrides` solo con variables del modelo, finitas y dentro del `domain` de la variable (extremos
incluidos). Se parte de la fila publicada de `(entity_id, at)`: sin ella, 404. Se ejecuta la inferencia real (la misma que
`rule-trace`) sobre la fila modificada; nada se escribe en disco ni se toca el conjunto de datos. `inputs[].origin` marca
cada entrada como `observed` o `overridden`; una entrada ausente que no se sobrescribe sigue ausente (sin inferencia). Sin
overrides, `modified == original`. Un clasificador con fila «sin referencia» (NYC) conserva la etiqueta retenida en las dos
trazas. El `label` obligatorio de la UI es «respuesta del modelo ante entradas modificadas».
El CORS del desarrollo local admite ahora `POST`.

**Pruebas.** `tests/contracts/test_models_v04.py`; `tests/services/test_publish_v04.py` y
`test_stories_territories_unit.py`; `tests/api/test_v04_mock.py` y `test_v04_artifacts.py` (regresor y clasificador
sintéticos, con una entidad sin modelo: `python -m atlas.services.synthetic --v04`); y, sobre los modelos reales,
`tests/integration/test_real_v04_endpoints.py` (`make qa`).

## 7. Contrato v0.5: importancia, resumen, etiquetas y territorios (`CONTRACTS.md` §12)

Todo se precalcula **al publicar** (`atlas.services.enrich`, `importance`, `summary`) a partir de lo ya publicado, y se
sirve sin recalcular nada. En `mock` salen de `fixtures/synthetic/` (`importance.json`, `summary.json`, `model_rules_extra.json`;
las genera `make fixtures` con el mismo código, para el regresor de juguete `synthetic-no2-h6-v0` y para un clasificador
sintético entrenado, `exfuzzy-synthetic_class_h6-synthetic-class-seed3`, cuyas reglas se sirven en `/rules` para que
`importance` se pueda leer junto a ellas).

| Endpoint | Respuesta | Notas |
|---|---|---|
| `GET /api/v1/models/{model_id}/importance` | `RuleImportanceResponse` | 404 si el modelo se publicó antes de v0.5 (`importance.json` no existe): el `detail` dice qué falta y cómo añadirlo |
| `GET /api/v1/summary?task_id=` | `SummaryResponse` | igual, con `summary.json`; `task_id` desconocido: 404 |

El fichero se lee una vez por versión del modelo (se descarta cuando cambia `SHA256SUMS`) y se valida contra el contrato.

**Importancia («decide y acierta», nunca activación).**

- *Clasificador* (`winning_rule`): cada predicción publicada (con etiqueta) la decide la única regla con `is_winner`;
  `decided_share` = predicciones que decide / `n_predicted`; `accuracy` = de esas decisiones con clase observada, las que
  coinciden. Comprobación al calcular, que falla si no se cumple: exactamente un `is_winner` por predicción con etiqueta, y la
  clase de la regla ganadora es `prediction_label`.
- *Regresión TSK de orden 0 aditiva* (`weighted_average`): cuota de una regla = `effective_firing / Σ effective_firing` por
  registro; `mean_weight_share` es su media. Comprobación al calcular: `Σ cuota × consecuente` reproduce la predicción
  publicada a 1e-9 (con el `train_target_mean` del modelo cuando nada dispara). «Decide» = mayor cuota (empate: menor
  posición); `mae` = error medio de las predicciones que decide y tienen observación.
- *Variables*: clasificador, fracción de las decisiones tomadas por reglas que usan la entrada; regresión, suma de las
  `mean_weight_share` de esas reglas. *Entidades*: las mismas medidas dentro de cada una (solo reglas que decidieron algo).
- *Mezcla de reglas* (`rule_mixture`, v0.7): ninguna regla decide, así que no hay `decided_share`. `top_contributor_share`
  = predicciones en las que la regla es la que más apoya la clase predicha (`top_rule_id`) / `n_predicted`, y `accuracy`
  se calcula sobre ellas; `decisive_share` = predicciones cuya clase cambiaría con los pesos de la regla a cero
  (`is_decisive`, calculado por ex_fuzzy al publicar) / `n_predicted` (no suman 1). Por variable: la regla principal
  usa la entrada, y al menos una regla que la usa es decisiva. `n_no_top_rule`: predicciones sin regla principal.
  Comprobación al calcular: la regla principal publicada es el primer registro de mayor contribución centrada positiva.
- `n_no_rule`: emisiones con entradas completas en las que no dispara ninguna regla (no se atribuyen a nadie).
  Una predicción que el publish **retuvo** aunque una regla disparó (NYC, celdas sin nivel de referencia: sin etiqueta) no es
  una predicción publicada y no entra ni en `n_predicted` ni en `n_no_rule` (queda en `publish.json`, `v05.importance.n_withheld_excluded`).
- `period_from_utc`/`period_to_utc`: primera y última emisión publicada. Es fiel a la inferencia, no causal.

**Resumen de datos.** Distribución de la variable observada de la tarea en **todo el histórico de la tabla de features**
(no solo la ventana publicada), contando cada valor **una vez** por entidad e instante (se deduplica por
`(entity_id, instante)` y dos valores distintos para lo mismo es un error). Se restringe a las entidades publicadas con modelo.
Variable observada por tarea (bloque `summary` de `configs/<dominio>/attribution*.json`; por defecto la columna objetivo
del run):

| Tarea | Variable | Instante | Presentación |
|---|---|---|---|
| Madrid (`madrid_no2_h6`), Alemania (`de_no2_h6`) | NO₂ horario observado (`target`) | `valid_at_utc` | clases del `target_scheme` con la convención de `classify_observed` (redondeo a entero, frontera superior inclusiva, clase final abierta) |
| Water (`uk_water_do`) | oxígeno disuelto observado, mg/l (`target`) | `valid_at_utc` (= muestra) | cuantiles p10, p25, p50, p75, p90 y media |
| NYC (`nyc_pickups_h1`) | recogidas por zona y hora (`target`) | `issued_at_utc` (la hora `[T, T+1)` que cubre) | cuantiles; el nivel relativo es uniforme por construcción y no se resume |

Un esquema `percentile_reference` nunca se divide en clases. Grupos: `all`, `year`, `month`, `hour`, `weekday`
(lunes = 0) en la hora local (`timezone`, la de las entidades) y `entity`. Los valores fuera de las clases no se cuentan
(y `notes` lo dice).

**Etiquetas de las entradas.** `LinguisticVariable.label/description` salen del bloque `features` del `--metadata`. Cada
etiqueta lleva el `lag_hours` que afirma, y el publish falla si el `feature_spec` dice otra cosa: «NO₂ hace 1 h (último dato)»
es `no2_last` (`lag_hours = 1`), «NO₂ hace 2 h» es `no2_lag1h` (`lag_hours = 2`).

**Añadir todo esto a un modelo ya publicado** (sin republicar; el modelo, las predicciones y las activaciones no se tocan):

```bash
PYTHONPATH=src python -m atlas.services.enrich --published-dir artifacts/published \
    --model-id <model_id> --metadata configs/<dominio>/attribution.json --territory madrid --territory-title Madrid
```

Verifica el directorio, calcula `importance.json` y `summary.json` en un directorio de preparación, parchea `rules.json`
con las etiquetas, reemplaza los ficheros dejando `SHA256SUMS` para el final, comprueba `verify`, anota lo hecho en
`publish.json` (`v05`) y fija el territorio en el registro. `--features` por defecto es la tabla registrada en `publish.json`.
Pico medido y tiempos en el PR; límite de DuckDB `--memory-limit` (2GB por defecto).

**Pruebas.** `tests/services/test_v05_importance.py`, `test_v05_summary.py`, `test_v05_enrich.py`;
`tests/api/test_v05_artifacts.py`, `test_v05_mock.py`; y sobre los modelos reales `tests/integration/test_real_v05_endpoints.py`
(se salta, con el comando, para un modelo publicado antes de v0.5).

## 8. Contrato v0.6.2: explicación de las reglas (`CONTRACTS.md` §17)

| Endpoint | Respuesta | Notas |
|---|---|---|
| `GET /api/v1/models/{model_id}/explanation` | `ModelExplanation` | 404 si el modelo no existe o no tiene explicación |

En `artifacts` se lee `configs/explanations/<model_id>.json` (en git; otro directorio con `ATLAS_EXPLANATIONS_DIR`) y se
valida contra el contrato; en `mock`, `fixtures/synthetic/explanations.json` (una explicación sintética del regresor de
juguete, escrita a mano por `make fixtures`, no por una IA). El texto lo escribe Claude con `scripts/explain_model.py`
(`docs/reproduce.md`, «Explicación del modelo»).

**Pruebas.** `tests/contracts/test_models_v062.py`, `tests/api/test_v062_explanation.py`, `tests/services/test_explain_model.py`;
sobre los modelos reales `tests/integration/test_explanations.py`.
