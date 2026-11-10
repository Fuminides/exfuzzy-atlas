import type { RuleDefinition, TargetScheme } from "../api/types";
import { tr } from "../i18n";
import { classColor, NO_COLOR, weightLabel, weightTitle } from "../lib/classifier";
import { fmtNum, unitLabel } from "../lib/format";
import { ruleMetrics } from "../lib/ruleMetrics";
import { ClassChip } from "./ClassChip";
import { ClassWeights, WeightKey } from "./ClassWeights";
import { ruleSentence, useFeatureLabel, useNames } from "../lib/labels";
import { RuleSentenceView } from "./RuleSentenceView";

interface Props {
  rule: RuleDefinition;
  onVariable: (feature: string) => void;
  /** Classifier: colours of the class consequents, and how the rule weight is called. */
  scheme?: TargetScheme | null;
  weighting?: Parameters<typeof weightTitle>[0];
  /** v0.7 rule mixture: the common scale of the weight bars (the model's largest |centred weight|). */
  weightScale?: number;
}

/** The selected rule: text, duplicate badge, its published `metrics` (labelled by name) and a way into its partitions. */
export function RuleDetail({ rule, onVariable, scheme, weighting, weightScale = 0 }: Props) {
  const label = useFeatureLabel();
  const names = useNames();
  const metrics = ruleMetrics(rule);
  return (
    <section className="rule-detail" aria-label={tr(`Regla ${rule.rule_id}`, `Rule ${rule.rule_id}`)}>
      <h2>
        {tr(`Regla ${rule.rule_id}`, `Rule ${rule.rule_id}`)}
        {rule.duplicate_of && <span className="badge-dup">{tr(`mismas condiciones que ${rule.duplicate_of} (dispara igual)`, `same conditions as ${rule.duplicate_of} (fires the same)`)}</span>}
      </h2>
      <RuleSentenceView sentence={ruleSentence(rule, label, scheme, names)} />
      {rule.class_weights_centred && scheme && (
        <div data-testid="rule-weights">
          <p className="rule-class">{tr("Lo que suma a cada categoría cuando se cumple del todo (peso centrado):", "What it adds to each category when it fully holds (centred weight):")}</p>
          <ClassWeights values={rule.class_weights_centred} scheme={scheme} scale={weightScale} strongest={rule.strongest_class ?? null} label={tr(`Pesos centrados de ${rule.rule_id} por categoría`, `Centred weights of ${rule.rule_id} by category`)} />
          <WeightKey />
        </div>
      )}
      {!rule.class_weights_centred && rule.consequent.type === "class" && rule.consequent.term != null && (
        <p className="rule-class" data-testid="rule-consequent">
          {tr("Si se cumple, vota la categoría", "If it holds, it votes for the category")}{" "}
          <ClassChip label={rule.consequent.term} color={scheme ? classColor(scheme, rule.consequent.term) : NO_COLOR} />
          {rule.weight != null && weighting !== "none" && (
            <>
              {" "}
              · <span title={weightTitle(weighting)}>{weightLabel()}</span>: <strong data-raw={String(rule.weight)}>{fmtNum(rule.weight)}</strong>
            </>
          )}
        </p>
      )}
      {rule.consequent.type !== "class" && rule.consequent.value != null && (
        <p className="rule-value" data-testid="rule-consequent">
          {tr("Consecuente (constante de la regla):", "Consequent (the rule's constant):")}{" "}
          <strong data-raw={String(rule.consequent.value)}>
            {fmtNum(rule.consequent.value)}
            {rule.consequent.unit ? ` ${unitLabel(rule.consequent.unit)}` : ""}
          </strong>
          {tr(". No es el valor de las muestras que cubre. Las reglas aditivas se leen juntas, y puede haber consecuentes repetidos o que se compensen.", ". It isn't the value of the samples it covers. Additive rules are read together, and consequents can repeat or offset each other.")}
        </p>
      )}
      <p>
        {tr("Particiones de sus variables:", "Partitions of its variables:")}{" "}
        {[...new Set(rule.antecedents.map((a) => a.feature))].map((f) => (
          <button key={f} type="button" className="link" onClick={() => onVariable(f)} aria-label={tr(`Ver particiones de ${label(f)}`, `Show partitions of ${label(f)}`)}>
            {label(f)}
          </button>
        ))}
      </p>
      {metrics.length > 0 && (
        <dl className="rule-metrics-list" aria-label={tr(`Métricas de ${rule.rule_id}`, `Metrics for ${rule.rule_id}`)}>
          {metrics.map((m) => (
            <div key={m.key}>
              <dt>
                <span title={m.key}>{m.label}</span>
              </dt>
              <dd>{m.text}</dd>
            </div>
          ))}
        </dl>
      )}
      <p className="muted note">
        {tr("Métricas tal como las publica el modelo para esta regla.", "Metrics as the model publishes them for this rule.")}
        {rule.class_weights_centred && tr(" En este modelo ninguna regla decide sola: las que se cumplen suman su apoyo a cada categoría.", " In this model no single rule decides: the rules that hold add up their support for each category.")}
        {rule.weight != null && weighting !== "none" && tr(" El peso pondera el voto de la regla (grado de asociación = activación × peso).", " The weight scales the rule's vote (association degree = activation × weight).")}
      </p>
    </section>
  );
}
