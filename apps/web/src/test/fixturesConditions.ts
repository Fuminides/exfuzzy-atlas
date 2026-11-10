import type { LinguisticVariable, ModelRules, RuleDefinition, RuleTrace } from "../api/types";
import { trace } from "./fixtures";

/**
 * Contract v0.8 conditions, hand-written: a quantity input with ordered terms (`at_least` / `at_most`) and an hour of the
 * day with compound terms (`any_of`), as the real models publish them (NYC's local hour: Madrugada, Mañana, Mediodía,
 * Tarde-noche). Test data only; the compound names are provisional display names.
 */

export const temperature: LinguisticVariable = {
  feature: "temperature",
  label: "Temperatura",
  label_en: "Temperature",
  domain: [0, 30],
  unit: "°C",
  terms: [
    { name: "Low", membership_type: "trapezoidal", params: [0, 0, 5, 12] },
    { name: "Medium", membership_type: "trapezoidal", params: [5, 12, 18, 25] },
    { name: "High", membership_type: "trapezoidal", params: [18, 25, 30, 30] },
  ],
};

export const hour: LinguisticVariable = {
  feature: "local_hour",
  label: "Hora local",
  label_en: "Local hour",
  domain: [0, 23],
  unit: "hour",
  terms: [
    { name: "Madrugada", membership_type: "trapezoidal", params: [0, 0, 6, 7] },
    { name: "Mañana", membership_type: "trapezoidal", params: [6, 7, 10, 11] },
    { name: "Mediodía", membership_type: "trapezoidal", params: [10, 11, 14, 15] },
    { name: "Tarde-noche", membership_type: "trapezoidal", params: [14, 15, 23, 23] },
  ],
};

export const variables = [temperature, hour];

/** "x is at least Medium": term = the lowest term covered. */
export const atLeast = { feature: "temperature", term: "Medium", operator: "at_least", terms: ["Medium", "High"] } as const;
/** "x is at most Medium": term = the highest term covered. */
export const atMost = { feature: "temperature", term: "Medium", operator: "at_most", terms: ["Low", "Medium"] } as const;
/** A compound: its `term` is an internal name that is not a term of the variable. */
export const earlyHours = { feature: "local_hour", term: "early_hours", operator: "any_of", terms: ["Madrugada", "Mañana"], label: "Primeras horas", label_en: "Early hours" } as const;
/** A compound over the two ends of the clock: it wraps midnight. */
export const lateNight = { feature: "local_hour", term: "late_night", operator: "any_of", terms: ["Madrugada", "Tarde-noche"], label: null, label_en: null } as const;

const rule = (rule_id: string, position: number, antecedents: RuleDefinition["antecedents"]): RuleDefinition => ({
  rule_id,
  position,
  antecedents,
  consequent: { type: "crisp", value: 1, term: null, unit: "u" },
  text: `IF ${antecedents.map((a) => `${a.feature} IS ${a.term}`).join(" AND ")} THEN y = 1`,
});

export const rules: RuleDefinition[] = [
  rule("R01", 0, [{ ...atLeast, terms: [...atLeast.terms] }, { ...earlyHours, terms: [...earlyHours.terms] }]),
  rule("R02", 1, [{ ...atMost, terms: [...atMost.terms] }]),
  rule("R03", 2, [{ feature: "temperature", term: "High" }, { ...lateNight, terms: [...lateNight.terms] }]),
];

/** A trace at hour 8 and 20 °C where the compound and the ordinal condition carry the library's bounded-sum memberships. */
export const traceWith = (): RuleTrace => {
  const base = trace("SYN_A", "07:00");
  return {
    ...base,
    feature_values: [
      { feature: "temperature", value: 20 },
      { feature: "local_hour", value: 8 },
    ],
    rules: [
      {
        rule_id: "R01",
        firing_strength: 0.6,
        effective_firing: 0.6,
        antecedents: [
          { feature: "temperature", term: "Medium", operator: "at_least", terms: ["Medium", "High"], membership: 1, effective_membership: 1 },
          { feature: "local_hour", term: "early_hours", operator: "any_of", terms: ["Madrugada", "Mañana"], membership: 0.6, effective_membership: 0.6 },
        ],
      },
      {
        rule_id: "R03",
        firing_strength: 0.3,
        effective_firing: 0.3,
        antecedents: [{ feature: "temperature", term: "High", membership: 0.3, effective_membership: 0.3 }],
      },
    ],
  };
};

/**
 * The same served model with its first rule's first condition read as "at least" (contract v0.8): the cards, the matrix
 * and the hovercards then write «es al menos …» / "is at least …". Test data only.
 */
export function withAtLeast<T extends { rules?: ModelRules }>(data: T): T {
  const model = data.rules!;
  const first = model.rules[0]!;
  const a = first.antecedents[0]!;
  const covered = model.variables.find((v) => v.feature === a.feature)!.terms.map((t) => t.name);
  const antecedents = [{ ...a, operator: "at_least" as const, terms: covered.slice(covered.indexOf(a.term)) }, ...first.antecedents.slice(1)] as RuleDefinition["antecedents"];
  return { ...data, rules: { ...model, schema_version: "0.8.0", rules: model.rules.map((r) => (r === first ? { ...r, antecedents } : r)) } };
}
