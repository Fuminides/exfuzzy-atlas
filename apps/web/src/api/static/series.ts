import type { SeriesPoint, SeriesResponse } from "../types";
import { SERIES_MAX_POINTS } from "./constants";
import { envelope, validQuality } from "./common";
import { notFound, type Data, type Model } from "./data";
import { at, rowsOf } from "./rows";
import { classAt, keysOf } from "./select";
import { HOUR_MS, iso, ms } from "./time";

export interface SeriesQuery {
  taskId: string;
  entityId: string;
  from?: string;
  to?: string;
  cursor?: string;
}

/** `GET /series` (`ArtifactStore.series_for`): the entity's rows by issue time, at most 2,000 per page. */
export async function series(d: Data, h: Model, q: SeriesQuery, signal?: AbortSignal): Promise<SeriesResponse> {
  const { meta } = h;
  if (!h.entityById.has(q.entityId)) throw notFound(`no series for ${q.taskId}/${q.entityId}`);
  if (h.unmodelled.has(q.entityId)) throw notFound(`${q.entityId} has no model for ${q.taskId} (not_modelled): there is no series`);
  const e = h.entityIndex.get(q.entityId)!;
  const lower = Math.max(q.from ? ms(q.from) : -Infinity, q.cursor ? ms(q.cursor) : -Infinity);
  const upper = q.to ? ms(q.to) : Infinity;
  // keys are days of issue time: bound the open ends by the model's own coverage
  const keys = keysOf(h, Number.isFinite(lower) ? lower : ms(meta.coverage.from), Number.isFinite(upper) ? upper : ms(meta.coverage.to) + 1);
  const shards = await Promise.all(keys.map((k) => d.pred(h, k, signal)));
  const found: { shardIndex: number; i: number; t: number }[] = [];
  shards.forEach((shard, n) => {
    if (!shard) return;
    const rows = rowsOf(shard, meta.entities.length);
    for (const i of rows.byEntity.get(e) ?? []) {
      const t = rows.timeOf(i);
      if (t >= lower && t < upper) found.push({ shardIndex: n, i, t });
    }
  });
  found.sort((a, b) => a.t - b.t);
  let nextCursor: string | null = null;
  if (found.length > SERIES_MAX_POINTS) {
    nextCursor = iso(found[SERIES_MAX_POINTS]!.t);
    found.length = SERIES_MAX_POINTS;
  }
  const points: SeriesPoint[] = found.map(({ shardIndex, i, t }) => {
    const shard = shards[shardIndex]!;
    const prediction = at(shard.pred, i);
    const predicted = classAt(h, at(shard.plabel, i));
    const code = at(shard.reason, i);
    const answered = prediction !== null || predicted !== null;
    return {
      issued_at_utc: iso(t),
      valid_at_utc: iso(t + meta.horizon_hours * HOUR_MS),
      observed: at(shard.obs, i),
      prediction,
      observed_label: classAt(h, at(shard.olabel, i)),
      predicted_label: predicted,
      missing_reason: answered ? null : code === null ? "prediction_unavailable" : (meta.missing_reasons[code] ?? "prediction_unavailable"),
      quality: validQuality(),
    };
  });
  return {
    ...envelope(h), task_id: q.taskId, entity_id: q.entityId, model_id: meta.model_id, target: meta.target, unit: meta.unit,
    horizon_hours: meta.horizon_hours, points, next_cursor: nextCursor,
  };
}
