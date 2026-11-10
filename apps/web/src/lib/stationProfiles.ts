import type { RuleImportanceResponse } from "../api/types";
import { leadShare } from "./mixture";

/**
 * What sets one entity (station, taxi zone, sampling point) apart by the rules the model uses there. Everything reads a
 * generic per-entity rule-share vector: the share of the entity's predictions each rule accounts for, next to the same
 * share over all the entities. For winning-rule classifiers and TSK regression that share is `decided_share`, the rule
 * that decides each prediction; for a mixture of rules (contract v0.7) it is `top_contributor_share`, the rule that adds
 * the most to the predicted class (`leadShare`). Only `shareTable` reads the API field, and the words that name the share
 * are in `stationWording.ts`. The shares are counts of predictions, nothing more.
 */

/** A rule is characteristic of an entity only when it accounts for at least this share of the entity's predictions… */
export const MIN_SHARE = 0.05;
/**
 * …and for at least this many of them. Five is the usual minimum count for comparing two frequencies (the rule of thumb
 * of the chi-square test). It only binds where an entity has few predictions: Water's sampling points have a median of
 * 18, where 5 % alone would let one or two samples make a rule "characteristic". Germany and NYC have hundreds or
 * thousands of predictions per entity, and there the 5 % is the bar. The same count is the minimum for an entity to get
 * a profile.
 */
export const MIN_COUNT = 5;
/** …and when its share there is at least this many times its share over all the entities (the lift). */
export const MIN_LIFT = 1.25;

/** Profiles: k-means with a fixed seed, k from 2 to 5, the k with the best mean silhouette (ties: the smaller k). */
export const PROFILE_SEED = 20261109;
export const PROFILE_K = [2, 5] as const;
const RESTARTS = 10;
const MAX_ITER = 100;
/** Below this mean silhouette the profiles barely separate (Kaufman & Rousseeuw: "no substantial structure"); the legend says so. */
export const WEAK_SILHOUETTE = 0.25;
/** At most this many rules name a profile ("más R03 y R07"). */
const NAME_RULES = 2;

export interface ShareEntity {
  entityId: string;
  /** Predictions of the entity the shares are over (0: none in the published period). */
  n: number;
  /** One share per rule of `ShareTable.ruleIds`. */
  shares: number[];
}

export interface ShareTable {
  /** Rules in the model's order. */
  ruleIds: string[];
  /** The share of each rule over all the entities' predictions. */
  overall: number[];
  entities: ShareEntity[];
}

const share = leadShare;

/** The only reader of the API's share field. v0.7 (rule mixtures) changes what the share means, not this shape. */
export function shareTable(imp: Pick<RuleImportanceResponse, "rules" | "entities">): ShareTable {
  const ruleIds = imp.rules.map((r) => r.rule_id);
  const index = new Map(ruleIds.map((id, i) => [id, i]));
  return {
    ruleIds,
    overall: imp.rules.map(share),
    entities: imp.entities.map((e) => {
      const shares = ruleIds.map(() => 0);
      for (const r of e.rules) {
        const i = index.get(r.rule_id);
        if (i !== undefined) shares[i] = share(r);
      }
      return { entityId: e.entity_id, n: e.n_predicted, shares };
    }),
  };
}

export interface RuleLift {
  ruleId: string;
  /** Share of the entity's predictions. */
  here: number;
  /** Share over all the entities. */
  overall: number;
  /** here / overall. */
  lift: number;
  /** Predictions of the entity the share stands for. */
  count: number;
  /** Clears the support bar (MIN_SHARE and MIN_COUNT). */
  supported: boolean;
}

const countOf = (share: number, n: number) => Math.round(share * n);
const isSupported = (here: number, count: number) => here >= MIN_SHARE - 1e-12 && count >= MIN_COUNT;

/** Every rule the entity uses, by lift (ties: larger share here, then the model's order). */
export function entityLifts(table: ShareTable, entity: ShareEntity): RuleLift[] {
  return table.ruleIds
    .map((ruleId, i) => {
      const here = entity.shares[i] ?? 0;
      const overall = table.overall[i] ?? 0;
      const count = countOf(here, entity.n);
      return { i, ruleId, here, overall, lift: overall > 0 ? here / overall : 0, count, supported: isSupported(here, count) };
    })
    .filter((l) => l.here > 0 && l.overall > 0)
    .sort((a, b) => b.lift - a.lift || b.here - a.here || a.i - b.i)
    .map((l) => ({ ruleId: l.ruleId, here: l.here, overall: l.overall, lift: l.lift, count: l.count, supported: l.supported }));
}

/** The rules used clearly more at this entity than overall (supported, lift ≥ MIN_LIFT), most over-represented first. */
export const distinguishing = (lifts: readonly RuleLift[], max = 3): RuleLift[] => lifts.filter((l) => l.supported && l.lift >= MIN_LIFT - 1e-12).slice(0, max);

/** The characteristic rule: the most over-represented supported rule, or null («sin regla característica»). */
export const characteristicRule = (lifts: readonly RuleLift[]): RuleLift | null => distinguishing(lifts, 1)[0] ?? null;

/** The rules that account for most of the entity's predictions (the fallback when none stands out, and the third map mode). */
export function topRules(table: ShareTable, entity: ShareEntity, max = 3): RuleLift[] {
  const all = entityLifts(table, entity);
  return all.sort((a, b) => b.here - a.here || table.ruleIds.indexOf(a.ruleId) - table.ruleIds.indexOf(b.ruleId)).slice(0, max);
}

// ---------------------------------------------------------------------------------------------- profiles (k-means)

export interface Profile {
  /** 0 = the largest profile. */
  index: number;
  /** "A", "B"… in the same order. */
  letter: string;
  entityIds: string[];
  /** Pooled share of each rule over the profile's predictions (same order as `ShareTable.ruleIds`). */
  shares: number[];
  /** The rules that name it: supported in the pooled shares and over-represented against all the entities, at most two. */
  naming: RuleLift[];
}

export interface Profiles {
  k: number;
  silhouette: number;
  /** Silhouette of every k tried, to report the choice. */
  tried: { k: number; silhouette: number }[];
  profiles: Profile[];
  /** entity id -> profile index; entities with fewer than MIN_COUNT predictions have none. */
  of: ReadonlyMap<string, number>;
}

/** mulberry32: a small seeded PRNG, so the clustering is the same on every machine and every render. */
function prng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const sq = (a: readonly number[], b: readonly number[]) => {
  let s = 0;
  for (let i = 0; i < a.length; i++) s += (a[i]! - b[i]!) ** 2;
  return s;
};

const nearest = (x: readonly number[], centres: readonly number[][]) => {
  let best = 0;
  let bestD = Infinity;
  centres.forEach((c, j) => {
    const d = sq(x, c);
    if (d < bestD - 1e-15) {
      bestD = d;
      best = j;
    }
  });
  return best;
};

/** Lloyd's k-means from k-means++ seeds, the best of RESTARTS runs by inertia. Deterministic for a given seed. */
function kmeans(points: readonly number[][], k: number, seed: number): number[] | null {
  const rand = prng(seed + k);
  const dim = points[0]!.length;
  let best: { inertia: number; labels: number[] } | null = null;
  for (let run = 0; run < RESTARTS; run++) {
    const centres: number[][] = [points[Math.floor(rand() * points.length)]!.slice()];
    while (centres.length < k) {
      const d = points.map((p) => Math.min(...centres.map((c) => sq(p, c))));
      const total = d.reduce((a, b) => a + b, 0);
      if (total <= 0) break;
      let t = rand() * total;
      let pickedAt = d.length - 1;
      for (let i = 0; i < d.length; i++) {
        t -= d[i]!;
        if (t <= 0) {
          pickedAt = i;
          break;
        }
      }
      centres.push(points[pickedAt]!.slice());
    }
    if (centres.length < k) continue;
    let labels = points.map((p) => nearest(p, centres));
    for (let it = 0; it < MAX_ITER; it++) {
      for (let j = 0; j < k; j++) {
        const members = points.filter((_, i) => labels[i] === j);
        if (members.length === 0) continue; // an empty cluster keeps its centre
        centres[j] = Array.from({ length: dim }, (_, d) => members.reduce((a, m) => a + m[d]!, 0) / members.length);
      }
      const next = points.map((p) => nearest(p, centres));
      if (next.every((l, i) => l === labels[i])) break;
      labels = next;
    }
    if (new Set(labels).size < k) continue;
    const inertia = points.reduce((a, p, i) => a + sq(p, centres[labels[i]!]!), 0);
    if (!best || inertia < best.inertia - 1e-12) best = { inertia, labels };
  }
  return best?.labels ?? null;
}

/** Mean silhouette over every point (exact: a few hundred entities at most). */
function silhouette(dist: readonly Float64Array[], labels: readonly number[], k: number): number {
  const n = labels.length;
  let total = 0;
  for (let i = 0; i < n; i++) {
    const sum = new Array<number>(k).fill(0);
    const cnt = new Array<number>(k).fill(0);
    for (let j = 0; j < n; j++) {
      if (j === i) continue;
      sum[labels[j]!]! += dist[i]![j]!;
      cnt[labels[j]!]!++;
    }
    const own = labels[i]!;
    if (cnt[own] === 0) continue; // a singleton scores 0
    const a = sum[own]! / cnt[own]!;
    let b = Infinity;
    for (let c = 0; c < k; c++) if (c !== own && cnt[c]! > 0) b = Math.min(b, sum[c]! / cnt[c]!);
    const m = Math.max(a, b);
    total += m > 0 && Number.isFinite(b) ? (b - a) / m : 0;
  }
  return total / n;
}

/**
 * Groups the entities by their rule-share vectors. The distance is the Hellinger distance (Euclidean on the square roots
 * of the shares), the usual one between two compositions: a rule that accounts for 45 % everywhere does not drown the
 * differences in the rules that account for 5–15 %. Entities with fewer than MIN_COUNT predictions are left out.
 * null when fewer than three entities qualify.
 */
export function profilesOf(table: ShareTable, seed = PROFILE_SEED): Profiles | null {
  const members = table.entities.filter((e) => e.n >= MIN_COUNT);
  if (members.length < 3) return null;
  const points = members.map((e) => e.shares.map((s) => Math.sqrt(Math.max(0, s))));
  const dist = points.map((p) => Float64Array.from(points, (q) => Math.sqrt(sq(p, q))));
  const tried: { k: number; silhouette: number; labels: number[] }[] = [];
  for (let k = PROFILE_K[0]; k <= Math.min(PROFILE_K[1], members.length - 1); k++) {
    const labels = kmeans(points, k, seed);
    if (labels) tried.push({ k, silhouette: silhouette(dist, labels, k), labels });
  }
  if (tried.length === 0) return null;
  const chosen = tried.reduce((a, b) => (b.silhouette > a.silhouette + 1e-12 ? b : a));
  // Largest profile first (ties: the one whose first member comes first), so "A" is the most common.
  const order = Array.from({ length: chosen.k }, (_, j) => j)
    .map((j) => ({ j, size: chosen.labels.filter((l) => l === j).length, first: chosen.labels.indexOf(j) }))
    .sort((a, b) => b.size - a.size || a.first - b.first)
    .map((o) => o.j);
  const profiles: Profile[] = order.map((j, index) => {
    const mine = members.filter((_, i) => chosen.labels[i] === j);
    const n = mine.reduce((a, e) => a + e.n, 0);
    const shares = table.ruleIds.map((_, r) => mine.reduce((a, e) => a + (e.shares[r] ?? 0) * e.n, 0) / n);
    const naming = distinguishing(entityLifts(table, { entityId: "", n, shares }), NAME_RULES);
    return { index, letter: String.fromCharCode(65 + index), entityIds: mine.map((e) => e.entityId), shares, naming };
  });
  const of = new Map<string, number>();
  for (const p of profiles) for (const id of p.entityIds) of.set(id, p.index);
  return { k: chosen.k, silhouette: chosen.silhouette, tried: tried.map(({ k, silhouette: s }) => ({ k, silhouette: s })), profiles, of };
}

/**
 * The predicted category mix behind a share vector: each rule's share goes to the class it predicts. Exact only for a
 * winning-rule classifier, where the deciding rule's class IS the prediction; with rule mixtures (v0.7) it is not, so the
 * caller passes the measure and gets null for anything else. Classes in the order of `classes`.
 */
export function classMix(
  table: Pick<ShareTable, "ruleIds">,
  shares: readonly number[],
  classOf: (ruleId: string) => string | null,
  classes: readonly string[],
  measure: string,
): number[] | null {
  if (measure !== "winning_rule") return null;
  const mix = classes.map(() => 0);
  table.ruleIds.forEach((id, i) => {
    const c = classOf(id);
    const k = c === null ? -1 : classes.indexOf(c);
    if (k >= 0) mix[k]! += shares[i] ?? 0;
  });
  const total = mix.reduce((a, b) => a + b, 0);
  return total > 0 ? mix.map((m) => m / total) : null;
}
