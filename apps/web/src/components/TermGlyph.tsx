import type { LinguisticVariable } from "../api/types";
import { boundedSumPoints, isExtra, termsOf, type CondSpec } from "../lib/conditions";
import { isDrawn, vertices } from "./PartitionsPanel";
import { viewRange } from "./RuleTermsPlot";

/** The fill of a term that is not a class of the scheme: the sienna data colour (DESIGN.md › Atlas additions). */
export const ACCENT = "#a05339";

/** Glyph size; with many columns (Water: 6) the compact one keeps the whole row in view on a desktop. */
export const GLYPH = { wide: [84, 28], compact: [60, 24] } as const;

/** The x range of a column: where the variable's terms change (the same as the terms plot), so every cell of a column shares it. */
export function columnRange(v: LinguisticVariable | undefined): [number, number] | null {
  const drawn = v?.terms.filter(isDrawn) ?? [];
  if (!v || drawn.length === 0) return null;
  return viewRange(drawn.flatMap((t) => t.params), v.domain as [number, number] | null | undefined);
}

/**
 * The variable's range in miniature: every term as a hairline, the term the rule asks for filled (in its class colour
 * when the term is a class of the scheme, else the accent). Drawn from the published parameters only. A term of zero
 * width (a detection limit) is a 3-px bar so it stays visible. An ordinal or compound condition (v0.8, `condition`) fills
 * the bounded sum of the terms it covers instead of one term.
 */
export function TermGlyph({ variable, term, range, fill, compact = false, condition }: { variable: LinguisticVariable; term: string | null; range: [number, number]; fill: string; compact?: boolean; condition?: CondSpec }) {
  const [GW, GH] = GLYPH[compact ? "compact" : "wide"];
  const [lo, hi] = range;
  const X = (v: number) => 2 + ((Math.min(hi, Math.max(lo, v)) - lo) / (hi - lo || 1)) * (GW - 4);
  const Y = (m: number) => GH - 1.5 - m * (GH - 5);
  const pts = (p: readonly number[]) => vertices(p).map(([x, m]) => `${X(x)},${Y(m)}`).join(" ");
  const extra = condition && isExtra(condition) ? condition : null;
  const used = extra ? undefined : variable.terms.find((t) => t.name === term && isDrawn(t));
  const covered = extra ? variable.terms.filter((t) => termsOf(extra).includes(t.name)) : [];
  const sum = covered.length > 0 ? boundedSumPoints(covered, lo, hi) : [];
  const thin = used ? X(used.params[3]!) - X(used.params[0]!) < 3 : false;
  return (
    <svg className="rmx-glyph" viewBox={`0 0 ${GW} ${GH}`} width={GW} height={GH} aria-hidden="true" focusable="false">
      <line x1={0} x2={GW} y1={Y(0)} y2={Y(0)} className="rmx-glyph-base" />
      {variable.terms.filter(isDrawn).map((t) => (!extra && t.name === term ? null : <polyline key={t.name} points={pts(t.params)} className="rmx-glyph-term" />))}
      {sum.length > 0 && <polygon points={`${X(sum[0]![0])},${Y(0)} ${sum.map(([x, m]) => `${X(x)},${Y(m)}`).join(" ")} ${X(sum[sum.length - 1]![0])},${Y(0)}`} className="rmx-glyph-used" style={{ fill }} />}
      {used &&
        (thin ? (
          <rect x={X(used.params[0]!) - 1.5} y={Y(1)} width={3} height={Y(0) - Y(1)} rx={1} className="rmx-glyph-used" style={{ fill }} />
        ) : (
          <polygon points={pts(used.params)} className="rmx-glyph-used" style={{ fill }} />
        ))}
    </svg>
  );
}
