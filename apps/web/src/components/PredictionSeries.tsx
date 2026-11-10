import type { RuleDefinition, SeriesResponse, TargetScheme } from "../api/types";
import type { AsyncState } from "../hooks/useAsync";
import { sameSampleText } from "../lib/format";
import type { TimeWindow } from "../lib/windows";
import { DecidedBy } from "./DecidedBy";
import { ClassSeriesChart } from "./ClassSeriesChart";
import { SampleChart } from "./SampleChart";
import { SeriesChart } from "./SeriesChart";
import { StateMessage } from "./StateMessage";
import { UnmodelledNotice } from "./UnmodelledNotice";
import { tr } from "../i18n";

type Request<T = unknown> = AsyncState<T> & { reload: () => void };

interface Props {
  irregular: boolean;
  scheme: TargetScheme | null;
  label: string;
  unit: string;
  noun: string;
  /** The selected entity; `unmodelled` entities have no series ("sin modelo"). */
  entityId: string | null;
  nameOf: (id: string) => string;
  unmodelled: boolean;
  predictions: Request;
  selectedSeriesState: Request<SeriesResponse>;
  pointSamples: Request<SeriesResponse>;
  /** The selected issue time, marked on the chart. */
  time: string;
  window: TimeWindow | null;
  /** `WhatIfEntry`, when a scenario can start from the selected entity and time. */
  whatIfEntry?: React.ReactNode;
  /** The rule that decided the selected entity's prediction at the time on screen, and where to read it. */
  decidedBy?: string | null;
  /** The model's rules carry no weight (`rule_weighting: "none"`): the rule that fires most decides. */
  unweighted?: boolean;
  /** Mixture of rules (v0.7): the rule is the one that adds the most to the predicted category, with its share and that category. */
  mixture?: boolean;
  topShare?: number | null;
  predictedLabel?: string | null;
  rules?: readonly RuleDefinition[];
  onOpenRule?: (ruleId: string) => void;
}

/** Prediction mode, side panel: the selected entity's observed and predicted series. */
export function PredictionSeries(p: Props) {
  const { irregular, scheme, label, unit, noun, entityId, nameOf, unmodelled, predictions, selectedSeriesState, pointSamples, time, window } = p;
  const selectedSeries = selectedSeriesState.status === "ok" ? selectedSeriesState.data : undefined;
  return (
    <section className="prediction" aria-label={tr("Serie observada y predicha", "Observed and predicted series")}>
      {irregular ? (
        <>
          <h2>{tr(`Observado vs predicho por muestra (${label}, ${unit})`, `Observed vs predicted per sample (${label}, ${unit})`)}</h2>
          <p className="muted" data-testid="same-sample-note">
            {tr(`Cada muestra es una pareja observado/predicho: ${sameSampleText()}.`, `Each sample is an observed/predicted pair: ${sameSampleText()}.`)}
          </p>
        </>
      ) : scheme ? (
        <>
          <h2>{tr(`Observado vs categoría prevista (${label}${unit ? `, ${unit}` : ""})`, `Observed vs predicted category (${label}${unit ? `, ${unit}` : ""})`)}</h2>
          <p className="muted">{tr("Valor observado y categoría prevista por el modelo.", "Observed value and category predicted by the model.")}</p>
        </>
      ) : (
        <>
          <h2>{tr(`Observado vs predicho (${label}, ${unit})`, `Observed vs predicted (${label}, ${unit})`)}</h2>
          <p className="muted">{tr("Valores de concentración.", "Concentration values.")}</p>
        </>
      )}
      {/* The rule that decided this prediction (in a mixture, the one that adds the most) ties the map to Patrones: it goes first, before the what-if entry. */}
      {entityId && !unmodelled && p.decidedBy && p.rules && <DecidedBy ruleId={p.decidedBy} rules={p.rules} scheme={scheme} onOpenRule={p.onOpenRule} unweighted={p.unweighted} mixture={p.mixture} topShare={p.topShare} predictedLabel={p.predictedLabel} />}
      {p.whatIfEntry}
      {predictions.status === "loading" && <StateMessage kind="loading">{tr("Cargando predicciones…", "Loading predictions…")}</StateMessage>}
      {predictions.status === "error" && (
        <StateMessage kind="error" onRetry={predictions.reload}>{tr("No se pudieron cargar las predicciones: ", "Could not load the predictions: ")}{predictions.error.message}</StateMessage>
      )}
      {predictions.status === "ok" && !entityId && <p className="muted">{tr(`Elige ${irregular ? "un" : "una"} ${noun} para ver su serie.`, `Pick a ${noun} to see its series.`)}</p>}
      {entityId && unmodelled && <UnmodelledNotice name={nameOf(entityId)} noun={noun} />}
      {!irregular && entityId && !unmodelled && selectedSeriesState.status === "loading" && <StateMessage kind="loading">{tr("Cargando la serie…", "Loading the series…")}</StateMessage>}
      {!irregular && entityId && !unmodelled && selectedSeriesState.status === "error" && (
        <StateMessage kind="error" onRetry={selectedSeriesState.reload}>{tr(`No se pudo cargar la serie de ${nameOf(entityId)}: `, `Could not load the series of ${nameOf(entityId)}: `)}{selectedSeriesState.error.message}</StateMessage>
      )}
      {irregular && entityId && !unmodelled && pointSamples.status === "loading" && <StateMessage kind="loading">{tr("Cargando muestras…", "Loading samples…")}</StateMessage>}
      {irregular && entityId && !unmodelled && pointSamples.status === "error" && (
        <StateMessage kind="error" onRetry={pointSamples.reload}>{tr("No se pudieron cargar las muestras: ", "Could not load the samples: ")}{pointSamples.error.message}</StateMessage>
      )}
      {irregular && entityId && !unmodelled && pointSamples.status === "ok" && (
        <>
          <h3>{nameOf(entityId)}</h3>
          <SampleChart series={pointSamples.data} window={window} />
        </>
      )}
      {!irregular && selectedSeries && (
        <>
          <h3>{nameOf(selectedSeries.entity_id)}</h3>
          {scheme ? <ClassSeriesChart series={selectedSeries} scheme={scheme} selectedIssue={time} /> : <SeriesChart series={selectedSeries} selectedIssue={time} />}
        </>
      )}
    </section>
  );
}
