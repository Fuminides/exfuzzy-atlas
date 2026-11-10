import type { RuleTrace, ScenarioResponse } from "../api/types";
import { dec } from "./format";

/** Memberships (and effective memberships) closer than this are the same number. */
const EPS = 1e-12;

export interface MembershipChange {
  ruleId: string;
  feature: string;
  term: string;
  before: number;
  after: number;
  /** after - before, from the two traces the API returned. */
  delta: number;
}

/**
 * Antecedent memberships that differ between the original and the modified trace, largest change first. Both numbers
 * come from the engine (the API runs the real inference twice); this only lines them up and subtracts.
 */
export function membershipChanges(r: Pick<ScenarioResponse, "original" | "modified">): MembershipChange[] {
  const before = new Map<string, number>();
  for (const rule of r.original.rules) for (const a of rule.antecedents) before.set(`${rule.rule_id}|${a.feature}|${a.term}`, a.membership);
  const out: MembershipChange[] = [];
  for (const rule of r.modified.rules) {
    for (const a of rule.antecedents) {
      const b = before.get(`${rule.rule_id}|${a.feature}|${a.term}`);
      if (b === undefined || Math.abs(a.membership - b) <= EPS) continue;
      out.push({ ruleId: rule.rule_id, feature: a.feature, term: a.term, before: b, after: a.membership, delta: a.membership - b });
    }
  }
  return out.sort((x, y) => Math.abs(y.delta) - Math.abs(x.delta));
}

/** Rules whose firing (or association) changed, largest firing change first. */
export function changedRuleDeltas(r: Pick<ScenarioResponse, "rule_deltas">): ScenarioResponse["rule_deltas"] {
  return r.rule_deltas
    .filter((d) => Math.abs(d.firing_delta ?? 0) > EPS || Math.abs(d.association_delta ?? 0) > EPS)
    .sort((a, b) => Math.abs(b.firing_delta ?? 0) - Math.abs(a.firing_delta ?? 0));
}

/** Features of the baseline trace the panel can offer (the model's inputs of that row). */
export const traceFeatures = (t: Pick<RuleTrace, "feature_values">): string[] => t.feature_values.map((f) => f.feature);

/** A signed change with a real minus: "+3.2", "−0.1", "0". */
export function signed(n: number, digits = 3): string {
  const s = dec(Math.abs(n), digits);
  return Number(s.replace(",", ".")) === 0 ? "0" : n > 0 ? `+${s}` : `−${s}`;
}
