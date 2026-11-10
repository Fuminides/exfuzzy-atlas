import { afterEach, describe, expect, it } from "vitest";
import { setLang } from "../i18n";
import { scenarioGolden } from "../test/fixturesV04";
import { changedRuleDeltas, membershipChanges, signed } from "./whatif";

describe("what-if reading of the API answer", () => {
  it("lists the memberships that differ between the two traces, largest first", () => {
    const changes = membershipChanges(scenarioGolden);
    expect(changes).toHaveLength(2);
    expect(changes[0]).toMatchObject({ ruleId: "R01", feature: "wind_speed_t", term: "Low", after: 0 });
    expect(changes[0]!.before).toBeCloseTo(0.4, 12);
    expect(changes[0]!.delta).toBeCloseTo(-0.4, 12);
    expect(changes.every((c) => Math.abs(c.delta) > 0)).toBe(true);
  });

  it("keeps only the rules whose firing changed", () => {
    expect(changedRuleDeltas(scenarioGolden).map((d) => d.rule_id)).toEqual(["R03", "R01"]); // |+0.333| before |-0.28|
  });

  it("writes signed numbers with a real minus and no '-0'", () => {
    expect(signed(0.2804)).toBe("+0,280");
    expect(signed(-0.28)).toBe("−0,280");
    expect(signed(-0.0001)).toBe("0");
  });
});

describe("what-if numbers in English", () => {
  afterEach(() => setLang("es"));

  it("signed numbers use a decimal point and still have no '-0'", () => {
    setLang("en");
    expect([signed(0.2804), signed(-0.28), signed(-0.0001)]).toEqual(["+0.280", "−0.280", "0"]);
  });
});
