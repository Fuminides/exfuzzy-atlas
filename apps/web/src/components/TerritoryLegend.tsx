import type { RuleDefinition, RuleTerritoriesResponse } from "../api/types";
import { MEASURE_DEFINITION, MEASURE_LABEL, measureName, measureThe, type TerritoryFocus } from "../lib/territories";
import type { TimeWindow } from "../lib/windows";
import { windowDays } from "../lib/windows";
import { tr } from "../i18n";
import { dec } from "../lib/format";
import { articles } from "../lib/domainUi";
import { colourOrModelOrder } from "../lib/ruleColours";
import { RuleRef } from "./RuleRef";

interface Props {
  data: RuleTerritoriesResponse;
  rules: readonly RuleDefinition[];
  /** Rules that dominate at least one entity, with how many. */
  present: readonly { ruleId: string; count: number }[];
  selectedRule: string | null;
  onSelect: (ruleId: string) => void;
  focus: TerritoryFocus;
  window: TimeWindow;
  /** Entities with a dominant rule / entities the model covers. */
  withDominant: number;
  total: number;
  nValid: readonly [number, number] | null;
  noun: { one: string; many: string };
  detail?: React.ReactNode;
  /** The shared rule colours (ranking of Patrones); without them, the model's rule order. */
  colours?: ReadonlyMap<string, string> | null;
}

/**
 * Categorical legend of Rule Territories: one colour per rule, listing ONLY the rules that dominate somewhere. It states
 * the measure, tau, the tie-break and the denominator, and that territories overlap. Its colours are categories of rules,
 * not values: the sequential activation scale has its own legend.
 */
export function TerritoryLegend({ data, rules, present, selectedRule, onSelect, focus, window, withDominant, total, nValid, noun, detail, colours }: Props) {
  const measure = data.measure;
  const g = articles(noun.one);
  const title = tr(`Territorios de reglas: regla dominante por ${noun.one} según ${measureName(measure)}`, `Rule territories: dominant rule per ${noun.one} by ${measureName(measure)}`);
  const highest =
    measure === "mean_activation"
      ? tr("activación media", "mean activation")
      : measure === "activation_frequency"
        ? tr("frecuencia de activación", "activation frequency")
        : tr("fracción de registros decididos", "share of records decided");
  return (
    <section className="legend legend--territories" aria-label={tr(`Leyenda: ${title}`, `Legend: ${title}`)} data-measure={measure} data-focus={focus}>
      <div className="legend-text">
        <h3>{title}</h3>
        <p className="muted" data-testid="territory-overlap">
          {tr(`Las reglas se solapan, y el color muestra solo la dominante según ${measureThe(measure)}, es decir, la de mayor ${highest} en ${g.ese} ${noun.one}.`, `Rules overlap, and the colour shows only the dominant one by ${measureName(measure)}, that is, the one with the highest ${highest} at that ${noun.one}.`)}
        </p>
        <dl className="territory-facts">
          <div>
            <dt>{tr("Medida", "Measure")}</dt>
            <dd data-testid="territory-measure">
              <span title={measure}>{MEASURE_LABEL[measure]}</span>: {MEASURE_DEFINITION[measure](data.tau)}.
            </dd>
          </div>
          <div>
            <dt>τ</dt>
            <dd data-testid="territory-tau">
              {measure === "activation_frequency" ? (
                <>
                  <code>{dec(data.tau, 2)}</code> {tr("(umbral de la frecuencia)", "(frequency threshold)")}
                </>
              ) : (
                <>{tr("no interviene en esta medida", "not used by this measure")}</>
              )}
            </dd>
          </div>
          <div>
            <dt>{tr("Desempate", "Tie-break")}</dt>
            <dd data-testid="territory-tiebreak">{tr("gana la regla de menor posición (R01 antes que R02) si los valores difieren menos de 1e-12.", "the rule with the lower position wins (R01 before R02) if the values differ by less than 1e-12.")}</dd>
          </div>
          <div>
            <dt>{tr("Denominador", "Denominator")}</dt>
            <dd data-testid="territory-nvalid">
              <span title="n_valid">{tr("Registros válidos", "Valid records")}</span>
              {tr(`: los de ${g.el} ${noun.one} en la ventana con todas las entradas presentes`, `: those of the ${noun.one} in the window with every input present`)}
              {nValid && tr(`: de ${nValid[0]} a ${nValid[1]}`, `: from ${nValid[0]} to ${nValid[1]}`)}
              .
            </dd>
          </div>
          <div>
            <dt>{tr("Ventana", "Window")}</dt>
            <dd>
              <code>[{window.from}, {window.to})</code> {tr(`UTC, semiabierta, ${windowDays(window)} d.`, `UTC, half-open, ${windowDays(window)} d.`)}
            </dd>
          </div>
        </dl>
        <details className="column-help">
          <summary>{tr("Texto del criterio, tal como se publica", "The criterion's text, as published")}</summary>
          <p data-testid="territory-api-text">
            <span title="tie_break">{tr("Desempate", "Tie-break")}</span>: {data.tie_break}
          </p>
          <p>
            <span title="denominators">{tr("Denominadores", "Denominators")}</span>: {data.denominators}
          </p>
          {(data.notes ?? []).map((n) => (
            <p key={n} className="muted">
              {n}
            </p>
          ))}
        </details>
      </div>
      <div className="legend-scale">
        <ol className="territory-list" aria-label={tr("Reglas que dominan en alguna entidad (categorías de regla, no una escala)", "Rules that dominate somewhere (rule categories, not a scale)")}>
          {present.map(({ ruleId, count }) => {
            const color = colourOrModelOrder(colours, rules, ruleId);
            return (
              <li key={ruleId} data-rule={ruleId} data-color={color}>
                <RuleRef id={ruleId} className="territory-rule" onClick={() => onSelect(ruleId)} buttonProps={{ "aria-pressed": focus !== "all" && selectedRule === ruleId }}>
                  <span className="territory-swatch" style={{ background: color }} aria-hidden="true" />
                  <strong>{ruleId}</strong>{" "}
                  <span className="muted">{tr(`domina en ${count} de ${total}`, `dominates in ${count} of ${total}`)}</span>
                </RuleRef>
              </li>
            );
          })}
        </ol>
        <p className="legend-missing">
          <span className="marker marker--missing" aria-hidden="true" />{" "}
          {tr("sin regla dominante (sin registros válidos, o la medida es 0 en todas las reglas)", "no dominant rule (no valid records, or the measure is 0 for every rule)")}
        </p>
        <p className="legend-count">
          {tr(`${noun.many.charAt(0).toUpperCase() + noun.many.slice(1)} con regla dominante: `, `${noun.many.charAt(0).toUpperCase() + noun.many.slice(1)} with a dominant rule: `)}
          <strong>{withDominant}</strong> {tr("de", "of")} {total}
        </p>
        {detail}
      </div>
    </section>
  );
}
