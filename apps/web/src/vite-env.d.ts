/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Basemap style URL; default OpenFreeMap Positron. */
  readonly VITE_BASEMAP_STYLE_URL?: string;
  /** Model to explore until the API can list models (see README). */
  readonly VITE_MODEL_ID?: string;
  /** API base path; default "/api/v1". */
  readonly VITE_API_BASE?: string;
  /** "static": no API, every response is built from the precomputed export (docs/static_export.md). */
  readonly VITE_ATLAS_DATA?: string;
  /** Static mode: the export id (12 hex characters), embedded at build time. */
  readonly VITE_ATLAS_EXPORT_ID?: string;
  /** Static mode: base URL of the export, instead of `<base>data/<export id>/`. */
  readonly VITE_ATLAS_DATA_URL?: string;
}
