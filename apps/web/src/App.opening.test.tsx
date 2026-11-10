import { render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { fake, installApi } from "./test/fakeApi";
import { resetMaps } from "./test/maplibreMock";
import { classifierV05 } from "./test/v05";

vi.mock("maplibre-gl", async () => (await import("./test/maplibreMock")).maplibreFactory());

// The probe scores every candidate time; only this one is a "good" moment for the opening rule.
const GOOD = vi.hoisted(() => ({ nth: -1, probed: [] as string[], rules: [] as string[] }));
vi.mock("./hooks/defaultTimeScores", async (orig) => ({
  ...(await orig<typeof import("./hooks/defaultTimeScores")>()),
  firingScore: (_model: string, ruleId: string) => async (time: string) => {
    GOOD.rules.push(ruleId);
    GOOD.probed.push(time);
    return GOOD.probed.length - 1 === GOOD.nth ? 0.8 : 0.1;
  },
}));

beforeEach(() => {
  resetMaps();
  GOOD.rules = [];
  GOOD.probed = [];
  GOOD.nth = -1;
});
afterEach(() => vi.unstubAllGlobals());

const ruleMapCalls = () => fake.calls.filter((c) => c.includes("/rule-map")).map((c) => new URL(c, "http://x").searchParams);

describe("Explorar opens on the rule that decides most, at a moment it fires", () => {
  it("selects the first rule of the Patrones ranking, not the first by number", async () => {
    const data = classifierV05();
    const imp = data.importance!;
    data.importance = { ...imp, rules: imp.rules.map((r) => (r.rule_id === "R03" ? { ...r, decided_share: 0.9 } : r)) };
    installApi({}, data);
    render(<App initialTab="explorar" />);
    await waitFor(() => expect(ruleMapCalls().some((q) => q.get("rule_id") === "R03")).toBe(true));
    expect(ruleMapCalls().every((q) => q.get("rule_id") === "R03")).toBe(true);
    expect(new Set(GOOD.rules)).toEqual(new Set(["R03"]));
  });

  it("moves to the first probed moment where that rule fires in many entities, and asks the map only there", async () => {
    GOOD.nth = 2; // the third candidate (another local hour of the first weekday) is the good one
    installApi({}, classifierV05());
    render(<App initialTab="explorar" />);
    await waitFor(() => expect(ruleMapCalls().length).toBeGreaterThan(0));
    expect(GOOD.probed).toHaveLength(3); // it stops at the first good moment
    expect(ruleMapCalls().map((q) => q.get("time"))).toEqual([GOOD.probed[2]]);
  });
});
