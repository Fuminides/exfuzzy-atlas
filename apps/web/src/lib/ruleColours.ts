import { tr } from "../i18n";
import { ruleColor, RULE_PALETTE } from "./territories";

/**
 * One colour per rule across the app (Patrones zones map, Predicción "regla que decidió"). The rules that decide most
 * predictions (the ranking of Patrones) get a palette colour each; every other rule shares one grey, so the legend
 * stays readable. The ranking is the one the cards use, so a rule has the same colour wherever it is drawn.
 */
// Five, not six: the palette's 1st and 6th colours are both blues and read alike on the map.
export const MAX_RULE_COLOURS = 5;
export const OTHER_RULES = "otras reglas";
/** What the legends show for the grey "other rules" (OTHER_RULES stays the map key, in any language). */
export const otherRulesLabel = (): string => tr("otras reglas", "other rules");
export const OTHER_RULES_COLOUR = "#a7b0bd";

/** rule id -> colour, for the first `MAX_RULE_COLOURS` rules of the ranking. */
export const ruleColours = (rankedIds: readonly string[]): ReadonlyMap<string, string> =>
  new Map(rankedIds.slice(0, MAX_RULE_COLOURS).map((id, i) => [id, RULE_PALETTE[i]!]));

/** The label a map feature carries for a rule: its id when it has its own colour, "otras reglas" otherwise. */
export const colourKey = (colours: ReadonlyMap<string, string>, ruleId: string): string => (colours.has(ruleId) ? ruleId : OTHER_RULES);

/** Colour of a rule, or of a key as `colourKey` returns it. */
export const colourOf = (colours: ReadonlyMap<string, string>, ruleIdOrKey: string): string => colours.get(ruleIdOrKey) ?? OTHER_RULES_COLOUR;

/** Colour of a rule in a view that may lack the ranking yet: the shared colour, or the model-order one as the fallback. */
export const colourOrModelOrder = (colours: ReadonlyMap<string, string> | null | undefined, rules: readonly { rule_id: string }[], ruleId: string): string =>
  colours ? colourOf(colours, ruleId) : ruleColor(rules, ruleId);

/** The `classes` of a categorical map layer: every coloured rule, then the grey for the rest. */
export const colourClasses = (colours: ReadonlyMap<string, string>): { label: string; color: string }[] => [
  ...[...colours].map(([label, color]) => ({ label, color })),
  { label: OTHER_RULES, color: OTHER_RULES_COLOUR },
];

/** What a legend lists: the rules present among `ruleIds`, coloured ones in ranking order with their counts, then how many fall in grey. */
export function presentRules(colours: ReadonlyMap<string, string>, ruleIds: readonly (string | null | undefined)[]): { coloured: { id: string; n: number }[]; others: { ids: string[]; n: number } } {
  const counts = new Map<string, number>();
  for (const id of ruleIds) if (id) counts.set(id, (counts.get(id) ?? 0) + 1);
  const coloured = [...colours.keys()].flatMap((id) => (counts.has(id) ? [{ id, n: counts.get(id)! }] : []));
  const otherIds = [...counts.keys()].filter((id) => !colours.has(id));
  return { coloured, others: { ids: otherIds, n: otherIds.reduce((a, id) => a + counts.get(id)!, 0) } };
}

/**
 * Colours of the profiles of "Por zonas", in order (A, B…). Hues the rule colours do not use, so a profile is not read
 * as a rule; from the dataviz reference palette, checked all-pairs on the light basemap (normal-vision ΔE ≥ 15.6; CVD in
 * the 6–8 band, so the letter and the table carry the identity too).
 */
export const PROFILE_COLOURS: readonly string[] = ["#1baf7a", "#e34948", "#6250d6", "#eda100", "#008300"];
/** An entity with predictions but no characteristic rule or profile: white with the dark rim every point has. */
export const NEUTRAL_ZONE_COLOUR = "#ffffff";
