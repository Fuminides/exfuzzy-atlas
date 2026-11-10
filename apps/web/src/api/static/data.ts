import { tr } from "../../i18n";
import { ApiError } from "../errors";
import type { DomainsResponse, EntityCollection, EntityFeature, ModelRules, TaskInfo } from "../types";
import * as paths from "./paths";
import type { AggFile, ApiTexts, FireShard, InputsFile, Manifest, MemShard, Meta, PredShard, WhatIfFile } from "./types";
import type { Source } from "./source";

/** The status codes the API answers, as errors the UI already handles. `detail` is the API's own text. */
export const notFound = (detail: string): ApiError => new ApiError(tr(`Sin datos (404): ${detail}`, `No data (404): ${detail}`), 404, detail);
/** `shown` is the same reason in the interface language; without it the API's English `detail` is shown. */
export const unprocessable = (detail: string, shown?: () => string): ApiError =>
  new ApiError(`${tr("Consulta no disponible", "Query not available")} (422): ${shown ? shown() : detail}`, 422, detail);

/** Everything about one model that the builders read, loaded once. */
export interface Model {
  meta: Meta;
  rules: ModelRules;
  entities: EntityCollection;
  schemaVersion: string;
  /** The texts the API writes from contract constants, as the export ships them. */
  texts: ApiTexts;
  /** Entities in the order of `entities.json` (unmodelled ones included). */
  features: readonly EntityFeature[];
  entityIndex: ReadonlyMap<string, number>; // E index of the modelled entities
  entityById: ReadonlyMap<string, EntityFeature>;
  unmodelled: ReadonlySet<string>;
  ruleIndex: ReadonlyMap<string, number>;
  classifier: boolean;
  winningRule: boolean;
  mixture: boolean;
  /** `feature\u0000term` -> position in `meta.mem_pairs` (axis P). */
  pairIndex: ReadonlyMap<string, number>;
  domainOf: ReadonlyMap<string, [number, number] | null>;
}

export const pairKey = (feature: string, term: string): string => `${feature}\u0000${term}`;

function buildModel(meta: Meta, rules: ModelRules, entities: EntityCollection, schemaVersion: string, texts: ApiTexts): Model {
  const unmodelled = new Set(entities.features.filter((f) => f.properties.modelled === false).map((f) => f.properties.entity_id));
  const domainOf = new Map<string, [number, number] | null>();
  for (const v of rules.variables) {
    const d = v.domain as unknown;
    domainOf.set(v.feature, Array.isArray(d) && d.length === 2 ? [Number(d[0]), Number(d[1])] : null);
  }
  return {
    meta,
    rules,
    entities,
    schemaVersion,
    texts,
    features: entities.features,
    entityIndex: new Map(meta.entities.map((id, e) => [id, e])),
    entityById: new Map(entities.features.map((f) => [f.properties.entity_id, f])),
    unmodelled,
    ruleIndex: new Map(meta.rules.map((id, r) => [id, r])),
    classifier: meta.family === "winning_rule_classifier" || meta.family === "rule_mixture_classifier",
    winningRule: meta.family === "winning_rule_classifier",
    mixture: meta.family === "rule_mixture_classifier",
    pairIndex: new Map(meta.mem_pairs.map(([f, t], p) => [pairKey(f, t), p])),
    domainOf,
  };
}

/**
 * Typed access to the files of an export. A missing file is `null` for the data shards (the builders answer "no
 * data") and a 404 for the exact bodies, as the API does.
 */
export class Data {
  private readonly memo = new Map<string, Promise<unknown>>();

  constructor(readonly source: Source) {}

  /** Computes once per key; a failure is not remembered. */
  private once<T>(key: string, make: () => Promise<T>): Promise<T> {
    let hit = this.memo.get(key) as Promise<T> | undefined;
    if (!hit) {
      hit = make();
      this.memo.set(key, hit);
      hit.catch(() => this.memo.delete(key));
    }
    return hit;
  }

  /** A file that may be missing. */
  file<T>(path: string, signal?: AbortSignal): Promise<T | null> {
    return this.source.json(path, signal) as Promise<T | null>;
  }

  /** An exact API body: missing means 404. */
  async exact<T>(path: string, what: string, signal?: AbortSignal): Promise<T> {
    const body = await this.file<T>(path, signal);
    if (body === null) throw notFound(what);
    return body;
  }

  manifest(signal?: AbortSignal): Promise<Manifest | null> {
    return this.file<Manifest>(paths.MANIFEST, signal);
  }

  domains(signal?: AbortSignal): Promise<DomainsResponse> {
    return this.exact<DomainsResponse>(paths.DOMAINS, "no domains in the export", signal);
  }

  /** The task as the registry lists it, and its domain. */
  async task(taskId: string, signal?: AbortSignal): Promise<{ task: TaskInfo; domain: string }> {
    for (const d of (await this.domains(signal)).domains) {
      const task = d.tasks.find((t) => t.task_id === taskId);
      if (task) return { task, domain: d.domain };
    }
    throw notFound(`unknown task_id ${taskId}`);
  }

  async modelOfTask(taskId: string, signal?: AbortSignal): Promise<string> {
    const { task } = await this.task(taskId, signal);
    if (!task.model_id) throw notFound(`task ${taskId} has no model`);
    return task.model_id;
  }

  meta(modelId: string, signal?: AbortSignal): Promise<Meta> {
    return this.once(`meta:${modelId}`, async () => this.exact<Meta>(paths.metaPath(modelId), `unknown model_id ${modelId}`, signal));
  }

  model(modelId: string, signal?: AbortSignal): Promise<Model> {
    return this.once(`model:${modelId}`, async () => {
      const meta = await this.meta(modelId, signal);
      const [rules, entities, manifest] = await Promise.all([
        this.exact<ModelRules>(paths.rulesPath(modelId), `unknown model_id ${modelId}`, signal),
        this.exact<EntityCollection>(paths.entitiesPath(meta.task_id), `no entities for task ${meta.task_id}`, signal),
        this.manifest(signal),
      ]);
      if (!manifest?.texts) throw new ApiError(tr("El export no incluye los textos de la API (manifest.texts)", "The export has no API texts (manifest.texts)"), null);
      return buildModel(meta, rules, entities, manifest.schema_version ?? rules.schema_version ?? "", manifest.texts);
    });
  }

  /** The pred shard of `key`, or null when the model published no row there. */
  pred(h: Model, key: string, signal?: AbortSignal): Promise<PredShard | null> {
    return h.meta.keys.includes(key) ? this.file<PredShard>(paths.shardPath(h.meta.model_id, key, "pred"), signal) : Promise.resolve(null);
  }

  fire(h: Model, key: string, signal?: AbortSignal): Promise<FireShard | null> {
    return this.file<FireShard>(paths.shardPath(h.meta.model_id, key, "fire"), signal);
  }

  mem(h: Model, key: string, signal?: AbortSignal): Promise<MemShard | null> {
    return this.file<MemShard>(paths.shardPath(h.meta.model_id, key, "mem"), signal);
  }

  inputs(h: Model, feature: number, key: string, signal?: AbortSignal): Promise<InputsFile | null> {
    return this.file<InputsFile>(paths.inputsPath(h.meta.features[feature]!.input, key), signal);
  }

  agg(h: Model, kind: paths.AggKind, from: string, signal?: AbortSignal): Promise<AggFile | null> {
    return this.file<AggFile>(paths.aggPath(h.meta.model_id, kind, from), signal);
  }

  whatif(h: Model, entityId: string, signal?: AbortSignal): Promise<WhatIfFile | null> {
    return this.file<WhatIfFile>(paths.whatIfPath(h.meta.model_id, entityId), signal);
  }
}
