import { tr } from "../i18n";
import type { RuleSentence } from "../lib/labels";
import { strongestText } from "../lib/mixture";
import { ClassChip } from "./ClassChip";

/**
 * A rule as a sentence: «Si el **NO₂ hace 4 h** es [*Buena*] y la **hora de validez** es *Noche* → [*Buena*]», «Si la
 * **demanda hace 1 h** es [*alta*] → [*demanda alta*]». Each variable is named once (bold), the term agrees with it and is
 * italic (lib/termPhrases.ts), classes are chips in the scheme's colour (a chip always carries its text too). A rule of
 * a mixture (contract v0.7) concludes nothing on its own: after the arrow it says the class it supports most.
 */
export function RuleSentenceView({ sentence, testId = "rule-sentence" }: { sentence: RuleSentence; testId?: string }) {
  const { parts, outcome } = sentence;
  return (
    <p className="rule-sentence" data-testid={testId}>
      <span className="kw">{tr("Si", "If")}</span>{" "}
      {parts.map((p, i) => (
        <span key={`${p.feature}|${p.term}`} className="cond">
          {i > 0 && <span className="kw">{tr(" y ", " and ")}</span>}
          {p.words.article && <>{p.words.article} </>}
          <strong className="var">{p.words.subject}</strong> <span className="kw">{p.words.verb}</span>{" "}
          {p.color ? <ClassChip label={p.term} text={p.words.value} color={p.color} /> : <em className="term">{p.words.value}</em>}
          {p.modifier !== null && p.modifier !== 1 && <span className="muted small">{tr(` (modificador ^${p.modifier})`, ` (modifier ^${p.modifier})`)}</span>}
        </span>
      ))}{" "}
      <span className="arrow" aria-label={tr("entonces", "then")}>
        →
      </span>{" "}
      {outcome.kind === "mixture" ? (
        <span className="outcome outcome--mixture" data-testid="rule-strongest">
          {outcome.key === null ? (
            strongestText(null)
          ) : (
            <>
              {tr("apoya sobre todo", "supports most")}{" "}
              {outcome.color ? <ClassChip label={outcome.key} text={outcome.label ?? outcome.key} color={outcome.color} /> : <strong>{outcome.label}</strong>}
            </>
          )}
        </span>
      ) : outcome.kind === "class" ? (
        outcome.color ? (
          <span className="outcome"><ClassChip label={outcome.key} text={outcome.label} color={outcome.color} /></span>
        ) : (
          <strong className="outcome">{outcome.label}</strong>
        )
      ) : outcome.kind === "value" ? (
        <strong className="outcome">{outcome.text}</strong>
      ) : (
        <em className="outcome">{outcome.label}</em>
      )}
    </p>
  );
}
