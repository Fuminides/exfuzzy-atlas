import { describe, expect, it } from "vitest";
import type { TargetScheme } from "../api/types";
import { icaScheme, rules, scheme } from "../test/fixturesClass";
import { nyc } from "../test/fixturesReal";
import { boundsText, classColor, classTitle, isClassifier, isMergedClass, isNoReference, mergedNote, scaleInObservedUnits, schemeQualifier, weightLabel } from "./classifier";

describe("classifier helpers (contract fields only)", () => {
  it("detects a classifier from task_type or from the inference family", () => {
    expect(isClassifier({ task_type: "classification" }, null)).toBe(true);
    expect(isClassifier({ task_type: "regression" }, rules)).toBe(true); // family wins when the rules say so
    expect(isClassifier({ task_type: "regression" }, { inference: { ...rules.inference, family: "tsk_zero_order" } })).toBe(false);
    expect(isClassifier(undefined, null)).toBe(false);
  });

  it("titles the ICA scheme as the official category and a non-official one with its own name", () => {
    expect(`${classTitle(icaScheme, "NO₂")} a +6 h (${schemeQualifier(icaScheme)})`).toBe("categoría ICA prevista de NO₂ a +6 h (índice oficial)");
    expect(schemeQualifier(scheme)).toBe(scheme.name); // kind "analytical": its own name
    expect(classTitle(scheme, "y")).toBe("categoría prevista de y");
  });

  it("writes the class bounds in the scheme's convention with the unit", () => {
    expect(icaScheme.classes.map((c) => boundsText(c, icaScheme))).toEqual([
      "≤ 40 µg/m³",
      "> 40 y ≤ 90 µg/m³",
      "> 90 y ≤ 120 µg/m³",
      "> 120 y ≤ 1000 µg/m³",
    ]);
    const lowerInclusive: TargetScheme = { ...icaScheme, boundary: "lower_inclusive" };
    expect(boundsText(icaScheme.classes[1]!, lowerInclusive)).toBe("≥ 40 y < 90 µg/m³");
  });

  it("flags only the merged ICA class, from the contract's merged_from, and names the categories it groups", () => {
    expect(icaScheme.classes.filter(isMergedClass).map((c) => c.label)).toEqual(["Desfavorable o peor"]);
    expect(scheme.classes.filter(isMergedClass)).toEqual([]);
    const note = mergedNote(icaScheme.classes[3]!, icaScheme);
    expect(note).toBe(
      "«Desfavorable o peor» reúne las categorías oficiales Desfavorable, Muy desfavorable y Extremadamente desfavorable (> 120 y ≤ 1000 µg/m³), que el modelo no distingue.",
    );
  });

  it("uses the scheme's colours and calls the rule weight \"peso\"", () => {
    expect(icaScheme.classes.map((c) => classColor(icaScheme, c.label))).toEqual(["#00FFFF", "#00B050", "#FFCC00", "#FF3300"]);
    expect(weightLabel()).toBe("peso");
  });
});

describe("relative schemes (NYC: percentiles of the zone's own reference)", () => {
  const level = nyc.card.target_scheme!;

  it("writes the bounds as percentiles, not with the scheme's long unit sentence", () => {
    expect(level.classes.map((c) => boundsText(c, level))).toEqual(["percentil ≥ 0 y < 25", "percentil ≥ 25 y < 75", "percentil ≥ 75 y < 95", "percentil ≥ 95 y < 100"]);
  });

  it("knows that its bounds are not on the axis of the observed trips, while the ICA's are on µg/m³", () => {
    expect(scaleInObservedUnits(level, "trips")).toBe(false);
    expect(scaleInObservedUnits(icaScheme, "ug/m3")).toBe(true);
  });

  it("'sin referencia' is an observed value with no reference class, withheld as prediction_unavailable", () => {
    const base = { observed: 2, observed_label: null, predicted_label: null, missing_reason: "prediction_unavailable" } as const;
    expect(isNoReference(base)).toBe(true);
    expect(isNoReference({ ...base, observed: null })).toBe(false); // nothing observed
    expect(isNoReference({ ...base, observed_label: "alta" })).toBe(false); // the engine fired nothing: "sin predicción"
    expect(isNoReference({ ...base, predicted_label: "normal", missing_reason: null })).toBe(false);
    expect(isNoReference({ ...base, missing_reason: "missing_input" })).toBe(false);
  });
});
