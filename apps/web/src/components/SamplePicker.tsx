import type { SeriesPoint } from "../api/types";
import { tr } from "../i18n";
import { fmt, formatInstant, unitLabel } from "../lib/format";
import { useZone } from "../lib/zone";

interface Props {
  entityName: string;
  samples: readonly SeriesPoint[];
  loading: boolean;
  /** The sample the trace is computed for (an exact issue time). */
  selected: string | null;
  onSelect: (issuedAt: string) => void;
  unit: string;
  windowText: string;
}

/**
 * Step before "¿Por qué aquí?" for irregular tasks: rule traces exist only at a sample's own issue time, so the user first picks
 * one of the point's samples inside the window (the latest by default).
 */
export function SamplePicker({ entityName, samples, loading, selected, onSelect, unit, windowText }: Props) {
  const zone = useZone();
  return (
    <section className="why sample-picker" aria-label={tr("Muestra del punto", "Sample of the point")}>
      <h2>
        {tr("Muestra del punto", "Sample of the point")} <span className="entity">{entityName}</span>
      </h2>
      {loading ? (
        <p role="status">{tr("Cargando muestras…", "Loading samples…")}</p>
      ) : samples.length === 0 ? (
        <p className="muted" data-testid="no-samples">
          {tr(`Este punto no tiene ninguna muestra en la ventana ${windowText}, así que no hay traza que mostrar. Elige otra ventana u otro punto.`,
            `This point has no sample in the window ${windowText}, so there's no trace to show. Pick another window or another point.`,
          )}
        </p>
      ) : (
        <label>
          {tr(`Muestra del punto en la ventana (${samples.length})`, `Sample of the point in the window (${samples.length})`)}
          <select value={selected ?? ""} onChange={(e) => onSelect(e.target.value)}>
            {samples.map((p) => (
              <option key={p.issued_at_utc} value={p.issued_at_utc}>
                {formatInstant(p.issued_at_utc, zone)}
                {p.observed !== null ? tr(` · observado ${fmt(p.observed)} ${unitLabel(unit)}`, ` · observed ${fmt(p.observed)} ${unitLabel(unit)}`) : ""}
              </option>
            ))}
          </select>
        </label>
      )}
    </section>
  );
}
