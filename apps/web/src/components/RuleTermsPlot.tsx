import type { LinguisticVariable, RuleDefinition } from "../api/types";
import { tr } from "../i18n";
import { fmtNum } from "../lib/format";
import { labelWithUnit, useFeatureLabel, useNames } from "../lib/labels";
import { COLORS, isDrawn, vertices } from "./PartitionsPanel";

const W = 300;
const H = 88;
const M = { l: 6, r: 6, t: 24, b: 16 };

/**
 * The x range worth drawing: where the terms actually change. A domain that runs far past the last term (NO₂ up to 1100 µg/m³
 * with terms ending at 69) would squeeze every term into a sliver, so the range is the knots (the parameters that are not
 * the domain's own ends) with a margin, within the domain.
 */
export function viewRange(params: readonly number[], dom: [number, number] | null | undefined): [number, number] {
  const dLo = dom ? dom[0] : params.length ? Math.min(...params) : 0;
  const dHi = dom ? dom[1] : params.length ? Math.max(...params) : dLo + 1;
  const knots = params.filter((v) => v > dLo && v < dHi);
  if (knots.length === 0) return [dLo, dHi];
  const a = Math.min(...knots);
  const b = Math.max(...knots);
  const pad = (b - a || 1) * 0.12;
  return [Math.max(dLo, a - pad), Math.min(dHi, b + pad)];
}

/**
 * The membership functions of the variables a rule uses, one small plot per variable: every term of the variable as a
 * line, the one the rule uses drawn thick. The lines are the terms' published parameters; nothing is computed here.
 */
export function RuleTermsPlot({ rule, variables }: { rule: RuleDefinition; variables: readonly LinguisticVariable[] }) {
  const label = useFeatureLabel();
  const names = useNames();
  const features = [...new Set(rule.antecedents.map((a) => a.feature))];
  return (
    <div className="terms-plots" data-testid="rule-terms">
      {features.map((feature) => {
        const variable = variables.find((v) => v.feature === feature);
        if (!variable) return null;
        const used = rule.antecedents.find((a) => a.feature === feature)?.term ?? null;
        const drawn = variable.terms.filter(isDrawn);
        const dom = variable.domain as [number, number] | null | undefined;
        const xs = drawn.flatMap((t) => t.params);
        const [lo, hi] = viewRange(xs, dom);
        const X = (v: number) => M.l + ((Math.min(hi, Math.max(lo, v)) - lo) / (hi - lo || 1)) * (W - M.l - M.r);
        const Y = (m: number) => H - M.b - m * (H - M.t - M.b);
        const name = labelWithUnit(label(feature), variable.unit);
        return (
          <figure key={feature} className="terms-plot">
            <figcaption>{name}</figcaption>
            <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={tr(`Términos de ${name} entre ${fmtNum(lo)} y ${fmtNum(hi)}; la regla usa ${used ? names.phrase(feature, used) : "ninguno"}`, `Terms of ${name} between ${fmtNum(lo)} and ${fmtNum(hi)}; the rule uses ${used ? names.phrase(feature, used) : "none"}`)}>
              <line x1={M.l} x2={W - M.r} y1={Y(0)} y2={Y(0)} className="axis-line" />
              {variable.terms.map((t, i) => {
                if (!isDrawn(t)) return null;
                const vs = vertices(t.params);
                const color = COLORS[i % COLORS.length]!;
                return (
                  <g key={t.name}>
                    <polyline className={t.name === used ? "term term--rule" : "term"} style={{ stroke: color }} points={vs.map(([x, m]) => `${X(x)},${Y(m)}`).join(" ")} />
                    <text x={X((Math.max(t.params[1]!, lo) + Math.min(t.params[2]!, hi)) / 2)} y={Y(1) - 3 - (i % 2) * 10} textAnchor="middle" className="axis" style={{ fill: color, fontWeight: t.name === used ? 700 : 400, fontStyle: "italic" }}>
                      {names.term(feature, t.name)}
                    </text>
                  </g>
                );
              })}
              <text x={M.l} y={H - 3} className="axis">{fmtNum(lo)}</text>
              <text x={W - M.r} y={H - 3} textAnchor="end" className="axis">{fmtNum(hi)}</text>
            </svg>
          </figure>
        );
      })}
    </div>
  );
}
