import { describe, expect, it } from "vitest";
import {
  coverageFits,
  MAX_WINDOW_DAYS,
  neighbourWindow,
  seriesBlock,
  splitPeriod,
  splitPeriodsIn,
  windowDays,
  windowFor,
  windowOverlapsCoverage,
} from "./windows";

// A real-scale year: 2025, hourly issue times (8,760).
const year = { issued_from_utc: "2025-01-01T00:00:00Z", issued_to_utc: "2025-12-31T23:00:00Z", step_hours: 1 };
const sel = "2025-05-14T15:00:00Z"; // a Wednesday

describe("aggregate windows", () => {
  it("are half-open [from, to) in UTC and contain the selected time", () => {
    const expected = {
      day: ["2025-05-14T00:00:00Z", "2025-05-15T00:00:00Z"],
      week: ["2025-05-12T00:00:00Z", "2025-05-19T00:00:00Z"], // Monday to Monday
      month: ["2025-05-01T00:00:00Z", "2025-06-01T00:00:00Z"],
      coverage: ["2025-01-01T00:00:00Z", "2026-01-01T00:00:00Z"], // last issue 23:00 + 1 step
    } as const;
    for (const [kind, [from, to]] of Object.entries(expected)) {
      const w = windowFor(kind as keyof typeof expected, sel, year);
      expect([w.from, w.to]).toEqual([from, to]);
      expect(windowDays(w)).toBeLessThanOrEqual(MAX_WINDOW_DAYS);
      if (kind !== "coverage") expect(Date.parse(w.from) <= Date.parse(sel) && Date.parse(sel) < Date.parse(w.to)).toBe(true);
    }
  });

  it("handles a Sunday and a December month end", () => {
    expect(windowFor("week", "2025-05-18T23:00:00Z", year)).toEqual({ from: "2025-05-12T00:00:00Z", to: "2025-05-19T00:00:00Z" });
    expect(windowFor("month", "2025-12-31T23:00:00Z", year)).toEqual({ from: "2025-12-01T00:00:00Z", to: "2026-01-01T00:00:00Z" });
  });

  it("offers the whole coverage only when the API accepts it (<= 366 days)", () => {
    expect(coverageFits(year)).toBe(true); // 365 days
    expect(coverageFits({ ...year, issued_to_utc: "2026-01-01T23:00:00Z" })).toBe(true); // exactly 366 days
    expect(coverageFits({ ...year, issued_to_utc: "2026-01-02T23:00:00Z" })).toBe(false); // 367 days
  });
});

describe("series blocks", () => {
  it("are 6 days wide and keep the selected time at least 48 h from both edges", () => {
    for (const t of ["2025-01-01T00:00:00Z", "2025-05-14T15:00:00Z", "2025-05-15T23:00:00Z", "2025-12-31T23:00:00Z"]) {
      const b = seriesBlock(t);
      expect(windowDays(b)).toBe(6);
      expect(Date.parse(t) - Date.parse(b.from)).toBeGreaterThanOrEqual(48 * 3_600_000);
      expect(Date.parse(b.to) - Date.parse(t)).toBeGreaterThan(48 * 3_600_000);
    }
  });

  it("do not change while scrubbing inside a 48 h block", () => {
    expect(seriesBlock("2025-05-14T01:00:00Z")).toEqual(seriesBlock("2025-05-14T20:00:00Z"));
  });
});

describe("splitPeriod", () => {
  const split = {
    train_from_utc: "2023-01-01T00:00:00Z",
    train_to_utc: "2024-06-01T00:00:00Z",
    validation_from_utc: "2024-06-02T00:00:00Z",
    validation_to_utc: "2024-12-31T00:00:00Z",
    test_from_utc: "2025-01-02T00:00:00Z",
    test_to_utc: "2026-01-01T00:00:00Z",
  };
  it("labels each half-open period and the embargo gap", () => {
    expect(splitPeriod("2024-01-01T00:00:00Z", split)).toBe("train");
    expect(splitPeriod("2024-06-01T00:00:00Z", split)).toBe("gap"); // train_to is exclusive
    expect(splitPeriod("2024-07-01T00:00:00Z", split)).toBe("validation");
    expect(splitPeriod("2025-01-02T00:00:00Z", split)).toBe("test");
    expect(splitPeriod("2026-01-01T00:00:00Z", split)).toBe("gap");
  });
});

describe("windows for irregular sample times", () => {
  const irregular = { issued_from_utc: "2024-01-02T07:46:00Z", issued_to_utc: "2025-12-22T10:14:00Z", step_hours: 1 };

  it("offers a calendar year (UTC) that the API accepts, leap years included", () => {
    expect(windowFor("year", "2025-12-22T10:14:00Z", irregular)).toEqual({ from: "2025-01-01T00:00:00Z", to: "2026-01-01T00:00:00Z" });
    const leap = windowFor("year", "2024-03-10T00:00:00Z", irregular);
    expect(windowDays(leap)).toBe(366);
    expect(windowDays(leap)).toBeLessThanOrEqual(MAX_WINDOW_DAYS);
  });

  it("steps to the neighbouring window of the same kind, across month and year ends", () => {
    const dec = windowFor("month", "2025-12-22T10:14:00Z", irregular);
    expect(neighbourWindow("month", dec, -1, irregular)).toEqual({ from: "2025-11-01T00:00:00Z", to: "2025-12-01T00:00:00Z" });
    expect(neighbourWindow("month", dec, 1, irregular)).toEqual({ from: "2026-01-01T00:00:00Z", to: "2026-02-01T00:00:00Z" });
    const week = windowFor("week", "2025-05-14T15:00:00Z", irregular);
    expect(neighbourWindow("week", week, -1, irregular)).toEqual({ from: "2025-05-05T00:00:00Z", to: "2025-05-12T00:00:00Z" });
  });

  it("knows which windows touch the coverage (navigation stops at its ends)", () => {
    const dec = windowFor("month", "2025-12-22T10:14:00Z", irregular);
    expect(windowOverlapsCoverage(dec, irregular)).toBe(true);
    expect(windowOverlapsCoverage(neighbourWindow("month", dec, 1, irregular), irregular)).toBe(false);
    const jan24 = windowFor("month", irregular.issued_from_utc, irregular);
    expect(windowOverlapsCoverage(neighbourWindow("month", jan24, -1, irregular), irregular)).toBe(false);
  });

  it("lists the split periods a window touches, so a mixed window is not called out of sample or test as a whole", () => {
    const split = {
      train_from_utc: "2015-01-01T00:00:00Z", train_to_utc: "2021-12-01T00:00:00Z",
      validation_from_utc: "2022-01-01T00:00:00Z", validation_to_utc: "2023-12-01T00:00:00Z",
      test_from_utc: "2024-01-01T00:00:00Z", test_to_utc: "2026-01-01T00:00:00Z",
    };
    expect(splitPeriodsIn({ from: "2025-12-01T00:00:00Z", to: "2026-01-01T00:00:00Z" }, split)).toEqual(["test"]);
    expect(splitPeriodsIn({ from: "2021-11-01T00:00:00Z", to: "2022-02-01T00:00:00Z" }, split)).toEqual(["train", "validation"]);
    expect(splitPeriodsIn({ from: "2023-12-05T00:00:00Z", to: "2023-12-20T00:00:00Z" }, split)).toEqual(["gap"]);
  });

  describe("a static export of a period", () => {
    // Germany: 1 January to 31 March 2025, inclusive of the last hour
    const period = { issued_from_utc: "2025-01-01T00:00:00Z", issued_to_utc: "2025-03-31T23:00:00Z", step_hours: 1, clip: true };

    it("clips the standard windows to the exported range", () => {
      expect(windowFor("week", "2025-01-01T10:00:00Z", period)).toEqual({ from: "2025-01-01T00:00:00Z", to: "2025-01-06T00:00:00Z" });
      expect(windowFor("month", "2025-03-15T10:00:00Z", period)).toEqual({ from: "2025-03-01T00:00:00Z", to: "2025-04-01T00:00:00Z" });
      expect(windowFor("year", "2025-02-01T00:00:00Z", period)).toEqual({ from: "2025-01-01T00:00:00Z", to: "2025-04-01T00:00:00Z" });
      expect(windowFor("week", "2025-03-31T10:00:00Z", period)).toEqual({ from: "2025-03-31T00:00:00Z", to: "2025-04-01T00:00:00Z" });
      expect(windowFor("coverage", "2025-02-01T00:00:00Z", period)).toEqual({ from: "2025-01-01T00:00:00Z", to: "2025-04-01T00:00:00Z" });
    });

    it("leaves the windows alone without a period", () => {
      expect(windowFor("week", "2025-01-01T10:00:00Z", { ...period, clip: undefined })).toEqual({ from: "2024-12-30T00:00:00Z", to: "2025-01-06T00:00:00Z" });
    });

    it("steps from a clipped window to the next and the previous one, and stops at the ends", () => {
      const first = windowFor("week", "2025-01-01T10:00:00Z", period);
      expect(neighbourWindow("week", first, 1, period)).toEqual({ from: "2025-01-06T00:00:00Z", to: "2025-01-13T00:00:00Z" });
      expect(windowOverlapsCoverage(neighbourWindow("week", first, -1, period), period)).toBe(false);
      const last = windowFor("week", "2025-03-31T10:00:00Z", period);
      expect(neighbourWindow("week", last, -1, period)).toEqual({ from: "2025-03-24T00:00:00Z", to: "2025-03-31T00:00:00Z" });
      expect(windowOverlapsCoverage(neighbourWindow("week", last, 1, period), period)).toBe(false);
    });
  });
});
