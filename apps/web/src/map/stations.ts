import type { EntityFeature, MissingReason } from "../api/types";

/** One station as shown on the map, the table and the legend counts. `value` comes from the API. */
export interface StationRow {
  entityId: string;
  name: string;
  /** null = no value (see `missingReason`); 0 is a real value. */
  value: number | null;
  /** Predicted class label (classifier prediction); null = "sin predicción". `value` stays null then. */
  label?: string | null;
  missingReason: MissingReason | null;
  /** Observed but with no reference level ("sin referencia", NYC): drawn hatched, never in a class colour. */
  noReference?: boolean;
  /**
   * Prediction mode: the entity has no prediction at any time of the published period (importance: absent or nothing
   * decided). Drawn quiet; never the per-time "falta una entrada" case.
   */
  noPredictions?: boolean;
  /** Irregular tasks (Water): the sample shown for the window (its issue time, and the observed value). */
  sample?: { at: string; observed: number | null };
  /** Prediction mode: the rule that decided this entity's prediction (`decided_by_rule_id`); null when the API does not say. */
  decidedBy?: string | null;
  /** Mixture of rules (v0.7): `decidedBy` is then the rule that adds the most (`top_rule_id`) and this its share (`top_rule_share`). */
  topShare?: number | null;
  /** Records behind `value` (rule-map `n_valid`); null when not applicable. */
  nValid: number | null;
  geometry: EntityFeature["geometry"];
}

export interface StationCollection {
  type: "FeatureCollection";
  features: {
    type: "Feature";
    id: string;
    geometry: NonNullable<StationRow["geometry"]>;
    properties: {
      entity_id: string;
      name: string;
      value: number | null;
      label: string | null;
      missing_reason: MissingReason | null;
      no_reference: boolean;
      no_predictions: boolean;
    };
  }[];
}

/** Entities without geometry (`geometry: null`) are never drawn: the table lists them as "sin geometría". */
export function toCollection(rows: readonly StationRow[]): StationCollection {
  return {
    type: "FeatureCollection",
    features: rows.flatMap((r) =>
      r.geometry === null
        ? []
        : [
            {
              type: "Feature" as const,
              id: r.entityId,
              geometry: r.geometry,
              properties: {
                entity_id: r.entityId,
                name: r.name,
                value: r.value,
                label: r.label ?? null,
                missing_reason: r.missingReason,
                no_reference: r.noReference === true,
                no_predictions: r.noPredictions === true,
              },
            },
          ],
    ),
  };
}

/** Every [lon, lat] of the drawn geometries (points and polygon rings), to frame the map. */
export function positions(rows: readonly StationRow[]): [number, number][] {
  return rows.flatMap((r) => {
    const g = r.geometry;
    if (g === null) return [];
    if (g.type === "Point") return [g.coordinates as [number, number]];
    const rings = g.type === "Polygon" ? [g.coordinates] : g.coordinates;
    return rings.flatMap((polygon) => polygon.flatMap((ring) => ring.map((p) => [p[0]!, p[1]!] as [number, number])));
  });
}
