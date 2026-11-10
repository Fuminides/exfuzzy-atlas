# ES → EN glossary for the interface

One term, one translation, everywhere. When a Spanish term below appears, use exactly this English; add new terms
here in the same PR that first needs them.

## How to translate

- `tr("español", "English")` next to the use; JSX: `tr(<>…</>, <>…</>)`. No central dictionary.
- Module-level constants that hold text (`const LABELS = {…}`) are evaluated once at import: turn them into functions
  called at render (`const label = (k) => ({ … })[k]`).
- Grammar belongs to each language: write both sentences whole (`tr(\`decide el ${p} de las predicciones\`,
  \`decides ${p} of the predictions\`)`), never glue translated fragments.
- Numbers, percentages, dates: always through `lib/format.ts` (`dec`, `pct`, `withUnit`, `count`, `formatDate`…),
  which follow the language. Never `toLocaleString("es-ES")`.
- Text that comes from the API (variable, term and class labels, entity names, territory titles, attribution texts,
  rule ids, feature keys) is **data**: do not wrap it in `tr`. Contract v0.6 adds `*_en` fields; show them with
  `localized(es, en)` (`i18n/index.ts`), or with the helpers of `lib/labels.ts` that use it (`labelerFor`, `namesFor`,
  `className`, `schemeName`, `schemeShort`, `describeVariable`). A missing `_en` falls back to the Spanish.
- `aria-label`, `title`, `alt` and placeholders are text too.
- A tab or section named in running text (not its own button or title) goes in italics, never in quotes: «La demo se abre en <em>Patrones</em>». `title` attributes and
  other plain-string places cannot carry it and stay as they are.
- British spelling, as the en-GB number and date formats: colour, licence, modelled, grey.
- Spanish quotes «…» become “…” in English (also around a class name, which is data: `“${worse}”`).
- Tests keep running in Spanish (`App` defaults to `es`). Add English checks for what you translate
  (`render(<App initialLang="en" />)` or `setLang("en")` in unit tests, then `setLang("es")` in `afterEach`).

- **Model families and metrics: the technical name is a label, a lower-case phrase is running text** (2026-11-09,
  refined 2026-11-10; the same rule for the interface and for the generated explanations). As a label (bar labels,
  titles, table cells, the evaluation table) the families keep their technical name: Random forest, Logistic regression,
  Linear regression, Gradient boosting, HGB, Ridge; so do the metrics macro-F1 / F1 macro. **Inside a sentence** they are
  written as ordinary words, lower case in the middle of a sentence and without quotes: «la regresión logística», «la
  regresión lineal», «el Random Forest» in Spanish ("del Random Forest", "al Random Forest": the user wants it left in
  English with a capital F, 2026-11-10; the Spanish bar label is «Random Forest» too); "logistic regression", "linear
  regression", "the random forest" in English (label "Random forest"). The explanation validator
  (`scripts/explain_model.py`) rejects the capitalised English names in an English sentence, and «bosque aleatorio» in
  Spanish. Everyday words (persistencia, climatología,
  acierto) are translated everywhere.

## Wording: precise, no defensive disclaimers (the English guard mirrors the Spanish one)

Firing, association and weight are never called a **probability**, **risk**, **contribution**, **cause/causal**,
**certainty** or **confidence**, in either language, and the tests that forbid those words stay. The interface does not
say it with disclaimers either (user decision, 2026-11-10): no sentence whose only job is to say what something is not
("no es una probabilidad", "it's an inference, not a forecast", "no efecto causal", "no sustituye…"). Say what the thing
is, precisely, and stop. A negation stays only where the text beside it would mislead without it (a hollow chart
mark, "validation period: not the test period", "Los colores son categorías, no una escala", the synthetic-data banner).
The English guard matches `/caus(e|al)/`, so "because" trips it too: on the guarded tabs write the sentence another
way ("no prediction is published: the zone has no reference level").

## Ordinal and compound conditions (contract v0.8)

- A condition `at_least` / `at_most` reads like an `is` condition with «al menos» / «como mucho» (EN "at least" / "at most")
  after the verb: «la temperatura es al menos media», "temperature is at least medium"; the verb of the term stays
  («está al menos en…»). The term is worded exactly as an `is` condition would word it (`lib/termPhrases.ts`). In a matrix
  cell or a hovercard line the compact marker is ≥ / ≤ before the term's phrase («≥ demanda alta»); on a plot the label
  is «al menos Aceptable» / "at least Fair".
- A compound (`any_of`) reads «es Primeras horas» / "is Early hours". Its name is a **display name** from an Atlas
  config (`label` / `label_en`), provisional and free to change without refitting the model; the web shows it as data
  with `localized(es, en)` and falls back to the internal `term`, never hard-coding a name. What it covers goes in a
  tooltip or the rule detail: the terms' labels joined with «o» / "or", and for an hour of the day the hours where the
  bounded sum is at least one half, computed from the terms' published parameters («Tarde-noche o Noche, 17–5 h»; a
  stretch through midnight reads «17–5 h»). Display only.
- On the partitions plot an ordinal or compound condition that some rule uses is a dashed line: the sum of the
  memberships of the terms it covers, capped at 1 (the bounded sum). Memberships quoted anywhere else come from the
  API's traces.

## Terms

| Español | English |
|---|---|
| Patrones / Resumen / Predicción / Explorar | Patterns / Summary / Prediction / Explore |
| regla, reglas | rule, rules |
| antecedente, condición | antecedent, condition |
| consecuente | consequent |
| activación (de regla), grado de activación | (rule) activation, activation degree |
| grado de asociación, asociación (activación × peso) | association degree, association (activation × weight) |
| peso (de la regla) | (rule) weight |
| pertenencia (μ) | membership (μ) |
| término lingüístico, partición | linguistic term, partition |
| t-norma | t-norm |
| decide el X % de las predicciones | decides X% of the predictions |
| acierta el X % | is right X% of the time |
| no decide ninguna predicción | decides no prediction |
| la regla que más decide, decide más | the rule that decides most, decides most |
| sin observaciones con las que comprobarlo | no observations to check it against |
| peso medio en la estimación, error medio | mean weight in the estimate, mean error |
| cuota (de una regla en el promedio) | share (never "contribution") |
| no dispara ninguna regla | no rule fires |
| la regla que decidió, la decidió R06 | the rule that decided, decided by R06 |
| categoría prevista | predicted category |
| valor estimado | estimated value |
| observado, valor observado | observed, observed value |
| emisión, hora de emisión | issue, issue time |
| validez, hora de validez | valid time |
| horizonte | horizon |
| misma muestra (horizonte 0) | same sample |
| inferencia, no es un pronóstico | inference, not a forecast |
| persistencia | persistence |
| periodo de prueba / de validación / de entrenamiento | test / validation / training period |
| F1 macro | macro-F1 |
| modelos de referencia | reference models (baselines) |
| repetir la última observación / categoría / el último valor | repeating the last observation / category / value |
| error medio absoluto | mean absolute error |
| nivel de referencia | reference level |
| ventana (día, semana, mes, año) | window (day, week, month, year) |
| instante de emisión | issue instant |
| media en la ventana | mean over the window |
| frecuencia ≥ τ en la ventana | frequency ≥ τ over the window |
| énfasis visual | visual emphasis |
| sin dato (y su motivo) | no data (and its reason) |
| sin datos, sin observaciones, sin predicciones | no data, no observations, no predictions |
| mediana, rango intercuartílico, la mitad de los valores entre A y B | median, interquartile range, half of the values between A and B |
| no disponible todavía | not available yet |
| sin modelo | not modelled |
| sin referencia (NYC) | no reference |
| estación, estaciones | station, stations |
| zona de taxi | taxi zone |
| punto de muestreo | sampling point |
| territorio | territory |
| Datos observados / Reglas en el mapa | Observed data / Rules on the map |
| Territorios | Territories |
| Duelo de reglas | Rule duel |
| Historias | Stories |
| ¿Y si…? | What if…? |
| ¿Por qué aquí? | Why here? |
| Ver términos / Ocultar términos | Show terms / Hide terms |
| Ver la regla en Patrones | See the rule in Patterns |
| Por zonas, Dónde decide R02 | By zone, Where R02 decides |
| Ver como tabla, Ver tabla de esta gráfica | Show as a table, Show this chart's table |
| Leyenda: …, Escala de A a B | Legend: …, Scale from A to B |
| Reintentar, Más información, Entendido | Retry, More information, Got it |
| Detalles de tiempo | Time details |
| Versiones y procedencia | Versions and provenance |
| Atribución | Attribution |
| Esquema de categorías | Category scheme |
| datos sintéticos | synthetic data |
| territorios de reglas, regla dominante | rule territories, dominant rule |
| intensidad (de la regla) | intensity |
| activación media / frecuencia de activación / reglas ganadoras | mean activation / activation frequency / winning rules |
| registros válidos | valid records |
| desempate, denominador | tie-break, denominator |
| semiabierta (ventana [desde, hasta)) | half-open |
| línea temporal | timeline |
| emisión anterior / siguiente | previous / next issue |
| índice oficial; relativo a lo habitual | official index; relative to what is usual |
| percentil | percentile |
| sin geometría | no geometry |
| mapa base | basemap |
| Duelo: regla A frente a regla B | Duel: rule A vs rule B |
| Lado a lado / Diferencia de activación (A − B) | Side by side / Activation difference (A − B) |
| ¿Cuánto acierta? | How often is it right? |
| ¿Para cuándo predice? | What does it predict for? |
| referencia (el modelo de referencia más simple) | reference |
| exactitud, exactitud balanceada | accuracy, balanced accuracy |
| error medio | mean error |
| Persistencia / Climatología (referencias) | Persistence / Climatology |
| Partición temporal; Entrenamiento / Validación / Prueba | Time split; Training / Validation / Test |
| Margen (embargo) | Gap (embargo) |
| Colorear por | Colour by |
| Regla característica, sin regla característica | Characteristic rule, no characteristic rule |
| Perfiles, Perfil A · más R03 y R07, sin regla destacada | Profiles, Profile A · more R03 and R07, no rule stands out |
| Regla que más decide | Rule that decides most |
| aquí / en el conjunto (una parte frente a la general) | here / everywhere |
| Qué la (lo) distingue | What sets it apart |
| Categorías previstas | Predicted categories |
| Ver su serie en Predicción, Ver en Explorar | See its series in Prediction, See in Explore |
| Estás viendo… (entradilla de pestaña) | You are looking at… |
| Reproducir (una historia), consulta, comprobación | Replay, query, check |
| Restablecer a los valores observados | Reset to the observed values |
| escenario artificial, entrada modificada | artificial scenario, modified input |
| Modo Data | Data mode |
| objetivo / entrada (papel de una variable) | target / input |
| ICA: Buena / Razonablemente buena / Regular / Desfavorable o peor | Good / Reasonably good / Moderate / Unfavourable or worse (no official English; set in `configs/air/attribution.json`) |
| EAQI: Buena / Aceptable / Moderada / Mala o peor | Good / Fair / Moderate / Poor or worse (the official names) |
| nivel NYC: baja / normal / alta / muy alta; Nivel relativo | low / normal / high / very high; Relative level |
| hora de validez (de una variable), «NO₂ ayer a la hora de validez» | valid time, “NO₂ yesterday at the valid time” |
| Modelo completo; La regla que más decide (cifras del héroe) | Whole model; The rule that decides most |
| Las reglas en cifras (héroe de Patrones) | The rules in figures (Patterns hero) |
| con modelo (estaciones con modelo) | modelled (stations modelled) |
| datos observados, sin modelo | observed data, no model |
| Reparto por categoría; Mediana y rango | Split by category; Median and range |
| Regla R10 (tarjeta de regla); Periodo publicado | Rule R10 (rule card); Published period |
| Ortografía | British spelling (colour, grey, licence), to match the en-GB locale |
| Empezar la demo; Ver cómo funciona; Sobre esta demo (página de inicio) | Start the demo; How it works; About this demo |
| Saltar al contenido | Skip to content |
| Tres territorios | Three territories |
| Explicando mapas con reglas (título de la página de inicio) | Explaining maps with rules |
| frase completa de un término: «demanda alta», «humedad media», «viento alto» (lib/termPhrases.ts) | high demand, medium humidity, high wind |
| la demanda hace 1 h (sujeto de las reglas de NYC) | demand 1 h ago |
| la demanda media de las 24 h previas; por encima / por debajo de lo habitual; la habitual | mean demand over the previous 24 h; above / below what is usual; as usual |
| en el límite de detección o por debajo (`<=L`); sobre el límite de detección (`Bajo>L`…) | at or below the detection limit; above the detection limit |
| época del año (estación del año de Water) | time of year |
| Las reglas de un vistazo | The rules at a glance |
| mezcla de reglas (`rule_mixture_classifier`, contrato v0.7) | mixture of rules |
| lo que una regla suma a una categoría (nunca «contribución») | what a rule adds to a category (never "contribution") |
| la regla que más suma (a la categoría prevista); la que más suma | the rule that adds the most (to the predicted category); adds the most |
| apoyo (+) / supresión (−); apoya / suprime | support (+) / suppression (−); supports / suppresses |
| apoya sobre todo Buena (`strongest_class`) | supports Good most |
| peso centrado (peso − su media en las categorías) | centred weight |
| Ninguna regla decide sola | No single rule decides / none decides alone |
| sin ella cambiaría la categoría del X % (`decisive_share`) | without it X% of the predictions would change category |
| Aciertan esas (las predicciones en las que es la que más suma) | Those are right |
| puntuación de cada categoría; sesgo (`class_scores`, `class_bias`) | score of each category; bias |
| Se cumple (columna con el grado en que se cumple una regla, fuera de Explorar) | Holds |
| «Reglas ganadoras» no existe en este modelo (mezcla de reglas: no hay ganadora) | "Winning rules" does not exist in this model |
| la que más cuenta (texto general de la página de inicio) | counts most |
| al menos / como mucho (condición ordinal de una entrada con términos ordenados, contrato v0.8): «es al menos Aceptable», «es como mucho Media» | at least / at most: "is at least Fair", "is at most Medium" |
| condición compuesta (varios términos con nombre propio, p. ej. «Primeras horas» = Madrugada + Mañana): «es Primeras horas» | compound condition: "is Early hours" |
| suma acotada (la forma que se dibuja de una condición ordinal o compuesta) | bounded sum |
