import type { SeriesResponse, TargetScheme } from "../api/types";
import { tr } from "../i18n";
import { classColor, isNoReference, scaleInObservedUnits } from "../lib/classifier";
import { fmtNum, formatInstant, sameSampleText, sameInstant, unitLabel, missingText } from "../lib/format";
import { className, schemeName } from "../lib/labels";
import { useZone } from "../lib/zone";
import { ClassChip } from "./ClassChip";
import { targetLabel } from "./SeriesChart";

const W = 420;
const H = 276;
const M = { l: 44, r: 12, t: 12, b: 64 };
const ROW_H = 14;
const ROW_GAP = 4;

interface Props {
  series: SeriesResponse;
  scheme: TargetScheme;
  /** Issue time currently selected on the timeline, marked on the chart. */
  selectedIssue: string | null;
}

/**
 * Classifier series by VALID time: the observed concentration as a line over the scheme's class bands, and two
 * categorical strips (observed category, predicted category). There is no numeric predicted line: the model predicts
 * a class, and gaps stay gaps.
 */
export function ClassSeriesChart({ series, scheme, selectedIssue }: Props) {
  const zone = useZone();
  const unit = unitLabel(series.unit);
  // Bands can only sit on the value axis when the scheme is written in the observed unit (NYC: percentiles of a count).
  const showBands = scaleInObservedUnits(scheme, series.unit);
  // "Sin referencia" exists only for schemes relative to a per-entity reference (NYC); never in an absolute index.
  const noReference = (p: Parameters<typeof isNoReference>[0]) => !showBands && isNoReference(p);
  const label = targetLabel(series.target);
  const pts = series.points;
  if (pts.length === 0) return <p className="muted">{tr(`No hay puntos de ${label} en esta ventana.`, `There are no ${label} points in this window.`)}</p>;
  const xs = pts.map((p) => new Date(p.valid_at_utc).getTime());
  const gaps = xs.slice(1).map((x, i) => x - xs[i]!).filter((d) => d > 0);
  const step = gaps.length ? Math.min(...gaps) : 3_600_000;
  const x0 = Math.min(...xs) - step / 2;
  const x1 = Math.max(...xs) + step / 2;
  const obs = pts.flatMap((p) => (p.observed === null ? [] : [p.observed]));
  const yMax = Math.max(1, ...obs) * 1.1;
  const plotB = H - M.b;
  const X = (t: number) => M.l + ((t - x0) / (x1 - x0 || 1)) * (W - M.l - M.r);
  const Y = (v: number) => plotB - (Math.min(v, yMax) / yMax) * (plotB - M.t);
  const cellW = Math.max(1, X(x0 + step) - X(x0));

  const bands = (showBands ? scheme.classes : [])
    .map((c) => ({ c, lo: c.lower ?? 0, hi: c.upper ?? yMax }))
    .filter((b) => b.lo < yMax);
  const segments = (): string[] => {
    const out: string[] = [];
    let cur: string[] = [];
    const flush = () => {
      if (cur.length > 1) out.push(cur.join(" "));
      cur = [];
    };
    pts.forEach((p, i) => {
      if (p.observed === null || (i > 0 && xs[i]! - xs[i - 1]! > 1.5 * step)) flush();
      if (p.observed !== null) cur.push(`${X(xs[i]!)},${Y(p.observed)}`);
    });
    flush();
    return out;
  };
  const selected = pts.find((p) => sameInstant(p.issued_at_utc, selectedIssue));
  const ticks = [0, 0.5, 1].map((f) => f * yMax);
  const xTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => x0 + step / 2 + f * (x1 - x0 - step));
  const dots = pts.length <= 48;
  const rowY = [plotB + 8, plotB + 8 + ROW_H + ROW_GAP];
  const strip = (row: 0 | 1, pick: (i: number) => string | null) =>
    pts.map((p, i) => {
      const l = pick(i);
      const noRef = l === null && row === 1 && noReference(p);
      return (
        <rect
          key={`${row}-${p.issued_at_utc}`}
          x={X(xs[i]!) - cellW / 2}
          y={rowY[row]}
          width={cellW}
          height={ROW_H}
          className={l === null ? (noRef ? "cell cell--noref" : "cell cell--missing") : "cell"}
          style={l === null ? (noRef ? { fill: "url(#noref-hatch)" } : undefined) : { fill: classColor(scheme, l) }}
          data-class={l ?? undefined}
          data-no-reference={noRef ? "true" : undefined}
        />
      );
    });

  return (
    <figure className="series series--classes">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={tr(`${label} observado (${unit}) y categoría prevista en ${series.entity_id}`, `Observed ${label} (${unit}) and predicted category at ${series.entity_id}`)}>
        <defs>
          <pattern id="noref-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="6" height="6" fill="#ffffff" />
            <line x1="0" y1="0" x2="0" y2="6" stroke="#6b7280" strokeWidth="2" />
          </pattern>
        </defs>
        {bands.map(({ c, lo, hi }) => (
          <g key={c.label} data-band={c.label}>
            <rect
              x={M.l}
              y={Y(Math.min(hi, yMax))}
              width={W - M.l - M.r}
              height={Math.max(0, Y(lo) - Y(Math.min(hi, yMax)))}
              style={{ fill: classColor(scheme, c.label) }}
              className="band"
            />
            {Y(lo) - Y(Math.min(hi, yMax)) > 11 && (
              <text x={W - M.r - 3} y={Y(Math.min(hi, yMax)) + 10} textAnchor="end" className="band-label">
                {className(c)}
              </text>
            )}
          </g>
        ))}
        {ticks.map((v) => (
          <g key={v}>
            <line x1={M.l} x2={W - M.r} y1={Y(v)} y2={Y(v)} className="grid" />
            <text x={M.l - 6} y={Y(v) + 4} textAnchor="end" className="axis">
              {Math.round(v)}
            </text>
          </g>
        ))}
        <text x={12} y={M.t + 2} className="axis" transform={`rotate(-90 12 ${(M.t + plotB) / 2})`} textAnchor="middle">
          {`${label} (${unit})`}
        </text>
        {selected && (
          <line x1={X(new Date(selected.valid_at_utc).getTime())} x2={X(new Date(selected.valid_at_utc).getTime())} y1={M.t} y2={rowY[1]! + ROW_H} className="sel" />
        )}
        {segments().map((d) => (
          <polyline key={d} points={d} className="line obs" />
        ))}
        {dots &&
          pts.map((p, i) => p.observed !== null && <circle key={p.issued_at_utc} cx={X(xs[i]!)} cy={Y(p.observed)} r={3} className="dot obs" />)}
        {selected && !dots && selected.observed !== null && (
          <circle cx={X(new Date(selected.valid_at_utc).getTime())} cy={Y(selected.observed)} r={3.5} className="dot obs" />
        )}
        <g data-strip="observed">{strip(0, (i) => pts[i]!.observed_label ?? null)}</g>
        <g data-strip="predicted">{strip(1, (i) => pts[i]!.predicted_label ?? null)}</g>
        <text x={M.l - 6} y={rowY[0]! + 10} textAnchor="end" className="axis">{tr("obs.", "obs.")}</text>
        <text x={M.l - 6} y={rowY[1]! + 10} textAnchor="end" className="axis">{tr("prev.", "pred.")}</text>
        {xTicks.map((t) => (
          <text key={t} x={X(t)} y={rowY[1]! + ROW_H + 11} textAnchor="middle" className="axis">
            {new Date(t).toISOString().slice(5, 16).replace("T", " ")}
          </text>
        ))}
        <text x={(M.l + W - M.r) / 2} y={H - 3} textAnchor="middle" className="axis">
          {tr("hora de validez (UTC, MM-DD HH:mm)", "valid time (UTC, MM-DD HH:mm)")}
        </text>
      </svg>
      <figcaption>
        <span className="key obs">● {showBands ? tr("concentración observada", "observed concentration") : tr(`valor observado (${unit})`, `observed value (${unit})`)}</span>{" "}
        {showBands
          ? tr(<>sobre las bandas de «{schemeName(scheme)}».</>, <>over the bands of “{schemeName(scheme)}”.</>)
          : tr(<>sin bandas: las categorías de «{schemeName(scheme)}» son percentiles de la referencia de cada zona, no valores de este eje.</>, <>no bands: the categories of “{schemeName(scheme)}” are percentiles of each zone&apos;s reference, not values of this axis.</>)}{" "}
        {tr(<>En las franjas de abajo, la categoría observada (obs.) y la prevista por el modelo (prev.). Un hueco gris es «sin predicción» o «sin dato»{showBands ? "" : ", y una franja rayada, «sin referencia» (la zona no tiene nivel de referencia a esa hora de la semana)"}. El modelo predice una categoría, no un valor, y por eso no hay línea de {showBands ? "concentración prevista" : "valor previsto"}. Eje X: hora de validez ({series.horizon_hours === 0 ? sameSampleText() : `emisión + ${series.horizon_hours} h`}).</>,
          <>The lower strips show the observed category (obs.) and the one the model predicted (pred.). A grey gap means “no prediction” or “no data”{showBands ? "" : ", and a hatched strip means “no reference” (the zone has no reference level at that hour of the week)"}. The model predicts a category, not a value, so there&apos;s no {showBands ? "predicted concentration" : "predicted value"} line. X axis: valid time ({series.horizon_hours === 0 ? sameSampleText() : `issue + ${series.horizon_hours} h`}).</>,
        )}
      </figcaption>
      <details>
        <summary>{tr(`Datos de la gráfica (${pts.length} puntos)`, `Chart data (${pts.length} points)`)}</summary>
        <table className="plain">
          <caption>{tr(`Datos de la gráfica (${unit})`, `Chart data (${unit})`)}</caption>
          <thead>
            <tr>
              <th scope="col">{tr("Válido", "Valid")}</th>
              <th scope="col">{tr("Observado", "Observed")}</th>
              <th scope="col">{tr("Categoría observada", "Observed category")}</th>
              <th scope="col">{tr("Categoría prevista", "Predicted category")}</th>
            </tr>
          </thead>
          <tbody>
            {pts.map((p) => (
              <tr key={p.issued_at_utc} aria-current={sameInstant(p.issued_at_utc, selectedIssue) ? "true" : undefined}>
                <th scope="row">{formatInstant(p.valid_at_utc, zone)}</th>
                <td>{p.observed === null ? tr("sin dato", "no data") : <span data-raw={String(p.observed)}>{fmtNum(p.observed)}</span>}</td>
                <td>{p.observed_label ? <ClassChip label={p.observed_label} color={classColor(scheme, p.observed_label)} /> : tr("sin dato", "no data")}</td>
                <td>
                  {p.predicted_label ? (
                    <ClassChip label={p.predicted_label} color={classColor(scheme, p.predicted_label)} />
                  ) : (
                    <span className="missing-text" data-no-reference={noReference(p) ? "true" : undefined}>
                      {noReference(p) ? tr("sin referencia", "no reference") : tr("sin predicción", "no prediction")}
                      {p.missing_reason && !noReference(p) ? ` · ${missingText(p.missing_reason)}` : ""}
                    </span>
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
