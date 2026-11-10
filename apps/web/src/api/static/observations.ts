import type { FeatureValue, ObservationFeature, ObservationsResponse } from "../types";
import { entityBase, envelope, noRowReason, validQuality, warning } from "./common";
import type { Data, Model } from "./data";
import { at } from "./rows";
import { classAt, pickRows, type Picked, type TimeQuery } from "./select";
import { HOUR_MS, iso, normalise, utcHour } from "./time";
import type { InputsFile } from "./types";

/** The value of input file `f` for a row: `values[hour * |E| + e]` on the lattice of a regular task, `values[i]` otherwise. */
export function inputValue(h: Model, file: InputsFile | null, p: Picked): number | null {
  if (!file) return null;
  const index = h.meta.regular ? utcHour(p.t) * h.meta.entities.length + p.e : p.i;
  return file.values[index] ?? null;
}

/** For each row, the model's inputs in model order. Files are fetched once per (feature, shard). */
export async function inputsOf(d: Data, h: Model, rows: readonly Picked[], signal?: AbortSignal): Promise<(number | null)[][]> {
  const keys = [...new Set(rows.map((p) => p.key))];
  const files = new Map<string, InputsFile | null>();
  await Promise.all(
    h.meta.features.flatMap((_, f) => keys.map(async (key) => void files.set(`${f}|${key}`, await d.inputs(h, f, key, signal)))),
  );
  return rows.map((p) => h.meta.features.map((_, f) => inputValue(h, files.get(`${f}|${p.key}`) ?? null, p)));
}

/** `GET /observations`: the observed target and the model's inputs per entity (`ArtifactStore.observations`). */
export async function observations(d: Data, h: Model, q: TimeQuery, signal?: AbortSignal): Promise<ObservationsResponse> {
  const { meta } = h;
  const picked = await pickRows(d, h, q, signal);
  const entries = [...picked.values()];
  const values = new Map(entries.map((p, n) => [p.e, n]));
  const inputs = await inputsOf(d, h, entries, signal);
  const features: ObservationFeature[] = h.features.map((entity) => {
    const eid = entity.properties.entity_id;
    const e = h.entityIndex.get(eid);
    const p = e === undefined ? undefined : picked.get(e);
    const common = { ...entityBase(entity), model_id: meta.model_id, data_version: meta.data_version };
    if (!p) {
      return {
        type: "Feature", id: eid, geometry: entity.geometry,
        properties: { ...common, issued_at_utc: null, valid_at_utc: null, target: null, target_label: null, inputs: [], missing_reason: noRowReason(entity, h), quality: validQuality() },
      } as ObservationFeature;
    }
    const row = inputs[values.get(p.e)!]!;
    const list: FeatureValue[] = meta.features.map((f, k) => {
      const value = row[k] ?? null;
      return {
        feature: f.name, value, unit: f.obs_unit, source_id: f.source_id,
        observed_at_utc: value === null ? null : iso(p.t - f.lag_hours * HOUR_MS),
        missing_reason: value === null ? "no_observation" : null,
      };
    });
    const missing = list.filter((fv) => fv.value === null).map((fv) => fv.feature);
    const observed = at(p.shard.obs, p.i);
    return {
      type: "Feature", id: eid, geometry: entity.geometry,
      properties: {
        ...common,
        issued_at_utc: iso(p.t),
        valid_at_utc: iso(p.t + meta.horizon_hours * HOUR_MS),
        target: {
          feature: meta.target, value: observed, unit: meta.unit, source_id: null, observed_at_utc: iso(p.t + meta.horizon_hours * HOUR_MS),
          missing_reason: observed !== null ? null : "no_observation",
        },
        target_label: classAt(h, at(p.shard.olabel, p.i)),
        inputs: list,
        missing_reason: null,
        quality: missing.length > 0 ? warning(`missing input: ${missing.join(", ")}`) : validQuality(),
      },
    } as ObservationFeature;
  });
  const instant = q.time !== undefined;
  return {
    type: "FeatureCollection", ...envelope(h),
    task_id: meta.task_id, model_id: meta.model_id, target: meta.target, unit: meta.unit, horizon_hours: meta.horizon_hours,
    issued_at_utc: instant ? normalise(q.time!) : null,
    time_from_utc: instant ? null : normalise(q.from!),
    time_to_utc: instant ? null : normalise(q.to!),
    note: h.texts.observations_note,
    features,
  };
}
