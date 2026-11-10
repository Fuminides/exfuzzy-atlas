/** How good a moment is to open a page at (see `useDefaultTime`): kept apart from the hook so tests can mock either. */
import { api } from "../api/client";
import { firingShare, predictedShare } from "../lib/defaultTime";
import { ruleMapQuery } from "../lib/duel";
import { sameInstant } from "../lib/format";

export type Score = (time: string, signal: AbortSignal) => Promise<number | null>;

/** Predicción: the share of entities with a prediction at that issue time (null when the API answers another instant). */
export const predictionScore = (taskId: string): Score => async (time, signal) => {
  const data = await api.predictions({ taskId, time }, signal);
  return sameInstant(time, data.issued_at_utc ?? null) ? predictedShare(data) : null;
};

/** Explorar: the share of entities where the rule fires at ≥ 0.5 at that issue time. */
export const firingScore = (modelId: string, ruleId: string): Score => async (time, signal) =>
  firingShare(await api.ruleMap(ruleMapQuery({ modelId, metric: "firing_strength", time }, ruleId), signal));
