import { afterEach, describe, expect, it } from "vitest";
import { setLang } from "../i18n";
import type { ModelCard } from "../api/types";
import { accuracySummary } from "./AccuracyBlock";

const row = (estimator: string, metric: string, value: number) => ({ estimator, metric, value, n: 1000, slice: "all" });
const card = (rows: ReturnType<typeof row>[], classifier = true): ModelCard =>
  ({
    target_scheme: classifier ? { classes: [] } : undefined,
    metrics: { rows },
  }) as unknown as ModelCard;
const clf = (acc: number, f1: number, baseAcc: number, baseF1: number) =>
  card([
    row("exfuzzy_classifier", "accuracy", acc),
    row("exfuzzy_classifier", "macro_f1", f1),
    row("persistence", "accuracy", baseAcc),
    row("persistence", "macro_f1", baseF1),
  ]);

describe("the one-line model quality (Predicción)", () => {
  it("says both the hit rate and the macro-F1, each against repeating the last observation", () => {
    expect(accuracySummary(clf(0.746, 0.329, 0.769, 0.294), "")).toMatch(
      /^En el periodo de prueba, acierta la categoría en el 75\s% de los casos \(repetir la categoría de la última observación: 77\s%\)\. Si todas las categorías cuentan igual, también las poco frecuentes \(F1 macro\), obtiene 0,33 frente a 0,29\.$/,
    );
  });

  it("says plainly when the model is below on the macro-F1 too, with no spin", () => {
    const text = accuracySummary(clf(0.424, 0.412, 0.439, 0.425), "")!;
    expect(text).toContain("acierta la categoría en el 42");
    expect(text).toContain("obtiene 0,41 frente a 0,43 y se queda por debajo.");
  });

  it("says when the two are indistinguishable (a gap under 0.01)", () => {
    expect(accuracySummary(clf(0.757, 0.652, 0.758, 0.658), "")).toContain("obtiene 0,65 frente a 0,66, sin diferencia apreciable.");
  });

  it("leaves the macro-F1 out when the card does not publish it for both", () => {
    const text = accuracySummary(card([row("exfuzzy_classifier", "accuracy", 0.7), row("persistence", "accuracy", 0.6)]), "")!;
    expect(text).toMatch(/^En el periodo de prueba, acierta la categoría en el 70\s% de los casos \(repetir la categoría de la última observación: 60\s%\)\.$/);
  });

  it("keeps the mean error comparison for a regression", () => {
    const text = accuracySummary(card([row("exfuzzy", "mae", 0.635), row("global_mean", "mae", 1.282)], false), "µg/m³")!;
    expect(text).toMatch(/error medio es 0,64.*, frente a 1,28.* al dar siempre la media del entrenamiento/);
    expect(text).not.toContain("F1");
  });
});

describe("the one-line model quality in English", () => {
  afterEach(() => setLang("es"));

  it("writes the whole sentence in English, with point decimals and no space before %", () => {
    setLang("en");
    expect(accuracySummary(clf(0.746, 0.329, 0.769, 0.294), "")).toBe(
      "In the test period, it gets the category right in 75% of the cases (repeating the category of the last observation: 77%). If every category counts the same, rare ones included (macro-F1), it scores 0.33 against 0.29.",
    );
    expect(accuracySummary(clf(0.424, 0.412, 0.439, 0.425), "")).toContain("it scores 0.41 against 0.43 and falls short.");
    expect(accuracySummary(clf(0.757, 0.652, 0.758, 0.658), "")).toContain("with no clear difference.");
  });

  it("regression: the mean error against always giving the training mean", () => {
    setLang("en");
    const text = accuracySummary(card([row("exfuzzy", "mae", 0.635), row("global_mean", "mae", 1.282)], false), "µg/m³")!;
    expect(text).toMatch(/^In the test period, the mean error is 0\.64.*, against 1\.28.* when always giving the training mean\.$/);
  });
});
