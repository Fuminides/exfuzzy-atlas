import { api } from "../api/client";
import type { ModelCard, ModelRules, ObservationsResponse, TargetScheme, TaskInfo } from "../api/types";
import { useAsync } from "../hooks/useAsync";
import { formatDate, sameSampleText } from "../lib/format";
import { labelerFor, labelWithUnit } from "../lib/labels";
import { utcToInput } from "../lib/localTime";
import { predictsText } from "../lib/taskText";
import { Card, MoreInfo } from "./Card";
import { tr } from "../i18n";

interface Props {
  task: TaskInfo;
  card: ModelCard;
  /** The card's coverage, which the caller has checked exists. */
  coverage: Coverage;
  rules: ModelRules;
  scheme: TargetScheme | null;
  zone: string;
  /** Horizons of the territory (hours, ascending). */
  horizons: readonly number[];
}

const HOUR = 3_600_000;
const clock = (ms: number, zone: string) => utcToInput(new Date(ms).toISOString(), zone).slice(11);
const localHour = (ms: number, zone: string) => Number(clock(ms, zone).slice(0, 2));

/** A typical issue time: the first 08:00 local a week after the coverage starts (or the first one there is). */
type Coverage = NonNullable<ModelCard["coverage"]>;

export function exampleIssue(coverage: Pick<Coverage, "issued_from_utc" | "issued_to_utc" | "step_hours">, zone: string): string {
  const from = Date.parse(coverage.issued_from_utc);
  const to = Date.parse(coverage.issued_to_utc);
  const step = Math.max(1, coverage.step_hours) * HOUR;
  for (let t = Math.min(to, from + 7 * 24 * HOUR); t <= to && t < from + 60 * 24 * HOUR; t += step) {
    if (localHour(t, zone) === 8) return new Date(t).toISOString().replace(".000Z", "Z");
  }
  return coverage.issued_from_utc;
}

interface Column {
  lagHours: number;
  inputs: { label: string }[];
}

/** Inputs grouped by how old they are at the issue time, from the published `observed_at_utc` of one example (never guessed). */
export function inputColumns(obs: ObservationsResponse, label: (feature: string) => string, units: Map<string, string | null | undefined>): Column[] {
  const sample = obs.features.find((f) => f.properties.issued_at_utc && f.properties.inputs.length > 0 && f.properties.inputs.every((i) => i.observed_at_utc));
  if (!sample) return [];
  const issued = Date.parse(sample.properties.issued_at_utc!);
  const byLag = new Map<number, Column>();
  for (const input of sample.properties.inputs) {
    const lag = Math.round((issued - Date.parse(input.observed_at_utc!)) / HOUR);
    const col = byLag.get(lag) ?? { lagHours: lag, inputs: [] };
    col.inputs.push({ label: labelWithUnit(label(input.feature), units.get(input.feature)) });
    byLag.set(lag, col);
  }
  return [...byLag.values()].sort((a, b) => b.lagHours - a.lagHours);
}

/**
 * "¿A qué horizonte predice?": one sentence with an example hour, and a timeline of which inputs are used (with their
 * labels and how old they are at the issue time) and what is predicted. A same-sample task (horizon 0) says it is not a forecast.
 */
export function HorizonBox({ task, card, coverage, rules, scheme, zone, horizons }: Props) {
  const h = task.horizon_hours;
  const regular = coverage.regular !== false;
  const forecast = h > 0 && regular;
  const issue = exampleIssue(coverage, zone);
  const issueMs = Date.parse(issue);
  const validMs = issueMs + h * HOUR;
  const label = labelerFor(rules.variables);
  const units = new Map(rules.variables.map((v) => [v.feature, v.unit]));
  const obs = useAsync((s) => api.observations({ taskId: task.task_id, time: issue }, s), [task.task_id, issue], forecast);
  const columns = obs.status === "ok" ? inputColumns(obs.data, label, units) : [];
  const predicts = predictsText(task, scheme);
  const day = formatDate(issue, zone);

  return (
    <Card title={tr("¿Para cuándo predice?", "What does it predict for?")} className="horizon-box">
      {forecast ? (
        <>
          <p className="lead" data-testid="horizon-sentence">
            {tr(<>Con los datos disponibles a la hora de emisión (p. ej. <strong>{clock(issueMs, zone)}</strong> hora local), el modelo prevé {predicts} para las <strong>{clock(validMs, zone)}</strong> (<strong>+{h} h</strong>).</>,
              <>With the data available at the issue time (e.g. <strong>{clock(issueMs, zone)}</strong> local time), the model predicts {predicts} for <strong>{clock(validMs, zone)}</strong> (<strong>+{h} h</strong>).</>)}
          </p>
          <p className="muted small">
            {tr(`Ejemplo del ${day}.`, `Example from ${day}.`)}{" "}
            {horizons.length > 1 ? tr("Cambia el horizonte con el selector de arriba.", "Change the horizon with the selector above.") : tr("Es el único horizonte disponible por ahora.", "It is the only horizon available for now.")}
          </p>
          {columns.length > 0 ? (
            <ol className="timeline-diagram" aria-label={tr("Datos de entrada según su antigüedad y valor previsto", "Input data by age, and the predicted value")}>
              {columns.map((c) => (
                <li key={c.lagHours} className={c.lagHours <= 0 ? "now" : undefined}>
                  <span className="tl-when">
                    {c.lagHours > 0
                      ? tr(`${clock(issueMs - c.lagHours * HOUR, zone)} · hace ${c.lagHours} h`, `${clock(issueMs - c.lagHours * HOUR, zone)} · ${c.lagHours} h before`)
                      : tr(`${clock(issueMs, zone)} · emisión`, `${clock(issueMs, zone)} · issue`)}
                  </span>
                  <span className="tl-dot" aria-hidden="true" />
                  <ul>
                    {c.inputs.map((i) => (
                      <li key={i.label}>{i.label}</li>
                    ))}
                  </ul>
                </li>
              ))}
              <li className="predicted">
                <span className="tl-when">{clock(validMs, zone)} · +{h} h</span>
                <span className="tl-dot" aria-hidden="true" />
                <ul>
                  <li>
                    <strong>{tr("Se predice:", "Predicted:")}</strong> {predicts}
                  </li>
                </ul>
              </li>
            </ol>
          ) : (
            obs.status === "loading" && <p className="muted">{tr("Preparando el esquema de entradas…", "Preparing the input diagram…")}</p>
          )}
          {columns.length > 0 && (
            <p className="muted small">
              {tr("Las distancias no están a escala. Los datos de calendario (hora y día de la hora prevista) se conocen de antemano.", "Distances are not to scale. Calendar data (hour and day of the predicted time) are known in advance.")}
            </p>
          )}
        </>
      ) : (
        <>
          <p className="lead" data-testid="horizon-sentence">
            {tr(<>Este modelo no mira hacia delante. Estima {predicts} <strong>sobre la misma muestra</strong>, a partir de las otras mediciones tomadas en ella.</>,
              <>This model doesn&apos;t look ahead. It estimates {predicts} <strong>on the same sample</strong>, from the other measurements taken in it.</>)}
          </p>
          <p className="muted small">{tr(`Es ${sameSampleText()}. No hay hora de emisión ni horizonte que elegir.`, `It is ${sameSampleText()}. There is no issue time or horizon to choose.`)}</p>
        </>
      )}
      {forecast && (
        <MoreInfo summary={tr("Cómo se evita usar datos del futuro", "How the model avoids data from the future")}>
          <p>
            {tr(<>El modelo solo usa datos medidos hasta la hora de emisión, más los datos de calendario de la hora prevista, que se conocen de antemano. Se evalúa sobre un periodo posterior al de entrenamiento, con un margen (embargo) de {card.manifest.split.embargo_hours} h entre los dos.</>,
              <>The model only uses data measured up to the issue time, plus the calendar data of the predicted time, which are known in advance. It is evaluated on a period after the training one, with a gap (embargo) of {card.manifest.split.embargo_hours} h between the two.</>)}
          </p>
        </MoreInfo>
      )}
    </Card>
  );
}
