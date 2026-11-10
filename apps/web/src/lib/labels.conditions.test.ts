import { afterEach, describe, expect, it } from "vitest";
import { setLang } from "../i18n";
import type { LinguisticVariable } from "../api/types";
import { atLeast, atMost, earlyHours, lateNight, rules, variables } from "../test/fixturesConditions";
import { condText, fullCondition, labelerFor, namesFor, ruleSentence, sentenceText } from "./labels";

const label = labelerFor(variables);
const names = () => namesFor(variables, null, null, rules);
const FORBIDDEN_ES = /probabilidad|riesgo|contribuci|causa|certeza|confianza|no es una|no sustituye/i;
const FORBIDDEN_EN = /probabilit|risk|contribut|caus(e|al)|certaint|confiden|isn't|aren't|doesn't/i;

afterEach(() => setLang("es"));

describe("conditions of contract v0.8 in words", () => {
  it("an old `is` condition reads exactly as before", () => {
    const old = { feature: "temperature", term: "High" };
    expect(condText(old, label, names())).toBe("la temperatura es alta");
    expect(names().cond("temperature", "High", "Temperatura").qualifier).toBeUndefined();
    expect(names().phrase("temperature", "High")).toBe("temperatura alta");
    expect(condText({ ...old, operator: "is", terms: ["High"] }, label, names())).toBe("la temperatura es alta");
  });

  it("at least / at most keep the verb and put «al menos» / «como mucho» after it", () => {
    expect(condText(atLeast, label, names())).toBe("la temperatura es al menos media");
    expect(condText(atMost, label, names())).toBe("la temperatura es como mucho media");
    expect(names().phrase("temperature", "Medium", atLeast)).toBe("≥ temperatura media");
    expect(names().phrase("temperature", "Medium", atMost)).toBe("≤ temperatura media");
    expect(names().label("temperature", atLeast)).toBe("al menos media");
    expect(names().label("temperature", atMost)).toBe("como mucho media");
  });

  it("keeps the verb «está» of a term that uses it", () => {
    const water: LinguisticVariable[] = [{ feature: "ammoniacal_nitrogen", terms: [{ name: "<=L", membership_type: "trapezoidal", params: [0, 0, 1, 2] }] }];
    const n = namesFor(water, null);
    const a = { feature: "ammoniacal_nitrogen", term: "<=L", operator: "at_most", terms: ["<=L"] } as const;
    expect(condText(a, () => "Nitrógeno amoniacal", n)).toBe("el nitrógeno amoniacal está como mucho en el límite de detección o por debajo");
  });

  it("a level above the detection limit reads with its adjective, as an `is` condition would", () => {
    const water: LinguisticVariable[] = [{ feature: "ammoniacal_nitrogen", unit: "mg/l", terms: [{ name: "Medio>L", label: "media (sobre el límite)", label_en: "medium (above the limit)", membership_type: "trapezoidal", params: [1, 2, 3, 4] }] }];
    const n = namesFor(water, null);
    const a = { feature: "ammoniacal_nitrogen", term: "Medio>L", operator: "at_most", terms: ["Bajo>L", "Medio>L"] } as const;
    const lbl = () => "Nitrógeno amoniacal de la muestra (mg/l)";
    expect(condText(a, lbl, n)).toBe("el nitrógeno amoniacal de la muestra es como mucho medio, sobre el límite de detección");
    expect(n.label("ammoniacal_nitrogen", a)).toBe("como mucho media (sobre el límite)");
    setLang("en");
    expect(condText(a, () => "Ammoniacal nitrogen in the sample (mg/l)", namesFor(water, null))).toBe("ammoniacal nitrogen in the sample is at most medium, above the detection limit");
  });

  it("a compound shows its display name, never the internal one", () => {
    expect(condText(earlyHours, label, names())).toBe("la hora local es Primeras horas");
    expect(names().phrase("local_hour", earlyHours.term, earlyHours)).toBe("Primeras horas");
    expect(names().label("local_hour", earlyHours)).toBe("Primeras horas");
    expect(condText(earlyHours, label, names())).not.toContain("early_hours");
    setLang("en");
    expect(condText(earlyHours, label, namesFor(variables, null, null, rules))).toBe("local hour is Early hours");
  });

  it("a compound without a display name falls back to its internal name", () => {
    expect(condText(lateNight, label, names())).toBe("la hora local es late_night");
    setLang("en");
    expect(condText({ ...lateNight, label: "Noche larga" }, label, names())).toBe("local hour is Noche larga"); // no English name: the Spanish one
  });

  it("a trace names a compound by its internal name: the display name comes from the rules", () => {
    const traced = { feature: "local_hour", term: "early_hours", operator: "any_of", terms: ["Madrugada", "Mañana"] } as const;
    expect(condText(traced, label, names())).toBe("la hora local es Primeras horas");
    expect(condText(traced, label, namesFor(variables, null))).toBe("la hora local es early_hours");
  });

  it("says what a compound covers, with the hour range for an hour of the day", () => {
    expect(names().detail("local_hour", earlyHours)).toBe("Madrugada o Mañana, 0–10 h");
    expect(names().detail("local_hour", lateNight)).toBe("Madrugada o Tarde-noche, 15–6 h");
    expect(names().detail("local_hour", atLeast)).toBeNull();
    expect(names().detail("local_hour", { term: "x", operator: "any_of" })).toBeNull();
    expect(fullCondition(earlyHours, label, names())).toBe("La hora local es Primeras horas (Madrugada o Mañana, 0–10 h)");
    setLang("en");
    expect(names().detail("local_hour", earlyHours)).toBe("Madrugada or Mañana, 0–10 h");
  });

  it("a compound on an input that is not an hour lists its terms only", () => {
    const week: LinguisticVariable[] = [{ feature: "local_dow", unit: "weekday_index", domain: [0, 6], terms: [{ name: "Sábado", membership_type: "trapezoidal", params: [4, 5, 5, 6] }, { name: "Domingo", membership_type: "trapezoidal", params: [5, 6, 6, 6] }] }];
    const weekend = { feature: "local_dow", term: "weekend", operator: "any_of", terms: ["Sábado", "Domingo"], label: "Fin de semana", label_en: "Weekend" } as const;
    expect(namesFor(week, null).detail("local_dow", weekend)).toBe("Sábado o Domingo");
  });

  it("builds the whole sentence of a rule, and its text in both languages", () => {
    const sentence = ruleSentence(rules[0]!, label, null, names());
    expect(sentence.parts[1]!.detail).toBe("Madrugada o Mañana, 0–10 h");
    expect(sentence.parts[0]!.detail).toBeNull();
    expect(sentenceText(sentence)).toBe("Si la temperatura es al menos media y la hora local es Primeras horas → 1 u");
    setLang("en");
    expect(sentenceText(ruleSentence(rules[0]!, label, null, namesFor(variables, null, null, rules)))).toBe("If temperature is at least medium and local hour is Early hours → 1 u");
  });

  it("the new wording has no probability, risk, contribution or causal word, and no defensive disclaimer", () => {
    const all = (n: ReturnType<typeof names>) => [atLeast, atMost, earlyHours, lateNight].flatMap((c) => [condText(c, label, n), n.label(c.feature, c), n.phrase(c.feature, c.term, c), n.detail(c.feature, c) ?? ""]).join(" | ");
    expect(all(names())).not.toMatch(FORBIDDEN_ES);
    setLang("en");
    expect(all(namesFor(variables, null, null, rules))).not.toMatch(FORBIDDEN_EN);
  });
});
