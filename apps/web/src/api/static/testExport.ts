/**
 * A tiny export written by hand to the format of docs/static_export.md, for the unit tests of the builders. Every number
 * is a binary fraction (0.5, 0.25, 0.125 ...), so a firing is exactly the product of its memberships and the expected
 * values in the tests can be checked by hand. The exporter's own output replaces it in the parity test (phase 5).
 *
 * Three models:
 *  - `m-win` / `t-win`: winning-rule classifier, regular, two days, entities A, B (modelled) and U (not modelled).
 *  - `m-mix` / `t-mix`: mixture of rules, one row.
 *  - `m-tsk` / `t-tsk`: additive TSK regressor, irregular (key `all`), entities W1, W2.
 */

export const ID = "0123456789ab";
const REASONS = ["no_observation", "invalid_observation", "censored", "missing_input", "prediction_unavailable", "not_modelled"];
const [NO_OBS, , , MISSING_INPUT, UNAVAILABLE] = [0, 1, 2, 3, 4];
export const reasonCode = { NO_OBS, MISSING_INPUT, UNAVAILABLE };

const point = (lon: number, lat: number) => ({ type: "Point", coordinates: [lon, lat] });
const entity = (id: string, name: string, lon: number, modelled = true) => ({
  type: "Feature",
  id,
  geometry: modelled ? point(lon, 40) : null,
  properties: {
    entity_id: id, name, domain: "air", geometry_support: modelled ? "observed_point" : "observed_polygon", geometry_source: "test",
    timezone: "UTC", ...(modelled ? {} : { modelled: false }),
  },
});
const collection = (domain: string, features: unknown[]) => ({
  schema_version: "0.7.0", data_version: "dv1", synthetic: false, type: "FeatureCollection", domain, attribution: [], features,
});

const term = (name: string) => ({ name, label: name, membership_type: "triangular", params: [0, 0, 1] });
const variable = (feature: string, domain: [number, number]) => ({ feature, label: feature, domain, unit: null, terms: [term("Low"), term("High")] });

/** `hours[h] = [value for E0, value for E1]` of a 24 x |E| lattice. */
const lattice = (nE: number, hours: Record<number, (number | null)[]>) => ({
  v: 1, kind: "inputs", layout: "lattice",
  values: Array.from({ length: 24 * nE }, (_, k) => hours[Math.floor(k / nE)]?.[k % nE] ?? null),
});

const inference = (family: string, extra: Record<string, unknown> = {}) => ({
  exfuzzy_version: "3.4.0", fallback: "none", family, tnorm: "product", tolerance: 1e-10, ...extra,
});

function winning(files: Map<string, unknown>) {
  const meta = {
    format_version: 2, model_id: "m-win", task_id: "t-win", domain: "air", territory: "x", task_type: "classification",
    family: "winning_rule_classifier", data_version: "dv1", synthetic: false, target: "no2", unit: "ug/m3", target_unit: "ug/m3",
    horizon_hours: 6, regular: true, step_hours: 1,
    coverage: { from: "2025-03-05T22:00:00Z", to: "2025-03-06T00:00:00Z" },
    keys: ["2025-03-05", "2025-03-06"], entities: ["A", "B"], rules: ["R01", "R02"], classes: ["Good", "Bad"],
    decides: true, mixture: false,
    features: [
      { name: "x", obs_unit: "ug/m3", trace_unit: "µg/m³", source_id: null, lag_hours: 0, input: "inputs/x/x" },
      { name: "y", obs_unit: "m/s", trace_unit: "m/s", source_id: "src-y", lag_hours: 1, input: "inputs/x/y" },
    ],
    mem_pairs: [["x", "is", "Low"], ["x", "is", "High"], ["y", "is", "Low"]],
    inference: inference("winning_rule_classifier", { rule_weighting: "weight", allow_unknown: true }),
    windows: { day: ["2025-03-05", "2025-03-06"], week: ["2025-03-03"], month: ["2025-03-01"], year: [], coverage: true },
    stories: { tau: 0.5, limit: 10 }, taus: [0.25, 0.5, 0.75, 1],
    whatif: { instants: ["2025-03-05T22:00:00Z"], steps: 3, per_entity: true },
    missing_reasons: REASONS, texts: { no_reference_warning: noReference("associations") },
  };
  const rule = (id: string, position: number, antecedents: unknown[], weight: number) => ({
    rule_id: id, position, antecedents, weight, consequent: { type: "class", term: "Good" }, text: id,
  });
  const rules = {
    schema_version: "0.7.0", data_version: "dv1", synthetic: false, model_id: "m-win", task_id: "t-win", domain: "air",
    inference: meta.inference,
    variables: [variable("x", [0, 40]), variable("y", [0, 40])],
    rules: [
      rule("R01", 0, [{ feature: "x", term: "Low" }, { feature: "y", term: "Low" }], 1),
      rule("R02", 1, [{ feature: "x", term: "High" }, { feature: "y", term: "Low", modifier: 2 }], 0.5),
    ],
    target_scheme: { name: "scheme", source_url: "", unit: "ug/m3", classes: [{ label: "Good", lower: 0, upper: 1 }, { label: "Bad", lower: 1, upper: 2 }] },
  };
  files.set("models/m-win/meta.json.gz", meta);
  files.set("models/m-win/rules.json.gz", rules);
  files.set("models/m-win/card.json.gz", { schema_version: "0.7.0", data_version: "dv1", manifest: { model_id: "m-win" } });
  files.set("models/m-win/importance.json.gz", { model_id: "m-win" });
  files.set("tasks/t-win/entities.json.gz", collection("air", [entity("A", "Alpha", 0), entity("B", "Beta", 1), entity("U", "Unmodelled", 2, false)]));
  // rows: 0 A@22, 1 B@22 (y missing), 2 B@23; A@23 has no row; day 2: 3 A@00 (nothing fires), 4 B@00 (no reference level)
  files.set("models/m-win/2025-03-05/pred.json.gz", {
    v: 1, kind: "pred", model_id: "m-win", key: "2025-03-05", t: ["2025-03-05T22:00:00Z", "2025-03-05T23:00:00Z"], n: 3,
    ti: [0, 0, 1], ei: [0, 1, 1],
    plabel: [0, null, 1], obs: [12, null, 50], olabel: [0, null, 1],
    reason: [null, MISSING_INPUT, null], decided: [0, null, 1],
  });
  files.set("models/m-win/2025-03-05/fire.json.gz", { v: 1, kind: "fire", n: 3, f: [[0.25, null, 0], [0.125, null, 1]] });
  files.set("models/m-win/2025-03-05/mem.json.gz", { v: 1, kind: "mem", n: 3, m: [[0.5, 0, 0], [0.5, 1, 1], [0.5, null, 1]] });
  files.set("models/m-win/2025-03-06/pred.json.gz", {
    v: 1, kind: "pred", model_id: "m-win", key: "2025-03-06", t: ["2025-03-06T00:00:00Z"], n: 2, ti: [0, 0], ei: [0, 1],
    plabel: [null, null], obs: [5, 7], olabel: [0, null], reason: [UNAVAILABLE, UNAVAILABLE], decided: [null, null], noref: [0, 1],
  });
  files.set("models/m-win/2025-03-06/fire.json.gz", { v: 1, kind: "fire", n: 2, f: [[0, 0.25], [0, 0.125]] });
  files.set("models/m-win/2025-03-06/mem.json.gz", { v: 1, kind: "mem", n: 2, m: [[0, 0.5], [0, 0.5], [0, 0.5]] });
  // x: A 10, B 30 at 22h; B 30 at 23h; 0 / 10 at 00h.   y: A 20 at 22h; B 10 at 23h; 0 / 20 at 00h
  files.set("inputs/x/x/2025-03-05.json.gz", lattice(2, { 22: [10, 30], 23: [null, 30] }));
  files.set("inputs/x/y/2025-03-05.json.gz", lattice(2, { 22: [20, null], 23: [null, 10] }));
  files.set("inputs/x/x/2025-03-06.json.gz", lattice(2, { 0: [0, 10] }));
  files.set("inputs/x/y/2025-03-06.json.gz", lattice(2, { 0: [0, 20] }));
  // windows: [r * |E| + e], rules x entities (R01A, R01B, R02A, R02B)
  const agg = (kind: string, from: string, to: string, p: { nr: number[]; nv: number[]; sum: number[]; over: number[][]; win: number[] }) =>
    ({ v: 1, kind: "agg", model_id: "m-win", window: { kind, from, to }, n_records: p.nr, n_valid: p.nv, sum: p.sum, over: p.over, win: p.win });
  const all = { nr: [2, 3], nv: [2, 2], sum: [0.25, 0.25, 0.125, 1.125], over: [[1, 1, 0, 1], [0, 0, 0, 1], [0, 0, 0, 1], [0, 0, 0, 1]], win: [1, 1, 0, 1] };
  files.set("models/m-win/agg/day/2025-03-05.json.gz", agg("day", "2025-03-05T00:00:00Z", "2025-03-06T00:00:00Z", {
    nr: [1, 2], nv: [1, 1], sum: [0.25, 0, 0.125, 1], over: [[1, 0, 0, 1], [0, 0, 0, 1], [0, 0, 0, 1], [0, 0, 0, 1]], win: [1, 0, 0, 1],
  }));
  files.set("models/m-win/agg/day/2025-03-06.json.gz", agg("day", "2025-03-06T00:00:00Z", "2025-03-07T00:00:00Z", {
    nr: [1, 1], nv: [1, 1], sum: [0, 0.25, 0, 0.125], over: [[0, 1, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]], win: [0, 1, 0, 0],
  }));
  files.set("models/m-win/agg/week/2025-03-03.json.gz", agg("week", "2025-03-03T00:00:00Z", "2025-03-10T00:00:00Z", all));
  files.set("models/m-win/agg/month/2025-03-01.json.gz", agg("month", "2025-03-01T00:00:00Z", "2025-04-01T00:00:00Z", all));
  files.set("models/m-win/agg/coverage/all.json.gz", agg("coverage", "2025-03-05T22:00:00Z", "2025-03-06T01:00:00Z", all));
  files.set("models/m-win/stories/day/2025-03-06.json.gz", { model_id: "m-win", stories: [], n_candidates: 0, tau: 0.5, limit: 10 });
  // what-if of A at 22h: x in {0, 10, 20}, y in {0, 20}
  files.set("models/m-win/whatif/A.json.gz", {
    v: 1, kind: "whatif", model_id: "m-win", entity_id: "A", at: ["2025-03-05T22:00:00Z"], grid: { x: [0, 10, 20], y: [0, 20] },
    variants: {
      "2025-03-05T22:00:00Z": {
        x: { f: [[0.5, 0.25, 0], [0, 0.125, 0.25]], m: [[1, 0.5, 0], [0, 0.5, 1]], plabel: [0, 0, 1], decided: [0, 0, 1] },
        y: { f: [[0.5, 0.25], [0.5, 0.125]], m: [[1, 0.5]], plabel: [0, 0], decided: [0, 0] },
      },
    },
  });
}

function mixture(files: Map<string, unknown>) {
  const meta = {
    format_version: 2, model_id: "m-mix", task_id: "t-mix", domain: "air", territory: "m", task_type: "classification",
    family: "rule_mixture_classifier", data_version: "dv1", synthetic: false, target: "no2", unit: "ug/m3", target_unit: "ug/m3",
    horizon_hours: 1, regular: true, step_hours: 1,
    coverage: { from: "2025-03-05T10:00:00Z", to: "2025-03-05T10:00:00Z" },
    keys: ["2025-03-05"], entities: ["M"], rules: ["R01", "R02"], classes: ["Good", "Bad"], decides: false, mixture: true,
    features: [{ name: "x", obs_unit: "ug/m3", trace_unit: "ug/m3", source_id: null, lag_hours: 0, input: "inputs/m/x" }],
    mem_pairs: [["x", "is", "Low"], ["x", "is", "High"]],
    inference: inference("rule_mixture_classifier", { allow_unknown: true }),
    windows: {}, stories: null, taus: [0.5], whatif: null, missing_reasons: REASONS,
    texts: { no_reference_warning: noReference("class scores") },
  };
  const rule = (id: string, position: number, termName: string, w: Record<string, number>, c: Record<string, number>) => ({
    rule_id: id, position, antecedents: [{ feature: "x", term: termName }], class_weights: w, class_weights_centred: c,
    consequent: { type: "class_mixture" }, text: id,
  });
  files.set("models/m-mix/meta.json.gz", meta);
  files.set("models/m-mix/rules.json.gz", {
    schema_version: "0.7.0", data_version: "dv1", synthetic: false, model_id: "m-mix", task_id: "t-mix", domain: "air",
    inference: meta.inference, variables: [variable("x", [0, 40])], class_bias: { Good: 0.25, Bad: 0 },
    rules: [
      rule("R01", 0, "Low", { Good: 1, Bad: 0 }, { Good: 0.5, Bad: -0.5 }),
      rule("R02", 1, "High", { Good: 0, Bad: 1 }, { Good: -0.5, Bad: 0.5 }),
    ],
  });
  files.set("tasks/t-mix/entities.json.gz", collection("air", [entity("M", "Mix", 3)]));
  files.set("models/m-mix/2025-03-05/pred.json.gz", {
    v: 1, kind: "pred", model_id: "m-mix", key: "2025-03-05", t: ["2025-03-05T10:00:00Z"], n: 1, ti: [0], ei: [0],
    plabel: [0], obs: [3], olabel: [0], reason: [null], top: [0], tshare: [1],
  });
  files.set("models/m-mix/2025-03-05/fire.json.gz", { v: 1, kind: "fire", n: 1, f: [[0.75], [0.25]] });
  files.set("models/m-mix/2025-03-05/mem.json.gz", { v: 1, kind: "mem", n: 1, m: [[0.75], [0.25]] });
  files.set("inputs/m/x/2025-03-05.json.gz", lattice(1, { 10: [10] }));
}

function tsk(files: Map<string, unknown>) {
  const meta = {
    format_version: 2, model_id: "m-tsk", task_id: "t-tsk", domain: "water", territory: "w", task_type: "regression",
    family: "tsk_zero_order", data_version: "dv1", synthetic: false, target: "do", unit: "mg/l", target_unit: "mg/l",
    horizon_hours: 0, regular: false, step_hours: 1,
    coverage: { from: "2024-05-01T10:00:00Z", to: "2024-05-03T12:00:00Z" },
    keys: ["all"], entities: ["W1", "W2"], rules: ["R01", "R02"], classes: [], decides: true, mixture: false,
    features: [{ name: "temp", obs_unit: "°C", trace_unit: "°C", source_id: null, lag_hours: 0, input: "models/m-tsk/inputs/temp" }],
    mem_pairs: [["temp", "is", "Low"], ["temp", "is", "High"]],
    inference: inference("tsk_zero_order", { rule_mode: "additive" }),
    windows: { day: [], week: [], month: ["2024-05-01"], year: [], coverage: false },
    stories: null, taus: [0.25, 0.5], whatif: null, missing_reasons: REASONS,
  };
  const rule = (id: string, position: number, termName: string) => ({
    rule_id: id, position, antecedents: [{ feature: "temp", term: termName }], consequent: { type: "value", value: id === "R01" ? 2 : 6 }, text: id,
  });
  files.set("models/m-tsk/meta.json.gz", meta);
  files.set("models/m-tsk/rules.json.gz", {
    schema_version: "0.7.0", data_version: "dv1", synthetic: false, model_id: "m-tsk", task_id: "t-tsk", domain: "water",
    inference: meta.inference, variables: [variable("temp", [0, 40])], rules: [rule("R01", 0, "Low"), rule("R02", 1, "High")],
  });
  files.set("tasks/t-tsk/entities.json.gz", collection("water", [entity("W1", "One", 5), entity("W2", "Two", 6)]));
  // rows: 0 W1@2024-05-01 10h (temp 10), 1 W1@2024-05-03 12h (temp missing), 2 W2@2024-05-03 12h (temp 20)
  files.set("models/m-tsk/all/pred.json.gz", {
    v: 1, kind: "pred", model_id: "m-tsk", key: "all", t: ["2024-05-01T10:00:00Z", "2024-05-03T12:00:00Z"], n: 3,
    ti: [0, 1, 1], ei: [0, 0, 1], pred: [4, null, 6], obs: [4.5, 5, null], reason: [null, MISSING_INPUT, null], decided: [0, null, 1],
  });
  files.set("models/m-tsk/all/fire.json.gz", { v: 1, kind: "fire", n: 3, f: [[0.5, null, 0], [0.5, null, 1]] });
  files.set("models/m-tsk/all/mem.json.gz", { v: 1, kind: "mem", n: 3, m: [[0.5, null, 0], [0.5, null, 1]] });
  files.set("models/m-tsk/inputs/temp/all.json.gz", { v: 1, kind: "inputs", layout: "rows", values: [10, null, 20] });
  const agg = (kind: string, from: string, to: string) => ({
    v: 1, kind: "agg", model_id: "m-tsk", window: { kind, from, to }, n_records: [2, 1], n_valid: [1, 1],
    sum: [0.5, 0, 0.5, 1], over: [[1, 0, 1, 1], [1, 0, 1, 1]],
  });
  files.set("models/m-tsk/agg/month/2024-05-01.json.gz", agg("month", "2024-05-01T00:00:00Z", "2024-06-01T00:00:00Z"));
}

/** `manifest.texts`: the words the API writes from contract constants, as the exporter ships them. */
const WHAT_IF_LABEL = "respuesta del modelo ante entradas modificadas \u2014 no efecto causal ni predicci\u00f3n";
export const TEXTS = {
  tie_break:
    "Dominant rule = argmax of the measure over the rules of the entity; values within 1e-12 tie and the rule with the lowest " +
    "position (R01 before R02, ...) wins; null if the measure is 0 for every rule.",
  denominators:
    "n_valid = records of the entity with issue time in [from, to) whose inputs are all present. mean_activation, " +
    "activation_frequency and winner_share are computed over those n_valid records (a missing input is never a 0).",
  territory_notes: [
    "Territories overlap: several rules are active in the same entity and record. They are not a partition.",
    "A rule's activation is a degree of match with the inputs. It is not a probability, a risk nor a contribution to " +
      "the prediction, and the dominant rule is not the rule that explains the prediction.",
  ],
  tie_tolerance: 1e-12,
  what_if_label: WHAT_IF_LABEL,
  what_if_warning: "what-if: inputs overridden ({features}); {label}",
  override_source_id: "what_if_override",
  observations_note:
    "Valores observados publicados (entradas del modelo y objetivo en valid_at_utc), no predicciones ni " +
    "interpolaciones; null = ausente, con su motivo.",
};
const noReference = (what: string) =>
  `no reference level for this row: no class is published; the rule firings and ${what} below are the engine's own outputs`;

/** The whole export as `path -> parsed file`. */
export function testExport(): Map<string, unknown> {
  const files = new Map<string, unknown>();
  files.set("manifest.json", { format: "exfuzzy-atlas-static", format_version: 2, export_id: ID, created_at_utc: "2026-11-10T00:00:00Z", schema_version: "0.7.0", texts: TEXTS });
  const task = (task_id: string, model_id: string, task_type: string, horizon_hours: number, unit: string) => ({
    task_id, model_id, task_type, target: task_id === "t-tsk" ? "do" : "no2", unit, horizon_hours, status: "available",
  });
  files.set("domains.json.gz", {
    schema_version: "0.7.0", data_version: "dv1", synthetic: false,
    domains: [
      { domain: "air", title: "Air", status: "available", tasks: [task("t-win", "m-win", "classification", 6, "ug/m3"), task("t-mix", "m-mix", "classification", 1, "ug/m3")] },
      { domain: "water", title: "Water", status: "available", tasks: [task("t-tsk", "m-tsk", "regression", 0, "mg/l")] },
      { domain: "mobility", title: "Mobility", status: "planned", tasks: [] },
    ],
  });
  winning(files);
  mixture(files);
  tsk(files);
  return files;
}
