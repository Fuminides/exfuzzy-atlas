import type { SeriesResponse } from "../api/types";
import { tr } from "../i18n";
import { fmt, formatInstant, sameSampleText, sameInstant, unitLabel, missingText } from "../lib/format";
import { useZone } from "../lib/zone";

const W = 420;
const H = 220;
const M = { l: 44, r: 12, t: 12, b: 34 };

// Built at call time (not at import): the language can change while the page is open.
const TARGET_LABEL = (): Record<string, string> => ({ no2: "NO₂", dissolved_oxygen: tr("oxígeno disuelto", "dissolved oxygen"), pickups: tr("recogidas de taxi", "taxi pickups") });
export const targetLabel = (target: string): string => TARGET_LABEL()[target] ?? target;

interface Props {
  series: SeriesResponse;
  /** Issue time currently selected on the timeline, marked on the chart. */
  selectedIssue: string | null;
}

/** Observed vs predicted target by VALID time. Gaps stay gaps: nothing is interpolated. */
export function SeriesChart({ series, selectedIssue }: Props) {
  const zone = useZone();
  const unit = unitLabel(series.unit);
  const label = targetLabel(series.target);
  const pts = series.points;
  if (pts.length === 0) return <p className="muted">{tr(`No hay puntos de ${label} en esta ventana.`, `There are no ${label} points in this window.`)}</p>;
  const xs = pts.map((p) => new Date(p.valid_at_utc).getTime());
  const x0 = Math.min(...xs);
  const x1 = Math.max(...xs);
  const ys = pts.flatMap((p) => [p.observed, p.prediction]).filter((v): v is number => v !== null);
  const yMax = Math.max(1, ...ys) * 1.1;
  const X = (t: number) => M.l + ((t - x0) / (x1 - x0 || 1)) * (W - M.l - M.r);
  const Y = (v: number) => H - M.b - (v / yMax) * (H - M.t - M.b);

  // A null, or a missing issue time, breaks the line: segments only join consecutive present values.
  const gaps = xs.slice(1).map((x, i) => x - xs[i]!).filter((d) => d > 0);
  const step = gaps.length ? Math.min(...gaps) : 0;
  const segments = (pick: (i: number) => number | null): string[] => {
    const out: string[] = [];
    let cur: string[] = [];
    const flush = () => {
      if (cur.length > 1) out.push(cur.join(" "));
      cur = [];
    };
    pts.forEach((_, i) => {
      const v = pick(i);
      if (v === null || (i > 0 && step > 0 && xs[i]! - xs[i - 1]! > 1.5 * step)) flush();
      if (v !== null) cur.push(`${X(xs[i]!)},${Y(v)}`);
    });
    flush();
    return out;
  };
  const selected = pts.find((p) => sameInstant(p.issued_at_utc, selectedIssue));
  const ticks = [0, 0.5, 1].map((f) => f * yMax);
  // At real scale a window has ~144 points: label ~5 evenly spaced times and draw dots only for short series.
  const xTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => x0 + f * (x1 - x0));
  const dots = pts.length <= 48;

  return (
    <figure className="series">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={tr(`${label} observado y predicho (${unit}) en ${series.entity_id}`, `Observed and predicted ${label} (${unit}) at ${series.entity_id}`)}>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={M.l} x2={W - M.r} y1={Y(v)} y2={Y(v)} className="grid" />
            <text x={M.l - 6} y={Y(v) + 4} textAnchor="end" className="axis">
              {Math.round(v)}
            </text>
          </g>
        ))}
        <text x={12} y={M.t + 2} className="axis" transform={`rotate(-90 12 ${H / 2})`} textAnchor="middle">
          {`${label} (${unit})`}
        </text>
        {selected && (
          <line x1={X(new Date(selected.valid_at_utc).getTime())} x2={X(new Date(selected.valid_at_utc).getTime())} y1={M.t} y2={H - M.b} className="sel" />
        )}
        {segments((i) => pts[i]!.observed).map((d) => (
          <polyline key={`o${d}`} points={d} className="line obs" />
        ))}
        {segments((i) => pts[i]!.prediction).map((d) => (
          <polyline key={`p${d}`} points={d} className="line pred" />
        ))}
        {dots &&
          pts.map((p, i) => (
            <g key={p.issued_at_utc}>
              {p.observed !== null && <circle cx={X(xs[i]!)} cy={Y(p.observed)} r={3.5} className="dot obs" />}
              {p.prediction !== null && <circle cx={X(xs[i]!)} cy={Y(p.prediction)} r={3.5} className="dot pred" />}
            </g>
          ))}
        {selected && !dots && (
          <>
            {selected.observed !== null && <circle cx={X(new Date(selected.valid_at_utc).getTime())} cy={Y(selected.observed)} r={3.5} className="dot obs" />}
            {selected.prediction !== null && <circle cx={X(new Date(selected.valid_at_utc).getTime())} cy={Y(selected.prediction)} r={3.5} className="dot pred" />}
          </>
        )}
        {xTicks.map((t) => (
          <text key={t} x={X(t)} y={H - M.b + 14} textAnchor="middle" className="axis">
            {new Date(t).toISOString().slice(5, 16).replace("T", " ")}
          </text>
        ))}
        <text x={(M.l + W - M.r) / 2} y={H - 4} textAnchor="middle" className="axis">
          {tr("hora de validez (UTC, MM-DD HH:mm)", "valid time (UTC, MM-DD HH:mm)")}
        </text>
      </svg>
      <figcaption>
        <span className="key obs">{tr("● observado", "● observed")}</span> <span className="key pred">{tr("● predicho por el modelo", "● predicted by the model")}</span>
        {" · "}
        {tr("eje X: hora de validez", "X axis: valid time")} ({series.horizon_hours === 0 ? sameSampleText() : tr(`emisión + ${series.horizon_hours} h`, `issue + ${series.horizon_hours} h`)})
      </figcaption>
      <details>
        <summary>{tr(`Datos de la gráfica (${pts.length} puntos)`, `Chart data (${pts.length} points)`)}</summary>
      <table className="plain">
        <caption>{tr(`Datos de la gráfica (${unit})`, `Chart data (${unit})`)}</caption>
        <thead>
          <tr>
            <th scope="col">{tr("Válido", "Valid")}</th>
            <th scope="col">{tr("Observado", "Observed")}</th>
            <th scope="col">{tr("Predicho", "Predicted")}</th>
          </tr>
        </thead>
        <tbody>
          {pts.map((p) => (
            <tr key={p.issued_at_utc} aria-current={sameInstant(p.issued_at_utc, selectedIssue) ? "true" : undefined}>
              <th scope="row">{formatInstant(p.valid_at_utc, zone)}</th>
              <td>{p.observed === null ? tr("sin dato", "no data") : fmt(p.observed)}</td>
              <td>
                {p.prediction === null ? (
                  <span className="missing-text">
                    {tr("sin dato", "no data")}
                    {p.missing_reason ? ` · ${missingText(p.missing_reason)}` : ""}
                  </span>
                ) : (
                  fmt(p.prediction)
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </details>
    </figure>
  );
}
