import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { setLang } from "../i18n";
import type { StationRow } from "../map/stations";
import { icaScheme, scheme } from "../test/fixturesClass";
import { nyc } from "../test/fixturesReal";
import { boundsText, classTitle, mergedNote, schemeQualifier, weightLabel, weightTitle } from "./classifier";
import { legendTitle, metricTitle, VIEW_LABEL } from "./ruleMapText";
import { stationTip } from "./stationTip";
import { MEASURE_DEFINITION, MEASURE_LABEL, measureName } from "./territories";
import { PERIOD_NOTE } from "./windows";

/** The map's text helpers in English: same facts as the Spanish, never a probability, risk, contribution or cause. */
const FORBIDDEN = /probabilit|risk|contribut|caus(e|al)|certaint|confiden/i;

beforeEach(() => setLang("en"));
afterEach(() => setLang("es"));

const row = (over: Partial<StationRow> = {}): StationRow => ({ entityId: "A", name: "A", value: null, label: null, missingReason: null, nValid: null, geometry: null, ...over });
const ctx = (over: Partial<Parameters<typeof stationTip>[1]> = {}) =>
  ({ mode: "prediction", scheme: null, noun: "station", unit: "µg/m³", zone: "UTC", territoriesOn: false, terrMeasure: "mean_activation", terrFocus: "all", ruleId: null, territoryOf: () => undefined, observationOf: () => null, ...over }) as Parameters<typeof stationTip>[1];

describe("map text in English", () => {
  it("titles schemes and bounds", () => {
    expect(`${classTitle(icaScheme, "NO₂")} (${schemeQualifier(icaScheme)})`).toBe("predicted ICA category for NO₂ (official index)");
    expect(classTitle(scheme, "y")).toBe("predicted category for y");
    expect(boundsText(icaScheme.classes[1]!, icaScheme)).toBe("> 40 and ≤ 90 µg/m³");
    const level = nyc.card.target_scheme!;
    expect(boundsText(level.classes[1]!, level)).toBe("percentile ≥ 25 and < 75");
    expect(schemeQualifier(level)).toMatch(/relative to what is usual, not an official index$/);
    expect(mergedNote(icaScheme.classes[3]!, icaScheme)).toBe(
      "“Desfavorable o peor” groups the official categories Desfavorable, Muy desfavorable and Extremadamente desfavorable (> 120 and ≤ 1000 µg/m³), which the model doesn't tell apart.",
    );
    expect([weightLabel(), weightTitle("dominance_score")]).toEqual(["weight", "Rule weight (dominance_score)"]);
  });

  it("names the rule-map metrics and the territory measures, and follows a language change", () => {
    expect(Object.values(VIEW_LABEL)).toEqual(["Issue instant", "Mean over the window", "Frequency ≥ τ over the window"]);
    expect(metricTitle("firing_strength", 0.5)).toBe("rule activation (0–1) at the issue instant");
    expect(legendTitle("activation_frequency", 0.5)).toBe("rule activation frequency ≥ τ=0.50 (fraction 0–1)");
    expect(MEASURE_LABEL.winner_share).toBe("Winning rules (classifiers only)");
    expect(measureName("activation_frequency")).toBe("activation frequency");
    expect(MEASURE_DEFINITION.activation_frequency(0.5)).toBe("fraction of the entity's valid records in which the rule's activation is ≥ τ = 0.50");
    expect(PERIOD_NOTE.test).toBe("test period (out of sample)");
    setLang("es");
    expect(VIEW_LABEL.firing_strength).toBe("Instante de emisión");
    expect(MEASURE_LABEL.mean_activation).toBe("Activación media");
  });

  it("writes the hover text of each mode", () => {
    expect(stationTip(row({ missingReason: "not_modelled" }), ctx())).toBe("A: not modelled (the model has no data for this station)");
    expect(stationTip(row({ label: "R03", nValid: 24 }), ctx({ territoriesOn: true }))).toBe("A: dominant rule R03 by mean activation (24 valid records)");
    expect(stationTip(row({ noReference: true }), ctx({ scheme: icaScheme }))).toBe("A: no reference (no reference level for that hour of the week)");
    expect(stationTip(row({ label: "Buena", decidedBy: "R06" }), ctx({ scheme: icaScheme }))).toBe("A: Buena · decided by R06");
    expect(stationTip(row({ value: 12 }), ctx({ mode: "data" }))).toBe("A: 12 µg/m³ observed");
  });

  it("never calls an activation a probability, a risk, a contribution or a cause", () => {
    const texts = [
      ...Object.values(VIEW_LABEL),
      ...Object.values(MEASURE_LABEL),
      ...(["mean_activation", "activation_frequency", "winner_share"] as const).map((m) => MEASURE_DEFINITION[m](0.5)),
      ...(["firing_strength", "mean_activation", "activation_frequency"] as const).flatMap((v) => [metricTitle(v, 0.5), legendTitle(v, 0.5)]),
      ...Object.values(PERIOD_NOTE),
    ];
    for (const t of texts) expect(t).not.toMatch(FORBIDDEN);
  });
});
