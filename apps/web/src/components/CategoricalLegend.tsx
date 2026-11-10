import type { TargetScheme } from "../api/types";
import { tr } from "../i18n";
import { boundsText, classColor, isMergedClass, mergedNote } from "../lib/classifier";
import { officialNames, schemeName } from "../lib/labels";
import { ClassChip } from "./ClassChip";

interface Props {
  title: string;
  /** What the categories are NOT (risk, probability, rule activation). */
  note: string;
  scheme: TargetScheme;
  nValid: number | null;
  total: number;
  countLabel: React.ReactNode;
  /** What a missing label means in this view. */
  missingLabel: string;
  detail?: React.ReactNode;
}

/** Ordered categorical legend of a classifier: classes with their bounds and unit, the scheme and its source. */
export function CategoricalLegend({ title, note, scheme, nValid, total, countLabel, missingLabel, detail }: Props) {
  const merged = scheme.classes.filter(isMergedClass);
  return (
    <section className="legend legend--classes" aria-label={tr(`Leyenda: ${title}`, `Legend: ${title}`)} data-classes={scheme.classes.map((c) => c.label).join("|")}>
      <div className="legend-text">
        <h3>{title}</h3>
        <p className="muted">{note}</p>
        <p className="legend-scheme">
          {tr("Esquema:", "Scheme:")}{" "}
          <a href={scheme.source_url} target="_blank" rel="noopener noreferrer">
            {schemeName(scheme)}
          </a>
          {officialNames(scheme) && <span className="muted small"> · {officialNames(scheme)}</span>}
        </p>
      </div>
      <div className="legend-scale">
        <ol className="class-legend" aria-label={tr("Categorías, de mejor a peor según el esquema", "Categories, from best to worst according to the scheme")}>
          {scheme.classes.map((c) => (
            <li key={c.label} data-class={c.label} data-color={classColor(scheme, c.label)}>
              <ClassChip label={c.label} color={classColor(scheme, c.label)} />
              <span className="muted"> {boundsText(c, scheme)}</span>
            </li>
          ))}
        </ol>
        {merged.map((c) => (
          <p key={c.label} className="legend-count merged-note" data-testid="merged-class-note">
            {mergedNote(c, scheme)}
          </p>
        ))}
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
