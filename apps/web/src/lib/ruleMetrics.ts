import type { RuleDefinition } from "../api/types";
import { tr } from "../i18n";
import { fmt } from "./format";

// Built at call time (not at import): the language can change while the page is open.
const fixedLabel = (key: string): string | undefined =>
  ({ n_antecedents: tr("nº de antecedentes", "no. of antecedents"), mean_activation: tr("activación media", "mean activation"), weight_spread: tr("diferencia entre su mayor y su menor peso", "spread between its largest and smallest weight") })[key];

/** Plain-language name of a rule metric key; unknown keys are shown as they come. Never "importance". */
export function metricLabel(key: string): string {
  const fixed = fixedLabel(key);
  if (fixed) return fixed;
  const tau = /^activation_frequency_tau(.+)$/.exec(key);
  return tau ? tr(`frecuencia de activación ≥ ${tau[1]!.replace(".", ",")}`, `activation frequency ≥ ${tau[1]!}`) : key;
}

export interface RuleMetric {
  key: string;
  label: string;
  /** Display text; counts are integers, the rest are fractions with 3 decimals (never percentages). */
  text: string;
  /** True for mean_activation / activation_frequency_*: shown inline in the rail. */
  activation: boolean;
}

/** The `metrics` the model publishes for a rule, as labelled rows. */
export function ruleMetrics(rule: Pick<RuleDefinition, "metrics">): RuleMetric[] {
  return Object.entries(rule.metrics ?? {})
    .map(([key, value]) => ({
      key,
      label: metricLabel(key),
      text: key === "n_antecedents" ? String(value) : fmt(value),
      activation: key === "mean_activation" || key.startsWith("activation_frequency"),
    }))
    .sort((a, b) => Number(b.activation) - Number(a.activation) || a.key.localeCompare(b.key));
}
