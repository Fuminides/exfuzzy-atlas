# MAP EXPERIENCE — Las reglas viven en el mapa

**Estado:** especificación de producto y técnica; no existe aún un prototipo funcional. 2026-10-30.

## 0. Tesis de producto

ExFuzzy Atlas no es un mapa con una columna de reglas al lado. Es un **atlas de reglas difusas**: una regla aprendida puede seleccionarse, seguirse en el tiempo, localizarse en las entidades donde se activa y relacionarse con predicciones y observaciones verificables. La misma interacción se aplica a Madrid, agua inglesa y taxis NYC, pero la representación geográfica será específica para cada dominio.

La propuesta tiene dos vistas distintas que **no deben confundirse**:

1. **Mapa de observaciones/predicciones:** muestra valores registrados o predichos por entidad y tiempo, con su procedencia.
2. **Mapa de reglas:** muestra cómo las observaciones de cada entidad activan las reglas de un modelo concreto. La activación no es una medida de contaminación, peligro, causalidad, confianza ni contribución a la predicción.

## 1. Cinco experiencias centrales

### E1 — Rule Spotlight (P0, imprescindible)

El usuario elige R07: «tráfico ALTO ∧ viento BAJO ∧ NO₂ previo ALTO», y el mapa resalta estaciones con mayor grado de activación en la hora seleccionada. Los demás puntos se atenúan, no desaparecen. Una escala cuantitativa 0–1, umbral ajustable, leyenda y conteo de observaciones válidas acompañan al mapa. Clic en una estación abre el desglose:

- Condición tráfico ALTO: μ = 0.81.
- Condición viento BAJO: μ = 0.94.
- Condición NO₂ anterior ALTO: μ = 0.72.
- Activación de la regla según el operador real del modelo (ej. mínimo, si así lo implementa el modelo): 0.72.
- Predicción completa: valor y unidad; otras reglas activas, y aviso si el modelo no permite desglosar atribución exacta.

**Todos los valores anteriores son ficticios y se usarán únicamente en tests/storyboards; no deben mostrarse como datos reales.**

### E2 — Rule Territories (P1)

En una ventana temporal elegida, cada entidad muestra su regla más frecuentemente activa o su distribución de reglas. Clic en una regla ilumina su «territorio empírico»: estaciones/zonas donde se activa, y fracción de horas o muestras observadas en las que lo hace. Las reglas pueden superponerse: no presentar territorios como particiones exclusivas salvo en una vista explícita de regla dominante y con una regla de desempate. La leyenda especifica los criterios (`mean_activation`, `fraction_above_threshold`, etc.) y el tamaño muestral.

### E3 — Time Scrubber / Rule Weather (P1)

Una línea temporal permite avanzar por horas/días y ver cómo cambia la activación. Al pasar el cursor sobre una estación se muestra el cambio de reglas activas y su incertidumbre de datos. En modo resumen, small multiples por franjas horarias/semanas/estaciones del año. Animaciones interpolan **la transición gráfica**, no inventan observaciones entre muestras.

### E4 — Rule Duel / Model Comparison (P1)

Dos reglas (o dos modelos) se comparan con un selector A/B: mapa dividido o comparación lado a lado con la misma escala, fecha, entidades y criterio estadístico. La diferencia puede representarse para una regla común en dos modelos versionados si existe un mapeo explícito de reglas; no asumir que R07 de un modelo equivale a R07 de otro. Una vista de desacuerdo ExFuzzy vs baseline requiere un criterio numérico documentado, no simplemente comparar colores o nombres.

### E5 — What-if Explorer (P1)

Al seleccionar una entidad, controles de tráfico, viento o variables permitidas modifican un **escenario hipotético del vector de entrada**. El usuario ve cambios de pertenencias, activaciones y salida del modelo. El escenario modifica solo el registro de ejemplo, no reescribe el dataset ni colorea toda la ciudad como si se hubiera simulado físicamente. Rotular **«respuesta del modelo ante entradas modificadas — no efecto causal ni predicción meteorológica»**. Indicar si una entrada es históricamente observada, predicha o artificial.

## 2. Tres lenguajes cartográficos

### AIR / Madrid — estaciones, no falsas superficies

**Unidad de análisis:** estación de contaminación × instante de emisión, con geometría de estación verificada. Inicialmente dibujar **puntos/círculos**: tamaño por intensidad/visibilidad, opacidad o color por activación; al seleccionar se abre una ficha. La información meteorológica/tráfico no siempre es co-ubicada: mostrar fuente/relación espacial en el detalle. Para eventos históricos, activar modo `coverage fraction` por estación. Una capa de polígonos o interpolación **solo** podrá ofrecerse si existe un modelo espacial/interpolador validado y rotulado como estimación, no como una lectura de ExFuzzy por barrio. La ciudad no debe aparecer pintada uniformemente basándose en pocas estaciones.

Ideas visuales: halos suaves alrededor de estaciones (decorativos, no campo numérico), una capa de puntos secuenciales que cambian al avanzar el tiempo, y minigráficas de activación en los marcadores al hacer zoom.

### WATER / Inglaterra — red hidrográfica, no choropleth inventada

**Unidad:** punto de muestreo × fecha × analito, con muestras irregulares. Pintar marcadores en puntos reales, agrupables por cuenca. Superponer el río únicamente con geometrías oficiales de red hidrográfica; colorear un tramo entero como estimado exige validación hidrológica. Interacción creativa: «ruta de una regla» como selección de puntos en un mismo cauce/cuenta, mostrando su orden espacial y temporal si el dato lo permite, sin afirmar transmisión causal aguas abajo. Permitir elegir analito y mostrar cobertura y detecciones censuradas.

Ideas visuales: pequeños glifos de varios analitos por punto; panel de «reglas río arriba/río abajo» presentado como *comparación exploratoria* y con tamaños muestrales visibles.

### MOBILITY / NYC — polígonos reales de taxi zones

**Unidad:** taxi zone × hora. Aquí sí existe un conjunto oficial de **polígonos** a los que corresponden directamente los targets: usar coropletas por activación o frecuencia de regla, no interpolación. Seleccionar zona abre un perfil horario; una vista temporal muestra la alternancia de patrones (p. ej., «demanda ALTA ∧ hora PUNTA»). Solo dibujar flujos/trayectorias cuando exista origen-destino real y una variable definida, nunca inventar rutas de vehículos.

Ideas visuales: mosaico de «familias de reglas» por zonas, comparación día laborable vs fin de semana, modo 3D opcional con altura = dato numérico validado e independiente del color.

## 3. Navegación y UX (una experiencia coherente)

Layout escritorio: **mapa ~65–70 % de ancho**, rail lateral de reglas (30–35 %), y **timeline acoplada abajo**. Menú de tres modos `[Data] [Prediction] [Rules]`, selector de dominio y fecha, y estado/fuente visibles en el pie. La selección activa se refleja bidireccionalmente en mapa, rail, gráfica y desglose:

- Clic regla → mapa colorea activaciones → selección de entidad filtra el historial → muestra μ por antecedente.
- Clic entidad → top reglas y predicción → clic en una regla abre sus particiones lingüísticas.
- Clic momento timeline → refresca todas las capas y se conserva regla/entidad elegidas cuando existen.
- Reset limpia escenarios y retorna a valores observados.

**Diseño:** basemap discreto y de bajo contraste, paleta perceptualmente uniforme para activación [0,1], colores semánticos consistentes en las tres verticales, estados missing explícitos (no confundir 0 con missing), tooltips accesibles, alternativa textual de tabla y controles de teclado. El mapa **no** debe ser la única forma de acceder a las explicaciones.

## 4. Conceptos y métricas: semántica precisa

- `firing_strength`/activación: grado real que devuelve el motor del modelo **para fila x y regla r**, ∈[0,1], calculado con operadores/particiones reales; A4 lo verifica contra inferencia upstream. No se calcula por reconstrucción aproximada en TS.
- `mean_activation`: media de activación en observaciones válidas de una entidad en una ventana. Requiere `n_valid` y resolución temporal.
- `activation_frequency`: fracción de observaciones válidas cuya activación supera un umbral `tau`; exige `tau` visible y denominador claro.
- `dominant_rule`: argmax de activación **únicamente para esta medida**, no asumir que es la «responsable de la predicción». Para `dominant_contributor` se necesita una descomposición fiel y verificable del modelo; no crearla automáticamente.
- `model_prediction`: valor final devuelto por `ex_fuzzy`, no salida aislada de una regla.
- `rule_contribution`: opcional; solo se expone si A4 demuestra que es una magnitud semánticamente válida para esa familia concreta de modelos.
- `prediction_uncertainty`: distinta de activación; solo si hay estimador/calibración válida.
- `missing`: sin observación / variable censurada / dato inválido / predicción no disponible se representan por separado.
- `geometry_support`: `observed_point | observed_polygon | derived_aggregate | estimated_surface`; si es superficie estimada debe llevar método/hipótesis. No usar `estimated_surface` en MVP.

## 5. Contratos de datos necesarios (A0 y A4)

Extensión de API propuesta a `CONTRACTS.md`: datos de reglas estáticos y **tiles/GeoJSON agregado de activaciones** por ventana. La API no debe recalcular optimizaciones genéticas durante requests ni transferir cada fila histórica al navegador. Precalcular activaciones de un modelo fijado y series de resumen por entidad/tiempo; para fuentes grandes usar Parquet/DuckDB + agregación backend y caché versionada.

**Operaciones UI mínimas:**

1. GET `/api/v1/models/{id}/rules` → definición textual, antecedentes, consecuente y metadatos.
2. GET `/api/v1/rule-map?model_id=...&rule_id=...&time=...&metric=firing_strength` → FeatureCollection por entidades reales con `value`, `n_valid`, `geometry_support`, `model_id` y tiempos.
3. GET `/api/v1/rule-map?model_id=...&rule_id=...&from=...&to=...&metric=activation_frequency&tau=0.5` → agregados empíricos y conteos.
4. GET `/api/v1/entities/{entity_id}/rule-trace?model_id=...&at=...` → condiciones, pertenencias, firing exacto, validez por antecedente y predicción.
5. POST `/api/v1/scenarios` → nueva predicción local, pertenencias y firing en entradas alteradas, con bandera `synthetic_what_if`.

Todos los endpoints aceptan paginación/límites, validan combinaciones de modelo/tarea/tiempo/entidad, devuelven `schema_version`, `model_id`, `data_version`, zona horaria y unidades cuando aplique. El `time` debe distinguir la fecha de emisión (`issued_at`) y el horizonte (`valid_at`). Una geometría de punto no es una zona inferida.

## 6. Stack para probar, no imposición

**MapLibre GL JS** como mapa base; sus capas `circle`, `fill`, `line`, `heatmap` y data-driven styles son adecuadas para puntos y polígonos (consulta la documentación de MapLibre). **deck.gl** opcional, no obligatorio en MVP, si necesitamos agregados GPU/hexágonos y geometría compleja; ofrece `GeoJsonLayer`, `HexagonLayer`, `ContourLayer` y capas de agregación. Habilitar deck.gl solo después de perfilar MapLibre; no añadir toda la pila por estética. Fuente de mapas y licencia a verificar por A0 (no asumir gratuidad ilimitada de servidores de terceros).

Referencias oficiales:
- https://maplibre.org/maplibre-style-spec/layers/
- https://deck.gl/docs/api-reference/layers/geojson-layer
- https://deck.gl/docs/api-reference/aggregation-layers/hexagon-layer
- Geodatos oficiales de estaciones de Madrid (Feature Layer de Geoportal): https://sigma.madrid.es/hosted/rest/services/GEOPORTAL/ZONAS_DE_CALIDAD_DEL_AIRE_Y_ESTACIONES_DE_MEDICION/MapServer/5

## 7. MVP geográfico, Definition of Done

**No considerar terminado el dashboard Madrid sin esto:**

1. Mapa con **coordenadas oficiales reales de las estaciones**, etiqueta de última fecha/fuente y estados sin datos.
2. Seleccionar una regla aprendida real y observar **activación real calculada por `ex_fuzzy`**, visualizada por estación para un timestamp/ventana permitida.
3. Clic en un punto: ver valores de entrada, grado de cada antecedente, firing, predicción del modelo y texto de la regla; todo enlazado a `model_id` y a un ejemplo reproducible.
4. Slider temporal que actualiza el mapa y la lista de top reglas sin mezclar timestamps ni horizontes.
5. Dos comprobaciones automatizadas de paridad: firing backend/representación geográfica y `0` frente a `missing`.
6. Tests de ausencia de interpolación engañosa, conteos coherentes y accesibilidad/leyenda.
7. Modo de predicción aislado del modo de activación (distinto título, unidad y leyenda).
8. Fixtures sintéticos bien marcados para desarrollar UI; **datos reales solo cuando estén disponibles y verificados**.

## 8. Extensiones creativas, sin bloquear MVP

- **Rule fingerprints:** tarjetas compactas con distribución espacial + temporal de cada regla; click expande la huella completa.
- **Rule stories:** recorridos explicativos automáticos anclados a eventos verificables («esta regla se activó en X estaciones durante Y horas»).
- **Rule families:** agrupar reglas por similitud semántica/antecedentes con definición computable; mapa de familias en lugar de IDs crudos.
- **Counterfactual lens:** arrastrar variables de un punto y mostrar cambios de pertenencias/reglas; mantener etiqueta no causal.
- **Rule drift:** comparar cobertura/activación en periodos y modelos versionados; no presentar cambios como deterioro sin test.
- **Dual-layer uncertainty:** contorno o patrón gráfico aparte para falta de cobertura / predicción conforme; activación y confianza nunca codificadas como una sola magnitud.

## 9. Antipatrones de diseño a bloquear en QA

- Extender un valor de estación a un distrito como si se hubiese medido todo el distrito.
- Etiquetar gradiente o halo decorativo como concentración calculada.
- Colorear ríos completos por pocas muestras irregulares.
- Llamar a una activación 0.8 «80% de probabilidad» o «80% de importancia».
- Mostrar regla «dominante» como explicación causal del pronóstico sin prueba de contribución.
- Dejar que el frontend compute reglas difusas distintas del motor real.
- Mostrar animaciones de horas sin datos como si fueran mediciones.
- Mezclar gradientes cromáticos de valores con colores categóricos de familias de reglas sin leyenda.

## 10. Primer demo objetivo para agentes (guion de 90 segundos)

1. Entrar en **Madrid / Rules** y seleccionar una fecha válida con mediciones verificadas.
2. Seleccionar regla Rn real que el modelo haya aprendido. Las estaciones cambian de color proporcionalmente a su firing, con leyenda 0–1.
3. Pulsar una estación y abrir «Why here?»: datos y μ de cada antecedente, firing exacto y pronóstico resultante.
4. Mover la timeline tres pasos: el mapa cambia de forma coherente y los registros sin dato aparecen como missing.
5. Pasar a **Prediction**: ver NO₂ a seis horas y serie pronosticada vs observada, sin confundir intensidad de regla con concentración.
6. Opcional: abrir **What-if** para una única estación y mostrar cómo cambia el firing y el output bajo entradas artificiales, rotulado no causal.
