import type { EntityImportance, EntityRuleImportance, RuleImportance, RuleImportanceResponse } from "../api/types";
import { tr } from "../i18n";
import { formatDate, pct, sig3 } from "./format";
import { hitsWhenTop, leadShare, topShareText } from "./mixture";

/**
 * Importance as the contract defines it (CONTRACTS.md §12.3): "decide and hit". How many predictions a rule decides and,
 * for a classifier, how often it is right when it decides; for the additive regression its exact share of the weighted
 * average and the MAE of the predictions it decides. It is faithful to the inference and is not a cause.
 * This module reads the precomputed numbers; it computes none of them.
 */

export const isRegressionImportance = (i: Pick<RuleImportanceResponse, "measure">): boolean => i.measure === "weighted_average";

/** Contract v0.7: a mixture of rules has no deciding rule (`decided_share` is null); 0 keeps the order stable. */
export const decidedShare = (r: { decided_share?: number | null }): number => r.decided_share ?? 0;

/**
 * Rules from the one that decides most predictions to the one that decides least (ties: rule order). In a mixture of
 * rules (v0.7) by the share of the predictions where each is the rule that adds the most to the predicted class.
 */
export function rankedRules(rules: readonly RuleImportance[]): RuleImportance[] {
  return rules
    .map((r, i) => ({ r, i }))
    .sort((a, b) => leadShare(b.r) - leadShare(a.r) || a.i - b.i)
    .map(({ r }) => r);
}

/** The rules a zone's predictions are decided by (a mixture: that add the most there), first the one with most. */
export function entityRanked(entity: EntityImportance | undefined): EntityRuleImportance[] {
  return [...(entity?.rules ?? [])].sort((a, b) => leadShare(b) - leadShare(a) || a.rule_id.localeCompare(b.rule_id));
}

export const entityOf = (imp: RuleImportanceResponse, entityId: string): EntityImportance | undefined => imp.entities.find((e) => e.entity_id === entityId);

/**
 * `n_withheld` (contract amendment of v0.5): issue times where a rule fired but the publish withheld the prediction (NYC
 * zones with no reference level). They are neither in `n_predicted` nor in `n_no_rule`.
 */
type Counts = Pick<RuleImportanceResponse, "n_no_rule" | "n_predicted" | "n_withheld">;
export const withheldOf = (imp: Pick<RuleImportanceResponse, "n_withheld">): number => imp.n_withheld ?? 0;

const hoursWithInputs = (imp: Counts): number => imp.n_no_rule + imp.n_predicted + withheldOf(imp);

/** Share of the hours with complete inputs in which no rule fired (those have no prediction). */
export function noRuleShare(imp: Counts): number {
  const total = hoursWithInputs(imp);
  return total === 0 ? 0 : imp.n_no_rule / total;
}

/** Share of the hours with complete inputs in which a rule fired but the prediction was withheld (no reference level). */
export function withheldShare(imp: Counts): number {
  const total = hoursWithInputs(imp);
  return total === 0 ? 0 : withheldOf(imp) / total;
}

/** The period of the importance: "2025" when it is one calendar year (the end is exclusive), else "entre X y Y". */
export function importancePeriod(imp: Pick<RuleImportanceResponse, "period_from_utc" | "period_to_utc">, zone = "UTC"): string {
  const from = new Date(imp.period_from_utc);
  const last = new Date(new Date(imp.period_to_utc).getTime() - 1);
  if (from.getUTCFullYear() === last.getUTCFullYear()) return String(from.getUTCFullYear());
  const [a, b] = [formatDate(imp.period_from_utc, zone), formatDate(last.toISOString(), zone)];
  return tr(`entre ${a} y ${b}`, `between ${a} and ${b}`);
}

/**
 * Plain-language reading of one rule's numbers (the card's metrics row). A classifier: how many predictions it decides and
 * how often it is right when it does. The additive regression: the same share, the mean weight the rule has in the
 * estimate (an exact share of the weighted average) and the mean error of the predictions it decides.
 */
export function decideText(
  r: Pick<RuleImportance, "decided_share" | "accuracy" | "mae" | "mean_weight_share"> & Partial<Pick<RuleImportance, "top_contributor_share">>,
  regression: boolean,
  unit: string,
): { decides: string; outcome: string | null } {
  // contract v0.7: in a mixture of rules none decides alone; its figure is the share where it adds the most
  if (r.decided_share == null && r.top_contributor_share != null)
    return { decides: topShareText(r.top_contributor_share), outcome: r.top_contributor_share > 0 && r.accuracy != null ? hitsWhenTop(r.accuracy) : null };
  if (r.decided_share == null) return { decides: tr("en este modelo ninguna regla decide sola", "in this model no single rule decides"), outcome: null };
  if (r.decided_share === 0) return { decides: tr("no decide ninguna predicción", "decides no prediction"), outcome: null };
  const share = pct(r.decided_share);
  const decides = tr(`decide el ${share} de las predicciones`, `decides ${share} of the predictions`);
  const unchecked = tr("sin observaciones con las que comprobarlo", "no observations to check it against");
  if (regression) {
    const weight = r.mean_weight_share == null ? null : tr(`peso medio en la estimación: ${pct(r.mean_weight_share)}`, `mean weight in the estimate: ${pct(r.mean_weight_share)}`);
    const mae = r.mae == null ? null : `${sig3(r.mae)}${unit ? ` ${unit}` : ""}`;
    const err = mae === null ? unchecked : tr(`error medio ${mae}`, `mean error ${mae}`);
    return { decides, outcome: [weight, err].filter(Boolean).join(" · ") };
  }
  return { decides, outcome: r.accuracy == null ? unchecked : tr(`acierta el ${pct(r.accuracy)}`, `is right ${pct(r.accuracy)} of the time`) };
}

/** The same for one rule inside one zone (the zone's own share). */
export const zoneDecideText = (r: EntityRuleImportance, regression: boolean, unit: string) => decideText(r, regression, unit);

/**
 * How often the class a rule predicts occurs, to read the rule's hit rate against. Preferred: `observed_class_shares`
 * (contract v0.5.2), over the same predictions as the accuracy ("de los casos"). Fallback: the share over all the
 * observed hours of Resumen ("de las horas"), which covers other years. null when neither knows it.
 */
export function baseRate(
  imp: Pick<RuleImportanceResponse, "observed_class_shares"> | null,
  summaryShare: number | null,
  classLabel: string,
): { share: number; ofChecked: boolean } | null {
  const own = imp?.observed_class_shares?.[classLabel];
  if (typeof own === "number") return { share: own, ofChecked: true };
  return summaryShare === null ? null : { share: summaryShare, ofChecked: false };
}

/**
 * Entities with no prediction at any time of the published period: absent from `entities`, or with no rule deciding any
 * of their predictions (n_decided = 0). Empty when the importance covers no predictions at all (nothing to compare with).
 */
export function neverPredictedIds(
  imp: Pick<RuleImportanceResponse, "entities" | "n_predicted"> & Partial<Pick<RuleImportanceResponse, "measure">>,
  entityIds: Iterable<string>,
): Set<string> {
  const never = new Set<string>();
  if (imp.n_predicted === 0) return never;
  const mixture = imp.measure === "rule_mixture"; // v0.7: no rule decides, n_predicted alone says it was predicted
  const decided = new Set(imp.entities.filter((e) => e.n_predicted > 0 && (mixture || e.rules.some((r) => decidedShare(r) > 0))).map((e) => e.entity_id));
  for (const id of entityIds) if (!decided.has(id)) never.add(id);
  return never;
}
