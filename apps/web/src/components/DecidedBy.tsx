import type { RuleDefinition, TargetScheme } from "../api/types";
import { ruleSentence, useFeatureLabel, useNames } from "../lib/labels";
import { RuleRef } from "./RuleRef";
import { RuleSentenceView } from "./RuleSentenceView";
import { tr } from "../i18n";
import { topRuleShareText } from "../lib/mixture";
import { topRuleHeading, topRuleNote } from "../lib/mixtureViews";

interface RuleProps {
  ruleId: string;
  rules: readonly RuleDefinition[];
  scheme: TargetScheme | null;
  /** Takes the user to the rule in Patrones; without it the id is plain text. */
  onOpenRule?: (ruleId: string) => void;
}

/** The id of the rule that decided a prediction; hovering shows the rule's card, clicking opens it in Patrones. */
export function DecidedByRule({ ruleId, onOpenRule }: Pick<RuleProps, "ruleId" | "onOpenRule">) {
  return <RuleRef id={ruleId} onClick={onOpenRule ? () => onOpenRule(ruleId) : undefined} hint={onOpenRule ? tr("Ver la regla en Patrones", "See the rule in Patterns") : undefined} buttonProps={{ "data-decided-by": ruleId }} />;
}

/**
 * Station detail: which rule decided the selected prediction, as the rule's sentence. "Decidir" is the model's own
 * mechanism (the largest association or share among the rules that fired); it says how the model got there, not why
 * the value is what it is.
 */
export function DecidedBy({ ruleId, rules, scheme, onOpenRule, unweighted = false, mixture = false, topShare = null, predictedLabel = null }: RuleProps & { unweighted?: boolean; mixture?: boolean; topShare?: number | null; predictedLabel?: string | null }) {
  const label = useFeatureLabel();
  const names = useNames();
  const def = rules.find((r) => r.rule_id === ruleId);
  return (
    <div className="decided-by" data-testid="decided-by">
      <p>
        <strong>{mixture ? <>{topRuleHeading()}: <RuleRef id={ruleId} /></> : tr(<>La decidió <RuleRef id={ruleId} /></>, <>Decided by <RuleRef id={ruleId} /></>)}</strong>
        {onOpenRule && (
          <>
            {" · "}
            <button type="button" className="link link--go" onClick={() => onOpenRule(ruleId)}>
              {tr(<>Ver la regla en <em>Patrones</em></>, <>See the rule in <em>Patterns</em></>)}
            </button>
          </>
        )}
      </p>
      {def && <RuleSentenceView sentence={ruleSentence(def, label, scheme, names)} />}
      {mixture ? (
        <>
          {topShare !== null && predictedLabel !== null && <p className="small" data-testid="top-rule-share">{topRuleShareText(ruleId, topShare, names.cls(predictedLabel))}</p>}
          <p className="muted small">{topRuleNote()}</p>
        </>
      ) : (
      <p className="muted small">{unweighted
        ? tr("Es la regla que más se activó (ante un empate, la primera en el orden del modelo).", "It's the rule that fired most (on a tie, the first in the model's order).")
        : tr("Es la regla con mayor peso en esta predicción.", "It's the rule with the largest weight in this prediction.")}</p>
      )}
    </div>
  );
}
