// Saves small golden API responses of the REAL published NYC and Water models as web test fixtures
// (src/test/fixtures-real/{nyc,water}). Source: the artifacts-mode API over `artifacts/published`
//   exfuzzy-nyc_pickups_h1-level-rel7-seed0  (data_version nyc-tlc-yellow-2024-04_2025-03-v1)
//   exfuzzy-uk_water_do-water-do-chrono-temp-seed0  (data_version uk-wq-ne-x-h-rivers-2015-2025-20261030)
//   ATLAS_API_MODE=artifacts ATLAS_PUBLISHED_DIR=<main checkout>/artifacts/published make api
//   node scripts/save-real-fixtures.mjs http://127.0.0.1:8000/api/v1
// Responses are stored as the API sent them, with these cuts only: entities, series and rule-map features are limited to a
// handful of zones/points (listed below), series to a short window (NYC) or to the whole coverage of those points (Water),
// and the model card's metric rows to slice "all" and the headline metrics.
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const base = process.argv[2] ?? "http://127.0.0.1:8000/api/v1";
const root = join(dirname(fileURLToPath(import.meta.url)), "..", "src", "test", "fixtures-real");
const get = async (path, q = {}) => {
  const url = `${base}${path}?${new URLSearchParams(q)}`;
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json();
};
const save = (dir, name, data, indent) => {
  mkdirSync(join(root, dir), { recursive: true });
  writeFileSync(join(root, dir, name), `${JSON.stringify(data, null, indent)}\n`);
};
const slimCard = (card) => ({
  ...card,
  metrics: card.metrics && {
    ...card.metrics,
    rows: card.metrics.rows.filter((r) => (r.slice ?? "all") === "all" && ["macro_f1", "balanced_accuracy", "accuracy", "mae", "rmse", "r2"].includes(r.metric)),
  },
});
const only = (collection, ids) => ({ ...collection, features: collection.features.filter((f) => ids.has(f.properties?.entity_id ?? f.id)) });

const domains = await get("/domains");
save(".", "domains.json", domains, 1);

// ---- NYC: 8 zones (two MultiPolygon: 39 and 74; 35 and 39 have no reference level at the chosen hour)
{
  const task = domains.domains.find((d) => d.domain === "mobility").tasks[0];
  const modelId = task.model_id;
  const ids = new Set(["4", "7", "35", "39", "41", "43", "68", "74"]);
  const at = "2025-03-19T23:00:00Z"; // Wednesday 19:00 America/New_York (EDT)
  save("nyc", "entities.json", only(await get("/entities", { domain: "mobility" }), ids), 1);
  save("nyc", "card.json", slimCard(await get(`/models/${modelId}`)), 1);
  save("nyc", "rules.json", await get(`/models/${modelId}/rules`), 1);
  const series = [];
  for (const id of ids) series.push(await get("/series", { task_id: task.task_id, entity_id: id, from: "2025-03-19T12:00:00Z", to: "2025-03-20T12:00:00Z" }));
  save("nyc", "series.json", series);
  save("nyc", "rule_traces.json", await Promise.all(["4", "35"].map((id) => get(`/entities/${id}/rule-trace`, { model_id: modelId, at }))), 1);
  const query = { model_id: modelId, rule_id: "R01", metric: "firing_strength", time: at };
  save("nyc", "rule_maps.json", [{ query, response: only(await get("/rule-map", query), ids) }], 1);
}

// ---- Water: 5 points with a sample in December 2025 and one without
{
  const task = domains.domains.find((d) => d.domain === "water").tasks[0];
  const modelId = task.model_id;
  const all = await get("/entities", { domain: "water" });
  const full = { from: "2024-01-01T00:00:00Z", to: "2026-01-01T00:00:00Z" };
  const withSamples = [];
  let without = null;
  for (const f of all.features) {
    const id = f.properties.entity_id;
    const s = await get("/series", { task_id: task.task_id, entity_id: id, ...full });
    const dec = s.points.some((p) => p.issued_at_utc >= "2025-12-01T00:00:00Z");
    if (dec && s.points.length <= 25 && withSamples.length < 5) withSamples.push(s);
    else if (!dec && s.points.length >= 3 && !without) without = s;
    if (withSamples.length === 5 && without) break;
  }
  const chosen = [...withSamples, without];
  const ids = new Set(chosen.map((s) => s.entity_id));
  save("water", "entities.json", only(all, ids), 1);
  save("water", "card.json", slimCard(await get(`/models/${modelId}`)), 1);
  save("water", "rules.json", await get(`/models/${modelId}/rules`), 1);
  save("water", "series.json", chosen);
  const first = withSamples[0];
  const lastDec = first.points.filter((p) => p.issued_at_utc >= "2025-12-01T00:00:00Z").at(-1);
  save("water", "rule_traces.json", [await get(`/entities/${first.entity_id}/rule-trace`, { model_id: modelId, at: lastDec.issued_at_utc })], 1);
  const maps = [];
  for (const rule_id of ["R01", "R02"]) {
    const query = { model_id: modelId, rule_id, metric: "mean_activation", from: "2025-12-01T00:00:00Z", to: "2026-01-01T00:00:00Z" };
    maps.push({ query, response: only(await get("/rule-map", query), ids) });
  }
  save("water", "rule_maps.json", maps, 1);
}
console.log(`saved real fixtures in ${root}`);
