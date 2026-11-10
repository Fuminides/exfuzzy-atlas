/**
 * The few literals that are the web's own. The texts the API writes from contract constants (tie-break, notes, the what-if
 * label and warning, the observations note, the no-reference warning) are read from the export (`manifest.texts`,
 * `meta.texts`), never copied here; the `"missing input"` strings stay in the builders.
 */

/** `apps/api/atlas_api/main.py` */
export const MAX_WINDOW_DAYS = 366;
export const DEFAULT_TAU = 0.5;
export const SERIES_MAX_POINTS = 2_000;
/** A TSK fires nothing below this total (`fallback_used`). */
export const FALLBACK_EPS = 1e-10;
