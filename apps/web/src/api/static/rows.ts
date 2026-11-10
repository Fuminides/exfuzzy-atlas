import type { Col, PredShard } from "./types";
import { ms } from "./time";

/** A column read at row `i`; an absent column is all null. */
export const at = <T>(col: Col<T>, i: number): T | null => (col ? (col[i] ?? null) : null);

/** The rows of a pred shard indexed once: by issue time, by entity, and by (issue time, entity). */
export class Rows {
  readonly tMs: number[];
  /** Row numbers per issue time (index into `t`), ascending. */
  readonly byTime: number[][];
  /** Row numbers per entity (E index), in issue-time order. */
  readonly byEntity = new Map<number, number[]>();
  private readonly lookup = new Map<number, number>();
  private readonly tIndex = new Map<number, number>();

  constructor(readonly shard: PredShard, private readonly nEntities: number) {
    this.tMs = shard.t.map(ms);
    this.tMs.forEach((t, k) => this.tIndex.set(t, k));
    this.byTime = this.tMs.map(() => []);
    for (let i = 0; i < shard.n; i++) {
      const k = shard.ti[i]!;
      const e = shard.ei[i]!;
      this.byTime[k]!.push(i);
      this.lookup.set(k * nEntities + e, i);
      const list = this.byEntity.get(e);
      if (list) list.push(i);
      else this.byEntity.set(e, [i]);
    }
  }

  /** The row of entity `e` at issue time `t` (ms), if the model published one. */
  find(t: number, e: number): number | undefined {
    const k = this.tIndex.get(t);
    return k === undefined ? undefined : this.lookup.get(k * this.nEntities + e);
  }

  /** Issue time (ms) of row `i`. */
  timeOf(i: number): number {
    return this.tMs[this.shard.ti[i]!]!;
  }
}

const cache = new WeakMap<PredShard, Rows>();

/** The (memoised) row index of a shard. */
export function rowsOf(shard: PredShard, nEntities: number): Rows {
  let rows = cache.get(shard);
  if (!rows) {
    rows = new Rows(shard, nEntities);
    cache.set(shard, rows);
  }
  return rows;
}
