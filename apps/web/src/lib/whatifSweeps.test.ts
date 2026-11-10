import { describe, expect, it } from "vitest";
import { gridIndex, nearestInstant } from "./whatifSweeps";

const weeks = ["2025-01-01T12:00:00Z", "2025-01-08T12:00:00Z", "2025-01-15T12:00:00Z"];

describe("nearestInstant", () => {
  it("picks the closest featured instant, the earlier on a tie", () => {
    expect(nearestInstant(weeks, "2025-01-09T00:00:00Z")).toBe("2025-01-08T12:00:00Z");
    expect(nearestInstant(weeks, "2025-01-12T00:00:00Z")).toBe("2025-01-08T12:00:00Z");
    expect(nearestInstant(weeks, "2030-01-01T00:00:00Z")).toBe("2025-01-15T12:00:00Z");
    expect(nearestInstant([], "2025-01-01T00:00:00Z")).toBeNull();
  });
  it("can be limited to a window (the samples of an irregular task are picked inside it)", () => {
    const w = { from: "2025-01-10T00:00:00Z", to: "2025-02-01T00:00:00Z" };
    expect(nearestInstant(weeks, "2025-01-01T00:00:00Z", w)).toBe("2025-01-15T12:00:00Z");
    expect(nearestInstant(weeks, "2025-01-01T00:00:00Z", { from: "2025-03-01T00:00:00Z", to: "2025-04-01T00:00:00Z" })).toBeNull();
  });
});

describe("gridIndex", () => {
  it("is the nearest grid step", () => {
    expect(gridIndex([0, 10, 12.5, 40], 11)).toBe(1);
    expect(gridIndex([0, 10, 12.5, 40], 30)).toBe(3);
    expect(gridIndex([0, 10], null)).toBe(0);
  });
});
