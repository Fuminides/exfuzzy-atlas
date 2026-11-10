import type { SeriesResponse } from "../api/types";
import { tr } from "../i18n";
import { fmt, formatInstant, sameSampleText, unitLabel, missingText } from "../lib/format";
import { useZone } from "../lib/zone";
import { targetLabel } from "./SeriesChart";
import type { TimeWindow } from "../lib/windows";

const W = 420;
const H = 230;
const M = { l: 44, r: 12, t: 12, b: 34 };

interface Props {
  series: SeriesResponse;
  /** Window selected on the navigator, shaded on the chart. */
  window: TimeWindow | null;
}

const day = (ms: number) => new Date(ms).toISOString().slice(0, 10);

/**
 * Observed and predicted target of one point, by SAMPLE date. Samples are irregular, so each sample is a separate
 * pair of marks (filled circle = observed, hollow diamond = predicted, joined by a short segment): no line runs
 * between samples and nothing is interpolated. The prediction is made on the same sample, not ahead of time.
 */
export function SampleChart({ series, window: w }: Props) {
  const zone = useZone();
  const unit = unitLabel(series.unit);
  const label = targetLabel(series.target);
  const pts = series.points;
  if (pts.length === 0) return <p className="muted">{tr(`Este punto no tiene muestras con ${label} en la cobertura.`, `This point has no samples with ${label} in the coverage.`)}</p>;
  const xs = pts.map((p) => Date.parse(p.valid_at_utc));
  const x0 = Math.min(...xs, w ? Date.parse(w.from) : Infinity);
  const x1 = Math.max(...xs, w ? Date.parse(w.to) : -Infinity);
  const ys = pts.flatMap((p) => [p.observed, p.prediction]).filter((v): v is number => v !== null);
  const yMax = Math.max(1, ...ys) * 1.1;
  const X = (t: number) => M.l + ((t - x0) / (x1 - x0 || 1)) * (W - M.l - M.r);
  const Y = (v: number) => H - M.b - (v / yMax) * (H - M.t - M.b);
  const ticks = [0, 0.5, 1].map((f) => f * yMax);
  const xTicks = [0, 0.5, 1].map((f) => x0 + f * (x1 - x0));

  return (
    <figure className="series series--samples" data-testid="sample-chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={tr(`${label} observado y predicho por muestra (${unit}) en ${series.entity_id}`, `Observed and predicted ${label} per sample (${unit}) at ${series.entity_id}`)}>
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
        {w && <rect x={X(Date.parse(w.from))} y={M.t} width={Math.max(1, X(Date.parse(w.to)) - X(Date.parse(w.from)))} height={H - M.t - M.b} className="window-band" />}
        {pts.map((p, i) => {
          const x = X(xs[i]!);
          return (
            <g key={p.issued_at_utc} data-sample={p.issued_at_utc}>
              {p.observed !== null && p.prediction !== null && <line x1={x} x2={x} y1={Y(p.observed)} y2={Y(p.prediction)} className="pair" />}
              {p.observed !== null && <circle cx={x} cy={Y(p.observed)} r={3.5} className="dot obs" />}
              {p.prediction !== null && (
                <rect x={x - 3.5} y={Y(p.prediction) - 3.5} width={7} height={7} transform={`rotate(45 ${x} ${Y(p.prediction)})`} className="mark pred" />
              )}
            </g>
          );
        })}
        {xTicks.map((t) => (
          <text key={t} x={X(t)} y={H - M.b + 14} textAnchor="middle" className="axis">
            {day(t)}
          </text>
        ))}
        <text x={(M.l + W - M.r) / 2} y={H - 4} textAnchor="middle" className="axis">
          {tr("fecha de la muestra (UTC)", "sample date (UTC)")}
        </text>
      </svg>
      <figcaption>
        <span className="key obs">{tr("● observado", "● observed")}</span> <span className="key pred">{tr("◇ predicho por el modelo", "◇ predicted by the model")}</span>
        {" · "}
        {tr("una pareja por muestra, sin línea entre muestras · banda: ventana elegida · ", "one pair per sample, no line between samples · band: chosen window · ")}
        {sameSampleText()}
      </figcaption>
      <details open>
        <summary>{tr(`Datos de la gráfica (${pts.length} muestras)`, `Chart data (${pts.length} samples)`)}</summary>
        <table className="plain">
          <caption>{tr(`Muestras de ${series.entity_id} (${unit})`, `Samples of ${series.entity_id} (${unit})`)}</caption>
          <thead>
            <tr>
              <th scope="col">{tr("Muestra", "Sample")}</th>
              <th scope="col">{tr("Observado", "Observed")}</th>
              <th scope="col">{tr("Predicho", "Predicted")}</th>
            </tr>
          </thead>
          <tbody>
            {pts.map((p) => (
              <tr
                key={p.issued_at_utc}
                data-in-window={w && Date.parse(p.issued_at_utc) >= Date.parse(w.from) && Date.parse(p.issued_at_utc) < Date.parse(w.to) ? "true" : undefined}
              >
                <th scope="row">{formatInstant(p.issued_at_utc, zone)}</th>
                <td>{p.observed === null ? tr("sin dato", "no data") : <span data-raw={String(p.observed)}>{fmt(p.observed)}</span>}</td>
                <td>
                  {p.prediction === null ? (
                    <span className="missing-text">
                      {tr("sin dato", "no data")}
                      {p.missing_reason ? ` · ${missingText(p.missing_reason)}` : ""}
                    </span>
                  ) : (
                    <span data-raw={String(p.prediction)}>{fmt(p.prediction)}</span>
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
