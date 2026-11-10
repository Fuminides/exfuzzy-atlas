import { DAY_MS, ms } from "./time";
import { MAX_WINDOW_DAYS } from "./constants";
import { unprocessable } from "./data";

/**
 * The query-shape 422s of `apps/api/atlas_api/main.py`, kept in the static layer (the builders assume a valid query).
 * `detail` is the API's own text.
 */

const instant = (value: string): number => {
  const t = ms(value);
  if (Number.isNaN(t)) throw unprocessable(`invalid datetime ${value}`);
  return t;
};

export function checkWindow(from: string, to: string): void {
  const a = instant(from);
  const b = instant(to);
  if (b <= a) throw unprocessable("`to` must be after `from`");
  if (b - a > MAX_WINDOW_DAYS * DAY_MS) throw unprocessable(`the window is limited to ${MAX_WINDOW_DAYS} days`);
}

/** A single issue time, or a half-open window [from, to) (latest sample per entity); never both nor neither. */
export function checkTimeOrWindow(time?: string, from?: string, to?: string): void {
  if (time !== undefined && (from !== undefined || to !== undefined)) {
    throw unprocessable("pass `time` (one issue time) or `from`/`to` (a window), not both");
  }
  if (time === undefined) {
    if (from === undefined || to === undefined) throw unprocessable("pass `time` (one issue time) or both `from` and `to` (a window)");
    checkWindow(from, to);
  } else {
    instant(time);
  }
}

export function checkRuleMap(q: { metric: string; time?: string; from?: string; to?: string; tau?: number }): void {
  if (q.metric === "firing_strength") {
    if (q.time === undefined || q.from !== undefined || q.to !== undefined) {
      throw unprocessable("firing_strength takes `time` (a single issue time), not from/to");
    }
    instant(q.time);
  } else {
    if (q.from === undefined || q.to === undefined || q.time !== undefined) throw unprocessable(`${q.metric} takes a window \`from\`/\`to\`, not \`time\``);
    checkWindow(q.from, q.to);
  }
  if ((q.metric === "activation_frequency") !== (q.tau !== undefined)) throw unprocessable("`tau` is required for activation_frequency and only for it");
  if (q.tau !== undefined && !(q.tau > 0 && q.tau <= 1)) throw unprocessable("`tau` must be in (0, 1]");
}

export function checkTau(tau: number): void {
  if (!(tau > 0 && tau <= 1)) throw unprocessable("`tau` must be in (0, 1]");
}

export function checkSeries(from?: string, to?: string): void {
  if (from !== undefined && to !== undefined && instant(to) <= instant(from)) throw unprocessable("`to` must be after `from`");
}
