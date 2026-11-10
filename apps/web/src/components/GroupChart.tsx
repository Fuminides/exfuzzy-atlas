import { useId } from "react";
import type { DistributionRow } from "../api/types";
import { tr } from "../i18n";
import { dec, pct, withUnit } from "../lib/format";
import { byKey, GROUP_KEYS, groupTitle, keyLabel, LOW_N, count, type CalendarGroup } from "../lib/summary";
import { Card } from "./Card";

interface Props {
  group: CalendarGroup;
  rows: readonly DistributionRow[];
  /** Classified variable: the value drawn is the share of observations in the classes from `from` on. */
  classified: { from: number; label: string } | null;
  /** Numeric variable: unit of the quantiles. */
  unit: string;
}

const W = 460;
const H = 190;
const M = { l: 46, r: 8, t: 10, b: 24 };

/** A "nice" top for a 0..max axis. */
function niceTop(max: number, steps = [1, 2, 2.5, 5, 10]): number {
  if (max <= 0) return 1;
  const exp = Math.pow(10, Math.floor(Math.log10(max)));
  for (const s of steps) if (s * exp >= max) return s * exp;
  return 10 * exp;
}

interface Point {
  key: string;
  label: string;
  n: number;
  /** Classified: the share. Numeric: the median. null = no data. */
  value: number | null;
  lo: number | null;
  hi: number | null;
}

/**
 * The distribution by year, month, hour or weekday. Classified variables draw the share of observations in the worse classes;
 * numeric ones the median with the middle half of the values. A key with no observations is a labelled gap, never a zero;
 * a key with few observations is drawn pale. The table under the chart has every number.
 */
export function GroupChart({ group, rows, classified, unit }: Props) {
  const id = useId();
  const map = byKey(rows);
  const keys = group === "year" ? [...map.keys()].sort() : GROUP_KEYS[group];
  const points: Point[] = keys.map((key) => {
    const r = map.get(key);
    const n = r?.n ?? 0;
    if (!r || n === 0) return { key, label: keyLabel(group, key), n: 0, value: null, lo: null, hi: null };
    if (classified) {
      const v = (r.shares ?? []).slice(classified.from).reduce((a, b) => a + b, 0);
      return { key, label: keyLabel(group, key), n, value: v, lo: null, hi: null };
    }
    return { key, label: keyLabel(group, key), n, value: r.quantiles?.p50 ?? null, lo: r.quantiles?.p25 ?? null, hi: r.quantiles?.p75 ?? null };
  });
  const present = points.filter((p) => p.value !== null);
  const title = groupTitle(group);
  const sentence = classified
    ? tr(`Horas en «${classified.label}»`, `Hours in “${classified.label}”`)
    : tr(`Mediana y rango intercuartílico${unit ? ` (${unit})` : ""}`, `Median and interquartile range${unit ? ` (${unit})` : ""}`);
  if (keys.length === 0 || present.length === 0) {
    return (
      <Card title={title} level={3} className="chart-card">
        <p className="muted">{tr("Sin datos para esta agrupación.", "No data for this grouping.")}</p>
      </Card>
    );
  }
  const top = classified ? niceTop(Math.max(...present.map((p) => p.value!))) : niceTop(Math.max(...present.map((p) => p.hi ?? p.value!)));
  const bottom = !classified ? Math.min(0, ...present.map((p) => p.lo ?? p.value!)) : 0;
  const inner = W - M.l - M.r;
  const step = inner / keys.length;
  const Y = (v: number) => M.t + (1 - (v - bottom) / (top - bottom || 1)) * (H - M.t - M.b);
  const fmtV = (v: number) => (classified ? pct(v) : withUnit(v, unit));
  const fmtTick = (v: number) => (classified ? pct(v) : dec(v, top < 10 ? 1 : 0));
  const ticks = [bottom, bottom + (top - bottom) / 2, top];
  const thinLabels = keys.length > 12 ? 3 : 1;
  const aria = tr(`${title}: ${sentence}. ${present.length} de ${keys.length} grupos con datos.`, `${title}: ${sentence}. ${present.length} of ${keys.length} groups with data.`);
  const noData = tr("sin datos", "no data");

  return (
    <Card title={title} subtitle={sentence} level={3} className="chart-card">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={aria} className="group-chart" data-group={group}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={M.l} x2={W - M.r} y1={Y(t)} y2={Y(t)} className="grid" />
            <text x={M.l - 6} y={Y(t) + 3} textAnchor="end" className="axis">
              {fmtTick(t)}
            </text>
          </g>
        ))}
        {points.map((p, i) => {
          const x = M.l + i * step;
          const w = Math.min(24, Math.max(2, step * 0.62)); // thin marks (dataviz): at most 24 px, the rest of the band is air
          const cx = x + step / 2;
          const low = p.n > 0 && p.n < LOW_N;
          return (
            <g key={p.key} data-key={p.key} data-n={p.n}>
              {p.value === null ? (
                <g>
                  <rect x={cx - w / 2} y={Y(bottom) - 6} width={w} height={6} className="gap-mark" />
                  <title>{`${p.label}: ${noData}`}</title>
                </g>
              ) : classified ? (
                <rect x={cx - w / 2} y={Y(p.value)} width={w} height={Math.max(1, Y(bottom) - Y(p.value))} className={`bar${low ? " bar--low" : ""}`} data-value={String(p.value)}>
                  <title>{`${p.label}: ${fmtV(p.value)} (n = ${count(p.n)})`}</title>
                </rect>
              ) : (
                <g className={low ? "iqr iqr--low" : "iqr"} data-value={String(p.value)}>
                  {p.lo !== null && p.hi !== null && <rect x={cx - w / 2} y={Y(p.hi)} width={w} height={Math.max(1, Y(p.lo) - Y(p.hi))} className="iqr-box" />}
                  <line x1={cx - w / 2} x2={cx + w / 2} y1={Y(p.value)} y2={Y(p.value)} className="iqr-median" />
                  <title>{tr(`${p.label}: mediana ${fmtV(p.value)} (n = ${count(p.n)})`, `${p.label}: median ${fmtV(p.value)} (n = ${count(p.n)})`)}</title>
                </g>
              )}
              {(i % thinLabels === 0 || keys.length <= 12) && (
                <text x={cx} y={H - 8} textAnchor="middle" className="axis">
                  {p.label}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      {points.some((p) => p.value === null) && (
        <p className="muted small">{tr("Las marcas grises sin barra son grupos sin observaciones.", "Grey marks with no bar are groups with no observations.")}</p>
      )}
      <details className="more-info">
        <summary>{tr("Ver tabla de esta gráfica", "Show this chart's table")}</summary>
        <table className="plain" aria-labelledby={id}>
          <caption id={id}>{title}: {sentence}</caption>
          <thead>
            <tr>
              <th scope="col">{group === "year" ? tr("Año", "Year") : group === "month" ? tr("Mes", "Month") : group === "hour" ? tr("Hora (local)", "Hour (local)") : tr("Día", "Day")}</th>
              <th scope="col" className="num">{classified ? tr("Horas", "Hours") : tr("Mediana", "Median")}</th>
              <th scope="col" className="num">{tr("Observaciones", "Observations")}</th>
            </tr>
          </thead>
          <tbody>
            {points.map((p) => (
              <tr key={p.key}>
                <th scope="row">{p.label}</th>
                <td className="num">{p.value === null ? noData : fmtV(p.value)}</td>
                <td className="num">{p.n === 0 ? "—" : `${count(p.n)}${p.n < LOW_N ? tr(" (pocas)", " (few)") : ""}`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </Card>
  );
}
