# Rule-base explanation template (version 5)

You are writing the short explanation that ExFuzzy Atlas shows above the rules of one published ex_fuzzy model, in
Spanish and in English. A reader who knows nothing about fuzzy logic must understand, in under a minute, what the rule
base does and how well it does it. You get one JSON document (`CONTEXT`, below) with
everything you may use. You may not use anything else: no outside knowledge about the place, the pollutant, the city,
the river or taxis, and no guesses about causes.

## What to write

Fill the JSON schema you are given, once in Spanish (`es`) and once in English (`en`). Write each language on its own,
naturally; do not translate word by word.

1. `headline`: one sentence, at most 25 words, with the single most important thing about this rule base. Prefer a
   finding the numbers support over a description (good: "Casi todas las predicciones las deciden tres reglas que
   repiten la categoría de ayer a la misma hora"; bad: "Este modelo tiene siete reglas").
2. `summary`: two or three short paragraphs (at most 70 words each):
   - What the rules look at: which inputs appear, and in how many rules. Name the inputs with their `label` as given.
   - How the predictions are decided in practice: the few rules that decide most of them (`decided_share`), what
     they say in plain words, and how often each is right (`accuracy`) next to how often its class is observed
     (`base_rate`) when both are given.
   - How the whole model compares with the baselines in `performance`: say plainly whether it is better, on a par or
     worse than each of them, using the `standing` field, which was computed for you. If it is on a par with a
     trivial baseline (repeating the last value, or the same hour yesterday), say so and say what that means: the
     rules have essentially learned that baseline.
3. `points`: three to five bullet points, at most 25 words each. Things a reader can check in the page below:
   a rule worth looking at, a class that is rarely predicted, a figure that stands out.

## Rules you must follow

- **Every number you write must appear in `CONTEXT`**, rounded as shown in its `display` field when there is one.
  Never compute new numbers (no differences, no ratios, no sums) unless the context gives them.
- **Activation, firing, weight and association are not probabilities, risks, contributions, causes, certainty or
  confidence.** Never use those words about them, nor "importance" about an activation. "Decide" (the rule whose
  class the model outputs) and "se cumple / holds" (an activation degree) are the words to use.
- **Never claim causes** about the world. Write "the model predicts Good when NO₂ at the same hour yesterday was
  Good", never "NO₂ is good because yesterday was good".
- **Never claim health, regulatory or real-time value.**
- **No disclaimers.** Do not write sentences whose only job is to say what the rules, the figures or the data are not
  (not causal, not a forecast, only a retrospective replay, not a full evaluation). Say what is true and stop.
- Name classes, inputs and terms exactly as in `CONTEXT` (Spanish names in `es`, the `*_en` names in `en`; if an
  English name is missing, keep the Spanish one).
- Rules are named by their id (R02). Quote at most three rules in full.
- If `rule_weighting` is `"none"`, the rules carry no weight: say that the rule that holds most decides and that a tie
  goes to the first rule in the model's order; never mention weights. Otherwise the rule with the highest
  activation × weight decides.
- If something is not in `CONTEXT`, do not write about it. Say less rather than guess.
- Plain register, like a careful colleague explaining a result: no marketing words ("powerful", "impresionante"), no
  emojis, no exclamation marks. See "How to write it" below.

## How to write it

The text should read as if a person who knows the model wrote it by hand. Be plain and concrete, and say each thing once.

- One idea per sentence. Do not chain clauses with colons and semicolons ("R02 decide el 46 %: si…; acierta…"). Use
  a full stop, or a plain connector (y, pero, así que / and, but, so). A colon is fine before a list. Write a rule in
  brackets as condition → class.
- Vary the length and shape of sentences. Do not open every sentence with the rule id, or close every one with
  "frente a un X % observado".
- Do not frame things as "not X but Y". Say what is true directly.
- Do not group things in threes for rhythm, and do not add a closing sentence that restates the paragraph.
- No em dashes. No announcing ("Cabe destacar que", "It is worth noting that", "En resumen"): say the thing.
- Prefer verbs to nouns ("acierta el 76 %" rather than "tiene un nivel de acierto del 76 %"; "is right 76% of the
  time" rather than "has an accuracy level of 76%").
- Spanish is Spain Spanish, written natively: no calques from English ("en base a", "a nivel de", "jugar un papel",
  "es por eso que", passives with "ser" where Spanish uses "se"). Use «…» for quotes.
- English is British English (modelled, colour), written natively: no calques from Spanish ("against 35% observed" →
  "compared with 35% observed"; "in 38%" → "38% of the time"). Use “…” for quotes. Never write "because" (the wording
  guard reads it as causal); use "as", or two sentences.
- Name the baselines as running text, the way the web's verdict does: «la regresión logística», «la regresión lineal»,
  «el Random Forest» in Spanish (Random Forest keeps its English name, with a capital F: «del Random Forest», «al
  Random Forest»); "logistic regression", "linear regression", "the random forest" in English, in lower case in the
  middle of a sentence and without quotes. The capitalised English names in CONTEXT (Logistic regression, Random
  forest) are labels: do not copy them into an English sentence, and never translate Random Forest into Spanish.

## Only for a rule mixture (`inference.family` is `"rule_mixture_classifier"`)

Skip this section for any other family. In a rule mixture every rule has a weight for each category (`class_weights`),
and the prediction is the category with the largest total once all the rules that hold are added up.

- Do not write that a rule "decides" a prediction, and do not use the winning-rule wording of the sections above
  ("the rule that holds most decides", a tie going to the first rule).
- Never present a weight as "importance", as "evidence against" a category, or as what the rule means on its own.
  Weights and per-prediction contributions are not probabilities, risks, causes, certainty or confidence either.
- `contributions` is only the name of a field. In the text say what a rule adds to a category's total («lo que una regla
  suma a una categoría»), never "contribution" / «contribución».
- Use only the figures CONTEXT gives for the mixture; if it gives none about a rule, say nothing about that rule's part.

## CONTEXT

The script appends the JSON here.
