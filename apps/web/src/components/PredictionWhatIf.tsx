import type { LinguisticVariable, RuleTrace, TargetScheme } from "../api/types";
import type { AsyncState } from "../hooks/useAsync";
import { classTitle } from "../lib/classifier";
import type { DomainUi } from "../lib/domainUi";
import { sameInstant } from "../lib/format";
import { StateMessage } from "./StateMessage";
import { WhatIfPanel } from "./WhatIfPanel";
import { tr } from "../i18n";
import type { TimeWindow } from "../lib/windows";

/** The way into What-if from a selected entity and time in Prediction mode. */
export function WhatIfEntry({ onOpen }: { onOpen: () => void }) {
  return (
    <p data-testid="whatif-entry">
      <button type="button" onClick={onOpen}>
        {tr("¿Y si…?", "What if…?")}
      </button>{" "}
      <span className="muted">{tr("Prueba entradas distintas en este registro. Es la respuesta del modelo a entradas hipotéticas.", "Try different inputs on this record. What you see is the model's answer to hypothetical inputs.")}</span>
    </p>
  );
}

interface Props {
  modelId: string;
  entityId: string;
  entityName: string;
  /** Issue time of the published row the scenario starts from. */
  at: string;
  variables: readonly LinguisticVariable[];
  trace: AsyncState<RuleTrace> & { reload: () => void };
  classifier: boolean;
  /** Mixture of rules (v0.7): the scenario names the rule that adds the most, not a winning rule. */
  mixture?: boolean;
  /** What the scenario recalculates is named as the prediction view names it. */
  scheme: TargetScheme | null;
  relativeScheme: boolean;
  ui: DomainUi;
  label: string;
  unit: string;
  irregular: boolean;
  onClose: () => void;
  /** Static export: go to the nearest instant that has a sweep, among the samples of `within` for an irregular task. */
  onGoTo?: (instant: string) => void;
  within?: TimeWindow | null;
}

/**
 * Prediction mode, side panel while What-if is open: the existing What-if panel, prefilled with the selected entity, the
 * selected time and that row's observed inputs, and a way back to the prediction view. The selection is not touched.
 */
export function PredictionWhatIf({ modelId, entityId, entityName, at, variables, trace, classifier, mixture = false, scheme, relativeScheme, ui, label, unit, irregular, onClose, onGoTo, within }: Props) {
  // "categoría ICA prevista de NO₂" (Madrid), "nivel de demanda ... previsto" (NYC), "NO₂ previsto (µg/m³)"; never a risk.
  const outputName = scheme
    ? ui.levelTitle && relativeScheme
      ? tr(`${ui.levelTitle} previsto`, `predicted ${ui.levelTitle}`)
      : classTitle(scheme, label)
    : tr(`${label} ${irregular ? "estimado" : "previsto"} (${unit})`, `${irregular ? "estimated" : "predicted"} ${label} (${unit})`);
  return (
    <section className="prediction" aria-label={tr("¿Y si…? sobre la predicción", "What if…? on the prediction")} data-testid="prediction-whatif">
      <p>
        <button type="button" onClick={onClose} data-testid="whatif-back">
          {tr("← Volver a la predicción", "← Back to the prediction")}
        </button>
      </p>
      <p className="muted">
        {tr(<>Escenario sobre el registro publicado de {entityName} en la emisión <code>{at}</code>. Salida que se recalcula: {outputName}. Es la respuesta del modelo a las entradas modificadas.</>,
          <>Scenario on the published record of {entityName} at issue <code>{at}</code>. Recalculated output: {outputName}. This is the model&apos;s answer to the modified inputs.</>)}
      </p>
      {trace.status === "error" && (
        <StateMessage kind="error" onRetry={trace.reload}>{tr(`No se pudo cargar el registro de ${entityName}: `, `Could not load the record of ${entityName}: `)}{trace.error.message}</StateMessage>
      )}
      {trace.status !== "error" && (
        <WhatIfPanel
          key={`${modelId}|${entityId}|${at}`}
          modelId={modelId}
          entityId={entityId}
          entityName={entityName}
          at={at}
          variables={variables}
          baseline={trace.status === "ok" && trace.data.entity_id === entityId && sameInstant(trace.data.issued_at_utc, at) ? trace.data : null}
          classifier={classifier}
          mixture={mixture}
          onGoTo={onGoTo}
          within={within}
        />
      )}
    </section>
  );
}
