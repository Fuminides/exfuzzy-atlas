import type {
  DomainsResponse, EntityCollection, ModelCard, ModelExplanation, ModelRules, ObservationsResponse, PredictionsResponse,
  RuleImportanceResponse, RuleMapMetric, RuleMapResponse, RuleStoriesResponse, RuleTerritoriesResponse, RuleTrace, ScenarioRequest,
  ScenarioResponse, SeriesResponse, SummaryResponse, TerritoryMeasure,
} from "../types";
import { tr } from "../../i18n";
import { DEFAULT_TAU } from "./constants";
import { close } from "./numbers";
import { Data, notFound, unprocessable } from "./data";
import { observations } from "./observations";
import * as paths from "./paths";
import { predictions } from "./predictions";
import { ruleMap, type RuleMapQuery } from "./ruleMap";
import { scenario, whatIfSweeps } from "./scenario";
import { series, type SeriesQuery } from "./series";
import type { Source } from "./source";
import { ruleTerritories } from "./territories";
import { ruleTrace } from "./trace";
import type { Meta, WhatIfSweeps } from "./types";
import { checkRuleMap, checkSeries, checkTau, checkTimeOrWindow, checkWindow } from "./validate";
import { requireWindow, windowKinds } from "./windows";

/** What the export holds for a model: the UI offers nothing outside it. */
export interface ExportSupport {
  taus: readonly number[];
  windowKinds: readonly ("day" | "week" | "month" | "year" | "coverage")[];
  /** The single τ the stories are exported at. */
  storiesTau: number;
  /** Is there a what-if sweep for this model? */
  whatIf: boolean;
  /** The EXPORTED range (the card's coverage is the model's full one): the timeline and the controls offer this and no more. */
  coverage: { issued_from_utc: string; issued_to_utc: string; regular: boolean; step_hours: number; clip: boolean };
}

export const supportOf = (meta: Meta): ExportSupport => ({
  taus: meta.taus,
  windowKinds: windowKinds(meta),
  storiesTau: meta.stories?.tau ?? DEFAULT_TAU,
  whatIf: meta.whatif != null,
  coverage: { ...{ issued_from_utc: meta.coverage.from, issued_to_utc: meta.coverage.to }, regular: meta.regular, step_hours: meta.step_hours, clip: meta.period != null },
});

/**
 * Every response of the API, rebuilt from the files of a static export (docs/static_export.md). The methods have the
 * arguments of `api.*` (`api/client.ts`) so a parity test can replay the same request against the golden samples.
 * Errors are `ApiError`s with the API's status: 404 where a file is missing, 422 for a query the export does not hold.
 */
export class StaticStore {
  readonly data: Data;

  constructor(source: Source) {
    this.data = new Data(source);
  }

  // ---- exact bodies

  domains(signal?: AbortSignal): Promise<DomainsResponse> {
    return this.data.domains(signal);
  }

  /** `served_task` of `atlas_api/store.py`. */
  async entities(domain: string, taskId: string | undefined, signal?: AbortSignal): Promise<EntityCollection> {
    const served = (await this.data.domains(signal)).domains.flatMap((d) => d.tasks.map((t) => ({ task: t.task_id, domain: d.domain })));
    let chosen: string | undefined = taskId;
    if (taskId !== undefined) {
      const own = served.find((s) => s.task === taskId);
      if (!own) throw notFound(`unknown task_id ${taskId}`);
      if (own.domain !== domain) throw unprocessable(`task_id ${taskId} belongs to domain ${own.domain}, not ${domain}`);
    } else {
      const mine = served.filter((s) => s.domain === domain).map((s) => s.task).sort();
      if (mine.length > 1) throw unprocessable(`domain ${domain} has ${mine.length} tasks (${mine.join(", ")}): pass task_id`);
      chosen = mine[0];
    }
    if (chosen === undefined) throw notFound(`no entities for domain ${domain}`);
    return this.data.exact<EntityCollection>(paths.entitiesPath(chosen), `unknown task_id ${chosen}`, signal);
  }

  modelCard(modelId: string, signal?: AbortSignal): Promise<ModelCard> {
    return this.data.exact<ModelCard>(paths.cardPath(modelId), `unknown model_id ${modelId}`, signal);
  }

  modelRules(modelId: string, signal?: AbortSignal): Promise<ModelRules> {
    return this.data.exact<ModelRules>(paths.rulesPath(modelId), `unknown model_id ${modelId}`, signal);
  }

  importance(modelId: string, signal?: AbortSignal): Promise<RuleImportanceResponse> {
    return this.data.exact<RuleImportanceResponse>(paths.importancePath(modelId), `${modelId} has no importance`, signal);
  }

  explanation(modelId: string, signal?: AbortSignal): Promise<ModelExplanation> {
    return this.data.exact<ModelExplanation>(paths.explanationPath(modelId), `${modelId} has no explanation`, signal);
  }

  summary(taskId: string, signal?: AbortSignal): Promise<SummaryResponse> {
    return this.data.exact<SummaryResponse>(paths.summaryPath(taskId), `${taskId} has no summary`, signal);
  }

  // ---- rebuilt from shards

  async predictions(q: { taskId: string; time?: string; from?: string; to?: string }, signal?: AbortSignal): Promise<PredictionsResponse> {
    checkTimeOrWindow(q.time, q.from, q.to);
    const h = await this.data.model(await this.data.modelOfTask(q.taskId, signal), signal);
    return predictions(this.data, h, q, signal);
  }

  async observations(q: { taskId: string; time?: string; from?: string; to?: string }, signal?: AbortSignal): Promise<ObservationsResponse> {
    checkTimeOrWindow(q.time, q.from, q.to);
    const h = await this.data.model(await this.data.modelOfTask(q.taskId, signal), signal);
    return observations(this.data, h, q, signal);
  }

  async ruleMap(q: { modelId: string; ruleId: string; metric: RuleMapMetric; time?: string; from?: string; to?: string; tau?: number }, signal?: AbortSignal): Promise<RuleMapResponse> {
    checkRuleMap(q);
    const h = await this.data.model(q.modelId, signal);
    if (!h.ruleIndex.has(q.ruleId)) throw notFound(`unknown rule_id ${q.ruleId} for ${q.modelId}`);
    return ruleMap(this.data, h, q as RuleMapQuery, signal);
  }

  async ruleTerritories(q: { modelId: string; from: string; to: string; measure: TerritoryMeasure; tau?: number }, signal?: AbortSignal): Promise<RuleTerritoriesResponse> {
    checkWindow(q.from, q.to);
    const tau = q.tau ?? DEFAULT_TAU;
    checkTau(tau);
    return ruleTerritories(this.data, await this.data.model(q.modelId, signal), { ...q, tau }, signal);
  }

  /** Only the stories the export holds: its window kinds, at its τ and limit. */
  async ruleStories(q: { modelId: string; from: string; to: string; tau?: number; limit?: number }, signal?: AbortSignal): Promise<RuleStoriesResponse> {
    checkWindow(q.from, q.to);
    const tau = q.tau ?? DEFAULT_TAU;
    checkTau(tau);
    const h = await this.data.model(q.modelId, signal);
    const fixed = h.meta.stories;
    const limit = q.limit ?? 10;
    if (!fixed || !close(tau, fixed.tau) || limit !== fixed.limit) {
      throw unprocessable(`stories are precomputed at tau ${fixed?.tau ?? DEFAULT_TAU} and limit ${fixed?.limit ?? 10} only`, () =>
        tr(`las historias están calculadas con τ = ${fixed?.tau ?? DEFAULT_TAU}`, `the stories are computed at τ = ${fixed?.tau ?? DEFAULT_TAU}`),
      );
    }
    const ref = requireWindow(h.meta, q.from, q.to);
    return this.data.exact<RuleStoriesResponse>(paths.storiesPath(q.modelId, ref.kind, ref.from), `no stories for ${q.modelId} in [${q.from}, ${q.to})`, signal);
  }

  async ruleTrace(entityId: string, modelId: string, at: string, signal?: AbortSignal): Promise<RuleTrace> {
    return ruleTrace(this.data, await this.data.model(modelId, signal), entityId, at, signal);
  }

  async series(q: SeriesQuery, signal?: AbortSignal): Promise<SeriesResponse> {
    checkSeries(q.from, q.to);
    const h = await this.data.model(await this.data.modelOfTask(q.taskId, signal), signal);
    return series(this.data, h, q, signal);
  }

  async scenario(body: ScenarioRequest, signal?: AbortSignal): Promise<ScenarioResponse> {
    return scenario(this.data, await this.data.model(body.model_id, signal), body, signal);
  }

  // ---- what the export holds (the UI offers nothing else)

  async support(modelId: string, signal?: AbortSignal): Promise<ExportSupport> {
    return supportOf(await this.data.meta(modelId, signal));
  }

  /** The what-if instants and values of one entity; null when the export holds none for it. */
  async whatIf(modelId: string, entityId: string, signal?: AbortSignal): Promise<WhatIfSweeps | null> {
    return whatIfSweeps(this.data, await this.data.model(modelId, signal), entityId, signal);
  }
}

