import type { RuleDefinition } from "../api/types";
import { tr } from "../i18n";
import { condText, useFeatureLabel, useNames, type Names } from "../lib/labels";

export type DuelView = "side" | "diff";

interface Props {
  on: boolean;
  onToggle: (on: boolean) => void;
  rules: readonly RuleDefinition[];
  modelId: string;
  ruleA: string | null;
  ruleB: string | null;
  onRuleA: (id: string) => void;
  onRuleB: (id: string) => void;
  onSwap: () => void;
  view: DuelView;
  onView: (v: DuelView) => void;
}

const title = (r: RuleDefinition, label: (feature: string) => string, names: Names) => `${r.rule_id}: ${r.antecedents.map((a) => condText(a, label, names)).join(tr(" y ", " and "))}`;

/**
 * Rule Duel controls (E4). Both selectors list only the rules of the loaded model: there is no rule mapping between
 * models, so nothing here can compare across models.
 */
export function DuelControls({ on, onToggle, rules, modelId, ruleA, ruleB, onRuleA, onRuleB, onSwap, view, onView }: Props) {
  const label = useFeatureLabel();
  const names = useNames();
  return (
    <section className="duel-controls" aria-label={tr("Duelo de reglas", "Rule duel")}>
      <h2>{tr("Duelo de reglas", "Rule duel")}</h2>
      <label>
        <input type="checkbox" checked={on} disabled={rules.length < 2} onChange={(e) => onToggle(e.target.checked)} /> {tr("Comparar dos reglas (A y B)", "Compare two rules (A and B)")}
        {rules.length < 2 && <span className="muted">{tr(" (el modelo tiene una sola regla)", " (the model has a single rule)")}</span>}
      </label>
      {on && ruleA && ruleB && (
        <>
          <div className="duel-pick">
            <label>
              {tr("Regla A", "Rule A")}
              <select value={ruleA} onChange={(e) => onRuleA(e.target.value)}>
                {rules.filter((r) => r.rule_id !== ruleB).map((r) => (
                  <option key={r.rule_id} value={r.rule_id}>{title(r, label, names)}</option>
                ))}
              </select>
            </label>
            <label>
              {tr("Regla B", "Rule B")}
              <select value={ruleB} onChange={(e) => onRuleB(e.target.value)}>
                {rules.filter((r) => r.rule_id !== ruleA).map((r) => (
                  <option key={r.rule_id} value={r.rule_id}>{title(r, label, names)}</option>
                ))}
              </select>
            </label>
            <button type="button" onClick={onSwap} aria-label={tr(`Intercambiar A y B (ahora A es ${ruleA} y B es ${ruleB})`, `Swap A and B (now A is ${ruleA} and B is ${ruleB})`)}>A ⇄ B</button>
          </div>
          <fieldset>
            <legend>{tr("Vista del duelo", "Duel view")}</legend>
            <label>
              <input type="radio" name="duel-view" checked={view === "side"} onChange={() => onView("side")} /> {tr("Lado a lado (misma escala 0–1)", "Side by side (same 0–1 scale)")}
            </label>
            <label>
              <input type="radio" name="duel-view" checked={view === "diff"} onChange={() => onView("diff")} /> {tr("Diferencia de activación (A − B)", "Activation difference (A − B)")}
            </label>
          </fieldset>
          <p className="muted" data-testid="duel-scope">
            {tr(<>Las dos reglas son de <code>{modelId}</code> y se piden con la misma medida, instante o ventana y τ. Solo se comparan reglas de un mismo modelo. Entre modelos no hay correspondencia de reglas, y la «R07» de uno no equivale a la «R07» de otro.</>,
              <>Both rules belong to <code>{modelId}</code> and are requested with the same measure, instant or window and τ. Only rules from the same model are compared. Rules don&apos;t map across models, so one model&apos;s “R07” isn&apos;t another&apos;s “R07”.</>)}
          </p>
        </>
      )}
    </section>
  );
}
