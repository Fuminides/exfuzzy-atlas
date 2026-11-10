import { vi } from "vitest";
import type {
  DomainsResponse,
  EntityCollection,
  ModelCard,
  ModelExplanation,
  ModelRules,
  ObservationsResponse,
  PredictionsResponse,
  RuleMapResponse,
  RuleImportanceResponse,
  RuleStoriesResponse,
  RuleTerritoriesResponse,
  RuleTrace,
  ScenarioRequest,
  SeriesResponse,
  SummaryResponse,
  TerritoryMeasure,
} from "../api/types";
import * as fx from "./fixtures";

/** The payloads of one task (one domain, one model). */
export interface FakeSet {
  entities: EntityCollection;
  card: ModelCard;
  rules: ModelRules;
  series: SeriesResponse[];
  /** Golden rule traces and rule maps; the regression fixtures by default. */
  traces: RuleTrace[];
  ruleMapFor: (q: URLSearchParams) => RuleMapResponse | undefined;
  /** Contract v0.4: stories and scenarios are golden payloads; predictions, observations and territories are derived. */
  stories?: (q: URLSearchParams) => RuleStoriesResponse | undefined;
  scenarioFor?: (body: ScenarioRequest) => { status: number; body: unknown };
  /** Contract v0.5: served when present, 404 ("not available yet") when absent, like a model published before v0.5. */
  summary?: SummaryResponse;
  importance?: RuleImportanceResponse;
  /** Contract v0.5.1: when set, every published prediction says this rule decided it (`decided_by_rule_id`). */
  decidedBy?: string;
  /** Contract v0.6.2: the AI-written explanation of the rule base; 404 when absent, like a model that has none. */
  explanation?: ModelExplanation;
  /** Contract v0.7 (rule mixture): every published prediction names this top rule (`top_rule_id`, `top_rule_share`). */
  topRule?: { id: string; share: number };
}

/** Backend fixtures served by a fake `fetch`; tests override pieces (e.g. a non-synthetic copy, null geometry). */
export interface FakeData extends FakeSet {
  domains: DomainsResponse;
  /** More tasks served next to the first (domain-switching tests): routed by domain, model id and task id. */
  extra?: FakeSet[];
}

export const defaults = (): FakeData => ({
  domains: fx.domains,
  entities: fx.entities,
  card: fx.card,
  rules: fx.rules,
  series: fx.series,
  traces: fx.traces,
  ruleMapFor: fx.ruleMapFor,
});

/** Same payload with every `synthetic` flag false: how a real (artifacts-mode) response looks. */
export const asReal = <T>(payload: T): T => JSON.parse(JSON.stringify(payload), (k, v) => (k === "synthetic" ? false : v)) as T;

export const json = (body: unknown, status = 200) => jsonResponse(body, status);
const jsonResponse = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));

/** Every request the app made, as `pathname + search`; POST bodies are kept apart. */
export const fake = { calls: [] as string[], posts: [] as { path: string; body: unknown }[] };

/** The window or instant of a v0.4 view: `time`, or `[from, to)`. */
function within(q: URLSearchParams): (issued: string) => boolean {
  if (q.get("time")) return (i) => Date.parse(i) === Date.parse(q.get("time")!);
  const from = Date.parse(q.get("from") ?? "");
  const to = Date.parse(q.get("to") ?? "");
  return (i) => Date.parse(i) >= from && Date.parse(i) < to;
}

const unmodelled = (f: EntityCollection["features"][number]) => f.properties.modelled === false;

/** /predictions as the API serves it: one Feature per entity; a window gives each entity its latest sample. */
export function predictionsFor(set: FakeSet, q: URLSearchParams): PredictionsResponse {
  const ok = within(q);
  const manifest = set.card.manifest;
  return {
    schema_version: "0.4.0",
    data_version: set.card.data_version,
    synthetic: set.card.synthetic,
    type: "FeatureCollection",
    task_id: manifest.task_id,
    model_id: manifest.model_id,
    task_type: set.rules.inference.family === "winning_rule_classifier" || set.rules.inference.family === "rule_mixture_classifier" ? "classification" : "regression",
    target: set.series[0]?.target ?? "y",
    unit: set.series[0]?.unit ?? "",
    horizon_hours: manifest.horizon_hours,
    issued_at_utc: q.get("time"),
    time_from_utc: q.get("from"),
    time_to_utc: q.get("to"),
    features: set.entities.features.map((f) => {
      const id = f.properties.entity_id;
      const base = { entity_id: id, model_id: manifest.model_id, data_version: set.card.data_version, unit: set.series[0]?.unit ?? "", geometry_support: f.properties.geometry_support };
      if (unmodelled(f)) {
        return { type: "Feature" as const, id, geometry: f.geometry, properties: { ...base, issued_at_utc: null, valid_at_utc: null, prediction: null, prediction_label: null, observed: null, observed_label: null, missing_reason: "not_modelled" as const } };
      }
      const points = (set.series.find((x) => x.entity_id === id)?.points ?? []).filter((p) => ok(p.issued_at_utc));
      const p = q.get("time") ? points[0] : points[points.length - 1];
      return {
        type: "Feature" as const,
        id,
        geometry: f.geometry,
        properties: p
          ? { ...base, issued_at_utc: p.issued_at_utc, valid_at_utc: p.valid_at_utc, prediction: p.prediction, prediction_label: p.predicted_label ?? null, ...(set.decidedBy && (p.prediction !== null || p.predicted_label) ? { decided_by_rule_id: set.decidedBy } : {}), ...(set.topRule && p.predicted_label ? { top_rule_id: set.topRule.id, top_rule_share: set.topRule.share } : {}), observed: p.observed, observed_label: p.observed_label ?? null, missing_reason: p.missing_reason ?? null }
          : { ...base, issued_at_utc: null, valid_at_utc: null, prediction: null, prediction_label: null, observed: null, observed_label: null, missing_reason: q.get("time") ? ("prediction_unavailable" as const) : ("no_observation" as const) },
      };
    }),
  };
}

/** /observations: the target observed at `valid_at` (a series point's `observed`) and the inputs of the trace at that issue time. */
export function observationsFor(set: FakeSet, q: URLSearchParams): ObservationsResponse {
  const preds = predictionsFor(set, q);
  return {
    schema_version: "0.4.0",
    data_version: preds.data_version,
    synthetic: preds.synthetic,
    type: "FeatureCollection",
    task_id: preds.task_id,
    model_id: preds.model_id,
    target: preds.target,
    unit: preds.unit,
    horizon_hours: preds.horizon_hours,
    issued_at_utc: preds.issued_at_utc,
    time_from_utc: preds.time_from_utc,
    time_to_utc: preds.time_to_utc,
    note: "Valores observados publicados, no predicciones ni interpolaciones; null = ausente, con su motivo.",
    features: preds.features.map((f) => {
      const p = f.properties;
      const trace = p.issued_at_utc ? set.traces.find((t) => t.entity_id === p.entity_id && Date.parse(t.issued_at_utc) === Date.parse(p.issued_at_utc!)) : undefined;
      const notModelled = p.missing_reason === "not_modelled";
      const value = p.observed ?? null;
      return {
        type: "Feature" as const,
        id: f.id,
        geometry: f.geometry,
        properties: {
          entity_id: p.entity_id,
          model_id: p.model_id,
          data_version: p.data_version,
          geometry_support: p.geometry_support,
          issued_at_utc: p.issued_at_utc,
          valid_at_utc: p.valid_at_utc,
          target: notModelled
            ? { feature: preds.target, value: null, unit: preds.unit, observed_at_utc: null, source_id: null, missing_reason: "not_modelled" as const }
            : { feature: preds.target, value, unit: preds.unit, observed_at_utc: value === null ? null : p.valid_at_utc, source_id: null, missing_reason: value === null ? ("no_observation" as const) : null },
          target_label: p.observed_label ?? null,
          inputs: trace?.feature_values ?? [],
          missing_reason: notModelled ? ("not_modelled" as const) : null,
        },
      };
    }),
  };
}

/**
 * /rule-territories with deterministic numbers (entity i, rule r) and the backend's rules: the dominant rule is the argmax
 * of the requested measure, ties go to the lowest rule position, null when the measure is 0 everywhere or n_valid = 0;
 * `winner_share` is classifier-only (422 otherwise). The first modelled entity has no valid record (n_valid = 0).
 */
export function territoriesFor(set: FakeSet, q: URLSearchParams): { status: number; body: unknown } {
  const measure = (q.get("measure") ?? "mean_activation") as TerritoryMeasure;
  const classifier = set.rules.inference.family === "winning_rule_classifier";
  if (measure === "winner_share" && !classifier) return { status: 422, body: { detail: "winner_share solo existe en clasificadores" } };
  const tau = Number(q.get("tau") ?? 0.5);
  const ids = set.rules.rules.map((r) => r.rule_id);
  const body: RuleTerritoriesResponse = {
    schema_version: "0.4.0",
    data_version: set.card.data_version,
    synthetic: set.card.synthetic,
    type: "FeatureCollection",
    model_id: set.rules.model_id,
    inference_family: set.rules.inference.family,
    measure,
    tau,
    time_from_utc: q.get("from")!,
    time_to_utc: q.get("to")!,
    n_rules: ids.length,
    tie_break: "Dominant rule = argmax of the measure over the rules of the entity; values within 1e-12 tie and the rule with the lowest position (R01 before R02, ...) wins; null if the measure is 0 for every rule.",
    denominators: "n_valid = records of the entity with issue time in [from, to) whose inputs are all present. A missing input is never a 0.",
    notes: ["Territories overlap: several rules are active in the same entity and record. They are not a partition."],
    features: set.entities.features.map((f, e) => {
      const id = f.properties.entity_id;
      const base = { entity_id: id, model_id: set.rules.model_id, data_version: set.card.data_version, geometry_support: f.properties.geometry_support };
      if (unmodelled(f)) {
        return { type: "Feature" as const, id, geometry: f.geometry, properties: { ...base, n_records: 0, n_valid: 0, dominant_rule_id: null, dominant_value: null, rules: [], missing_reason: "not_modelled" as const } };
      }
      if (e === 0) {
        return { type: "Feature" as const, id, geometry: f.geometry, properties: { ...base, n_records: 5, n_valid: 0, dominant_rule_id: null, dominant_value: null, rules: [], missing_reason: "no_observation" as const } };
      }
      const rules = ids.map((rule_id, r) => {
        const mean = ((e * 7 + r * 3) % 10) / 10;
        return { rule_id, mean_activation: mean, activation_frequency: tau < 0.5 ? Math.min(1, mean + 0.2) : mean * 0.5, winner_share: classifier ? ((e + r) % 4) / 8 : null };
      });
      let best = -1;
      let dominant: string | null = null;
      for (const r of rules) {
        const v = (measure === "winner_share" ? r.winner_share : r[measure]) ?? 0;
        if (v > best + 1e-12) {
          best = v;
          dominant = r.rule_id;
        }
      }
      return { type: "Feature" as const, id, geometry: f.geometry, properties: { ...base, n_records: 20 + e, n_valid: 10 + e, dominant_rule_id: best > 0 ? dominant : null, dominant_value: best > 0 ? best : null, rules } };
    }),
  };
  return { status: 200, body };
}

/**
 * `real: true` serves every payload (also the golden rule maps and traces) with `synthetic: false`,
 * as the artifacts-mode API does for a real published model.
 */
export function installApi(overrides: Record<string, () => Promise<Response>> = {}, data: Partial<FakeData> & { real?: boolean } = {}) {
  const { real, ...rest } = data;
  const d = { ...defaults(), ...rest };
  const sets: FakeSet[] = [d, ...(d.extra ?? [])];
  const byModel = (id: string | null) => sets.find((x) => x.rules.model_id === id) ?? d;
  const json = (body: unknown, status = 200) => jsonResponse(real ? asReal(body) : body, status);
  fake.calls = [];
  fake.posts = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string, init?: RequestInit) => {
      const url = new URL(input, "http://x");
      fake.calls.push(url.pathname + url.search);
      const p = url.pathname.replace("/api/v1", "");
      const q = url.searchParams;
      const override = overrides[p];
      if (override) return override();
      if (p === "/health") return json({ status: "ok", schema_version: "0.3.0", mode: "mock" });
      if (p === "/domains") return json(d.domains);
      if (p === "/entities") {
        // Like the API: with task_id exactly that task's entities (404 unknown, 422 other domain); without it a domain
        // that serves several tasks is ambiguous (422).
        const domain = q.get("domain");
        const here = sets.filter((x) => x.entities.domain === domain);
        const task = q.get("task_id");
        if (task === null) return here.length > 1 ? json({ detail: `domain ${domain} has ${here.length} tasks: pass task_id` }, 422) : json((here[0] ?? d).entities);
        const own = sets.find((x) => x.card.manifest.task_id === task);
        if (!own) return json({ detail: `unknown task_id ${task}` }, 404);
        return own.entities.domain === domain ? json(own.entities) : json({ detail: `task_id ${task} belongs to another domain` }, 422);
      }
      const imp = sets.find((x) => p === `/models/${x.rules.model_id}/importance`);
      if (imp) return imp.importance ? json(imp.importance) : json({ detail: "no importance.json for this model" }, 404);
      if (p === "/summary") {
        const own = sets.find((x) => x.card.manifest.task_id === q.get("task_id"));
        return own?.summary ? json(own.summary) : json({ detail: "no summary.json for this task" }, 404);
      }
      const explained = sets.find((x) => p === `/models/${x.rules.model_id}/explanation`);
      if (explained) return explained.explanation ? json(explained.explanation) : json({ detail: "no explanation for this model" }, 404);
      const card = sets.find((x) => p === `/models/${x.rules.model_id}`);
      if (card) return json(card.card);
      const rules = sets.find((x) => p === `/models/${x.rules.model_id}/rules`);
      if (rules) return json(rules.rules);
      const taskSet = () => sets.find((x) => x.card.manifest.task_id === q.get("task_id"));
      if (p === "/predictions" || p === "/observations") {
        const own = taskSet();
        if (!own) return json({ detail: "unknown task" }, 404);
        return json(p === "/predictions" ? predictionsFor(own, q) : observationsFor(own, q));
      }
      if (p === "/rule-territories") {
        const r = territoriesFor(byModel(q.get("model_id")), q);
        return json(r.body, r.status);
      }
      if (p === "/rule-stories") {
        const golden = byModel(q.get("model_id")).stories?.(q);
        return golden ? json(golden) : json({ detail: "no stories" }, 404);
      }
      if (p === "/scenarios") {
        const body = JSON.parse(String(init?.body ?? "{}")) as ScenarioRequest;
        fake.posts.push({ path: p, body });
        const r = byModel(body.model_id).scenarioFor?.(body);
        return r ? json(r.body, r.status) : json({ detail: "no scenario" }, 404);
      }
      if (p === "/rule-map") {
        const golden = byModel(q.get("model_id")).ruleMapFor(q);
        return golden ? json(golden) : json({ detail: "no golden rule-map for this query" }, 404);
      }
      if (p.endsWith("/rule-trace")) {
        const id = decodeURIComponent(p.split("/")[2]!);
        const t = byModel(q.get("model_id")).traces.find((x) => x.entity_id === id && x.issued_at_utc === q.get("at"));
        return t ? json(t) : json({ detail: "no trace" }, 404);
      }
      if (p === "/series") {
        const own = sets.find((x) => x.series.some((sr) => sr.task_id === q.get("task_id"))) ?? d;
        const s = own.series.find((x) => x.entity_id === q.get("entity_id"));
        if (!s) return json({ detail: "no series" }, 404);
        // [from, to) by issue time, like the API.
        const from = q.get("from") ? Date.parse(q.get("from")!) : -Infinity;
        const to = q.get("to") ? Date.parse(q.get("to")!) : Infinity;
        const points = s.points.filter((pt) => Date.parse(pt.issued_at_utc) >= from && Date.parse(pt.issued_at_utc) < to);
        return json({ ...s, points });
      }
      return json({ detail: "not found" }, 404);
    }),
  );
}
