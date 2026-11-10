import { describe, expect, it } from "vitest";
import { placeCard, splitRuleIds } from "./ruleRefs";

const known = (ids: string[]) => (id: string) => ids.includes(id);

describe("splitRuleIds", () => {
  it("splits on the ids the model has and leaves the others in the text", () => {
    expect(splitRuleIds("Tres reglas (R05, R04, R08) predicen Moderada.", known(["R04", "R05"]))).toEqual([
      "Tres reglas (",
      { ruleId: "R05" },
      ", ",
      { ruleId: "R04" },
      ", R08) predicen Moderada.",
    ]);
  });

  it("handles ids at the start and the end, three digits, and no id at all", () => {
    expect(splitRuleIds("R10 predice lo mismo que R113", known(["R10", "R113"]))).toEqual([{ ruleId: "R10" }, " predice lo mismo que ", { ruleId: "R113" }]);
    expect(splitRuleIds("Sin reglas aquí.", known(["R01"]))).toEqual(["Sin reglas aquí."]);
    expect(splitRuleIds("", known(["R01"]))).toEqual([""]);
  });

  it("needs R and two digits as a whole word: R1, XR10 and R10b are text", () => {
    expect(splitRuleIds("R1 y XR10 y R10b", known(["R1", "R10"]))).toEqual(["R1 y XR10 y R10b"]);
  });
});

describe("placeCard", () => {
  const view = { width: 1000, height: 800 };
  const card = { width: 300, height: 200 };
  const anchor = (top: number, left: number) => ({ top, left, bottom: top + 20, right: left + 40 });

  it("goes below the trigger when it fits there", () => {
    expect(placeCard(anchor(100, 50), card, view)).toEqual({ top: 128, left: 50, side: "below" });
  });

  it("flips above when there is no room below", () => {
    expect(placeCard(anchor(700, 50), card, view)).toEqual({ top: 492, left: 50, side: "above" });
  });

  it("never leaves the viewport sideways", () => {
    expect(placeCard(anchor(100, 900), card, view).left).toBe(1000 - 8 - 300);
    expect(placeCard(anchor(100, -20), card, view).left).toBe(8);
  });

  it("a card taller than both sides takes the larger one and is clamped inside the viewport", () => {
    const tall = { width: 300, height: 700 };
    const p = placeCard(anchor(300, 50), tall, view);
    expect(p.side).toBe("below");
    expect(p.top).toBe(800 - 8 - 700);
    const q = placeCard(anchor(600, 50), tall, view);
    expect(q.side).toBe("above");
    expect(q.top).toBeGreaterThanOrEqual(8);
    expect(q.top + 700).toBeLessThanOrEqual(800 - 8);
  });
});
