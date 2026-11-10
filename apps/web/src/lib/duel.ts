import type { MissingReason, ModelRules, RuleMapMetric, RuleMapResponse } from "../api/types";
import type { ColorStop } from "./colorScale";
import type { StationRow } from "../map/stations";
import { dec } from "./format";

/**
 * Rule Duel (E4): two rules of the SAME model, asked with the same metric, time or window and tau. The only thing that
 * differs between the two `/rule-map` requests is `rule_id`. There is no rule mapping between models, so a duel never
 * leaves the model of the loaded rules.
 */
export interface DuelParams {
  modelId: string;
  metric: RuleMapMetric;
  time?: string;
  from?: string;
  to?: string;
  tau?: number;
}

export interface RuleMapQuery extends DuelParams {
  ruleId: string;
}

/** The request for one rule of a duel (or the single selected rule): `params` is shared, only the rule changes. */
export const ruleMapQuery = (params: DuelParams, ruleId: string): RuleMapQuery => ({ ...params, ruleId });

/** Rule B proposed when a duel starts: the next rule of the model after A (the first one if A is the last). */
export function defaultRuleB(rules: ModelRules["rules"], ruleA: string | null): string | null {
  if (rules.length < 2) return null;
  const i = rules.findIndex((r) => r.rule_id === ruleA);
  return rules[(i + 1) % rules.length]!.rule_id;
}

/** Entities without a feature in the answer keep `value: null`: absent is never drawn as 0. */
export function withRuleMap(baseRows: readonly StationRow[], data: RuleMapResponse): StationRow[] {
  const byId = new Map(data.features.map((f) => [f.properties.entity_id, f.properties]));
  return baseRows.map((r) => {
    const p = byId.get(r.entityId);
    return p ? { ...r, value: p.value, missingReason: p.missing_reason ?? null, nValid: p.n_valid } : r;
  });
}

/** One entity of the duel: both activations and their difference (null when either side is missing). */
export interface DuelEntry {
  entityId: string;
  name: string;
  a: number | null;
  b: number | null;
  /** value(A) - value(B); null if A or B is null. A missing side is never treated as 0. */
  diff: number | null;
  missingA: MissingReason | null;
  missingB: MissingReason | null;
  nValidA: number | null;
  nValidB: number | null;
}

export function duelEntries(rowsA: readonly StationRow[], rowsB: readonly StationRow[]): DuelEntry[] {
  const byId = new Map(rowsB.map((r) => [r.entityId, r]));
  return rowsA.map((a) => {
    const b = byId.get(a.entityId);
    const bv = b?.value ?? null;
    return {
      entityId: a.entityId,
      name: a.name,
      a: a.value,
      b: bv,
      diff: a.value !== null && bv !== null ? a.value - bv : null,
      missingA: a.missingReason,
      missingB: b?.missingReason ?? null,
      nValidA: a.nValid,
      nValidB: b?.nValid ?? null,
    };
  });
}

/** The difference as map rows: the colour is value(A) - value(B) on the diverging scale; missing on either side stays null. */
export function diffRows(rowsA: readonly StationRow[], entries: readonly DuelEntry[]): StationRow[] {
  const byId = new Map(entries.map((e) => [e.entityId, e]));
  return rowsA.map((r) => {
    const e = byId.get(r.entityId);
    return {
      ...r,
      value: e?.diff ?? null,
      // The reason of the side that is missing; nValid is meaningless for a difference.
      missingReason: e && e.diff === null ? (e.missingA ?? e.missingB) : null,
      nValid: null,
    };
  });
}

/** Diverging scale for A - B in [-1, 1], centred at 0 (ColorBrewer PuOr, colour-blind safe): purple = B higher, orange = A higher. */
export const DIVERGING: readonly ColorStop[] = [
  [0, "#542788"],
  [0.25, "#998ec3"],
  [0.5, "#f1f1f1"],
  [0.75, "#f1a340"],
  [1, "#b35806"],
];
export const DIFF_DOMAIN = [-1, 1] as const;

/** A signed difference with a real minus sign: "+0.250", "−0.100", "0.000". */
export const fmtDiff = (n: number): string => {
  const s = dec(Math.abs(n), 3);
  const zero = s === dec(0, 3);
  return n > 0 && !zero ? `+${s}` : n < 0 && !zero ? `−${s}` : s;
};
