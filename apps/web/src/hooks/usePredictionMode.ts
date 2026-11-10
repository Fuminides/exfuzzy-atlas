import { useEffect, useState } from "react";
import { api, seriesWindow } from "../api/client";
import type { ModelCard, TaskInfo } from "../api/types";
import { addHours } from "../lib/format";
import type { Mode } from "../lib/mode";
import { seriesBlock, type TimeWindow } from "../lib/windows";
import { useAsync } from "./useAsync";

interface Args {
  mode: Mode;
  task: TaskInfo | undefined;
  irregular: boolean;
  coverage: ModelCard["coverage"] | null;
  entityId: string | null;
  unmodelledSelected: boolean;
  /** The selected issue time (not the debounced one). */
  time: string | null;
  fetchTime: string | null;
  window: TimeWindow | null;
}

/** Prediction mode: all entities' predictions for the time or window, and the selected entity's series. */
export function usePredictionMode({ mode, task, irregular, coverage, entityId, unmodelledSelected, time, fetchTime, window }: Args) {
  const [scaleMax, setScaleMax] = useState(0);
  // ONE request for all entities (an issue time, or each entity's latest sample in the window).
  const predictions = useAsync(
    (s) =>
      api.predictions(irregular ? { taskId: task!.task_id, from: window!.from, to: window!.to } : { taskId: task!.task_id, time: fetchTime! }, s),
    [task?.task_id, irregular ? window?.from : fetchTime, irregular ? window?.to : null],
    mode === "prediction" && task !== undefined && (irregular ? window !== null : fetchTime !== null),
  );
  // Only the selected entity's series is loaded (the chart): a 6-day block of issue times around the selected one.
  const block = !irregular && time ? seriesBlock(time) : null;
  const selectedSeriesState = useAsync(
    (s) => seriesWindow({ taskId: task!.task_id, entityId: entityId!, from: block!.from, to: block!.to }, s),
    [task?.task_id, entityId, block?.from, block?.to],
    mode === "prediction" && !irregular && task !== undefined && entityId !== null && !unmodelledSelected && block !== null,
  );
  // Irregular tasks: every sample of the selected point over the whole coverage (a few dozen), as a per-sample chart.
  const pointSamples = useAsync(
    (s) =>
      seriesWindow({ taskId: task!.task_id, entityId: entityId!, from: coverage!.issued_from_utc, to: addHours(coverage!.issued_to_utc, 1) }, s),
    [task?.task_id, entityId, coverage?.issued_from_utc, coverage?.issued_to_utc],
    irregular && mode === "prediction" && task !== undefined && entityId !== null && !unmodelledSelected && coverage !== null,
  );
  const windowMax =
    predictions.status === "ok"
      ? Math.max(1, ...predictions.data.features.flatMap((f) => [f.properties.observed ?? null, f.properties.prediction]).filter((v): v is number => v !== null))
      : 0;
  useEffect(() => {
    // The colour scale only grows while browsing, so colours do not jump back and forth between windows.
    if (windowMax > 0) setScaleMax((old) => Math.max(old, windowMax));
  }, [windowMax]);
  return { predictions, block, selectedSeriesState, pointSamples, scaleMax, windowMax };
}
