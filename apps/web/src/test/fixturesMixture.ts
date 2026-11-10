import type { ModelExplanation, ModelRules, RuleImportanceResponse, RuleTrace } from "../api/types";
import type { FakeData } from "./fakeApi";
import { classifierV05 } from "./v05";

/**
 * A contract v0.7 rule mixture (`rule_mixture_classifier`) made from the synthetic classifier: the same rules, variables,
 * scheme (low / mid / high), entities and series, with made-up class weights, a class bias, the `rule_mixture`
 * importance and traces rebuilt as the API serves a mixture (contributions = weight × firing, scores = bias + Σ, the
 * label the first class of largest score, the top rule the largest positive centred contribution to it). Test data only.
 */

/** Fitted weights per rule, classes in the scheme's order (low, mid, high). R04 mostly suppresses mid. */
const WEIGHTS: Record<string, [number, number, number]> = {
  R01: [3.0, 1.2, 0.0],
  R02: [0.6, 2.4, 0.9],
  R03: [0.0, 0.3, 1.5],
  R04: [1.0, 0.0, 1.0],
};
const BIAS: [number, number, number] = [0.2, 0.1, -0.3];
const TOP = [0.5, 0.3, 0.15, 0.05];
const DECISIVE = [0.3, 0.2, 0.08, 0.02];

const asRecord = (classes: readonly string[], v: readonly number[]) => Object.fromEntries(classes.map((c, i) => [c, v[i]!]));
const centre = (v: readonly number[]) => {
  const m = v.reduce((a, b) => a + b, 0) / v.length;
  return v.map((x) => x - m);
};

export function mixtureRules(base: ModelRules): ModelRules {
  const classes = base.target_scheme!.classes.map((c) => c.label);
  return {
    ...base,
    schema_version: "0.7.0",
    model_id: base.model_id,
    inference: { family: "rule_mixture_classifier", tnorm: "product", rule_mode: null, tolerance: 0, fallback: "unknown", rule_weighting: null, allow_unknown: true, mixture_weights: "non_negative", mixture_C: 1, exfuzzy_version: "3.4.0" },
    class_bias: asRecord(classes, BIAS),
    rules: base.rules.map((r) => {
      const w = WEIGHTS[r.rule_id] ?? [0, 0, 0];
      const max = Math.max(...w);
      const strongest = w.every((x) => x === w[0]) ? null : classes[w.indexOf(max)]!;
      return { ...r, weight: null, class_weights: asRecord(classes, w), class_weights_centred: asRecord(classes, centre(w)), strongest_class: strongest };
    }),
  };
}

export function mixtureImportance(base: RuleImportanceResponse, rules: ModelRules): RuleImportanceResponse {
  const n = base.n_predicted;
  return {
    ...base,
    schema_version: "0.7.0",
    measure: "rule_mixture",
    n_no_top_rule: 0,
    rules: rules.rules.map((r, i) => ({
      rule_id: r.rule_id,
      n_decided: null,
      decided_share: null,
      n_top: Math.round(TOP[i]! * n),
      top_contributor_share: TOP[i]!,
      n_checked: Math.round(TOP[i]! * n * 0.9),
      accuracy: 0.9 - i * 0.15,
      n_decisive: Math.round(DECISIVE[i]! * n),
      decisive_share: DECISIVE[i]!,
    })),
    variables: base.variables.map((v, i) => ({ feature: v.feature, n_rules: v.n_rules, decided_share: null, top_contributor_share: Math.max(0, 0.8 - i * 0.25), decisive_share: Math.max(0, 0.5 - i * 0.2) })),
    entities: base.entities.map((e) => ({ ...e, rules: e.rules.map((r) => ({ rule_id: r.rule_id, decided_share: null, top_contributor_share: r.decided_share ?? 0, accuracy: r.accuracy })) })),
  };
}

export function mixtureTrace(t: RuleTrace, rules: ModelRules): RuleTrace {
  const classes = rules.target_scheme!.classes.map((c) => c.label);
  const entries = t.rules.map((e) => {
    const def = rules.rules.find((r) => r.rule_id === e.rule_id)!;
    const w = classes.map((c) => def.class_weights![c]!);
    const wc = classes.map((c) => def.class_weights_centred![c]!);
    return {
      ...e,
      weight: null,
      association_degree: null,
      class_weights: asRecord(classes, w),
      class_contributions: asRecord(classes, w.map((x) => x * e.firing_strength)),
      class_contributions_centred: asRecord(classes, wc.map((x) => x * e.firing_strength)),
    };
  });
  const fired = entries.some((e) => e.firing_strength > 0);
  const scores = classes.map((c, k) => BIAS[k]! + entries.reduce((s, e) => s + e.class_contributions[c]!, 0));
  const best = scores.indexOf(Math.max(...scores));
  const label = fired && t.prediction.label != null ? classes[best]! : null;
  let top: string | null = null;
  let topShare: number | null = null;
  if (label) {
    const pos = entries.map((e) => ({ id: e.rule_id, v: e.class_contributions_centred[label]! })).filter((x) => x.v > 0);
    const total = pos.reduce((s, x) => s + x.v, 0);
    const lead = pos.reduce<{ id: string; v: number } | null>((a, x) => (a === null || x.v > a.v ? x : a), null);
    if (lead && total > 0) [top, topShare] = [lead.id, lead.v / total];
  }
  return {
    ...t,
    schema_version: "0.7.0",
    inference: rules.inference as RuleTrace["inference"],
    rules: entries,
    prediction: {
      ...t.prediction,
      label,
      winning_rule_id: null,
      class_scores: label ? asRecord(classes, scores) : null,
      class_bias: asRecord(classes, BIAS),
      top_rule_id: top,
      top_rule_share: topShare,
    },
  };
}

export function mixtureExplanation(modelId: string, dataVersion: string): ModelExplanation {
  return {
    schema_version: "0.7.0",
    data_version: dataVersion,
    synthetic: true,
    model_id: modelId,
    template_version: "2",
    generated_by: { tool: "Claude Code", tool_version: "2.1.321", model: "claude-opus-5-5" },
    generated_at_utc: "2026-11-09T12:00:00Z",
    input_sha256: "0".repeat(64),
    reviewed: false,
    es: {
      headline: "Las reglas suman su apoyo a cada categoría y ninguna decide sola; R01 es la que más suma en la mitad de las predicciones",
      summary: ["Las cuatro reglas miran el nivel de hace 3 h, la hora y una variable exógena.", "R01 apoya sobre todo low y suprime high."],
      points: ["R04 suprime mid.", "Es un ejemplo inventado.", "Un peso solo tiene sentido junto con los de las otras reglas."],
    },
    en: {
      headline: "The rules add up their support for each category and none decides alone; R01 adds the most in half of the predictions",
      summary: ["The four rules look at the level 3 h earlier, the hour and an exogenous variable.", "R01 supports low most and suppresses high."],
      points: ["R04 suppresses mid.", "It is a made-up example.", "A weight only makes sense together with those of the other rules."],
    },
  };
}

/** The synthetic classifier served as a rule mixture: rules, importance, traces, explanation and top rules in /predictions. */
export function mixtureV07(): Partial<FakeData> {
  const base = classifierV05();
  const rules = mixtureRules(base.rules!);
  return {
    ...base,
    rules,
    importance: mixtureImportance(base.importance!, rules),
    traces: base.traces!.map((t) => mixtureTrace(t, rules)),
    explanation: mixtureExplanation(rules.model_id, rules.data_version),
    topRule: { id: "R01", share: 0.6 },
  };
}
