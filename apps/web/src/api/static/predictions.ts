import type { PredictionFeature, PredictionsResponse } from "../types";
import { entityBase, envelope, noRowReason, validQuality } from "./common";
import type { Data, Model } from "./data";
import { at } from "./rows";
import { classAt, pickRows, reasonAt, type TimeQuery } from "./select";
import { HOUR_MS, iso, normalise } from "./time";

/** `GET /predictions`: one `Feature` per entity, from the pred shards (`ArtifactStore.predictions`). */
export async function predictions(d: Data, h: Model, q: TimeQuery, signal?: AbortSignal): Promise<PredictionsResponse> {
  const { meta } = h;
  const picked = await pickRows(d, h, q, signal);
  const features: PredictionFeature[] = h.features.map((entity) => {
    const eid = entity.properties.entity_id;
    const e = h.entityIndex.get(eid);
    const p = e === undefined ? undefined : picked.get(e);
    const common = { ...entityBase(entity), model_id: meta.model_id, data_version: meta.data_version, unit: meta.unit };
    let body;
    if (!p) {
      body = {
        issued_at_utc: null, valid_at_utc: null, prediction: null, prediction_label: null, observed: null, observed_label: null,
        missing_reason: noRowReason(entity, h), decided_by_rule_id: null, top_rule_id: null, top_rule_share: null,
      };
    } else {
      const prediction = at(p.shard.pred, p.i);
      const label = classAt(h, at(p.shard.plabel, p.i));
      const decided = at(p.shard.decided, p.i);
      const top = at(p.shard.top, p.i);
      const withTop = h.mixture && label !== null && top !== null;
      body = {
        issued_at_utc: iso(p.t),
        valid_at_utc: iso(p.t + meta.horizon_hours * HOUR_MS),
        prediction,
        prediction_label: label,
        observed: at(p.shard.obs, p.i),
        observed_label: classAt(h, at(p.shard.olabel, p.i)),
        missing_reason: prediction !== null || label !== null ? null : (reasonAt(h, p) ?? "prediction_unavailable"),
        decided_by_rule_id: decided === null ? null : (meta.rules[decided] ?? null),
        top_rule_id: withTop ? (meta.rules[top] ?? null) : null,
        top_rule_share: withTop ? at(p.shard.tshare, p.i) : null,
      };
    }
    return { type: "Feature", id: eid, geometry: entity.geometry, properties: { ...common, ...body, quality: validQuality() } } as PredictionFeature;
  });
  const instant = q.time !== undefined;
  return {
    type: "FeatureCollection",
    ...envelope(h),
    task_id: meta.task_id,
    model_id: meta.model_id,
    task_type: meta.task_type,
    target: meta.target,
    unit: meta.unit,
    horizon_hours: meta.horizon_hours,
    issued_at_utc: instant ? normalise(q.time!) : null,
    time_from_utc: instant ? null : normalise(q.from!),
    time_to_utc: instant ? null : normalise(q.to!),
    features,
  };
}
