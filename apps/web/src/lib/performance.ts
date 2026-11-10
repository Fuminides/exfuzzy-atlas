import type { MetricRow, ModelCard, ModelRules } from "../api/types";
import { tr } from "../i18n";

/** What a bar of the performance report stands for. */
export type BarKey = "model" | "persistence" | "persistence_24h" | "linear" | "forest";
export type ReportMetric = "macro_f1" | "accuracy" | "mae";

export interface PerformanceBar {
  key: BarKey;
  /** The estimator id in the report (e.g. `logistic_regression_subsample`). */
  estimator: string;
  /** Test-period value of the shown metric. */
  value: number;
}

export interface PerformanceReport {
  metric: ReportMetric;
  higherIsBetter: boolean;
  bars: PerformanceBar[];
}

const slice = (r: MetricRow) => r.slice ?? "all";
const value = (rows: readonly MetricRow[], estimator: string, metric: string, s: string) =>
  rows.find((r) => r.estimator === estimator && r.metric === metric && slice(r) === s)?.value ?? null;

/** The metrics a report can show for this card: a classifier has macro-F1 and accuracy; a regression its mean error. */
export const reportMetrics = (card: ModelCard): ReportMetric[] => (card.target_scheme != null ? ["macro_f1", "accuracy"] : ["mae"]);

/**
 * The variant of one baseline family (logistic regression, random forest: full data or the model's subsample, balanced
 * or not) that scored best on VALIDATION on the selection metric (macro-F1, or MAE for a regression). It is chosen once,
 * whatever metric is shown, and never on the test period, so the comparison does not flatter the baselines.
 */
export function pickVariant(rows: readonly MetricRow[], prefix: RegExp, selection: "macro_f1" | "mae"): string | null {
  const higher = selection === "macro_f1";
  const candidates = [...new Set(rows.map((r) => r.estimator))]
    .filter((e) => prefix.test(e))
    .flatMap((e) => {
      const v = value(rows, e, selection, "validation/all");
      return v === null ? [] : [{ e, v }];
    })
    .sort((a, b) => (higher ? b.v - a.v : a.v - b.v) || a.e.localeCompare(b.e));
  return candidates[0]?.e ?? null;
}

/**
 * The bars of the performance report, from the model card's evaluation report (nothing is recomputed): the ExFuzzy
 * model, repeating the last observation, repeating the same hour yesterday (when published), the linear model and the
 * random forest (each the variant picked on validation), all on the test period and the same predictions. A bar whose
 * estimator is missing from the report is left out. null when the report has no ExFuzzy score for the metric.
 */
export function performanceReport(card: ModelCard, metric: ReportMetric): PerformanceReport | null {
  const rows = (card.metrics?.rows ?? []).filter((r) => slice(r) === "all" || slice(r) === "validation/all");
  const classifier = card.target_scheme != null;
  const selection = classifier ? "macro_f1" : "mae";
  const own = [...new Set(rows.map((r) => r.estimator))].find((e) => e.startsWith("exfuzzy"));
  if (!own) return null;
  const linear = pickVariant(rows, classifier ? /^logistic_regression/ : /^(ridge|linear)/, selection);
  const forest = pickVariant(rows, /^random_forest/, selection);
  const wanted: [BarKey, string | null][] = [
    ["model", own],
    ["persistence", "persistence"],
    ["persistence_24h", "persistence_24h"],
    ["linear", linear],
    ["forest", forest],
  ];
  const bars = wanted.flatMap(([key, estimator]) => {
    const v = estimator ? value(rows, estimator, metric, "all") : null;
    return estimator && v !== null ? [{ key, estimator, value: v }] : [];
  });
  if (!bars.some((b) => b.key === "model")) return null;
  return { metric, higherIsBetter: metric !== "mae", bars };
}

/** The bar's name in the interface language. */
export function barLabel(key: BarKey, classifier: boolean): string {
  switch (key) {
    case "model":
      return "ExFuzzy";
    case "persistence":
      return classifier ? tr("Repetir la última categoría", "Repeat the last category") : tr("Repetir el último valor", "Repeat the last value");
    case "persistence_24h":
      return classifier ? tr("Repetir la de ayer a la misma hora", "Repeat yesterday's category at the same hour") : tr("Repetir el de ayer a la misma hora", "Repeat yesterday's value at the same hour");
    case "linear":
      // Model families keep their technical (English) name in both languages.
      return classifier ? "Logistic regression" : "Linear regression";
    case "forest":
      return tr("Random Forest", "Random forest"); // Spanish capitalises Forest (user, 2026-11-10)
  }
}

/** How the ExFuzzy model stands against a bar: within 0.01 (or 1 % of the error) is a tie. */
export function standing(model: number, other: number, higherIsBetter: boolean): "above" | "par" | "below" {
  const tol = higherIsBetter ? 0.01 : 0.01 * Math.abs(other);
  if (Math.abs(model - other) < tol) return "par";
  return model > other === higherIsBetter ? "above" : "below";
}

/** How big the whole model is: number of rules and their mean number of conditions. */
export function modelSize(rules: Pick<ModelRules, "rules">): { rules: number; meanConditions: number } {
  const n = rules.rules.length;
  const conditions = rules.rules.reduce((s, r) => s + r.antecedents.length, 0);
  return { rules: n, meanConditions: n > 0 ? conditions / n : 0 };
}

/**
 * How the model does at one entity against all of them, on the test period, from the card's evaluation report (slices
 * `entity=<id>` and `all`): accuracy for a classifier, mean absolute error for a regression. null when the report has no
 * per-entity slice for it (NYC publishes slices by volume group, not by zone).
 */
export function entityScore(card: ModelCard, entityId: string): { metric: "accuracy" | "mae"; here: number; overall: number; n: number } | null {
  const rows = card.metrics?.rows ?? [];
  const own = [...new Set(rows.map((r) => r.estimator))].find((e) => e.startsWith("exfuzzy"));
  if (!own) return null;
  const metric = card.target_scheme != null ? "accuracy" : "mae";
  const here = rows.find((r) => r.estimator === own && r.metric === metric && slice(r) === `entity=${entityId}`);
  const overall = value(rows, own, metric, "all");
  return here && overall !== null ? { metric, here: here.value, overall, n: here.n } : null;
}
