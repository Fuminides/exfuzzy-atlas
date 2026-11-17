/** Where each file lives in the export (docs/static_export.md section 3). Paths are relative to `data/<export_id>/`. */

export const MANIFEST = "manifest.json";
export const DOMAINS = "domains.json.gz";

const gz = (path: string): string => `${path}.json.gz`;

export const entitiesPath = (taskId: string): string => gz(`tasks/${taskId}/entities`);
export const summaryPath = (taskId: string): string => gz(`tasks/${taskId}/summary`);
export const cardPath = (modelId: string): string => gz(`models/${modelId}/card`);
export const rulesPath = (modelId: string): string => gz(`models/${modelId}/rules`);
export const importancePath = (modelId: string): string => gz(`models/${modelId}/importance`);
export const explanationPath = (modelId: string): string => gz(`models/${modelId}/explanation`);
export const metaPath = (modelId: string): string => gz(`models/${modelId}/meta`);

export type ShardKind = "pred" | "fire" | "mem";
export const shardPath = (modelId: string, key: string, kind: ShardKind): string => gz(`models/${modelId}/${key}/${kind}`);

/** `base` is `meta.features[i].input`; the file is `<base>/<day>` for a regular task and `<base>/all` for an irregular one. */
export const inputsPath = (base: string, key: string): string => gz(`${base}/${key}`);

export type AggKind = "day" | "week" | "month" | "year" | "coverage";
export const aggPath = (modelId: string, kind: AggKind, from: string): string => gz(`models/${modelId}/agg/${kind}/${from}`);
export const storiesPath = (modelId: string, kind: AggKind, from: string): string => gz(`models/${modelId}/stories/${kind}/${from}`);
export const whatIfPath = (modelId: string, entityId: string): string => gz(`models/${modelId}/whatif/${entityId}`);

// Montage tasks (format 3, section 15): exact bodies only; the traces of a subject share one file.
export const montagePath = (taskId: string): string => gz(`tasks/${taskId}/montage`);
export const fnirsCardPath = (modelId: string): string => gz(`models/${modelId}/fnirs/card`);
export const fnirsTrialsPath = (modelId: string): string => gz(`models/${modelId}/fnirs/trials`);
/** `s03` for subject 3 (`fmt.trace_shard`). */
export const traceShardPath = (modelId: string, subject: number): string => gz(`models/${modelId}/fnirs/traces/s${String(subject).padStart(2, "0")}`);
