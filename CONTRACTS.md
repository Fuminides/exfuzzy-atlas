# Contratos de interoperabilidad — v0.1 ratificado

**Ratificado por A0 el 2026-10-30, con las enmiendas del §7.** La forma normativa es el código: `src/atlas/contracts/models.py` (Pydantic), `src/atlas/contracts/observations.py` (Arrow/Parquet) y los JSON Schema exportados en `src/atlas/contracts/schemas/`. Si este documento y el código discrepan, manda el código y se corrige el documento en el mismo PR. Los contratos pretenden permitir exploración por separado en los tres dominios.

## 1. Registro de observación canónico

`domain` (`air|water|mobility`), `entity_id` (estación/punto/zona), `timestamp_utc` (instante), `source_timestamp_local` (opcional), `timezone`, `feature_name`, `value`, `unit`, `validity_flag`, `source_id`, `data_version`. Para eventos agregados, `aggregation_window_start_utc`, `aggregation_window_end_utc` y `n_records`.

Los pipelines pueden almacenar tablas anchas para eficiencia, pero deben preservar estos metadatos y la semántica para exportación/consulta. `entity` incluye `lat`, `lon` o geometría; no fabricar coordenadas ausentes. Los datos no disponibles son `null` con motivo cuando se conozca; nunca convertir a cero sin justificación.

## 2. Ejemplo de registro de predicción (schema lógico)

```json
{
  "domain": "air",
  "task_id": "madrid_no2_h6",
  "entity_id": "STATION_ID",
  "issued_at_utc": "2025-05-10T12:00:00Z",
  "valid_at_utc": "2025-05-10T18:00:00Z",
  "target": "no2",
  "unit": "ug/m3",
  "prediction": 39.7,
  "observed": null,
  "model_id": "exfuzzy-no2-v001",
  "data_version": "madrid-2025-05",
  "quality": {"status": "valid", "warnings": []},
  "explanation": {"rule_firings": [{"rule_id": "R03", "strength": 0.72}]}
}
```

Valores ficticios: solo para ilustrar formato. `observed` se rellena únicamente si existe observación y no implica disponibilidad a la fecha de emisión.

## 3. Interfaces sugeridas

Python:

```python
class DatasetAdapter(Protocol):
    def ingest(self, manifest: SourceManifest) -> DataArtifact: ...
    def validate(self, artifact: DataArtifact) -> QualityReport: ...
    def make_features(self, artifact: DataArtifact, task: TaskSpec) -> FeatureArtifact: ...

class TrainedModelAdapter(Protocol):
    def predict(self, features: pd.DataFrame) -> np.ndarray: ...
    def explain_rows(self, features: pd.DataFrame) -> list[dict]: ...
```

Son **contratos de diseño, no APIs ya existentes**. Hay que inspeccionar la versión instalada de `ex_fuzzy` antes de implementar `explain_rows`; no asumir nombres internos como `firing_strength`.

HTTP:

- `GET /api/v1/domains` — dominios/tareas habilitados.
- `GET /api/v1/entities?domain=air` — estaciones/zonas con geometría.
- `GET /api/v1/series?task_id=...&entity_id=...&from=...&to=...` — observado/predicho/calidad.
- `GET /api/v1/models/{model_id}` — metadata, evaluación, entrenamiento, procedencia.
- `GET /api/v1/predictions/{prediction_id}/explanation` — reglas activas, grado y texto.
- `POST /api/v1/scenarios` — evaluación contrafactual descriptiva (no causal), límites de entradas explícitos.

Para respuestas paginadas, incluir `next_cursor`, `total` si está disponible y `data_version`. Nunca devolver millones de filas en un endpoint sin agregación.

## 4. Formato de artefactos

- `run_manifest.json`: commit, versión paquete ex_fuzzy, task, seed, split period, data checksum, feature list, warnings, metrics y paths.
- `metrics.json`: baselines y estimador final sobre **el mismo split temporal**.
- `rules.json`: id estable dentro del modelo, condición lingüística, umbrales/particiones, consequent, soporte, calidad, y documentación del método de activación.
- `predictions.parquet`: entidad, issued_at, valid_at, observado (si disponible), predicción, model_id.
- `quality_report.json`: rows, cobertura, missing, intervalos, duplicados, códigos inválidos, outliers etiquetados.

Nombres y unidades normalizados; conservar campos originales y versiones de esquema para trazabilidad. El backend de entrenamiento escribe artefactos atómicos; el frontend consume solo API.

## 5. Reglas temporales obligatorias

- UTC para keys/timestamps, timezone local preservada como contexto (Madrid: Europe/Madrid; NYC: America/New_York; UK: Europe/London). Determinar horas ambiguas/inexistentes con estrategia documentada.
- Predecir `y(t+h)` solo con features disponibles a `t`; `issued_at`/`valid_at` separados.
- Splits cronológicos con embargo/lag adecuados y sin shuffle; holdout por entidad opcional para generalización espacial.
- Imputación/estandarización ajustada solo con train; control de leakage automatizado.

## 6. Extensión v0.2: reglas en el mapa (propuesta sujeta a ratificación A0)

La experiencia principal está en `MAP_EXPERIENCE.md`. Nunca llamar «contribución» a una activación sin equivalencia demostrada con la inferencia real.

- `GET /api/v1/models/{model_id}/rules`: reglas, términos lingüísticos, atributos, consecuentes, versión, tipo de inferencia y metadatos.
- `GET /api/v1/rule-map?model_id=...&rule_id=...&time=...&metric=firing_strength`: GeoJSON por entidad observada (punto para Madrid/agua, polígono real en NYC) con `value`, `n_valid`, `model_id`, `data_version`, `geometry_support`, `issued_at_utc`, `valid_at_utc` y `quality`.
- `GET /api/v1/rule-map?model_id=...&rule_id=...&from=...&to=...&metric=activation_frequency&tau=0.5`: valor agregado por entidad en un intervalo, siempre con denominador `n_valid`; aclarar si `time` es instante o ventana de emisión.
- `GET /api/v1/entities/{entity_id}/rule-trace?model_id=...&at=...`: `feature_values`, `antecedent_memberships`, `firing_strength`, `tnorm`, `prediction`, `rule_id`, `observation_ids`, `data_version` y alertas de calidad. La traza usa directamente el motor Python verificado.

**Schema mínimo de Feature GeoJSON:
** `Feature.properties = {entity_id, rule_id, metric, value: number|null, n_valid: integer, time_from_utc, time_to_utc, issued_at_utc?, valid_at_utc?, model_id, data_version, geometry_support, missing_reason?, quality}`. Los campos temporales no aplicables pueden ser `null`; `metric` y `geometry_support` son enumerados, no texto arbitrario.

**Invariantes:**

1. `metric=firing_strength` es valor por registro válido, no probabilidad. Para ventanas temporales usar `mean_activation` o `activation_frequency`, no un firing indeterminado.
2. El frontend no reconstruye firing ni particiones; representa valores calculados desde el modelo versionado.
3. `dominant_rule` es argmax de firing, no contribución a la predicción. `rule_contribution` requiere validación específica de la familia.
4. La geometría debe corresponder a la unidad real de predicción o muestreo. `estimated_surface` está prohibido en MVP.
5. `value=0` es distinto de `value=null` y debe distinguirse visualmente en tests.
6. Cada respuesta está limitada en tamaño; agregaciones y caché se hacen en backend, con claves `model_id + data_version + rule_id + metric + time_window + tau`.
7. Las trazas exactas de antecedente deben verificarse con casos golden de la versión fijada de `ex_fuzzy`.

## 7. Enmiendas de A0 al ratificar v0.1 (2026-10-30)

1. **Renombrado:** `explanation.rule_firings[].strength` pasa a llamarse `firing_strength`, el mismo nombre que la métrica de `rule-map`.
2. **Sobre de los payloads:** todos llevan `schema_version`, `data_version` y `synthetic`. Si `synthetic: true`, la UI debe rotularlo.
3. **Datos ausentes:** `missing_reason` es un enumerado: `no_observation | invalid_observation | censored | missing_input | prediction_unavailable`.
   - `value=null` exige motivo, y un número nunca lleva motivo (0 ≠ null).
   - Las observaciones añaden `censoring` (`left | right`) para límites de detección.
4. **Geometría:** en v0.1, `geometry_support` vale `observed_point | observed_polygon | derived_aggregate`. `estimated_surface` no existe y la validación lo rechaza. El tipo de geometría tiene que cuadrar con el soporte.
5. **Semántica temporal de `rule-map`:**
   - `time` es el **instante de emisión** (`issued_at_utc`) y solo vale para `firing_strength`.
   - Los agregados usan una ventana semiabierta `from`/`to` = `[from, to)`.
   - `tau` va solo con `activation_frequency`.
   - Una combinación ambigua devuelve 422. Todas las fechas tienen que llegar en UTC explícito.
6. **`rule-trace`:**
   - Devuelve todas las reglas del modelo, cada una con `membership`, `modifier` y `effective_membership` (= μ^modifier) por antecedente, más `firing_strength` (la t-norma) y `effective_firing` (tras `rule_mode`).
   - Incluye `inference` (familia, t-norma, `rule_mode`, tolerancia, fallback y versión de ex_fuzzy) y `prediction.fallback_used`.
   - El validador comprueba la paridad con la t-norma (±1e-9) y que ningún `observed_at_utc` sea posterior a `issued_at_utc`.
7. **Comportamiento de ex_fuzzy 3.3.1** (verificado):
   - El regressor es TSK de orden cero con t-norma **producto** por defecto, no mínimo; el ejemplo de `MAP_EXPERIENCE.md` E1 es solo ilustrativo.
   - Si ninguna regla dispara, devuelve la media del target de entrenamiento.
   - Rechaza entradas no finitas. Con una entrada ausente no se hace inferencia (`missing_input`) y v0.1 no tiene firing parcial.
   - El GA puede devolver reglas con antecedentes idénticos; A4 decide cómo tratarlas.
8. **`ModelCard.coverage`** (`issued_from_utc`, `issued_to_utc`, `step_hours`) alimenta la timeline.
9. **Splits:** `SplitSpec` usa periodos semiabiertos con `embargo_hours`, y `RunManifest` exige `embargo_hours ≥ horizon_hours`. `MetricsReport` tiene un único split por informe, así que todos los estimadores se comparan con la misma partición.
10. **Fuera de v0.1:** `POST /api/v1/scenarios` (P1, AT-056).

## 8. Enmiendas de A0 en v0.2 (2026-10-30)

Son cambios aditivos y compatibles con v0.1: todos los campos nuevos son opcionales.

1. **`TaskInfo.model_id`:** el modelo que la API sirve para cada tarea (null mientras no haya ninguno). La web lo descubre desde `/api/v1/domains`, y `VITE_MODEL_ID` queda solo como override.
2. **`LinguisticVariable.domain`:** `[min, max]`, el universo de discurso. ex_fuzzy recorta las entradas a ese rango, así que un valor fuera de él recibe la pertenencia del extremo.
3. **`LinguisticTerm.params`:** documentada la semántica de ex_fuzzy. `trapezoidal` y `triangular` usan `[a, b, c, d]` (forma de trapecio). `gaussian` usa `[mean, std]` con μ = exp(−((x − mean)/std)²), sin el factor 1/2.
4. **`RuleDefinition.duplicate_of`:** el `rule_id` de la primera regla con antecedentes idénticos. Sustituye al marcador numérico en `metrics`. Las reglas duplicadas no se fusionan: el id posicional sigue alineado con el modelo.
5. **`fixtures/synthetic/rule_maps.json`:** respuestas rule-map de referencia generadas por el backend. Los tests de los clientes las usan para no reimplementar la agregación. Las fixtures se generan ya por el camino de producción (`atlas.ml.rules_export`, `atlas.explain`).
6. **Hora local ambigua en agregados** (vuelta atrás del DST, cuando la fuente da hora local sin desfase): la hora repetida mezcla dos horas reales, así que ambas horas UTC se escriben con `value=null`, `missing_reason=invalid_observation` y `validity_flag=ambiguous_local_hour`. Nunca con 0.
7. **Observaciones de agua (AT-020):**
   - Se admiten **columnas extra de identificación y procedencia** en la tabla canónica (`sample_id`, `observation_id`, `determinand_code`, `result_raw`, …): `validate_observations` comprueba las obligatorias y tolera las demás. `sample_id` es lo que impide que un join multiplique ejemplos.
   - `validity_flag` puede ser null en toda una fuente cuando esta no publica control de calidad (la API de agua no lo tiene). Eso no equivale a «válido verificado».
   - Una coordenada oficial fuera de la extensión del dataset (un marcador de posición) se publica como `geometry: null`, con `attributes.coordinate_flag` y los valores originales.
   - Queda pendiente un `available_at_utc` opcional (la `resultDate` del laboratorio), que se decidirá con el target de AT-021.
8. **Pendiente:**
   - términos `categorical`, hasta que una feature los necesite;
   - `rule_contribution` (A4 la verificó numéricamente, pero sigue sin exponerse; ver `docs/ml/rule_contribution.md`);
   - Mamdani en el contrato.

## 9. Enmiendas de A0 en v0.3 (2026-10-30): clasificación y horizonte 0

Son aditivas salvo dos relajaciones: `InferenceSpec.rule_mode` pasa a ser opcional y se admite `valid_at = issued_at`.

1. **Decisión de producto (el usuario, autor de ex_fuzzy):** NO₂ de Madrid deja de ser una regresión y pasa a ser una **clasificación en las categorías oficiales del Índice de Calidad del Aire (ICA)**, que están definidas por sus efectos sobre la salud.
   - La salida se etiqueta como «categoría ICA prevista».
   - Nunca se presenta como «riesgo sanitario» ni como probabilidad.
2. **`InferenceFamily.winning_rule_classifier`** (clasificador de ex_fuzzy):
   - grado de asociación = firing × peso de la regla (*dominance score*);
   - la clase la decide **una sola regla**, la de mayor asociación;
   - sin regla activa y con `allow_unknown`, no hay clase.

   `InferenceSpec` añade `rule_weighting` (`dominance_score|weight|none`) y `allow_unknown`. `rule_mode` solo aplica a TSK y Mamdani. `fallback` admite `unknown`.
3. **`TargetScheme` y `TargetClass`:** clases ordenadas y contiguas con límites, unidad, color oficial y fuente citada (`source_url`), más la convención de frontera `boundary`. Aparecen en `ModelRules.target_scheme`, obligatorio en clasificadores, y en `ModelCard.target_scheme`. `Consequent.type="class"` usa `term` como etiqueta, y `RuleDefinition.weight` guarda el peso de la regla.
4. **Trazas de clasificador:**
   - Cada `RuleTraceEntry` lleva `weight` y `association_degree`. El validador comprueba que asociación = firing × peso (±1e-9).
   - `TracePrediction` lleva `label` y `winning_rule_id`, y el validador exige que la regla ganadora sea la de **mayor asociación positiva** (la primera en caso de empate, como `argmax`).
   - «Sin clase» es `label=null` con `missing_reason=prediction_unavailable`.
5. **Series y predicciones:**
   - `SeriesPoint` añade `observed_label` y `predicted_label`, y `PredictionRecord` añade `prediction_label`.
   - Una etiqueta cuenta como predicción: un null exige motivo y una etiqueta no lo lleva.
   - `TaskInfo.task_type` (`regression|classification`) y el registro de modelos publicados lo propagan a `/domains`.
6. **Horizonte 0 (Water, inferencia sobre la misma muestra):** `horizon_hours ≥ 0` en `TaskInfo`, `RunManifest`, `SeriesResponse` y el registro. `valid_at` nunca puede ser anterior a `issued_at`, y la regla `embargo ≥ horizonte` se mantiene.
7. **Pendiente en servicios:** que `publish` y la API sirvan clasificadores (predicciones con etiqueta, tarjeta con `target_scheme`, trazas del clasificador). Se implementará con el wrapper de A4 (AT-041c).

## 10. Enmiendas de A0 en v0.4 (2026-10-31): atribución, modelos parciales y backends creativos

Son aditivas y compatibles con v0.3: todos los campos nuevos de modelos existentes tienen valor por defecto (los payloads v0.3 siguen validando; lo prueba `tests/contracts/test_models_v04.py`). Cambian el valor de `SCHEMA_VERSION` (0.4.0) y el enumerado `MissingReason`, que gana `not_modelled`. Solicitudes de origen: issue #56 y `docs/qa/mvp_checklist.md` (carencias conocidas).

**Metadatos**

1. **`Attribution{text, license, url}`** en `EntityCollection.attribution` y `ModelCard.attribution`. `license` es null cuando la fuente no declara ninguna, y entonces el texto lo dice (NYC TLC, documento ICA del MITECO); nunca se inventa una licencia. `publish` la rellena desde `configs/<dominio>/attribution.json` (formato `layout.PublishMetadata`, construido desde `ATTRIBUTION.md`).
2. **`TimeCoverage.regular`** (por defecto `true`). `publish --irregular-times` lo deja en `false`: las emisiones son instantes de muestreo, `step_hours = 1` es solo el paso más fino que el contrato expresa, y los mapas deben usar agregados por ventana, no instantes.
3. **`TargetScheme.kind`** (`official_index | percentile_reference | analytical`) y **`short_name`**. ICA: `official_index` / «ICA»; nivel NYC: `percentile_reference` / «Nivel relativo». Cambia cómo se redactan las clases (una clase oficial frente a un nivel relativo a lo habitual).
4. **`TargetClass.merged_from`**: etiquetas de las categorías oficiales que agrupa la clase. Cierra QA-5: «Desfavorable o peor» (121-1000 µg/m³) lleva `["Desfavorable", "Muy desfavorable", "Extremadamente desfavorable"]` y una descripción que dice qué agrupa y con qué rangos.
   - **Cómo se aplicó sin reentrenar.** El bloque `target_scheme` de `configs/air/attribution.json` se aplica en el publish a la **copia publicada** de `rules.json` (y a `card.json`). Primero se copia `rules.json` del run verificando su `SHA256SUMS`, después se reescribe con el esquema enriquecido (etiquetas, límites, colores y reglas idénticos) y el `SHA256SUMS` publicado se recalcula sobre los ficheros publicados. El directorio del run queda intacto, y `publish.json` guarda `rules_json_patch` con el sha256 del `rules.json` original y los campos tocados.
5. **`EntityProperties.modelled`** (`true | false | null`; null = publicado antes de v0.4). `false`: la entidad está en el fichero de geometrías pero el modelo no tiene datos para ella. `publish --include-unmodelled-entities` las incluye (solo si tienen geometría) para dibujarlas como «sin modelo». NYC sirve 263 zonas con polígono, 110 con modelo y 153 `modelled: false`.
6. **`MissingReason.not_modelled`**. En las entidades `modelled: false`, `rule-map`, `rule-territories`, `predictions`, `observations` y `rule-trace` devuelven `value`/`prediction` null con `missing_reason = not_modelled` (nunca un número, nunca 0); `n_valid = 0`. `rule-trace` devuelve una traza sin entradas ni reglas. `series` y `scenarios` no tienen nada que servir: 404 y 422 respectivamente.
7. **`RuleTrace.observed` / `observed_label`**: el objetivo observado en `valid_at_utc`, si se conoce (de `predictions.parquet`). No estaba disponible en la emisión (salvo horizonte 0), así que no entra en la inferencia.

**Vistas nuevas** (todas con la semántica temporal de §7.5: instante de emisión `time`, o ventana semiabierta `[from, to)`, UTC explícito, 422 si es ambiguo)

8. **`GET /api/v1/predictions?task_id&time`** (o `from`/`to`): una `Feature` por entidad con `prediction`, `prediction_label`, `observed`, `observed_label`, `unit`, `issued_at_utc`, `valid_at_utc`, `missing_reason`. Con `time`, todas las filas son de esa emisión. Con ventana (pensado para tareas irregulares, válido en cualquiera), cada entidad trae su **última** muestra en la ventana, con su propio `issued_at_utc`. Una entidad sin fila: `prediction` null con `no_observation`. Igual que `series`: un clasificador publica `prediction` null y la etiqueta.
9. **`GET /api/v1/observations?task_id&time`** (modo Data): para cada entidad, el objetivo observado y las entradas del modelo en esa emisión, tal como se publicaron (`inputs.parquet` y `predictions.parquet`), con unidad, fuente y `observed_at_utc = issued_at_utc − lag`. **El objetivo se observa en `valid_at_utc` (= emisión + horizonte), no en la emisión.** No es una predicción ni una interpolación. Un valor ausente es null con `no_observation`; null nunca es 0.
10. **`GET /api/v1/rule-territories?model_id&from&to&measure&tau`** (E2). Ventana ≤ 366 días, `tau` por defecto 0,5.
    - Por entidad y regla: `mean_activation`, `activation_frequency` (con `tau`) y, **solo en clasificadores**, `winner_share` (fracción de registros válidos en los que la regla decidió la clase; suma ≤ 1 porque un registro sin regla activa no tiene ganadora).
    - **Denominador:** `n_valid` = registros de la entidad en la ventana con todas las entradas presentes; `n_records` los publicados. Las tres medidas se calculan sobre `n_valid`.
    - **Regla dominante:** argmax **solo de la medida pedida** (`measure`); valores a menos de `1e-12` empatan y gana la de menor posición (R01 antes que R02). Null si `n_valid = 0` o la medida es 0 en todas las reglas. En un regresor TSK es el argmax del firing y nunca una «contribución». `winner_share` pedido a un regresor es 422.
    - Los territorios **se solapan**: la respuesta lo declara y no son una partición. La respuesta repite `measure`, `tau`, `tie_break`, `denominators` y `notes`. El validador del contrato recalcula la regla dominante.
11. **`POST /api/v1/scenarios`** (E5): `{model_id, entity_id, at, overrides: {feature: valor}}`. Vuelve a ejecutar la **inferencia real de ex_fuzzy** sobre la fila publicada modificada (`atlas.explain`) y devuelve:
    - `original` y `modified` (`RuleTrace`);
    - `inputs`, con `origin: observed | overridden`;
    - `rule_deltas` (firing y, en clasificadores, asociación, modificado − original);
    - `prediction_change`;
    - `synthetic_what_if: true`;
    - `label`: «respuesta del modelo ante entradas modificadas — no efecto causal ni predicción».

    Validación (422): solo variables del modelo, valores finitos, dentro del `domain` de la variable (extremos incluidos). Sin overrides, `modified == original`. Un override desactiva `observation_ids`, `observed` y `observed_at_utc` de lo modificado (`source_id = what_if_override`), y la traza modificada lleva un aviso. No escribe nada en disco. Entidad sin modelo: 422; entidad o emisión inexistentes: 404.
12. **`GET /api/v1/rule-stories?model_id&from&to&tau&limit`** (§8, Rule Stories). Frases con plantilla, sin modelo de lenguaje, en español, que **solo describen activaciones**. Cada historia lleva `numbers` (las cifras del texto), `queries` (las peticiones `rule-map` / `rule-territories` exactas) y `checks` (qué recuento de qué propiedad de esas respuestas da cada cifra), de modo que se puede auditar sin confiar en el texto. Tipos y puntuación documentados en `atlas.services.stories` y en `score_definition`: `co_activation_burst` (varias entidades por encima de `tau` a la vez durante emisiones consecutivas; solo en rejillas regulares), `localized_rule` y `territory_leader`. Se ordena por puntuación (desempate: tipo y posición de la regla), `limit` ≤ 50 (por defecto 10) y `n_candidates` dice cuántas había. La puntuación ordena qué mostrar; no es un test estadístico ni una probabilidad.

**Fuera de alcance, a propósito:** comparar dos reglas del mismo modelo (Rule Duel, E4) ya se hace con dos llamadas a `rule-map`; comparar modelos exige un mapeo explícito de reglas y no existe endpoint. `rule_contribution` y `dominant_contributor` siguen sin exponerse.

## 11. Enmienda de A0 en v0.4.1 (2026-11-02): varias tareas por dominio

Aditiva y compatible con v0.4 (`SCHEMA_VERSION` 0.4.1; los artefactos 0.4.0 publicados siguen sirviéndose sin republicar). Origen: AT-070 (Alemania como segunda tarea `air` junto a Madrid).

1. **`TaskInfo.title`** (opcional, null en servidores anteriores): título de la tarea, que nombra su territorio («Madrid air quality», «Germany air quality (EEA)»). Sale del `title` del registro. `DomainInfo.title` es el de la tarea cuando el dominio tiene una sola y el título genérico del dominio («Air quality») cuando tiene varias.
2. **`GET /api/v1/entities?domain&task_id`**: `task_id` opcional. Sin él, un dominio con varias tareas responde 422 con los `task_id` posibles, en vez de mezclar las entidades de dos modelos en un mapa; con una sola tarea, todo sigue igual. `task_id` de otro dominio: 422; desconocido: 404. El resto de endpoints ya iban por `task_id` o `model_id`.
3. **Orden de las tareas** en `DomainInfo.tasks`: primero la tarea por defecto del dominio (`layout.DEFAULT_TASKS`; aire: `madrid_no2_h6`, decisión del autor del 2026-11-02), después el resto por `task_id`. La web abre un dominio en su primera tarea. No cambia el esquema.


## 12. Enmienda de A0 en v0.5 (2026-11-02): rediseño de la web: legibilidad, importancia, resumen, horizontes

Aditiva sobre v0.4.1 (`SCHEMA_VERSION` 0.5.0): los artefactos anteriores siguen sirviéndose. Los dos endpoints nuevos responden 404 con un motivo mientras un modelo no tenga su fichero precalculado.

Origen: la revisión del autor del 2026-11-02 («beta de una beta»): no se entendía qué se mira, las variables salían con su nombre interno, no se veía cuánto importa cada patrón (en total y por zona), faltaba un resumen de la calidad del aire y el horizonte no estaba claro.

Decisiones del autor:
- pestañas por territorio, con el Resumen primero (Resumen | Patrones | Predicción | Explorar);
- importancia medida como «decide y acierta», nunca como activación: aún no está claro empíricamente qué significa una activación frente, por ejemplo, a una medida de incertidumbre epistémica;
- un selector de horizontes discretos.

1. **Nombres legibles de las entradas.**
   - `LinguisticVariable.label` y `.description` son opcionales; si faltan, la web muestra `feature`. Por ejemplo, «NO₂ hace 3 h» y «Concentración horaria de NO₂ en la estación, medida 3 h antes de la última hora disponible a la hora de emisión».
   - Se fijan al publicar desde el bloque `features` del fichero `--metadata` (`layout.PublishMetadata.features`). Igual que el esquema de clases en v0.4, parchean la copia publicada de `rules.json`, sin reentrenar.
2. **Territorios y horizontes.**
   - `TaskInfo.territory` y `.territory_title` son opcionales y salen del registro (`RegistryEntry.territory`, que se fija al publicar).
   - Las tareas de un dominio con el mismo `territory` difieren solo en `horizon_hours`: la web muestra un único territorio con un selector discreto de horizonte sobre esas tareas.
   - Ejemplo: `madrid_no2_h1`, `madrid_no2_h3`, `madrid_no2_h6`, `madrid_no2_h12` y `madrid_no2_h24` forman `madrid`.
   - La tarea por defecto del territorio sigue siendo la que fija §11.3.
3. **`GET /api/v1/models/{model_id}/importance` → `RuleImportanceResponse`.** Mide cuánto pesa cada regla en las predicciones **publicadas** del modelo. Se precalcula al publicar (`importance.json`).
   - **Clasificador (`measure = winning_rule`):** cada predicción la decide una sola regla, la de mayor activación × peso, que es la inferencia de ex_fuzzy.
     - `decided_share` es la fracción de predicciones que decide la regla.
     - `accuracy` es la fracción de esas decisiones, con observación, cuya clase es la observada.
   - **Regresión TSK de orden 0 aditiva (`measure = weighted_average`):**
     - `mean_weight_share` es la media de f_r/Σf. Es la cuota exacta de la regla en la media ponderada, y en cada predicción suman 1.
     - La regla «decide» la predicción en la que su cuota es la mayor; `mae` es el error de esas predicciones.
   - **Por variable:** `decided_share` es la fracción de decisiones tomadas por reglas que usan la entrada. En regresión es la cuota media sumada de esas reglas.
   - **Por entidad («por zonas»):** las mismas medidas dentro de cada entidad.
   - **Predicciones sin regla:** las horas con entradas completas en las que no dispara ninguna regla cuentan aparte, en `n_no_rule`, y no se atribuyen a ninguna regla.
   - **Predicciones retenidas:** las horas en que dispara una regla pero la publicación retiene la predicción (en NYC, celdas sin nivel de referencia) cuentan en `n_withheld`. Tampoco se atribuyen a ninguna regla ni entran en `n_predicted`.
   - Es fiel a la inferencia, no causal. **No usa la activación como importancia.**
4. **`GET /api/v1/summary?task_id` → `SummaryResponse`.** Describe qué dicen los datos, sin el modelo. Es la distribución de la variable observada de la tarea en todo su histórico, precalculada al publicar (`summary.json`).
   - **Valores:** por las clases del esquema de la tarea (`classes`, con una cuota por clase) o, si la variable es numérica, por cuantiles (p10, p25, p50, p75, p90 y media).
   - **Grupos:** total, año, mes, hora y día de la semana (en hora local, `timezone`) y entidad.
   - Cada valor observado cuenta una vez por entidad e instante.

**Pendiente:** términos `categorical`; Mamdani; `rule_contribution`; un `available_at_utc` opcional para Water; una medida de incertidumbre de la predicción (la sugiere el autor como alternativa futura a la activación).

## 13. Enmienda de A0 en v0.5.1 (2026-11-02): términos legibles, clases traducidas y regla que decide cada predicción

Aditiva sobre v0.5 (`SCHEMA_VERSION` 0.5.1): todos los campos nuevos son opcionales y los artefactos anteriores siguen sirviéndose.

Origen: la segunda revisión del autor («aún queda bastante tomate») y la auditoría visual de A0. En la web seguían saliendo:
- nombres internos de términos (`<=L`, `Bajo>L`, `Low`);
- clases EAQI en inglés en una interfaz en castellano;
- predicciones sin la regla que las decide, aunque el diferenciador de Atlas son las reglas sobre el mapa.

1. **`LinguisticTerm.label`.**
   - Nombre visible del término; `name` sigue siendo la clave a la que se refieren las reglas.
   - Se fija al publicar (o con `atlas.services.enrich`) desde `FeatureMetadata.terms` (`{nombre: etiqueta}`) del fichero `--metadata`, como `LinguisticVariable.label` en v0.5.
2. **`TargetClass.display_label`.**
   - Nombre visible de la clase cuando la etiqueta oficial está en otro idioma (EAQI: `Good` → «Buena»).
   - `label` sigue siendo la clave y el nombre oficial; la web lo muestra junto a la fuente del esquema.
   - Se fija desde `ClassMetadata.display_label`.
3. **`PredictionProperties.decided_by_rule_id`.**
   - La regla que decidió esa predicción, con la misma medida que `/importance`: en un clasificador, la regla ganadora (mayor activación × peso); en TSK, la regla con mayor cuota f_r/Σf.
   - Es nulo sin predicción, si no dispara ninguna regla y si la predicción se retiene.
   - Sirve para decir «esta predicción la decidió R04». No es una causa ni una contribución: es la regla que ganó la inferencia.

## 14. Enmienda de A0 en v0.5.2 (2026-11-02): tasa base de las clases en el mismo periodo que el acierto

Aditiva sobre v0.5.1 (`SCHEMA_VERSION` 0.5.2).

**`RuleImportanceResponse.observed_class_shares`** (solo clasificadores) es la cuota de cada clase observada entre las predicciones publicadas que tienen observación, es decir, la unión de los `n_checked` de las reglas.
- **Para qué.** La web dice «acierta el 92 % (la clase aparece en el 78 % de los casos)». La tasa base debe salir de las mismas predicciones que el acierto, no de todo el histórico de `/summary`, que cubre otros años.
- **NYC.** Además, NYC no tiene clases en `/summary`; con este campo también tiene tasa base.
- **Cálculo.** Se calcula al publicar, o con `atlas.services.enrich`, en `importance.json`.

## 15. Enmienda de A0 en v0.6 (2026-11-06): nombres en inglés servidos por la API

Aditiva sobre v0.5.2 (`SCHEMA_VERSION` 0.6.0): todos los campos nuevos son opcionales (null por defecto), los payloads v0.5.2 siguen validando (`tests/contracts/test_models_v06.py`) y los artefactos anteriores siguen sirviéndose.

Origen: la web ya tiene el conmutador ES/EN (`tr(es, en)`, PRs #92–#94), pero en inglés seguían saliendo en castellano los **datos** que manda la API: nombres de variables y términos, clases, el nombre del esquema, la variable del resumen y los territorios.

1. **Campos `*_en`**, junto a su versión en castellano. La web muestra el inglés cuando la interfaz está en inglés y, si falta, cae a la versión de siempre (`localized(es, en)` en `apps/web/src/i18n`):
   - `LinguisticTerm.label_en` (si falta: `label`, después `name`);
   - `LinguisticVariable.label_en` y `.description_en` (si falta: `label` / `description`, después `feature`);
   - `TargetClass.display_label_en` y `.description_en`; `label` sigue siendo la clave y el nombre oficial (si falta: `display_label`, después `label`);
   - `TargetScheme.name_en` y `.short_name_en` (el nombre corto del NYC es «Nivel relativo»);
   - `SummaryResponse.label_en`;
   - `TaskInfo.territory_title_en`, desde `RegistryEntry.territory_title_en`. `TaskInfo.title` ya está en inglés y no lleva par.
2. **De dónde salen.** De los mismos bloques del fichero `--metadata` (`layout.PublishMetadata`): `FeatureMetadata.label_en`, `.description_en` y `.terms_en` (por nombre de término, también de un término sin etiqueta en castellano); `ClassMetadata.display_label_en` y `.description_en`; `SchemeMetadata.name_en` y `.short_name_en`; `SummaryMetadata.label_en`. `--territory-title-en` va al registro (en `publish` y en `enrich`). Como en v0.5, parchean la copia publicada de `rules.json` y `card.json`, sin reentrenar.
3. **Guardas.** Un `label_en` que dice una edad («4 h ago») tiene que coincidir con el `lag_hours` del `feature_spec` y con la edad que dice la etiqueta en castellano («hace 4 h»); si no, `publish` y `enrich` la rechazan. Un `terms_en` con un término que la variable no tiene también se rechaza.
4. **Backfill sin recalcular.** `python -m atlas.services.enrich --labels-only` aplica solo los campos visibles (reglas, tarjeta, y etiqueta y clases de `summary.json`): no recalcula `importance.json` ni los números de `summary.json` y no lee la tabla de variables. Reescribe `SHA256SUMS` al final y comprueba `verify`; `publish.json` lo anota en `v06`.
5. **Nombres de las clases en inglés.**
   - ICA: el MITECO no publica nombres en inglés; su página en inglés deja los nombres de las categorías en castellano. Se traducen: «Buena» → Good, «Razonablemente buena» → Reasonably good, «Regular» → Moderate, «Desfavorable o peor» → Unfavourable or worse.
   - EAQI: sus nombres oficiales ya están en inglés (Good, Fair, Moderate, Poor or worse), así que en inglés se muestran tal cual.
   - Nivel NYC: low / normal / high / very high.

**Siguen en castellano en inglés:** los textos que la API genera con plantilla (las notas de `/summary` y las historias de `/rule-stories`), los textos de atribución y los nombres de las categorías oficiales que agrupa una clase (`merged_from`, que son claves oficiales del ICA). Quedan fuera de esta versión. Los avisos de la tarjeta y las notas de `/rule-territories` ya estaban en inglés.

## 16. Enmienda de A0 en v0.6.1 (2026-11-09): créditos de las fuentes en inglés

Aditiva sobre v0.6 (`SCHEMA_VERSION` 0.6.1): `Attribution.text_en`, opcional, el mismo crédito en inglés. La web lo
muestra en el pie cuando la interfaz está en inglés y, si falta, muestra `text`. La licencia y la URL no cambian. Los
textos están en `configs/<dominio>/attribution*.json`; `python -m atlas.services.enrich --labels-only --metadata …`
los añade a `card.json` y `entities.geojson` de un modelo publicado emparejando cada crédito por su `text` (no cambia
qué fuentes se citan ni su orden, ni ningún número).

## 17. Enmienda de A0 en v0.6.2 (2026-11-09): explicación de las reglas escrita por una IA

Aditiva sobre v0.6.1 (`SCHEMA_VERSION` 0.6.2): un modelo nuevo, `ModelExplanation`, y un endpoint nuevo; ningún campo
existente cambia (`tests/contracts/test_models_v062.py`).

1. **`GET /api/v1/models/{model_id}/explanation`** → `ModelExplanation`; 404 cuando el modelo no existe o no tiene
   explicación, como `/importance` antes de v0.5. La web lo muestra en Patrones encima de las reglas («Qué hacen estas
   reglas» / "What these rules do") y no muestra nada si es 404.
2. **Campos.** `model_id`, `data_version`, `synthetic`, `template_version` (de la cabecera de
   `configs/explanations/TEMPLATE.md`), `generated_by` (`tool`, `tool_version`, `model`: el texto lo escribe una IA,
   Claude a través de la CLI de Claude Code, a partir de los ficheros publicados del modelo; no es un análisis humano),
   `generated_at_utc`, `input_sha256` (sha256 del JSON de contexto, canónico: claves ordenadas, sin espacios),
   `reviewed` (true cuando una persona lo ha leído contra las reglas y métricas) y `es` / `en`, cada uno
   `{headline, summary: [párrafos], points: [puntos]}`.
3. **Dónde vive.** En git, `configs/explanations/<model_id>.json`, junto a la plantilla; la API lo lee de ahí
   (`ATLAS_EXPLANATIONS_DIR`). No es un artefacto publicado: no entra en `SHA256SUMS` ni en la release `qa-artifacts`.
4. **Cómo se escribe.** `scripts/explain_model.py --model-id <id>` (`make explain MODEL_ID=…`, `docs/reproduce.md`). El
   contexto sale solo de `rules.json`, `importance.json`, `card.json` (métricas), `summary.json` y `registry.json`; cada
   número lleva su `display` en los dos idiomas; la comparación con las referencias es la del Informe de rendimiento de
   la web (persistencia, persistencia a 24 h, regresión logística o lineal y bosque aleatorio, las variantes elegidas
   en validación) con su `standing` ya calculado. La respuesta se valida antes de guardarse (esquema, límites, redacción,
   cifras = `display` ±1 en la última cifra, reglas existentes); si falla dos veces no se escribe nada.
5. **Honestidad.** La web pone debajo del texto: «Texto redactado por Claude (IA) a partir de las reglas y métricas
   publicadas de este modelo; [revisado / todavía no revisado] por una persona.» Un modelo republicado invalida su
   explicación: `tests/integration/test_explanations.py` compara `input_sha256` con el contexto reconstruido.
6. **Mezcla de reglas (v0.7).** La plantilla v2 ya dice cómo describir un `rule_mixture_classifier` (`class_weights` por
   regla; las reglas suman su apoyo a cada categoría, ninguna decide sola, un peso no es «importancia» ni «evidencia en
   contra»). `scripts/explain_model.py` rechaza esa familia hasta que v0.7 fije sus campos.

## 18. Enmienda de A0 en v0.7 (2026-11-09): mezcla de reglas (`rule_mixture_classifier`)

Aditiva sobre v0.6.2 (`SCHEMA_VERSION` 0.7.0), con dos relajaciones: `TracePrediction` admite una etiqueta sin
`winning_rule_id` cuando trae `class_scores`, y `RuleImportance.n_decided` / `decided_share` (con
`VariableImportance.decided_share` y `EntityRuleImportance.decided_share`) pasan a ser opcionales porque no existen en
la nueva familia. Los payloads v0.6.2 siguen validando (`tests/contracts/test_models_v07.py`) y los modelos ya
publicados se siguen sirviendo sin republicar.

Origen: decisión del usuario (2026-11-09) de llevar la mezcla de reglas a todos los clasificadores de la demo (Alemania
+1/+3/+6/+12/+24 h y NYC +1/+3/+6/+24 h), tras AT-041i (`docs/ml/rule_mixture.md`, que en su §6 describía lo que el
contrato necesitaba). Reentrenamiento y resultados: `docs/ml/rule_mixture_serve.md` (AT-041j). NYC +6 h sigue siendo de
regla ganadora tras un reintento con umbral prerregistrado que no lo superó (§7 de ese documento): las dos familias se
sirven a la vez, cada tarea según el `inference.family` de su `rules.json`.

1. **Familia `rule_mixture_classifier`** (ex_fuzzy `inference='mixture'`, PR 44 de ex-fuzzy): la puntuación de la clase
   c es `b_c + Σ_r W[r, c] · firing_r` y se predice la primera clase de mayor puntuación. **Ninguna regla decide sola.**
   - `InferenceSpec`: `allow_unknown` obligatorio, sin `rule_weighting` ni `rule_mode`; `mixture_weights`
     (`non_negative` | `unconstrained`) y `mixture_C` (> 0, el `C` de la penalización L2). `fallback` es `unknown`
     con `allow_unknown` (sin regla activa no hay clase) y `largest_bias` si no (nuevo valor del enumerado).
   - Los pesos son coeficientes de un modelo lineal ajustado (regresión logística multinomial sobre los firings de la
     muestra de ajuste): no son probabilidades, confianzas, contribuciones causales ni riesgos. **No se sirve el
     softmax** de las puntuaciones en ningún campo.
2. **Documento de reglas.**
   - `RuleDefinition.class_weights`: `W[r, c]` por clase del `target_scheme` (en su orden), tal como se ajustaron. Puede
     ser negativo con pesos `unconstrained`, así que el `weight` de v0.3 (≥ 0, multiplica el firing) no lo puede llevar:
     en esta familia `weight` es null.
   - `RuleDefinition.class_weights_centred`: `W[r, c] − media_c W[r, c]`. Sumar una constante a todos los pesos de una
     regla no cambia ninguna predicción, así que pesos `≥ 0` y libres describen la misma familia de modelos (solo cambia
     la penalización; de ahí que coincidan en el 99,4-99,99 % de las filas). En la forma centrada una regla **apoya**
     (+) unas clases y **suprime** (−) otras respecto al resto, gane el brazo que gane, y las dos variantes se comparan
     igual. «Supresión» (la regla baja la puntuación de esa clase frente a las demás) no es «evidencia en contra» ni una
     probabilidad.
   - `RuleDefinition.strongest_class`: la clase de mayor peso (la primera en el orden del esquema si empatan); null si
     todos sus pesos son iguales (una regla duplicada, con pesos todos cero): no cambia ninguna predicción.
   - `ModelRules.class_bias`: `b_c` por clase (centrados a media 0), la puntuación de una fila que no activa ninguna
     regla.
   - `consequent` sigue siendo la clase que la búsqueda genética asoció a la regla (solo sirve a la búsqueda y a su
     poda): **no entra en la predicción** y no se debe presentar como la conclusión de la regla.
   - Validador: claves exactamente las clases del esquema y en su orden; forma centrada = pesos − media (±1e-9);
     `strongest_class` coherente; sin pesos negativos con `non_negative`; una regla `duplicate_of` lleva pesos cero.
3. **Traza (`rule-trace`).** Cada `RuleTraceEntry` lleva `class_weights`, `class_contributions` = `W[r, c] · firing`
   (lo que la regla suma a cada clase; ex_fuzzy `mixture_contributions`) y `class_contributions_centred` (lo mismo con
   los pesos centrados); `weight` y `association_degree` son null. `TracePrediction` lleva `class_scores` (ex_fuzzy
   `mixture_scores`), `class_bias`, `label`, `top_rule_id` y `top_rule_share`; `winning_rule_id` es **siempre null**.
   El validador comprueba contribuciones = pesos × firing, puntuaciones = sesgo + Σ contribuciones (±1e-9), que la
   etiqueta es la primera de mayor puntuación, que `fallback_used` equivale a «no se activa ninguna regla» y la regla
   principal.
4. **Regla que más apoya la predicción (`top_rule_id`, `top_rule_share`)**, en la traza, en `GET /predictions` y en
   `/importance` con una sola definición (`models.top_contributor`): la regla con la **mayor contribución centrada
   positiva a la clase predicha** (la primera en el orden de reglas si empatan exactamente) y su fracción de la suma de
   las contribuciones centradas positivas a esa clase (el sesgo no cuenta). Null sin predicción o si ninguna regla apoya
   la clase predicha (gana por su sesgo y por lo que las reglas quitan a las demás clases).
   - **Refinamiento sobre §6 de `rule_mixture.md`:** se define sobre la forma centrada y no sobre `W` tal cual, porque la
     contribución bruta a una clase cambia al sumar una constante a los pesos de una regla (sin cambiar ninguna
     predicción): con pesos `≥ 0` una regla que suprime una clase frente a la ganadora le seguiría «sumando». Y la
     fracción no es «de la puntuación de la clase»: con sesgo y pesos con signo esa puntuación puede ser negativa o
     cercana a cero, así que el denominador son las contribuciones centradas positivas.
   - En `PredictionProperties`, `decided_by_rule_id` es null para esta familia: **la web nunca debe decir que la regla
     «decidió»** la predicción; es la regla que más la apoya.
5. **Importancia (`measure = rule_mixture`).** Por regla: `n_top` / `top_contributor_share` (predicciones en las que es
   la regla principal) con `n_checked` / `accuracy` sobre esas, y `n_decisive` / `decisive_share` (predicciones cuya
   clase cambiaría si los pesos de la regla fueran cero). El decisivo es exacto y barato: al publicar, ex_fuzzy vuelve a
   puntuar cada fila con la fila de `coef_` de la regla a cero (`RuleMixture.predict`, una multiplicación de matrices
   más por regla), y la tabla de activaciones guarda `is_decisive`. Varias reglas pueden ser decisivas para una
   predicción y ninguna para otra: las fracciones no suman 1. Por variable: `top_contributor_share` (la regla principal
   usa la entrada) y `decisive_share` (al menos una regla que la usa es decisiva). `n_no_top_rule` cuenta las
   predicciones sin regla principal (`Σ n_top + n_no_top_rule = n_predicted`). Las medidas de regla ganadora siguen
   igual para los modelos de regla ganadora.
6. **Ficheros publicados.** `activations/`: `entity_id, issued_at_utc, rule_id, firing_strength, centred_contribution`
   (a la clase predicha; null sin predicción)`, is_decisive, missing_reason` (sin `weight`, `association_degree` ni
   `is_winner`). `predictions.parquet` añade `top_rule_id` y `top_rule_share` (null donde la etiqueta es null o se
   retiene). `GET /rule-territories` con `measure=winner_share` responde 422 para esta familia; `mean_activation` y
   `activation_frequency` siguen igual.
7. **What-if.** `POST /scenarios` vuelve a ejecutar ex_fuzzy sobre la fila modificada; las trazas original y modificada
   llevan sus puntuaciones y contribuciones, `PredictionChange` añade `original_top_rule_id` / `scenario_top_rule_id`, y
   `RuleDelta` da los deltas de firing (la asociación es null).
8. **Dependencia.** `pyproject.toml` fija `ex-fuzzy==3.4.0` de PyPI, la primera versión con la mezcla (PR 44: el código
   del commit `5409bb8` más el cambio de versión; antes la rama se fijaba por commit, `20c1095` y luego `5409bb8`). Con ese
   código los modelos servidos (regla ganadora, regresión y las mezclas ajustadas con `20c1095`) dan las mismas tablas de
   activación y predicciones bit a bit (`python -m atlas.ml.publish_parity --tables`). `exfuzzy_version()` registra
   `3.4.0`; cada modelo conserva en `rules.json` y `card.json` la versión con la que se ajustó.
