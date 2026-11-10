import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type {
  DomainsResponse,
  EntityCollection,
  ModelCard,
  ModelRules,
  RuleMapResponse,
  RuleTrace,
  SeriesResponse,
} from "../api/types";

// `npm test` runs from apps/web; fixtures live at the repo root.
const dir = resolve(process.cwd(), "../../fixtures/synthetic");
const load = <T>(name: string) => JSON.parse(readFileSync(resolve(dir, name), "utf8")) as T;

export const domains = load<DomainsResponse>("domains.json");
export const entities = load<EntityCollection>("entities_air.json");
export const card = load<ModelCard>("model_card.json");
/** The backend publishes `variables[].label` (v0.5); the synthetic fixture predates it, so the tests give it one. */
export const LABELS: Record<string, string> = { no2_t: "NO₂ actual", wind_speed_t: "Velocidad del viento" };
const rawRules = load<ModelRules>("model_rules.json");
export const rules: ModelRules = { ...rawRules, variables: rawRules.variables.map((v) => ({ ...v, label: LABELS[v.feature] ?? null })) };
export const traces = load<RuleTrace[]>("rule_traces.json");
export const series = load<SeriesResponse[]>("series.json");

export const trace = (entity: string, hourUtc: string): RuleTrace => {
  const t = traces.find((x) => x.entity_id === entity && x.issued_at_utc === `2025-01-15T${hourUtc}:00Z`);
  if (!t) throw new Error(`no fixture trace ${entity} ${hourUtc}`);
  return t;
};

interface RuleMapEntry {
  query: Record<string, string | number>;
  response: RuleMapResponse;
}

/** Rule-map responses produced by the backend (scripts/make_fixtures.py); the client never aggregates. */
export const ruleMaps = load<RuleMapEntry[]>("rule_maps.json");

const TIME_KEYS = ["time", "from", "to"];

/** The golden backend response for a rule-map query string, or undefined if the fixtures lack it. */
export function ruleMapFor(q: URLSearchParams): RuleMapResponse | undefined {
  const matches = (key: string, expected: string | number) => {
    const got = q.get(key);
    if (got === null) return false;
    if (TIME_KEYS.includes(key)) return Date.parse(got) === Date.parse(String(expected));
    return key === "tau" ? Number(got) === Number(expected) : got === String(expected);
  };
  return ruleMaps.find(
    (e) =>
      Object.entries(e.query).every(([k, v]) => matches(k, v)) &&
      [...TIME_KEYS, "tau"].every((k) => q.has(k) === k in e.query),
  )?.response;
}
