import type { ObservationsResponse, PredictionsResponse } from "../api/types";
import type { StationRow } from "../map/stations";
import { isNoReference } from "./classifier";
import { predictionRule } from "./mixtureViews";

interface PredictionOptions {
  /** Classifier: colour by `prediction_label`; a numeric prediction is never drawn. */
  classifier: boolean;
  /** NYC: an observed hour without a reference level is "sin referencia", not a class and not a failure. */
  relativeScheme: boolean;
  /** Sample-time tasks: each entity carries the date of its own latest sample. */
  irregular: boolean;
}

/**
 * Prediction mode: one `Feature` per entity from `/predictions` (an issue time, or each entity's latest sample in a
 * window). An entity without a feature, or with `prediction: null`, keeps its reason: null is never 0 and never a class.
 * "Sin modelo" rows (`not_modelled`) are left as the base rows have them.
 */
export function predictionRows(base: readonly StationRow[], data: PredictionsResponse, o: PredictionOptions): StationRow[] {
  const byId = new Map(data.features.map((f) => [f.properties.entity_id, f.properties]));
  return base.map((r) => {
    if (r.missingReason === "not_modelled") return r;
    const p = byId.get(r.entityId);
    if (!p) return { ...r, missingReason: o.irregular ? "no_observation" : "prediction_unavailable" };
    if (o.classifier) {
      const label = p.prediction_label ?? null;
      return {
        ...r,
        label,
        decidedBy: label !== null ? predictionRule(p) : null,
        topShare: label !== null && p.top_rule_id ? (p.top_rule_share ?? null) : null,
        noReference:
          o.relativeScheme &&
          isNoReference({ observed: p.observed ?? null, observed_label: p.observed_label, predicted_label: label, missing_reason: p.missing_reason }),
        missingReason: label !== null ? null : (p.missing_reason ?? "prediction_unavailable"),
      };
    }
    return {
      ...r,
      value: p.prediction,
      decidedBy: p.prediction !== null ? (p.decided_by_rule_id ?? null) : null,
      missingReason: p.prediction === null ? (p.missing_reason ?? null) : null,
      sample: o.irregular && p.issued_at_utc ? { at: p.issued_at_utc, observed: p.observed ?? null } : undefined,
    };
  });
}

/**
 * Data mode: the observed target of each entity (`target.value`, observed at `valid_at_utc`). Absent is null with a
 * reason (`no_observation` when the API gives none); 0 is only ever a measured 0. Nothing is predicted or interpolated.
 */
export function observationRows(base: readonly StationRow[], data: ObservationsResponse): StationRow[] {
  const byId = new Map(data.features.map((f) => [f.properties.entity_id, f.properties]));
  return base.map((r) => {
    if (r.missingReason === "not_modelled") return r;
    const p = byId.get(r.entityId);
    const value = p?.target?.value ?? null;
    return {
      ...r,
      value,
      missingReason: value !== null ? null : (p?.target?.missing_reason ?? p?.missing_reason ?? "no_observation"),
    };
  });
}

/**
 * Prediction mode: flags the rows that have no prediction at any time of the published period (`never`) and sends them
 * to the end of the table. Only rows that are plainly "sin predicción" now: a withheld "sin referencia" (NYC), an entity
 * without model or one that has a prediction at this time keep their own reading.
 */
export function markNeverPredicted(rows: readonly StationRow[], never: ReadonlySet<string>): StationRow[] {
  if (never.size === 0) return [...rows];
  const flagged = rows.map((r) =>
    never.has(r.entityId) && r.missingReason !== "not_modelled" && !r.noReference && r.value === null && (r.label ?? null) === null ? { ...r, noPredictions: true } : r,
  );
  return [...flagged.filter((r) => !r.noPredictions), ...flagged.filter((r) => r.noPredictions)];
}
