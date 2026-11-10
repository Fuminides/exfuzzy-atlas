import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { ModelRules, RuleImportanceResponse } from "../api/types";
import type { FakeData } from "./fakeApi";
import * as cls from "./fixturesClass";
import { classifierImportance } from "./fixturesV05";
import { classifierV05 } from "./v05";

/**
 * The rule bases of the five SERVED models (artifacts/published, 2026-11-09), `rules.json` and `importance.json` as the
 * artifacts-mode API returns them, with the per-zone `entities` of the importance dropped (the rule matrix does not use
 * them). Not synthetic: the payloads say `synthetic: false`.
 *   madrid_h6  exfuzzy-madrid_no2_h6-ica4-yday-seed1       7 rules of 1 condition, unweighted (rule_weighting none)
 *   madrid_h1  exfuzzy-madrid_no2_h1-ica2-justified-seed2  9 rules of 1-2 conditions over 9 inputs, weighted (dominance_score)
 *   de_h6      exfuzzy-de_no2_h6-ica4-yday-seed2          10 rules of 1-2 conditions, unweighted, EAQI (English class labels)
 *   nyc_h1     exfuzzy-nyc_pickups_h1-level-rel7-seed0     10 rules of 1-2 conditions, weighted
 *   water      exfuzzy-uk_water_do-fx-w-unique-seed0       39 rules of 1-2 conditions, additive regression (TSK)
 */
export type PatternsModel = "madrid_h6" | "madrid_h1" | "de_h6" | "nyc_h1" | "water";

const dir = resolve(process.cwd(), "src/test/fixtures-real/patterns");

export function served(name: PatternsModel): { rules: ModelRules; importance: RuleImportanceResponse } {
  return JSON.parse(readFileSync(resolve(dir, `${name}.json`), "utf8")) as { rules: ModelRules; importance: RuleImportanceResponse };
}

/**
 * A served classifier's rule base under the synthetic classifier's task, for App-level tests of Patrones: the rules and the
 * importance are the real ones, renamed to the fixture's model id; the zones of the importance are the fixture's (synthetic).
 */
export function servedAsClassifier(name: Exclude<PatternsModel, "water">): Partial<FakeData> {
  const base = classifierV05();
  const real = served(name);
  const modelId = cls.rules.model_id;
  const taskId = cls.card.manifest.task_id;
  const zones = classifierImportance(cls.rules, cls.entities, taskId).entities;
  return {
    ...base,
    rules: { ...real.rules, model_id: modelId, task_id: taskId },
    importance: { ...real.importance, model_id: modelId, task_id: taskId, entities: zones },
  };
}
