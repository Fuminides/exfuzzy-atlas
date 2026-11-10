import type { ModelRules, RuleDefinition, RuleImportanceResponse } from "../api/types";
import { tr } from "../i18n";
import { weightLabel, weightTitle } from "./classifier";
import { fmtNum, pct, sig3 } from "./format";
import { isRegressionImportance } from "./importance";
import { isMixtureImportance } from "./mixture";

export interface RuleFigure {
  key: "decided" | "hits" | "weight_share" | "error" | "weight" | "top" | "decisive";
  label: string;
  value: string;
  /** Longer wording for a `title`. */
  title?: string;
}

export interface FigureSource {
  rule: RuleDefinition;
  /** null while the importance is not published: only the rule's own weight can be shown. */
  importance: RuleImportanceResponse | null;
  weighting: ModelRules["inference"]["rule_weighting"] | undefined;
  unit: string;
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/**
 * The published figures of one rule, as the hovercard lists them: the share of the predictions it decides and how often
 * it is right (classifier) or its mean weight in the estimate and the mean error (regression), from the importance; and
 * its weight when the model is weighted. Nothing is computed here.
 *
 * A rule of a mixture (contract v0.7) decides nothing on its own: its figures are the share of the predictions in which it
 * adds the most to the predicted category, how often those are right, and the share whose category would change without it.
 */
export function ruleFigures({ rule, importance, weighting, unit }: FigureSource): RuleFigure[] {
  const rows: RuleFigure[] = [];
  const r = importance?.rules.find((x) => x.rule_id === rule.rule_id);
  if (importance && r && isMixtureImportance(importance)) {
    const top = r.top_contributor_share ?? 0;
    rows.push({ key: "top", label: tr("Es la que más suma", "Adds the most"), value: pct(top), title: tr("Parte de las predicciones en las que es la regla que más suma a la categoría prevista", "Share of the predictions in which it is the rule that adds the most to the predicted category") });
    if (top > 0) rows.push({ key: "hits", label: tr("Aciertan esas", "Those are right"), value: r.accuracy == null ? tr("sin observaciones con las que comprobarlo", "no observations to check it against") : pct(r.accuracy) });
    if (r.decisive_share != null) rows.push({ key: "decisive", label: tr("Sin ella cambiaría", "Without it, would change"), value: pct(r.decisive_share), title: tr("Parte de las predicciones cuya categoría cambiaría sin esta regla", "Share of the predictions whose category would change without this rule") });
    return rows;
  }
  // a rule of a mixture (contract v0.7) decides nothing on its own: decided_share is null and these figures do not apply
  const decided = r?.decided_share;
  if (importance && r && decided != null) {
    const unchecked = tr("sin observaciones con las que comprobarlo", "no observations to check it against");
    rows.push({ key: "decided", label: tr("Predicciones que decide", "Predictions it decides"), value: pct(decided) });
    if (isRegressionImportance(importance)) {
      if (r.mean_weight_share != null) rows.push({ key: "weight_share", label: tr("Peso medio en la estimación", "Mean weight in the estimate"), value: pct(r.mean_weight_share) });
      if (decided > 0) rows.push({ key: "error", label: tr("Error medio", "Mean error"), value: r.mae == null ? unchecked : `${sig3(r.mae)}${unit ? ` ${unit}` : ""}` });
    } else if (decided > 0) {
      rows.push({ key: "hits", label: tr("Acierta", "Is right"), value: r.accuracy == null ? unchecked : pct(r.accuracy) });
    }
  }
  if (rule.weight != null && weighting !== "none") rows.push({ key: "weight", label: cap(weightLabel()), value: fmtNum(rule.weight), title: weightTitle(weighting) });
  return rows;
}
