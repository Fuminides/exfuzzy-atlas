import { afterEach, describe, expect, it } from "vitest";
import { setLang } from "../i18n";
import type { RuleMapResponse } from "../api/types";
import type { StationRow } from "../map/stations";
import { defaultRuleB, diffRows, DIVERGING, DIFF_DOMAIN, duelEntries, fmtDiff, ruleMapQuery, withRuleMap } from "./duel";

const base = (id: string): StationRow => ({ entityId: id, name: `N${id}`, value: null, missingReason: null, nValid: null, geometry: null });
const response = (values: Record<string, [number | null, number, string?]>): RuleMapResponse =>
  ({
    features: Object.entries(values).map(([id, [value, n, reason]]) => ({
      properties: { entity_id: id, value, n_valid: n, missing_reason: reason ?? null },
    })),
  }) as unknown as RuleMapResponse;

describe("duel requests", () => {
  it("the two queries differ only in the rule", () => {
    const params = { modelId: "m", metric: "activation_frequency" as const, from: "2025-01-01T00:00:00Z", to: "2025-01-08T00:00:00Z", tau: 0.5 };
    const a = ruleMapQuery(params, "R01");
    const b = ruleMapQuery(params, "R07");
    expect({ ...a, ruleId: "x" }).toEqual({ ...b, ruleId: "x" });
    expect([a.ruleId, b.ruleId]).toEqual(["R01", "R07"]);
  });

  it("proposes the next rule of the same model as B, wrapping at the end, and none when there is a single rule", () => {
    const rules = [{ rule_id: "R01" }, { rule_id: "R02" }, { rule_id: "R03" }] as Parameters<typeof defaultRuleB>[0];
    expect(defaultRuleB(rules, "R01")).toBe("R02");
    expect(defaultRuleB(rules, "R03")).toBe("R01");
    expect(defaultRuleB(rules.slice(0, 1), "R01")).toBeNull();
  });
});

describe("duel values", () => {
  const rows = ["1", "2", "3", "4", "5"].map(base);
  const a = withRuleMap(rows, response({ "1": [0.8, 24], "2": [0, 24], "3": [null, 0, "no_observation"], "4": [0.5, 10] }));
  const b = withRuleMap(rows, response({ "1": [0.3, 24], "2": [0.25, 24], "3": [0.9, 24], "4": [null, 0, "missing_input"] }));

  it("an entity absent from the answer keeps value null (never 0)", () => {
    expect(a.find((r) => r.entityId === "5")).toMatchObject({ value: null, missingReason: null, nValid: null });
  });

  it("A - B per entity; 0 is a value, and a side that is missing makes the difference missing, not 0", () => {
    const entries = duelEntries(a, b);
    const by = (id: string) => entries.find((e) => e.entityId === id)!;
    expect(by("1").diff).toBeCloseTo(0.5, 12);
    expect(by("2").diff).toBe(-0.25); // A is a real 0
    expect(by("3")).toMatchObject({ a: null, b: 0.9, diff: null, missingA: "no_observation" });
    expect(by("4")).toMatchObject({ a: 0.5, b: null, diff: null, missingB: "missing_input" });
    expect(by("5")).toMatchObject({ a: null, b: null, diff: null });
    expect(by("1")).toMatchObject({ nValidA: 24, nValidB: 24 });
  });

  it("the difference rows feed the map with null where either side is missing", () => {
    const entries = duelEntries(a, b);
    const d = diffRows(a, entries);
    expect(d.map((r) => r.value)).toEqual([entries[0]!.diff, -0.25, null, null, null]);
    expect(d[2]!.missingReason).toBe("no_observation");
    expect(d[3]!.missingReason).toBe("missing_input");
  });

  it("the diverging scale is centred at 0 over [-1, 1] and the difference text keeps its sign", () => {
    expect(DIFF_DOMAIN).toEqual([-1, 1]);
    expect(DIVERGING.find(([p]) => p === 0.5)![1]).toBe("#f1f1f1");
    expect([fmtDiff(0.25), fmtDiff(-0.1), fmtDiff(0), fmtDiff(-0.0001)]).toEqual(["+0,250", "−0,100", "0,000", "0,000"]);
  });
});

describe("duel values in English", () => {
  afterEach(() => setLang("es"));

  it("the difference text uses a decimal point and still never shows a signed zero", () => {
    setLang("en");
    expect([fmtDiff(0.25), fmtDiff(-0.1), fmtDiff(0), fmtDiff(-0.0001), fmtDiff(0.0001)]).toEqual(["+0.250", "−0.100", "0.000", "0.000", "0.000"]);
  });
});
