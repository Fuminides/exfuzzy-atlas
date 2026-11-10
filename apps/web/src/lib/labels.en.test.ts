import { afterEach, describe, expect, it } from "vitest";
import type { LinguisticVariable, RuleDefinition, TargetScheme } from "../api/types";
import { localized, setLang } from "../i18n";
import { territoryTitle } from "./tasks";
import { className, describeVariable, humanizeFeature, labelerFor, lagText, namesFor, officialNames, ruleSentence, schemeName, schemeShort, sentenceText, termLabel } from "./labels";

afterEach(() => setLang("es"));

/** Madrid as the API serves it from contract v0.6: Spanish labels with their English pair. */
const ICA: TargetScheme = {
  name: "Índice Nacional de Calidad del Aire (ICA) - NO2, concentración media horaria",
  name_en: "Spanish National Air Quality Index (ICA) - NO2, hourly mean concentration",
  short_name: "ICA",
  short_name_en: "ICA",
  kind: "official_index",
  source_url: "https://example.org/ica",
  unit: "ug/m3",
  boundary: "upper_inclusive",
  classes: [
    { label: "Buena", display_label_en: "Good", lower: null, upper: 40, color: "#00FFFF", merged_from: [] },
    { label: "Regular", display_label_en: "Moderate", lower: 40, upper: null, color: "#FFCC00", merged_from: [] },
  ],
};
const VARIABLES: LinguisticVariable[] = [
  {
    feature: "no2_yday_valid",
    unit: "ug/m3",
    label: "NO₂ ayer a la hora de validez",
    label_en: "NO₂ yesterday at the valid time",
    description: "Concentración horaria de NO₂ 24 h antes de la hora de validez.",
    description_en: "Hourly NO₂ concentration 24 h before the valid time.",
    terms: [
      { name: "Buena", membership_type: "trapezoidal", params: [0, 0, 40, 46] },
      { name: "Regular", membership_type: "trapezoidal", params: [40, 46, 1000, 1000] },
    ],
  },
  {
    feature: "valid_hour_local",
    unit: "hour",
    label: "Hora de validez (local)",
    terms: [{ name: "Noche", label_en: "Night", membership_type: "trapezoidal", params: [0, 0, 5, 6] }],
  },
];
const RULE: RuleDefinition = {
  rule_id: "R01",
  position: 0,
  antecedents: [{ feature: "no2_yday_valid", term: "Buena" }],
  consequent: { type: "class", term: "Buena" },
  text: "IF no2_yday_valid IS Buena THEN Buena",
};

describe("localized (contract v0.6 *_en fields)", () => {
  it("gives the English in English when the API sends it, and the Spanish otherwise", () => {
    expect(localized("Alemania", "Germany")).toBe("Alemania");
    setLang("en");
    expect(localized("Alemania", "Germany")).toBe("Germany");
    expect(localized("Alemania", null)).toBe("Alemania");
    expect(localized("Alemania", undefined)).toBe("Alemania");
    expect(localized("Alemania", "")).toBe("Alemania");
    expect(localized(null, "Germany")).toBe("Germany");
  });
});

describe("Madrid's rule in English", () => {
  it("reads 'If NO₂ yesterday at the valid time is Good → Good', and the same rule in Spanish keeps «Buena»", () => {
    const sentence = () => sentenceText(ruleSentence(RULE, labelerFor(VARIABLES), ICA, namesFor(VARIABLES, ICA)));
    expect(sentence()).toBe("Si el NO₂ ayer a la hora de validez es Buena → Buena");
    setLang("en");
    expect(sentence()).toBe("If NO₂ yesterday at the valid time is Good → Good");
  });

  it("memoised namers follow the language: the names are picked when they are asked for", () => {
    const label = labelerFor(VARIABLES);
    const names = namesFor(VARIABLES, ICA);
    expect([label("no2_yday_valid"), names.cls("Buena"), names.term("valid_hour_local", "Noche")]).toEqual(["NO₂ ayer a la hora de validez", "Buena", "Noche"]);
    setLang("en");
    expect([label("no2_yday_valid"), names.cls("Buena"), names.term("valid_hour_local", "Noche")]).toEqual(["NO₂ yesterday at the valid time", "Good", "Night"]);
  });

  it("class, scheme and description: English in English, and the official names are listed next to them", () => {
    setLang("en");
    expect(className(ICA.classes[0]!)).toBe("Good");
    expect(schemeName(ICA)).toBe("Spanish National Air Quality Index (ICA) - NO2, hourly mean concentration");
    expect(officialNames(ICA)).toBe("official ICA names: Buena, Regular");
    expect(describeVariable(VARIABLES[0]!)).toBe("Hourly NO₂ concentration 24 h before the valid time.");
    setLang("es");
    expect(className(ICA.classes[0]!)).toBe("Buena");
    expect(officialNames(ICA)).toBeNull();
    expect(schemeName(ICA)).toMatch(/^Índice Nacional/);
  });

  it("EAQI in English shows its own official names and needs no 'official names' line", () => {
    const eaqi = { short_name: "EAQI", short_name_en: "EAQI", classes: [{ label: "Good", display_label: "Buena", display_label_en: "Good" }, { label: "Fair", display_label: "Aceptable", display_label_en: "Fair" }] };
    expect(officialNames(eaqi)).toBe("nombres oficiales EAQI: Good, Fair");
    setLang("en");
    expect(className(eaqi.classes[0]!)).toBe("Good");
    expect(officialNames(eaqi)).toBeNull();
  });
});

describe("a missing *_en falls back to the Spanish", () => {
  it("variable, term, class, scheme, description and territory", () => {
    setLang("en");
    const label = labelerFor(VARIABLES);
    expect(label("valid_hour_local")).toBe("Hora de validez (local)"); // no label_en
    const old = { label: "Good", display_label: "Buena" }; // a v0.5.1 EAQI class
    expect(className(old)).toBe("Buena");
    expect(namesFor([], { classes: [old] }).cls("Good")).toBe("Buena");
    expect(namesFor([{ feature: "w", terms: [{ name: "<=L", label: "≤ límite de detección", membership_type: "trapezoidal", params: [0, 0, 1, 2] }] }], null).term("w", "<=L")).toBe("≤ límite de detección");
    expect(schemeName({ name: "Nivel de demanda" })).toBe("Nivel de demanda");
    expect(schemeShort({ short_name: "Nivel relativo" })).toBe("Nivel relativo");
    expect(describeVariable({ description: "Solo en castellano" })).toBe("Solo en castellano");
    const task = { task_id: "de_no2_h6", target: "no2", unit: "ug/m3", horizon_hours: 6, status: "available" as const, territory: "germany" };
    expect(territoryTitle("germany", { ...task, territory_title: "Alemania" })).toBe("Alemania");
    expect(territoryTitle("germany", { ...task, territory_title: "Alemania", territory_title_en: "Germany" })).toBe("Germany");
  });
});

describe("the web's own fallbacks in English", () => {
  it("humanised features, lags and generic terms", () => {
    setLang("en");
    expect(humanizeFeature("no2_lag3h")).toBe("NO₂ 4 h ago");
    expect(humanizeFeature("no2_last")).toBe("NO₂ 1 h ago (latest value)");
    expect(humanizeFeature("rel_lag168")).toBe("Relative demand 1 week ago");
    expect(humanizeFeature("wind_speed")).toBe("Wind speed");
    expect(humanizeFeature("pm25_lag2h")).toBe("PM2.5 3 h ago");
    expect(humanizeFeature("local_dow")).toBe("Weekday");
    expect([lagText(336), termLabel("Low"), termLabel("High")]).toEqual(["2 weeks", "low", "high"]);
  });
});
