import type { FeatureValue, PredictionChange, RuleDelta, RuleTrace, ScenarioInput, ScenarioRequest, ScenarioResponse } from "../types";
import { close } from "./numbers";
import { envelope, warning } from "./common";
import { tr } from "../../i18n";
import { notFound, unprocessable, type Data, type Model } from "./data";
import { at as col } from "./rows";
import { findRow } from "./select";
import { nearestInstant } from "../../lib/whatifSweeps";
import { ms, pyIso } from "./time";
import { buildTrace, rowData, type RowData } from "./trace";
import type { WhatIfSweeps, WhatIfVariant } from "./types";

/** `atlas.services.scenarios.validate_overrides`: the same checks, in the same order. */
function validateOverrides(h: Model, features: readonly string[], overrides: Readonly<Record<string, number>>): void {
  const unknown = Object.keys(overrides).filter((f) => !features.includes(f)).sort();
  if (unknown.length > 0) throw unprocessable(`unknown features ${JSON.stringify(unknown)}; the model's inputs are ${JSON.stringify(features)}`);
  for (const [feature, value] of Object.entries(overrides)) {
    if (!Number.isFinite(value)) throw unprocessable(`${feature}: the value must be finite`);
    const domain = h.domainOf.get(feature);
    if (domain && !(domain[0] <= value && value <= domain[1])) {
      throw unprocessable(`${feature}=${value} is outside the variable's domain [${domain[0]}, ${domain[1]}]`);
    }
  }
}

/** What the export holds for one entity: the instants with a sweep and, per input, the values tried (null: nothing). */
export async function whatIfSweeps(d: Data, h: Model, entityId: string, signal?: AbortSignal): Promise<WhatIfSweeps | null> {
  if (!h.meta.whatif || !h.entityIndex.has(entityId)) return null;
  const file = await d.whatif(h, entityId, signal);
  return file ? { at: file.at, grid: file.grid } : null;
}

/** The two grid values around `value`, for the 422 that names them. */
const nearestTwo = (grid: readonly number[], value: number): number[] =>
  [...grid].sort((a, b) => Math.abs(a - value) - Math.abs(b - value)).slice(0, 2).sort((a, b) => a - b);

/** The row's data with `feature` set to the grid value `s` of the variant (spec sections 9 and 10, scenario). */
function variantRow(h: Model, base: RowData, feature: string, value: number, variant: WhatIfVariant, s: number): RowData {
  const k = h.meta.features.findIndex((f) => f.name === feature);
  const mem = [...base.mem];
  let j = 0;
  h.meta.mem_pairs.forEach(([f], p) => {
    if (f === feature) mem[p] = variant.m[j++]?.[s] ?? null;
  });
  return {
    ...base,
    inputs: base.inputs.map((x, i) => (i === k ? value : x)),
    fire: variant.f.map((row) => row[s] ?? null),
    mem,
    pred: col(variant.pred, s),
    plabel: col(variant.plabel, s),
    decided: col(variant.decided, s),
    top: col(variant.top, s),
    tshare: col(variant.tshare, s),
  };
}

const delta = (a: number | null, b: number | null): number | null => (a === null || b === null ? null : b - a);

/** `atlas.services.scenarios.rule_deltas`. */
function ruleDeltas(original: RuleTrace, modified: RuleTrace): RuleDelta[] {
  const before = new Map(original.rules.map((e) => [e.rule_id, e]));
  const after = new Map(modified.rules.map((e) => [e.rule_id, e]));
  const ids = [...before.keys(), ...[...after.keys()].filter((id) => !before.has(id))];
  return ids.map((id) => {
    const a = before.get(id);
    const b = after.get(id);
    const fa = a ? a.firing_strength : null;
    const fb = b ? b.firing_strength : null;
    const aa = a?.association_degree ?? null;
    const ab = b?.association_degree ?? null;
    return {
      rule_id: id, firing_original: fa, firing_scenario: fb, firing_delta: delta(fa, fb),
      association_original: aa, association_scenario: ab, association_delta: delta(aa, ab),
    } as RuleDelta;
  });
}

/** `atlas.services.scenarios.prediction_change`. */
function predictionChange(original: RuleTrace, modified: RuleTrace): PredictionChange {
  const a = original.prediction;
  const b = modified.prediction;
  const classified = (a.label ?? null) !== null || (b.label ?? null) !== null;
  return {
    original_value: a.value, scenario_value: b.value, value_delta: delta(a.value, b.value),
    original_label: a.label ?? null, scenario_label: b.label ?? null,
    label_changed: classified ? (a.label ?? null) !== (b.label ?? null) : null,
    original_winning_rule_id: a.winning_rule_id ?? null, scenario_winning_rule_id: b.winning_rule_id ?? null,
    original_top_rule_id: a.top_rule_id ?? null, scenario_top_rule_id: b.top_rule_id ?? null,
  } as PredictionChange;
}

/**
 * `POST /scenarios`, answered from the precomputed sweep: the model's response to ONE input changed at a time, at the
 * entity's featured instants, to a value of the grid. Anything else is a 422 that says what is available.
 */
export async function scenario(d: Data, h: Model, req: ScenarioRequest, signal?: AbortSignal): Promise<ScenarioResponse> {
  if (!h.entityById.has(req.entity_id)) throw notFound(`unknown entity ${req.entity_id} for ${req.model_id}`);
  if (h.unmodelled.has(req.entity_id)) throw unprocessable(`${req.entity_id} has no model (not_modelled): there is no row to modify`);
  const t = ms(req.at);
  const p = await findRow(d, h, req.entity_id, t, signal);
  if (!p) throw notFound(`no trace for ${req.entity_id} at ${pyIso(t)}`);
  const base = await rowData(d, h, p, signal);
  const original = buildTrace(h, req.entity_id, t, base);
  const originals = new Map(original.feature_values.map((fv) => [fv.feature, fv]));
  const overrides = req.overrides ?? {};
  validateOverrides(h, [...originals.keys()], overrides);
  const changed = Object.entries(overrides);
  if (changed.length > 1) {
    throw unprocessable("one input at a time in the static demo", () => tr("en esta demo solo se cambia una entrada cada vez", "this demo changes one input at a time"));
  }

  let modified: RuleTrace;
  if (changed.length === 0) {
    modified = structuredClone(original);
  } else {
    const [feature, value] = changed[0]!;
    const file = await d.whatif(h, req.entity_id, signal);
    const atKey = file?.at.find((x) => ms(x) === t);
    if (!file || atKey === undefined) {
      const near = file ? nearestInstant(file.at, req.at) : null;
      throw unprocessable(
        near ? `${req.at} is not a featured instant of ${req.entity_id}; the nearest is ${near}` : `no what-if is precomputed for ${req.entity_id}`,
        near ? () => tr(`este instante no tiene escenarios; el más cercano es ${near}`, `this instant has no scenarios; the nearest is ${near}`) : undefined,
      );
    }
    const grid = file.grid[feature] ?? [];
    const s = grid.findIndex((g) => close(g, value));
    const variant = file.variants[atKey]?.[feature];
    if (s < 0 || !variant) {
      throw unprocessable(`${feature}=${value} is not precomputed; the nearest values are ${nearestTwo(grid, value).join(" and ")}`, () =>
        tr(`${feature} = ${value} no está precalculado`, `${feature} = ${value} is not precomputed`),
      );
    }
    const rerun = buildTrace(h, req.entity_id, t, variantRow(h, base, feature, value, variant, s));
    const feature_values: FeatureValue[] = rerun.feature_values.map((fv) =>
      fv.feature === feature ? { ...fv, source_id: h.texts.override_source_id, observed_at_utc: null } : originals.get(fv.feature)!,
    );
    const warnings = [...(rerun.quality?.warnings ?? []), h.texts.what_if_warning.replace("{features}", feature).replace("{label}", h.texts.what_if_label)];
    modified = { ...rerun, feature_values, observation_ids: [], observed: null, observed_label: null, quality: warning(...warnings) };
  }

  const inputs: ScenarioInput[] = [...originals.values()].map((fv) => ({
    feature: fv.feature,
    unit: fv.unit ?? null,
    origin: fv.feature in overrides ? "overridden" : "observed",
    original_value: fv.value,
    scenario_value: overrides[fv.feature] ?? fv.value,
    domain: h.domainOf.get(fv.feature) ?? null,
    missing_reason: fv.missing_reason ?? null,
  })) as ScenarioInput[];
  return {
    ...envelope(h),
    model_id: req.model_id, entity_id: req.entity_id, issued_at_utc: original.issued_at_utc,
    synthetic_what_if: true, label: h.texts.what_if_label, inputs, original, modified,
    rule_deltas: ruleDeltas(original, modified), prediction_change: predictionChange(original, modified),
  } as ScenarioResponse;
}

