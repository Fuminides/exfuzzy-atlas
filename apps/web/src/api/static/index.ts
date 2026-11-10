import { staticDataBase } from "../../lib/dataMode";
import { tr } from "../../i18n";
import type { Api } from "../client";
import { ApiError } from "../errors";
import { httpSource, type Source } from "./source";
import { StaticStore } from "./store";

let store: StaticStore | null = null;

/** The store over the export the site was built with (made on first use). */
export function staticStore(): StaticStore {
  store ??= new StaticStore(httpSource(staticDataBase()));
  return store;
}

/** Point the static API at another source (tests, and the parity test's reader of an export directory). */
export function useStaticSource(source: Source): StaticStore {
  store = new StaticStore(source);
  return store;
}

/**
 * The static `api`: the same methods and types as the live one (`Api` is `typeof` the live object, so TypeScript
 * keeps them identical), answered from the precomputed export instead of a server.
 */
export const staticApi: Api = {
  // The footer label that used it is hidden in static mode.
  health: () => Promise.reject(new ApiError(tr("No hay servidor que consultar", "There is no server to ask"), 404)),
  domains: (signal) => staticStore().domains(signal),
  entities: (domain, taskId, signal) => staticStore().entities(domain, taskId, signal),
  modelCard: (modelId, signal) => staticStore().modelCard(modelId, signal),
  modelRules: (modelId, signal) => staticStore().modelRules(modelId, signal),
  importance: (modelId, signal) => staticStore().importance(modelId, signal),
  explanation: (modelId, signal) => staticStore().explanation(modelId, signal),
  summary: (taskId, signal) => staticStore().summary(taskId, signal),
  ruleMap: (q, signal) => staticStore().ruleMap(q, signal),
  ruleTrace: (entityId, modelId, at, signal) => staticStore().ruleTrace(entityId, modelId, at, signal),
  predictions: (q, signal) => staticStore().predictions(q, signal),
  observations: (q, signal) => staticStore().observations(q, signal),
  ruleTerritories: (q, signal) => staticStore().ruleTerritories(q, signal),
  ruleStories: (q, signal) => staticStore().ruleStories(q, signal),
  scenario: (body, signal) => staticStore().scenario(body, signal),
  series: (q, signal) => staticStore().series(q, signal),
};
