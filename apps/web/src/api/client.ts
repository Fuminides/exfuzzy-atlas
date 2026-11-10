import { tr } from "../i18n";
import { isStaticData } from "../lib/dataMode";
import { ApiError } from "./errors";
import { staticApi } from "./static";
import type {
  DomainsResponse,
  EntityCollection,
  Health,
  ModelCard,
  ModelExplanation,
  ModelRules,
  ObservationsResponse,
  PredictionsResponse,
  RuleMapMetric,
  RuleImportanceResponse,
  RuleMapResponse,
  RuleStoriesResponse,
  RuleTerritoriesResponse,
  RuleTrace,
  ScenarioRequest,
  ScenarioResponse,
  SeriesResponse,
  SummaryResponse,
  TerritoryMeasure,
} from "./types";

const BASE: string = import.meta.env.VITE_API_BASE ?? "/api/v1";

export { ApiError };

type Params = Record<string, string | number | undefined>;

/** The `detail` of an error body: FastAPI sends a string for our 4xx, a list of `{loc, msg}` for body validation. */
function detailText(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : ""))
      .filter(Boolean)
      .join("; ");
  }
  return "";
}

async function request<T>(url: string, init: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(tr(`No se pudo contactar con la API (${url})`, `Could not reach the API (${url})`), null);
  }
  if (!response.ok) {
    let detail = "";
    try {
      const body = (await response.json()) as { detail?: unknown };
      detail = detailText(body.detail);
    } catch {
      /* body is not JSON */
    }
    throw new ApiError(tr(`La API respondió ${response.status}`, `The API returned ${response.status}`) + (detail ? `: ${detail}` : ""), response.status);
  }
  return (await response.json()) as T;
}

function urlOf(path: string, params: Params = {}): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) query.set(key, String(value));
  }
  const qs = query.toString();
  return `${BASE}${path}${qs ? `?${qs}` : ""}`;
}

async function get<T>(path: string, params: Params = {}, signal?: AbortSignal): Promise<T> {
  return request<T>(urlOf(path, params), { signal });
}

const ruleTracePath = (entityId: string) => `/entities/${encodeURIComponent(entityId)}/rule-trace`;

/** The exact GET that returns a rule trace: the reproducible example of a "¿Por qué aquí?" panel. */
export const ruleTraceUrl = (entityId: string, modelId: string, at: string): string =>
  urlOf(ruleTracePath(entityId), { model_id: modelId, at });

async function post<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  return request<T>(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
}

const httpApi = {
  health: (signal?: AbortSignal) => get<Health>("/health", {}, signal),
  domains: (signal?: AbortSignal) => get<DomainsResponse>("/domains", {}, signal),
  /** `taskId` is required by the API when the domain serves several tasks (it answers 422 otherwise); always sent. */
  entities: (domain: string, taskId: string | undefined, signal?: AbortSignal) =>
    get<EntityCollection>("/entities", { domain, task_id: taskId }, signal),
  modelCard: (modelId: string, signal?: AbortSignal) =>
    get<ModelCard>(`/models/${encodeURIComponent(modelId)}`, {}, signal),
  modelRules: (modelId: string, signal?: AbortSignal) =>
    get<ModelRules>(`/models/${encodeURIComponent(modelId)}/rules`, {}, signal),
  /** v0.5: how many predictions each rule decides and how often it is right. 404 until the model has its `importance.json`. */
  importance: (modelId: string, signal?: AbortSignal) =>
    get<RuleImportanceResponse>(`/models/${encodeURIComponent(modelId)}/importance`, {}, signal),
  /** v0.6.2: a short text about the rule base, written by an AI from the published files. 404 when the model has none. */
  explanation: (modelId: string, signal?: AbortSignal) =>
    get<ModelExplanation>(`/models/${encodeURIComponent(modelId)}/explanation`, {}, signal),
  /** v0.5: distribution of the observed variable of a task over its history (no model). 404 until `summary.json` exists. */
  summary: (taskId: string, signal?: AbortSignal) => get<SummaryResponse>("/summary", { task_id: taskId }, signal),
  /** `time` is an ISSUE time and only goes with firing_strength; aggregates use [from, to). */
  ruleMap: (
    q: {
      modelId: string;
      ruleId: string;
      metric: RuleMapMetric;
      time?: string;
      from?: string;
      to?: string;
      tau?: number;
    },
    signal?: AbortSignal,
  ) =>
    get<RuleMapResponse>(
      "/rule-map",
      { model_id: q.modelId, rule_id: q.ruleId, metric: q.metric, time: q.time, from: q.from, to: q.to, tau: q.tau },
      signal,
    ),
  ruleTrace: (entityId: string, modelId: string, at: string, signal?: AbortSignal) =>
    get<RuleTrace>(ruleTracePath(entityId), { model_id: modelId, at }, signal),
  /** One `Feature` per entity: an issue `time`, or a window `[from, to)` (each entity's latest sample in it). */
  predictions: (q: { taskId: string; time?: string; from?: string; to?: string }, signal?: AbortSignal) =>
    get<PredictionsResponse>("/predictions", { task_id: q.taskId, time: q.time, from: q.from, to: q.to }, signal),
  /** Data mode: the target observed at `valid_at` and the model's inputs, as published. Same time semantics. */
  observations: (q: { taskId: string; time?: string; from?: string; to?: string }, signal?: AbortSignal) =>
    get<ObservationsResponse>("/observations", { task_id: q.taskId, time: q.time, from: q.from, to: q.to }, signal),
  /** E2: per entity and rule, the three measures over `[from, to)` and the dominant rule of `measure`. */
  ruleTerritories: (
    q: { modelId: string; from: string; to: string; measure: TerritoryMeasure; tau?: number },
    signal?: AbortSignal,
  ) =>
    get<RuleTerritoriesResponse>(
      "/rule-territories",
      { model_id: q.modelId, from: q.from, to: q.to, measure: q.measure, tau: q.tau },
      signal,
    ),
  /** Template stories about activations; `limit` is at most 50 in the API, the UI asks for 10. */
  ruleStories: (
    q: { modelId: string; from: string; to: string; tau?: number; limit?: number },
    signal?: AbortSignal,
  ) =>
    get<RuleStoriesResponse>(
      "/rule-stories",
      { model_id: q.modelId, from: q.from, to: q.to, tau: q.tau, limit: q.limit },
      signal,
    ),
  /** E5: the real inference over the published row with `overrides`; nothing is written. */
  scenario: (body: ScenarioRequest, signal?: AbortSignal) => post<ScenarioResponse>("/scenarios", body, signal),
  /** One page of a series: `[from, to)` by issue time; `next_cursor` of the answer goes back as `cursor`. */
  series: (
    q: { taskId: string; entityId: string; from?: string; to?: string; cursor?: string },
    signal?: AbortSignal,
  ) =>
    get<SeriesResponse>(
      "/series",
      { task_id: q.taskId, entity_id: q.entityId, from: q.from, to: q.to, cursor: q.cursor },
      signal,
    ),
};

/** The API the app talks to: the live one, or (static build) the one rebuilt from the precomputed export. Same methods and types. */
export type Api = typeof httpApi;
export const api: Api = isStaticData() ? staticApi : httpApi;

/** The API pages series at 2,000 points (#59 B1); a window of a few days stays within one page, but the cursor is followed. */
const MAX_SERIES_PAGES = 20;

/** All points of `[from, to)` for one entity, following `next_cursor`. Never asks for a full-coverage series. */
export async function seriesWindow(
  q: { taskId: string; entityId: string; from: string; to: string },
  signal?: AbortSignal,
): Promise<SeriesResponse> {
  let page = await api.series(q, signal);
  const points = [...page.points];
  for (let n = 1; page.next_cursor && n < MAX_SERIES_PAGES; n++) {
    page = await api.series({ ...q, cursor: page.next_cursor }, signal);
    points.push(...page.points);
  }
  return { ...page, points, next_cursor: page.next_cursor ?? null };
}
