import { describe, expect, it } from "vitest";
import type { RuleDefinition, TargetScheme } from "../api/types";
import { icaScheme } from "../test/fixturesClass";
import { condText, displayUnit, humanizeFeature, labelerFor, labelWithUnit, lagText, ruleSentence, sentenceText, termLabel } from "./labels";

describe("humanizeFeature (fallback of variables[].label)", () => {
  it("never leaves an identifier: lags, last hour, calendar, weather and water names read as words", () => {
    // exact timing, like the labels the backend publishes: x_lagNh is N h behind the last datum, which is 1 h old at the issue time
    expect(humanizeFeature("no2_lag3h")).toBe("NO₂ hace 4 h");
    expect(humanizeFeature("no2_lag24h")).toBe("NO₂ hace 25 h");
    expect(humanizeFeature("no2_last")).toBe("NO₂ hace 1 h (último dato)");
    expect(humanizeFeature("valid_hour_local")).toBe("Hora de validez (local)");
    expect(humanizeFeature("wind_speed")).toBe("Velocidad del viento");
    expect(humanizeFeature("rel_lag168")).toBe("Demanda relativa hace 1 semana");
    expect(humanizeFeature("rel_lag24")).toBe("Demanda relativa hace 24 h");
    expect(humanizeFeature("water_temperature")).toBe("Temperatura del agua");
    expect(humanizeFeature("ph")).toBe("pH");
  });

  it("falls back to capitalised words for an unknown name, without underscores", () => {
    expect(humanizeFeature("turbidity_index")).toBe("Turbidity index");
    expect(humanizeFeature("pm10_lag2h")).toBe("PM10 hace 3 h");
    for (const f of ["no2_lag3h", "some_new_feature", "rel_mean24h"]) expect(humanizeFeature(f)).not.toMatch(/_/);
  });

  it("writes a lag in weeks only for whole weeks", () => {
    expect([lagText(3), lagText(24), lagText(168), lagText(336), lagText(170)]).toEqual(["3 h", "24 h", "1 semana", "2 semanas", "170 h"]);
  });
});

describe("labelerFor", () => {
  it("prefers the published label and falls back to the humanised name", () => {
    const label = labelerFor([
      { feature: "no2_lag3h", label: "NO₂ hace 4 h (publicado)" },
      { feature: "wind_speed", label: null },
    ]);
    expect(label("no2_lag3h")).toBe("NO₂ hace 4 h (publicado)");
    expect(label("wind_speed")).toBe("Velocidad del viento");
    expect(label("not_listed")).toBe("Not listed");
  });
});

describe("units and terms", () => {
  it("shows a unit only when it is one: hour or weekday indexes have none", () => {
    expect([displayUnit("ug/m3"), displayUnit("degC"), displayUnit("h"), displayUnit("weekday_index"), displayUnit("percentile"), displayUnit(null)]).toEqual(["µg/m³", "°C", "", "", "percentil", ""]);
    expect(labelWithUnit("Temperatura", "degC")).toBe("Temperatura (°C)");
    expect(labelWithUnit("Hora de validez (local)", "h")).toBe("Hora de validez (local)");
    expect(labelWithUnit("NO₂ hace 1 h (último dato)", "ug/m3")).toBe("NO₂ hace 1 h (último dato, µg/m³)");
    // a published label that already names its unit gets it once
    expect(labelWithUnit("Humedad relativa hace 1 h (%)", "%")).toBe("Humedad relativa hace 1 h (%)");
    expect(labelWithUnit("Viento hace 1 h (m/s)", "m/s")).toBe("Viento hace 1 h (m/s)");
  });

  it("translates only the three generic English terms", () => {
    expect([termLabel("Low"), termLabel("medium"), termLabel("HIGH"), termLabel("Buena"), termLabel("Brisa ligera")]).toEqual(["baja", "media", "alta", "Buena", "Brisa ligera"]);
  });
});

const rule = (over: Partial<RuleDefinition> = {}): RuleDefinition => ({
  rule_id: "R03",
  position: 2,
  text: "IF no2_lag3h IS Buena AND valid_hour_local IS Noche THEN ICA = Buena",
  antecedents: [
    { feature: "no2_lag3h", term: "Buena" },
    { feature: "valid_hour_local", term: "Noche" },
  ],
  consequent: { type: "class", term: "Buena" },
  ...over,
});

describe("ruleSentence", () => {
  const label = labelerFor([]);
  it("writes 'Si <variable> es <término> y ... → <resultado>' with no identifier and the official colour on class terms", () => {
    const s = ruleSentence(rule(), label, icaScheme);
    expect(sentenceText(s)).toBe("Si el NO₂ hace 4 h es Buena y la hora de validez (local) es Noche → Buena");
    expect(s.parts[0]!.color).toBe(icaScheme.classes[0]!.color);
    expect(s.parts[1]!.color).toBeNull(); // «Noche» is not a class
    expect(s.outcome).toEqual({ kind: "class", key: "Buena", label: "Buena", color: icaScheme.classes[0]!.color });
    expect(condText(rule().antecedents[0]!, label)).toBe("el NO₂ hace 4 h es Buena");
  });

  it("writes a regression consequent as a number with its unit, es-ES", () => {
    const s = ruleSentence(rule({ consequent: { type: "crisp", value: 5.9984, unit: "mg/l" }, antecedents: [{ feature: "water_temperature", term: "Low" }] }), label, null as TargetScheme | null);
    expect(sentenceText(s)).toBe("Si la temperatura del agua es baja → 6 mg/l");
  });
});
