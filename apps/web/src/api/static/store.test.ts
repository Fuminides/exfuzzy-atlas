import { describe, expect, it } from "vitest";
import type { PredictionFeature, TerritoryFeature } from "../types";
import { memorySource } from "./source";
import { StaticStore } from "./store";
import { testExport } from "./testExport";
import { windowRef } from "./windows";
import type { Meta } from "./types";

const store = (edit?: (files: Map<string, unknown>) => void) => {
  const files = testExport();
  edit?.(files);
  return new StaticStore(memorySource(files));
};
const props = <T extends { id: string; properties: unknown }>(features: T[]) => Object.fromEntries(features.map((f) => [f.id, f.properties])) as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const status = async (p: Promise<unknown>) => p.then(() => 200, (e: { status: number; detail?: string }) => ({ status: e.status, detail: e.detail }));

describe("exact bodies", () => {
  it("serves domains, a task's entities, the card and the rules as they are", async () => {
    const s = store();
    const files = testExport();
    expect(await s.domains()).toEqual(files.get("domains.json.gz"));
    expect(await s.entities("air", "t-win")).toEqual(files.get("tasks/t-win/entities.json.gz"));
    expect(await s.modelCard("m-win")).toEqual(files.get("models/m-win/card.json.gz"));
    expect(await s.modelRules("m-mix")).toEqual(files.get("models/m-mix/rules.json.gz"));
  });

  it("picks the task as the API does", async () => {
    const s = store();
    expect(((await s.entities("water", undefined)) as { domain: string }).domain).toBe("water");
    expect(await status(s.entities("air", undefined))).toMatchObject({ status: 422, detail: expect.stringContaining("pass task_id") });
    expect(await status(s.entities("water", "t-win"))).toMatchObject({ status: 422 });
    expect(await status(s.entities("air", "nope"))).toMatchObject({ status: 404 });
    expect(await status(s.entities("mobility", undefined))).toMatchObject({ status: 404 });
  });

  it("answers 404 for a file the export does not hold, never an empty body", async () => {
    const s = store();
    expect(await status(s.importance("m-mix"))).toMatchObject({ status: 404 });
    expect(await status(s.explanation("m-win"))).toMatchObject({ status: 404 });
    expect(await status(s.summary("t-win"))).toMatchObject({ status: 404 });
    expect(await status(s.modelCard("nope"))).toMatchObject({ status: 404 });
    expect((await s.importance("m-win")) as unknown).toEqual({ model_id: "m-win" });
  });
});

describe("predictions", () => {
  it("builds one Feature per entity at an issue time", async () => {
    const r = await store().predictions({ taskId: "t-win", time: "2025-03-05T22:00:00Z" });
    expect(r).toMatchObject({
      type: "FeatureCollection", schema_version: "0.7.0", data_version: "dv1", synthetic: false, task_id: "t-win", model_id: "m-win",
      task_type: "classification", target: "no2", unit: "ug/m3", horizon_hours: 6, issued_at_utc: "2025-03-05T22:00:00Z",
      time_from_utc: null, time_to_utc: null,
    });
    expect(r.features.map((f) => f.id)).toEqual(["A", "B", "U"]);
    const p = props(r.features);
    expect(p.A).toMatchObject({
      issued_at_utc: "2025-03-05T22:00:00Z", valid_at_utc: "2025-03-06T04:00:00Z", prediction: null, prediction_label: "Good", observed: 12,
      observed_label: "Good", missing_reason: null, decided_by_rule_id: "R01", top_rule_id: null, top_rule_share: null,
      quality: { status: "valid", warnings: [] }, geometry_support: "observed_point", unit: "ug/m3",
    });
    // a missing input is a missing reason, not a class
    expect(p.B).toMatchObject({ prediction_label: null, observed: null, missing_reason: "missing_input", decided_by_rule_id: null });
    expect(p.U).toMatchObject({ issued_at_utc: null, valid_at_utc: null, missing_reason: "not_modelled" });
    expect(r.features[2]!.geometry).toBeNull();
    expect(r.features[0]!.geometry).toEqual({ type: "Point", coordinates: [0, 40] });
  });

  it("says an entity without a row has no observation", async () => {
    const r = await store().predictions({ taskId: "t-win", time: "2025-03-05T23:00:00Z" });
    const p = props(r.features);
    expect(p.A).toMatchObject({ issued_at_utc: null, missing_reason: "no_observation", prediction_label: null });
    expect(p.B).toMatchObject({ prediction_label: "Bad", decided_by_rule_id: "R02", observed_label: "Bad" });
    // an hour no shard covers: nobody has data
    const none = await store().predictions({ taskId: "t-win", time: "2025-03-09T00:00:00Z" });
    expect(none.features.map((f) => f.properties.missing_reason)).toEqual(["no_observation", "no_observation", "not_modelled"]);
  });

  it("takes each entity's latest row of a window, across shards", async () => {
    const r = await store().predictions({ taskId: "t-win", from: "2025-03-05T22:00:00Z", to: "2025-03-06T01:00:00Z" });
    expect(r).toMatchObject({ issued_at_utc: null, time_from_utc: "2025-03-05T22:00:00Z", time_to_utc: "2025-03-06T01:00:00Z" });
    const p = props(r.features);
    expect(p.A).toMatchObject({ issued_at_utc: "2025-03-06T00:00:00Z", prediction_label: null, missing_reason: "prediction_unavailable", observed: 5 });
    expect(p.B).toMatchObject({ issued_at_utc: "2025-03-06T00:00:00Z", missing_reason: "prediction_unavailable" });
    const first = await store().predictions({ taskId: "t-win", from: "2025-03-05T22:00:00Z", to: "2025-03-05T23:30:00Z" });
    expect(props(first.features).A.issued_at_utc).toBe("2025-03-05T22:00:00Z");
    expect(props(first.features).B.issued_at_utc).toBe("2025-03-05T23:00:00Z");
  });

  it("names the rule that supports a mixture's class, and no deciding rule", async () => {
    const r = await store().predictions({ taskId: "t-mix", time: "2025-03-05T10:00:00Z" });
    expect(r.features[0]!.properties).toMatchObject({ prediction_label: "Good", decided_by_rule_id: null, top_rule_id: "R01", top_rule_share: 1 });
  });

  it("builds a regressor's prediction from an irregular task's single shard", async () => {
    const r = await store().predictions({ taskId: "t-tsk", from: "2024-05-01T00:00:00Z", to: "2024-06-01T00:00:00Z" });
    const p = props(r.features as PredictionFeature[]);
    expect(p.W1).toMatchObject({ issued_at_utc: "2024-05-03T12:00:00Z", valid_at_utc: "2024-05-03T12:00:00Z", prediction: null, missing_reason: "missing_input", observed: 5 });
    expect(p.W2).toMatchObject({ prediction: 6, prediction_label: null, missing_reason: null, decided_by_rule_id: "R02" });
    expect(r).toMatchObject({ task_type: "regression", unit: "mg/l" });
  });

  it("rejects the query shapes the API rejects", async () => {
    const s = store();
    expect(await status(s.predictions({ taskId: "t-win" }))).toMatchObject({ status: 422 });
    expect(await status(s.predictions({ taskId: "t-win", time: "2025-03-05T22:00:00Z", from: "2025-03-05T00:00:00Z", to: "2025-03-06T00:00:00Z" }))).toMatchObject({ status: 422 });
    expect(await status(s.predictions({ taskId: "t-win", from: "2025-03-06T00:00:00Z", to: "2025-03-05T00:00:00Z" }))).toMatchObject({ status: 422, detail: "`to` must be after `from`" });
    expect(await status(s.predictions({ taskId: "t-win", from: "2024-01-01T00:00:00Z", to: "2025-03-05T00:00:00Z" }))).toMatchObject({ status: 422 });
    expect(await status(s.predictions({ taskId: "nope", time: "2025-03-05T22:00:00Z" }))).toMatchObject({ status: 404 });
  });
});

describe("observations", () => {
  it("lays the inputs of the hour next to the observed target", async () => {
    const r = await store().observations({ taskId: "t-win", time: "2025-03-05T22:00:00Z" });
    expect(r.note).toMatch(/^Valores observados publicados/);
    const p = props(r.features);
    expect(p.A.inputs).toEqual([
      { feature: "x", value: 10, unit: "ug/m3", source_id: null, observed_at_utc: "2025-03-05T22:00:00Z", missing_reason: null },
      { feature: "y", value: 20, unit: "m/s", source_id: "src-y", observed_at_utc: "2025-03-05T21:00:00Z", missing_reason: null },
    ]);
    expect(p.A.target).toEqual({
      feature: "no2", value: 12, unit: "ug/m3", source_id: null, observed_at_utc: "2025-03-06T04:00:00Z", missing_reason: null,
    });
    expect(p.A).toMatchObject({ target_label: "Good", quality: { status: "valid", warnings: [] }, missing_reason: null });
  });

  it("marks a missing input as absent with its reason, never as 0", async () => {
    const p = props((await store().observations({ taskId: "t-win", time: "2025-03-05T22:00:00Z" })).features);
    expect(p.B.inputs[1]).toMatchObject({ feature: "y", value: null, observed_at_utc: null, missing_reason: "no_observation" });
    expect(p.B.target).toMatchObject({ value: null, missing_reason: "no_observation" });
    expect(p.B.quality).toEqual({ status: "warning", warnings: ["missing input: y"] });
    expect(p.U).toMatchObject({ issued_at_utc: null, target: null, inputs: [], missing_reason: "not_modelled" });
  });

  it("reads each row's input from the day of that row when it is a window", async () => {
    const r = await store().observations({ taskId: "t-win", from: "2025-03-05T22:00:00Z", to: "2025-03-06T01:00:00Z" });
    const p = props(r.features);
    expect(p.A.inputs.map((i: { value: number }) => i.value)).toEqual([0, 0]);
    expect(p.B.inputs.map((i: { value: number }) => i.value)).toEqual([10, 20]);
  });

  it("reads an irregular task's inputs row by row", async () => {
    const r = await store().observations({ taskId: "t-tsk", from: "2024-05-01T00:00:00Z", to: "2024-06-01T00:00:00Z" });
    const p = props(r.features);
    expect(p.W1.inputs[0]).toMatchObject({ value: null, missing_reason: "no_observation" });
    expect(p.W2.inputs[0]).toMatchObject({ value: 20, unit: "°C" });
  });
});

describe("rule map", () => {
  it("is the firing of the row at an instant", async () => {
    const r = await store().ruleMap({ modelId: "m-win", ruleId: "R01", metric: "firing_strength", time: "2025-03-05T22:00:00Z" });
    expect(r).toMatchObject({ rule_id: "R01", metric: "firing_strength", tau: null, time_from_utc: "2025-03-05T22:00:00Z", time_to_utc: "2025-03-05T22:00:00Z" });
    const p = props(r.features);
    expect(p.A).toMatchObject({ value: 0.25, n_valid: 1, issued_at_utc: "2025-03-05T22:00:00Z", valid_at_utc: "2025-03-06T04:00:00Z", missing_reason: null, tau: null });
    expect(p.B).toMatchObject({ value: null, n_valid: 0, missing_reason: "missing_input", valid_at_utc: "2025-03-06T04:00:00Z", quality: { status: "warning", warnings: ["missing input"] } });
    expect(p.U).toMatchObject({ value: null, missing_reason: "not_modelled", valid_at_utc: null });
  });

  it("keeps a firing of 0 as 0 and an absent row as no observation", async () => {
    const p = props((await store().ruleMap({ modelId: "m-win", ruleId: "R01", metric: "firing_strength", time: "2025-03-05T23:00:00Z" })).features);
    expect(p.B).toMatchObject({ value: 0, n_valid: 1 });
    expect(p.A).toMatchObject({ value: null, missing_reason: "no_observation", valid_at_utc: null });
  });

  it("averages and counts over a window from its statistics", async () => {
    const s = store();
    const window = { from: "2025-03-05T22:00:00Z", to: "2025-03-06T01:00:00Z" };
    const mean = await s.ruleMap({ modelId: "m-win", ruleId: "R02", metric: "mean_activation", ...window });
    expect(mean).toMatchObject({ tau: null, time_from_utc: window.from, time_to_utc: window.to });
    expect(props(mean.features).A).toMatchObject({ value: 0.0625, n_valid: 2, issued_at_utc: null, valid_at_utc: null, tau: null });
    expect(props(mean.features).B.value).toBe(0.5625);
    const frequency = await s.ruleMap({ modelId: "m-win", ruleId: "R02", metric: "activation_frequency", tau: 0.5, ...window });
    expect(frequency.tau).toBe(0.5);
    expect(props(frequency.features).B).toMatchObject({ value: 0.5, tau: 0.5 });
    expect(props(frequency.features).A.value).toBe(0);
    // the UTC day and the ISO week are windows too
    expect(props((await s.ruleMap({ modelId: "m-win", ruleId: "R01", metric: "mean_activation", from: "2025-03-06T00:00:00Z", to: "2025-03-07T00:00:00Z" })).features).B.value).toBe(0.25);
    expect(props((await s.ruleMap({ modelId: "m-win", ruleId: "R01", metric: "mean_activation", from: "2025-03-03T00:00:00Z", to: "2025-03-10T00:00:00Z" })).features).A.value).toBe(0.125);
  });

  it("separates a window with records but no valid input from one with no records", async () => {
    const s = store((files) => {
      const day = files.get("models/m-win/agg/day/2025-03-05.json.gz") as { n_valid: number[] };
      day.n_valid = [1, 0];
    });
    const day = { from: "2025-03-05T00:00:00Z", to: "2025-03-06T00:00:00Z" };
    const p = props((await s.ruleMap({ modelId: "m-win", ruleId: "R01", metric: "mean_activation", ...day })).features);
    expect(p.B).toMatchObject({ value: null, n_valid: 0, missing_reason: "missing_input", quality: { status: "warning", warnings: ["missing input"] } });
    // a day the model has no window for: nothing was observed
    const later = props((await s.ruleMap({ modelId: "m-win", ruleId: "R01", metric: "mean_activation", from: "2025-03-07T00:00:00Z", to: "2025-03-08T00:00:00Z" })).features);
    expect(later.A).toMatchObject({ value: null, n_valid: 0, missing_reason: "no_observation" });
    expect(later.U.missing_reason).toBe("not_modelled");
  });

  it("is a 404 when a listed window has no file: the export is incomplete", async () => {
    const s = store((files) => files.delete("models/m-win/agg/day/2025-03-06.json.gz"));
    expect(await status(s.ruleMap({ modelId: "m-win", ruleId: "R01", metric: "mean_activation", from: "2025-03-06T00:00:00Z", to: "2025-03-07T00:00:00Z" }))).toMatchObject({ status: 404 });
  });

  it("answers 422 for a window or a tau the export does not hold, and 404 for an unknown rule", async () => {
    const s = store();
    const q = { modelId: "m-win", ruleId: "R01", metric: "mean_activation" as const };
    expect(await status(s.ruleMap({ ...q, from: "2025-03-05T22:00:00Z", to: "2025-03-05T23:00:00Z" }))).toMatchObject({ status: 422, detail: "window not precomputed" });
    expect(await status(s.ruleMap({ ...q, from: "2025-01-01T00:00:00Z", to: "2026-01-01T00:00:00Z" }))).toMatchObject({ status: 422, detail: "window not precomputed" });
    // a kind the export holds no window of (year: cut)
    expect(await status(s.ruleMap({ ...q, from: "2025-01-01T00:00:00Z", to: "2026-01-01T00:00:00Z" }))).toMatchObject({ status: 422 });
    expect(await status(s.ruleMap({ ...q, metric: "activation_frequency", tau: 0.3, from: "2025-03-06T00:00:00Z", to: "2025-03-07T00:00:00Z" }))).toMatchObject({ status: 422, detail: expect.stringContaining("not precomputed") });
    expect(await status(s.ruleMap({ ...q, ruleId: "R09", time: "2025-03-05T22:00:00Z", metric: "firing_strength" }))).toMatchObject({ status: 404 });
    expect(await status(s.ruleMap({ ...q, metric: "firing_strength", time: undefined }))).toMatchObject({ status: 422 });
    expect(await status(s.ruleMap({ ...q, metric: "activation_frequency", from: "2025-03-06T00:00:00Z", to: "2025-03-07T00:00:00Z" }))).toMatchObject({ status: 422, detail: expect.stringContaining("tau") });
  });
});

describe("territories", () => {
  const window = { from: "2025-03-05T22:00:00Z", to: "2025-03-06T01:00:00Z" };

  it("lists every rule's three measures and the dominant rule of the chosen one", async () => {
    const r = await store().ruleTerritories({ modelId: "m-win", ...window, measure: "mean_activation", tau: 0.5 });
    expect(r).toMatchObject({ inference_family: "winning_rule_classifier", measure: "mean_activation", tau: 0.5, n_rules: 2, time_from_utc: window.from, time_to_utc: window.to });
    expect(r.tie_break).toContain("1e-12");
    expect(r.notes).toHaveLength(2);
    const p = props(r.features);
    expect(p.A).toMatchObject({ n_records: 2, n_valid: 2, dominant_rule_id: "R01", dominant_value: 0.125, missing_reason: null });
    expect(p.A.rules).toEqual([
      { rule_id: "R01", mean_activation: 0.125, activation_frequency: 0, winner_share: 0.5 },
      { rule_id: "R02", mean_activation: 0.0625, activation_frequency: 0, winner_share: 0 },
    ]);
    expect(p.B).toMatchObject({ n_records: 3, n_valid: 2, dominant_rule_id: "R02", dominant_value: 0.5625 });
    expect(p.B.rules[1]).toEqual({ rule_id: "R02", mean_activation: 0.5625, activation_frequency: 0.5, winner_share: 0.5 });
    expect(p.U).toMatchObject({ n_records: 0, n_valid: 0, rules: [], dominant_rule_id: null, missing_reason: "not_modelled" });
  });

  it("breaks a tie towards the lowest rule position", async () => {
    const r = await store().ruleTerritories({ modelId: "m-win", ...window, measure: "winner_share", tau: 0.5 });
    expect(props(r.features).B).toMatchObject({ dominant_rule_id: "R01", dominant_value: 0.5 });
  });

  it("has no dominant rule when the measure is 0 for every rule", async () => {
    const s = store((files) => {
      (files.get("models/m-win/agg/coverage/all.json.gz") as { sum: number[] }).sum = [0, 0, 0, 0];
    });
    const p = props((await s.ruleTerritories({ modelId: "m-win", ...window, measure: "mean_activation", tau: 0.5 })).features);
    expect(p.A).toMatchObject({ dominant_rule_id: null, dominant_value: null, quality: { status: "warning", warnings: ["mean_activation is 0 for every rule: no dominant rule"] } });
  });

  it("uses the default tau, and refuses winner_share where no rule decides", async () => {
    const s = store();
    expect((await s.ruleTerritories({ modelId: "m-win", ...window, measure: "mean_activation" })).tau).toBe(0.5);
    expect(await status(s.ruleTerritories({ modelId: "m-mix", from: "2025-03-05T10:00:00Z", to: "2025-03-05T11:00:00Z", measure: "winner_share", tau: 0.5 }))).toMatchObject({ status: 422 });
    expect(await status(s.ruleTerritories({ modelId: "m-win", ...window, measure: "mean_activation", tau: 0.3 }))).toMatchObject({ status: 422 });
  });

  it("separates no records from no valid records", async () => {
    const s = store((files) => {
      (files.get("models/m-win/agg/coverage/all.json.gz") as { n_valid: number[]; n_records: number[] }).n_valid = [2, 0];
    });
    const p = props((await s.ruleTerritories({ modelId: "m-win", ...window, measure: "mean_activation", tau: 0.5 })).features as TerritoryFeature[]);
    expect(p.B).toMatchObject({ n_records: 3, n_valid: 0, rules: [], missing_reason: "missing_input", quality: { status: "warning", warnings: ["missing input"] } });
    const empty = props((await s.ruleTerritories({ modelId: "m-win", from: "2025-03-07T00:00:00Z", to: "2025-03-08T00:00:00Z", measure: "mean_activation", tau: 0.5 })).features);
    expect(empty.A).toMatchObject({ n_records: 0, missing_reason: "no_observation" });
  });
});

describe("the API's own texts", () => {
  const edited = () =>
    store((files) => {
      const m = files.get("manifest.json") as { texts: Record<string, unknown> };
      m.texts = { ...m.texts, tie_break: "TB", denominators: "DEN", territory_notes: ["N1"], observations_note: "NOTE" };
    });

  it("come from manifest.texts, not from the web", async () => {
    const t = await edited().ruleTerritories({ modelId: "m-win", from: "2025-03-05T22:00:00Z", to: "2025-03-06T01:00:00Z", measure: "mean_activation", tau: 0.5 });
    expect([t.tie_break, t.denominators, t.notes]).toEqual(["TB", "DEN", ["N1"]]);
    expect((await edited().observations({ taskId: "t-win", time: "2025-03-05T22:00:00Z" })).note).toBe("NOTE");
  });

  it("break the tie with the tolerance the export ships", async () => {
    const s = store((files) => {
      (files.get("manifest.json") as { texts: { tie_tolerance: number } }).texts.tie_tolerance = 1;
    });
    // R01 0.125 and R02 0.5625 differ by less than 1: they tie and the lowest position wins
    const r = await s.ruleTerritories({ modelId: "m-win", from: "2025-03-05T22:00:00Z", to: "2025-03-06T01:00:00Z", measure: "mean_activation", tau: 0.5 });
    expect(props(r.features).B.dominant_rule_id).toBe("R01");
  });

  it("are required: an export without them is not served", async () => {
    const s = store((files) => {
      delete (files.get("manifest.json") as { texts?: unknown }).texts;
    });
    expect(await status(s.predictions({ taskId: "t-win", time: "2025-03-05T22:00:00Z" }))).toMatchObject({ status: null });
  });
});

describe("numeric matches", () => {
  it("use relative 1e-9 with an absolute floor, for tau and for the stories' tau", async () => {
    const s = store();
    const day = { modelId: "m-win", from: "2025-03-06T00:00:00Z", to: "2025-03-07T00:00:00Z" };
    expect((await s.ruleTerritories({ ...day, measure: "activation_frequency", tau: 0.5 + 1e-10 })).tau).toBeCloseTo(0.5);
    expect(await status(s.ruleTerritories({ ...day, measure: "activation_frequency", tau: 0.5 + 1e-6 }))).toMatchObject({ status: 422 });
    expect(await s.ruleStories({ ...day, tau: 0.5 + 1e-10 })).toMatchObject({ n_candidates: 0 });
  });
});

describe("stories", () => {
  it("serves the exported body for a window, at its tau and limit only", async () => {
    const s = store();
    const day = { modelId: "m-win", from: "2025-03-06T00:00:00Z", to: "2025-03-07T00:00:00Z" };
    expect(await s.ruleStories({ ...day, tau: 0.5, limit: 10 })).toEqual(testExport().get("models/m-win/stories/day/2025-03-06.json.gz"));
    expect(await s.ruleStories(day)).toMatchObject({ n_candidates: 0 });
    expect(await status(s.ruleStories({ ...day, tau: 0.6 }))).toMatchObject({ status: 422 });
    expect(await status(s.ruleStories({ ...day, limit: 5 }))).toMatchObject({ status: 422 });
    expect(await status(s.ruleStories({ ...day, to: "2025-03-06T06:00:00Z" }))).toMatchObject({ status: 422, detail: "window not precomputed" });
    expect(await status(s.ruleStories({ modelId: "m-win", from: "2025-03-05T00:00:00Z", to: "2025-03-06T00:00:00Z" }))).toMatchObject({ status: 404 });
    expect(await status(s.ruleStories({ modelId: "m-mix", from: "2025-03-05T00:00:00Z", to: "2025-03-06T00:00:00Z" }))).toMatchObject({ status: 422 });
  });
});

describe("series", () => {
  const entity = { taskId: "t-win", entityId: "B", from: "2025-03-05T00:00:00Z", to: "2025-03-07T00:00:00Z" };

  it("lists an entity's rows by issue time across the days", async () => {
    const r = await store().series(entity);
    expect(r).toMatchObject({ task_id: "t-win", entity_id: "B", model_id: "m-win", target: "no2", unit: "ug/m3", horizon_hours: 6, next_cursor: null });
    expect(r.points).toEqual([
      { issued_at_utc: "2025-03-05T22:00:00Z", valid_at_utc: "2025-03-06T04:00:00Z", observed: null, prediction: null, observed_label: null, predicted_label: null, missing_reason: "missing_input", quality: { status: "valid", warnings: [] } },
      { issued_at_utc: "2025-03-05T23:00:00Z", valid_at_utc: "2025-03-06T05:00:00Z", observed: 50, prediction: null, observed_label: "Bad", predicted_label: "Bad", missing_reason: null, quality: { status: "valid", warnings: [] } },
      { issued_at_utc: "2025-03-06T00:00:00Z", valid_at_utc: "2025-03-06T06:00:00Z", observed: 7, prediction: null, observed_label: null, predicted_label: null, missing_reason: "prediction_unavailable", quality: { status: "valid", warnings: [] } },
    ]);
  });

  it("is [from, to) by issue time, and empty outside the rows", async () => {
    const s = store();
    expect((await s.series({ ...entity, from: "2025-03-05T23:00:00Z", to: "2025-03-06T00:00:00Z" })).points).toHaveLength(1);
    expect((await s.series({ ...entity, from: "2025-04-01T00:00:00Z", to: "2025-04-02T00:00:00Z" })).points).toEqual([]);
    expect((await s.series({ taskId: "t-win", entityId: "A" })).points.map((p) => p.issued_at_utc)).toEqual(["2025-03-05T22:00:00Z", "2025-03-06T00:00:00Z"]);
  });

  it("reads an irregular task's samples and its regressor value", async () => {
    const r = await store().series({ taskId: "t-tsk", entityId: "W1", from: "2024-05-01T00:00:00Z", to: "2024-06-01T00:00:00Z" });
    expect(r.points.map((p) => [p.issued_at_utc, p.prediction, p.observed, p.missing_reason])).toEqual([
      ["2024-05-01T10:00:00Z", 4, 4.5, null],
      ["2024-05-03T12:00:00Z", null, 5, "missing_input"],
    ]);
  });

  it("pages at 2,000 points with the issue time of the next one as the cursor", async () => {
    const n = 2005;
    const s = store((files) => {
      const meta = files.get("models/m-tsk/meta.json.gz") as Meta;
      meta.coverage = { from: "2024-01-01T00:00:00Z", to: "2024-04-12T04:00:00Z" };
      files.set("models/m-tsk/all/pred.json.gz", {
        v: 1, kind: "pred", model_id: "m-tsk", key: "all", n,
        t: Array.from({ length: n }, (_, i) => new Date(Date.UTC(2024, 0, 1) + i * 3_600_000).toISOString().replace(".000Z", "Z")),
        ti: Array.from({ length: n }, (_, i) => i), ei: Array.from({ length: n }, () => 0), pred: Array.from({ length: n }, () => 1),
      });
    });
    const first = await s.series({ taskId: "t-tsk", entityId: "W1", from: "2024-01-01T00:00:00Z", to: "2024-12-31T00:00:00Z" });
    expect(first.points).toHaveLength(2000);
    expect(first.next_cursor).toBe(new Date(Date.UTC(2024, 0, 1) + 2000 * 3_600_000).toISOString().replace(".000Z", "Z"));
    const next = await s.series({ taskId: "t-tsk", entityId: "W1", from: "2024-01-01T00:00:00Z", to: "2024-12-31T00:00:00Z", cursor: first.next_cursor! });
    expect(next.points).toHaveLength(5);
    expect(next.next_cursor).toBeNull();
  });

  it("is a 404 for an unknown or unmodelled entity and a 422 for an empty window", async () => {
    const s = store();
    expect(await status(s.series({ ...entity, entityId: "Z" }))).toMatchObject({ status: 404 });
    expect(await status(s.series({ ...entity, entityId: "U" }))).toMatchObject({ status: 404, detail: expect.stringContaining("not_modelled") });
    expect(await status(s.series({ ...entity, from: "2025-03-07T00:00:00Z", to: "2025-03-06T00:00:00Z" }))).toMatchObject({ status: 422 });
  });
});

describe("export support", () => {
  it("tells the UI which windows, taus and sweeps the model has", async () => {
    const s = store();
    expect(await s.support("m-win")).toMatchObject({ taus: [0.25, 0.5, 0.75, 1], windowKinds: ["day", "week", "month", "coverage"], storiesTau: 0.5, whatIf: true });
    expect(await s.support("m-tsk")).toMatchObject({ windowKinds: ["month"], whatIf: false });
    expect(await s.whatIf("m-win", "A")).toEqual({ at: ["2025-03-05T22:00:00Z"], grid: { x: [0, 10, 20], y: [0, 20] } });
    expect(await s.whatIf("m-win", "B")).toBeNull();
    expect(await s.whatIf("m-tsk", "W1")).toBeNull();
  });
});

describe("an export of a period", () => {
  // the whole fixture is the period: windows are the standard ones clipped to [22:00 on 5 March, 01:00 on 6 March)
  const clipped = () =>
    store((files) => {
      (files.get("models/m-win/meta.json.gz") as Meta).period = { from: "2025-03-05T22:00:00Z", to: "2025-03-06T00:00:00Z" };
    });

  it("answers the clipped window and names its file after the standard one", async () => {
    const r = await clipped().ruleMap({ modelId: "m-win", ruleId: "R01", metric: "mean_activation", from: "2025-03-05T22:00:00Z", to: "2025-03-06T01:00:00Z" });
    // the week of 3 March clipped is the whole range: its statistics are in week/2025-03-03
    expect(r).toMatchObject({ time_from_utc: "2025-03-05T22:00:00Z", time_to_utc: "2025-03-06T01:00:00Z" });
    expect(props(r.features).A.value).toBe(0.125);
    const day = await clipped().ruleMap({ modelId: "m-win", ruleId: "R01", metric: "mean_activation", from: "2025-03-05T22:00:00Z", to: "2025-03-06T00:00:00Z" });
    expect(props(day.features).A).toMatchObject({ value: 0.25, n_valid: 1 });
  });

  it("refuses a standard window that crosses the edge of the period", async () => {
    expect(await status(clipped().ruleMap({ modelId: "m-win", ruleId: "R01", metric: "mean_activation", from: "2025-03-03T00:00:00Z", to: "2025-03-10T00:00:00Z" }))).toMatchObject({ status: 422, detail: "window not precomputed" });
  });

  it("offers the exported range to the UI, not the card's", async () => {
    expect((await clipped().support("m-win")).coverage).toEqual({
      issued_from_utc: "2025-03-05T22:00:00Z", issued_to_utc: "2025-03-06T00:00:00Z", regular: true, step_hours: 1, clip: true,
    });
    expect((await store().support("m-win")).coverage.clip).toBe(false);
  });
});

describe("windowRef", () => {
  const meta = testExport().get("models/m-win/meta.json.gz") as Meta;
  it("recognises the windows the web offers", () => {
    expect(windowRef(meta, "2025-03-06T00:00:00Z", "2025-03-07T00:00:00Z")).toEqual({ kind: "day", from: "2025-03-06" });
    expect(windowRef(meta, "2025-03-03T00:00:00Z", "2025-03-10T00:00:00Z")).toEqual({ kind: "week", from: "2025-03-03" });
    expect(windowRef(meta, "2025-03-01T00:00:00Z", "2025-04-01T00:00:00Z")).toEqual({ kind: "month", from: "2025-03-01" });
    expect(windowRef(meta, "2025-01-01T00:00:00Z", "2026-01-01T00:00:00Z")).toEqual({ kind: "year", from: "2025-01-01" });
    expect(windowRef(meta, "2025-03-05T22:00:00Z", "2025-03-06T01:00:00Z")).toEqual({ kind: "coverage", from: "all" });
  });
  it("refuses anything else", () => {
    expect(windowRef(meta, "2025-03-04T00:00:00Z", "2025-03-11T00:00:00Z")).toBeNull();
    expect(windowRef(meta, "2025-03-05T22:00:00Z", "2025-03-06T02:00:00Z")).toBeNull();
    expect(windowRef(meta, "2025-03-06T00:00:00Z", "2025-03-06T12:00:00Z")).toBeNull();
  });
});
