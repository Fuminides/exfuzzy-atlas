import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { PredictionsResponse } from "../api/types";
import { isStaticData } from "../lib/dataMode";
import type { Mode } from "../lib/mode";
import { useAsync, type AsyncState } from "./useAsync";
import { useWhatIfSweeps } from "./useExportSupport";

interface Args {
  mode: Mode;
  modelId: string | null;
  entityId: string | null;
  unmodelledSelected: boolean;
  irregular: boolean;
  /** The settled issue time (regular tasks) and whether the slider is still being dragged. */
  fetchTime: string | null;
  staleInstant: boolean;
  predictions: AsyncState<PredictionsResponse>;
  answers: (r: PredictionsResponse) => boolean;
  /** Irregular tasks: start of the window on screen, which a picked sample belongs to. */
  windowFrom?: string | null;
}

/**
 * Prediction mode's way into What-if: the scenario starts from the published row of the selected entity. `at` is that
 * row's issue time (the selected one for regular tasks, the entity's own latest sample for irregular ones); it is null
 * while there is nothing to start from, and then the entry is not offered. The selection lives in the workspace, so
 * leaving What-if returns to the prediction view with the same entity and time.
 */
export function useScenarioEntry({ mode, modelId, entityId, unmodelledSelected, irregular, fetchTime, staleInstant, predictions, answers, windowFrom = null }: Args) {
  const [opened, setOpened] = useState(false);
  useEffect(() => {
    if (mode !== "prediction") setOpened(false);
  }, [mode]);

  const sampleAt =
    predictions.status === "ok" && answers(predictions.data)
      ? (predictions.data.features.find((f) => f.properties.entity_id === entityId)?.properties.issued_at_utc ?? null)
      : null;
  // Static export: the scenario can start only from an instant with a sweep, so the entry is offered only for an entity that
  // has some; an irregular task's sample can be picked (the nearest with a sweep) instead of the window's latest one.
  const sweeps = useWhatIfSweeps(modelId, entityId);
  const available = !isStaticData() || (sweeps.status === "ok" && sweeps.data !== null && sweeps.data.at.length > 0);
  const [picked, setPicked] = useState<{ entityId: string | null; windowFrom: string | null; at: string } | null>(null);
  const pickedHere = irregular && picked !== null && picked.entityId === entityId && picked.windowFrom === windowFrom ? picked.at : null;
  const row = irregular ? (pickedHere ?? sampleAt) : staleInstant ? null : fetchTime;
  const at = mode === "prediction" && entityId !== null && !unmodelledSelected ? row : null;
  const open = opened && at !== null;
  // The observed row (inputs and firing) the panel edits a copy of.
  const trace = useAsync((s) => api.ruleTrace(entityId!, modelId!, at!, s), [modelId, entityId, at], open && modelId !== null);
  return {
    at,
    available,
    open,
    trace,
    openWhatIf: () => setOpened(true),
    close: () => setOpened(false),
    pick: (instant: string) => setPicked({ entityId, windowFrom, at: instant }),
  };
}
