import type { ModelRules, RuleDefinition } from "../api/types";
import { tr } from "../i18n";
import { dec, pct } from "./format";

/**
 * Contract v0.7, the mixture of rules (`rule_mixture_classifier`): every rule has a weight per class and the predicted
 * class is the one with the largest total of bias + Σ weight × firing. No single rule decides, so the winning-rule words
 * («decide», «la decidió», «ganadora») never describe it. What a rule does to a class is said as what it adds to that
 * class («lo que una regla suma a una categoría»): support (+) or suppression (−) in the centred form. Every number comes
 * from the API (`class_weights_centred`, `class_contributions_centred`, `class_scores`, `top_contributor_share`…);
 * this module only formats and words them. The words of every view that names a mixture's figures live here.
 */

export const MIXTURE_FAMILY = "rule_mixture_classifier";

type WithInference = { inference: Pick<ModelRules["inference"], "family"> };

export const isMixture = (m: WithInference | null | undefined): boolean => m?.inference.family === MIXTURE_FAMILY;
export const isMixtureImportance = (i: { measure?: string } | null | undefined): boolean => i?.measure === "rule_mixture";

/**
 * The share a view ranks and colours the rules by: the share of the predictions a rule decides (winning rule, TSK) or,
 * in a mixture, the share in which it is the top rule (it adds the most to the predicted class). 0 when absent.
 */
export const leadShare = (r: { decided_share?: number | null; top_contributor_share?: number | null }): number =>
  r.decided_share ?? r.top_contributor_share ?? 0;

/** The centred weights of a rule, in the scheme's class order (null for any other family). */
export function centredWeights(rule: Pick<RuleDefinition, "class_weights_centred">, classes: readonly string[]): { cls: string; value: number }[] | null {
  const w = rule.class_weights_centred;
  if (!w) return null;
  return classes.filter((c) => typeof w[c] === "number").map((c) => ({ cls: c, value: w[c]! }));
}

/** The largest |centred weight| of the model: the common scale of the weight bars (drawing only, never shown). */
export function weightScale(rules: readonly Pick<RuleDefinition, "class_weights_centred">[]): number {
  let max = 0;
  for (const r of rules) for (const v of Object.values(r.class_weights_centred ?? {})) max = Math.max(max, Math.abs(v));
  return max;
}

/** A signed figure with a true minus sign: «+2,22», «−1,34», «0,00». */
export function signed(v: number, digits = 2): string {
  const s = dec(Math.abs(v), digits);
  if (s === dec(0, digits)) return s;
  return v > 0 ? `+${s}` : `−${s}`;
}

/** «apoyo» / «supresión» (and «nada» for an exact zero at the shown precision). */
export function polarity(v: number, digits = 2): "support" | "suppression" | "none" {
  if (dec(Math.abs(v), digits) === dec(0, digits)) return "none";
  return v > 0 ? "support" : "suppression";
}
export const polarityWord = (p: "support" | "suppression" | "none"): string =>
  ({ support: tr("apoyo", "support"), suppression: tr("supresión", "suppression"), none: tr("nada", "nothing") })[p];

// ------------------------------------------------------------------------------------------------------------- words

/** How a mixture predicts, in one short paragraph (Patrones' lead, the hovercard, ¿Por qué aquí?). */
export const howItPredicts = (): string =>
  tr("Cada regla tiene un peso para cada categoría. Las reglas que se cumplen suman su apoyo a cada categoría, y se predice la que más total reúne. Ninguna regla decide sola.",
    "Each rule has a weight for each category. The rules that hold add up their support for each category, and the category with the largest total is predicted. No single rule decides.");

/** What a centred weight is (legend of the weight bars). */
export const centredNote = (): string =>
  tr("Peso centrado: el peso de la regla para esa categoría menos su media en todas las categorías. Positivo es apoyo: la regla sube esa categoría frente a las demás. Negativo es supresión: la baja frente a las demás.",
    "Centred weight: the rule's weight for that category minus its mean over all the categories. Positive is support: the rule raises that category against the others. Negative is suppression: it lowers it against the others.");

export const strongestText = (name: string | null): string =>
  name === null ? tr("no apoya ninguna categoría más que otra", "supports no category more than another") : tr(`apoya sobre todo ${name}`, `supports ${name} most`);

/** The rule that adds the most to the predicted category (the mixture's analogue of the deciding rule). */
export const topRuleLabel = (): string => tr("La regla que más suma", "The rule that adds the most");
export const topRulesLabel = (): string => tr("Las reglas que más suman", "The rules that add the most");

/** «es la que más suma a la categoría prevista en el 45 % de las predicciones». */
export function topShareText(share: number | null | undefined): string {
  if (share == null || share === 0) return tr("nunca es la que más suma a la categoría prevista", "never adds the most to the predicted category");
  return tr(`es la que más suma a la categoría prevista en el ${pct(share)} de las predicciones`, `adds the most to the predicted category in ${pct(share)} of the predictions`);
}

/** «sin ella cambiaría la categoría del 5,6 % de las predicciones». */
export function decisiveText(share: number | null | undefined): string | null {
  if (share == null) return null;
  if (share === 0) return tr("sin ella no cambiaría ninguna categoría prevista", "without it no predicted category would change");
  return tr(`sin ella cambiaría la categoría del ${pct(share)} de las predicciones`, `without it ${pct(share)} of the predictions would change category`);
}

/** How often the predictions it adds the most to are right. */
export const hitsWhenTop = (accuracy: number): string => tr(`acierta el ${pct(accuracy)} de esas`, `right ${pct(accuracy)} of the time in those`);

/** One prediction: the top rule and its share of what the supporting rules add to the predicted category. */
export const topRuleShareText = (ruleId: string, share: number, className: string): string =>
  tr(`${ruleId} es la regla que más suma a ${className}: el ${pct(share)} de lo que suman las reglas que la apoyan.`,
    `${ruleId} adds the most to ${className}: ${pct(share)} of what the rules that support it add.`);

/** The same sentence without the rule id, to follow a rule chip: «es la regla que más suma a Buena: el 40 % de…». */
export const topRuleShareTail = (share: number, className: string): string =>
  tr(`es la regla que más suma a ${className}: el ${pct(share)} de lo que suman las reglas que la apoyan.`,
    `adds the most to ${className}: ${pct(share)} of what the rules that support it add.`);

/** The share of the variable: of the predictions, those whose top rule uses it. */
export const variableShareNote = (): string =>
  tr("Parte de las predicciones en las que la regla que más suma a la categoría prevista usa cada variable.", "Share of the predictions in which the rule that adds the most to the predicted category uses each variable.");

/** «Cómo se mide» of Patrones for a mixture. */
export const measuredNote = (): string =>
  tr("En este modelo ninguna regla decide sola: las reglas que se cumplen suman su apoyo a cada categoría y gana la de más total. «La que más suma» es la regla que más apoyo añade a la categoría prevista en una predicción (sin contar lo que resta a las demás). «Acierta» es la parte de esas predicciones (las que tienen observación) en la que la categoría coincide con la observada. «Sin ella» cuenta las predicciones cuya categoría cambiaría si la regla no estuviera.",
    "In this model no single rule decides: the rules that hold add up their support for each category and the one with the largest total wins. “Adds the most” is the rule that adds the most support to the predicted category in a prediction (not counting what it takes from the others). “Is right” is the share of those predictions (the ones with an observation) whose category matches the observed one. “Without it” counts the predictions whose category would change if the rule were not there.");

export const decisiveLabel = (): string => tr("Sin ella cambiaría", "Without it, would change");
