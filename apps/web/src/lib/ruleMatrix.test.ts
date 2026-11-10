import { describe, expect, it } from "vitest";
import { served } from "../test/fixturesPatterns";
import { cellFor, mainCount, matrixColumns, orderedRules, ruleMatrix } from "./ruleMatrix";

const ids = (rows: readonly { rule: { rule_id: string } }[]) => rows.map((r) => r.rule.rule_id);
const features = (cols: readonly { feature: string }[]) => cols.map((c) => c.feature);

describe("rule matrix layout over the served models", () => {
  it("Madrid +6 h (7 rules of 1 condition): rows as the cards rank them, the 4 rules under 1 % fold, columns of the shown rules only", () => {
    const { rules, importance } = served("madrid_h6");
    const folded = ruleMatrix(rules, importance, false);
    expect(ids(folded.rows)).toEqual(["R02", "R03", "R01"]);
    expect([folded.nMain, folded.nHidden]).toEqual([3, 4]);
    expect(folded.mainShare).toBeCloseTo(0.807 + 0.1528 + 0.0319, 3); // the headline: 3 of 7 rules decide 99 %
    expect(features(folded.columns)).toEqual(["no2_yday_valid", "wind_speed"]);
    expect(folded.columns[0]!.share).toBeCloseTo(0.807 + 0.1528 + 0.0077, 3); // every rule on the variable, folded ones too
    expect(folded.rows[0]!.cells.map((c) => c?.term ?? null)).toEqual(["Buena", null]);
    expect(folded.rows[2]!.cells.map((c) => c?.term ?? null)).toEqual([null, "Brisa gentil-moderada"]);

    const all = ruleMatrix(rules, importance, true);
    expect(ids(all.rows)).toEqual(["R02", "R03", "R01", "R05", "R07", "R04", "R06"]); // R07 decides slightly more than R04 (both round to 0.03 %)
    // unfolding appends columns, it never reorders the ones already shown
    expect(features(all.columns)).toEqual(["no2_yday_valid", "wind_speed", "valid_hour_local", "no2_last"]);
  });

  it("Madrid +1 h (weighted, 1-2 conditions over 9 inputs): only the used inputs are columns, each cell is the term on that input", () => {
    const { rules, importance } = served("madrid_h1");
    const m = ruleMatrix(rules, importance, false);
    expect(ids(m.rows)).toEqual(["R01", "R02", "R08", "R07"]);
    expect(features(m.columns)).toEqual(["no2_last", "relative_humidity", "valid_hour_local"]);
    expect(m.rows[1]!.cells.map((c) => c?.term ?? null)).toEqual(["Razonablemente buena", "High", null]);
    expect(features(ruleMatrix(rules, importance, true).columns)).toEqual(["no2_last", "relative_humidity", "valid_hour_local", "no2_lag1h"]);
    // the 5 inputs no rule uses (temperature, wind, lags 3 h and 24 h, weekday) are never columns
    expect(features(ruleMatrix(rules, importance, true).columns)).not.toContain("temperature");
  });

  it("Germany, NYC and Water: columns from the variable whose rules decide most to the one whose rules decide fewest", () => {
    const de = served("de_h6");
    expect(features(ruleMatrix(de.rules, de.importance, false).columns)).toEqual(["no2_yday_valid", "no2_last", "wind_speed", "valid_hour_local"]);
    const nyc = served("nyc_h1");
    const n = ruleMatrix(nyc.rules, nyc.importance, false);
    expect(ids(n.rows)).toEqual(["R10", "R02", "R08", "R01", "R04", "R07", "R09"]);
    expect(features(n.columns)).toEqual(["rel_lag1", "rel_lag24", "rel_mean24h", "rel_lag168"]);
    const water = served("water");
    const w = ruleMatrix(water.rules, water.importance, false);
    expect([w.nMain, w.nHidden]).toEqual([14, 25]); // 39 rules: 14 decide at least 1 %
    expect(features(w.columns)).toEqual(["days_from_midwinter", "orthophosphate_reactive", "ph", "water_temperature", "ammoniacal_nitrogen", "local_hour"]);
    for (let i = 1; i < w.columns.length; i++) expect(w.columns[i - 1]!.share!).toBeGreaterThanOrEqual(w.columns[i]!.share!);
  });

  it("without the importance: model order, the first 8 shown, columns by how many rules use them (ties: model order)", () => {
    const { rules } = served("nyc_h1");
    const m = ruleMatrix(rules, null, false);
    expect(ids(m.rows)).toEqual(["R01", "R02", "R03", "R04", "R05", "R06", "R07", "R08"]);
    expect([m.nMain, m.nHidden]).toEqual([8, 2]);
    expect(m.columns.every((c) => c.share === null)).toBe(true);
    expect(m.mainShare).toBeNull();
    expect(features(m.columns)).toEqual(["rel_lag1", "rel_lag24", "rel_mean24h", "rel_lag2", "rel_lag168"]);
    expect(m.rows.every((r) => r.importance === null)).toBe(true);
    const small = served("madrid_h6").rules;
    expect(ruleMatrix(small, null, false)).toMatchObject({ nMain: 7, nHidden: 0 }); // fewer than 8 rules: nothing folds
  });
});

describe("rule matrix pieces", () => {
  const { rules, importance } = served("madrid_h1");
  const byId = new Map(importance.rules.map((r) => [r.rule_id, r]));

  it("cellFor: the condition on a variable, or null", () => {
    const r02 = rules.rules.find((r) => r.rule_id === "R02")!;
    expect(cellFor(r02, "relative_humidity")).toEqual(expect.objectContaining({ feature: "relative_humidity", term: "High" }));
    expect(cellFor(r02, "wind_speed")).toBeNull();
  });

  it("folding keeps at least one rule even when none reaches 1 %", () => {
    const tiny = new Map([...byId].map(([k, v]) => [k, { ...v, decided_share: 0.001 }]));
    expect(mainCount(orderedRules(rules, importance), tiny)).toBe(1);
    expect(mainCount(orderedRules(rules, importance), byId)).toBe(4);
  });

  it("orderedRules ranks by decided share and keeps the model order without the importance", () => {
    expect(orderedRules(rules, importance).map((r) => r.rule_id)).toEqual(["R01", "R02", "R08", "R07", "R04", "R05", "R03", "R06", "R09"]);
    expect(orderedRules(rules, null).map((r) => r.rule_id)).toEqual(rules.rules.map((r) => r.rule_id));
  });

  it("matrixColumns breaks share ties by the number of rules, then the variable order", () => {
    const shown = rules.rules.filter((r) => ["R03", "R05"].includes(r.rule_id)); // hour; humidity + hour
    const flat = new Map([...byId].map(([k, v]) => [k, { ...v, decided_share: 0 }]));
    expect(features(matrixColumns(shown, rules.rules, rules.variables, flat))).toEqual(["valid_hour_local", "relative_humidity"]);
  });
});
