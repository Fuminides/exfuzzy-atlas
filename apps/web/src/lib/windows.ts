import { tr } from "../i18n";
import { addHours } from "./format";

/** Aggregate windows offered in the UI. All are half-open [from, to) in UTC, like the API's. */
export type WindowKind = "day" | "week" | "month" | "year" | "coverage";

export interface TimeWindow {
  from: string;
  to: string;
}

export interface CoverageLike {
  issued_from_utc: string;
  issued_to_utc: string;
  step_hours: number;
  /**
   * A static export of a period (Germany: three months) holds the standard windows clipped to the exported range, so a
   * window never reaches past the first or last exported issue time. Absent: the windows are the standard ones.
   */
  clip?: boolean;
}

/** The API rejects aggregate windows longer than this (apps/api/atlas_api/main.py). */
export const MAX_WINDOW_DAYS = 366;

const DAY_MS = 86_400_000;
const iso = (ms: number): string => new Date(ms).toISOString().replace(".000Z", "Z");

export const windowDays = (w: TimeWindow): number => (Date.parse(w.to) - Date.parse(w.from)) / DAY_MS;

/** Whole coverage as a half-open window: from the first issue time to the last one plus one step. */
export const coverageWindow = (c: CoverageLike): TimeWindow => ({
  from: iso(Date.parse(c.issued_from_utc)),
  to: addHours(c.issued_to_utc, c.step_hours),
});

/** "Whole coverage" is only offered when the API would accept it. */
export const coverageFits = (c: CoverageLike): boolean => windowDays(coverageWindow(c)) <= MAX_WINDOW_DAYS;

/** The standard window cut to the exported range (`[issued_from, issued_to + step)`) when the coverage says so. */
const clipped = (w: TimeWindow, c: CoverageLike): TimeWindow => {
  if (!c.clip) return w;
  const whole = coverageWindow(c);
  return { from: iso(Math.max(Date.parse(w.from), Date.parse(whole.from))), to: iso(Math.min(Date.parse(w.to), Date.parse(whole.to))) };
};

/** The standard UTC day, ISO week (Monday start), UTC month or year that contains `selected`. */
function standardWindow(kind: Exclude<WindowKind, "coverage">, selected: string): TimeWindow {
  const t = new Date(selected);
  const dayStart = Date.UTC(t.getUTCFullYear(), t.getUTCMonth(), t.getUTCDate());
  if (kind === "day") return { from: iso(dayStart), to: iso(dayStart + DAY_MS) };
  if (kind === "week") {
    const monday = dayStart - ((t.getUTCDay() + 6) % 7) * DAY_MS;
    return { from: iso(monday), to: iso(monday + 7 * DAY_MS) };
  }
  if (kind === "year") return { from: iso(Date.UTC(t.getUTCFullYear(), 0, 1)), to: iso(Date.UTC(t.getUTCFullYear() + 1, 0, 1)) };
  return {
    from: iso(Date.UTC(t.getUTCFullYear(), t.getUTCMonth(), 1)),
    to: iso(Date.UTC(t.getUTCFullYear(), t.getUTCMonth() + 1, 1)),
  };
}

/**
 * The UTC day, ISO week (Monday start) or UTC month that contains `selected`, or the whole coverage; clipped to the
 * exported range when the coverage is one (`clip`). Boundaries are UTC because issue times, keys and the API are UTC;
 * the legend states them.
 */
export function windowFor(kind: WindowKind, selected: string, coverage: CoverageLike): TimeWindow {
  if (kind === "coverage") return coverageWindow(coverage);
  return clipped(standardWindow(kind, selected), coverage);
}

/** The standard (unclipped) window of `kind` that contains `selected`: what a static export names its files after. */
export const standardWindowFor = (kind: Exclude<WindowKind, "coverage">, selected: string): TimeWindow => standardWindow(kind, selected);

/** The window right after (`1`) or right before (`-1`) `w`, of the same kind. */
export function neighbourWindow(kind: Exclude<WindowKind, "coverage">, w: TimeWindow, direction: 1 | -1, coverage: CoverageLike): TimeWindow {
  // `w` may be clipped: step from the standard window it belongs to, so the neighbour is never `w` itself
  const std = standardWindow(kind, w.from);
  return windowFor(kind, direction === 1 ? std.to : iso(Date.parse(std.from) - 1), coverage);
}

/** Does `w` overlap the coverage at all? (Used to disable navigation past either end.) */
export const windowOverlapsCoverage = (w: TimeWindow, c: CoverageLike): boolean =>
  Date.parse(w.from) <= Date.parse(c.issued_to_utc) && Date.parse(w.to) > Date.parse(c.issued_from_utc);

/**
 * Series are fetched in blocks of 48 h of issue time and each block is requested with 48 h of margin on both sides
 * ([block - 48 h, block + 96 h): 6 days). The selected issue time is therefore always at least 48 h away from both
 * edges, and scrubbing inside a block does not trigger new requests.
 */
export function seriesBlock(selected: string): TimeWindow {
  const block = 48 * 3_600_000;
  const start = Math.floor(Date.parse(selected) / block) * block;
  return { from: iso(start - block), to: iso(start + 2 * block) };
}

export type SplitPeriod = "train" | "validation" | "test" | "gap";

interface SplitLike {
  train_from_utc: string;
  train_to_utc: string;
  validation_from_utc?: string | null;
  validation_to_utc?: string | null;
  test_from_utc: string;
  test_to_utc: string;
}

/** Which period of the run's chronological split (half-open, by issue time) contains `iso`; "gap" = embargo or outside. */
export function splitPeriod(iso: string, s: SplitLike): SplitPeriod {
  const t = Date.parse(iso);
  const inside = (a?: string | null, b?: string | null) => !!a && !!b && t >= Date.parse(a) && t < Date.parse(b);
  if (inside(s.train_from_utc, s.train_to_utc)) return "train";
  if (inside(s.validation_from_utc, s.validation_to_utc)) return "validation";
  if (inside(s.test_from_utc, s.test_to_utc)) return "test";
  return "gap";
}

/** The split periods a window [from, to) touches, in train, validation, test order; "gap" when it touches none. */
export function splitPeriodsIn(w: TimeWindow, s: SplitLike): SplitPeriod[] {
  const a = Date.parse(w.from);
  const b = Date.parse(w.to);
  const touches = (from?: string | null, to?: string | null) => !!from && !!to && a < Date.parse(to) && b > Date.parse(from);
  const out: SplitPeriod[] = [];
  if (touches(s.train_from_utc, s.train_to_utc)) out.push("train");
  if (touches(s.validation_from_utc, s.validation_to_utc)) out.push("validation");
  if (touches(s.test_from_utc, s.test_to_utc)) out.push("test");
  return out.length > 0 ? out : ["gap"];
}

/** What each split period means for the predictions shown; getters, so each read follows the current language. */
export const PERIOD_NOTE: Record<SplitPeriod, string> = {
  get train() { return tr("periodo de entrenamiento: las predicciones son dentro de muestra", "training period: the predictions are in-sample"); },
  get validation() { return tr("periodo de validación: no es el periodo de prueba", "validation period: not the test period"); },
  get test() { return tr("periodo de prueba (fuera de muestra)", "test period (out of sample)"); },
  get gap() { return tr("fuera de los periodos del modelo (margen de embargo o sin partición)", "outside the model's periods (embargo margin or no split)"); },
};
