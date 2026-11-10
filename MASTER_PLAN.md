# MASTER PLAN — ExFuzzy Atlas

## 1. Visión

ExFuzzy Atlas es una aplicación web **nueva e independiente** para explorar grandes datos de interés ambiental/urbano y comprender patrones con reglas difusas aprendidas por **la librería Python `ex_fuzzy`**. El producto tiene tres módulos pluggables:

- **Atlas Air:** Madrid como primera implementación; en una fase posterior, estaciones europeas (EEA).
- **Atlas Water:** calidad del agua de Inglaterra, inicialmente una cuenca y un conjunto reducido de analitos.
- **Atlas Mobility:** movilidad urbana de Nueva York, inicialmente taxi amarillo y demanda agregada por zona/hora.

**NO usar ExFuzzy Lab**. No migrar código de frontend de Lab, ni usar Pyodide. No modificar el repo `Fuminides/ex-fuzzy` salvo necesidad demostrada y autorizada.

## 2. Objetivos verificables

1. Ingestar y versionar fuentes reales en formatos columnar y consultarlas con memoria acotada.
2. Definir tareas ML científicamente válidas y compararlas con baselines relevantes.
3. Exponer las reglas aprendidas, activaciones por observación, cobertura y estabilidad temporal.
4. Construir **mapas de activación real de reglas difusas** (no solo mapas de predicciones), con timeline, filtros, exploración local de antecedentes y reglas, y visualización temporal por entidad. La experiencia cartográfica es un requisito central, detallado en `MAP_EXPERIENCE.md`.
5. Ejecutar experimentos reproducibles, con licencias y atribución de datos visibles.
6. Mantener el flujo completo local sin servicios pagos obligatorios.

## 3. Primera vertical (Madrid)

**Target primario:** concentración NO₂ (µg/m³) en estación y hora `t+6h` como regresión. Solo entradas observadas hasta `t`, con lagged NO₂, calendario, meteorología disponible hasta `t`, y tráfico agregado y asignado espacialmente. Comparar con predicción de persistencia, climatología (hora/día/estación), un modelo lineal y gradient boosting. Como vista secundaria, derivar riesgo de superar umbrales bien documentados; separar umbral analítico de exigencia normativa.

**Fase inicial:** 2019–2025 completos; revisar cobertura antes de fijar train/validation/test. No usar 2026 incompleto como prueba principal sin especificar las fechas. Comparar modelos con y sin tráfico para medir valor incremental; no afirmar causalidad a partir de correlaciones.

**Vista de producto:** selector de estación y ventana temporal; **Rule Spotlight sobre las coordenadas oficiales de estaciones, resaltando activaciones [0,1] calculadas por ExFuzzy**; explorador de antecedentes, timeline, serie observado/predicho, top reglas activas, alertas de calidad de datos y editor `what-if` no causal. La ausencia de medidas se muestra como ausencia y no se rellenan artificialmente barrios enteros.

## 4. Segundo módulo (Water)

**Mapa central:** puntos de muestreo observados con activaciones de reglas por muestra/fecha y filtros por cuenca/analito. No colorear segmentos completos de río sin validación hidrogeográfica.

**Problema exploratorio:** analizar perfiles de pH/temperatura/oxígeno disuelto/nutrientes por punto de muestreo, cuenca y temporada. Elegir un target viable *después* de estudiar cobertura y frecuencia: por ejemplo, categoría de una medición o predicción temporal solo si la densidad lo permite. Variables censuradas o medidas por debajo del límite de detección deben conservar su significado. No asumir que todas las variables se miden en cada muestra o que existe serie horaria regular.

## 5. Tercer módulo (Mobility)

**Mapa central:** polígonos oficiales de taxi zones con activación/frecuencia de reglas por zona-hora y comparación temporal. A diferencia del módulo Air, los polígonos corresponden a las unidades de agregación reales.

**Target primario:** demanda de recogidas de taxis amarillos por taxi zone y hora futura (horizonte propuesto: 1 hora) usando solo históricos de recogidas, calendario y contexto conocido a la hora de predicción. La duración del viaje queda como segundo caso, con precauciones de fuga de información: no usar hora/lugar de llegada ni tarifas al predecir antes del trayecto. Los datos no miden por sí solos emisiones ni congestión reales; cualquier estimación de CO₂ requerirá factores y supuestos adicionales explícitos.

## 6. Arquitectura propuesta (ratificada en `docs/architecture.md`)

```
exfuzzy-atlas/
  AGENTS.md
  pyproject.toml
  src/atlas/
    contracts/          # schema + validadores
    ingest/             # catálogo y adaptadores generales
    features/           # transformaciones temporales/espaciales comunes
    ml/                 # wrappers de ex_fuzzy, baselines, métricas
    explain/            # reglas, cobertura, firing, estabilidad
    domains/
      air/
      water/
      mobility/
    services/            # consultas y modelos ya entrenados
  apps/api/              # API FastAPI propuesta
  apps/web/              # React+TypeScript / Vite propuesto
  tests/
  configs/
  scripts/
  docs/
  data/                  # ignorado en git, excepto ejemplos pequeños sintéticos
  artifacts/             # ignorado en git, excepto manifiestos ligeros
```

Stack sugerido: Python >=3.10; `ex_fuzzy` como dependencia versionada; DuckDB+Parquet para analítica y ETL; Polars/Pandas donde convenga; FastAPI/Pydantic para API; React/TypeScript, **MapLibre como mapa base** y librería de gráficas para interfaz (**deck.gl opcional** si se justifica por las capas/rendimiento). Alternativas admisibles con justificación técnica. Los entrenamientos son jobs separados del proceso de peticiones web; la API sirve artefactos y agregaciones precalculadas.

## 7. Modelo de trabajo para datos

`source -> raw immutable + checksum -> validated normalized Parquet -> feature table -> time-aware split -> fitted model + manifest -> precomputed views -> API/UI`.

- Guardar URL, fecha de descarga, periodo, licencia, número de filas, cambios de esquema y checksums.
- Filtros de calidad: duplicados, rangos plausibles, códigos de validez, cobertura por estación/zona, huso horario y horario de verano.
- Las transformaciones de ajuste (imputaciones, escaladores, particiones difusas aprendidas) se ajustan solo en training.
- ETL incremental, particionado por fecha y estación/zona, sin cargar toda la historia en RAM.
- Distinguir timestamp de la observación, disponibilidad real del dato y hora objetivo.

## 8. Evaluación

**Protocolo de regresión:** MAE, RMSE, R², evaluación por estación, mes, hora y episodios extremos. **Clasificación:** macro-F1, balanced accuracy, precision/recall y matriz de confusión. **Incertidumbre:** cobertura y anchura de predicción conforme si el soporte y el protocolo lo permiten; no atribuir garantías a salida evidencial sin calibración. **Interpretabilidad:** nº reglas, longitud, soporte, activación, fracción sin cobertura, estabilidad entre periodos/semillas y fidelidad de las explicaciones. **Sistema:** tiempo total del fit, latencia de inferencia, pico RAM y tamaño de artefacto. Comparar a igualdad de split y presupuesto explícito.

## 9. Fases y puertas de calidad

- **M0 — Contratos y repo:** A0 confirma stack, contratos y fixtures; A6 establece CI. No autorizar trabajo compartido sobre los mismos archivos sin coordinación.
- **M1 — Fuentes verificadas:** A1/A2/A3 entregan ingestión reproducible de un subconjunto real y un informe de calidad. Pueden trabajar simultáneamente.
- **M2 — Modelo Madrid:** A4 y A1 entregan regresión NO₂ vs baselines con evaluación temporal y manifest; al menos una explicación de reglas verificable.
- **M3 — Rule Atlas Madrid:** A5 integra mapa, series, filtros, comparación con baseline y **Rule Spotlight real sobre estaciones + timeline + explicación de antecedentes al seleccionar una estación**; todo respaldado por trazas de inferencia verificadas. Este es el primer showcase completo.
- **M4 — Agua y NYC:** adaptar mismo contrato, modelos y vistas al piloto de cada dominio.
- **M5 — Endurecimiento:** pruebas de carga/consistencia, documentación pública, atribuciones, despliegue opcional; evaluación de extensión EEA.

No iniciar infra distribuida, nube gestionada, autenticación ni tiempo real hasta demostrar necesidad y contar con datos de calidad.

## 10. Definición de terminado del MVP

- Reproducción documentada en máquina local con `make demo` (o comando equivalente) sin credenciales ni APIs pagadas.
- Pipeline Madrid real con al menos 12 meses de datos alineados y checks de validez.
- Modelo ex_fuzzy entrenado con split cronológico, y comparación contra persistencia + gradient boosting.
- Página de dashboard funcional mostrando valores observados, predicción y **dos modos de mapa distintos: predicción y activación de reglas**.
- Rule Spotlight real para una regla aprendida: puntos de estación oficiales, intensidad calculada por la librería, leyenda 0–1, timeline y clic para ver cada antecedente y su grado de pertenencia.
- No pintar superficies continuas falsas basándose solo en datos puntuales; mostrar missing explícito.
- Tener al menos un test de paridad entre activación de `ex_fuzzy` y valor coloreado en el mapa.
- Cada cifra, pronóstico y regla ligados al `model_id`, versión de fuente y horizonte.
- Pruebas unitarias e integración básicas en CI; caso de fuga temporal comprobado.
- Los pilotos Water y Mobility pueden estar en fase de ETL aunque Madrid ya esté en demo; no bloquear entrega del MVP de Madrid por ellos.

## 11. Riesgos/decisiones abiertas

- **Acoplamiento espacial:** estaciones de aire, meteorología y sensores de tráfico son distintos. Documentar asociación por distancia/grupo/área, sin fingir co-localización exacta.
- **Escalabilidad:** grandes volúmenes para analytics no implican entrenar el optimizador genético sobre cada fila; comparar muestreo estratificado y entrenamiento incremental solo si hay soporte real.
- **Licencias:** `ex_fuzzy` declara AGPL-3.0-or-later; revisar obligaciones de distribución/servicio público antes de despliegue. Mantener licencias y atribuciones de fuentes.
- **Data freshness:** la app debe mostrar la última actualización disponible y no prometer real-time hasta que exista un pipeline de actualización.
- **Seguridad/confianza:** no llamar 'riesgo sanitario' a un score no validado. Los escenarios no son estimaciones de efectos causales.

## 12. Dirección creativa cartográfica (decisión de producto, 2026-10-30)

La característica principal del showcase será el **atlas espacial de reglas difusas**, no solo una tabla de reglas junto a un mapa. La especificación completa y su guion de demo están en [`MAP_EXPERIENCE.md`](MAP_EXPERIENCE.md). Las primeras funciones obligatorias son Rule Spotlight, timeline y desglose de antecedentes sobre una estación real. Después se podrán añadir Rule Territories, Rule Duel, Rule Stories y escenarios. Mantener exactitud en la semántica de firing, la geometría y la calidad de datos.
