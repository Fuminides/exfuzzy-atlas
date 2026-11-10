import { describe, expect, it } from "vitest";
import { memorySource } from "./source";
import { StaticStore } from "./store";
import { testExport } from "./testExport";

const store = () => new StaticStore(memorySource(testExport()));
const status = async (p: Promise<unknown>) => p.then(() => 200, (e: { status: number; detail?: string }) => ({ status: e.status, detail: e.detail }));

describe("rule trace of a winning-rule classifier", () => {
  it("places the inputs, memberships, firing and association of each rule", async () => {
    const t = await store().ruleTrace("A", "m-win", "2025-03-05T22:00:00Z");
    expect(t).toMatchObject({
      schema_version: "0.7.0", data_version: "dv1", synthetic: false, model_id: "m-win", task_id: "t-win", entity_id: "A",
      issued_at_utc: "2025-03-05T22:00:00Z", valid_at_utc: "2025-03-06T04:00:00Z", observation_ids: [], observed: 12, observed_label: "Good",
      quality: { status: "valid", warnings: [] },
    });
    expect(t.inference.family).toBe("winning_rule_classifier");
    expect(t.feature_values).toEqual([
      { feature: "x", value: 10, unit: "µg/m³", observed_at_utc: "2025-03-05T22:00:00Z", source_id: null, missing_reason: null },
      { feature: "y", value: 20, unit: "m/s", observed_at_utc: "2025-03-05T21:00:00Z", source_id: "src-y", missing_reason: null },
    ]);
    expect(t.rules[0]).toMatchObject({
      rule_id: "R01", firing_strength: 0.25, effective_firing: 0.25, weight: 1, association_degree: 0.25,
      antecedents: [
        { feature: "x", term: "Low", membership: 0.5, modifier: null, effective_membership: 0.5 },
        { feature: "y", term: "Low", membership: 0.5, modifier: null, effective_membership: 0.5 },
      ],
    });
    // a condition with a modifier is membership ** modifier
    expect(t.rules[1]).toMatchObject({
      rule_id: "R02", firing_strength: 0.125, weight: 0.5, association_degree: 0.0625,
      antecedents: [
        { feature: "x", term: "High", membership: 0.5, modifier: null, effective_membership: 0.5 },
        { feature: "y", term: "Low", membership: 0.5, modifier: 2, effective_membership: 0.25 },
      ],
    });
    expect(t.rules[0]!.class_weights).toBeNull();
    expect(t.prediction).toEqual({
      value: null, label: "Good", winning_rule_id: "R01", unit: "ug/m3", fallback_used: false, missing_reason: null,
      class_scores: null, class_bias: null, top_rule_id: null, top_rule_share: null,
    });
  });

  it("follows the deciding rule of the shard, not a recomputation", async () => {
    const t = await store().ruleTrace("B", "m-win", "2025-03-05T23:00:00Z");
    expect(t.prediction).toMatchObject({ label: "Bad", winning_rule_id: "R02", fallback_used: false });
    expect(t.rules.map((r) => r.association_degree)).toEqual([0, 0.5]);
    expect(t.observed_label).toBe("Bad");
  });

  it("has no rules and says which input is missing", async () => {
    const t = await store().ruleTrace("B", "m-win", "2025-03-05T22:00:00Z");
    expect(t.rules).toEqual([]);
    expect(t.feature_values[1]).toMatchObject({ feature: "y", value: null, observed_at_utc: null, missing_reason: "no_observation" });
    expect(t.prediction).toMatchObject({ value: null, label: null, fallback_used: false, missing_reason: "missing_input" });
    expect(t.quality).toEqual({ status: "warning", warnings: ["missing input: y"] });
    expect(t.observed).toBeNull();
  });

  it("uses the fallback when no rule fires", async () => {
    const t = await store().ruleTrace("A", "m-win", "2025-03-06T00:00:00Z");
    expect(t.prediction).toMatchObject({ label: null, winning_rule_id: null, fallback_used: true, missing_reason: "prediction_unavailable" });
    expect(t.quality?.warnings).toEqual([]);
    expect(t).toMatchObject({ observed: 5, observed_label: "Good" });
  });

  it("withholds the class of a row with no reference level, keeping the engine's firings", async () => {
    const t = await store().ruleTrace("B", "m-win", "2025-03-06T00:00:00Z");
    expect(t.prediction).toMatchObject({ label: null, winning_rule_id: null, fallback_used: false, missing_reason: "prediction_unavailable" });
    expect(t.rules.map((r) => r.firing_strength)).toEqual([0.25, 0.125]);
    expect(t.quality).toEqual({
      status: "warning",
      warnings: ["no reference level for this row: no class is published; the rule firings and associations below are the engine's own outputs"],
    });
  });

  it("is a trace with no inputs and no rules for an entity without a model", async () => {
    const t = await store().ruleTrace("U", "m-win", "2030-01-01T00:00:00Z");
    expect(t).toMatchObject({ entity_id: "U", feature_values: [], rules: [], observed: null, valid_at_utc: "2030-01-01T06:00:00Z" });
    expect(t.prediction).toMatchObject({ value: null, missing_reason: "not_modelled", fallback_used: false });
    expect(t.quality).toEqual({ status: "warning", warnings: ["entity without a model (not_modelled)"] });
  });

  it("is a 404 when there is no row, no entity or no shard", async () => {
    const s = store();
    expect(await status(s.ruleTrace("A", "m-win", "2025-03-05T23:00:00Z"))).toMatchObject({ status: 404, detail: expect.stringContaining("no trace for A at 2025-03-05T23:00:00+00:00") });
    expect(await status(s.ruleTrace("Z", "m-win", "2025-03-05T22:00:00Z"))).toMatchObject({ status: 404 });
    expect(await status(s.ruleTrace("A", "m-win", "2030-01-01T00:00:00Z"))).toMatchObject({ status: 404 });
    expect(await status(s.ruleTrace("A", "nope", "2025-03-05T22:00:00Z"))).toMatchObject({ status: 404 });
  });

  it("is a 404, not invented memberships, when the memberships of the day were not exported", async () => {
    const files = testExport();
    files.delete("models/m-win/2025-03-05/mem.json.gz");
    expect(await status(new StaticStore(memorySource(files)).ruleTrace("A", "m-win", "2025-03-05T22:00:00Z"))).toMatchObject({ status: 404 });
  });
});

describe("feature order", () => {
  it("lists a trace's inputs in the engine's order, and the observations in the model's", async () => {
    const files = testExport();
    (files.get("models/m-win/meta.json.gz") as { antecedent_order?: string[] }).antecedent_order = ["y", "x"];
    const s = new StaticStore(memorySource(files));
    const t = await s.ruleTrace("A", "m-win", "2025-03-05T22:00:00Z");
    expect(t.feature_values.map((f) => [f.feature, f.value])).toEqual([["y", 20], ["x", 10]]);
    expect((await s.ruleTrace("B", "m-win", "2025-03-05T22:00:00Z")).quality?.warnings).toEqual(["missing input: y"]);
    expect((await s.scenario({ model_id: "m-win", entity_id: "A", at: "2025-03-05T22:00:00Z", overrides: { x: 20 } })).inputs.map((i) => i.feature)).toEqual(["y", "x"]);
    const o = await s.observations({ taskId: "t-win", time: "2025-03-05T22:00:00Z" });
    expect(o.features[0]!.properties.inputs.map((i) => i.feature)).toEqual(["x", "y"]);
  });

  it("writes the no-reference warning the export ships for the model's family", async () => {
    const files = testExport();
    (files.get("models/m-win/meta.json.gz") as { texts: { no_reference_warning: string } }).texts.no_reference_warning = "NOREF";
    const t = await new StaticStore(memorySource(files)).ruleTrace("B", "m-win", "2025-03-06T00:00:00Z");
    expect(t.quality?.warnings).toEqual(["NOREF"]);
  });

  it("does not warn about a missing reference level on a row nothing fires on", async () => {
    const files = testExport();
    (files.get("models/m-win/2025-03-06/pred.json.gz") as { noref: number[] }).noref = [1, 1];
    const t = await new StaticStore(memorySource(files)).ruleTrace("A", "m-win", "2025-03-06T00:00:00Z");
    expect(t.quality?.warnings).toEqual([]);
    expect(t.prediction).toMatchObject({ label: null, fallback_used: true });
  });
});

describe("rule trace of a mixture of rules", () => {
  it("adds what each rule gives each class, and the scores, bias and top rule", async () => {
    const t = await store().ruleTrace("M", "m-mix", "2025-03-05T10:00:00Z");
    expect(t.rules[0]).toMatchObject({
      rule_id: "R01", firing_strength: 0.75, weight: null, association_degree: null,
      class_weights: { Good: 1, Bad: 0 }, class_contributions: { Good: 0.75, Bad: 0 }, class_contributions_centred: { Good: 0.375, Bad: -0.375 },
    });
    expect(t.rules[1]).toMatchObject({ class_contributions: { Good: 0, Bad: 0.25 }, class_contributions_centred: { Good: -0.125, Bad: 0.125 } });
    expect(t.prediction).toEqual({
      value: null, label: "Good", winning_rule_id: null, unit: "ug/m3", fallback_used: false, missing_reason: null,
      class_scores: { Good: 1, Bad: 0.25 }, class_bias: { Good: 0.25, Bad: 0 }, top_rule_id: "R01", top_rule_share: 1,
    });
  });
});

describe("rule trace of a TSK regressor", () => {
  it("carries the value and no class", async () => {
    const t = await store().ruleTrace("W2", "m-tsk", "2024-05-03T12:00:00Z");
    expect(t.prediction).toEqual({
      value: 6, label: null, winning_rule_id: null, unit: "mg/l", fallback_used: false, missing_reason: null,
      class_scores: null, class_bias: null, top_rule_id: null, top_rule_share: null,
    });
    expect(t.rules.map((r) => [r.firing_strength, r.weight])).toEqual([[0, null], [1, null]]);
    expect(t).toMatchObject({ valid_at_utc: "2024-05-03T12:00:00Z", observed: null, observed_label: null });
    expect(t.feature_values[0]).toMatchObject({ feature: "temp", value: 20, unit: "°C" });
  });

  it("falls back when nothing fires, and is a missing-input trace when an input is absent", async () => {
    const files = testExport();
    (files.get("models/m-tsk/all/fire.json.gz") as { f: number[][] }).f = [[0, null, 0], [0, null, 0]] as never;
    const s = new StaticStore(memorySource(files));
    expect((await s.ruleTrace("W2", "m-tsk", "2024-05-03T12:00:00Z")).prediction.fallback_used).toBe(true);
    const missing = await store().ruleTrace("W1", "m-tsk", "2024-05-03T12:00:00Z");
    expect(missing.rules).toEqual([]);
    expect(missing.prediction).toMatchObject({ value: null, missing_reason: "missing_input" });
    expect(missing.observed).toBe(5);
  });
});

describe("rule trace with v0.8 conditions", () => {
  /** R02 of the TSK model reads `temp <operator> <term>`; its membership (mem pair 1) is the number the export carries. */
  const withCondition = (condition: Record<string, unknown>) => {
    const files = testExport();
    const rules = files.get("models/m-tsk/rules.json.gz") as { rules: { antecedents: unknown[] }[] };
    rules.rules[1]!.antecedents = [{ feature: "temp", ...condition }];
    const meta = files.get("models/m-tsk/meta.json.gz") as { mem_pairs: string[][] };
    meta.mem_pairs[1] = ["temp", String(condition.operator), String(condition.term)];
    return new StaticStore(memorySource(files));
  };

  it("places the bounded sum of an at_least condition with its operator and terms", async () => {
    const t = await withCondition({ operator: "at_least", term: "Low", terms: ["Low", "High"] }).ruleTrace("W2", "m-tsk", "2024-05-03T12:00:00Z");
    expect(t.rules[1]!.antecedents).toEqual([
      { feature: "temp", term: "Low", operator: "at_least", terms: ["Low", "High"], membership: 1, modifier: null, effective_membership: 1 },
    ]);
  });

  it("places an at_most condition and a compound that wraps (internal name as term)", async () => {
    const atMost = await withCondition({ operator: "at_most", term: "High", terms: ["Low", "High"] }).ruleTrace("W2", "m-tsk", "2024-05-03T12:00:00Z");
    expect(atMost.rules[1]!.antecedents[0]).toMatchObject({ operator: "at_most", term: "High", terms: ["Low", "High"], membership: 1 });
    const compound = await withCondition({ operator: "any_of", term: "Night", terms: ["Low", "High"], label: "Noche larga" }).ruleTrace("W2", "m-tsk", "2024-05-03T12:00:00Z");
    expect(compound.rules[1]!.antecedents[0]).toEqual({
      feature: "temp", term: "Night", operator: "any_of", terms: ["Low", "High"], membership: 1, modifier: null, effective_membership: 1,
    });
  });

  it("applies the modifier to the membership of a condition and keeps plain conditions as is", async () => {
    const t = await withCondition({ operator: "at_least", term: "Low", terms: ["Low", "High"], modifier: 2 }).ruleTrace("W2", "m-tsk", "2024-05-03T12:00:00Z");
    expect(t.rules[1]!.antecedents[0]).toMatchObject({ membership: 1, modifier: 2, effective_membership: 1 });
    const plain = await store().ruleTrace("W2", "m-tsk", "2024-05-03T12:00:00Z");
    expect(plain.rules[0]!.antecedents[0]).toMatchObject({ operator: "is", term: "Low", terms: ["Low"] });
  });

  it("stops with a 404 when a condition has no exported membership", async () => {
    const files = testExport();
    (files.get("models/m-tsk/meta.json.gz") as { mem_pairs: string[][] }).mem_pairs[1] = ["temp", "at_least", "Low"];
    const s = new StaticStore(memorySource(files));
    expect(await status(s.ruleTrace("W2", "m-tsk", "2024-05-03T12:00:00Z"))).toMatchObject({ status: 404 });
  });

  it("refuses an export of another format", async () => {
    const files = testExport();
    (files.get("models/m-tsk/meta.json.gz") as { format_version: number }).format_version = 1;
    const s = new StaticStore(memorySource(files));
    expect(await status(s.ruleTrace("W2", "m-tsk", "2024-05-03T12:00:00Z"))).toMatchObject({ status: null });
  });
});

describe("scenario", () => {
  const request = { model_id: "m-win", entity_id: "A", at: "2025-03-05T22:00:00Z" };

  it("answers one changed input from the precomputed sweep", async () => {
    const r = await store().scenario({ ...request, overrides: { x: 20 } });
    expect(r).toMatchObject({
      schema_version: "0.7.0", model_id: "m-win", entity_id: "A", issued_at_utc: "2025-03-05T22:00:00Z", synthetic_what_if: true,
      label: "respuesta del modelo ante entradas modificadas — no efecto causal ni predicción",
    });
    expect(r.inputs).toEqual([
      { feature: "x", unit: "µg/m³", origin: "overridden", original_value: 10, scenario_value: 20, domain: [0, 40], missing_reason: null },
      { feature: "y", unit: "m/s", origin: "observed", original_value: 20, scenario_value: 20, domain: [0, 40], missing_reason: null },
    ]);
    expect(r.original.prediction).toMatchObject({ label: "Good", winning_rule_id: "R01" });
    // the overridden input has no source and no observation time; the others keep theirs
    expect(r.modified.feature_values).toEqual([
      { feature: "x", value: 20, unit: "µg/m³", observed_at_utc: null, source_id: "what_if_override", missing_reason: null },
      r.original.feature_values[1],
    ]);
    // the swept feature's memberships and every firing come from the variant, the other memberships from the row
    expect(r.modified.rules.map((e) => e.firing_strength)).toEqual([0, 0.25]);
    expect(r.modified.rules[1]!.antecedents.map((a) => [a.feature, a.term, a.membership, a.effective_membership])).toEqual([
      ["x", "High", 1, 1], ["y", "Low", 0.5, 0.25],
    ]);
    expect(r.modified.rules[0]!.antecedents[0]).toMatchObject({ membership: 0 });
    expect(r.modified.rules.map((e) => e.association_degree)).toEqual([0, 0.125]);
    expect(r.modified.prediction).toMatchObject({ label: "Bad", winning_rule_id: "R02" });
    expect(r.modified).toMatchObject({ observed: null, observed_label: null, observation_ids: [] });
    expect(r.modified.quality).toEqual({
      status: "warning",
      warnings: ["what-if: inputs overridden (x); respuesta del modelo ante entradas modificadas — no efecto causal ni predicción"],
    });
    expect(r.rule_deltas).toEqual([
      { rule_id: "R01", firing_original: 0.25, firing_scenario: 0, firing_delta: -0.25, association_original: 0.25, association_scenario: 0, association_delta: -0.25 },
      { rule_id: "R02", firing_original: 0.125, firing_scenario: 0.25, firing_delta: 0.125, association_original: 0.0625, association_scenario: 0.125, association_delta: 0.0625 },
    ]);
    expect(r.prediction_change).toEqual({
      original_value: null, scenario_value: null, value_delta: null, original_label: "Good", scenario_label: "Bad", label_changed: true,
      original_winning_rule_id: "R01", scenario_winning_rule_id: "R02", original_top_rule_id: null, scenario_top_rule_id: null,
    });
  });

  it("writes the label, warning and source of an override from the export's texts", async () => {
    const files = testExport();
    const texts = (files.get("manifest.json") as { texts: Record<string, string> }).texts;
    Object.assign(texts, { what_if_label: "LABEL", what_if_warning: "changed {features} -> {label}", override_source_id: "SRC" });
    const r = await new StaticStore(memorySource(files)).scenario({ ...request, overrides: { x: 20 } });
    expect(r.label).toBe("LABEL");
    expect(r.modified.quality?.warnings).toEqual(["changed x -> LABEL"]);
    expect(r.modified.feature_values[0]!.source_id).toBe("SRC");
  });

  it("finds a grid value to the shared tolerance", async () => {
    const s = store();
    expect((await s.scenario({ ...request, overrides: { x: 20 + 1e-9 } })).modified.prediction.label).toBe("Bad");
    expect(await status(s.scenario({ ...request, overrides: { x: 20.001 } }))).toMatchObject({ status: 422 });
    expect((await s.scenario({ ...request, overrides: { x: 1e-10 } })).modified.rules[0]!.firing_strength).toBe(0.5); // grid value 0
  });

  it("answers the other input of the sweep", async () => {
    const r = await store().scenario({ ...request, overrides: { y: 0 } });
    expect(r.modified.rules.map((e) => e.firing_strength)).toEqual([0.5, 0.5]);
    expect(r.modified.prediction.label).toBe("Good");
    expect(r.prediction_change.label_changed).toBe(false);
    expect(r.modified.rules[1]!.antecedents[0]).toMatchObject({ feature: "x", membership: 0.5 });
    expect(r.modified.rules[1]!.antecedents[1]).toMatchObject({ feature: "y", membership: 1, effective_membership: 1 });
  });

  it("is the original when nothing changes", async () => {
    const r = await store().scenario(request);
    expect(r.modified).toEqual(r.original);
    expect(r.inputs.every((i) => i.origin === "observed")).toBe(true);
    expect(r.rule_deltas.every((d) => d.firing_delta === 0)).toBe(true);
  });

  it("is a 422 for what the export does not hold, saying what it does", async () => {
    const s = store();
    expect(await status(s.scenario({ ...request, overrides: { x: 20, y: 0 } }))).toMatchObject({ status: 422, detail: "one input at a time in the static demo" });
    expect(await status(s.scenario({ ...request, overrides: { x: 15 } }))).toMatchObject({ status: 422, detail: expect.stringContaining("nearest values are 10 and 20") });
    expect(await status(s.scenario({ ...request, overrides: { x: 100 } }))).toMatchObject({ status: 422, detail: expect.stringContaining("outside the variable's domain") });
    expect(await status(s.scenario({ ...request, overrides: { z: 1 } }))).toMatchObject({ status: 422, detail: expect.stringContaining("unknown features") });
    expect(await status(s.scenario({ ...request, overrides: { x: Number.NaN } }))).toMatchObject({ status: 422 });
    // a row with no sweep names the nearest instant that has one
    expect(await status(s.scenario({ ...request, at: "2025-03-06T00:00:00Z", overrides: { x: 20 } }))).toMatchObject({
      status: 422, detail: expect.stringContaining("the nearest is 2025-03-05T22:00:00Z"),
    });
    expect(await status(s.scenario({ ...request, entity_id: "B", at: "2025-03-05T23:00:00Z", overrides: { x: 20 } }))).toMatchObject({ status: 422 });
  });

  it("is a 404 without a row and a 422 for an entity without a model", async () => {
    const s = store();
    expect(await status(s.scenario({ ...request, at: "2025-03-05T23:00:00Z", overrides: { x: 20 } }))).toMatchObject({ status: 404 });
    expect(await status(s.scenario({ ...request, entity_id: "Z", overrides: { x: 20 } }))).toMatchObject({ status: 404 });
    expect(await status(s.scenario({ ...request, entity_id: "U", overrides: { x: 20 } }))).toMatchObject({ status: 422 });
  });
});
