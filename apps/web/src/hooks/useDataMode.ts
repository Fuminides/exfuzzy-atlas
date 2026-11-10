import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { TaskInfo } from "../api/types";
import type { Mode } from "../lib/mode";
import type { TimeWindow } from "../lib/windows";
import { useAsync } from "./useAsync";

interface Args {
  mode: Mode;
  task: TaskInfo | undefined;
  irregular: boolean;
  fetchTime: string | null;
  window: TimeWindow | null;
}

/** Data mode: the observed target at its valid time and the model's inputs, same time semantics as predictions. */
export function useDataMode({ mode, task, irregular, fetchTime, window }: Args) {
  const [dataMax, setDataMax] = useState(0);
  const observations = useAsync(
    (s) =>
      api.observations(irregular ? { taskId: task!.task_id, from: window!.from, to: window!.to } : { taskId: task!.task_id, time: fetchTime! }, s),
    [task?.task_id, irregular ? window?.from : fetchTime, irregular ? window?.to : null],
    mode === "data" && task !== undefined && (irregular ? window !== null : fetchTime !== null),
  );
  const observedMax =
    observations.status === "ok"
      ? Math.max(1, ...observations.data.features.map((f) => f.properties.target?.value ?? null).filter((v): v is number => v !== null))
      : 0;
  useEffect(() => {
    if (observedMax > 0) setDataMax((old) => Math.max(old, observedMax));
  }, [observedMax]);
  return { observations, dataMax, observedMax };
}
