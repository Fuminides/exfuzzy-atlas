import { afterEach, describe, expect, it } from "vitest";
import { setLang } from "../i18n";
import { metricLabel, ruleMetrics } from "./ruleMetrics";

afterEach(() => setLang("es"));

describe("rule metric labels", () => {
  it("Spanish: fixed keys and the tau of a frequency with a decimal comma; unknown keys as they come", () => {
    expect([metricLabel("n_antecedents"), metricLabel("mean_activation"), metricLabel("activation_frequency_tau0.5"), metricLabel("support")]).toEqual([
      "nº de antecedentes",
      "activación media",
      "frecuencia de activación ≥ 0,5",
      "support",
    ]);
  });

  it("English: the same keys in English, the tau with a decimal point; never 'importance'", () => {
    setLang("en");
    expect([metricLabel("n_antecedents"), metricLabel("mean_activation"), metricLabel("activation_frequency_tau0.5")]).toEqual([
      "no. of antecedents",
      "mean activation",
      "activation frequency ≥ 0.5",
    ]);
    const rows = ruleMetrics({ metrics: { mean_activation: 0.25, n_antecedents: 2 } });
    expect(rows.map((r) => `${r.label} ${r.text}`)).toEqual(["mean activation 0.250", "no. of antecedents 2"]);
    expect(rows.map((r) => r.label).join(" ")).not.toMatch(/importan|probabilit/i);
  });
});
