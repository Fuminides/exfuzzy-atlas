import { tr } from "../i18n";
import { gradientCss, type ColorStop } from "../lib/colorScale";

interface Props {
  title: string;
  /** Short statement of what the scale is NOT (probability, risk, ...), or the unit semantics. */
  note: string;
  stops: readonly ColorStop[];
  domain: readonly [number, number];
  /** Text shown for each tick, left to right. */
  ticks: readonly string[];
  /** Records with a value / total entities. */
  nValid: number | null;
  /** Text before the count, e.g. what is being counted. */
  countLabel: React.ReactNode;
  total: number;
  /** What a missing value means in this view. */
  missingLabel: string;
  /** Extra lines under the count: the aggregate window [from, to), n_valid range, entities not drawn... */
  detail?: React.ReactNode;
}

export function Legend({ title, note, stops, domain, ticks, nValid, total, missingLabel, countLabel, detail }: Props) {
  return (
    <section className="legend" aria-label={tr(`Leyenda: ${title}`, `Legend: ${title}`)} data-domain={`${domain[0]}-${domain[1]}`}>
      <div className="legend-text">
        <h3>{title}</h3>
        <p className="muted">{note}</p>
      </div>
      <div className="legend-scale">
        <div className="legend-bar" style={{ background: gradientCss(stops) }} role="img" aria-label={tr(`Escala de ${ticks[0]} a ${ticks[ticks.length - 1]}`, `Scale from ${ticks[0]} to ${ticks[ticks.length - 1]}`)} />
        <ol className="legend-ticks">
          {ticks.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ol>
        <p className="legend-missing">
          <span className="marker marker--missing" aria-hidden="true" /> {missingLabel}
        </p>
        {nValid !== null && (
          <p className="legend-count">
            {tr(<>{countLabel}: <strong>{nValid}</strong> de {total}</>, <>{countLabel}: <strong>{nValid}</strong> of {total}</>)}
          </p>
        )}
        {detail}
      </div>
    </section>
  );
}
