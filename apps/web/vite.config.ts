/// <reference types="vitest/config" />
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// In dev, /api is proxied to the API (`make api` from the repo root: port 8000). ATLAS_API_URL points the proxy elsewhere
// (e.g. a second API on 8010 next to a running demo).
const API_TARGET = process.env.ATLAS_API_URL ?? "http://127.0.0.1:8000";

// Static build (GitHub Pages): `vite build --mode static` reads .env.static (VITE_ATLAS_DATA=static). The site then lives
// under the repository's path, so every asset, the data and the landing maps resolve under /exfuzzy-atlas/. The export
// (data/<id>/) is named by VITE_ATLAS_EXPORT_ID, embedded at build time; VITE_ATLAS_DATA_URL points elsewhere instead.
const PAGES_BASE = "/exfuzzy-atlas/";

export default defineConfig(({ mode }) => {
  const env = { ...loadEnv(mode, process.cwd(), "VITE_"), ...process.env };
  const isStatic = env.VITE_ATLAS_DATA === "static";
  if (isStatic && !env.VITE_ATLAS_EXPORT_ID && !env.VITE_ATLAS_DATA_URL) {
    throw new Error("A static build needs VITE_ATLAS_EXPORT_ID (the export id) or VITE_ATLAS_DATA_URL");
  }
  return {
    plugins: [react()],
    base: env.VITE_BASE ?? (isStatic ? PAGES_BASE : "/"),
    server: {
      proxy: {
        "/api": { target: API_TARGET, changeOrigin: true },
      },
    },
    preview: {
      proxy: {
        "/api": { target: API_TARGET, changeOrigin: true },
      },
    },
    // MapLibre GL alone is ~1 MB minified; not worth splitting for the prototype.
    build: { chunkSizeWarningLimit: 1500 },
    test: {
      environment: "jsdom",
      setupFiles: ["./src/test/setup.ts"],
      css: false,
    },
  };
});
