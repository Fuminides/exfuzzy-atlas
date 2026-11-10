import { describe, expect, it } from "vitest";
import type { StationRow } from "../map/stations";
import * as fx from "../test/fixtures";
import { territoriesFor } from "../test/fakeApi";
import type { RuleTerritoriesResponse } from "../api/types";
import { dominanceCounts, RULE_PALETTE, ruleColor, ruleValue, territoryRows } from "./territories";

const SET = { entities: fx.entities, card: fx.card, rules: fx.rules, series: fx.series, traces: fx.traces, ruleMapFor: fx.ruleMapFor };
const answer = (measure: string): RuleTerritoriesResponse =>
  territoriesFor(SET, new URLSearchParams({ measure, from: "2025-01-13T00:00:00Z", to: "2025-01-20T00:00:00Z" })).body as RuleTerritoriesResponse;
const base: StationRow[] = fx.entities.features.map((f) => ({
  entityId: f.properties.entity_id,
  name: f.properties.name ?? "",
  value: null,
  missingReason: null,
  nValid: null,
  geometry: f.geometry,
}));

describe("territory rows", () => {
  it("labels each entity with the API's dominant rule and keeps n_valid; a missing dominant stays null, not a rule", () => {
    const data = answer("mean_activation");
    const rows = territoryRows(base, data, "all", null);
    for (const r of rows) {
      const p = data.features.find((f) => f.properties.entity_id === r.entityId)!.properties;
      expect(r.label).toBe(p.dominant_rule_id ?? null);
      expect(r.nValid).toBe(p.n_valid);
      expect(r.value).toBeNull();
    }
    expect(rows[0]!.label).toBeNull(); // n_valid = 0
    expect(rows[0]!.missingReason).toBe("no_observation");
  });

  it("intensity: the value is the focused rule's measure; 0 stays 0 and absent stays null", () => {
    const data = answer("activation_frequency");
    const rows = territoryRows(base, data, "intensity", "R02");
    for (const r of rows) {
      const p = data.features.find((f) => f.properties.entity_id === r.entityId)!.properties;
      expect(r.value).toBe(ruleValue(p, "R02", "activation_frequency"));
      expect(r.label).toBeNull();
    }
    expect(rows[0]!.value).toBeNull();
    expect(rows.some((r) => r.value === 0)).toBe(true);
  });

  it("'sin modelo' entities are left as they are (never given a rule or a value)", () => {
    const rows = territoryRows(
      [{ ...base[0]!, missingReason: "not_modelled" }],
      { ...answer("mean_activation"), features: [{ ...answer("mean_activation").features[0]!, properties: { ...answer("mean_activation").features[0]!.properties, missing_reason: "not_modelled", n_valid: 0, dominant_rule_id: null, rules: [] } }] },
      "intensity",
      "R01",
    );
    expect(rows[0]).toMatchObject({ value: null, label: null, missingReason: "not_modelled" });
  });

  it("winner_share is the measure of a classifier only: null in a TSK answer", () => {
    const p = answer("mean_activation").features[1]!.properties;
    expect(ruleValue(p, "R01", "winner_share")).toBeNull();
  });

  it("counts only the rules that dominate somewhere, in rule order", () => {
    const counts = dominanceCounts(answer("mean_activation"));
    expect(counts.map((c) => c.ruleId)).toEqual([...counts.map((c) => c.ruleId)].sort());
    expect(counts.reduce((n, c) => n + c.count, 0)).toBe(answer("mean_activation").features.filter((f) => f.properties.dominant_rule_id).length);
  });
});

describe("rule colours", () => {
  it("are stable per rule position and categorical (distinct for the first rules)", () => {
    expect(ruleColor(fx.rules.rules, "R02")).toBe(RULE_PALETTE[1]);
    expect(new Set(fx.rules.rules.map((r) => ruleColor(fx.rules.rules, r.rule_id))).size).toBe(fx.rules.rules.length);
    expect(new Set(RULE_PALETTE).size).toBe(RULE_PALETTE.length);
  });
});
