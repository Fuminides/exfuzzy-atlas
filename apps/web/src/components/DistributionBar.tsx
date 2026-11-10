import type { TargetClass } from "../api/types";
import { pct } from "../lib/format";
import { distributionText, segments } from "../lib/summary";

interface Props {
  classes: readonly TargetClass[];
  shares: readonly number[];
  /** Accessible subject of the bar ("Todas las estaciones", "Estación X"). */
  subject: string;
  /** Show the legend with each class and its share under the bar. */
  legend?: boolean;
  compact?: boolean;
}

/** One 100 % stacked bar in the official class colours; every segment is also written out (colour is never the only cue). */
export function DistributionBar({ classes, shares, subject, legend = true, compact = false }: Props) {
  const segs = segments(classes, shares);
  return (
    <div className={`dist${compact ? " dist--compact" : ""}`}>
      <div className="dist-bar" role="img" aria-label={`${subject}: ${distributionText(classes, shares)}`}>
        {segs.map((s) => (
          <span key={s.key} className="dist-seg" style={{ width: `${s.share * 100}%`, background: s.color }} data-class={s.key} data-share={String(s.share)}>
            {!compact && s.share >= 0.1 && <span className="dist-seg-text">{pct(s.share)}</span>}
          </span>
        ))}
      </div>
      {legend && (
        <ul className="dist-legend">
          {segs.map((s) => (
            <li key={s.key} data-class={s.key}>
              <span className="class-swatch" style={{ background: s.color }} aria-hidden="true" />
              <strong>{pct(s.share)}</strong> {s.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
