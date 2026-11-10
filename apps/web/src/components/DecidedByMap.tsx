import { articles } from "../lib/domainUi";
import { colourOf, OTHER_RULES_COLOUR, otherRulesLabel, presentRules } from "../lib/ruleColours";
import { tr } from "../i18n";
import { byRuleLegendWords, colourByRuleOption } from "../lib/mixtureViews";
import { RuleRef } from "./RuleRef";

export type ColourBy = "prediction" | "rule";

/** The switch above the Predicción map: paint the predicted category, or the rule that decided each prediction. */
export function ColourBySwitch({ value, onChange, regression = false, mixture = false }: { value: ColourBy; onChange: (v: ColourBy) => void; regression?: boolean; mixture?: boolean }) {
  return (
    <div className="colour-by">
      <span className="colour-by-label">{tr("Colorear por:", "Colour by:")}</span>
      <div className="modes" role="group" aria-label={tr("Colorear el mapa por", "Colour the map by")}>
      {(
        [
          ["prediction", regression ? tr("valor estimado", "estimated value") : tr("categoría prevista", "predicted category")],
          ["rule", colourByRuleOption(mixture)],
        ] as const
      ).map(([id, text]) => (
        <button key={id} type="button" aria-pressed={value === id} onClick={() => onChange(id)}>
          {text}
        </button>
      ))}
      </div>
    </div>
  );
}

interface LegendProps {
  colours: ReadonlyMap<string, string>;
  /** The rule that decided each entity's prediction (null: no rule is named). */
  decidedBy: readonly (string | null | undefined)[];
  noun: { one: string; many: string };
  total: number;
  onOpenRule?: (ruleId: string) => void;
  detail?: React.ReactNode;
  /** Mixture of rules (v0.7): the colour is the rule that adds the most to the predicted category. */
  mixture?: boolean;
}

/** Categorical legend of "regla que decidió": only the rules present on screen, each with its rule card on hover, the grey for the rest. */
export function DecidedByLegend({ colours, decidedBy, noun, total, onOpenRule, detail, mixture = false }: LegendProps) {
  const { coloured, others } = presentRules(colours, decidedBy);
  const g = articles(noun.one);
  const w = byRuleLegendWords(mixture, noun, g.el);
  return (
    <section className="legend legend--rules legend--decided" aria-label={tr(`Leyenda: ${w.title}`, `Legend: ${w.title}`)}>
      <h3>{w.title}</h3>
      <p className="muted">{w.note}</p>
      <ol className="rule-legend" aria-label={w.list}>
        {coloured.map(({ id, n }) => (
          <li key={id} data-rule={id} data-color={colourOf(colours, id)}>
            <RuleRef id={id} className="rule-legend-btn" onClick={onOpenRule ? () => onOpenRule(id) : undefined} hint={onOpenRule ? tr("Ver la regla en Patrones", "See the rule in Patterns") : undefined}>
              <span className="territory-swatch" style={{ background: colourOf(colours, id) }} aria-hidden="true" />
              <strong>{id}</strong> <span className="muted small">{n}</span>
            </RuleRef>
          </li>
        ))}
        {others.ids.length > 0 && (
          <li data-rule="otras">
            <span className="rule-legend-btn rule-legend-btn--other" title={others.ids.join(", ")}>
              <span className="territory-swatch" style={{ background: OTHER_RULES_COLOUR }} aria-hidden="true" />
              {otherRulesLabel()} <span className="muted small">{others.n}</span>
            </span>
          </li>
        )}
      </ol>
      <p className="legend-missing">
        <span className="marker marker--missing" aria-hidden="true" />{" "}
        {w.missing}
      </p>
      <p className="legend-count">
        {w.count}
        <strong>{decidedBy.filter(Boolean).length}</strong> {tr("de", "of")} {total}
      </p>
      {detail}
    </section>
  );
}
