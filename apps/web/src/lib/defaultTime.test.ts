import { describe, expect, it } from "vitest";
import type { PredictionsResponse } from "../api/types";
import { candidateIndexes, predictedShare } from "./defaultTime";
import { issueTimes } from "./format";

const hourly = (from: string, to: string, step = 1) => issueTimes({ issued_from_utc: from, issued_to_utc: to, step_hours: step });

describe("candidateIndexes", () => {
  it("starts at the first weekday 08:00 local, then a week, two, four, eight and thirteen weeks later", () => {
    const times = hourly("2025-01-01T00:00:00Z", "2025-12-31T21:00:00Z"); // a Wednesday
    const idx = candidateIndexes(times, "Europe/Berlin");
    expect(idx.map((i) => times[i])).toEqual([
      "2025-01-01T07:00:00Z", // Wed 1 Jan 08:00 CET
      "2025-01-08T07:00:00Z",
      "2025-01-15T07:00:00Z",
      "2025-01-29T07:00:00Z",
      "2025-02-26T07:00:00Z",
      "2025-04-02T06:00:00Z", // 08:00 CEST: the clock moved, the local hour did not
    ]);
  });

  it("skips a weekend start (NYC coverage begins on a Saturday)", () => {
    const times = hourly("2025-02-08T05:00:00Z", "2025-04-01T03:00:00Z");
    expect(times[candidateIndexes(times, "America/New_York")[0]!]).toBe("2025-02-10T13:00:00Z"); // Monday 08:00 EST
  });

  it("takes the step closest to 08:00 when the steps skip it", () => {
    const times = hourly("2025-01-01T00:00:00Z", "2025-01-31T18:00:00Z", 6);
    expect(times[candidateIndexes(times, "Europe/Madrid")[0]!]).toBe("2025-01-01T06:00:00Z"); // 07:00 local
  });

  it("is empty without issue times and never repeats an index on a short coverage", () => {
    expect(candidateIndexes([], "Europe/Madrid")).toEqual([]);
    const idx = candidateIndexes(hourly("2025-03-03T00:00:00Z", "2025-03-04T23:00:00Z"), "Europe/Madrid");
    expect(new Set(idx).size).toBe(idx.length);
  });
});

describe("predictedShare", () => {
  const f = (properties: Record<string, unknown>) => ({ properties }) as unknown as PredictionsResponse["features"][number];
  it("counts the entities the model covers that have a prediction, never the 'sin modelo' ones", () => {
    const data = { features: [f({ prediction_label: "low" }), f({ prediction: 12 }), f({ prediction: null, prediction_label: null }), f({ missing_reason: "not_modelled" })] } as PredictionsResponse;
    expect(predictedShare(data)).toBeCloseTo(2 / 3);
  });
  it("is 0 when nothing is modelled", () => {
    expect(predictedShare({ features: [] } as unknown as PredictionsResponse)).toBe(0);
  });
});

describe("Explorar's opening moment", () => {
  it("firingShare counts the entities where the rule fires at ≥ 0.5, never a missing value, never an unmodelled one", async () => {
    const { firingShare } = await import("./defaultTime");
    const f = (value: number | null, missing_reason: string | null = null) => ({ properties: { value, missing_reason } });
    const data = { features: [f(0.9), f(0.5), f(0.2), f(null, "missing_input"), f(null, "not_modelled")] } as never;
    expect(firingShare(data)).toBe(2 / 4);
  });

  it("probes other local hours of the same days when asked (a rule about the night only fires at night)", async () => {
    const { candidateIndexes, RULE_PROBE_HOURS } = await import("./defaultTime");
    const ts = Array.from({ length: 24 * 3 }, (_, i) => new Date(Date.parse("2025-01-06T00:00:00Z") + i * 3_600_000).toISOString().replace(".000", ""));
    const hours = candidateIndexes(ts, "UTC", RULE_PROBE_HOURS).slice(0, 4).map((i) => new Date(ts[i]!).getUTCHours());
    expect(hours).toEqual([8, 14, 20, 2]);
  });
});
