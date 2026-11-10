import { staticStore } from "../api/static";
import type { ExportSupport } from "../api/static/store";
import type { WhatIfSweeps } from "../api/static/types";
import { isStaticData } from "../lib/dataMode";
import { useAsync, type AsyncState } from "./useAsync";

/**
 * What the static export holds for a model (its τ grid, window kinds, the τ of its stories): the controls offer nothing
 * else, so no request can come back as unsupported. null in a live build (nothing to constrain) and while it loads.
 */
export function useExportSupport(modelId: string | null): ExportSupport | null {
  const state = useAsync((s) => staticStore().support(modelId!, s), [modelId], isStaticData() && modelId !== null);
  return state.status === "ok" ? state.data : null;
}

/** The what-if instants and values the export holds for one entity; idle in a live build. `data` null: none for this entity. */
export function useWhatIfSweeps(modelId: string | null, entityId: string | null): AsyncState<WhatIfSweeps | null> & { reload: () => void } {
  return useAsync((s) => staticStore().whatIf(modelId!, entityId!, s), [modelId, entityId], isStaticData() && modelId !== null && entityId !== null);
}
