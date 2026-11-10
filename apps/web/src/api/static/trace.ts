import type { TracePrediction } from "../generated/RuleTrace";
import type { AntecedentTrace, FeatureValue, MissingReason, RuleTrace, RuleTraceEntry } from "../types";
import { FALLBACK_EPS } from "./constants";
import { envelope, validQuality, warning } from "./common";
import { notFound, pairKey, type Data, type Model } from "./data";
import { inputsOf } from "./observations";
import { at as col } from "./rows";
import { classAt, findRow, type Picked } from "./select";
import { HOUR_MS, iso, ms, pyIso } from "./time";

/** Everything the builder needs of one row to write its trace: the row of the shards, or a what-if variant of it. */
export interface RowData {
  /** The model's inputs, by feature. */
  inputs: (number | null)[];
  /** Firing of each rule (`fire.f[r][i]`). */
  fire: (number | null)[];
  /** Membership of each used (feature, term) pair (`mem.m[p][i]`). */
  mem: (number | null)[];
  pred: number | null;
  plabel: number | null;
  decided: number | null;
  top: number | null;
  tshare: number | null;
  obs: number | null;
  olabel: number | null;
  /** The raw published row withholds its label ("no reference level"). */
  noref: boolean;
}

const names = (xs: readonly string[]): string => xs.join(", ");

/** `FeatureValue`s of a row, as `ArtifactStore._trace` writes them: in the engine's order (`meta.antecedent_order`). */
export function featureValues(h: Model, t: number, inputs: readonly (number | null)[]): FeatureValue[] {
  const order = h.meta.antecedent_order ?? h.meta.features.map((f) => f.name);
  return order.map((name) => {
    const k = h.meta.features.findIndex((f) => f.name === name);
    const f = h.meta.features[k]!;
    const value = inputs[k] ?? null;
    return {
      feature: f.name,
      value,
      unit: f.trace_unit,
      observed_at_utc: value === null ? null : iso(t - f.lag_hours * HOUR_MS),
      source_id: f.source_id,
      missing_reason: value === null ? "no_observation" : null,
    };
  });
}

/** A trace with nothing to infer (a missing input, no model): no rules and a reason instead of a prediction. */
function withoutRules(h: Model, entityId: string, t: number, values: FeatureValue[], reason: MissingReason, warnings: string, rd?: RowData, inference = h.meta.inference): RuleTrace {
  return {
    ...envelope(h),
    model_id: h.meta.model_id, task_id: h.meta.task_id, entity_id: entityId,
    issued_at_utc: iso(t), valid_at_utc: iso(t + h.meta.horizon_hours * HOUR_MS),
    inference, feature_values: values, rules: [],
    prediction: {
      value: null, label: null, winning_rule_id: null, unit: h.meta.target_unit, fallback_used: false, missing_reason: reason,
      class_scores: null, class_bias: null, top_rule_id: null, top_rule_share: null,
    },
    observation_ids: [],
    observed: rd?.obs ?? null,
    observed_label: rd ? classAt(h, rd.olabel) : null,
    quality: warning(warnings),
  };
}

/**
 * `atlas.services.unmodelled.not_modelled_trace`. Its inference is the one of `rules.json` (no engine ran), which can
 * carry another `exfuzzy_version` than the traces of real rows (`meta.inference`, captured from one).
 */
export const notModelledTrace = (h: Model, entityId: string, t: number): RuleTrace =>
  withoutRules(h, entityId, t, [], "not_modelled", "entity without a model (not_modelled)", undefined, h.rules.inference);

/**
 * The conditions of a rule with the membership of each (`StaticStore._antecedent_traces`): the only reader of how a rule's
 * antecedent is written, besides `pairKey` of the model. Today it is a feature, a term and an optional modifier; a
 * contract that adds more (v0.8 operators) must extend this and the exporter together, so anything else stops here.
 */
function antecedentTraces(h: Model, rule: Model["rules"]["rules"][number], mem: readonly (number | null)[]): AntecedentTrace[] {
  return rule.antecedents.map((a) => {
    const operator = (a as { operator?: string }).operator;
    if (operator !== undefined && operator !== "is") throw notFound(`no trace: the condition operator ${operator} is not supported by this export`);
    const p = h.pairIndex.get(pairKey(a.feature, a.term));
    const membership = p === undefined ? null : (mem[p] ?? null);
    if (membership === null) throw notFound(`no trace: the membership of ${a.feature} / ${a.term} is not exported`);
    const modifier = a.modifier ?? null;
    return { feature: a.feature, term: a.term, membership, modifier, effective_membership: modifier === null ? membership : membership ** modifier };
  });
}

const classMap = (classes: readonly string[], f: (c: string) => number): Record<string, number> => Object.fromEntries(classes.map((c) => [c, f(c)]));

/**
 * The trace of one row (`ArtifactStore._trace`): the inputs, the memberships of each rule's conditions, the firing and, by
 * family, the association degrees and winner, the class scores and top rule, or the TSK value. Every number was computed
 * by ex_fuzzy when the export was made; here they are only placed.
 */
export function buildTrace(h: Model, entityId: string, t: number, rd: RowData): RuleTrace {
  const { meta, rules } = h;
  const values = featureValues(h, t, rd.inputs);
  const missing = values.filter((fv) => fv.value === null).map((fv) => fv.feature);
  if (missing.length > 0 || rd.fire.some((f) => f === null)) {
    return withoutRules(h, entityId, t, values, "missing_input", `missing input: ${names(missing)}`, rd);
  }
  const classes = meta.classes;
  const entries: RuleTraceEntry[] = rules.rules.map((rule, r) => {
    const firing = rd.fire[r]!;
    const antecedents = antecedentTraces(h, rule, rd.mem);
    const entry: RuleTraceEntry = {
      rule_id: rule.rule_id, antecedents: antecedents as RuleTraceEntry["antecedents"], firing_strength: firing, effective_firing: firing,
      weight: null, association_degree: null, class_weights: null, class_contributions: null, class_contributions_centred: null,
    };
    if (h.winningRule) {
      const weight = rule.weight ?? 1;
      entry.weight = weight;
      entry.association_degree = firing * (meta.inference.rule_weighting === "none" ? 1 : weight);
    } else if (h.mixture) {
      const w = rule.class_weights ?? {};
      const centred = rule.class_weights_centred ?? {};
      entry.class_weights = classMap(classes, (c) => w[c]!);
      entry.class_contributions = classMap(classes, (c) => w[c]! * firing);
      entry.class_contributions_centred = classMap(classes, (c) => centred[c]! * firing);
    }
    return entry;
  });

  const prediction: TracePrediction = {
    value: null, label: null, winning_rule_id: null, unit: meta.target_unit, fallback_used: false, missing_reason: null,
    class_scores: null, class_bias: null, top_rule_id: null, top_rule_share: null,
  };
  let quality = validQuality();
  if (!h.classifier) {
    prediction.value = rd.pred;
    prediction.fallback_used = entries.reduce((sum, e) => sum + e.firing_strength, 0) <= FALLBACK_EPS;
    prediction.missing_reason = rd.pred === null ? "prediction_unavailable" : null;
  } else {
    let label = classAt(h, rd.plabel);
    let winning = rd.decided === null ? null : (meta.rules[rd.decided] ?? null);
    let top = rd.top === null ? null : (meta.rules[rd.top] ?? null);
    let share = rd.tshare;
    if (h.mixture) {
      const bias = rules.class_bias ?? {};
      prediction.class_bias = classMap(classes, (c) => bias[c]!);
      prediction.class_scores = classMap(classes, (c) => entries.reduce((sum, e) => sum + e.class_contributions![c]!, bias[c]!));
      prediction.fallback_used = !entries.some((e) => e.firing_strength > 0);
    } else {
      prediction.fallback_used = !entries.some((e) => (e.association_degree ?? 0) > 0);
    }
    // The engine still names a class for a row whose target has no reference level; the published rows do not.
    // (`noref` is also 1 for a row nothing fires on: the engine named no class there and nothing is withheld)
    if (rd.noref && !prediction.fallback_used) {
      label = winning = top = null;
      share = null;
      const text = meta.texts?.no_reference_warning;
      if (text === undefined) throw notFound(`the export has no no_reference_warning for ${meta.model_id}`);
      quality = warning(text);
    }
    prediction.label = label;
    prediction.winning_rule_id = h.mixture ? null : label === null ? null : winning;
    prediction.top_rule_id = h.mixture ? top : null;
    prediction.top_rule_share = h.mixture ? share : null;
    prediction.missing_reason = label === null ? "prediction_unavailable" : null;
  }
  return {
    ...envelope(h),
    model_id: meta.model_id, task_id: meta.task_id, entity_id: entityId,
    issued_at_utc: iso(t), valid_at_utc: iso(t + meta.horizon_hours * HOUR_MS),
    inference: meta.inference, feature_values: values, rules: entries, prediction,
    observation_ids: [], observed: rd.obs, observed_label: classAt(h, rd.olabel), quality,
  };
}

/** The `RowData` of a published row: its fire, mem and input shards. A missing shard is "no trace for this row". */
export async function rowData(d: Data, h: Model, p: Picked, signal?: AbortSignal): Promise<RowData> {
  const [fire, mem, inputs] = await Promise.all([d.fire(h, p.key, signal), d.mem(h, p.key, signal), inputsOf(d, h, [p], signal)]);
  if (!fire || !mem) throw notFound(`no trace for ${h.meta.entities[p.e]} at ${pyIso(p.t)}`);
  const s = p.shard;
  return {
    inputs: inputs[0]!,
    fire: h.meta.rules.map((_, r) => fire.f[r]?.[p.i] ?? null),
    mem: h.meta.mem_pairs.map((_, k) => mem.m[k]?.[p.i] ?? null),
    pred: col(s.pred, p.i), plabel: col(s.plabel, p.i), decided: col(s.decided, p.i), top: col(s.top, p.i), tshare: col(s.tshare, p.i),
    obs: col(s.obs, p.i), olabel: col(s.olabel, p.i), noref: (col(s.noref, p.i) ?? 0) === 1,
  };
}

/** `GET /entities/{id}/rule-trace`. */
export async function ruleTrace(d: Data, h: Model, entityId: string, atInstant: string, signal?: AbortSignal): Promise<RuleTrace> {
  if (!h.entityById.has(entityId)) throw notFound(`unknown entity ${entityId} for ${h.meta.model_id}`);
  const t = ms(atInstant);
  if (h.unmodelled.has(entityId)) return notModelledTrace(h, entityId, t);
  const p = await findRow(d, h, entityId, t, signal);
  if (!p) throw notFound(`no trace for ${entityId} at ${pyIso(t)}`);
  return buildTrace(h, entityId, t, await rowData(d, h, p, signal));
}
