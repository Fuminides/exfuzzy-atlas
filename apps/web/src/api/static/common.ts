import type { MissingReason, EntityFeature } from "../types";
import type { Model } from "./data";
import type { Meta } from "./types";

/** `Quality()` of the contract: a fresh object each time, as a JSON body would be. */
export interface Quality {
  status: "valid" | "warning" | "invalid";
  warnings: string[];
}
export const validQuality = (): Quality => ({ status: "valid", warnings: [] });
export const warning = (...warnings: string[]): Quality => ({ status: "warning", warnings });

/** The `_Envelope` fields every body carries. */
export const envelope = (h: Model) => ({ schema_version: h.schemaVersion, data_version: h.meta.data_version, synthetic: h.meta.synthetic });

/** The fields of an entity every per-entity property block repeats. */
export const entityBase = (f: EntityFeature) => ({
  entity_id: f.properties.entity_id,
  geometry_support: f.properties.geometry_support,
});

/** Why an entity has no row: it has no model, or the model published nothing for it in the query. */
export const noRowReason = (f: EntityFeature, h: Model): MissingReason => (h.unmodelled.has(f.properties.entity_id) ? "not_modelled" : "no_observation");

export const metaOf = (h: Model): Meta => h.meta;

/** `value` clamped to [0, 1]. */
export const unit = (value: number): number => Math.min(1, Math.max(0, value));
