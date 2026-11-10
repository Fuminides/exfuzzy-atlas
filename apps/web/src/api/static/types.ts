import type { InferenceSpec } from "../generated/RuleTrace";
import type { MissingReason } from "../types";

/** The wire formats of docs/static_export.md. A column that does not apply to a model is absent and reads as all null. */

export type Col<T> = ReadonlyArray<T | null> | undefined;

export interface MetaFeature {
  name: string;
  obs_unit: string | null;
  trace_unit: string | null;
  source_id: string | null;
  lag_hours: number;
  /** Base path of the input files (spec section 7). */
  input: string;
}

export interface MetaWindows {
  day?: string[];
  week?: string[];
  month?: string[];
  year?: string[];
  coverage?: boolean;
}

export interface MetaWhatIf {
  rule: "weekly_wed_12utc" | "daily_13utc" | "all_samples";
  /** null for `all_samples`: every sample of the entity. */
  instants: string[] | null;
  steps: number;
  per_entity: boolean;
}

/** `models/<model_id>/meta.json.gz` (spec section 4). */
export interface Meta {
  format_version: number;
  model_id: string;
  task_id: string;
  domain: string;
  territory: string;
  task_type: "regression" | "classification";
  family: string;
  data_version: string;
  synthetic: boolean;
  target: string;
  unit: string;
  target_unit: string;
  horizon_hours: number;
  /** Input names in the engine's order: the order of `feature_values` in a trace. */
  antecedent_order?: string[];
  regular: boolean;
  step_hours: number;
  /** The EXPORTED range (first and last exported issue time): what the timeline and controls offer. Not `card.coverage`. */
  coverage: { from: string; to: string };
  full_coverage?: { from: string; to: string };
  /** `null`: the whole coverage is exported. */
  period?: { from: string; to: string } | null;
  keys: string[];
  entities: string[];
  rules: string[];
  classes: string[];
  decides: boolean;
  mixture: boolean;
  features: MetaFeature[];
  mem_pairs: [string, string][];
  inference: InferenceSpec;
  windows: MetaWindows;
  stories: { tau: number; limit: number } | null;
  taus: number[];
  whatif: MetaWhatIf | null;
  missing_reasons: MissingReason[];
  /** Per classifier: the warning of a trace whose label is withheld (no reference level), for this model's family. */
  texts?: { no_reference_warning?: string };
}

export interface PredShard {
  v: number;
  kind: "pred";
  model_id: string;
  key: string;
  t: string[];
  n: number;
  ti: number[];
  ei: number[];
  pred?: Col<number>;
  plabel?: Col<number>;
  obs?: Col<number>;
  olabel?: Col<number>;
  reason?: Col<number>;
  decided?: Col<number>;
  top?: Col<number>;
  tshare?: Col<number>;
  noref?: Col<number>;
}

export interface FireShard {
  v: number;
  kind: "fire";
  n: number;
  /** f[r][i] */
  f: (number | null)[][];
}

export interface MemShard {
  v: number;
  kind: "mem";
  n: number;
  /** m[p][i] */
  m: (number | null)[][];
}

export interface InputsFile {
  v: number;
  kind: "inputs";
  layout: "lattice" | "rows";
  values: (number | null)[];
}

export interface AggFile {
  v: number;
  kind: "agg";
  model_id: string;
  window: { kind: string; from: string; to: string };
  n_records: number[];
  n_valid: number[];
  /** sum[r * |E| + e] */
  sum: number[];
  /** over[k][r * |E| + e] */
  over: number[][];
  win?: number[];
}

export interface WhatIfVariant {
  f: number[][];
  m: number[][];
  pred?: Col<number>;
  plabel?: Col<number>;
  decided?: Col<number>;
  top?: Col<number>;
  tshare?: Col<number>;
}

export interface WhatIfFile {
  v: number;
  kind: "whatif";
  model_id: string;
  entity_id: string;
  at: string[];
  grid: Record<string, number[]>;
  variants: Record<string, Record<string, WhatIfVariant>>;
}

/** What the UI may offer for one entity: the instants with a sweep and, per input, the values tried. */
export interface WhatIfSweeps {
  at: string[];
  grid: Record<string, number[]>;
}

/** The texts the API writes from contract constants (`manifest.texts`, spec section 10). */
export interface ApiTexts {
  tie_break: string;
  denominators: string;
  territory_notes: string[];
  tie_tolerance: number;
  what_if_label: string;
  /** Template with `{features}` (sorted, comma-separated) and `{label}`. */
  what_if_warning: string;
  override_source_id: string;
  observations_note: string;
}

/** `manifest.json` (spec section 13): only the fields the web reads. */
export interface Manifest {
  format: string;
  format_version: number;
  export_id: string;
  created_at_utc: string;
  schema_version: string;
  exfuzzy_version?: string;
  texts?: ApiTexts;
}
