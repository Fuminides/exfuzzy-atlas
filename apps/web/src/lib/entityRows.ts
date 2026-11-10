import type { EntityCollection } from "../api/types";
import type { StationRow } from "../map/stations";
import { tr } from "../i18n";

const SMALL_WORDS = new Set(["at", "of", "the", "and", "on", "by", "in", "to", "with", "from", "for", "le", "upon"]);

/** EEA names a station that closed or moved with its years ("Elsterwerda, 1992-2020" next to the current "Elsterwerda"). */
const STATION_YEARS = /^(.*\S),\s*(\d{4})\s*[-–]\s*(\d{4})$/;

/**
 * A name written fully in capitals (Water sampling points) is shown in title case; a trailing year range is written
 * out ("Elsterwerda (estación de 1992 a 2020)", "Elsterwerda (station from 1992 to 2020)"), never dropped, because it is what tells two stations apart. Any other
 * name is untouched. Display only.
 */
export function displayName(name: string): string {
  const years = STATION_YEARS.exec(name);
  if (years) return tr(`${displayName(years[1]!)} (estación de ${years[2]} a ${years[3]})`, `${displayName(years[1]!)} (station from ${years[2]} to ${years[3]})`);
  if (name !== name.toUpperCase() || name === name.toLowerCase()) return name;
  return name
    .toLowerCase()
    .replace(/[a-zà-ÿ]+(?:'[a-zà-ÿ]+)*/g, (w, i: number) => (i > 0 && SMALL_WORDS.has(w) ? w : w.charAt(0).toUpperCase() + w.slice(1)));
}

/**
 * One row per entity, without values: the base every mode paints on. Entities the model has no data for are marked
 * "sin modelo" (never counted as missing: "110 zonas con modelo de 263").
 */
export function entityRows(entities: EntityCollection, unmodelledIds: ReadonlySet<string>): { baseRows: StationRow[]; nameOf: (id: string) => string } {
  const names = new Map(entities.features.map((f) => [f.properties.entity_id, displayName(f.properties.name ?? f.properties.entity_id)]));
  const nameOf = (id: string) => names.get(id) ?? id;
  const baseRows = entities.features.map((f) => ({
    entityId: f.properties.entity_id,
    name: nameOf(f.properties.entity_id),
    value: null,
    missingReason: unmodelledIds.has(f.properties.entity_id) ? ("not_modelled" as const) : null,
    nValid: null,
    geometry: f.geometry,
  }));
  return { baseRows, nameOf };
}
