import type { RuleMapMetric, StoryCheck, StoryQuery, TerritoryMeasure } from "../api/types";
import { tr } from "../i18n";

/**
 * Rule Stories: the backend writes the text (templates, no language model) and says which requests and counts support
 * it. The web renders `text` as is; it only maps a story's query to the state of the app ("reproducir") and spells out
 * the checks so they can be audited.
 */

/** Where the app goes to show a story's query: the same rule, metric, time or window and tau as the request. */
export type ReproduceTarget =
  | { view: "rule"; ruleId: string; metric: RuleMapMetric; time: string | null; from: string | null; to: string | null; tau: number | null }
  | { view: "territories"; measure: TerritoryMeasure; from: string; to: string; tau: number | null };

const METRICS: readonly string[] = ["firing_strength", "mean_activation", "activation_frequency"];
const MEASURES: readonly string[] = ["mean_activation", "activation_frequency", "winner_share"];

/** The query as a target of the app; null when the query is not one the app can show (never guessed). */
export function reproduceTarget(q: StoryQuery): ReproduceTarget | null {
  const p = q.params;
  const tau = p.tau !== undefined && Number.isFinite(Number(p.tau)) ? Number(p.tau) : null;
  if (q.path === "/api/v1/rule-map") {
    if (!p.rule_id || !p.metric || !METRICS.includes(p.metric)) return null;
    if (p.metric === "firing_strength" ? !p.time : !(p.from && p.to)) return null;
    return {
      view: "rule",
      ruleId: p.rule_id,
      metric: p.metric as RuleMapMetric,
      time: p.time ?? null,
      from: p.from ?? null,
      to: p.to ?? null,
      tau,
    };
  }
  if (q.path === "/api/v1/rule-territories") {
    if (!p.measure || !MEASURES.includes(p.measure) || !p.from || !p.to) return null;
    return { view: "territories", measure: p.measure as TerritoryMeasure, from: p.from, to: p.to, tau };
  }
  return null;
}

/** A short description of the request, spelling out what the app will show. */
export function queryText(q: StoryQuery): string {
  const p = q.params;
  const when = p.time ? tr(`emisión ${p.time}`, `issue ${p.time}`) : `[${p.from}, ${p.to})`;
  const tau = p.tau !== undefined ? `, τ=${p.tau}` : "";
  return q.path === "/api/v1/rule-map"
    ? tr(`rule-map · regla ${p.rule_id} · ${p.metric} · ${when}${tau}`, `rule-map · rule ${p.rule_id} · ${p.metric} · ${when}${tau}`)
    : `rule-territories · ${p.measure} · ${when}${tau}`;
}

const OP_TEXT: Record<StoryCheck["op"], (property: string, operand: StoryCheck["operand"]) => string> = {
  gte: (property, operand) => `${property} ≥ ${operand}`,
  eq: (property, operand) => `${property} = ${operand}`,
  not_null: (property) => tr(`${property} no es null`, `${property} is not null`),
};

/** "consulta 1: contar las entidades con value ≥ 0.5 → 19", as the API defines the check. */
export const checkText = (c: StoryCheck): string =>
  tr(`consulta ${c.query + 1}: contar las entidades con ${OP_TEXT[c.op](c.property, c.operand)} → ${c.expected}`, `query ${c.query + 1}: count the entities with ${OP_TEXT[c.op](c.property, c.operand)} → ${c.expected}`);
