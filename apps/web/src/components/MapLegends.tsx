import type { ReactNode } from "react";
import type { ModelRules, ObservationsResponse, RuleMapMetric, RuleTerritoriesResponse, TargetScheme } from "../api/types";
import { classTitle, schemeQualifier } from "../lib/classifier";
import { BLUES, MAGMA, VIRIDIS } from "../lib/colorScale";
import { tr } from "../i18n";
import { fmtNum, formatInstant, sameSampleText , dec, numShort } from "../lib/format";
import { legendTitle } from "../lib/ruleMapText";
import { dominanceCounts, measureName, measureThe, type TerritoryFocus } from "../lib/territories";
import { windowDays, type TimeWindow } from "../lib/windows";
import { CategoricalLegend } from "./CategoricalLegend";
import { Legend } from "./Legend";
import { TerritoryLegend } from "./TerritoryLegend";
import { articles, type DomainUi } from "../lib/domainUi";
import { ACTIVATION_DOMAIN } from "../lib/mapLayer";



/** What every legend of the map shares: the nouns, the counts and the notes about periods, geometry and "sin modelo". */
interface Common {
  noun: { one: string; many: string };
  /** The plural noun capitalised ("Estaciones"). */
  Nouns: string;
  /** Entities with a value (or a label) and entities the model has data for. */
  withValue: number;
  total: number;
  periodNote: ReactNode;
  noGeometryNote: ReactNode;
  absentNote: ReactNode;
  /** The target (name, unit, forecast horizon), whether samples are irregular, and the value range of the colour scale. */
  label: string;
  unit: string;
  horizon: number;
  irregular: boolean;
  domainRange: readonly [number, number];
}

/** Ticks of a 0–1 scale in the current language ("0,25" / "0.25"). */
const ticks01 = (): string[] => [0, 0.25, 0.5, 0.75, 1].map((n) => numShort(n));

interface RuleLegendProps {
  view: RuleMapMetric;
  tau: number;
  scheme: TargetScheme | null;
  Nouns: string;
  withValue: number;
  total: number;
  /** `RuleMapDetail`: the Rule Duel shows the same detail under its own legend. */
  detail: ReactNode;
}

/** Rules mode, "Regla" view: the activation of one rule (E1). */
export function RuleLegend({ view, tau, scheme, Nouns, withValue, total, detail }: RuleLegendProps) {
  return (
    <Legend
      title={`${legendTitle(view, tau)}`}
      note={
        scheme
          ? tr("Grado de activación calculado por el motor del modelo. Muestra la activación de la regla elegida.", "Activation degree computed by the model's engine. This is the activation of the chosen rule.")
          : tr("Grado de activación calculado por el motor del modelo.", "Activation degree computed by the model's engine.")
      }
      stops={VIRIDIS}
      domain={ACTIVATION_DOMAIN}
      ticks={ticks01()}
      nValid={withValue}
      total={total}
      missingLabel={tr("sin dato (el motivo se indica en la tabla)", "no data (the reason is given in the table)")}
      countLabel={tr(`${Nouns} con algún registro válido`, `${Nouns} with at least one valid record`)}
      detail={detail}
    />
  );
}

/** The window line and the notes under a rule-map legend; the Rule Duel shows the same detail under its own legend. */
export function RuleMapDetail({
  view,
  window,
  irregular,
  nValids,
  noun,
  periodNote,
  noGeometryNote,
  absentNote,
}: {
  view: RuleMapMetric;
  window: TimeWindow | null;
  irregular: boolean;
  /** `n_valid` of every entity with a value. */
  nValids: number[];
  noun: { one: string; many: string };
  periodNote: ReactNode;
  noGeometryNote: ReactNode;
  absentNote: ReactNode;
}) {
  return (
    <>
      {view !== "firing_strength" && window && (
        <p className="legend-count">
          {irregular ? tr("Ventana de muestras", "Sample window") : tr("Ventana de emisión", "Issue window")} <code>[{window.from}, {window.to})</code>{" "}
          {tr(`(UTC, semiabierta, ${windowDays(window)} d).`, `(UTC, half-open, ${windowDays(window)} d).`)}{" "}
          {irregular ? tr(`Muestras válidas por ${noun.one}`, `Valid samples per ${noun.one}`) : tr(`Emisiones válidas por ${noun.one}`, `Valid issues per ${noun.one}`)}
          {nValids.length > 0 && tr(`: de ${Math.min(...nValids)} a ${Math.max(...nValids)}`, `: from ${Math.min(...nValids)} to ${Math.max(...nValids)}`)}.
        </p>
      )}
      {periodNote}
      {noGeometryNote}
      {absentNote}
    </>
  );
}

interface TerritoriesLegendProps extends Common {
  data: RuleTerritoriesResponse;
  rules: ModelRules["rules"];
  ruleId: string | null;
  focus: TerritoryFocus;
  measure: string;
  window: TimeWindow;
  /** Entities with a dominant rule. */
  withDominant: number;
  onSelect: (id: string) => void;
  colours?: ReadonlyMap<string, string> | null;
}

/** Rules mode, "Territorios" view: the dominant rule per entity, or the intensity of the chosen rule (E2). */
export function TerritoriesLegend(p: TerritoriesLegendProps) {
  const { data, rules, ruleId, focus, measure, window, noun, Nouns, withValue, total, periodNote, noGeometryNote, absentNote } = p;
  const present = dominanceCounts(data);
  const valid = data.features.flatMap((f) => (f.properties.missing_reason === "not_modelled" ? [] : [f.properties.n_valid]));
  if (focus !== "intensity") {
    return (
      <TerritoryLegend
        data={data}
        rules={rules}
        present={present}
        selectedRule={ruleId}
        onSelect={p.onSelect}
        colours={p.colours}
        focus={focus}
        window={window}
        withDominant={p.withDominant}
        total={total}
        nValid={valid.length > 0 ? [Math.min(...valid), Math.max(...valid)] : null}
        noun={noun}
        detail={
          <>
            {focus === "territory" && ruleId && (
              <p className="legend-count" data-testid="territory-focus-note">
                {tr(`Territorio resaltado: ${ruleId} domina en ${present.find((x) => x.ruleId === ruleId)?.count ?? 0} de ${total}. Las demás reglas se atenúan en gris claro, pero no desaparecen.`,
                  `Highlighted territory: ${ruleId} dominates in ${present.find((x) => x.ruleId === ruleId)?.count ?? 0} of ${total}. The other rules are dimmed to light grey but don't disappear.`,
                )}
              </p>
            )}
            {periodNote}
            {noGeometryNote}
            {absentNote}
          </>
        }
      />
    );
  }
  if (!ruleId) return null;
  return (
    <Legend
      title={tr(`Intensidad de ${ruleId}: ${measureName(measure)} (fracción 0–1)`, `Intensity of ${ruleId}: ${measureName(measure)} (fraction 0–1)`)}
      note={tr(`${measureThe(measure, true)} de la regla ${ruleId} en cada ${noun.one} durante la ventana elegida, calculada sobre sus registros válidos. Es un grado de activación de esa regla. La escala es secuencial y distinta de los colores de regla de los territorios.`, `The ${measureName(measure)} of rule ${ruleId} at each ${noun.one} over the chosen window, computed on its valid records. It's that rule's activation degree. The scale is sequential and separate from the territories' rule colours.`)}
      stops={VIRIDIS}
      domain={ACTIVATION_DOMAIN}
      ticks={ticks01()}
      nValid={withValue}
      total={total}
      missingLabel={tr("sin dato (sin registros válidos)", "no data (no valid records)")}
      countLabel={tr(`${Nouns} con valor para ${ruleId}`, `${Nouns} with a value for ${ruleId}`)}
      detail={
        <>
          <p className="legend-count">
            {tr(`Medida: ${measureName(measure)}`, `Measure: ${measureName(measure)}`)}
            {measure === "activation_frequency" && tr(` con τ = ${dec(data.tau, 2)}`, ` with τ = ${dec(data.tau, 2)}`)}; {tr("ventana", "window")} <code>[{window.from}, {window.to})</code>{" "}
            {tr("UTC. Las reglas se solapan, así que esta vista no las compara.", "UTC. Rules overlap, so this view doesn't compare them.")}
          </p>
          {noGeometryNote}
          {absentNote}
        </>
      }
    />
  );
}

interface PredictionLegendProps extends Common {
  scheme: TargetScheme | null;
  ui: DomainUi;
  relativeScheme: boolean;
  noReferenceCount: number;
}

/** Prediction mode: the predicted category (classifier) or the predicted value (regressor). */
export function PredictionLegend(p: PredictionLegendProps) {
  const { scheme, ui, relativeScheme, label, unit, horizon, irregular, domainRange, noun, Nouns, withValue, total, periodNote, noGeometryNote, absentNote } = p;
  if (scheme) {
    return (
      <CategoricalLegend
        title={ui.levelTitle && relativeScheme ? tr(`${ui.levelTitle.charAt(0).toUpperCase()}${ui.levelTitle.slice(1)} previsto`, `Predicted ${ui.levelTitle}`) : `${classTitle(scheme, label)} (${schemeQualifier(scheme)})`}
        note={
          ui.predictionNote && relativeScheme
            ? tr(`${ui.predictionNote} Categoría para la hora de validez (emisión + ${horizon} h).`, `${ui.predictionNote} Category for the valid time (issue + ${horizon} h).`)
            : tr(`Categoría que el modelo prevé para la hora de validez (emisión + ${horizon} h), según el esquema del modelo.`, `Category the model predicts for the valid time (issue + ${horizon} h), on the model's scheme.`)
        }
        scheme={scheme}
        nValid={withValue}
        total={total}
        missingLabel={tr("sin predicción (el motivo se indica en la tabla)", "no prediction (the reason is given in the table)")}
        countLabel={tr(`${Nouns} con categoría prevista`, `${Nouns} with a predicted category`)}
        detail={
          <>
            {relativeScheme && (
              <p className="legend-missing" data-testid="no-reference-legend">
                <span className="marker marker--noref" aria-hidden="true" />{" "}
                {tr(`sin referencia: ${articles(noun.one).el} ${noun.one} no tiene nivel de referencia a esa hora de la semana (tuvo poco volumen en el entrenamiento) y no se pinta como «normal» ni como clase`, `no reference: the ${noun.one} has no reference level at that hour of the week (too little volume in training), so it isn't painted as “normal” or as a class`)}
                {p.noReferenceCount > 0 && <>: <strong>{p.noReferenceCount}</strong> {tr("de", "of")} {total}</>}
              </p>
            )}
            {periodNote}
            {noGeometryNote}
            {absentNote}
          </>
        }
      />
    );
  }
  return (
    <Legend
      title={irregular ? tr(`${label} estimado en la última muestra (${unit})`, `Estimated ${label} at the last sample (${unit})`) : tr(`${label} previsto (${unit})`, `Predicted ${label} (${unit})`)}
      note={
        irregular
          ? tr(`Valor que el modelo completo estima para la última muestra de cada punto dentro de la ventana, a partir de las demás determinaciones de esa misma muestra. Es una ${sameSampleText()}. La fecha de la muestra está en la tabla y en la descripción emergente.`, `Value the full model estimates for each point's last sample in the window, from the other determinations of that same sample. This is ${sameSampleText()}. The sample's date is in the table and in the tooltip.`)
          : tr(`Concentración predicha por el modelo completo para la hora de validez (emisión + ${horizon} h).`, `Concentration predicted by the full model for the valid time (issue + ${horizon} h).`)
      }
      stops={MAGMA}
      domain={domainRange}
      ticks={[0, 0.25, 0.5, 0.75, 1].map((f) => String(Math.round(domainRange[0] + f * (domainRange[1] - domainRange[0]))))}
      nValid={withValue}
      total={total}
      missingLabel={irregular ? tr("sin muestra con predicción en la ventana (el motivo se indica en la tabla)", "no sample with a prediction in the window (the reason is given in the table)") : tr("sin predicción (el motivo se indica en la tabla)", "no prediction (the reason is given in the table)")}
      countLabel={irregular ? tr(`${Nouns} con muestra y predicción`, `${Nouns} with a sample and a prediction`) : tr(`${Nouns} con predicción`, `${Nouns} with a prediction`)}
      detail={
        <>
          <p className="legend-count">
            {irregular
              ? tr(`Escala 0–${domainRange[1]} ${unit}: se ajusta a las predicciones cargadas (la última muestra de cada punto en la ventana elegida) y solo crece al navegar.`, `Scale 0–${domainRange[1]} ${unit}: it fits the loaded predictions (the last sample of each point in the chosen window) and only grows while browsing.`)
              : tr(`Escala 0–${domainRange[1]} ${unit}: se ajusta a las predicciones cargadas (la hora de emisión elegida) y solo crece al navegar.`, `Scale 0–${domainRange[1]} ${unit}: it fits the loaded predictions (the chosen issue time) and only grows while browsing.`)}
          </p>
          {periodNote}
          {noGeometryNote}
          {absentNote}
        </>
      }
    />
  );
}

interface DataLegendProps extends Common {
  sqrt: boolean;
  /** The `/observations` answer in hand (its valid time is named in the note). */
  observations: ObservationsResponse | null;
  zone: string;
}

/** Data mode: the observed target as published. */
export function DataLegend({ label, unit, horizon, irregular, domainRange, sqrt, observations, zone, noun, Nouns, withValue, total, noGeometryNote, absentNote }: DataLegendProps) {
  const validAt = observations?.features.find((f) => f.properties.valid_at_utc)?.properties.valid_at_utc;
  const validTimeText = validAt ? formatInstant(validAt, zone) : null;
  return (
    <Legend
      title={tr(`${label} observado (${unit})`, `Observed ${label} (${unit})`)}
      note={
        irregular
          ? tr(`Última muestra medida de cada ${noun.one} dentro de la ventana, tal como se publicó, con su propia fecha (en la tabla y en la descripción emergente). Cada círculo es una lectura.`, `Each ${noun.one}'s last measured sample in the window, as published, with its own date (in the table and in the tooltip). Each circle is one reading.`)
          : tr(`Valor medido en la hora de validez (emisión + ${horizon} h)${validTimeText ? `: ${validTimeText}` : ""}, tal como se publicó. Cada ${noun.one} es una lectura.`, `Value measured at the valid time (issue + ${horizon} h)${validTimeText ? `: ${validTimeText}` : ""}, as published. Each ${noun.one} is one reading.`)
      }
      stops={BLUES}
      domain={domainRange}
      ticks={[0, 0.25, 0.5, 0.75, 1].map((f) => fmtNum(sqrt ? (f * Math.sqrt(domainRange[1])) ** 2 : f * domainRange[1]))}
      nValid={withValue}
      total={total}
      missingLabel={tr("sin observación (el motivo se indica en la tabla; no es 0)", "no observation (the reason is given in the table; not 0)")}
      countLabel={tr(`${Nouns} con observación`, `${Nouns} with an observation`)}
      detail={
        <>
          <p className="legend-count">
            {tr(`Escala de observaciones de 0 a ${domainRange[1]} ${unit}`, `Observation scale from 0 to ${domainRange[1]} ${unit}`)}
            {sqrt && tr(" (raíz cuadrada: las marcas de la barra están a 0, 6, 25, 56 y 100 % del recorrido en raíz)", " (square root: the bar's ticks sit at 0, 6, 25, 56 and 100% of the square-root range)")}
            {tr("; solo crece al navegar.", "; it only grows while browsing.")}
          </p>
          {noGeometryNote}
          {absentNote}
        </>
      }
    />
  );
}
