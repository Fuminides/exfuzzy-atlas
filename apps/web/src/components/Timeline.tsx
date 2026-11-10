import { tr } from "../i18n";
import { useState, type KeyboardEvent } from "react";
import { addHours, formatInstant, formatPlain, formatShortDate, sameSampleText, zoneName } from "../lib/format";
import { inputToUtc, utcToInput, type InputZone } from "../lib/localTime";
import { useZone } from "../lib/zone";

interface Props {
  times: readonly string[];
  index: number;
  onIndex: (i: number) => void;
  horizonHours: number;
  /** Hours between consecutive issue times (coverage.step_hours). */
  stepHours: number;
}

const jumps = () =>
  [
    { hours: -24, label: "−1 d", name: tr("Retroceder 1 día", "Back 1 day"), keys: "PageUp" },
    { hours: -1, label: "−1 h", name: tr("Retroceder 1 hora", "Back 1 hour"), keys: "Shift+ArrowLeft" },
    { hours: 1, label: "+1 h", name: tr("Avanzar 1 hora", "Forward 1 hour"), keys: "Shift+ArrowRight" },
    { hours: 24, label: "+1 d", name: tr("Avanzar 1 día", "Forward 1 day"), keys: "PageDown" },
  ] as const;

/**
 * Slider over issue times (up to ~8,760 at real scale), plus a date-time input and day/hour jumps.
 * The valid time (issue + horizon) is shown separately. Nothing is interpolated: every move lands on an issue time.
 */
export function Timeline({ times, index, onIndex, horizonHours, stepHours }: Props) {
  const local = useZone();
  const zones: InputZone[] = local === "UTC" ? ["UTC"] : ["UTC", local];
  const [zone, setZone] = useState<InputZone>("UTC");
  const [note, setNote] = useState<string | null>(null);
  const issued = times[index];
  if (!issued) return null;
  const last = times.length - 1;

  const go = (i: number) => {
    setNote(null);
    onIndex(Math.min(last, Math.max(0, i)));
  };
  /** A jump of `hours` is only offered when it is a whole number of issue steps. */
  const steps = (hours: number): number | null => (Number.isInteger(hours / stepHours) ? hours / stepHours : null);
  const jump = (hours: number) => {
    const s = steps(hours);
    if (s !== null) go(index + s);
  };

  const commitInput = (value: string) => {
    const ms = inputToUtc(value, zone);
    if (ms === null) return;
    const t0 = Date.parse(times[0]!);
    const i = Math.min(last, Math.max(0, Math.round((ms - t0) / (stepHours * 3_600_000))));
    onIndex(i);
    setNote(
      Date.parse(times[i]!) === ms
        ? null
        : ms < t0 || ms > Date.parse(times[last]!)
          ? tr("Fuera de la cobertura: se ha ajustado al extremo más cercano.", "Outside the coverage: moved to the nearest end.")
          : tr("No hay emisión en ese instante: se ha ajustado a la más cercana.", "No issue at that instant: moved to the nearest one."),
    );
  };

  // Keyboard jumps work from the slider and the buttons, but never steal keys from the date-time field.
  const onKeyDown = (e: KeyboardEvent<HTMLElement>) => {
    const target = e.target as HTMLElement;
    if (target.tagName === "SELECT" || (target instanceof HTMLInputElement && target.type !== "range")) return;
    const hours =
      e.key === "PageUp" ? -24
      : e.key === "PageDown" ? 24
      : e.shiftKey && e.key === "ArrowLeft" ? -1
      : e.shiftKey && e.key === "ArrowRight" ? 1
      : 0;
    if (hours === 0 || steps(hours) === null) return;
    e.preventDefault();
    jump(hours);
  };

  const valid = addHours(issued, horizonHours);
  const sameDay = formatShortDate(valid, local) === formatShortDate(issued, local);
  const clock = (iso: string) => formatPlain(iso, local).split(", ")[1];
  const line =
    horizonHours === 0
      ? tr(`Muestra: ${formatPlain(issued, local)} (${zoneName(local)}) · ${sameSampleText()}`, `Sample: ${formatPlain(issued, local)} (${zoneName(local)}) · ${sameSampleText()}`)
      : tr(`Emisión: ${formatPlain(issued, local)} → prevé ${sameDay ? `las ${clock(valid)}` : `el ${formatPlain(valid, local)}`} (${zoneName(local)})`, `Issue: ${formatPlain(issued, local)} → predicts ${sameDay ? clock(valid) : formatPlain(valid, local)} (${zoneName(local)})`);

  return (
    <section className="timeline timeline--compact" aria-label={tr("Línea temporal de emisión", "Issue timeline")} onKeyDown={onKeyDown}>
      <div className="timeline-controls">
        <button type="button" onClick={() => go(index - 1)} disabled={index <= 0} aria-label={tr("Emisión anterior", "Previous issue")}>
          ◀
        </button>
        <input
          type="range"
          min={0}
          max={last}
          step={1}
          value={index}
          onChange={(e) => go(Number(e.target.value))}
          aria-label={tr("Hora de emisión", "Issue time")}
          aria-valuetext={formatInstant(issued, local)}
          aria-keyshortcuts="PageUp PageDown Shift+ArrowLeft Shift+ArrowRight"
        />
        <button type="button" onClick={() => go(index + 1)} disabled={index >= last} aria-label={tr("Emisión siguiente", "Next issue")}>
          ▶
        </button>
        <div className="timeline-jumps" role="group" aria-label={tr("Saltos en el tiempo", "Jumps in time")}>
          {jumps().map((j) => {
            const s = steps(j.hours);
            const target = s === null ? null : index + s;
            return (
              <button
                key={j.label}
                type="button"
                onClick={() => jump(j.hours)}
                disabled={target === null || target < 0 || target > last}
                aria-label={j.name}
                aria-keyshortcuts={j.keys}
                title={`${j.name} (${j.keys})`}
              >
                {j.label}
              </button>
            );
          })}
          <label className="timeline-input" title={tr(`Ir a fecha y hora (${zone})`, `Go to date and time (${zone})`)}>
            <span className="sr-only">{tr("Ir a fecha y hora", "Go to date and time")}</span>
            <input
              type="datetime-local"
              value={utcToInput(issued, zone)}
              min={utcToInput(times[0]!, zone)}
              max={utcToInput(times[last]!, zone)}
              step={Math.max(60, stepHours * 3600)}
              onChange={(e) => e.target.value && commitInput(e.target.value)}
            />
          </label>
          <span className="muted timeline-zone-hint">{zone}</span>
        </div>
      </div>
      <p className="timeline-line" data-testid="timeline-line">
        {line}
      </p>
      {note && (
        <p className="notice" role="status">
          {note}
        </p>
      )}
      <details className="timeline-details">
        <summary>{tr("Detalles de tiempo", "Time details")}</summary>
        <div className="timeline-jumps">
          <label className="timeline-zone">
            {tr("Zona del campo", "Field time zone")}
            <select value={zone} onChange={(e) => setZone(e.target.value as InputZone)}>
              {zones.map((z) => (
                <option key={z} value={z}>
                  {z}
                </option>
              ))}
            </select>
          </label>
          <span className="muted keys-hint">{tr("Teclado: Re Pág / Av Pág = −1 d / +1 d · Mayús+←/→ = −1 h / +1 h", "Keyboard: Page Up / Page Down = −1 d / +1 d · Shift+←/→ = −1 h / +1 h")}</span>
        </div>
        <dl className="timeline-labels">
          <div>
            <dt>{tr("Hora de emisión", "Issue time")}</dt>
            <dd data-testid="issue-time">{formatInstant(issued, local)}</dd>
          </div>
          <div>
            <dt>{horizonHours === 0 ? tr(`Hora de validez (= emisión; ${sameSampleText()})`, `Valid time (= issue; ${sameSampleText()})`) : tr(`Hora de validez (emisión + ${horizonHours} h)`, `Valid time (issue + ${horizonHours} h)`)}</dt>
            <dd data-testid="valid-time">{formatInstant(valid, local)}</dd>
          </div>
          <div>
            <dt>{tr("Cobertura", "Coverage")}</dt>
            <dd>
              {tr(`${times.length} emisiones, de ${formatInstant(times[0]!, local)} a ${formatInstant(times[last]!, local)}`, `${times.length} issue times, from ${formatInstant(times[0]!, local)} to ${formatInstant(times[last]!, local)}`)}
            </dd>
          </div>
        </dl>
      </details>
    </section>
  );
}
