import type { LinguisticTerm, LinguisticVariable, RuleDefinition } from "../api/types";
import { tr } from "../i18n";
import { fmtNum } from "../lib/format";
import { boundedSumPoints, isExtra, termMembership, termsOf } from "../lib/conditions";
import { labelWithUnit, useFeatureLabel, useNames } from "../lib/labels";
import { isDrawn } from "./PartitionsPanel";

const W = 320;
const H = 96;
const M = { l: 8, r: 8, t: 30, b: 18 };

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

/** A term's line inside the drawn range: its membership at the range ends and at its own knots in between, without the
 * runs at 0 before and after it (they would lie on the axis). The line is cut at the range, so no edge is drawn as a wall. */
function termPoints(t: LinguisticTerm, lo: number, hi: number): [number, number][] {
  const xs = [...new Set([lo, ...t.params.filter((v) => v > lo && v < hi), hi])].sort((a, b) => a - b);
  return trimZeros(xs.map((x): [number, number] => [x, termMembership(t, x)]));
}

/** A line without its runs at 0 at either end. */
function trimZeros(points: readonly [number, number][]): [number, number][] {
  const pts = [...points];
  while (pts.length > 2 && pts[0]![1] === 0 && pts[1]![1] === 0) pts.shift();
  while (pts.length > 2 && pts[pts.length - 1]![1] === 0 && pts[pts.length - 2]![1] === 0) pts.pop();
  return pts;
}

/** Two significant digits for the axis (`-0,00096`, not `-0,0009633`). */
const axisNum = (v: number): string => fmtNum(Number(v.toPrecision(2)));

/**
 * The membership functions of the variables a rule uses, one small plot per variable: every term of the variable as a
 * grey line, and what the rule asks for (its term, or the bounded sum of the terms an ordinal or compound condition
 * covers) as a filled shape in the accent colour, named above the plot. The lines are the terms' published parameters.
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
        const condition = rule.antecedents.find((a) => a.feature === feature);
        // an ordinal or compound condition (v0.8) is drawn as the bounded sum of the terms it covers, not as one of them
        const extra = condition && isExtra(condition) ? condition : null;
        const used = extra ? null : (condition?.term ?? null);
        const covered = new Set(extra ? termsOf(extra) : used ? [used] : []);
        const drawn = variable.terms.filter(isDrawn);
        const dom = variable.domain as [number, number] | null | undefined;
        const [lo, hi] = viewRange(drawn.flatMap((t) => t.params), dom);
        const X = (v: number) => M.l + ((Math.min(hi, Math.max(lo, v)) - lo) / (hi - lo || 1)) * (W - M.l - M.r);
        const Y = (m: number) => H - M.b - m * (H - M.t - M.b);
        const line = (pts: readonly [number, number][]) => pts.map(([x, m]) => `${X(x).toFixed(1)},${Y(m).toFixed(1)}`).join(" ");
        const area = (pts: readonly [number, number][]) => `M ${X(pts[0]![0]).toFixed(1)},${Y(0)} L ${line(pts).replace(/ /g, " L ")} L ${X(pts[pts.length - 1]![0]).toFixed(1)},${Y(0)} Z`;
        const ruleShape = extra
          ? trimZeros(boundedSumPoints(variable.terms.filter((t) => covered.has(t.name)), lo, hi))
          : (() => { const t = drawn.find((d) => d.name === used); return t ? termPoints(t, lo, hi) : null; })();
        // term names on one row above the plateaus; a name that would touch the previous one goes up a row
        const placed: { x: number; w: number; row: number }[] = [];
        const labels = drawn.map((t) => {
          const text = names.term(feature, t.name);
          const w = text.length * 6;
          const centre = X((Math.max(t.params[1]!, lo) + Math.min(t.params[2]!, hi)) / 2);
          const x = Math.min(W - M.r - w / 2, Math.max(M.l + w / 2, centre));
          const prev = placed[placed.length - 1];
          const row = prev && prev.row === 0 && x - w / 2 < prev.x + prev.w / 2 + 6 ? 1 : 0;
          placed.push({ x, w, row });
          return { t, text, x, row };
        });
        const name = labelWithUnit(label(feature), variable.unit);
        const asked = condition ? (extra ? names.label(feature, extra) : names.term(feature, condition.term)) : null;
        return (
          <figure key={feature} className="terms-plot">
            <figcaption>
              {name}
              {asked && (
                <span className="terms-plot-asked">
                  <span className="terms-plot-swatch" aria-hidden="true" />
                  <em>{asked}</em>
                </span>
              )}
            </figcaption>
            <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={tr(`Términos de ${name} entre ${fmtNum(lo)} y ${fmtNum(hi)}; la regla usa ${condition ? names.phrase(feature, condition.term, condition) : "ninguno"}`, `Terms of ${name} between ${fmtNum(lo)} and ${fmtNum(hi)}; the rule uses ${condition ? names.phrase(feature, condition.term, condition) : "none"}`)}>
              {ruleShape && ruleShape.length > 1 && <path className="term-area" d={area(ruleShape)} />}
              <line x1={M.l} x2={W - M.r} y1={Y(0)} y2={Y(0)} className="axis-line" />
              {lo < 0 && hi > 0 && <line x1={X(0)} x2={X(0)} y1={Y(0)} y2={Y(0) + 3} className="axis-line" />}
              {drawn.map((t) => (
                <polyline key={t.name} className={t.name === used ? "term term--rule" : "term"} points={line(termPoints(t, lo, hi))} />
              ))}
              {extra && ruleShape && <polyline className="term term--rule term--sum" data-condition={extra.operator} points={line(ruleShape)} />}
              {labels.map(({ t, text, x, row }) => (
                <text key={t.name} x={x} y={Y(1) - 4 - row * 11} textAnchor="middle" className={covered.has(t.name) ? "term-label term-label--rule" : "term-label"}>
                  {text}
                </text>
              ))}
              <text x={M.l} y={H - 3} className="axis">{axisNum(lo)}</text>
              {lo < 0 && hi > 0 && X(0) - M.l > 40 && W - M.r - X(0) > 40 && <text x={X(0)} y={H - 3} textAnchor="middle" className="axis">0</text>}
              <text x={W - M.r} y={H - 3} textAnchor="end" className="axis">{axisNum(hi)}</text>
            </svg>
          </figure>
        );
      })}
    </div>
  );
}
