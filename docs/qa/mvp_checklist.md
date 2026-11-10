# Checklist Go/No-Go del MVP

Estado a **2026-10-31**, rama `a6/AT-060-062-qa-demo` sobre `main` (`b75dc00`). Autor: A6. **Revisado el 2026-11-05** sobre `main`
(`971be00`, contrato v0.5.2): las filas que cambiaron lo dicen en su texto; ver «Revisión del 2026-11-05» al final. Criterios de
`MASTER_PLAN.md` §10 y `MAP_EXPERIENCE.md` §7, más los antipatrones de §9. «Sí» solo si hay evidencia ejecutable o
verificada a mano; «Parcial» y «No» se explican. Las pruebas citadas están en `tests/integration/` y corren con
`make qa` (necesitan los modelos publicados; CI los salta).

Veredicto: **GO condicionado** para el MVP de Madrid con Water y NYC como pilotos publicados. No hay un criterio en «No»
que bloquee, pero hay **cuatro «Parcial»** (dos tras la revisión del 2026-11-05) y **siete hallazgos** (uno de gravedad media; ver el final de este documento; todos resueltos a 2026-11-05) que A0 debe decidir antes de
una demo pública. Nada de lo hallado afecta a la corrección numérica de las activaciones.

## MASTER_PLAN §10 (definición de terminado)

| # | Criterio | Estado | Evidencia y matiz |
|---|---|---|---|
| 1 | Reproducción local documentada con `make demo`, sin credenciales ni APIs de pago | **Sí, con la cadena larga sin re-ejecutar** | `make demo` (este PR, `scripts/qa/demo.sh`): API en artifacts mode + web construida, Ctrl-C para ambos, falla con un mensaje claro si faltan los publicados. Probado con los tres modelos reales. `make reproduce ARGS=--check` verifica 19 etapas (módulos, opciones, configs, entradas) y `--smoke` republica en un temporal el run Water anterior (`water-do-chrono-temp-seed0`, ya no registrado) con resultado idéntico. **No se re-ejecutó ningún entrenamiento** (decisión de A0); los tiempos y RSS son los de `docs/`. El mapa base necesita internet (OpenFreeMap); sin él, fondo liso |
| 2 | Pipeline Madrid real, ≥ 12 meses alineados, checks de validez | **Sí** | Aire horario y meteo 2019-2025 (`docs/air/`, PRs #30, #35); 210 072 filas publicadas en 2025; informes de calidad por fuente |
| 3 | Modelo ex_fuzzy con split cronológico y comparación con persistencia + gradient boosting | **Sí, y pierde contra GB** | Madrid ICA, test 2025: ExFuzzy macro-F1 0,329; persistencia 0,294; HGB 0,373; random forest 0,374. NYC: ExFuzzy 0,412, persistencia 0,425, HGB 0,372 (HGB con submuestreo 0,409, LR con submuestreo 0,447). Water (modelo servido desde 2026-10-31, `exfuzzy-uk_water_do-fx-w-unique-seed0`, sin reglas repetidas): ExFuzzy MAE 0,635 (RMSE 0,932; el modelo anterior, 0,630), HGB 0,562, random forest 0,548. Fuente: `metrics.json` de cada modelo (PRs #40, #44, #48, #49). El cambio de regresión NO₂ a clasificación ICA es decisión de producto (CONTRACTS §9). La web no lo presenta como «mejor modelo» |
| 4 | Dashboard con valores observados, predicción y dos modos de mapa distintos (predicción y activación) | **Sí** (2026-11-05) | Los dos modos existen y son distintos en título, unidad y leyenda (`test_web_smoke.py`). Los valores observados tienen ahora su propia vista: Explorar → «Datos observados», servida por `GET /observations` (contrato v0.4), con el objetivo en su hora de validez, las entradas del modelo y «sin dato» con su motivo (captura `qa-*-explorar-data.png`) |
| 5 | Rule Spotlight real: puntos oficiales, intensidad calculada por la librería, leyenda 0–1, timeline y clic con cada antecedente y su pertenencia | **Sí** | `test_real_map_parity.py` (mapa = tabla = traza con ex_fuzzy), capturas `qa-madrid-rules.png`, panel «¿Por qué aquí?» (A5, PR #28, #38, #47) |
| 6 | Sin superficies continuas falsas con datos puntuales; missing explícito | **Sí** | `test_real_geometry_support.py` (sin `estimated_surface`, tipo = soporte, sin geometría nula en el mapa); anillos huecos «sin dato» con motivo en las capturas; agua solo en ventanas |
| 7 | Al menos un test de paridad entre la activación de ex_fuzzy y el valor coloreado | **Sí** | Backend: `test_firing_strength_map_equals_activations_table_and_rule_trace` y `test_window_aggregates_equal_a_recomputation_with_n_valid` (los tres modelos reales). Frontend: `App.real.test.tsx` compara lo pintado con payloads reales guardados. La paridad *píxel* del mapa de MapLibre no se prueba (es un canvas WebGL) |
| 8 | Cada cifra, pronóstico y regla ligados a `model_id`, versión de fuente y horizonte | **Sí** | Todos los payloads llevan `model_id`, `data_version`, `issued_at`/`valid_at`; el pie de la web muestra `model_id`, `data_version`, geometría y ex_fuzzy; títulos con «+6 h», «+1 h» o «misma muestra» |
| 9 | Pruebas unitarias e integración básicas en CI; caso de fuga temporal comprobado | **Parcial** | `make test` en CI: contratos, API mock y sintética, publicación, fugas en las tablas (`tests/air`, `tests/mobility`, `tests/ml`) y el validador `observed_at ≤ issued_at`. Las pruebas de integración sobre los modelos **reales** (incluida la fuga en cada traza) **se saltan en CI** porque no hay artefactos; el humo de navegador es solo local. **Falta** la protección de rama (ver abajo). 2026-11-05, en local: `make test` 1129 pasan y 78 se saltan; `make qa` 169 pasan y 71 se saltan (volumen y navegador son opcionales); `make qa-web` 35 pasan |
| 10 | Water y Mobility pueden estar en ETL | **Superado** | Ambos publicados y servidos (PRs #42, #46, #49, #53) |

## MAP_EXPERIENCE §7 (MVP geográfico)

| # | Criterio | Estado | Evidencia y matiz |
|---|---|---|---|
| 1 | Coordenadas oficiales reales, etiqueta de última fecha/fuente, estados sin datos | **Sí** | `geometry_source` por entidad y en el pie, «Cobertura … a …» bajo la línea temporal, anillos «sin dato» (`test_entities_have_the_documented_support_and_geometry_type`) |
| 2 | Regla aprendida real con activación real de `ex_fuzzy` por estación y timestamp/ventana permitida | **Sí** | Paridad con las tablas y la traza; Water solo por ventana (`test_water_is_windowed_and_madrid_nyc_show_instants`) |
| 3 | Clic: entradas, grado de cada antecedente, firing, predicción y texto de la regla, enlazado a `model_id` y a un ejemplo reproducible | **Sí** (2026-11-05) | Todo el contenido está (traza exacta; `test_no_trace_input_is_observed_after_the_issue_time`). «¿Por qué aquí?» enlaza la petición exacta `GET /entities/{id}/rule-trace?model_id&at`, con `at` igual a la hora de emisión de la traza (`WhyHerePanel.test.tsx`); en los modelos servidos de Madrid, Water y NYC, volver a pedirla devuelve la misma traza |
| 4 | Slider temporal sin mezclar timestamps ni horizontes | **Sí** | `test_series_rule_map_and_trace_share_the_issue_time_and_horizon`; PageUp/PageDown mueven la línea temporal (`web_smoke.mjs`) |
| 5 | Dos paridades automatizadas: firing backend/mapa y `0` frente a `missing` | **Sí** | `test_real_map_parity.py`, `test_real_zero_vs_missing.py` |
| 6 | Ausencia de interpolación engañosa, conteos coherentes y accesibilidad/leyenda | **Parcial** | Sin interpolación y `n_valid` recalculado: sí (tests de CI-con-artefactos). Accesibilidad: humo automático local (`make qa-web`: tabla alternativa, nombre accesible del mapa, Tab, leyenda con unidad); lector de pantalla, contraste y zoom son una lista manual (`docs/qa/README.md`) |
| 7 | Modo de predicción aislado del de activación (título, unidad y leyenda distintos) | **Sí** | `test_each_view_has_title_legend_units_table_alternative_and_keyboard_access` para los tres dominios |
| 8 | Fixtures sintéticos bien marcados | **Sí** | Banner permanente en modo mock; `synthetic` en todos los payloads (`tests/api/`, `SyntheticBanner.test.tsx`) |

## MAP_EXPERIENCE §9 (antipatrones bloqueantes)

| Antipatrón | Estado | Evidencia |
|---|---|---|
| Extender el valor de una estación a un distrito | No ocurre | Madrid/agua solo `Point`; NYC polígonos oficiales de zona, no extendidos |
| Gradiente o halo decorativo como concentración | No ocurre | Sin `heatmap`/halos; las capturas muestran círculos y polígonos |
| Colorear ríos completos con pocas muestras | No ocurre | Agua: puntos de muestreo, ventana con `n_valid` por punto |
| Llamar «80 % de probabilidad/importancia» a una activación | No ocurre | Auditoría: 0 hits sobre reglas en la web, los payloads y el texto renderizado; los avisos están negados |
| Regla dominante como causa del pronóstico | No ocurre | El texto separa activación, asociación y categoría prevista; ninguna «contribución» expuesta |
| El frontend calcula reglas distintas del motor | No ocurre | La web pinta `value` de la API (README de la web; `App.real.test.tsx`) |
| Animar horas sin datos como mediciones | No ocurre | No hay animación; los vacíos son anillos «sin dato» |
| Mezclar gradiente de valores y colores categóricos sin leyenda | No ocurre | Activación: viridis con leyenda 0–1; categorías: leyenda categórica propia |

## Carencias conocidas (no son fallos de QA)

| Carencia | Dueño | Efecto |
|---|---|---|
| ~~Solicitudes de contrato pendientes~~: resueltas en el contrato v0.4: `license` y `attribution` en las fuentes, entidades y modelo; `coverage.regular` (la web lo lee en `irregular.ts`); `target_scheme.kind = percentile_reference` (NYC, `classifier.ts`); `GET /predictions` para todas las entidades a una hora | A0 | Ninguno. `irregular.ts` y `classifier.ts` ya leen los campos del contrato, no heurísticas |
| Protección de rama de `main` no activada | A0 | CI no bloquea la fusión |
| ~~PRs de ex-fuzzy pendientes de revisión del usuario~~ | usuario | Resuelto: el PR 44 (mezcla de reglas) está en ex-fuzzy 3.4.0, la versión fijada desde el contrato v0.7 |
| Atlas fijado a ex-fuzzy 3.4.0 (antes 3.3.1) | A0 | Actualizar exige repetir las trazas golden y comprobar los modelos publicados (`publish_parity --tables`) |
| Entrenamientos largos sin re-ejecutar | A0/A4 | `make reproduce` solo los lista y verifica entradas; los tiempos son los de `docs/ml/` |
| Licencia de NYC TLC sin cláusula abierta | usuario | No bloquea la demo (decisión del 2026-11-06); revisarla solo antes de publicar para descarga artefactos derivados (`ATTRIBUTION.md`) |
| ~~Licencia del documento ICA del MITECO sin verificar~~ | usuario | No bloquea: resolución oficial, art. 13 LPI (decisión del 2026-11-06, `ATTRIBUTION.md`) |

## Hallazgos abiertos de QA (AT-062)

Cada uno tiene evidencia reproducible. «Dueño» es quien debe corregirlo; A6 no edita código ajeno.

| Id | Gravedad | Dueño | Hallazgo | Evidencia |
|---|---|---|---|---|
| QA-1 | Media · **resuelto** (A0: código en #53, `rules.json` de Water reescrito con «(t)» y republicado; xfails retirados) | A4 (`atlas.ml.rules_export`) | El texto de las 39 reglas de Water dice `dissolved_oxygen(t+0h) = …`: con horizonte 0 es inferencia sobre la misma muestra, no un pronóstico en «t+0h». Se ve en la web (detalle de regla) | `rules.json` del modelo `exfuzzy-uk_water_do-…` (39 líneas, p. ej. `python scripts/qa/wording_audit.py`); `qa-water-rules.txt` líneas 226 y 258; `test_horizon_zero_is_never_written_as_t_plus_0h_in_api_payloads` y `test_water_never_renders_t_plus_0h` (xfail estricto) |
| QA-2 | Baja-media · **resuelto** (A0: «OpenFreeMap © OpenMapTiles · datos © OpenStreetMap contributors») | A5 (`StationMap.tsx`) | La atribución del mapa base dice «© OpenStreetMap contributors · OpenFreeMap» y omite «© OpenMapTiles», que la propia fuente de teselas declara | `curl https://tiles.openfreemap.org/planet` (campo `attribution`); `ATTRIBUTION.md` |
| QA-3 | Baja · **resuelto** (A0: 4 cifras significativas en la tabla de predicción) | A5 (`SampleChart`/tabla de Water) | En Prediction de Water la tabla muestra el oxígeno con 15 decimales («11.358646666666669 mg/l»): precisión falsa para un modelo con MAE 0,63 mg/l | `qa-water-prediction.png`, `qa-water-prediction.txt` líneas 126-130 |
| QA-4 | Baja · **resuelto** (A0: la frase «sin referencia» solo aparece en esquemas relativos, NYC) | A5 (`ClassSeriesChart.tsx`, línea 154) | El pie del gráfico de Madrid explica la franja rayada «sin referencia (la zona no tiene nivel de referencia a esa hora de la semana)»: es un concepto de NYC que no existe en Madrid | `qa-madrid-prediction.txt` línea 57 |
| QA-5 | Baja · **resuelto** (contrato v0.4: `TargetClass.merged_from`; el `rules.json` publicado lleva `merged_from` con las tres clases y una descripción que lo dice, 2026-11-05) | A4 (esquema ICA fusionado) | La clase fusionada «Desfavorable o peor» (121-1000) lleva solo la descripción de «Desfavorable» y su color; el hecho de que agrupa «Muy desfavorable» y «Extremadamente desfavorable» está solo en la etiqueta y en la nota de la web, no en la descripción del payload | `GET /api/v1/models/exfuzzy-madrid_no2_h6-ica2-justified-seed0/rules` → `target_scheme.classes[3]`; `test_ica_scheme_matches_the_config_with_the_documented_merged_upper_class` |
| QA-6 | Baja · **resuelto** (A0: comando en `docs/reproduce.md`) | A4/A0 (documentación) | El comando de publicación del modelo de Madrid ICA (`ica2-justified-seed0`) no está escrito en `docs/ml`; se reconstruyó desde `publish.json` y reproduce `predictions.parquet` exactamente | `scripts/qa/reproduce.sh`, etapa `madrid-7` |
| QA-7 | Informativa · **resuelto** (A0: aviso de reproducción retrospectiva en el pie de la web) | A5/A0 | La web no dice que los datos publicados son una reproducción retrospectiva (Madrid 2025, NYC feb-mar 2025, Water 2024-2025), solo muestra el periodo de cobertura y «periodo de prueba»; `MASTER_PLAN` §11 pide mostrar la frescura y no prometer tiempo real. Nada afirma tiempo real | grep de la web y de los textos renderizados |

## Revisión del 2026-11-05

Lo que sigue abierto en `main` (`971be00`) después de esta revisión:

| Punto | Dueño | Estado |
|---|---|---|
| Protección de rama de `main` | usuario | No se activa: decisión del usuario (2026-11-05) |
| ~~Pruebas con modelos reales fuera de CI~~ | A6 | Resuelto en #86: job `qa-real` sobre la release privada `qa-artifacts` (las cuatro tareas de QA; NYC añadida el 2026-11-06). El humo de navegador sigue siendo local |
| ~~Accesibilidad más allá del humo automático~~ | A6 / A5 | Auditoría automática en #86 (`scripts/qa/a11y_audit.mjs`); A11Y-1 a A11Y-4 corregidos el 2026-11-06. Escucharlo con un lector de pantalla real sigue siendo manual (`docs/qa/README.md`) |
| ~~Licencias de NYC TLC y del documento ICA del MITECO~~ | usuario | Decidido el 2026-11-06: ninguna bloquea la demo; NYC solo se revisaría antes de publicar para descarga artefactos derivados (`ATTRIBUTION.md`) |
| ~~Volumen con artefactos reales y un modelo ≥ 20 M filas~~ | A6 | Hecho en #86: `docs/qa/volume.md` §10 (Alemania, 57,4 M de registros) |
| ~~Issue #27 (AT-070, Alemania)~~ | A0 | Cerrado el 2026-11-05 |

## Revisión del 2026-11-09: Madrid sale de la demo

Decisión del usuario: Madrid deja de servirse (registro de `artifacts/published` sin las tareas `madrid_no2_*`; copia
del registro anterior en `registry.before-madrid-removal-2026-11-09.json`). Motivo: ni las reglas con «NO₂ ayer a la
hora de validez» (F1 macro de prueba 0,411) ni la mezcla de reglas (0,421) superan de forma clara a repetir la
categoría de ayer a la misma hora (0,407). Los datos, el código, los informes y los directorios de modelo se conservan;
volver a servirlo es reponer sus entradas en el registro. Las pruebas de integración de `madrid_no2_h6` se saltan
(«not in the published registry») y `scripts/qa/qa_bundle.py` deja fuera una tarea que ya no se sirve.

