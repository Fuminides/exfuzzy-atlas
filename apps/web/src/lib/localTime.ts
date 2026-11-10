/** "UTC" or an IANA zone name (the entities' timezone). */
export type InputZone = string;

const pad = (n: number) => String(n).padStart(2, "0");

const partsIn = (ms: number, zone: InputZone): Record<string, number> => {
  const out: Record<string, number> = {};
  const fmt = new Intl.DateTimeFormat("en-GB", {
    timeZone: zone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
  for (const p of fmt.formatToParts(new Date(ms))) if (p.type !== "literal") out[p.type] = Number(p.value);
  return out;
};

/** Wall clock of an instant in `zone`, as the value of an `<input type="datetime-local">`. */
export function utcToInput(iso: string, zone: InputZone): string {
  const p = partsIn(Date.parse(iso), zone);
  return `${p.year}-${pad(p.month!)}-${pad(p.day!)}T${pad(p.hour!)}:${pad(p.minute!)}`;
}

/**
 * The UTC instant (epoch ms) whose wall clock in `zone` is the `datetime-local` value, or null if it is malformed.
 * In the DST overlap the first of the two instants is used; a skipped local hour lands on a nearby real one. The
 * caller snaps the result to an issue time anyway.
 */
export function inputToUtc(value: string, zone: InputZone): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(value);
  if (!m) return null;
  const wall = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4]), Number(m[5]));
  if (zone === "UTC") return wall;
  const offsetAt = (ms: number) => {
    const p = partsIn(ms, zone);
    return Date.UTC(p.year!, p.month! - 1, p.day!, p.hour!, p.minute!) - Math.floor(ms / 60_000) * 60_000;
  };
  // The two UTC offsets in force around that day give the candidates; keep those whose wall clock matches.
  const day = 86_400_000;
  const matches = [offsetAt(wall - day), offsetAt(wall + day)]
    .map((off) => wall - off)
    .filter((ms) => utcToInput(new Date(ms).toISOString(), zone) === value.slice(0, 16));
  return matches.length > 0 ? Math.min(...matches) : wall - offsetAt(wall);
}
