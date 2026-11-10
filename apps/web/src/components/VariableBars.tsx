import type { LinguisticVariable, VariableImportance } from "../api/types";
import { tr } from "../i18n";
import { pct } from "../lib/format";
import { leadShare, variableShareNote } from "../lib/mixture";
import { describeVariable, labelWithUnit } from "../lib/labels";

interface Props {
  variables: readonly VariableImportance[];
  info: readonly LinguisticVariable[];
  label: (feature: string) => string;
  regression: boolean;
  /** v0.7 rule mixture: the share is of the predictions whose top rule (the one that adds the most) uses the input. */
  mixture?: boolean;
  /** Side column: label and value on one line, the bar under them. */
  compact?: boolean;
}

/**
 * Horizontal bars: the share of the model's decisions made by rules that use each input, most used first (a mixture of
 * rules, v0.7: the share of the predictions whose top rule uses it).
 */
export function VariableBars({ variables, info, label, regression, mixture = false, compact = false }: Props) {
  const unitOf = new Map(info.map((v) => [v.feature, v.unit]));
  const descriptionOf = new Map(info.flatMap((v) => { const d = describeVariable(v); return d ? [[v.feature, d] as const] : []; }));
  const sorted = [...variables].sort((a, b) => leadShare(b) - leadShare(a) || a.feature.localeCompare(b.feature));
  return (
    <ul className={`hbars${compact ? " hbars--compact" : ""}`} aria-label={
        mixture
          ? variableShareNote()
          : regression
          ? tr("Cuota media del promedio que aportan las reglas que usan cada variable", "Mean share of the average carried by the rules that use each variable")
          : tr("Parte de las predicciones decididas por reglas que usan cada variable", "Share of the predictions decided by rules that use each variable")
      }>
      {sorted.map((v) => (
        <li key={v.feature} data-feature={v.feature} data-share={String(leadShare(v))}>
          <span className="hbar-label" title={descriptionOf.get(v.feature)}>{labelWithUnit(label(v.feature), unitOf.get(v.feature))}</span>
          <span className="hbar-track" aria-hidden="true">
            <span className="hbar-fill" style={{ width: `${Math.min(1, leadShare(v)) * 100}%` }} />
          </span>
          <span className="hbar-value num">{pct(leadShare(v))}</span>
          <span className="hbar-aside muted small">
            {v.n_rules === 1 ? tr("1 regla", "1 rule") : tr(`${v.n_rules} reglas`, `${v.n_rules} rules`)}
          </span>
        </li>
      ))}
    </ul>
  );
}
