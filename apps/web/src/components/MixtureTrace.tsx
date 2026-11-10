import type { RuleTrace, TargetScheme } from "../api/types";
import { tr } from "../i18n";
import { classColor } from "../lib/classifier";
import { dec, fmt } from "../lib/format";
import { useNames } from "../lib/labels";
import { howItPredicts, signed, topRuleShareTail } from "../lib/mixture";
import { ClassChip } from "./ClassChip";
import { WeightBar, WeightKey, WeightValue } from "./ClassWeights";
import { RuleRef } from "./RuleRef";

interface Props {
  trace: RuleTrace;
  scheme: TargetScheme;
  onSelectRule: (ruleId: string) => void;
  selectedRuleId: string | null;
}

/**
 * ¿Por qué aquí? for a mixture of rules (contract v0.7): what each rule that holds adds to each category (the trace's
 * `class_contributions_centred`), the score of each category (`class_scores`, with `class_bias`) and the rule that adds
 * the most to the predicted one (`top_rule_id`, `top_rule_share`). No rule decides: the category with the largest total
 * wins. Every number is the trace's; the browser only sorts the rows and formats.
 */
export function MixtureTrace({ trace, scheme, onSelectRule, selectedRuleId }: Props) {
  const names = useNames();
  const p = trace.prediction;
  const label = p.label ?? null;
  const classes = scheme.classes.map((c) => c.label);
  const holding = trace.rules.filter((r) => r.firing_strength > 0 && r.class_contributions_centred);
  const silent = trace.rules.length - holding.length;
  // the rows from the rule that adds the most to the predicted category to the one that adds the least (given values)
  const rows = label ? [...holding].sort((a, b) => (b.class_contributions_centred![label] ?? 0) - (a.class_contributions_centred![label] ?? 0) || a.rule_id.localeCompare(b.rule_id)) : holding;
  let scale = 0;
  for (const r of holding) for (const c of classes) scale = Math.max(scale, Math.abs(r.class_contributions_centred![c] ?? 0));
  const scores = p.class_scores ?? null;
  const bias = p.class_bias ?? null;
  const topId = p.top_rule_id ?? null;
  return (
    <div className="mixture-trace" data-testid="mixture-trace">
      <p className="muted small">{howItPredicts()}</p>
      {label && topId && p.top_rule_share != null ? (
        <p data-testid="top-rule-note">
          <RuleRef id={topId} />{" "}
          {topRuleShareTail(p.top_rule_share, names.cls(label))}
        </p>
      ) : label ? (
        <p data-testid="top-rule-note">
          {tr(`Ninguna regla apoya ${names.cls(label)} aquí: gana por su sesgo y por lo que las reglas restan a las demás categorías.`, `No rule supports ${names.cls(label)} here: it wins by its bias and by what the rules take from the other categories.`)}
        </p>
      ) : null}

      {scores && (
        <>
          <h3>{tr("Puntuación de cada categoría", "Score of each category")}</h3>
          <table className="plain mixture-scores" aria-label={tr("Puntuación de cada categoría", "Score of each category")}>
            <thead>
              <tr>
                <th scope="col">{tr("Categoría", "Category")}</th>
                <th scope="col" className="num" title="class_bias">{tr("Sesgo", "Bias")}</th>
                <th scope="col" className="num" title="class_scores">{tr("Puntuación", "Score")}</th>
              </tr>
            </thead>
            <tbody>
              {classes.map((c) => (
                <tr key={c} data-class={c} aria-current={c === label ? "true" : undefined}>
                  <th scope="row">
                    <ClassChip label={c} color={classColor(scheme, c)} />
                    {c === label && <span className="badge-win">{tr("prevista", "predicted")}</span>}
                  </th>
                  <td className="num">{bias && typeof bias[c] === "number" ? <span data-raw={String(bias[c])}>{signed(bias[c]!)}</span> : "—"}</td>
                  <td className="num">{typeof scores[c] === "number" ? <strong data-raw={String(scores[c])}>{dec(scores[c]!, 2)}</strong> : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted small">
            {tr("La puntuación es el sesgo más lo que suman las reglas que se cumplen. Gana la categoría de mayor puntuación.", "The score is the bias plus what the rules that hold add. The category with the highest score wins.")}
          </p>
        </>
      )}

      <h3>{tr("Lo que suma cada regla a cada categoría", "What each rule adds to each category")}</h3>
      {holding.length === 0 ? (
        <p className="muted">{tr("Aquí no se cumple ninguna regla.", "No rule holds here.")}</p>
      ) : (
        <>
          <WeightKey note={false} />
          <div className="table-scroll">
            <table className="plain mixture-adds" aria-label={tr("Lo que suma cada regla que se cumple a cada categoría (centrado)", "What each rule that holds adds to each category (centred)")}>
              <thead>
                <tr>
                  <th scope="col">{tr("Regla", "Rule")}</th>
                  <th scope="col" className="num" title="firing_strength">{tr("Se cumple", "Holds")}</th>
                  {classes.map((c) => (
                    <th key={c} scope="col" className={`mixture-class${c === label ? " mixture-class--predicted" : ""}`} data-class={c}>
                      <ClassChip label={c} color={classColor(scheme, c)} />
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.rule_id} data-rule={r.rule_id} aria-current={r.rule_id === topId ? "true" : undefined}>
                    <th scope="row">
                      <RuleRef id={r.rule_id} className="link" onClick={() => onSelectRule(r.rule_id)} buttonProps={{ "aria-label": tr(`Seleccionar regla ${r.rule_id}`, `Select rule ${r.rule_id}`) }}>
                        {r.rule_id}
                      </RuleRef>
                      {r.rule_id === topId && <span className="badge-win">{tr("la que más suma", "adds the most")}</span>}
                      {r.rule_id === selectedRuleId && <span className="muted">{tr(" (seleccionada)", " (selected)")}</span>}
                    </th>
                    <td className="num"><span data-raw={String(r.firing_strength)}>{fmt(r.firing_strength)}</span></td>
                    {classes.map((c) => {
                      const v = r.class_contributions_centred![c];
                      return (
                        <td key={c} className={`mixture-cell${c === label ? " mixture-cell--predicted" : ""}`} data-class={c}>
                          {typeof v === "number" ? (
                            <span className="rmx-wcell-in">
                              <WeightBar value={v} scale={scale} />
                              <WeightValue value={v} strong={c === label} />
                            </span>
                          ) : "—"}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted small" data-testid="mixture-adds-note">
            {tr("Cada cifra es lo que la regla suma a esa categoría aquí: su peso centrado por cuánto se cumple. Centrar resta a cada regla la misma cantidad en todas las categorías, así que no cambia qué categoría gana, pero estas cifras no suman la puntuación.", "Each figure is what the rule adds to that category here: its centred weight times how much it holds. Centring takes the same amount from every category of a rule, so it does not change which category wins, but these figures do not add up to the score.")}
            {silent > 0 && (silent === 1 ? tr(" Otra regla no se cumple aquí y no suma nada.", " One more rule does not hold here and adds nothing.") : tr(` Otras ${silent} reglas no se cumplen aquí y no suman nada.`, ` ${silent} more rules do not hold here and add nothing.`))}
          </p>
        </>
      )}
    </div>
  );
}
