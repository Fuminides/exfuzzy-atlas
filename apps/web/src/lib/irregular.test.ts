import { describe, expect, it } from "vitest";
import { nyc, water } from "../test/fixturesReal";
import { isIrregular } from "./irregular";

describe("isIrregular", () => {
  it("reads coverage.regular on the real Water card (sample times), and not on a regular task", () => {
    expect(water.card.coverage!.step_hours).toBe(1); // only the finest step the contract expresses
    expect(water.card.coverage!.regular).toBe(false);
    expect(isIrregular(water.card)).toBe(true);
    expect(isIrregular(nyc.card)).toBe(false);
  });

  it("is false while the card has not loaded, has no coverage, or predates the flag", () => {
    expect(isIrregular(null)).toBe(false);
    expect(isIrregular(undefined)).toBe(false);
    expect(isIrregular({ coverage: null })).toBe(false);
    const old = { ...water.card.coverage! } as Partial<typeof water.card.coverage> & object;
    delete (old as { regular?: boolean }).regular;
    expect(isIrregular({ coverage: old as NonNullable<typeof water.card.coverage> })).toBe(false); // no heuristic on warnings any more
  });
});
