import type { ModelCard, RuleMapMetric, TerritoryMeasure } from "../api/types";
import { tr } from "../i18n";
import type { RulesView } from "../lib/mode";
import { VIEW_LABEL } from "../lib/ruleMapText";
import { noWinnerShareReason } from "../lib/mixtureViews";
import { MEASURE_LABEL, TERRITORY_MEASURES, type TerritoryFocus } from "../lib/territories";
import { coverageFits, type TimeWindow, type WindowKind } from "../lib/windows";
import { dec } from "../lib/format";
import { isStaticData } from "../lib/dataMode";

const WINDOW_KINDS: readonly Exclude<WindowKind, "coverage" | "year">[] = ["day", "week", "month"];
// Built at render (not at import): the language can change while the page is open.
const windowLabel = (k: Exclude<WindowKind, "coverage" | "year">): string =>
  ({
    day: tr("Día (UTC) que contiene la hora seleccionada", "Day (UTC) containing the selected time"),
    week: tr("Semana (lunes–lunes, UTC)", "Week (Monday–Monday, UTC)"),
    month: tr("Mes (UTC)", "Month (UTC)"),
  })[k];

interface Props {
  noun: string;
  irregular: boolean;
  classifier: boolean;
  /** A mixture of rules (v0.7): no rule decides, so «Reglas ganadoras» is not offered. */
  mixture?: boolean;
  coverage: NonNullable<ModelCard["coverage"]>;
  window: TimeWindow;
  rulesView: RulesView;
  onRulesView: (v: RulesView) => void;
  view: RuleMapMetric;
  onView: (m: RuleMapMetric) => void;
  ruleId: string | null;
  tau: number;
  onTau: (t: number) => void;
  emphasis: number;
  onEmphasis: (e: number) => void;
  terrMeasure: TerritoryMeasure;
  onTerrMeasure: (m: TerritoryMeasure) => void;
  terrFocus: TerritoryFocus;
  onTerrFocus: (f: TerritoryFocus) => void;
  /** The window kind in effect, and the window a story pinned (which replaces the kind until cleared). */
  kind: WindowKind;
  onKind: (k: WindowKind) => void;
  customWindow: TimeWindow | null;
  onClearPins: () => void;
  /** Static export: the τ values it holds and the window kinds it has. The controls offer nothing else. */
  taus?: readonly number[];
  kinds?: readonly WindowKind[];
}

/** Rules mode controls: the view (rule or territories), the measure and its parameters, and the aggregate's window. */
export function RulesControls(p: Props) {
  const { noun, irregular, classifier, mixture = false, coverage, window, rulesView, view, ruleId, tau, terrMeasure, terrFocus, kind, customWindow, taus, kinds } = p;
  const staticSite = isStaticData();
  const offers = (k: WindowKind) => !kinds || kinds.includes(k);
  const tauShown = (rulesView === "rule" && view === "activation_frequency") || (terrMeasure === "activation_frequency" && rulesView === "territories");
  const tauIndex = taus ? taus.reduce((best, t, i) => (Math.abs(t - tau) < Math.abs(taus[best]! - tau) ? i : best), 0) : 0;
  return (
    <section className="controls" aria-label={tr("Controles de la vista de reglas", "Rules view controls")}>
      <fieldset>
        <legend>{tr("Vista", "View")}</legend>
        <div className="window-kinds" role="group" aria-label={tr("Vista de reglas", "Rules view")}>
          <button type="button" aria-pressed={rulesView === "rule"} onClick={() => p.onRulesView("rule")}>
            {tr("Regla", "Rule")}
          </button>
          <button type="button" aria-pressed={rulesView === "territories"} onClick={() => p.onRulesView("territories")}>
            {tr("Territorios", "Territories")}
          </button>
        </div>
      </fieldset>
      {rulesView === "rule" && (
      <fieldset>
        <legend>{tr("Medida", "Measure")}</legend>
        {(Object.keys(VIEW_LABEL) as RuleMapMetric[])
          // An instant means nothing when issue times are sample times: only window aggregates are offered.
          .filter((m) => !(irregular && m === "firing_strength"))
          .map((m) => (
          <label key={m}>
            <input type="radio" name="view" checked={view === m} onChange={() => p.onView(m)} /> {VIEW_LABEL[m]}
          </label>
        ))}
      </fieldset>
      )}
      {rulesView === "territories" && (
        <>
          <fieldset>
            <legend>{tr("Medida del territorio", "Territory measure")}</legend>
            {TERRITORY_MEASURES.map((m) => (
              <label key={m}>
                <input type="radio" name="territory-measure" checked={terrMeasure === m} disabled={m === "winner_share" && (!classifier || mixture)} onChange={() => p.onTerrMeasure(m)} /> {MEASURE_LABEL[m]}
              </label>
            ))}
            {!classifier && <p className="muted">{tr("«Reglas ganadoras» solo existe en clasificadores, y este modelo es un regresor TSK.", "“Winning rules” only exists for classifiers, and this model is a TSK regressor.")}</p>}
            {classifier && mixture && <p className="muted" data-testid="no-winner-share">{noWinnerShareReason()}</p>}
          </fieldset>
          <fieldset>
            <legend>{tr("Qué se colorea", "What is coloured")}</legend>
            {(
              [
                ["all", tr(`Regla dominante de cada ${noun}`, `Dominant rule per ${noun}`)],
                ["territory", ruleId ? tr(`Resaltar el territorio de ${ruleId}`, `Highlight ${ruleId}'s territory`) : tr("Resaltar el territorio de la regla elegida", "Highlight the territory of the chosen rule")],
                ["intensity", ruleId ? tr(`Intensidad de ${ruleId} (escala secuencial)`, `Intensity of ${ruleId} (sequential scale)`) : tr("Intensidad de la regla elegida", "Intensity of the chosen rule")],
              ] as [TerritoryFocus, string][]
            ).map(([f, text]) => (
              <label key={f}>
                <input type="radio" name="territory-focus" checked={terrFocus === f} disabled={f !== "all" && ruleId === null} onChange={() => p.onTerrFocus(f)} /> {text}
              </label>
            ))}
          </fieldset>
        </>
      )}
      {irregular && (
        <p className="muted" data-testid="irregular-window-hint">
          {tr(<>Ventana <code>[{window.from}, {window.to})</code> UTC, elegida en la línea temporal de abajo. Las muestras son irregulares y no hay un instante de emisión que mirar.</>,
            <>Window <code>[{window.from}, {window.to})</code> UTC, chosen on the timeline below. The samples are irregular, so there&apos;s no issue instant to look at.</>)}
        </p>
      )}
      {tauShown && (!staticSite || taus) && (
        <label className="slider">
          {staticSite ? tr("τ de la frecuencia: ", "Frequency τ: ") : tr("τ de la frecuencia (parámetro de la API): ", "Frequency τ (API parameter): ")}<strong>{dec(taus ? taus[tauIndex]! : tau, 2)}</strong>
          {taus ? (
            // a static export holds a fixed set of τ values: the slider moves over those and nothing else
            <input type="range" min={0} max={taus.length - 1} step={1} value={tauIndex} onChange={(e) => p.onTau(taus[Number(e.target.value)]!)} />
          ) : (
            <input type="range" min={0.05} max={1} step={0.05} value={tau} onChange={(e) => p.onTau(Number(e.target.value))} />
          )}
        </label>
      )}
      {customWindow && (
        <p className="muted" data-testid="custom-window">
          {tr(<>Ventana fijada por una historia: <code>[{customWindow.from}, {customWindow.to})</code> UTC.</>, <>Window pinned by a story: <code>[{customWindow.from}, {customWindow.to})</code> UTC.</>)}{" "}
          <button type="button" className="link" onClick={p.onClearPins}>
            {tr("Volver a la ventana elegida", "Back to the chosen window")}
          </button>
        </p>
      )}
      {(rulesView === "territories" || view !== "firing_strength") && !irregular && (
        <fieldset>
          <legend>{tr("Ventana del agregado", "Aggregate window")}</legend>
          {WINDOW_KINDS.filter(offers).map((k) => (
            <label key={k}>
              <input
                type="radio"
                name="window"
                checked={kind === k && customWindow === null}
                onChange={() => {
                  p.onKind(k);
                  p.onClearPins();
                }}
              />{" "}
              {windowLabel(k)}
            </label>
          ))}
          {offers("coverage") && (
          <label>
            <input
              type="radio"
              name="window"
              checked={kind === "coverage" && customWindow === null}
              disabled={!coverageFits(coverage)}
              onChange={() => {
                p.onKind("coverage");
                p.onClearPins();
              }}
            />{" "}
            {tr("Toda la cobertura", "Whole coverage")}
            {!coverageFits(coverage) && <span className="muted">{tr(" (supera los 366 días que admite la API)", " (longer than the 366 days the API accepts)")}</span>}
          </label>
          )}
          <p className="muted">
            {tr(<>Ventana <code>[{window.from}, {window.to})</code> UTC. La línea temporal mueve la ventana y el desglose.</>, <>Window <code>[{window.from}, {window.to})</code> UTC. The timeline moves the window and the breakdown.</>)}
          </p>
        </fieldset>
      )}
      {rulesView === "rule" && (
      <label className="slider">
        {tr("Énfasis visual ≥ ", "Visual emphasis ≥ ")}<strong>{dec(p.emphasis, 2)}</strong>
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={p.emphasis}
          onChange={(e) => p.onEmphasis(Number(e.target.value))}
          aria-label={tr("Umbral de énfasis visual", "Visual emphasis threshold")}
        />
        <span className="muted">{tr("Solo atenúa los puntos por debajo del umbral. Los datos no cambian.", "Only dims the points below the threshold. The data stay the same.")}</span>
      </label>
      )}
    </section>
  );
}
