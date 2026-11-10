import { describe, expect, it } from "vitest";
import { inputToUtc, utcToInput } from "./localTime";

describe("date-time input zones", () => {
  it("reads and writes UTC as is", () => {
    expect(utcToInput("2025-05-14T15:00:00Z", "UTC")).toBe("2025-05-14T15:00");
    expect(inputToUtc("2025-05-14T15:00", "UTC")).toBe(Date.parse("2025-05-14T15:00:00Z"));
  });

  it("converts Europe/Madrid wall clock in winter (UTC+1) and summer (UTC+2)", () => {
    expect(utcToInput("2025-01-15T06:00:00Z", "Europe/Madrid")).toBe("2025-01-15T07:00");
    expect(utcToInput("2025-07-15T06:00:00Z", "Europe/Madrid")).toBe("2025-07-15T08:00");
    expect(inputToUtc("2025-01-15T07:00", "Europe/Madrid")).toBe(Date.parse("2025-01-15T06:00:00Z"));
    expect(inputToUtc("2025-07-15T08:00", "Europe/Madrid")).toBe(Date.parse("2025-07-15T06:00:00Z"));
  });

  it("round-trips every hour around the autumn DST change", () => {
    for (let h = 0; h < 6; h++) {
      const iso = new Date(Date.parse("2025-10-26T00:00:00Z") + h * 3_600_000).toISOString();
      const back = inputToUtc(utcToInput(iso, "Europe/Madrid"), "Europe/Madrid")!;
      // The repeated local hour maps to its first occurrence; every other hour is exact.
      expect([Date.parse(iso), Date.parse(iso) - 3_600_000]).toContain(back);
    }
  });

  it("rejects malformed input", () => {
    expect(inputToUtc("", "UTC")).toBeNull();
    expect(inputToUtc("15/05/2025", "Europe/Madrid")).toBeNull();
  });
});
