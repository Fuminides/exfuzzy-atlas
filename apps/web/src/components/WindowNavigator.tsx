import { tr } from "../i18n";
import { useZone } from "../lib/zone";
import { formatInstant, utcStamp, windowDaysText } from "../lib/format";
import { neighbourWindow, windowDays, windowOverlapsCoverage, type CoverageLike, type TimeWindow, type WindowKind } from "../lib/windows";

export type NavKind = Exclude<WindowKind, "coverage">;

const kinds = (): { id: NavKind; label: string }[] => [
  { id: "day", label: tr("Día", "Day") },
  { id: "week", label: tr("Semana", "Week") },
  { id: "month", label: tr("Mes", "Month") },
  { id: "year", label: tr("Año", "Year") },
];

interface Props {
  kind: NavKind;
  window: TimeWindow;
  coverage: CoverageLike;
  onKind: (k: NavKind) => void;
  /** Static export: the window kinds it holds (every kind when absent). */
  kinds?: readonly WindowKind[];
  /** An instant inside the window to show (the navigator moves the window, never an hour). */
  onAnchor: (iso: string) => void;
}

/**
 * Timeline of a task whose issue times are irregular sample times (Water). There is no hourly slider: most hours
 * have no sample at all, so stepping through them would show "time passing" over empty data. The window is the unit.
 */
export function WindowNavigator({ kind, window: w, coverage, onKind, kinds: offered, onAnchor }: Props) {
  const zone = useZone();
  const prev = neighbourWindow(kind, w, -1, coverage);
  const next = neighbourWindow(kind, w, 1, coverage);
  const day = (iso: string) => iso.slice(0, 10);
  return (
    <section className="timeline timeline--windows timeline--compact" aria-label={tr("Ventana de muestras", "Sample window")} data-irregular="true">
      <div className="timeline-controls">
        <button type="button" onClick={() => onAnchor(prev.from)} disabled={!windowOverlapsCoverage(prev, coverage)} aria-label={tr("Ventana anterior", "Previous window")}>
          ◀
        </button>
        <div className="window-kinds" role="group" aria-label={tr("Tamaño de la ventana", "Window size")}>
          {kinds().filter((k) => !offered || offered.includes(k.id)).map((k) => (
            <button key={k.id} type="button" aria-pressed={k.id === kind} onClick={() => onKind(k.id)}>
              {k.label}
            </button>
          ))}
        </div>
        <button type="button" onClick={() => onAnchor(next.from)} disabled={!windowOverlapsCoverage(next, coverage)} aria-label={tr("Ventana siguiente", "Next window")}>
          ▶
        </button>
        <label className="timeline-input">
          <span className="sr-only">{tr("Ir a fecha", "Go to date")}</span>
          <input
            type="date"
            value={day(Date.parse(w.from) < Date.parse(coverage.issued_from_utc) ? coverage.issued_from_utc : w.from)}
            min={day(coverage.issued_from_utc)}
            max={day(coverage.issued_to_utc)}
            onChange={(e) => {
              if (!e.target.value) return;
              const t = Date.parse(`${e.target.value}T00:00:00Z`);
              const lo = Date.parse(coverage.issued_from_utc);
              const hi = Date.parse(coverage.issued_to_utc);
              onAnchor(new Date(Math.min(hi, Math.max(lo, t))).toISOString().replace(".000Z", "Z"));
            }}
          />
        </label>
      </div>
      <p className="timeline-line" data-testid="timeline-line">
        {tr(`Muestras del ${windowDaysText(w.from, w.to)}`, `Samples: ${windowDaysText(w.from, w.to)}`)}
      </p>
      <details className="timeline-details">
        <summary>{tr("Detalles de tiempo", "Time details")}</summary>
        <dl className="timeline-labels">
          <div>
            <dt>{tr("Ventana (semiabierta, UTC)", "Window (half-open, UTC)")}</dt>
            <dd data-testid="window-range">
              [{utcStamp(w.from)}, {utcStamp(w.to)}) · {windowDays(w)} d
            </dd>
          </div>
          <div>
            <dt>{tr("Cobertura", "Coverage")}</dt>
            <dd>
              {tr(`de ${formatInstant(coverage.issued_from_utc, zone)} a ${formatInstant(coverage.issued_to_utc, zone)}`, `from ${formatInstant(coverage.issued_from_utc, zone)} to ${formatInstant(coverage.issued_to_utc, zone)}`)}
            </dd>
          </div>
        </dl>
        <p className="muted" data-testid="irregular-note">
          {tr("Las emisiones son las fechas de muestreo, que son irregulares: no hay una por hora. La ventana agrupa las muestras de cada punto. No se avanza hora a hora.", "The issue times are the sampling dates, which are irregular, so there isn't one per hour. The window groups each point's samples. It doesn't step hour by hour.")}
        </p>
      </details>
    </section>
  );
}
