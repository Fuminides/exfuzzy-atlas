import { useId, useMemo, useState } from "react";
import type { LinguisticVariable, ModelRules, RuleImportanceResponse, TargetScheme } from "../api/types";
import { tr } from "../i18n";
import { pct, sig3 } from "../lib/format";
import { rankedRules } from "../lib/importance";
import { classColor } from "../lib/classifier";
import { isMixture, leadShare, weightScale } from "../lib/mixture";
import { isExtra } from "../lib/conditions";
import { fullCondition, labelWithUnit, ruleSentence, sentenceText, useFeatureLabel, useNames } from "../lib/labels";
import { colourOf, ruleColours } from "../lib/ruleColours";
import { ruleMatrix } from "../lib/ruleMatrix";
import { RuleSentenceView } from "./RuleSentenceView";
import { ACCENT, columnRange, TermGlyph } from "./TermGlyph";
import { OutcomePill } from "./OutcomePill";
import { ClassChip } from "./ClassChip";
import { WeightBar, WeightKey, WeightValue } from "./ClassWeights";
import { RuleRef } from "./RuleRef";

interface Props {
  model: ModelRules;
  /** null while the importance is not published: rows in the model's order, no share or hit columns. */
  importance: RuleImportanceResponse | null;
  scheme: TargetScheme | null;
  regression: boolean;
  unit: string;
  /** The rule picked in the cards and on the map; clicking a row picks (or releases) it there too. */
  selected: string | null;
  onSelect: (ruleId: string) => void;
  /** The fold is the cards' own: unfolding one unfolds the other, so a picked rule always has its card. */
  showAll: boolean;
  onToggleAll: () => void;
}

/** With many columns (Water: 6) the compact glyph keeps the whole row in view on a desktop. */
const COMPACT_FROM = 5;

/** The glyph of the key: three made-up terms, the middle one filled. */
function KeyGlyph() {
  const v: LinguisticVariable = {
    feature: "key",
    terms: [
      { name: "a", membership_type: "trapezoidal", params: [0, 0, 2, 4] },
      { name: "b", membership_type: "trapezoidal", params: [2, 4, 6, 8] },
      { name: "c", membership_type: "trapezoidal", params: [6, 8, 10, 10] },
    ],
  };
  return <TermGlyph variable={v} term="b" range={[0, 10]} fill={ACCENT} />;
}

/** A small ring for a hit rate (a part of a whole); the number is always written next to it. */
function Ring({ share }: { share: number }) {
  const r = 9;
  const c = 2 * Math.PI * r;
  return (
    <svg className="rmx-ring" viewBox="0 0 24 24" width={24} height={24} aria-hidden="true" focusable="false">
      <circle cx={12} cy={12} r={r} className="rmx-ring-track" />
      <circle cx={12} cy={12} r={r} className="rmx-ring-arc" strokeDasharray={`${Math.max(0, Math.min(1, share)) * c} ${c}`} transform="rotate(-90 12 12)" />
    </svg>
  );
}

/**
 * The rule base at a glance, before the cards: one floating row per rule (ranked like the cards) with one tile per
 * input variable, the term the rule asks for drawn inside the variable's range, then what the rule predicts, the share of the predictions it decides and how often it is right.
 * Underneath it is a real table: every cell carries its text and the glyphs only decorate it. Hovering or focusing a row
 * shows its sentence; clicking picks the rule on the map and in the cards.
 */
export function RuleMatrix({ model, importance, scheme, regression, unit, selected, onSelect, showAll, onToggleAll }: Props) {
  const label = useFeatureLabel();
  const names = useNames();
  const headingId = useId();
  const [active, setActive] = useState<string | null>(null);
  const { columns, rows, nMain, nHidden } = useMemo(() => ruleMatrix(model, importance, showAll), [model, importance, showAll]);
  const variables = useMemo(() => new Map(model.variables.map((v) => [v.feature, v])), [model]);
  const ranges = columns.map((c) => columnRange(variables.get(c.feature)));
  const compact = columns.length >= COMPACT_FROM;
  // the same colour as on the map and in Predicción: the rules that decide most get their own, the rest share the grey
  const colours = useMemo(() => (importance ? ruleColours(rankedRules(importance.rules).map((r) => r.rule_id)) : null), [importance]);
  const sentenceOf = (id: string) => {
    const r = model.rules.find((x) => x.rule_id === id);
    return r ? ruleSentence(r, label, scheme, names) : null;
  };
  const reading = active ?? selected;
  const readingSentence = reading ? sentenceOf(reading) : null;
  const imp = importance !== null;
  const n = model.rules.length;
  // v0.7 rule mixture: one column per class with the rule's centred weight instead of «Entonces»
  const mixture = isMixture(model) && scheme !== null;
  const scale = mixture ? weightScale(model.rules) : 0;
  const unchecked = tr("sin observaciones con las que comprobarlo", "no observations to check it against");

  const onKey = (e: React.KeyboardEvent<HTMLButtonElement>) => {
    const all = [...(e.currentTarget.closest("tbody")?.querySelectorAll<HTMLButtonElement>("button.rmx-rule") ?? [])];
    const i = all.indexOf(e.currentTarget);
    const next = e.key === "ArrowDown" ? i + 1 : e.key === "ArrowUp" ? i - 1 : e.key === "Home" ? 0 : e.key === "End" ? all.length - 1 : null;
    if (next === null || !all[next]) return;
    e.preventDefault();
    all[next].focus();
  };

  return (
    <section className={`rmx${compact ? " rmx--compact" : ""}`} aria-labelledby={headingId}>
      <header className="rmx-head">
        <h2 id={headingId} className="rmx-title">{tr("Las reglas de un vistazo", "The rules at a glance")}</h2>
        <p className="rmx-sub">
          {mixture
            ? tr("Cada fila es una regla, con lo que pide a cada variable y su peso para cada categoría. Pasa el ratón por una fila para leerla entera, o púlsala para verla en el mapa.", "Each row is a rule, with what it asks of each variable and its weight for each category. Hover over a row to read it in full, or click it to see it on the map.")
            : tr("Cada fila es una regla, con lo que pide a cada variable y lo que predice. Pasa el ratón por una fila para leerla entera, o púlsala para verla en el mapa.", "Each row is a rule, with what it asks of each variable and what it predicts. Hover over a row to read it in full, or click it to see it on the map.")}
        </p>
      </header>

      <ul className="rmx-key" data-testid="rule-matrix-key">
        <li>
          <span className="rmx-key-tile"><KeyGlyph /></span>
          {tr("el término que pide la regla, dentro del recorrido de la variable (en gris, sus otros términos)", "the term the rule asks for, inside the variable's range (its other terms in grey)")}
        </li>
        <li>
          <span className="rmx-key-tile rmx-key-tile--empty" />
          {tr("la regla no usa esa variable", "the rule does not use that variable")}
        </li>
        {imp && (
          <li>
            <span className="rmx-swatch" style={{ background: colourOf(colours!, rows[0]?.rule.rule_id ?? "") }} />
            {tr("el color de la regla en el mapa", "the rule's colour on the map")}
          </li>
        )}
        <li className="rmx-key-order">
          {imp && mixture
            ? tr("Columnas: primero la variable cuyas reglas son las que más suman en más predicciones.", "Columns: the variable whose rules add the most in most predictions comes first.")
            : imp
            ? tr("Columnas: primero la variable cuyas reglas deciden más predicciones.", "Columns: the variable whose rules decide most predictions comes first.")
            : tr("Columnas: primero la variable que usan más reglas.", "Columns: the variable used by most rules comes first.")}
        </li>
      </ul>
      {mixture && <WeightKey />}

      <div className={`rmx-reading${readingSentence ? " rmx-reading--on" : ""}`} aria-hidden="true">
        {readingSentence ? (
          <>
            <span className="rule-badge">{reading}</span> <RuleSentenceView sentence={readingSentence} testId="rule-matrix-sentence" />
          </>
        ) : (
          <span className="rmx-reading-hint">{tr("Pasa el ratón por una fila, o llega a ella con el teclado, para leer la regla entera.", "Hover over a row, or reach it with the keyboard, to read the whole rule.")}</span>
        )}
      </div>

      <div className="rmx-scroll" role="region" aria-label={tr("Matriz de reglas (se desplaza en horizontal)", "Rule matrix (scrolls horizontally)")} tabIndex={0}>
        <table className="rmx-table" onMouseLeave={() => setActive(null)}>
          <caption className="sr-only">
            {mixture
              ? tr("Matriz de reglas: una fila por regla, una columna por variable con el término que pide la regla, una columna por categoría con su peso centrado (positivo, apoyo; negativo, supresión) y, si está publicado, la parte de las predicciones en las que es la que más suma y cuánto aciertan esas.", "Rule matrix: one row per rule, one column per variable with the term the rule asks for, one column per category with its centred weight (positive, support; negative, suppression) and, when published, the share of the predictions in which it adds the most and how often those are right.")
              : tr("Matriz de reglas: una fila por regla, una columna por variable con el término que pide la regla, su resultado y, si está publicado, la parte de las predicciones que decide y cuánto acierta.", "Rule matrix: one row per rule, one column per variable with the term the rule asks for, its outcome and, when published, the share of the predictions it decides and how often it is right.")}
          </caption>
          <thead>
            <tr>
              <th scope="col" className="rmx-id">{tr("Regla", "Rule")}</th>
              {columns.map((c) => (
                <th key={c.feature} scope="col" className="rmx-var" data-feature={c.feature} title={labelWithUnit(label(c.feature), variables.get(c.feature)?.unit)}>
                  {label(c.feature)}
                </th>
              ))}
              {mixture
                ? scheme.classes.map((c) => (
                    <th key={c.label} scope="col" className="rmx-class" data-class={c.label}>
                      <ClassChip label={c.label} color={classColor(scheme, c.label)} />
                    </th>
                  ))
                : <th scope="col" className="rmx-out">{tr("Entonces", "Then")}</th>}
              {imp && <th scope="col" className="rmx-share">{mixture ? tr("La que más suma", "Adds the most") : tr("Predicciones que decide", "Predictions it decides")}</th>}
              {imp && <th scope="col" className="rmx-hit">{regression ? tr(`Error medio${unit ? ` (${unit})` : ""}`, `Mean error${unit ? ` (${unit})` : ""}`) : mixture ? tr("Aciertan esas", "Those are right") : tr("Acierta", "Is right")}</th>}
            </tr>
          </thead>
          <tbody>
            {rows.map(({ rule, importance: ri, cells }) => {
              const id = rule.rule_id;
              const sentence = sentenceOf(id)!;
              const on = selected === id;
              const outcome = sentence.outcome;
              const hit = !ri ? null : regression ? (ri.mae == null ? null : sig3(ri.mae)) : ri.accuracy == null ? null : pct(ri.accuracy);
              return (
                <tr
                  key={id}
                  data-rule={id}
                  className={`rmx-row${on ? " rmx-row--on" : ""}${active === id ? " rmx-row--active" : ""}`}
                  aria-current={on ? "true" : undefined}
                  onMouseEnter={() => setActive(id)}
                  onClick={() => onSelect(id)}
                >
                  <th scope="row" className="rmx-id">
                    {colours && <span className="rmx-swatch" style={{ background: colourOf(colours, id) }} aria-hidden="true" />}
                    <RuleRef
                      id={id}
                      className="rmx-rule"
                      onClick={(e) => {
                        e.stopPropagation(); // the row's own click would pick it a second time
                        onSelect(id);
                      }}
                      buttonProps={{
                        "aria-pressed": on,
                        "aria-label": `${id}: ${sentenceText(sentence)}`,
                        onFocus: () => setActive(id),
                        onBlur: () => setActive(null),
                        onKeyDown: onKey,
                      }}
                    >
                      {id}
                    </RuleRef>
                  </th>
                  {cells.map((a, i) => {
                    const c = columns[i]!;
                    if (!a)
                      return (
                        <td key={c.feature} className="rmx-cell rmx-cell--empty">
                          <span className="rmx-tile rmx-tile--empty" aria-hidden="true" />
                          <span className="sr-only">{tr("no la usa", "not used")}</span>
                        </td>
                      );
                    const v = variables.get(c.feature);
                    const r = ranges[i];
                    const part = sentence.parts.find((p) => p.feature === a.feature && p.term === a.term);
                    return (
                      <td key={c.feature} className="rmx-cell" data-term={a.term} title={isExtra(a) ? fullCondition(a, label, names) : undefined}>
                        <span className="rmx-tile">
                          {v && r && <TermGlyph variable={v} term={a.term} range={r} fill={part?.color ?? ACCENT} compact={compact} condition={a} />}
                          <span className="rmx-term">
                            {part?.color && <span className="class-swatch" style={{ background: part.color }} aria-hidden="true" />}
                            <em className="term-phrase">{names.phrase(a.feature, a.term, a)}</em>
                            {a.modifier != null && a.modifier !== 1 && <span className="muted"> ^{a.modifier}</span>}
                          </span>
                        </span>
                      </td>
                    );
                  })}
                  {mixture ? (
                    scheme.classes.map((c) => {
                      const v = rule.class_weights_centred?.[c.label];
                      const strongest = rule.strongest_class === c.label;
                      return (
                        <td key={c.label} className={`rmx-wcell${strongest ? " rmx-wcell--strongest" : ""}`} data-class={c.label}>
                          {typeof v === "number" ? (
                            <span className="rmx-wcell-in">
                              <WeightBar value={v} scale={scale} />
                              <WeightValue value={v} strong={strongest} />
                            </span>
                          ) : (
                            <span className="muted">—</span>
                          )}
                        </td>
                      );
                    })
                  ) : (
                  <td className="rmx-out">
                    <span className="rmx-arrow" aria-hidden="true">→</span>
                    <OutcomePill outcome={outcome} />
                  </td>
                  )}
                  {imp && (
                    <td className="rmx-share">
                      {ri && (ri.decided_share ?? ri.top_contributor_share) != null ? ( /* a mixture (v0.7): the top-rule share */
                        <>
                          <span className="rmx-share-num">{pct(leadShare(ri))}</span>
                          <span className="rmx-bar" aria-hidden="true">
                            <span style={{ width: `${Math.min(1, leadShare(ri)) * 100}%`, background: colours ? colourOf(colours, id) : ACCENT }} />
                          </span>
                        </>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                  )}
                  {imp && (
                    <td className="rmx-hit" title={hit === null && ri && leadShare(ri) > 0 ? unchecked : undefined}>
                      {hit === null ? (
                        <span className="muted">—</span>
                      ) : (
                        <span className="rmx-hit-in">
                          {!regression && ri?.accuracy != null && <Ring share={ri.accuracy} />}
                          {hit}
                        </span>
                      )}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {nHidden > 0 && (
        <button type="button" className="rmx-fold" onClick={onToggleAll} aria-expanded={showAll}>
          {showAll
            ? imp && mixture
              ? tr("Ocultar las reglas que son la que más suma en menos del 1 %", "Hide the rules that add the most in less than 1%")
              : imp
              ? tr("Ocultar las reglas que deciden menos del 1 %", "Hide the rules that decide less than 1%")
              : tr(`Ver solo las ${nMain} primeras en la matriz`, `Show only the first ${nMain} in the matrix`)
            : imp && mixture
              ? nHidden === 1
                ? tr("Ver también la regla que es la que más suma en menos del 1 %", "Also show the rule that adds the most in less than 1%")
                : tr(`Ver también las ${nHidden} reglas que son la que más suma en menos del 1 %`, `Also show the ${nHidden} rules that add the most in less than 1%`)
              : imp
              ? nHidden === 1
                ? tr("Ver también la regla que decide menos del 1 %", "Also show the rule that decides less than 1%")
                : tr(`Ver también las ${nHidden} reglas que deciden menos del 1 %`, `Also show the ${nHidden} rules that decide less than 1%`)
              : tr(`Ver las ${n} reglas en la matriz`, `Show all ${n} rules in the matrix`)}
        </button>
      )}
    </section>
  );
}
