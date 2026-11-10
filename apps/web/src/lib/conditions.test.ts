import { describe, expect, it } from "vitest";
import type { LinguisticTerm } from "../api/types";
import { boundedSum, boundedSumPoints, condKey, extraConditions, hourRangeText, hourStretches, isExtra, joinOr, operatorOf, termMembership, termsOf } from "./conditions";
import { atLeast, earlyHours, hour, rules, temperature } from "../test/fixturesConditions";

const [low, medium, high] = temperature.terms;
const term = (membership_type: LinguisticTerm["membership_type"], params: number[]) => ({ membership_type, params });
const [madrugada, manana, , tardeNoche] = hour.terms;

describe("condition helpers (contract v0.8)", () => {
  it("reads an old antecedent as `is` on its one term", () => {
    const old = { feature: "temperature", term: "High" };
    expect(operatorOf(old)).toBe("is");
    expect(isExtra(old)).toBe(false);
    expect(termsOf(old)).toEqual(["High"]);
    expect(condKey(old)).toBe("High");
    expect(termsOf({ term: "High", terms: [] })).toEqual(["High"]);
  });

  it("keys an ordinal or compound condition by operator and covered terms", () => {
    expect(condKey(atLeast)).toBe("at_least|Medium,High");
    expect(condKey(earlyHours)).toBe("any_of|Madrugada,Mañana");
  });

  it("lists the extra conditions some rule uses on a variable, once each", () => {
    expect(extraConditions(rules, "temperature").map(condKey)).toEqual(["at_least|Medium,High", "at_most|Low,Medium"]);
    expect(extraConditions(rules, "local_hour").map(condKey)).toEqual(["any_of|Madrugada,Mañana", "any_of|Madrugada,Tarde-noche"]);
    expect(extraConditions([...rules, ...rules], "temperature")).toHaveLength(2);
    expect(extraConditions(rules, "ph")).toEqual([]);
  });
});

describe("bounded sum of the memberships of a condition's terms", () => {
  it("evaluates trapezoids, shoulders and gaussians", () => {
    expect(termMembership(medium!, 8.5)).toBeCloseTo(0.5, 12); // rising edge 5..12
    expect(termMembership(medium!, 15)).toBe(1);
    expect(termMembership(low!, 0)).toBe(1); // left shoulder
    expect(termMembership(high!, 30)).toBe(1); // right shoulder
    expect(termMembership(high!, 17)).toBe(0);
    expect(termMembership(term("gaussian", [5, 2]), 5)).toBe(1);
    expect(termMembership(term("gaussian", [5, 2]), 7)).toBeCloseTo(Math.exp(-0.5), 12);
    expect(termMembership(term("triangular", [0, 2, 4]), 3)).toBeCloseTo(0.5, 12);
  });

  it("adds the memberships and caps the sum at 1", () => {
    expect(boundedSum([medium!, high!], 21.5)).toBeCloseTo(1, 12); // 0.5 + 0.5, then 1 + 0.5 capped
    expect(boundedSum([medium!, high!], 19)).toBe(1);
    expect(boundedSum([medium!, high!], 3)).toBe(0);
    expect(boundedSum([low!, medium!], 8.5)).toBeCloseTo(1, 12); // low falls as medium rises
    const a = term("trapezoidal", [0, 4, 4, 8]);
    const b = term("trapezoidal", [2, 4, 4, 6]);
    expect(boundedSum([a, b], 2)).toBeCloseTo(0.5, 12);
    expect(boundedSum([a, b], 4)).toBe(1);
  });

  it("draws the polyline through every knot and bends where the sum reaches 1", () => {
    const pts = boundedSumPoints([low!, medium!], 0, 30);
    // each point is on the bounded sum, nothing exceeds 1, and the knots of both terms are there
    for (const [x, m] of pts) {
      expect(m).toBeCloseTo(boundedSum([low!, medium!], x), 9);
      expect(m).toBeLessThanOrEqual(1);
    }
    expect(pts.map(([x]) => x)).toEqual(expect.arrayContaining([0, 5, 12, 18, 25, 30]));
    // low falls 1 -> 0 over 5..12 while medium rises 0 -> 1: their sum is 1 all along, so it is flat at 1 up to 18
    expect(pts.filter(([x]) => x >= 0 && x <= 18).every(([, m]) => Math.abs(m - 1) < 1e-9)).toBe(true);
    expect(pts[pts.length - 1]).toEqual([30, 0]);
  });

  it("adds a point where the sum of two overlapping terms reaches the cap", () => {
    const a = term("trapezoidal", [0, 4, 4, 8]);
    const b = term("trapezoidal", [2, 4, 4, 6]);
    const pts = boundedSumPoints([a, b], 0, 8);
    // the sum 0.75 x - 1 reaches 1 at x = 8/3, between the knots 2 and 4
    const bend = pts.find(([x]) => x > 2 && x < 4)!;
    expect(bend[0]).toBeCloseTo(8 / 3, 12);
    expect(bend[1]).toBe(1);
  });

  it("samples a grid when a term is gaussian", () => {
    const pts = boundedSumPoints([term("gaussian", [5, 1])], 0, 10);
    expect(pts.length).toBeGreaterThan(50);
    expect(Math.max(...pts.map(([, m]) => m))).toBeCloseTo(1, 6);
  });
});

describe("hour range of a compound", () => {
  it("reads the hours where the bounded sum is at least one half", () => {
    expect(hourStretches([madrugada!, manana!], hour.domain as [number, number])).toEqual([[0, 10]]);
    expect(hourStretches([manana!], hour.domain as [number, number])).toEqual([[7, 10]]);
  });

  it("joins both ends of a 0..23 clock into one stretch that wraps midnight", () => {
    const stretches = hourStretches([madrugada!, tardeNoche!], hour.domain as [number, number]);
    expect(stretches).toEqual([[15, 6]]);
    expect(hourRangeText(stretches)).toBe("15–6 h");
  });

  it("joins every stretch that touches both ends, and writes a single hour as one number", () => {
    const stretches = hourStretches([madrugada!, tardeNoche!, manana!], [0, 23]);
    expect(stretches).toEqual([[15, 10]]);
    expect(hourRangeText([[3, 3], [8, 10]])).toBe("3 h, 8–10 h");
    expect(hourRangeText([])).toBe("");
  });

  it("does not wrap on a domain that is not the whole clock", () => {
    const stretches = hourStretches([madrugada!, tardeNoche!], [0, 20]);
    expect(stretches).toEqual([[0, 6], [15, 20]]);
  });

  it("joins the names of the covered terms with «o» / “or”", () => {
    expect(joinOr(["Tarde-noche", "Noche"], "es")).toBe("Tarde-noche o Noche");
    expect(joinOr(["Evening", "Night"], "en")).toBe("Evening or Night");
  });
});
