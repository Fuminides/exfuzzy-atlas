import type { TimeWindow } from "./windows";

/** The instant of `instants` closest to `target` (ties: the earlier), optionally only those inside `within`; null if none. */
export function nearestInstant(instants: readonly string[], target: string, within?: TimeWindow | null): string | null {
  const t = Date.parse(target);
  let best: string | null = null;
  for (const instant of instants) {
    const x = Date.parse(instant);
    if (within && !(x >= Date.parse(within.from) && x < Date.parse(within.to))) continue;
    if (best === null || Math.abs(x - t) < Math.abs(Date.parse(best) - t)) best = instant;
  }
  return best;
}

/** Index of the grid value closest to `value` (0 when there is no value): where a snapped slider sits. */
export function gridIndex(grid: readonly number[], value: number | null): number {
  if (value === null) return 0;
  return grid.reduce((best, g, i) => (Math.abs(g - value) < Math.abs(grid[best]! - value) ? i : best), 0);
}
