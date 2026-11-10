import { describe, expect, it } from "vitest";
import type { StationRow } from "../map/stations";
import { neverPredictedIds } from "./importance";
import { markNeverPredicted } from "./predictions";
import { stationTip } from "./stationTip";

const ent = (id: string, n: number, decided: number) => ({ entity_id: id, n_predicted: n, rules: decided > 0 ? [{ rule_id: "R01", decided_share: decided }] : [] });
const imp = { n_predicted: 100, entities: [ent("A", 50, 1), ent("B", 0, 0), ent("C", 50, 0)] };

const row = (entityId: string, over: Partial<StationRow> = {}): StationRow => ({
  entityId, name: entityId, value: null, label: null, missingReason: "missing_input", nValid: null, geometry: null, ...over,
});

describe("entities with no prediction in the whole published period", () => {
  it("detects the absent ones and those where no rule decides anything", () => {
    expect([...neverPredictedIds(imp, ["A", "B", "C", "D"])]).toEqual(["B", "C", "D"]);
  });

  it("classifies nothing when the importance has no predictions at all", () => {
    expect(neverPredictedIds({ n_predicted: 0, entities: [] }, ["A"]).size).toBe(0);
  });

  it("flags only plain missing rows and sends them to the end", () => {
    const never = new Set(["A", "B", "N", "W", "X"]);
    const rows = [
      row("A"),
      row("N", { missingReason: "not_modelled" }),
      row("W", { noReference: true, missingReason: "prediction_unavailable" }),
      row("X", { label: "Bueno", missingReason: null }),
      row("Z"),
      row("B"),
    ];
    const out = markNeverPredicted(rows, never);
    expect(out.map((r) => r.entityId)).toEqual(["N", "W", "X", "Z", "A", "B"]);
    expect(out.filter((r) => r.noPredictions).map((r) => r.entityId)).toEqual(["A", "B"]);
  });

  it("reads differently from the per-time gap in the tooltip", () => {
    const ctx = { mode: "prediction", scheme: null, noun: "estación", unit: "", zone: "UTC", territoriesOn: false, terrMeasure: "", terrFocus: "all", ruleId: null, territoryOf: () => undefined, observationOf: () => null } as unknown as Parameters<typeof stationTip>[1];
    expect(stationTip(row("A", { noPredictions: true }), ctx)).toBe("A: sin predicciones en el periodo publicado");
    expect(stationTip(row("A"), ctx)).toContain("falta una entrada");
  });
});
