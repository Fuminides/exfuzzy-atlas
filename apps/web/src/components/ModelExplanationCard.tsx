import { api } from "../api/client";
import type { ModelExplanation } from "../api/types";
import { useOptionalAsync } from "../hooks/useOptionalAsync";
import { splitRuleIds } from "../lib/ruleRefs";
import { tr, useLang } from "../i18n";
import { Card } from "./Card";
import { RuleRef, useRuleLookup } from "./RuleRef";
import { StateMessage } from "./StateMessage";

/** The honest note under the text: who wrote it, from what, and whether a person has checked it. */
export const aiNote = (reviewed: boolean): string =>
  reviewed
    ? tr("Texto redactado por Claude (IA) a partir de las reglas y las métricas publicadas de este modelo, y revisado por una persona.", "Text written by Claude (AI) from this model's published rules and metrics, and reviewed by a person.")
    : tr("Texto redactado por Claude (IA) a partir de las reglas y las métricas publicadas de este modelo. Todavía no lo ha revisado ninguna persona.", "Text written by Claude (AI) from this model's published rules and metrics. No one has reviewed it yet.");

/** One point of the text, its rule ids (only those of this model) turned into rule hovercards. */
export function PointText({ text }: { text: string }) {
  const lookup = useRuleLookup();
  const parts = splitRuleIds(text, (id) => lookup?.byId.has(id) ?? false);
  return <>{parts.map((part, i) => (typeof part === "string" ? part : <RuleRef key={i} id={part.ruleId} />))}</>;
}

/**
 * The explanation in the interface language (contract v0.6.2: both languages are always sent). Only the points are
 * shown (user decision, 2026-11-09): the headline and paragraphs read as a run of figures; they stay in the file.
 */
export function ExplanationBody({ explanation }: { explanation: ModelExplanation }) {
  const { lang } = useLang();
  const text = lang === "en" ? explanation.en : explanation.es;
  return (
    <>
      <ul className="explanation-points">
        {text.points.map((p, i) => (
          <li key={i}>
            <PointText text={p} />
          </li>
        ))}
      </ul>
      <p className="muted small" data-testid="ai-note">
        {aiNote(explanation.reviewed)}
      </p>
    </>
  );
}

/**
 * «Qué hacen estas reglas»: a short text about the rule base, written by an AI from the model's published files. Shown
 * below the rules at a glance, above the cards, when the model has one; a 404 (no explanation yet) shows nothing, other failures the usual retry.
 */
export function ModelExplanationCard({ modelId }: { modelId: string }) {
  const explanation = useOptionalAsync((s) => api.explanation(modelId, s), [modelId]);
  if (explanation.status === "error")
    return (
      <StateMessage kind="error" onRetry={explanation.reload}>
        {tr("No se pudo cargar la explicación de las reglas: ", "Could not load the explanation of the rules: ")}
        {explanation.error.message}
      </StateMessage>
    );
  if (explanation.status !== "ok") return null;
  return (
    <Card title={tr("Qué hacen estas reglas", "What these rules do")} className="explanation-card">
      <div data-testid="model-explanation">
        <ExplanationBody explanation={explanation.data} />
      </div>
    </Card>
  );
}
