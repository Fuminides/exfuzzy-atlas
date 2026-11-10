import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { AttributionItem, EntityCollection, RuleStoriesResponse, ScenarioRequest, ScenarioResponse } from "../api/types";
import type { FakeSet } from "./fakeApi";

/**
 * Contract v0.4 test data. The golden payloads (stories, scenario) are the ones the backend wrote to
 * `fixtures/synthetic/v04_responses.json`; predictions, observations and territories are derived in `fakeApi.ts`.
 */
const dir = resolve(process.cwd(), "../../fixtures/synthetic");
type Golden = { method: string; path: string; query: Record<string, string>; body?: ScenarioRequest; response: unknown };
const goldens = JSON.parse(readFileSync(resolve(dir, "v04_responses.json"), "utf8")) as Golden[];

export const storiesGolden = goldens.find((g) => g.path === "/api/v1/rule-stories")!.response as RuleStoriesResponse;
const scenario = goldens.find((g) => g.path === "/api/v1/scenarios")!;
export const scenarioGolden = scenario.response as ScenarioResponse;
export const scenarioBody = scenario.body!;

/** What the API says for Madrid (two of its four sources: one with a licence, one that declares none). */
export const MADRID_ATTRIBUTION: AttributionItem[] = [
  { text: "Ayuntamiento de Madrid, Servicio de Calidad del Aire. Datos abiertos: calidad del aire horaria.", license: "CC BY 4.0", url: "https://datos.madrid.es/dataset/201200-0-calidad-aire-horario" },
  { text: "MITECO, Índice Nacional de Calidad del Aire (ICA). La licencia de reutilización no está declarada en el documento.", license: null, url: "https://www.miteco.gob.es/" },
];

/** Scenario golden: wind_speed_t of SYN_A at 07:00; the backend's validation (domain, known variables) is mimicked. */
export function scenarioFor(set: FakeSet) {
  return (body: ScenarioRequest): { status: number; body: unknown } => {
    for (const [feature, value] of Object.entries(body.overrides ?? {})) {
      const variable = set.rules.variables.find((v) => v.feature === feature);
      if (!variable) return { status: 422, body: { detail: `override de una variable que no es del modelo: ${feature}` } };
      const [lo, hi] = variable.domain as unknown as [number, number];
      if (!Number.isFinite(value) || value < lo || value > hi) return { status: 422, body: { detail: `${feature}=${value} fuera del rango [${lo}, ${hi}]` } };
    }
    return { status: 200, body: scenarioGolden };
  };
}

/** Collection with `n` extra low-volume zones the model has no data for (`modelled: false`), as the NYC API serves 153. */
export function withUnmodelledZones(entities: EntityCollection, n: number): EntityCollection {
  const base = entities.features[0]!;
  const extra = Array.from({ length: n }, (_, i) => ({
    ...base,
    id: `U${i + 1}`,
    geometry: {
      type: "Polygon" as const,
      coordinates: [[[-73.9 + i * 0.01, 40.7], [-73.89 + i * 0.01, 40.7], [-73.89 + i * 0.01, 40.71], [-73.9 + i * 0.01, 40.71], [-73.9 + i * 0.01, 40.7]]] as never,
    },
    properties: { ...base.properties, entity_id: `U${i + 1}`, name: `Zona sin modelo ${i + 1}`, modelled: false },
  }));
  return { ...entities, features: [...entities.features, ...extra] };
}
