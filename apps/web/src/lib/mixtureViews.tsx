import type { PredictionProperties } from "../api/types";
import { tr } from "../i18n";

/**
 * The words that the peripheral views (Predicción, Explorar, ¿Y si…?, the landing) use for a mixture of rules (contract
 * v0.7), next to the winning-rule words they keep for the other families. In a mixture no single rule decides, so none
 * of these says «decidió», «ganadora» or "decided": the rule a view names is the one that adds the most to the
 * predicted category (`top_rule_id`). The mixture's shared helpers and figures live in `lib/mixture.ts`.
 */

/** The rule a prediction names: the rule that decided it (winning rule, TSK) or, in a mixture, the one that adds the most. */
export const predictionRule = (p: Pick<PredictionProperties, "decided_by_rule_id" | "top_rule_id">): string | null => p.decided_by_rule_id ?? p.top_rule_id ?? null;

/** «Regla que decidió» / «Regla que más suma» (column of the stations table). */
export const ruleColumnHeader = (mixture: boolean): string =>
  mixture ? tr("Regla que más suma", "Rule that adds the most") : tr("Regla que decidió", "Rule that decided");

/** «regla que decidió» / «regla que más suma» (the option of «Colorear por»). */
export const colourByRuleOption = (mixture: boolean): string =>
  mixture ? tr("regla que más suma", "rule that adds the most") : tr("regla que decidió", "rule that decided");

/** Title of the map coloured by rule. */
export const mapByRuleTitle = (mixture: boolean, predictionTitle: string): string =>
  mixture
    ? tr(`Regla que más suma a la categoría prevista: ${predictionTitle}`, `Rule that adds the most to the predicted category: ${predictionTitle}`)
    : tr(`Regla que decidió cada predicción: ${predictionTitle}`, `Rule that decided each prediction: ${predictionTitle}`);

/** The map's hover text: « · la decidió R04» / « · la que más suma: R01». */
export const tipRule = (mixture: boolean, ruleId: string): string =>
  mixture ? tr(` · la que más suma: ${ruleId}`, ` · adds the most: ${ruleId}`) : tr(` · la decidió ${ruleId}`, ` · decided by ${ruleId}`);

/** The words of the legend of the map coloured by rule (Predicción). */
export function byRuleLegendWords(mixture: boolean, noun: { one: string; many: string }, el: string) {
  const Many = noun.many.charAt(0).toUpperCase() + noun.many.slice(1);
  return mixture
    ? {
        title: tr(`Regla que más suma a la categoría prevista de cada ${noun.one}`, `Rule that adds the most to each ${noun.one}'s predicted category`),
        note: tr(<>Cada color es la regla que más suma a la categoría prevista de {el} {noun.one} a esa hora. En este modelo ninguna regla decide sola: las reglas que se cumplen suman su apoyo a cada categoría. Los colores son categorías, no una escala. Son los mismos que en <em>Patrones</em>: las 8 reglas que más suman, y el resto en gris.</>,
          <>Each colour is the rule that adds the most to the {noun.one}&apos;s predicted category at that hour. In this model no single rule decides: the rules that hold add up their support for each category. The colours are categories, not a scale. They match the colours in <em>Patterns</em>: the 8 rules that add the most, with the rest in grey.</>),
        list: tr("Reglas que más suman a la categoría prevista de alguna predicción en pantalla", "Rules that add the most to the predicted category of a prediction on screen"),
        missing: tr("sin regla que más sume (sin predicción, o ninguna regla apoya la categoría prevista; el motivo se indica en la tabla)", "no top rule (no prediction, or no rule supports the predicted category; the table gives the reason)"),
        count: tr(`${Many} con regla que más suma: `, `${Many} with a top rule: `),
      }
    : {
        title: tr(`Regla que decidió la predicción de cada ${noun.one}`, `Rule that decided each ${noun.one}'s prediction`),
        note: tr(<>Cada color es la regla que decidió la predicción de {el} {noun.one} a esa hora. Los colores son categorías, no una escala. Son los mismos que en <em>Patrones</em>: las 8 reglas que más deciden, y el resto en gris.</>,
          <>Each colour is the rule that decided the {noun.one}&apos;s prediction at that hour. The colours are categories, not a scale. They match the colours in <em>Patterns</em>: the 8 rules that decide most, with the rest in grey.</>),
        list: tr("Reglas que deciden alguna predicción en pantalla", "Rules that decide a prediction on screen"),
        missing: tr("sin regla que decida (sin predicción, o ninguna regla dispara; el motivo se indica en la tabla)", "no deciding rule (no prediction, or no rule fires; the table gives the reason)"),
        count: tr(`${Many} con regla que decidió: `, `${Many} with a deciding rule: `),
      };
}

/** Station detail: the heading and the note under the rule's sentence. */
export const topRuleHeading = (): string => tr("La regla que más suma", "The rule that adds the most");
export const topRuleNote = (): string =>
  tr("Es la regla que más apoyo añade a la categoría prevista. Ninguna regla decide sola: el modelo suma el apoyo de todas las reglas que se cumplen.",
    "It is the rule that adds the most support to the predicted category. No single rule decides: the model adds up the support of all the rules that hold.");

// ---------------------------------------------------------------------------------------------------- Territorios

/** Why «Reglas ganadoras» is not offered for a mixture (the API answers 422 to `winner_share`). */
export const noWinnerShareReason = (): string =>
  tr("«Reglas ganadoras» no existe en este modelo: ninguna regla decide sola, así que no hay ganadora que contar.",
    "“Winning rules” does not exist in this model: no single rule decides, so there is no winner to count.");

// ------------------------------------------------------------------------------------------------------------ ¿Y si…?

export const whatIfTopRuleLabel = (): string => tr("Regla que más suma: ", "Rule that adds the most: ");
export const whatIfTopRuleSame = (same: boolean): string =>
  same ? tr("la regla que más suma no cambia", "the rule that adds the most does not change") : tr("la regla que más suma cambia", "the rule that adds the most changes");
