import type { Data, Model } from "./data";
import { at, Rows, rowsOf } from "./rows";
import { dayKey, dayKeys, ms } from "./time";
import type { PredShard } from "./types";

/** One published row: where it is in its shard and the instant it was issued. */
export interface Picked {
  key: string;
  shard: PredShard;
  rows: Rows;
  /** Row number inside the shard. */
  i: number;
  /** Issue time, ms. */
  t: number;
  /** Axis E. */
  e: number;
}

/** The shard keys `[lo, hi)` touches, restricted to the keys the model published. */
export function keysOf(h: Model, lo: number, hi: number): string[] {
  if (!h.meta.regular) return h.meta.keys.includes("all") ? ["all"] : [];
  const have = new Set(h.meta.keys);
  return dayKeys(lo, hi).filter((k) => have.has(k));
}

/** The shard key of one issue time. */
export const keyOf = (h: Model, t: number): string => (h.meta.regular ? dayKey(t) : "all");

export interface TimeQuery {
  time?: string;
  from?: string;
  to?: string;
}

/**
 * Per modelled entity, the row at `time`, or the latest row in `[from, to)` (`ArtifactStore._rows_at`). An entity
 * without a row is not in the map: it has no observation.
 */
export async function pickRows(d: Data, h: Model, q: TimeQuery, signal?: AbortSignal): Promise<Map<number, Picked>> {
  const [lo, hi] = q.time !== undefined ? [ms(q.time), ms(q.time) + 1] : [ms(q.from!), ms(q.to!)];
  const keys = keysOf(h, lo, hi);
  const shards = await Promise.all(keys.map((k) => d.pred(h, k, signal)));
  const picked = new Map<number, Picked>();
  keys.forEach((key, n) => {
    const shard = shards[n];
    if (!shard) return;
    const rows = rowsOf(shard, h.meta.entities.length);
    rows.tMs.forEach((t, k) => {
      if (t < lo || t >= hi) return;
      for (const i of rows.byTime[k]!) {
        const e = shard.ei[i]!;
        picked.set(e, { key, shard, rows, i, t, e });
      }
    });
  });
  return picked;
}

/** The row of one entity at one issue time, if the model published it. */
export async function findRow(d: Data, h: Model, entityId: string, t: number, signal?: AbortSignal): Promise<Picked | null> {
  const e = h.entityIndex.get(entityId);
  if (e === undefined) return null;
  const key = keyOf(h, t);
  const shard = await d.pred(h, key, signal);
  if (!shard) return null;
  const rows = rowsOf(shard, h.meta.entities.length);
  const i = rows.find(t, e);
  return i === undefined ? null : { key, shard, rows, i, t, e };
}

/** The class named by an index into `classes`, or null. */
export const classAt = (h: Model, index: number | null): string | null => (index === null ? null : (h.meta.classes[index] ?? null));

/** `reason` codes -> the contract's missing reason. */
export const reasonAt = (h: Model, p: Picked) => {
  const code = at(p.shard.reason, p.i);
  return code === null ? null : (h.meta.missing_reasons[code] ?? null);
};

