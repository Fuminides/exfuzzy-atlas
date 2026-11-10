import { coverageWindow, standardWindowFor, windowFor, type CoverageLike } from "../../lib/windows";
import { tr } from "../../i18n";
import { notFound, unprocessable, type Data, type Model } from "./data";
import type { AggKind } from "./paths";
import { close } from "./numbers";
import { dayKey, ms } from "./time";
import type { AggFile, Meta } from "./types";

/** An aggregate window of the export: its kind and the day key its files are named with (`all` for the coverage). */
export interface WindowRef {
  kind: AggKind;
  from: string;
}

const KINDS = ["day", "week", "month", "year"] as const;

/** The exported range. With a period the standard windows are clipped to it (spec section 8); without one they are not. */
export const coverageOf = (meta: Meta): CoverageLike => ({
  issued_from_utc: meta.coverage.from, issued_to_utc: meta.coverage.to, step_hours: meta.step_hours, clip: meta.period != null,
});

/**
 * Which window of the export `[from, to)` is: the UTC day, ISO week, UTC month or UTC year containing `from` (clipped to
 * the exported range when the export has a period), or the whole exported range (the same rules as the web's
 * `lib/windows.ts`). The files are named after the standard window's first day. `null` when it is none of them: a
 * standard window that crosses the edge of the period is not one.
 */
export function windowRef(meta: Meta, from: string, to: string): WindowRef | null {
  const a = ms(from);
  const b = ms(to);
  const coverage = coverageOf(meta);
  for (const kind of KINDS) {
    const w = windowFor(kind, from, coverage);
    if (ms(w.from) === a && ms(w.to) === b) return { kind, from: dayKey(ms(standardWindowFor(kind, from).from)) };
  }
  const whole = coverageWindow(coverage);
  return ms(whole.from) === a && ms(whole.to) === b ? { kind: "coverage", from: "all" } : null;
}

/** Does the export hold windows of this kind at all? (A cut removes a whole kind, spec section 12.) */
export function offers(meta: Meta, kind: AggKind): boolean {
  return kind === "coverage" ? meta.windows.coverage === true : (meta.windows[kind]?.length ?? 0) > 0;
}

/** The kinds of window the export holds for this model. */
export const windowKinds = (meta: Meta): AggKind[] => [...KINDS, "coverage" as const].filter((k) => offers(meta, k));

export const notPrecomputed = () =>
  unprocessable("window not precomputed", () => tr("ventana no precalculada", "window not precomputed"));

/** The reference of `[from, to)`, or a 422 when the export holds no such window. */
export function requireWindow(meta: Meta, from: string, to: string): WindowRef {
  const ref = windowRef(meta, from, to);
  if (!ref || !offers(meta, ref.kind)) throw notPrecomputed();
  return ref;
}

/**
 * The statistics of a window. Every window of the exported range has its file (zeros when it has no rows), so a listed
 * window whose file is missing is an incomplete export (404); a window outside the range is not exported: null, and the
 * builders answer "no observation" as the API does.
 */
export async function aggOf(d: Data, h: Model, ref: WindowRef, signal?: AbortSignal): Promise<AggFile | null> {
  const listed = ref.kind === "coverage" || (h.meta.windows[ref.kind] ?? []).includes(ref.from);
  if (!listed) return null;
  const agg = await d.agg(h, ref.kind, ref.from, signal);
  if (agg === null) throw notFound(`no statistics for the ${ref.kind} window ${ref.from} of ${h.meta.model_id}`);
  return agg;
}

/** The index of `tau` in the export's grid (relative 1e-9), or a 422 naming the grid. */
export function tauIndex(meta: Meta, tau: number): number {
  const k = meta.taus.findIndex((g) => close(g, tau));
  if (k < 0) {
    throw unprocessable(`tau ${tau} not precomputed; the grid is ${meta.taus.join(", ")}`, () => tr(`τ = ${tau} no está precalculado`, `τ = ${tau} is not precomputed`));
  }
  return k;
}

