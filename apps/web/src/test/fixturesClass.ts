import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { DomainsResponse, EntityCollection, ModelCard, ModelRules, RuleMapResponse, RuleTrace, SeriesResponse, TargetScheme, MetricsReport } from "../api/types";
import type { FakeData } from "./fakeApi";

/**
 * Golden responses of the SYNTHETIC winning-rule classifier (`make publish-demo-class`, artifacts-mode API, contract
 * v0.3), saved by `scripts/save-class-fixtures.mjs`. The scheme is invented ("low/mid/high"), not the official ICA.
 */
const dir = resolve(process.cwd(), "src/test/fixtures-class");
const load = <T>(name: string) => JSON.parse(readFileSync(resolve(dir, name), "utf8")) as T;

export const domains = load<DomainsResponse>("domains.json");
export const entities = load<EntityCollection>("entities.json");
export const card = load<ModelCard>("card.json");
const rawRules = load<ModelRules>("rules.json");
export const LABELS: Record<string, string> = { y_t: "Nivel actual", y_lag3: "Nivel hace 3 h", exo_t: "Variable exógena", hour: "Hora del día" };
export const rules: ModelRules = { ...rawRules, variables: rawRules.variables.map((v) => ({ ...v, label: LABELS[v.feature] ?? null })) };
export const series = load<SeriesResponse[]>("series.json");
export const traces = load<RuleTrace[]>("rule_traces.json");
const ruleMaps = load<{ query: Record<string, string>; response: RuleMapResponse }[]>("rule_maps.json");

/** Real ICA model (`exfuzzy-madrid_no2_h6-ica-v1-seed0`): its scheme (4 classes, the last merged) and test-period metrics. */
export const icaScheme = load<TargetScheme>("ica_scheme.json");
export const icaMetrics = load<MetricsReport>("ica_metrics.json");

export const scheme = card.target_scheme!;
/** First issue time of the coverage (the app starts here). */
export const FIRST_ISSUE = "2024-01-05T00:00:00Z";

export const trace = (entity: string, issued: string): RuleTrace => {
  const t = traces.find((x) => x.entity_id === entity && x.issued_at_utc === issued);
  if (!t) throw new Error(`no class fixture trace ${entity} ${issued}`);
  return t;
};

export function ruleMapFor(q: URLSearchParams): RuleMapResponse | undefined {
  return ruleMaps.find(
    (e) => e.query.rule_id === q.get("rule_id") && e.query.metric === q.get("metric") && Date.parse(e.query.time!) === Date.parse(q.get("time") ?? ""),
  )?.response;
}

/** Data for `installApi(overrides, classifierData)`. */
export const classifierData = (): Partial<FakeData> => ({ domains, entities, card, rules, series, traces, ruleMapFor });
