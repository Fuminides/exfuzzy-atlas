import { tr } from "../i18n";
import { dec, pct, withUnit } from "../lib/format";

interface Props {
  quantiles: Record<string, number> | null;
  unit: string;
}

const W = 360;
const H = 56;
const PAD = 10;

/** Median and spread of a numeric variable: p10–p90 whisker, p25–p75 box and the median tick, with the numbers written out. */
export function QuantileStrip({ quantiles: q, unit }: Props) {
  if (!q || q.p50 === undefined) return <p className="muted">{tr("Sin observaciones.", "No observations.")}</p>;
  const lo = q.p10 ?? q.p25 ?? q.p50;
  const hi = q.p90 ?? q.p75 ?? q.p50;
  const X = (v: number) => PAD + ((v - lo) / (hi - lo || 1)) * (W - 2 * PAD);
  const digits = hi - lo < 10 ? 1 : 0;
  const [median, a, b] = [withUnit(q.p50, unit, digits), dec(q.p25 ?? q.p50, digits), withUnit(q.p75 ?? q.p50, unit, digits)];
  const text = tr(`mediana ${median}; la mitad de los valores entre ${a} y ${b}`, `median ${median}; half of the values between ${a} and ${b}`);
  return (
    <figure className="quantile-strip">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={text}>
        <line x1={X(lo)} x2={X(hi)} y1={22} y2={22} className="whisker" />
        {q.p25 !== undefined && q.p75 !== undefined && <rect x={X(q.p25)} y={10} width={Math.max(2, X(q.p75) - X(q.p25))} height={24} className="iqr-box" />}
        <line x1={X(q.p50)} x2={X(q.p50)} y1={8} y2={36} className="iqr-median" />
        <text x={X(lo)} y={52} textAnchor="middle" className="axis">{dec(lo, digits)}</text>
        <text x={X(q.p50)} y={52} textAnchor="middle" className="axis axis--strong">{dec(q.p50, digits)}</text>
        <text x={X(hi)} y={52} textAnchor="middle" className="axis">{dec(hi, digits)}</text>
      </svg>
      <figcaption>
        <strong>{tr(`Mediana ${median}`, `Median ${median}`)}</strong>
        {q.p25 !== undefined && q.p75 !== undefined && tr(` · la mitad de los valores entre ${dec(q.p25, digits)} y ${withUnit(q.p75, unit, digits)}`, ` · half of the values between ${dec(q.p25, digits)} and ${withUnit(q.p75, unit, digits)}`)}
        {q.p10 !== undefined && q.p90 !== undefined && tr(` · el ${pct(0.8)} entre ${dec(q.p10, digits)} y ${withUnit(q.p90, unit, digits)}`, ` · ${pct(0.8)} between ${dec(q.p10, digits)} and ${withUnit(q.p90, unit, digits)}`)}
        {q.mean !== undefined && tr(` · media ${withUnit(q.mean, unit, digits)}`, ` · mean ${withUnit(q.mean, unit, digits)}`)}
      </figcaption>
    </figure>
  );
}
