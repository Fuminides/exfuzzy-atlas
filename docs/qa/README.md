# QA del MVP (AT-062, AT-060)

| Qué | Cómo |
|---|---|
| Pruebas de integración sobre los modelos publicados reales | `make qa` (o `pytest tests/integration`). Apuntan a `ATLAS_PUBLISHED_DIR` (por defecto `artifacts/published`) y **se saltan con el motivo escrito** si no hay `registry.json`. En CI corren en el job `qa-real` sobre el asset de la release `qa-artifacts` de un repo privado aparte (abajo) |
| Humo de accesibilidad y capturas con Chrome | `make qa-web` (opt-in, `ATLAS_QA_WEB=1`; necesita la web construida, Node y Chrome). Capturas en `ATLAS_QA_OUT` (por defecto un directorio temporal) como `qa-<madrid\|nyc\|water>-<rules\|prediction>.png` |
| Auditoría de redacción | `python scripts/qa/wording_audit.py` (lista cada hit con fichero y línea; `--web-only` no necesita artefactos) |
| Demo local | `make demo` (API en artifacts mode `:8000` y web construida `:4173`; Ctrl-C para ambos) |
| Cadena completa datos crudos a publicado | `make reproduce` (lista), `make reproduce ARGS=--check` (simulacro), `make reproduce ARGS=--smoke` (publica el run de Water en un temporal y lo compara) |
| Checklist Go/No-Go | [`mvp_checklist.md`](mvp_checklist.md) |
| Prueba de volumen (≥ 1 M filas, ≥ 20 M registros): latencia, RAM, concurrencia, validador (AT-061) | [`volume.md`](volume.md); `python scripts/qa/volume.py all --out <scratch>`; presupuesto opt-in: `make qa-volume` (`ATLAS_QA_VOLUME=1 pytest tests/integration/test_volume_budget.py`) |

## Modelos publicados en CI (release `qa-artifacts`)

Los modelos no están en git. El tarball lleva pickles (`model.pkl`) y tablas derivadas de NYC, así que no se publica
en este repo: vive en la release `qa-artifacts` de **un repo privado aparte**. El job `qa-real` de
`.github/workflows/ci.yml` descarga de ahí `qa-published.tar.gz`, comprueba su SHA-256 y corre `make qa` con
`ATLAS_PUBLISHED_DIR` apuntando a él.

| Ajuste del repo (Settings → Secrets and variables → Actions) | Qué es |
|---|---|
| variable `QA_DATA_REPO` | el repo privado con la release, `<owner>/<repo>` |
| secret `QA_DATA_TOKEN` | un token *fine-grained* de solo lectura (Contents: read) limitado a ese repo |

Sin los dos, el job lee la release `qa-artifacts` del propio repo con su token de siempre. En los PR que vienen de un fork
no hay secrets, así que `qa-real` se salta (el run no falla); esos cambios se prueban con los modelos reales al llegar a
`main` o en una rama del propio repo. Si el token caduca, `qa-real` falla al descargar: hay que renovarlo y volver a guardarlo.

El tarball lleva `registry.json` reducido a las tareas de QA y sus directorios de modelo sin tocar (con `SHA256SUMS`).
Lleva las cuatro tareas de QA (NYC desde el 2026-11-06: la release es privada y no es una publicación para descarga,
`ATTRIBUTION.md`); una tarea que se deje fuera con `--exclude` se salta en CI («not in the published registry»). Tras
republicar un modelo de QA:

```bash
python scripts/qa/qa_bundle.py --out <scratch>
gh release upload qa-artifacts --repo "$QA_DATA_REPO" <scratch>/qa-published.tar.gz <scratch>/qa-published.tar.gz.sha256 --clobber
```

## Qué comprueban las pruebas de integración

Por cada tarea publicada (`madrid_no2_h6`, `nyc_pickups_h1`, `uk_water_do`, `de_no2_h6`), con muestras deterministas
(`random.Random(f"{SEED}-{task}-{what}")`, `SEED = 20261031`) y la verdad leída directamente de los Parquet/JSON
publicados con DuckDB y pandas, no a través de la API:

| Fichero | Comprueba |
|---|---|
| `test_real_map_parity.py` | valor del mapa = fila de `activations` = firing de `rule-trace` (y `effective_firing`, peso y asociación); agregados (`mean_activation`, `activation_frequency` con dos `tau`) = recálculo con `n_valid`; 422 ante combinaciones ambiguas |
| `test_real_zero_vs_missing.py` | un 0 exacto es un número en mapa, traza y serie; `missing_input` es `null` con motivo y sin reglas en la traza; las series coinciden fila a fila con `predictions.parquet` |
| `test_real_geometry_support.py` | tipo de geometría = `geometry_support` (Madrid/agua solo puntos, NYC polígonos); sin `estimated_surface`; ninguna entidad sin geometría llega al mapa; polígonos NYC válidos y cerrados; coordenadas dentro de una caja de cordura |
| `test_real_time_semantics.py` | `valid_at - issued_at == horizonte` (6 h, 1 h, 0); ninguna entrada de traza observada después de la emisión y `observed_at = issued_at - lag`; serie, mapa y traza comparten el reloj; agua irregular y dispersa |
| `test_real_classifier_semantics.py` | un clasificador nunca publica un número; etiquetas del esquema; regla ganadora: `winning_rule_id` = argmax de asociación y su consecuente = etiqueta publicada; mezcla de reglas (v0.7): puntuaciones = sesgo + Σ pesos × firing, etiqueta = argmax de las puntuaciones, `winning_rule_id` nulo y `top_rule_id` = primer registro de mayor contribución centrada positiva; filas «sin referencia» de NYC (#51); esquema ICA = `configs/ml/ica_no2_scheme.json` con la clase superior fusionada documentada |
| `test_wording_audit.py` | ver abajo |
| `test_explanations.py` | contrato v0.6.2: cada modelo servido (las 15 tareas del registro) tiene su `configs/explanations/<model_id>.json`, escrito a partir de sus ficheros publicados actuales (`input_sha256` = contexto reconstruido) y con textos que pasan el validador de `scripts/explain_model.py` (cifras, redacción, reglas, límites); si falla, `make explain MODEL_ID=…` |
| `test_web_smoke.py` | opt-in, navegador: título, leyenda con unidad, tabla alternativa al mapa, teclado, atribución, texto renderizado |

**Contrato v0.7 (2026-11-09):** Alemania +6 h y NYC +1 h se sirven como mezcla de reglas (`exfuzzy-de_no2_h6-mixture-nonneg-seed0`,
`exfuzzy-nyc_pickups_h1-mixture-nonneg-seed1`, `docs/ml/rule_mixture_serve.md`), ajustados con `ex_fuzzy` `20c1095` y servidos con ex-fuzzy 3.4.0 (el código de `5409bb8`), con el que reproducen sus tablas bit a bit;
`tests/integration` pasa sobre el lote de QA de esos modelos (123 pasan, 129 se saltan por ser opt-in, de Madrid o de otra familia).

**Modelo de Water servido (2026-10-31):** `exfuzzy-uk_water_do-fx-w-unique-seed0` (39 reglas, 0 repetidas, `exfuzzy_version`
`3.3.1+g2ffcfb9`, ajustado con la construcción local de `ex_fuzzy`; véase `docs/reproduce.md`). `make qa` (113 pruebas pasan, 41 se
saltan por ser opt-in o de otra tarea) y `python -m atlas.services.verify` se ejecutaron con él, con la biblioteca fijada y con la
construcción. Las tablas de `volume_report.json` y las capturas citadas en `volume.md` son del modelo anterior
(`water-do-chrono-temp-seed0`, que sigue en disco sin registrar); el modelo nuevo tiene las mismas cifras de entradas (3.316),
entidades (195) y registros de activación (129.324).

Los fallos conocidos están como `xfail(strict=True)` con el motivo: cuando se corrijan, el `xfail` pasa a fallar y se
quita la marca.

## Auditoría de redacción

`scripts/qa/wording_audit.py` busca «probabilidad / riesgo / contribución / importancia / causa / relevancia /
influencia / certeza / confianza» (y sus formas inglesas) **usadas sobre una regla** (firing, activación, asociación, peso, antecedente) sin
una negación antes en la misma frase («No es una probabilidad…», «never importance»), y «+0 h» / «(t+0h)». Las
negaciones son los avisos del propio proyecto y no cuentan. Los hits que no hablan de reglas (p. ej. «grupos de riesgo»
en la descripción oficial del ICA) salen como informativos.

## Auditoría de accesibilidad (`scripts/qa/a11y_audit.mjs`)

Lo que antes era una lista manual se comprueba ahora con Chrome por CDP contra `make demo` (4 territorios x 4 secciones,
Explorar en sus dos vistas). La URL desnuda abre la portada (`components/Landing.tsx`): ambos scripts la comprueban primero
(contraste, árbol de accesibilidad, un solo h1, el botón «Empezar la demo», desbordamiento a 390 px) y abren la app con
`?demo=1`, que se la salta:

```bash
make demo   # en otra terminal
google-chrome --headless=new --remote-debugging-port=9444 --user-data-dir=<tmp> about:blank &
node scripts/qa/a11y_audit.mjs --cdp 9444 --out <dir>    # <dir>/a11y_audit.json y capturas a11y-*.png
```

Resultado del 2026-11-05 (`main` en `971be00`):

| Comprobación | Resultado |
|---|---|
| Contraste de texto (WCAG 1.4.3; 4,5:1, o 3:1 si es grande) | **0 fallos** en 22 641 elementos con texto. Los 22 casos por debajo (`#e2e2e2` sobre blanco, 1,29:1) son el botón «−1 d» **desactivado** al principio del rango, exento por la norma |
| Árbol de accesibilidad (lo que lee un lector de pantalla) | 0 controles sin nombre; ningún salto de nivel de encabezado; puntos de referencia `banner`, `navigation`, `contentinfo` y `complementary`; cada mapa es una región con nombre que apunta a su tabla («Mapa de estaciones. La tabla de estaciones ofrece las mismas funciones con teclado.») |
| Teclado en la tabla | Enter y Espacio sobre el botón de una fila seleccionan la entidad en los 4 territorios |
| Zoom al 200 % (750 x 525 px CSS) | Sin desplazamiento horizontal; el deslizador de tiempo (Madrid, Alemania, NYC) y la columna lateral visibles y alcanzables con Tab. Water navega por ventanas y su navegador no se midió |
| Ancho de móvil (390 px) | Sin desplazamiento horizontal de la página; las tablas anchas (Alemania, NYC) se desplazan dentro de `main` |
| Sin internet | Fondo liso con aviso (`StationMap.test.tsx`) |

**Hallazgos** (dueño A5):

| Id | Gravedad | Hallazgo | Evidencia |
|---|---|---|---|
| A11Y-1 | Media · **resuelto** (2026-11-06: borde `#1f2937` de 1 px en los puntos y contorno `#64748b` de 0,7 px en los polígonos, ≥ 3:1 frente a la tierra; `mapLayers.a11y.test.ts`) | Contraste de las marcas del mapa con el fondo (WCAG 1.4.11, 3:1): el extremo claro de **todas** las paletas queda por debajo frente a la tierra del mapa base (`#f2f3f0`): ICA «Buena» `#00FFFF` 1,13; EAQI «Good» 1,26 y «Moderate» 1,17; viridis en 1,0 `#fde725` 1,13; los valores bajos de Blues, Oranges y Purples ≈ 1,0–1,6. El borde blanco de 1,5 px no ayuda sobre un fondo claro. La información está también en la tabla (alternativa), pero en el mapa un punto «Buena» casi no se ve | cálculo de luminancia relativa sobre los colores de `configs/` y `colorScale.ts` y el color dominante del mapa base en las capturas. Arreglo propuesto: borde oscuro fino (p. ej. `#1f2937`, 1 px) en lugar del blanco; los colores oficiales no se tocan |
| A11Y-2 | Media · **resuelto** (2026-11-06: botón «Ir a la línea temporal», visible solo con el foco; 8 Tab desde la pestaña y Enter llevan al deslizador; `A11y.test.tsx`) | En Explorar la línea temporal va **después** de la tabla de entidades en el orden del DOM: con teclado hacen falta 473 pulsaciones de Tab para llegar al control de tiempo en Alemania y 297 en NYC (65 en Madrid). En Predicción va antes (2 Tab) | `Workspace.tsx`: `timelineFirst = mode === "prediction"`; recuento de elementos enfocables con CDP. Arreglo propuesto: un enlace «Ir a la línea temporal» visible al recibir el foco, o la línea temporal antes del mapa también en Explorar |
| A11Y-3 | Baja · **resuelto** (2026-11-06: la fila se reparte en dos líneas por debajo de 560 px) | En 390 px la fila de saltos de tiempo no se reparte en dos líneas (`.timeline--compact .timeline-jumps { flex-wrap: nowrap }`): el campo de fecha queda cortado por la derecha y los botones se aprietan («−1» / «d» en dos líneas) | captura `a11y-madrid-prediccion-phone390.png` |
| A11Y-4 | Baja · **resuelto** (2026-11-06: el lienzo pasa a `role="application"` con nombre en español, «Mapa interactivo: flechas para desplazarlo, + y − para acercar o alejar»; 0 regiones «Map» en la auditoría; `A11y.test.tsx`) | MapLibre añade su propia región «Map» (en inglés) alrededor del lienzo, además de la región con nombre en español: un lector de pantalla anuncia dos regiones de mapa | árbol de accesibilidad: 20 regiones «Map» en las 20 vistas auditadas |

Lo que sigue siendo manual: escucharlo con un lector de pantalla real (Orca, NVDA o VoiceOver). El árbol de Chrome es lo
que esos lectores reciben, pero no dice cómo suena ni si el orden de lectura tiene sentido.
