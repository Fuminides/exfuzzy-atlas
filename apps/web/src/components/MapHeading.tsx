import { tr } from "../i18n";
import type { RuleMapMetric, TargetScheme } from "../api/types";
import { classTitle, schemeQualifier } from "../lib/classifier";
import type { DomainUi } from "../lib/domainUi";
import { horizonText, sameSampleText , dec } from "../lib/format";
import type { Mode } from "../lib/mode";
import { metricTitle } from "../lib/ruleMapText";
import { mapByRuleTitle } from "../lib/mixtureViews";
import { measureName, measureThe, type TerritoryFocus } from "../lib/territories";

interface Props {
  mode: Mode;
  noun: { one: string; many: string };
  irregular: boolean;
  label: string;
  unit: string;
  horizon: number;
  // Rules mode
  territoriesOn: boolean;
  duelOn: boolean;
  ruleId: string | null;
  ruleB: string | null;
  view: RuleMapMetric;
  tau: number;
  terrFocus: TerritoryFocus;
  terrMeasure: string;
  // Prediction mode
  scheme: TargetScheme | null;
  ui: DomainUi;
  relativeScheme: boolean;
  selectedName: string | null;
  /** The map is coloured by the rule that decided each prediction, not by the prediction. */
  byRule?: boolean;
  /** Mixture of rules (v0.7): no rule decides; the rule coloured is the one that adds the most. */
  mixture?: boolean;
}

/** The title of the map for the mode and view on screen, and which entity is selected. */
export function MapHeading(p: Props) {
  const { mode, noun, irregular, label, unit, horizon, territoriesOn, duelOn, ruleId, ruleB, view, tau, terrFocus, terrMeasure, scheme, ui } = p;
  const predictionTitle = scheme
    ? ui.levelTitle && p.relativeScheme
      ? tr(`${ui.levelTitle} previsto ${horizonText(horizon)}`, `predicted ${ui.levelTitle} ${horizonText(horizon)}`)
      : `${classTitle(scheme, label)} ${horizonText(horizon)} (${schemeQualifier(scheme)})`
    : `${label} ${horizonText(horizon)} (${unit})`;
  const tauText = terrMeasure === "activation_frequency" ? ` (τ = ${dec(tau, 2)})` : "";
  return (
    <>
      {mode === "rules" && !territoriesOn && (
        <h2 className="map-title">
          {duelOn && ruleId ? tr(`Duelo: regla ${ruleId} (A) frente a regla ${ruleB} (B)`, `Duel: rule ${ruleId} (A) vs rule ${ruleB} (B)`) : ruleId ? tr(`Regla ${ruleId}`, `Rule ${ruleId}`) : tr("Mapa de reglas", "Rule map")}: {metricTitle(view, tau)}
        </h2>
      )}
      {territoriesOn && (
        <h2 className="map-title" data-testid="territory-title">
          {terrFocus === "intensity" && ruleId
            ? tr(`Intensidad de la regla ${ruleId} por ${noun.one}: ${measureName(terrMeasure)}${tauText}`, `Intensity of rule ${ruleId} per ${noun.one}: ${measureName(terrMeasure)}${tauText}`)
            : tr(`Territorios de reglas: regla dominante por ${noun.one} según ${measureThe(terrMeasure)}${tauText}`, `Rule territories: dominant rule per ${noun.one} by ${measureName(terrMeasure)}${tauText}`)}
        </h2>
      )}
      {mode === "prediction" && (
        <h2 className="map-title">
          {irregular
            ? tr(`Última muestra de la ventana: ${label} estimado (${unit}), ${sameSampleText()}`, `Last sample of the window: estimated ${label} (${unit}), ${sameSampleText()}`)
            : p.byRule
              ? mapByRuleTitle(!!p.mixture, predictionTitle)
              : tr(`Predicción del modelo: ${predictionTitle}`, `Model prediction: ${predictionTitle}`)}
        </h2>
      )}
      {mode === "data" && (
        <h2 className="map-title" data-testid="data-title">
          {irregular
            ? tr(`Datos observados: última muestra de cada ${noun.one} en la ventana, ${label} medido (${unit})`, `Observed data: last sample of each ${noun.one} in the window, measured ${label} (${unit})`)
            : horizon > 0
              ? tr(`Datos observados: ${label} medido en la hora de validez (emisión + ${horizon} h) (${unit})`, `Observed data: ${label} measured at the valid time (issue + ${horizon} h) (${unit})`)
              : tr(`Datos observados: ${label} medido en la hora de la muestra (${unit})`, `Observed data: ${label} measured at the sample time (${unit})`)}
        </h2>
      )}
      {p.selectedName && (
        <p className="map-selected">
          {tr(`${noun.one.charAt(0).toUpperCase() + noun.one.slice(1)} seleccionad${noun.one === "punto de muestreo" ? "o" : "a"}: `, `Selected ${noun.one}: `)}
          <strong>{p.selectedName}</strong>
        </p>
      )}
    </>
  );
}
