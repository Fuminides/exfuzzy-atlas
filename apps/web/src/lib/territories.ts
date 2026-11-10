import type { ModelRules, RuleTerritoriesResponse, TerritoryMeasure } from "../api/types";
import type { StationRow } from "../map/stations";
import { tr } from "../i18n";
import { dec } from "./format";

/**
 * Rule Territories (E2). The backend decides everything that matters: `dominant_rule_id` is the argmax of the requested
 * measure only (tie-break to the lowest rule position), `n_valid` is the denominator. This module only turns the answer
 * into map rows and chooses colours. Territories overlap: the colour is the dominant rule of ONE measure, not a partition
 * and never the rule that explains a prediction.
 */

export const TERRITORY_MEASURES: readonly TerritoryMeasure[] = ["mean_activation", "activation_frequency", "winner_share"];

/** Labels of the measures; getters, so each read follows the current language. */
export const MEASURE_LABEL: Record<TerritoryMeasure, string> = {
  get mean_activation() { return tr("Activación media", "Mean activation"); },
  get activation_frequency() { return tr("Frecuencia ≥ τ", "Frequency ≥ τ"); },
  get winner_share() { return tr("Reglas ganadoras (solo clasificadores)", "Winning rules (classifiers only)"); },
};

/** The measure as a phrase inside a sentence; the API's identifier is never shown. */
const MEASURE_NAME: Record<TerritoryMeasure, string> = {
  get mean_activation() { return tr("activación media", "mean activation"); },
  get activation_frequency() { return tr("frecuencia de activación", "activation frequency"); },
  get winner_share() { return tr("reglas ganadoras", "winning rules"); },
};
export const measureName = (measure: string): string => MEASURE_NAME[measure as TerritoryMeasure] ?? measure;

/**
 * The measure as a noun phrase with its Spanish article, for «según la …» and «La … de la regla R01 …»: «reglas ganadoras»
 * is plural («las reglas ganadoras»), so an article glued in front of `measureName` would give «la reglas ganadoras».
 * English needs no article for the first use; "the" is part of the phrase for the second. `capital` starts a sentence.
 */
export function measureThe(measure: string, capital = false): string {
  const phrase =
    measure === "mean_activation"
      ? tr("la activación media", "the mean activation")
      : measure === "activation_frequency"
        ? tr("la frecuencia de activación", "the activation frequency")
        : measure === "winner_share"
          ? tr("las reglas ganadoras", "the winning rules")
          : tr(`la ${measure}`, `the ${measure}`);
  return capital ? phrase.charAt(0).toUpperCase() + phrase.slice(1) : phrase;
}

/** What each measure is, in one sentence; the denominator is always `n_valid`. */
export const MEASURE_DEFINITION: Record<TerritoryMeasure, (tau: number) => string> = {
  mean_activation: () => tr("media del grado de activación de la regla en los registros válidos de la entidad", "mean of the rule's activation degree over the entity's valid records"),
  activation_frequency: (tau) => tr(`fracción de los registros válidos de la entidad en los que la activación de la regla es ≥ τ = ${dec(tau, 2)}`, `fraction of the entity's valid records in which the rule's activation is ≥ τ = ${dec(tau, 2)}`),
  winner_share: () => tr("fracción de los registros válidos de la entidad en los que la regla decidió la clase (suma ≤ 1: sin regla activa no hay ganadora)", "fraction of the entity's valid records in which the rule decided the class (sum ≤ 1: with no active rule there is no winner)"),
};

/**
 * Categorical colours for rules (Tableau 20 order: strong tones first). Deliberately not viridis (activation), magma
 * (predicted concentration) nor the class colours of a scheme: a rule colour never reads as a value or a class.
 * With more than 20 rules colours repeat; the legend then lists only the rules present and the table has the id.
 */
// The first five (the rules coloured on the Patrones and Predicción maps) avoid the traffic-light hues of the class
// schemes: no red, green, yellow or cyan, so a rule is never read as «Desfavorable» or «Buena». On a map any two colours
// can sit side by side, so they are validated all-pairs (dataviz validator, `--pairs all`) on the basemap's land
// (#f2f3f0), white and Mist (#f2f2f3): worst colour-blind ΔE 11.9 (magenta↔violet, protan), worst normal-vision ΔE 17.8.
// Retuned for DESIGN.md (2026-11-09): blue and orange kept; violet, magenta and brown replace #7a4fc4, #e87ba4 and
// #b07a00, which failed all-pairs (gold↔orange ΔE 2.0 protan / 11.8 normal, violet↔blue 3.9 / 12.7). The orange is
// 2.9:1 on the land, so map points keep their dark rim and every legend names the rule. The tail only cycles for the
// Territorios view, where a rule is always named in the legend.
export const RULE_PALETTE: readonly string[] = [
  "#2a78d6", "#eb6834", "#6b2fa5", "#b84888", "#7f4413", "#1c5cab",
  "#4e79a7", "#f28e2b", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac", "#1f4e79", "#c55a11", "#6c3f7a", "#d4577a",
  "#5b3f2c", "#6b6b6b",
];

/** Colour of a rule by its position in the model (stable while browsing windows and measures). */
export function ruleColor(rules: readonly Pick<ModelRules["rules"][number], "rule_id">[], ruleId: string): string {
  const i = rules.findIndex((r) => r.rule_id === ruleId);
  return RULE_PALETTE[(i < 0 ? 0 : i) % RULE_PALETTE.length]!;
}

/** Colour of the rules that are not highlighted in "territory" focus: quiet, never a data colour. */
export const DIMMED_RULE = "#dfe5ec";

export type TerritoryFocus = "all" | "territory" | "intensity";

/** The measure of one rule at one entity (null when the entity has no rule stats: nothing observed, or no model). */
export function ruleValue(p: RuleTerritoriesResponse["features"][number]["properties"], ruleId: string, measure: TerritoryMeasure): number | null {
  const stats = p.rules?.find((r) => r.rule_id === ruleId);
  if (!stats) return null;
  return measure === "winner_share" ? (stats.winner_share ?? null) : stats[measure];
}

/**
 * Rows for the map and the table. "all"/"territory": `label` = dominant rule (null = no dominant rule, never a colour).
 * "intensity": `value` = the focused rule's measure per entity (a sequential scale; null stays null, 0 stays 0).
 * An entity absent from the answer keeps `label: null` and its own missing reason; "sin modelo" is kept as is.
 */
export function territoryRows(
  base: readonly StationRow[],
  data: RuleTerritoriesResponse,
  focus: TerritoryFocus,
  ruleId: string | null,
): StationRow[] {
  const byId = new Map(data.features.map((f) => [f.properties.entity_id, f.properties]));
  return base.map((r) => {
    const p = byId.get(r.entityId);
    if (!p) return r;
    const nValid = p.n_valid;
    const notModelled = p.missing_reason === "not_modelled";
    const missingReason = p.dominant_rule_id ? null : (p.missing_reason ?? (nValid === 0 ? "no_observation" : null));
    if (focus === "intensity" && ruleId !== null) {
      const value = notModelled ? null : ruleValue(p, ruleId, data.measure);
      return { ...r, value, label: null, nValid, missingReason: value === null ? (p.missing_reason ?? (nValid === 0 ? "no_observation" : null)) : null };
    }
    return { ...r, value: null, label: p.dominant_rule_id ?? null, nValid, missingReason };
  });
}

/** Per rule, how many entities it dominates, in rule order; only rules that dominate at least one entity. */
export function dominanceCounts(data: RuleTerritoriesResponse): { ruleId: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const f of data.features) {
    const id = f.properties.dominant_rule_id;
    if (id) counts.set(id, (counts.get(id) ?? 0) + 1);
  }
  const order = new Map<string, number>();
  for (const f of data.features) f.properties.rules?.forEach((r, i) => order.set(r.rule_id, i));
  return [...counts]
    .map(([ruleId, count]) => ({ ruleId, count }))
    .sort((a, b) => (order.get(a.ruleId) ?? 0) - (order.get(b.ruleId) ?? 0) || a.ruleId.localeCompare(b.ruleId));
}

