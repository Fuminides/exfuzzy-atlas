import type { LinguisticTerm, RuleDefinition } from "../api/types";
import { trIn, type Lang } from "../i18n";

/**
 * Conditions of contract v0.8: `is` one term, `at_least` / `at_most` a term of an ordered variable, `any_of` a named
 * compound of terms. Everything here is display only: the memberships a screen quotes come from the API's traces; the
 * shapes below are drawn on the partitions plot and the hour range reads «Tarde-noche o Noche, 17–5 h».
 */

export type Operator = "is" | "at_least" | "at_most" | "any_of";

/** What the display needs of an antecedent (a rule's, or a trace's, which carries no label). */
export interface CondSpec {
  term: string;
  operator?: Operator | null;
  terms?: readonly string[] | null;
  label?: string | null;
  label_en?: string | null;
}

export const operatorOf = (c: Partial<CondSpec> | undefined | null): Operator => c?.operator ?? "is";

/** Whether the condition is more than one term's own membership (an old model never is). */
export const isExtra = (c: Partial<CondSpec> | undefined | null): boolean => operatorOf(c) !== "is";

/** The base terms the condition covers, low to high; `[term]` for an `is` condition or when the API left `terms` out. */
export const termsOf = (c: Pick<CondSpec, "term" | "terms">): readonly string[] => (c.terms && c.terms.length > 0 ? c.terms : [c.term]);

/** Identifies a condition within one variable: the term for `is`, else the operator with the terms it covers. */
export const condKey = (c: CondSpec): string => (isExtra(c) ? `${operatorOf(c)}|${termsOf(c).join(",")}` : c.term);

/** The conditions that are more than a plain term and some rule of the model uses on `feature`, once each. */
export function extraConditions(rules: readonly Pick<RuleDefinition, "antecedents">[], feature: string): CondSpec[] {
  const seen = new Map<string, CondSpec>();
  for (const r of rules) for (const a of r.antecedents) if (a.feature === feature && isExtra(a) && !seen.has(condKey(a))) seen.set(condKey(a), a);
  return [...seen.values()];
}

/** Membership of `x` in a published term (trapezoid [a,b,c,d], triangle [a,b,c], gaussian [mean, sd]); drawing only. */
export function termMembership(t: Pick<LinguisticTerm, "membership_type" | "params">, x: number): number {
  const p = t.params;
  if (t.membership_type === "gaussian" || p.length === 2) return p[1]! > 0 ? Math.exp(-((x - p[0]!) ** 2) / (2 * p[1]! ** 2)) : x === p[0] ? 1 : 0;
  const [a, b, c, d] = p.length === 3 ? [p[0]!, p[1]!, p[1]!, p[2]!] : [p[0]!, p[1]!, p[2]!, p[3]!];
  if (x < b) return x <= a ? 0 : (x - a) / (b - a);
  if (x <= c) return 1;
  return x < d ? (d - x) / (d - c) : 0;
}

/** The bounded sum min(1, sum of the memberships of `terms`) at `x`: the shape of an ordinal or compound condition. */
export const boundedSum = (terms: readonly Pick<LinguisticTerm, "membership_type" | "params">[], x: number): number =>
  Math.min(1, terms.reduce((s, t) => s + termMembership(t, x), 0));

/**
 * The bounded sum as a polyline over [lo, hi]: every knot of the terms, the points where the sum reaches 1, and (with a
 * gaussian among the terms) a regular grid.
 */
export function boundedSumPoints(terms: readonly Pick<LinguisticTerm, "membership_type" | "params">[], lo: number, hi: number): [number, number][] {
  const grid = terms.some((t) => t.membership_type === "gaussian" || t.params.length === 2) ? Array.from({ length: 81 }, (_, i) => lo + ((hi - lo) * i) / 80) : [];
  const xs = [...new Set([lo, hi, ...grid, ...terms.flatMap((t) => (t.params.length === 2 ? [] : t.params)).filter((v) => v > lo && v < hi)])].sort((a, b) => a - b);
  const sum = (x: number) => terms.reduce((s, t) => s + termMembership(t, x), 0);
  const out: [number, number][] = [];
  xs.forEach((x, i) => {
    if (i > 0) {
      // the sum is linear between knots: where it crosses 1 the bounded sum bends
      const x0 = xs[i - 1]!;
      const s0 = sum(x0);
      const s1 = sum(x);
      if ((s0 - 1) * (s1 - 1) < 0) out.push([x0 + ((1 - s0) / (s1 - s0)) * (x - x0), 1]);
    }
    out.push([x, Math.min(1, sum(x))]);
  });
  return out;
}

/** Membership of a clock input at which an hour counts as inside the compound. */
const INSIDE = 0.5;

/**
 * The hours of an hour-of-day input (domain 0..23) at which the compound's bounded sum is at least 0.5, as stretches
 * `[from, to]` (both inclusive). When both ends of the clock are in, the two stretches join into one that wraps midnight
 * (`[17, 5]`).
 */
export function hourStretches(terms: readonly Pick<LinguisticTerm, "membership_type" | "params">[], domain: readonly [number, number] | null | undefined): [number, number][] {
  const lo = Math.ceil(domain ? domain[0] : 0);
  const hi = Math.floor(domain ? domain[1] : 23);
  const stretches: [number, number][] = [];
  for (let h = lo; h <= hi; h++) {
    if (boundedSum(terms, h) < INSIDE) continue;
    const last = stretches[stretches.length - 1];
    if (last && last[1] === h - 1) last[1] = h;
    else stretches.push([h, h]);
  }
  const first = stretches[0];
  const last = stretches[stretches.length - 1];
  if (stretches.length > 1 && lo === 0 && hi === 23 && first![0] === 0 && last![1] === 23) return [...stretches.slice(1, -1), [last![0], first![1]]];
  return stretches;
}

/** «17–5 h», «0–6 h, 15–23 h»; "" when no hour reaches 0.5. */
export const hourRangeText = (stretches: readonly [number, number][], fmtHour: (h: number) => string = String): string =>
  stretches.map(([a, b]) => (a === b ? `${fmtHour(a)} h` : `${fmtHour(a)}–${fmtHour(b)} h`)).join(", ");

/** «Tarde-noche o Noche», "Evening or Night": the constituents joined with the language's «o» / "or". */
export const joinOr = (names: readonly string[], lang: Lang): string => names.join(trIn(lang)(" o ", " or "));
