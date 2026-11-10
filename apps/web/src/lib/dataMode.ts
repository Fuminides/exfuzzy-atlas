/**
 * Static mode: the site is deployed as plain files (GitHub Pages) and every response is built in the browser from the
 * precomputed export (`src/api/static/`). Selected at build time: `VITE_ATLAS_DATA=static`. A function (not a constant)
 * so a test can switch it; Vite still replaces the `import.meta.env` read at build time.
 */
export const isStaticData = (): boolean => import.meta.env.VITE_ATLAS_DATA === "static";

/**
 * Where the export lives: `VITE_ATLAS_DATA_URL` when given, else `<base>data/<export id>/` (the build's `base`, so the
 * data follows `/exfuzzy-atlas/` on Pages). The export id is embedded at build time: a new export is a new path, so a
 * cached file never mixes two exports.
 */
export function staticDataBase(): string {
  const url = import.meta.env.VITE_ATLAS_DATA_URL;
  const base = url ?? `${import.meta.env.BASE_URL}data/${import.meta.env.VITE_ATLAS_EXPORT_ID ?? ""}/`;
  return base.endsWith("/") ? base : `${base}/`;
}

/** Stories are exported at one τ only (the export's `stories.tau`); this is the one the format fixes. */
export const STORIES_TAU = 0.5;
