import { afterEach, describe, expect, it } from "vitest";
import type { ModelCard } from "../api/types";
import { setLang } from "../i18n";
import { barLabel, modelSize, performanceReport, pickVariant, reportMetrics, standing } from "./performance";

afterEach(() => setLang("es"));

const row = (estimator: string, metric: string, value: number, slice = "all") => ({ estimator, metric, value, n: 100, slice });
const card = (rows: ReturnType<typeof row>[], classifier = true) => ({ target_scheme: classifier ? { classes: [] } : null, metrics: { rows } }) as unknown as ModelCard;

const madridLike = card([
  row("exfuzzy_classifier", "macro_f1", 0.41), row("exfuzzy_classifier", "accuracy", 0.82),
  row("persistence", "macro_f1", 0.29), row("persistence", "accuracy", 0.77),
  row("persistence_24h", "macro_f1", 0.41), row("persistence_24h", "accuracy", 0.82),
  // the full-data LR is better on test, but the subsample variant was better on validation: the subsample is shown
  row("logistic_regression", "macro_f1", 0.45), row("logistic_regression", "macro_f1", 0.30, "validation/all"), row("logistic_regression", "accuracy", 0.84),
  row("logistic_regression_subsample", "macro_f1", 0.42), row("logistic_regression_subsample", "macro_f1", 0.44, "validation/all"), row("logistic_regression_subsample", "accuracy", 0.81),
  row("random_forest_subsample", "macro_f1", 0.43), row("random_forest_subsample", "macro_f1", 0.46, "validation/all"), row("random_forest_subsample", "accuracy", 0.80),
  row("random_forest", "macro_f1", 0.39), row("random_forest", "macro_f1", 0.40, "validation/all"),
]);

describe("performance report", () => {
  it("shows ExFuzzy, the two repeat baselines, and the LR and RF variants picked on validation, with their test values", () => {
    const r = performanceReport(madridLike, "macro_f1")!;
    expect(r.bars.map((b) => [b.key, b.estimator, b.value])).toEqual([
      ["model", "exfuzzy_classifier", 0.41],
      ["persistence", "persistence", 0.29],
      ["persistence_24h", "persistence_24h", 0.41],
      ["linear", "logistic_regression_subsample", 0.42],
      ["forest", "random_forest_subsample", 0.43],
    ]);
  });

  it("keeps the variants picked on macro-F1 when accuracy is shown (one choice, whatever the metric)", () => {
    const r = performanceReport(madridLike, "accuracy")!;
    expect(r.bars.find((b) => b.key === "linear")).toMatchObject({ estimator: "logistic_regression_subsample", value: 0.81 });
    expect(r.higherIsBetter).toBe(true);
  });

  it("leaves out what the report does not have, and is null without an ExFuzzy score", () => {
    const r = performanceReport(card([row("exfuzzy_classifier", "macro_f1", 0.4), row("persistence", "macro_f1", 0.3)]), "macro_f1")!;
    expect(r.bars.map((b) => b.key)).toEqual(["model", "persistence"]);
    expect(performanceReport(card([row("persistence", "macro_f1", 0.3)]), "macro_f1")).toBeNull();
  });

  it("a regression shows its mean error, with ridge as the linear model, lower being better", () => {
    const water = card([row("exfuzzy", "mae", 0.635), row("ridge", "mae", 0.659), row("ridge", "mae", 0.7, "validation/all"), row("random_forest", "mae", 0.548), row("random_forest", "mae", 0.6, "validation/all")], false);
    expect(reportMetrics(water)).toEqual(["mae"]);
    const r = performanceReport(water, "mae")!;
    expect(r.higherIsBetter).toBe(false);
    expect(r.bars.map((b) => b.key)).toEqual(["model", "linear", "forest"]);
    expect(standing(0.635, 0.659, false)).toBe("above");
  });

  it("standing: within 0.01 is a tie; names in both languages; model size", () => {
    expect([standing(0.41, 0.407, true), standing(0.41, 0.43, true), standing(0.41, 0.29, true)]).toEqual(["par", "below", "above"]);
    expect(pickVariant([], /^x/, "macro_f1")).toBeNull();
    expect(barLabel("persistence_24h", true)).toBe("Repetir la de ayer a la misma hora");
    setLang("en");
    expect(barLabel("linear", true)).toBe("Logistic regression");
    expect(modelSize({ rules: [{ antecedents: [1, 2] }, { antecedents: [1] }] } as never)).toEqual({ rules: 2, meanConditions: 1.5 });
  });
});
