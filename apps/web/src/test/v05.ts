import type { DomainsResponse, ModelExplanation } from "../api/types";
import type { FakeData } from "./fakeApi";
import * as fx from "./fixtures";
import * as cls from "./fixturesClass";
import { classifiedSummary, classifierImportance, numericSummary, regressionImportance } from "./fixturesV05";

/** The synthetic winning-rule classifier as one territory ("Zona de prueba") with its v0.5 summary and importance. */
export function classifierV05(over: { summary?: boolean; importance?: boolean; explanation?: boolean } = {}): Partial<FakeData> {
  const base = cls.classifierData();
  const taskId = cls.card.manifest.task_id;
  const domains: DomainsResponse = {
    ...cls.domains,
    domains: cls.domains.domains.map((d) => ({ ...d, tasks: d.tasks.map((t) => ({ ...t, territory: "zona", territory_title: "Zona de prueba" })) })),
  };
  return {
    ...base,
    domains,
    summary: over.summary === false ? undefined : classifiedSummary(cls.rules, cls.entities, taskId),
    importance: over.importance === false ? undefined : classifierImportance(cls.rules, cls.entities, taskId),
    explanation: over.explanation === false ? undefined : classifierExplanation(cls.rules.model_id, cls.rules.data_version),
  };
}

/** A contract v0.6.2 explanation of the synthetic classifier, in both languages (made up for the tests). */
export function classifierExplanation(modelId: string, dataVersion: string, reviewed = false): ModelExplanation {
  return {
    schema_version: "0.6.2",
    data_version: dataVersion,
    synthetic: true,
    model_id: modelId,
    template_version: "1",
    generated_by: { tool: "Claude Code", tool_version: "2.1.319", model: "claude-opus-5-5" },
    generated_at_utc: "2026-11-09T12:00:00Z",
    input_sha256: "0".repeat(64),
    reviewed,
    es: {
      headline: "Casi todas las predicciones las decide R01, que repite el nivel de hace 3 h",
      summary: ["Las cuatro reglas miran una sola entrada: el nivel de hace 3 h.", "R01 decide el 40 % de las predicciones y acierta el 92 %."],
      points: ["R04 no tiene observaciones con las que comprobarla.", "El modelo no prevé nunca la categoría más alta.", "Es un ejemplo inventado."],
    },
    en: {
      headline: "Almost every prediction is decided by R01, which repeats the level of 3 h earlier",
      summary: ["The four rules look at one input: the level 3 h earlier.", "R01 decides 40% of the predictions and is right 92% of the time."],
      points: ["R04 has no observations to check it against.", "The model never predicts the highest category.", "It is a made-up example."],
    },
  };
}

/** The synthetic regressor (Madrid-like) with a numeric summary and the weighted-average importance. */
export function regressionV05(): Partial<FakeData> {
  const taskId = fx.card.manifest.task_id;
  return {
    summary: numericSummary(fx.rules, fx.entities, taskId),
    importance: regressionImportance(fx.rules, fx.entities, taskId),
  };
}
