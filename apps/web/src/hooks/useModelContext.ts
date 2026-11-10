import { api } from "../api/client";
import type { DomainInfo, TaskInfo } from "../api/types";
import { isClassifier, schemeOf } from "../lib/classifier";
import { DEFAULT_ZONE } from "../lib/format";
import { isIrregular } from "../lib/irregular";
import { isStaticData } from "../lib/dataMode";
import { useAsync } from "./useAsync";
import { useExportSupport } from "./useExportSupport";

/** Optional override; by default the model is the one the API serves for the task (`tasks[].model_id`). */
const CONFIGURED_MODEL_ID: string | undefined = import.meta.env.VITE_MODEL_ID || undefined;

/**
 * What every mode shares: the selected task's entities (a domain may serve several tasks, so never the domain's), the
 * model card and rules, and what is read from them (task type, scheme, coverage, whether the time axis is irregular,
 * the entities' own time zone, the "sin modelo" entities).
 */
export function useModelContext(domain: DomainInfo, task: TaskInfo | undefined) {
  const modelId = CONFIGURED_MODEL_ID ?? task?.model_id ?? null;
  const entities = useAsync((s) => api.entities(domain.domain, task?.task_id, s), [domain.domain, task?.task_id]);
  const card = useAsync((s) => api.modelCard(modelId!, s), [modelId], modelId !== null);
  const rules = useAsync((s) => api.modelRules(modelId!, s), [modelId], modelId !== null);

  // Classification is read from the contract (`task_type`, `inference.family`); the scheme from the model card / rules.
  const classifier = isClassifier(task, rules.status === "ok" ? rules.data : null);
  const scheme = classifier ? schemeOf(card.status === "ok" ? card.data : null, rules.status === "ok" ? rules.data : null) : null;

  // A static export holds a period of the model's coverage (Germany: three months): that range is what the timeline and the
  // controls offer, never the card's, which stays the full published one.
  const support = useExportSupport(modelId);
  const coverage = isStaticData() ? (support?.coverage ?? null) : card.status === "ok" ? card.data.coverage : null;
  // Sample-time tasks have no regular grid: no hourly timeline, window aggregates by default (`coverage.regular`).
  const irregular = isIrregular(card.status === "ok" ? card.data : null);
  const horizon = task?.horizon_hours ?? (card.status === "ok" ? card.data.manifest.horizon_hours : 0);
  // Local time is the entities' own zone (America/New_York for NYC), never assumed to be Madrid.
  const zone = entities.status === "ok" ? (entities.data.features[0]?.properties.timezone ?? "UTC") : DEFAULT_ZONE;

  // `modelled: false` entities are in the geometry file but the model has no data for them ("sin modelo").
  const unmodelledIds = new Set(entities.status === "ok" ? entities.data.features.filter((f) => f.properties.modelled === false).map((f) => f.properties.entity_id) : []);
  const modelRules = rules.status === "ok" ? rules.data.rules : [];

  return { task, modelId, entities, card, rules, classifier, scheme, coverage, irregular, horizon, zone, unmodelledIds, modelRules, support };
}
