import { describe, expect, it } from "vitest";
import { colourClasses, colourKey, colourOf, MAX_RULE_COLOURS, OTHER_RULES, OTHER_RULES_COLOUR, presentRules, ruleColours } from "./ruleColours";
import { RULE_PALETTE } from "./territories";

const ranked = Array.from({ length: 11 }, (_, i) => `R${String(i + 1).padStart(2, "0")}`);

describe("one colour per rule", () => {
  it("gives the palette colours, in ranking order, to the first 5 rules and nothing to the rest", () => {
    const c = ruleColours(ranked);
    expect(c.size).toBe(MAX_RULE_COLOURS);
    expect(colourOf(c, "R01")).toBe(RULE_PALETTE[0]);
    expect(colourOf(c, "R05")).toBe(RULE_PALETTE[4]);
    expect(colourKey(c, "R06")).toBe(OTHER_RULES);
    expect(colourOf(c, colourKey(c, "R11"))).toBe(OTHER_RULES_COLOUR);
  });

  it("depends only on the ranking, so any view that ranks the same way paints a rule the same", () => {
    expect(colourOf(ruleColours(["R04", "R02", "R01"]), "R02")).toBe(RULE_PALETTE[1]);
    expect(colourOf(ruleColours(["R02", "R04"]), "R02")).toBe(RULE_PALETTE[0]);
  });

  it("lists as map classes every coloured rule and then the grey", () => {
    expect(colourClasses(ruleColours(["R04", "R02"]))).toEqual([
      { label: "R04", color: RULE_PALETTE[0] },
      { label: "R02", color: RULE_PALETTE[1] },
      { label: OTHER_RULES, color: OTHER_RULES_COLOUR },
    ]);
  });

  it("counts, for a legend, only the rules present: coloured ones in ranking order, the rest together", () => {
    const c = ruleColours(ranked);
    const p = presentRules(c, ["R03", "R01", "R03", null, undefined, "R10", "R11", "R10"]);
    expect(p.coloured).toEqual([{ id: "R01", n: 1 }, { id: "R03", n: 2 }]);
    expect(p.others).toEqual({ ids: ["R10", "R11"], n: 3 });
  });
});
