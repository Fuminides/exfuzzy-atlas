import type { MissingReason, RuleTerritoriesResponse, TerritoryFeature, TerritoryMeasure, TerritoryRuleStats } from "../types";
import { tr } from "../../i18n";
import { entityBase, envelope, unit, validQuality, warning } from "./common";
import { unprocessable, type Data, type Model } from "./data";
import { iso, ms } from "./time";
import { aggOf, requireWindow, tauIndex } from "./windows";
import type { AggFile } from "./types";

export interface TerritoriesQuery {
  modelId: string;
  from: string;
  to: string;
  measure: TerritoryMeasure;
  tau: number;
}

/** Position of the largest value; values within the tie tolerance of it tie and the lowest position wins; null when nothing is positive. */
export function dominantIndex(values: readonly number[], tolerance: number): number | null {
  if (values.length === 0) return null;
  const best = Math.max(...values);
  if (best <= 0) return null;
  return values.findIndex((v) => v >= best - tolerance);
}

/** `atlas.services.territories.build_territories` fed with the window statistics. */
export async function ruleTerritories(d: Data, h: Model, q: TerritoriesQuery, signal?: AbortSignal): Promise<RuleTerritoriesResponse> {
  const { meta } = h;
  if (q.measure === "winner_share" && !h.winningRule) {
    throw unprocessable(
      "winner_share only exists for winning-rule classifiers (in a mixture of rules no rule decides alone); use mean_activation or activation_frequency",
      () => tr("«reglas ganadoras» solo existe en clasificadores de regla ganadora", "“winning rules” only exists for winning-rule classifiers"),
    );
  }
  const ref = requireWindow(meta, q.from, q.to);
  const k = tauIndex(meta, q.tau);
  const agg = await aggOf(d, h, ref, signal);
  const features: TerritoryFeature[] = h.features.map((entity) => {
    const eid = entity.properties.entity_id;
    const e = h.entityIndex.get(eid);
    const common = { ...entityBase(entity), model_id: meta.model_id, data_version: meta.data_version };
    const nRecords = e === undefined || !agg ? 0 : agg.n_records[e]!;
    let body;
    if (e === undefined) body = empty(0, 0, "not_modelled");
    else if (nRecords === 0) body = empty(0, 0, "no_observation");
    else if (agg!.n_valid[e] === 0) body = empty(nRecords, 0, "missing_input", warning("missing input"));
    else body = entityBody(h, agg!, e, k, q.measure);
    return { type: "Feature", id: eid, geometry: entity.geometry, properties: { ...common, ...body } } as TerritoryFeature;
  });
  return {
    type: "FeatureCollection", ...envelope(h),
    model_id: meta.model_id, inference_family: meta.family as RuleTerritoriesResponse["inference_family"], measure: q.measure, tau: q.tau,
    time_from_utc: iso(ms(q.from)), time_to_utc: iso(ms(q.to)),
    n_rules: meta.rules.length, tie_break: h.texts.tie_break, denominators: h.texts.denominators, notes: [...h.texts.territory_notes], features,
  };
}

const empty = (nRecords: number, nValid: number, reason: MissingReason, quality = validQuality()) => ({
  n_records: nRecords, n_valid: nValid, dominant_rule_id: null, dominant_value: null, rules: [], missing_reason: reason, quality,
});

function entityBody(h: Model, agg: AggFile, e: number, k: number, measure: TerritoryMeasure) {
  const nE = h.meta.entities.length;
  const nValid = agg.n_valid[e]!;
  const rules: TerritoryRuleStats[] = h.meta.rules.map((ruleId, r) => ({
    rule_id: ruleId,
    mean_activation: unit(agg.sum[r * nE + e]! / nValid),
    activation_frequency: unit(agg.over[k]![r * nE + e]! / nValid),
    winner_share: h.winningRule ? unit((agg.win?.[r * nE + e] ?? 0) / nValid) : null,
  }));
  const chosen = dominantIndex(rules.map((s) => s[measure]!), h.texts.tie_tolerance);
  const body = { n_records: agg.n_records[e]!, n_valid: nValid, rules, missing_reason: null };
  return chosen === null
    ? { ...body, dominant_rule_id: null, dominant_value: null, quality: warning(`${measure} is 0 for every rule: no dominant rule`) }
    : { ...body, dominant_rule_id: rules[chosen]!.rule_id, dominant_value: rules[chosen]![measure]!, quality: validQuality() };
}
