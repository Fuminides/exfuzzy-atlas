import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { RuleDefinition, TargetClass } from "../api/types";
import { setLang } from "../i18n";
import { articles, domainUi } from "./domainUi";
import { displayName } from "./entityRows";
import { horizonText, missingText, neverPredictedText, SAME_SAMPLE, sameSampleText, THIN, unitLabel, windowDaysText, zoneName } from "./format";
import { decideText, importancePeriod } from "./importance";
import { condText, displayUnit, officialNames, ruleSentence, sentenceText } from "./labels";
import { groupTitle, keyLabel, orMore, quantileText, thresholdLabel } from "./summary";
import { horizonButton, territoryTitle } from "./tasks";
import { horizonClause, horizonShort } from "./taskText";
import { barLabel } from "./performance";
import type { TaskInfo } from "../api/types";

beforeEach(() => setLang("en"));
afterEach(() => setLang("es"));

const label = (f: string) => ({ x: "Nivel hace 3 h", y: "Hora" })[f] ?? f;
const rule = (consequent: RuleDefinition["consequent"]): RuleDefinition =>
  ({ rule_id: "R01", antecedents: [{ feature: "x", term: "low" }, { feature: "y", term: "Noche" }], consequent }) as unknown as RuleDefinition;
const classes = [{ label: "Good" }, { label: "Fair" }, { label: "Poor" }] as TargetClass[];

describe("lib text in English", () => {
  it("format: missing reasons, zone names, windows, units and horizons", () => {
    expect(missingText("no_observation")).toBe("no observation");
    expect(missingText("not_modelled")).toBe("not modelled");
    expect(missingText("whatever")).toBe("undocumented reason");
    expect(zoneName("Europe/Madrid")).toBe("Madrid time");
    expect(zoneName("America/New_York")).toBe("New York time");
    expect(zoneName("UTC")).toBe("UTC");
    expect(windowDaysText("2025-12-01T00:00:00Z", "2026-01-01T00:00:00Z")).toBe("1–31 Dec 2025");
    expect(windowDaysText("2025-11-30T00:00:00Z", "2025-12-02T00:00:00Z")).toBe("30 Nov 2025 – 1 Dec 2025");
    expect([unitLabel("trips"), unitLabel("days"), unitLabel("ratio"), unitLabel("ug/m3")]).toEqual(["trips", "days", "ratio", "µg/m³"]);
    expect(horizonText(6)).toBe("at +6 h");
    expect(horizonText(0)).toBe("inference on the same sample");
    expect(sameSampleText()).toBe("inference on the same sample");
    expect(neverPredictedText()).toBe("no predictions in the published period");
    // the deprecated constant was fixed at import, in Spanish: callers should move to sameSampleText()
    expect(SAME_SAMPLE).toBe("inferencia sobre la misma muestra");
  });

  it("labels: the scaffolding and the generic terms are English, the model's own labels and terms stay as it names them", () => {
    expect(condText({ feature: "x", term: "low" }, label)).toBe("Nivel hace 3 h is low");
    const s = ruleSentence(rule({ type: "class", term: "Good" }), label, null);
    expect(sentenceText(s)).toBe("If Nivel hace 3 h is low and Hora is Noche → Good");
    expect(ruleSentence(rule({ type: "class", term: null }), label, null).outcome).toMatchObject({ label: "no class" });
    expect(ruleSentence(rule({ type: "fuzzy", term: null }), label, null).outcome).toMatchObject({ label: "no outcome" });
    expect(displayUnit("percentile")).toBe("percentile");
    expect(officialNames({ short_name: "EAQI", classes: [{ label: "Good", display_label: "Buena" }, { label: "Fair", display_label: "Razonable" }] })).toBe("official EAQI names: Good, Fair");
  });

  it("summary: group titles, months, weekdays, thresholds and quantiles", () => {
    expect(["year", "month", "hour", "weekday"].map((g) => groupTitle(g as "year"))).toEqual(["By year", "By month", "By hour of the day", "By day of the week"]);
    expect([keyLabel("month", "02"), keyLabel("weekday", "6"), keyLabel("hour", "07")]).toEqual(["Feb", "Sun", "07"]);
    expect([orMore("air"), orMore("mobility")]).toEqual(["or worse", "or more"]);
    expect(thresholdLabel(classes, 1, "air")).toBe("Fair or worse");
    expect(thresholdLabel(classes, 2, "air")).toBe("Poor");
    expect(quantileText({ p25: 14, p50: 23, p75: 37 }, "ug/m3", 0)).toBe(`median 23${THIN}µg/m³ (half of the values between 14 and 37${THIN}µg/m³)`);
    expect(quantileText({ p50: 23 }, "ug/m3", 0)).toBe(`median 23${THIN}µg/m³`);
    expect(quantileText(null, "ug/m3")).toBe("no data");
  });

  it("importance: decide-and-hit sentences and periods", () => {
    const r = { decided_share: 0.4, accuracy: 0.92, mae: null, mean_weight_share: null };
    expect(decideText(r, false, "")).toEqual({ decides: "decides 40% of the predictions", outcome: "is right 92% of the time" });
    expect(decideText({ ...r, accuracy: null }, false, "").outcome).toBe("no observations to check it against");
    expect(decideText({ ...r, decided_share: 0 }, false, "")).toEqual({ decides: "decides no prediction", outcome: null });
    expect(decideText({ ...r, mae: 2.5, mean_weight_share: 0.5 }, true, "µg/m³").outcome).toBe("mean weight in the estimate: 50% · mean error 2.5 µg/m³");
    expect(importancePeriod({ period_from_utc: "2025-01-01T00:00:00Z", period_to_utc: "2026-01-01T00:00:00Z" })).toBe("2025");
    expect(importancePeriod({ period_from_utc: "2024-01-01T00:00:00Z", period_to_utc: "2026-01-01T00:00:00Z" })).toBe("between 1 January 2024 and 31 December 2025");
  });

  it("tasks, horizons, domains, names and baselines", () => {
    expect([horizonButton(0), horizonButton(6), horizonShort(0), horizonClause(6)]).toEqual(["Same sample", "+6 h", "same sample", "at +6 h"]);
    expect(horizonClause(0)).toBe("(inference on the same sample)");
    expect(territoryTitle("de", { task_id: "de_no2_h6" } as TaskInfo)).toBe("Germany");
    expect(territoryTitle("nyc", { task_id: "nyc_pickups_h1", territory_title: "Taxis NYC" } as TaskInfo)).toBe("Taxis NYC"); // the API's title is data
    expect(domainUi("air")).toMatchObject({ title: "Air quality", noun: { one: "station", many: "stations" } });
    expect(domainUi("water").noun).toEqual({ one: "sampling point", many: "sampling points" });
    expect(domainUi("mobility").predictionNote).toContain("percentile of the training period");
    expect(articles("punto de muestreo")).toEqual({ un: "a", este: "this", ese: "that", el: "the", Este: "This" });
    expect(displayName("Elsterwerda, 1992-2020")).toBe("Elsterwerda (station from 1992 to 2020)");
    expect(barLabel("forest", true)).toBe("Random forest");
  });

  it("switching back to Spanish gives the Spanish text again (nothing is fixed at import)", () => {
    setLang("es");
    expect([missingText("no_observation"), zoneName("Europe/London"), groupTitle("month"), keyLabel("month", "01"), horizonButton(0)]).toEqual([
      "sin observación",
      "hora de Londres",
      "Por mes",
      "ene",
      "Misma muestra",
    ]);
    expect(domainUi("air").noun.one).toBe("estación");
  });
});
