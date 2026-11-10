import { describe, expect, it } from "vitest";
import * as fx from "../test/fixtures";
import { observationsFor, predictionsFor } from "../test/fakeApi";
import type { StationRow } from "../map/stations";
import { observationRows, predictionRows } from "./predictions";

const SET = { entities: fx.entities, card: fx.card, rules: fx.rules, series: fx.series, traces: fx.traces, ruleMapFor: fx.ruleMapFor };
const base: StationRow[] = fx.entities.features.map((f) => ({
  entityId: f.properties.entity_id,
  name: "",
  value: null,
  missingReason: null,
  nValid: null,
  geometry: f.geometry,
}));
const opts = { classifier: false, relativeScheme: false, irregular: false };

describe("prediction rows (from /predictions)", () => {
  it("keeps a null prediction null with its reason; 0 is never inferred", () => {
    const rows = predictionRows(base, predictionsFor(SET, new URLSearchParams({ time: "2025-01-15T08:00:00Z" })), opts);
    const d = rows.find((r) => r.entityId === "SYN_D")!;
    expect(d.value).toBeNull();
    expect(d.missingReason).toBe("missing_input");
    expect(rows.find((r) => r.entityId === "SYN_A")!.value).toBe(72);
  });

  it("an entity the answer lacks is 'prediction_unavailable' at an instant and 'no_observation' in a window", () => {
    const empty = { ...predictionsFor(SET, new URLSearchParams({ time: "2025-01-15T08:00:00Z" })), features: [] };
    expect(predictionRows(base, empty, opts)[0]!.missingReason).toBe("prediction_unavailable");
    expect(predictionRows(base, empty, { ...opts, irregular: true })[0]!.missingReason).toBe("no_observation");
  });

  it("a window answer carries each entity's own sample date", () => {
    const w = predictionsFor(SET, new URLSearchParams({ from: "2025-01-15T06:00:00Z", to: "2025-01-15T09:00:00Z" }));
    const rows = predictionRows(base, w, { ...opts, irregular: true });
    expect(rows.find((r) => r.entityId === "SYN_A")!.sample).toEqual({ at: "2025-01-15T08:00:00Z", observed: 52 });
  });

  it("leaves 'sin modelo' rows alone", () => {
    const rows = predictionRows([{ ...base[0]!, missingReason: "not_modelled" }], predictionsFor(SET, new URLSearchParams({ time: "2025-01-15T08:00:00Z" })), opts);
    expect(rows[0]).toMatchObject({ value: null, missingReason: "not_modelled" });
  });
});

describe("observation rows (Data mode)", () => {
  it("takes the target observed at valid_at, and a gap is null with a reason (0 only if measured)", () => {
    const series = structuredClone(fx.series);
    series[0]!.points[0]!.observed = null;
    series[1]!.points[0]!.observed = 0;
    const rows = observationRows(base, observationsFor({ ...SET, series }, new URLSearchParams({ time: "2025-01-15T06:00:00Z" })));
    expect(rows[0]).toMatchObject({ value: null, missingReason: "no_observation" });
    expect(rows[1]).toMatchObject({ value: 0, missingReason: null });
    expect(rows[2]!.value).toBe(62.5);
  });
});
