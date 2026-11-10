import { describe, expect, it } from "vitest";
import * as fx from "../test/fixtures";
import * as cls from "../test/fixturesClass";
import { classifierImportance, regressionImportance } from "../test/fixturesV05";
import { decideText, entityRanked, importancePeriod, noRuleShare, rankedRules } from "./importance";

const imp = classifierImportance(cls.rules, cls.entities, "t");

describe("importance as 'decides and hits'", () => {
  it("orders the rules by how many predictions they decide", () => {
    const shuffled = [...imp.rules].reverse();
    expect(rankedRules(shuffled).map((r) => r.rule_id)).toEqual(["R01", "R02", "R03", "R04"]);
  });

  it("says what a classifier rule decides and how often it is right, and says so when nothing could be checked", () => {
    const first = decideText(imp.rules[0]!, false, "");
    expect(first.decides).toBe("decide el 40 % de las predicciones");
    expect(first.outcome).toBe("acierta el 92 %");
    expect(decideText(imp.rules[3]!, false, "").outcome).toBe("sin observaciones con las que comprobarlo");
    expect(decideText({ decided_share: 0, accuracy: null }, false, "").decides).toBe("no decide ninguna predicción");
  });

  it("says what a regression rule weighs and its MAE, with the unit", () => {
    const reg = regressionImportance(fx.rules, fx.entities, "t");
    const t = decideText(reg.rules[0]!, true, "µg/m³");
    expect(t.decides).toBe("decide el 50\u202f% de las predicciones");
    expect(t.outcome).toBe("peso medio en la estimación: 50\u202f% · error medio 2,5 µg/m³");
  });

  it("reads the share of hours with no rule and the period (one calendar year is just the year)", () => {
    expect(noRuleShare(imp)).toBeCloseTo(50 / 1050, 12);
    expect(noRuleShare({ n_no_rule: 0, n_predicted: 0 })).toBe(0);
    expect(importancePeriod({ period_from_utc: "2025-01-01T00:00:00Z", period_to_utc: "2026-01-01T00:00:00Z" })).toBe("2025");
    expect(importancePeriod({ period_from_utc: "2024-12-01T00:00:00Z", period_to_utc: "2025-03-01T00:00:00Z" })).toBe("entre 1 de diciembre de 2024 y 28 de febrero de 2025");
  });

  it("ranks a zone's rules by their own share", () => {
    expect(entityRanked(imp.entities[0]).map((r) => r.rule_id)).toEqual(["R01", "R02"]);
    expect(entityRanked(undefined)).toEqual([]);
  });
});
