import { describe, expect, it } from "vitest";
import { dec, fmt, fmtFine, fmtNum, formatDate, formatPlain, missingText, formatInstant, horizonText, numShort, pct, SAME_SAMPLE, unitLabel, windowDaysText, withUnit, zoneName } from "./format";

describe("local time follows the entities' zone", () => {
  it("shows UTC next to the zone it is given, with DST applied", () => {
    expect(formatInstant("2025-03-19T23:00:00Z", "America/New_York")).toBe("19/03/2025, 23:00 UTC · 19:00 America/New_York"); // EDT, UTC-4
    expect(formatInstant("2025-01-15T23:00:00Z", "America/New_York")).toBe("15/01/2025, 23:00 UTC · 18:00 America/New_York"); // EST, UTC-5
    expect(formatInstant("2025-12-03T08:15:00Z", "Europe/London")).toBe("03/12/2025, 08:15 UTC · 08:15 Europe/London");
  });

  it("keeps Madrid as the default only where no zone is given", () => {
    expect(formatInstant("2025-01-15T06:00:00Z")).toBe("15/01/2025, 06:00 UTC · 07:00 Europe/Madrid");
    expect(formatDate("2025-03-20T02:00:00Z", "America/New_York")).toBe("19 de marzo de 2025"); // still the 19th in New York
    expect(formatDate("2025-03-20T02:00:00Z", "Europe/Madrid")).toBe("20 de marzo de 2025");
  });
});

describe("horizon and units", () => {
  it("never writes +0 h: horizon 0 is inference on the same sample", () => {
    expect(horizonText(0)).toBe(SAME_SAMPLE);
    expect(SAME_SAMPLE).toBe("inferencia sobre la misma muestra");
    expect(horizonText(6)).toBe("a +6 h");
  });

  it("labels the task units", () => {
    expect([unitLabel("ug/m3"), unitLabel("mg/l"), unitLabel("trips")]).toEqual(["µg/m³", "mg/l", "viajes"]);
  });
});

describe("fmtFine (weights and associations)", () => {
  it("is fmt from 0.1 up and keeps two significant digits below it, so a non-zero number is never 0.000", () => {
    expect([fmtFine(1), fmtFine(0.5), fmtFine(0.1), fmtFine(0)]).toEqual([fmt(1), fmt(0.5), fmt(0.1), fmt(0)]);
    expect([fmtFine(0.0621), fmtFine(0.05551), fmtFine(0.0059), fmtFine(0.00064), fmtFine(0.00008), fmtFine(0.0000321)]).toEqual([
      "0,062",
      "0,056",
      "0,0059",
      "0,00064",
      "0,00008",
      "0,000032",
    ]);
    expect(fmtFine(0.05)).toBe("0,050");
  });
});

describe("missingText", () => {
  it("labels the documented reasons, the v0.4 'not_modelled', and never prints undefined", () => {
    expect(missingText("no_observation")).toBe("sin observación");
    expect(missingText("not_modelled")).toBe("sin modelo");
    expect(missingText("something_new")).toBe("motivo no documentado");
  });
});

describe("es-ES numbers", () => {
  it("writes comma decimals and a thin space before %", () => {
    expect([dec(2.5, 1), dec(0.123, 3)]).toEqual(["2,5", "0,123"]);
    expect([pct(0.74), pct(0.026), pct(0), pct(0.0001), pct(1)]).toEqual(["74 %", "2,6 %", "0 %", "<0,1 %", "100 %"]);
    expect(withUnit(32.7, "µg/m³")).toBe("32,7 µg/m³");
    expect(withUnit(7, "")).toBe("7,0");
    expect([fmt(0.45), fmtNum(1234.5678), numShort(5.99843)]).toEqual(["0,450", "1235", "5,998"]);
  });
});

describe("plain time line", () => {
  it("writes the wall clock of the entity's zone and names the zone in words", () => {
    expect(formatPlain("2025-01-02T07:00:00Z", "Europe/Madrid")).toBe("2 ene 2025, 08:00");
    expect(formatPlain("2025-09-02T07:00:00Z", "Europe/Madrid")).toBe("2 sept 2025, 09:00");
    expect(zoneName("Europe/Madrid")).toBe("hora de Madrid");
    expect(zoneName("America/New_York")).toBe("hora de Nueva York");
    expect(zoneName("Asia/Ho_Chi_Minh")).toBe("hora de Ho Chi Minh");
  });

  it("writes a half-open UTC window as its days", () => {
    expect(windowDaysText("2025-12-01T00:00:00Z", "2026-01-01T00:00:00Z")).toBe("1 al 31 dic 2025");
    expect(windowDaysText("2025-12-29T00:00:00Z", "2026-01-05T00:00:00Z")).toBe("29 dic 2025 al 4 ene 2026");
    expect(windowDaysText("2025-12-03T00:00:00Z", "2025-12-04T00:00:00Z")).toBe("3 dic 2025");
  });
});
