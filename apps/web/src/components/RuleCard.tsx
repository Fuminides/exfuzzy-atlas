import { useState } from "react";
import type { LinguisticVariable, RuleDefinition, RuleImportance, TargetScheme } from "../api/types";
import { tr } from "../i18n";
import { pct } from "../lib/format";
import { decideText } from "../lib/importance";
import { ruleSentence, useFeatureLabel, useNames } from "../lib/labels";
import { count } from "../lib/summary";
import { RuleSentenceView } from "./RuleSentenceView";
import { RuleTermsPlot } from "./RuleTermsPlot";
import { ClassWeights } from "./ClassWeights";
import { decisiveText, leadShare } from "../lib/mixture";

interface Props {
  rule: RuleDefinition;
  /** null while the importance is not published: the card then shows the sentence only. */
  importance: RuleImportance | null;
  regression: boolean;
  unit: string;
  scheme: TargetScheme | null;
  variables: readonly LinguisticVariable[];
  /** 1-based position in the ranking. */
  rank: number | null;
  /** How often the class this rule predicts occurs (`ofChecked`: among the same predictions as the accuracy; else among all the observed hours of Resumen); null when unknown or not a classifier. */
  baseRate: { share: number; ofChecked: boolean } | null;
  selected: boolean;
  /** Clicking the card selects the rule (the map then shows where it decides); clicking it again clears it. */
  onSelect: (ruleId: string) => void;
  /** v0.7 rule mixture: the common scale of the weight bars (the model's largest |centred weight|); absent otherwise. */
  weightScale?: number;
}

/** One rule: its sentence, one row of numbers (how much it decides, how often it is right) and its terms on demand. */
export function RuleCard({ rule, importance, regression, unit, scheme, variables, rank, baseRate, selected, onSelect, weightScale }: Props) {
  const label = useFeatureLabel();
  const names = useNames();
  const [open, setOpen] = useState(false);
  const text = importance ? decideText(importance, regression, unit) : null;
  const className = rule.consequent.type === "class" ? names.cls(rule.consequent.term ?? "") : null;
  // v0.7 rule mixture: no rule decides; the rule's predictions are those where it adds the most (n_top)
  const mixture = rule.class_weights_centred != null && scheme !== null;
  const nDecided = (mixture ? importance?.n_top : importance?.n_decided) ?? 0;
  const checkedShare = importance && nDecided > 0 ? importance.n_checked / nDecided : null;
  const note =
    importance && checkedShare !== null
      ? mixture
        ? tr(`Se pudo comprobar con ${count(importance.n_checked)} de las ${count(nDecided)} predicciones en las que es la que más suma (${pct(checkedShare)}).`, `Checked against ${count(importance.n_checked)} of the ${count(nDecided)} predictions in which it adds the most (${pct(checkedShare)}).`)
        : tr(
            `Se pudo comprobar con ${count(importance.n_checked)} de las ${count(nDecided)} predicciones que decide (${pct(checkedShare)}).`,
            `Checked against ${count(importance.n_checked)} of the ${count(nDecided)} predictions it decides (${pct(checkedShare)}).`,
          )
      : null;
  const share = importance ? (importance.decided_share ?? importance.top_contributor_share ?? null) : null;
  const decisive = mixture && importance ? decisiveText(importance.decisive_share) : null;
  return (
    <li className={`rule-card${selected ? " rule-card--selected" : ""}`} data-rule={rule.rule_id} aria-current={selected ? "true" : undefined}>
      <button type="button" className="rule-card-hit" aria-pressed={selected} aria-label={selected ? tr(`Quitar del mapa la regla ${rule.rule_id}`, `Remove rule ${rule.rule_id} from the map`) : tr(`Mostrar en el mapa la regla ${rule.rule_id}`, `Show rule ${rule.rule_id} on the map`)} title={note ?? undefined} onClick={() => onSelect(rule.rule_id)} />
      <div className="rule-card-top">
        <span className="rule-badge" title={tr(`Regla ${rule.rule_id}`, `Rule ${rule.rule_id}`)}>{rule.rule_id}</span>
        {rank !== null && <span className="muted small" title={mixture ? tr("Posición por predicciones en las que es la que más suma", "Rank by the predictions in which it adds the most") : tr("Posición por predicciones que decide", "Rank by the predictions it decides")}>{tr(`n.º ${rank}`, `no. ${rank}`)}</span>}
        {rule.duplicate_of && <span className="badge-dup">{tr("mismas condiciones que", "same conditions as")} {rule.duplicate_of}</span>}
        {selected && <span className="rule-card-on">{tr("en el mapa", "on the map")}</span>}
        {importance && share != null && (
          <span className="rule-share" title={mixture ? tr("Parte de las predicciones en las que es la que más suma", "Share of the predictions in which it adds the most") : tr("Parte de las predicciones que decide", "Share of the predictions it decides")}>
            <span className="rule-bar" aria-hidden="true">
              <span style={{ width: `${Math.min(1, leadShare(importance)) * 100}%` }} />
            </span>
            <span className="rule-share-value" aria-hidden="true">{pct(leadShare(importance))}</span>
          </span>
        )}
      </div>
      <RuleSentenceView sentence={ruleSentence(rule, label, scheme, names)} />
      {mixture && rule.class_weights_centred && (
        <ClassWeights
          values={rule.class_weights_centred}
          scheme={scheme!}
          scale={weightScale ?? 0}
          strongest={rule.strongest_class ?? null}
          label={tr(`Pesos centrados de ${rule.rule_id} por categoría`, `Centred weights of ${rule.rule_id} by category`)}
        />
      )}
      {importance && text ? (
        <p className="rule-metrics" data-testid="rule-metrics">
          <span className="rule-metric" data-stat="decides">{text.decides}</span>
          {text.outcome && (
            <>
              <span className="rule-metric-sep" aria-hidden="true"> · </span>
              <span className="rule-metric" data-stat="hits">{text.outcome}</span>
            </>
          )}
          {decisive && (
            <>
              <span className="rule-metric-sep" aria-hidden="true"> · </span>
              <span className="rule-metric" data-stat="decisive">{decisive}</span>
            </>
          )}
          {!mixture && !regression && importance.accuracy != null && baseRate !== null && className && (
            <span className="muted" data-testid="base-rate">
              {" · "}
              {baseRate.ofChecked
                ? tr(`en general, esa clase se observa en el ${pct(baseRate.share)} de los casos`, `overall, that class is observed in ${pct(baseRate.share)} of the cases`)
                : tr(`en general, esa clase se observa en el ${pct(baseRate.share)} de las horas`, `overall, that class is observed in ${pct(baseRate.share)} of the hours`)}
            </span>
          )}
        </p>
      ) : (
        <p className="muted small">{mixture ? tr("Todavía no hay cifras de esta regla.", "There are no figures yet for this rule.") : tr("Todavía no hay cifras de lo que decide esta regla.", "There are no figures yet for what this rule decides.")}</p>
      )}
      {note && checkedShare !== null && checkedShare < 0.9 && <p className="rule-note muted" data-testid="checked-note">{note}</p>}
      <button type="button" className="link rule-terms-toggle" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {open ? tr("Ocultar términos", "Hide terms") : tr("Ver términos", "Show terms")}
      </button>
      {open && <RuleTermsPlot rule={rule} variables={variables} />}
    </li>
  );
}
