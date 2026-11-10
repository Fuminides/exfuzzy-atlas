// Saves golden API responses of the SYNTHETIC classifier publish as web test fixtures (src/test/fixtures-class).
//   make publish-demo-class && ATLAS_PUBLISHED_DIR=artifacts/published-demo-class/published make api-artifacts
//   node scripts/save-class-fixtures.mjs http://127.0.0.1:8000/api/v1 [http://127.0.0.1:8001/api/v1]
// The optional second base is an API serving the real ICA model (exfuzzy-madrid_no2_h6-ica-v1-seed0): only its
// `target_scheme` (the official ICA classes, merged "Desfavorable o peor" included) and the test-period metric rows
// (slice "all", baselines included) are saved, as ica_scheme.json and ica_metrics.json.
// The responses are stored exactly as the API sent them (series and traces are cut to a few windows/instants).
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const base = process.argv[2] ?? "http://127.0.0.1:8000/api/v1";
const out = join(dirname(fileURLToPath(import.meta.url)), "..", "src", "test", "fixtures-class");
mkdirSync(out, { recursive: true });
const get = async (path, q = {}) => {
  const url = `${base}${path}?${new URLSearchParams(q)}`;
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.json();
};
const save = (name, data) => writeFileSync(join(out, name), `${JSON.stringify(data, null, 1)}\n`);

const domains = await get("/domains");
const task = domains.domains.find((d) => d.domain === "air").tasks[0];
if (task.task_type !== "classification") throw new Error("the API is not serving a classifier");
const modelId = task.model_id;
save("domains.json", domains);
const entities = await get("/entities", { domain: "air" });
save("entities.json", entities);
save("card.json", await get(`/models/${modelId}`));
save("rules.json", await get(`/models/${modelId}/rules`));

const ids = entities.features.map((f) => f.properties.entity_id);
const series = [];
for (const id of ids) {
  series.push(await get("/series", { task_id: task.task_id, entity_id: id, from: "2024-01-05T00:00:00Z", to: "2024-01-09T00:00:00Z" }));
}
save("series.json", series);

// E0 at 2024-01-06T09Z has no predicted class; 10:00Z has one.
const traces = [];
for (const [id, at] of [["E0", "2024-01-06T09:00:00Z"], ["E0", "2024-01-06T10:00:00Z"], ["E1", "2024-01-06T10:00:00Z"]]) {
  traces.push(await get(`/entities/${id}/rule-trace`, { model_id: modelId, at }));
}
save("rule_traces.json", traces);

const ruleMaps = [];
for (const [rule, time] of [["R01", "2024-01-05T00:00:00Z"], ["R01", "2024-01-06T10:00:00Z"], ["R02", "2024-01-06T10:00:00Z"]]) {
  const query = { model_id: modelId, rule_id: rule, metric: "firing_strength", time };
  ruleMaps.push({ query, response: await get("/rule-map", query) });
}
save("rule_maps.json", ruleMaps);
if (process.argv[3]) {
  const ica = await (await fetch(`${process.argv[3]}/models/exfuzzy-madrid_no2_h6-ica-v1-seed0`)).json();
  save("ica_scheme.json", ica.target_scheme);
  save("ica_metrics.json", { ...ica.metrics, rows: ica.metrics.rows.filter((r) => (r.slice ?? "all") === "all") });
}
console.log(`saved fixtures for ${modelId} in ${out}`);
