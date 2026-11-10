import type { PredictionsResponse, RuleMapResponse } from "../api/types";

const WEEKDAYS = new Set(["Mon", "Tue", "Wed", "Thu", "Fri"]);
const DAY_MS = 86_400_000;

const formats = new Map<string, Intl.DateTimeFormat>();
function localParts(iso: string, zone: string): { day: string; weekday: string; hour: number } {
  let f = formats.get(zone);
  if (!f) {
    f = new Intl.DateTimeFormat("en-GB", { timeZone: zone, weekday: "short", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", hourCycle: "h23" });
    formats.set(zone, f);
  }
  const p = Object.fromEntries(f.formatToParts(new Date(iso)).map((x) => [x.type, x.value]));
  return { day: `${p.year}-${p.month}-${p.day}`, weekday: p.weekday!, hour: Number(p.hour) };
}

/** The issue time at or after `from` on the first weekday (Mon-Fri) of the entity's zone, as close to `hour` local as the steps allow. */
function weekdayAt(times: readonly string[], from: number, zone: string, hour: number): number | null {
  let i = from;
  while (i < times.length && !WEEKDAYS.has(localParts(times[i]!, zone).weekday)) i++;
  if (i >= times.length) return null;
  const day = localParts(times[i]!, zone).day;
  let best = i;
  for (let j = i; j < times.length; j++) {
    const p = localParts(times[j]!, zone);
    if (p.day !== day) break;
    if (Math.abs(p.hour - hour) < Math.abs(localParts(times[best]!, zone).hour - hour)) best = j;
  }
  return best;
}

/**
 * Where to look for a representative moment to open the page at: the first weekday morning (08:00 local) of the coverage,
 * then the same a week, two, four, eight and thirteen weeks later. Indexes into `times`, without repeats. `hours` adds
 * other local hours of the same days (Explorar: a rule about the night only fires at night).
 */
export function candidateIndexes(times: readonly string[], zone: string, hours: readonly number[] = [8]): number[] {
  if (times.length === 0) return [];
  const t0 = Date.parse(times[0]!);
  const out: number[] = [];
  for (const days of [0, 7, 14, 28, 56, 91]) {
    const from = times.findIndex((t) => Date.parse(t) >= t0 + days * DAY_MS);
    if (from < 0) break;
    for (const hour of hours) {
      const i = weekdayAt(times, from, zone, hour);
      if (i !== null && !out.includes(i)) out.push(i);
    }
  }
  return out;
}

/** Share of the entities the model covers that have a prediction in the answer (a missing prediction is never counted as one). */
export function predictedShare(data: PredictionsResponse): number {
  const modelled = data.features.filter((f) => f.properties.missing_reason !== "not_modelled");
  if (modelled.length === 0) return 0;
  const predicted = modelled.filter((f) => (f.properties.prediction_label ?? f.properties.prediction ?? null) !== null).length;
  return predicted / modelled.length;
}

/** Enough entities have a prediction for the map to read as a map and not as a field of hollow rings. */
export const GOOD_COVERAGE = 0.9;

/** Share of the entities on a rule map where the rule fires at least `threshold` (a missing value never counts). */
export function firingShare(data: RuleMapResponse, threshold = 0.5): number {
  const features = data.features.filter((f) => f.properties.missing_reason !== "not_modelled");
  if (features.length === 0) return 0;
  return features.filter((f) => f.properties.value !== null && f.properties.value >= threshold).length / features.length;
}

/** Explorar opens where its rule fires at ≥ 0.5 in this share of the entities: a map with something to look at. */
export const GOOD_FIRING = 0.3;
/** Local hours probed for Explorar's opening moment, in order. */
export const RULE_PROBE_HOURS: readonly number[] = [8, 14, 20, 2];
