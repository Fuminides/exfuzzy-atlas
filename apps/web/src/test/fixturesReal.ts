import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { DomainsResponse, EntityCollection, ModelCard, ModelRules, RuleMapResponse, RuleTrace, SeriesResponse } from "../api/types";
import type { FakeData, FakeSet } from "./fakeApi";

/**
 * Golden responses of the REAL published NYC and Water models (artifacts-mode API, contract v0.3), saved by
 * `scripts/save-real-fixtures.mjs`:
 *   NYC   exfuzzy-nyc_pickups_h1-level-rel7-seed0, data_version nyc-tlc-yellow-2024-04_2025-03-v1, 8 of the 110 zones,
 *         series 2025-03-19T12Z..2025-03-20T12Z, traces at 2025-03-19T23Z (Wednesday 19:00 America/New_York);
 *         zones 35 and 39 have no reference level at that hour ("sin referencia"), 39 and 74 are MultiPolygon.
 *   Water exploratory model exfuzzy-uk_water_do-water-do-chrono-temp-seed0, data_version
 *         uk-wq-ne-x-h-rivers-2015-2025-20261030, 6 of the 195 points, their whole series (irregular sample times),
 *         mean_activation for 2025-12; NE-42500191 has no sample in that month.
 * These are not synthetic: the payloads say `synthetic: false`.
 */
const dir = resolve(process.cwd(), "src/test/fixtures-real");
const load = <T>(...path: string[]) => JSON.parse(readFileSync(resolve(dir, ...path), "utf8")) as T;

export const domains = load<DomainsResponse>("domains.json");

type StoredMap = { query: Record<string, string>; response: RuleMapResponse };

function setOf(name: "nyc" | "water"): FakeSet {
  const maps = load<StoredMap[]>(name, "rule_maps.json");
  return {
    entities: load<EntityCollection>(name, "entities.json"),
    card: load<ModelCard>(name, "card.json"),
    rules: load<ModelRules>(name, "rules.json"),
    series: load<SeriesResponse[]>(name, "series.json"),
    traces: load<RuleTrace[]>(name, "rule_traces.json"),
    ruleMapFor: (q) =>
      maps.find((m) => {
        const same = (k: string) => (m.query[k] === undefined ? q.get(k) === null : Date.parse(m.query[k]!) === Date.parse(q.get(k) ?? "") || m.query[k] === q.get(k));
        return m.query.rule_id === q.get("rule_id") && m.query.metric === q.get("metric") && same("time") && same("from") && same("to");
      })?.response,
  };
}

export const nyc = setOf("nyc");
export const water = setOf("water");

/** NYC: the first issue time of the coverage, and the Wednesday evening the fixtures are cut around. */
export const NYC_FIRST_ISSUE = nyc.card.coverage!.issued_from_utc;
export const NYC_EVENING = "2025-03-19T23:00:00Z";
/** The zone with a class at NYC_EVENING, and the two without a reference level. */
export const NYC_ZONE = "4";
export const NYC_NO_REFERENCE = ["35", "39"] as const;
/** Water: a point with samples in 2025-12, and the one without. */
export const WATER_POINT = water.entities.features[0]!.properties.entity_id;
export const WATER_EMPTY_POINT = water.entities.features[water.entities.features.length - 1]!.properties.entity_id;

/** `installApi(overrides, realData())`: NYC first, Water served next to it; Madrid has no real fixtures here. */
export const realData = (): Partial<FakeData> => ({
  domains: { ...domains, domains: domains.domains.filter((d) => d.domain !== "air") },
  ...nyc,
  extra: [water],
});
