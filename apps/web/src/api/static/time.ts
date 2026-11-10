/** Instants are `YYYY-MM-DDTHH:MM:SSZ` (UTC), exactly as the API writes them; a day key is `YYYY-MM-DD`. */

export const HOUR_MS = 3_600_000;
export const DAY_MS = 86_400_000;

export const ms = (iso: string): number => Date.parse(iso);

/** The API's spelling of an instant (no fractional seconds). */
export const iso = (t: number): string => new Date(t).toISOString().replace(/\.000Z$/, "Z");

/** The same instant in the API's spelling (`2025-01-01T00:00:00+00:00` and `…Z` both become `…Z`). */
export const normalise = (instant: string): string => iso(ms(instant));

export const dayKey = (t: number): string => new Date(t).toISOString().slice(0, 10);

export const utcHour = (t: number): number => new Date(t).getUTCHours();

/** The shard keys (UTC days) of `[lo, hi)`, ascending. */
export function dayKeys(lo: number, hi: number): string[] {
  const keys: string[] = [];
  const last = Math.floor((hi - 1) / DAY_MS);
  for (let d = Math.floor(lo / DAY_MS); d <= last; d++) keys.push(dayKey(d * DAY_MS));
  return keys;
}

/** Python's `datetime.isoformat()` of a UTC instant, as the API writes it inside error texts (`+00:00`, not `Z`). */
export const pyIso = (t: number): string => iso(t).replace("Z", "+00:00");
