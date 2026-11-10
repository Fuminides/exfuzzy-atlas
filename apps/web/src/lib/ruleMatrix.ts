import type { ModelRules, RuleDefinition, RuleImportance, RuleImportanceResponse } from "../api/types";
import { rankedRules } from "./importance";
import { leadShare } from "./mixture";

/** The share a rule is ranked by: decided (winning rule, TSK) or, in a mixture (v0.7), the top-rule share. */
const leadOf = (r: RuleImportance | undefined): number => (r ? leadShare(r) : 0);

/** One condition of a rule: a variable, the term it asks for and an optional modifier. */
export type Antecedent = RuleDefinition["antecedents"][number];

/**
 * Layout of the rule matrix of Patrones: one row per rule, in the order the cards use, and one column per input variable
 * the shown rules use. Columns go from the variable whose rules decide most predictions to the one whose rules decide
 * fewest. Nothing here is an activation: the numbers are the published "decides and hits" of each rule (in a mixture of
 * rules, v0.7: the share of the predictions where each is the rule that adds the most to the predicted class).
 */

/** Without the importance the cards show this many rules first; with it, the rules that decide at least MINOR_SHARE. */
export const FIRST = 8;
export const MINOR_SHARE = 0.01;

export interface MatrixColumn {
  feature: string;
  /** Sum of the decided shares of every rule (shown or folded) that uses the variable; null without the importance. */
  share: number | null;
  /** How many rules (shown or folded) use the variable. */
  nRules: number;
}

export interface MatrixRow {
  rule: RuleDefinition;
  importance: RuleImportance | null;
  /** One entry per column: the condition the rule puts on that variable, or null when it does not use it. */
  cells: (Antecedent | null)[];
}

export interface RuleMatrix {
  columns: MatrixColumn[];
  rows: MatrixRow[];
  /** Rules shown while folded, and how many fold. */
  nMain: number;
  nHidden: number;
  /** Share of the predictions the rules shown while folded decide together (the headline); null without the importance. */
  mainShare: number | null;
}

/** The rules in the order of the cards: by decided share (ties: model order) with the importance, else the model's order. */
export function orderedRules(model: Pick<ModelRules, "rules">, imp: Pick<RuleImportanceResponse, "rules"> | null): RuleDefinition[] {
  if (!imp) return [...model.rules];
  return rankedRules(imp.rules).flatMap((r) => model.rules.filter((d) => d.rule_id === r.rule_id));
}

/** How many rules show while folded: those that decide at least 1 % (at least one), or the first 8 without the importance. */
export function mainCount(order: readonly RuleDefinition[], byId: ReadonlyMap<string, RuleImportance> | null): number {
  if (!byId) return Math.min(FIRST, order.length);
  return Math.max(1, order.filter((r) => leadOf(byId.get(r.rule_id)) >= MINOR_SHARE).length);
}

/** The condition a rule puts on a variable (the first, if it named the variable twice), or null. */
export const cellFor = (rule: Pick<RuleDefinition, "antecedents">, feature: string): Antecedent | null => rule.antecedents.find((a) => a.feature === feature) ?? null;

/**
 * Columns for `shown`: the variables they use, the one whose rules decide most first. The share counts every rule of the
 * model, so unfolding the tail adds columns at the end but never reorders the ones already there. Ties: more rules first,
 * then the model's variable order.
 */
export function matrixColumns(
  shown: readonly RuleDefinition[],
  all: readonly RuleDefinition[],
  variables: readonly { feature: string }[],
  byId: ReadonlyMap<string, RuleImportance> | null,
): MatrixColumn[] {
  const used = new Set(shown.flatMap((r) => r.antecedents.map((a) => a.feature)));
  const position = new Map(variables.map((v, i) => [v.feature, i]));
  const columns = [...used].map((feature) => {
    const users = all.filter((r) => cellFor(r, feature) !== null);
    const share = byId ? users.reduce((s, r) => s + leadOf(byId.get(r.rule_id)), 0) : null;
    return { feature, share, nRules: users.length };
  });
  const pos = (f: string) => position.get(f) ?? Number.MAX_SAFE_INTEGER;
  return columns.sort((a, b) => (b.share ?? 0) - (a.share ?? 0) || b.nRules - a.nRules || pos(a.feature) - pos(b.feature) || a.feature.localeCompare(b.feature));
}

/** The whole layout: ranked rows (folded unless `showAll`), their columns, and each row's condition per column. */
export function ruleMatrix(model: Pick<ModelRules, "rules" | "variables">, imp: Pick<RuleImportanceResponse, "rules"> | null, showAll: boolean): RuleMatrix {
  const byId = imp ? new Map(imp.rules.map((r) => [r.rule_id, r])) : null;
  const order = orderedRules(model, imp);
  const nMain = mainCount(order, byId);
  const shown = showAll ? order : order.slice(0, nMain);
  const columns = matrixColumns(shown, model.rules, model.variables, byId);
  const rows = shown.map((rule) => ({ rule, importance: byId?.get(rule.rule_id) ?? null, cells: columns.map((c) => cellFor(rule, c.feature)) }));
  const mainShare = byId ? order.slice(0, nMain).reduce((s, r) => s + leadOf(byId.get(r.rule_id)), 0) : null;
  return { columns, rows, nMain, nHidden: Math.max(0, order.length - nMain), mainShare };
}
