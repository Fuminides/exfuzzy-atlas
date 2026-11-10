import { describe, expect, it } from "vitest";
import { servedShares } from "../test/fixturesProfiles";
import { characteristicRule, classMix, distinguishing, entityLifts, MIN_COUNT, MIN_LIFT, MIN_SHARE, profilesOf, shareTable, topRules, type ShareTable } from "./stationProfiles";

/** Three rules; overall R01 60 %, R02 30 %, R03 10 %. */
const table = (entities: { id: string; n: number; shares: number[] }[]): ShareTable => ({
  ruleIds: ["R01", "R02", "R03"],
  overall: [0.6, 0.3, 0.1],
  entities: entities.map((e) => ({ entityId: e.id, n: e.n, shares: e.shares })),
});

describe("lift and support", () => {
  it("is the share here over the share overall, most over-represented first", () => {
    const t = table([{ id: "A", n: 1000, shares: [0.5, 0.3, 0.2] }]);
    const lifts = entityLifts(t, t.entities[0]!);
    expect(lifts.map((l) => l.ruleId)).toEqual(["R03", "R02", "R01"]);
    expect(lifts[0]).toMatchObject({ here: 0.2, overall: 0.1, count: 200, supported: true });
    expect(lifts[0]!.lift).toBeCloseTo(2, 12);
    expect(lifts[1]!.lift).toBeCloseTo(1, 12);
    expect(characteristicRule(lifts)?.ruleId).toBe("R03");
  });

  it("ignores a rule below the minimum share of the entity's predictions, however large its lift", () => {
    // R03 4 % here vs 1 % overall: lift 4, but below MIN_SHARE (5 %)
    const t: ShareTable = { ruleIds: ["R01", "R02", "R03"], overall: [0.6, 0.39, 0.01], entities: [{ entityId: "A", n: 10_000, shares: [0.46, 0.5, 0.04] }] };
    const lifts = entityLifts(t, t.entities[0]!);
    expect(lifts[0]).toMatchObject({ ruleId: "R03", supported: false });
    expect(characteristicRule(lifts)?.ruleId).toBe("R02"); // 50 % vs 39 %: lift 1.28
    expect(MIN_SHARE).toBe(0.05);
  });

  it("ignores a rule that decides fewer than MIN_COUNT of the entity's predictions (Water: few samples per point)", () => {
    const t = table([{ id: "A", n: 18, shares: [10 / 18, 4 / 18, 4 / 18] }]); // R03: 4 predictions, 22 %, lift 2.2
    const lifts = entityLifts(t, t.entities[0]!);
    expect(lifts[0]).toMatchObject({ ruleId: "R03", count: 4, supported: false });
    expect(characteristicRule(lifts)).toBeNull(); // R02 is under-represented, R01 too: «sin regla característica»
    const t5 = table([{ id: "A", n: 18, shares: [9 / 18, 4 / 18, 5 / 18] }]);
    expect(characteristicRule(entityLifts(t5, t5.entities[0]!))?.ruleId).toBe("R03");
    expect(MIN_COUNT).toBe(5);
  });

  it("needs a lift of at least MIN_LIFT: a zone like the whole has no characteristic rule", () => {
    const t = table([{ id: "A", n: 1000, shares: [0.55, 0.36, 0.09] }]); // R02: 1.2
    expect(characteristicRule(entityLifts(t, t.entities[0]!))).toBeNull();
    const t2 = table([{ id: "A", n: 1000, shares: [0.525, 0.375, 0.1] }]); // R02: exactly 1.25
    expect(characteristicRule(entityLifts(t2, t2.entities[0]!))?.ruleId).toBe("R02");
    expect(MIN_LIFT).toBe(1.25);
  });

  it("lists at most three distinguishing rules, and falls back to the rules that account for most", () => {
    const t = table([{ id: "A", n: 1000, shares: [0.6, 0.3, 0.1] }]);
    expect(distinguishing(entityLifts(t, t.entities[0]!))).toEqual([]);
    expect(topRules(t, t.entities[0]!, 2).map((l) => l.ruleId)).toEqual(["R01", "R02"]);
  });

  it("reads the per-entity shares of the API in the model's rule order, absent rules as 0", () => {
    const t = shareTable({
      rules: [
        { rule_id: "R01", decided_share: 0.7, n_decided: 7, n_checked: 7 },
        { rule_id: "R02", decided_share: 0.3, n_decided: 3, n_checked: 3 },
      ],
      entities: [{ entity_id: "E1", n_predicted: 10, rules: [{ rule_id: "R02", decided_share: 0.3 }] }],
    });
    expect(t).toEqual({ ruleIds: ["R01", "R02"], overall: [0.7, 0.3], entities: [{ entityId: "E1", n: 10, shares: [0, 0.3] }] });
  });
});

describe("the predicted category mix", () => {
  const t = { ruleIds: ["R01", "R02", "R03"] };
  const classOf = (id: string) => ({ R01: "low", R02: "high", R03: "low" })[id] ?? null;
  it("adds each rule's share to the class it predicts (winning-rule classifiers only)", () => {
    expect(classMix(t, [0.5, 0.3, 0.2], classOf, ["low", "mid", "high"], "winning_rule")).toEqual([0.7, 0, 0.3]);
    expect(classMix(t, [0.5, 0.3, 0.2], classOf, ["low", "high"], "weighted_average")).toBeNull();
  });
});

describe("profiles (k-means on the rule shares)", () => {
  const two = table([
    ...Array.from({ length: 6 }, (_, i) => ({ id: `a${i}`, n: 500, shares: [0.8 - i * 0.01, 0.15 + i * 0.01, 0.05] })),
    ...Array.from({ length: 4 }, (_, i) => ({ id: `b${i}`, n: 500, shares: [0.3, 0.3 - i * 0.01, 0.4 + i * 0.01] })),
    { id: "few", n: 3, shares: [1, 0, 0] },
  ]);

  it("finds two clear groups, the larger first, named by their over-represented rules", () => {
    const p = profilesOf(two)!;
    expect(p.k).toBe(2);
    expect(p.profiles.map((x) => [x.letter, x.entityIds.length])).toEqual([["A", 6], ["B", 4]]);
    expect(p.profiles[0]!.naming.map((l) => l.ruleId)).toEqual(["R01"]);
    expect(p.profiles[1]!.naming.map((l) => l.ruleId)).toEqual(["R03"]);
    expect(p.of.get("few")).toBeUndefined(); // fewer than MIN_COUNT predictions: no profile
    expect(p.silhouette).toBeGreaterThan(0.7);
  });

  it("is deterministic: the same input gives the same profiles every time", () => {
    const a = profilesOf(two)!;
    const b = profilesOf(two)!;
    expect([...b.of]).toEqual([...a.of]);
    expect(b.tried).toEqual(a.tried);
  });

  it("has no profiles with fewer than three entities", () => {
    expect(profilesOf(table([{ id: "x", n: 100, shares: [1, 0, 0] }, { id: "y", n: 100, shares: [0, 1, 0] }]))).toBeNull();
  });
});

/** Golden values on the served models (2026-11-09): any change to the method or its thresholds shows here. */
describe("on the served models", () => {
  const characteristicCounts = (name: "de_h6" | "nyc_h1" | "water") => {
    const t = shareTable(servedShares(name));
    const c: Record<string, number> = {};
    for (const e of t.entities) if (e.n > 0) {
      const id = characteristicRule(entityLifts(t, e))?.ruleId ?? "none";
      c[id] = (c[id] ?? 0) + 1;
    }
    return c;
  };

  it("Germany +6 h: the characteristic rule spreads over seven rules where the rule that decides most is R01 or R03", () => {
    expect(characteristicCounts("de_h6")).toEqual({ R01: 112, R02: 97, R08: 55, R05: 43, R07: 32, R03: 25, R09: 2, none: 5 });
    const t = shareTable(servedShares("de_h6"));
    const top: Record<string, number> = {};
    for (const e of t.entities) if (e.n > 0) top[topRules(t, e, 1)[0]!.ruleId] = (top[topRules(t, e, 1)[0]!.ruleId] ?? 0) + 1;
    expect(top).toEqual({ R01: 235, R03: 132, R05: 3, R08: 1 });
    const p = profilesOf(t)!;
    expect(p.k).toBe(2);
    expect(p.silhouette).toBeCloseTo(0.479, 3);
    expect(p.profiles.map((x) => [x.letter, x.entityIds.length, x.naming.map((l) => l.ruleId)])).toEqual([
      ["A", 187, ["R01"]],
      ["B", 184, ["R05", "R08"]],
    ]);
  });

  it("NYC +1 h: 110 modelled zones, two profiles of 55", () => {
    expect(characteristicCounts("nyc_h1")).toEqual({ R10: 47, R01: 19, R02: 15, R09: 7, R04: 6, R07: 6, R08: 4, none: 6 });
    const p = profilesOf(shareTable(servedShares("nyc_h1")))!;
    expect(p.k).toBe(2);
    expect(p.profiles.map((x) => [x.letter, x.entityIds.length, x.naming.map((l) => l.ruleId)])).toEqual([
      ["A", 55, ["R01", "R02"]],
      ["B", 55, ["R10"]],
    ]);
  });

  it("Water: few samples per point, so most points have no characteristic rule and the profiles barely separate", () => {
    const c = characteristicCounts("water");
    expect(c["none"]).toBe(73);
    expect(c["R12"]).toBe(36);
    const p = profilesOf(shareTable(servedShares("water")))!;
    expect(p.k).toBe(2);
    expect(p.silhouette).toBeLessThan(0.25);
    expect(p.of.size).toBe(180); // 12 points have fewer than 5 predictions
    expect(p.profiles.map((x) => x.naming.map((l) => l.ruleId))).toEqual([["R18", "R09"], ["R10", "R12"]]);
  });
});
