import type { MissingReason, RuleMapFeature, RuleMapMetric, RuleMapResponse } from "../types";
import { entityBase, envelope, unit, validQuality, warning } from "./common";
import { notFound, type Data, type Model } from "./data";
import { rowsOf } from "./rows";
import { keyOf } from "./select";
import { aggOf, requireWindow, tauIndex } from "./windows";
import { HOUR_MS, iso, ms } from "./time";

export interface RuleMapQuery {
  modelId: string;
  ruleId: string;
  metric: RuleMapMetric;
  time?: string;
  from?: string;
  to?: string;
  tau?: number;
}

function ruleOf(h: Model, ruleId: string): number {
  const r = h.ruleIndex.get(ruleId);
  if (r === undefined) throw notFound(`unknown rule_id ${ruleId} for ${h.meta.model_id}`);
  return r;
}

interface Cell {
  value: number | null;
  nValid: number;
  nRecords: number;
  reason: MissingReason | null;
}

/** `ArtifactStore._compute_rule_map`, with the per-entity statistics given. */
function collection(h: Model, q: RuleMapQuery, instant: boolean, lo: number, hi: number, tau: number | null, cell: (e: number) => Cell): RuleMapResponse {
  const { meta } = h;
  const features: RuleMapFeature[] = h.features.map((entity) => {
    const eid = entity.properties.entity_id;
    const e = h.entityIndex.get(eid);
    let value: number | null = null;
    let nValid = 0;
    let reason: MissingReason | null;
    let quality = validQuality();
    let nRecords = 0;
    if (e === undefined) {
      reason = "not_modelled";
    } else {
      const c = cell(e);
      ({ value, nValid, reason, nRecords } = c);
      if (reason === "missing_input") quality = warning("missing input");
    }
    return {
      type: "Feature",
      id: eid,
      geometry: entity.geometry,
      properties: {
        ...entityBase(entity),
        rule_id: q.ruleId,
        metric: q.metric,
        value,
        n_valid: nValid,
        time_from_utc: iso(lo),
        time_to_utc: iso(instant ? lo : hi),
        issued_at_utc: instant ? iso(lo) : null,
        valid_at_utc: instant && nRecords > 0 ? iso(lo + meta.horizon_hours * HOUR_MS) : null,
        tau,
        model_id: meta.model_id,
        data_version: meta.data_version,
        missing_reason: reason,
        quality,
      },
    } as RuleMapFeature;
  });
  return {
    type: "FeatureCollection", ...envelope(h),
    model_id: meta.model_id, rule_id: q.ruleId, metric: q.metric, tau,
    time_from_utc: iso(lo), time_to_utc: iso(instant ? lo : hi), features,
  };
}

/** One rule at one issue time (`metric = firing_strength`): the firing of the pred/fire shards of its day. */
async function atInstant(d: Data, h: Model, q: RuleMapQuery, signal?: AbortSignal): Promise<RuleMapResponse> {
  const lo = ms(q.time!);
  const r = ruleOf(h, q.ruleId);
  const key = keyOf(h, lo);
  const [shard, fire] = await Promise.all([d.pred(h, key, signal), d.fire(h, key, signal)]);
  const rows = shard ? rowsOf(shard, h.meta.entities.length) : null;
  return collection(h, q, true, lo, lo, null, (e) => {
    const i = rows?.find(lo, e);
    if (i === undefined || !fire) return { value: null, nValid: 0, nRecords: 0, reason: "no_observation" };
    const firing = fire.f[r]?.[i] ?? null;
    return firing === null
      ? { value: null, nValid: 0, nRecords: 1, reason: "missing_input" }
      : { value: unit(firing), nValid: 1, nRecords: 1, reason: null };
  });
}

/** One rule over a window: the mean and the share at or over tau, from the window's statistics. */
async function overWindow(d: Data, h: Model, q: RuleMapQuery, signal?: AbortSignal): Promise<RuleMapResponse> {
  const ref = requireWindow(h.meta, q.from!, q.to!);
  const frequency = q.metric === "activation_frequency";
  const k = frequency ? tauIndex(h.meta, q.tau!) : -1;
  const r = ruleOf(h, q.ruleId);
  const agg = await aggOf(d, h, ref, signal);
  const nE = h.meta.entities.length;
  return collection(h, q, false, ms(q.from!), ms(q.to!), frequency ? q.tau! : null, (e) => {
    const nRecords = agg?.n_records[e] ?? 0;
    const nValid = agg?.n_valid[e] ?? 0;
    if (nValid > 0 && agg) {
      const total = frequency ? agg.over[k]![r * nE + e]! : agg.sum[r * nE + e]!;
      return { value: unit(total / nValid), nValid, nRecords, reason: null };
    }
    return { value: null, nValid, nRecords, reason: nRecords > 0 ? "missing_input" : "no_observation" };
  });
}

/** `GET /rule-map` (`ArtifactStore.rule_map`). */
export function ruleMap(d: Data, h: Model, q: RuleMapQuery, signal?: AbortSignal): Promise<RuleMapResponse> {
  return q.metric === "firing_strength" ? atInstant(d, h, q, signal) : overWindow(d, h, q, signal);
}

