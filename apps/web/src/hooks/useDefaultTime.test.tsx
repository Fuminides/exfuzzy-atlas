import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { PredictionsResponse } from "../api/types";
import { issueTimes } from "../lib/format";
import { GOOD_COVERAGE } from "../lib/defaultTime";
import { predictionScore } from "./defaultTimeScores";
import { useDefaultTime } from "./useDefaultTime";

const times = issueTimes({ issued_from_utc: "2025-01-01T00:00:00Z", issued_to_utc: "2025-03-01T00:00:00Z", step_hours: 1 });
const answer = (time: string, share: number): PredictionsResponse =>
  ({
    issued_at_utc: time,
    features: Array.from({ length: 10 }, (_, i) => ({ properties: { prediction_label: i < share * 10 ? "low" : null } })),
  }) as unknown as PredictionsResponse;

afterEach(() => vi.restoreAllMocks());

const run = (enabled = true, moved = false) => {
  const pick = vi.fn();
  const view = renderHook(() => useDefaultTime({ enabled, taskId: "t", score: predictionScore("t"), good: GOOD_COVERAGE, times, zone: "Europe/Berlin", moved: { current: moved }, pick }));
  return { pick, view };
};

describe("useDefaultTime", () => {
  it("picks the first weekday morning whose coverage is good, and stops probing there", async () => {
    const spy = vi.spyOn(api, "predictions").mockImplementation(async (q) => answer(q.time!, q.time === "2025-01-08T07:00:00Z" ? 0.95 : 0.6));
    const { pick, view } = run();
    expect(view.result.current).toBe(true);
    await waitFor(() => expect(view.result.current).toBe(false));
    expect(pick).toHaveBeenCalledWith(times.indexOf("2025-01-08T07:00:00Z"));
    expect(spy).toHaveBeenCalledTimes(2);
  });

  it("falls back to the best covered moment, the first issue time winning a tie", async () => {
    vi.spyOn(api, "predictions").mockImplementation(async (q) => answer(q.time!, q.time === "2025-01-15T07:00:00Z" ? 0.8 : 0.5));
    const best = run();
    await waitFor(() => expect(best.view.result.current).toBe(false));
    expect(best.pick).toHaveBeenCalledWith(times.indexOf("2025-01-15T07:00:00Z"));
    vi.spyOn(api, "predictions").mockImplementation(async (q) => answer(q.time!, 0.5));
    const tie = run();
    await waitFor(() => expect(tie.view.result.current).toBe(false));
    expect(tie.pick).toHaveBeenCalledWith(0);
  });

  it("keeps the first issue time when the API fails, and never overrides a time the user picked", async () => {
    vi.spyOn(api, "predictions").mockRejectedValue(new Error("boom"));
    const failed = run();
    await waitFor(() => expect(failed.view.result.current).toBe(false));
    expect(failed.pick).not.toHaveBeenCalled();
    vi.spyOn(api, "predictions").mockImplementation(async (q) => answer(q.time!, 1));
    const moved = run(true, true);
    await waitFor(() => expect(moved.view.result.current).toBe(false));
    expect(moved.pick).not.toHaveBeenCalled();
  });

  it("does nothing outside Predicción", () => {
    const spy = vi.spyOn(api, "predictions");
    const { view } = run(false);
    expect(view.result.current).toBe(false);
    expect(spy).not.toHaveBeenCalled();
  });
});
