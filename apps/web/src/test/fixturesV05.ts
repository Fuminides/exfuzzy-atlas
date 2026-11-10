import type { EntityCollection, ModelRules, RuleImportanceResponse, SummaryResponse } from "../api/types";

/**
 * Contract v0.5 test payloads (typed by the generated types): the data summary and the rule importance. The numbers are
 * invented and small so a test can state what each one must look like on screen; the synthetic fixtures carry
 * `synthetic: true` like every payload built on them.
 */

const ids = (e: EntityCollection) => e.features.map((f) => f.properties.entity_id);

/** A classified summary: shares per class for the whole history, by year, month, hour, weekday and entity. The first entity has no observations. */
export function classifiedSummary(rules: ModelRules, entities: EntityCollection, taskId: string, synthetic = true): SummaryResponse {
  const classes = rules.target_scheme!.classes;
  const n = classes.length;
  const shares = (worse: number) => classes.map((_, i) => (i === n - 1 ? worse : i === 0 ? 1 - worse - 0.2 : i === 1 ? 0.2 : 0));
  const row = (key: string, count: number, worse: number) => ({ key, n: count, shares: shares(worse) });
  const emptyKey = { key: "02", n: 0, shares: null, quantiles: null };
  return {
    schema_version: "0.5.0",
    data_version: "v05-test",
    synthetic,
    task_id: taskId,
    domain: rules.domain,
    variable: "y",
    label: "Concentración observada",
    unit: "u",
    timezone: "Europe/Madrid",
    period_from_utc: "2024-01-01T00:00:00Z",
    period_to_utc: "2025-01-01T00:00:00Z",
    classes,
    groups: {
      all: [row("all", 1000, 0.1)],
      year: [row("2024", 1000, 0.1)],
      month: [row("01", 500, 0.05), emptyKey, row("03", 20, 0.3)],
      hour: [row("08", 100, 0.2), row("14", 100, 0.05)],
      weekday: [row("0", 300, 0.12), row("6", 100, 0.02)],
      entity: ids(entities).slice(1).map((id, i) => row(id, 400 - i * 100, 0.3 - i * 0.1)),
    },
    notes: ["Cada valor observado cuenta una vez por estación e instante."],
  };
}

/** A numeric summary (quantiles, no classes), as a regression task would have. */
export function numericSummary(rules: ModelRules, entities: EntityCollection, taskId: string): SummaryResponse {
  const q = (p50: number) => ({ p10: p50 - 6, p25: p50 - 3, p50, p75: p50 + 3, p90: p50 + 6, mean: p50 + 0.5 });
  const row = (key: string, n: number, p50: number) => ({ key, n, quantiles: q(p50), shares: null });
  return {
    schema_version: "0.5.0",
    data_version: "v05-test",
    synthetic: true,
    task_id: taskId,
    domain: rules.domain,
    variable: "no2",
    label: "NO₂ horario observado",
    unit: "ug/m3",
    timezone: "Europe/Madrid",
    period_from_utc: "2025-01-01T00:00:00Z",
    period_to_utc: "2026-01-01T00:00:00Z",
    classes: null,
    groups: {
      all: [row("all", 900, 30)],
      year: [row("2025", 900, 30)],
      month: [row("01", 450, 34), row("02", 450, 26)],
      hour: [row("08", 100, 40)],
      weekday: [row("0", 300, 31)],
      entity: ids(entities).slice(1).map((id, i) => row(id, 300, 20 + i * 10)),
    },
    notes: [],
  };
}

/**
 * Importance of a winning-rule classifier: rule i decides a decreasing share of the predictions; the accuracy of the
 * last rule is null (nothing to check). The first entity has no predictions (it is absent from `entities`).
 */
export function classifierImportance(rules: ModelRules, entities: EntityCollection, taskId: string): RuleImportanceResponse {
  const shares = [0.4, 0.3, 0.2, 0.1].slice(0, rules.rules.length);
  const features = rules.variables.map((v) => v.feature);
  return {
    schema_version: "0.5.0",
    data_version: "v05-test",
    synthetic: true,
    model_id: rules.model_id,
    task_id: taskId,
    measure: "winning_rule",
    period_from_utc: "2024-02-06T01:00:00Z",
    period_to_utc: "2024-02-15T00:00:00Z",
    n_predicted: 1000,
    n_no_rule: 50,
    // v0.5.2: the base rate over the same predictions as the accuracy (deliberately not Resumen's 70 % for the first class)
    observed_class_shares: Object.fromEntries((rules.target_scheme?.classes ?? []).map((c, i, all) => [c.label, i === 0 ? 0.55 : 0.45 / (all.length - 1)])),
    rules: rules.rules.map((r, i) => ({
      rule_id: r.rule_id,
      decided_share: shares[i] ?? 0,
      n_decided: Math.round((shares[i] ?? 0) * 1000),
      n_checked: i === 3 ? 0 : Math.round((shares[i] ?? 0) * 1000 * 0.9),
      accuracy: i === 3 ? null : 0.92 - i * 0.1,
    })),
    variables: features.map((f, i) => ({
      feature: f,
      decided_share: 0.8 - i * 0.2,
      n_rules: rules.rules.filter((r) => r.antecedents.some((a) => a.feature === f)).length,
    })),
    entities: ids(entities).slice(1).map((id, i) => ({
      entity_id: id,
      n_predicted: 300,
      rules: rules.rules.slice(0, 2).map((r, k) => ({ rule_id: r.rule_id, decided_share: k === i % 2 ? 0.6 : 0.3, accuracy: 0.9 })),
    })),
  };
}

/** Importance of the additive regression: exact weight share and MAE where the rule decides. */
export function regressionImportance(rules: ModelRules, entities: EntityCollection, taskId: string): RuleImportanceResponse {
  const shares = [0.5, 0.3, 0.2];
  return {
    schema_version: "0.5.0",
    data_version: "v05-test",
    synthetic: true,
    model_id: rules.model_id,
    task_id: taskId,
    measure: "weighted_average",
    period_from_utc: "2025-01-01T00:00:00Z",
    period_to_utc: "2026-01-01T00:00:00Z",
    n_predicted: 800,
    n_no_rule: 0,
    rules: rules.rules.map((r, i) => ({
      rule_id: r.rule_id,
      decided_share: shares[i] ?? 0,
      n_decided: Math.round((shares[i] ?? 0) * 800),
      n_checked: Math.round((shares[i] ?? 0) * 800),
      mae: 2.5 + i,
      mean_weight_share: shares[i] ?? 0,
    })),
    variables: rules.variables.map((v, i) => ({ feature: v.feature, decided_share: 0.7 - i * 0.3, n_rules: 2 })),
    entities: ids(entities).slice(1).map((id) => ({ entity_id: id, n_predicted: 200, rules: [{ rule_id: rules.rules[0]!.rule_id, decided_share: 0.7, mae: 2.5, mean_weight_share: 0.6 }] })),
  };
}
