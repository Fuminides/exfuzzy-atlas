import { useState, type MouseEvent } from "react";
import { api } from "./api/client";
import type { DomainInfo, RuleStory, TaskInfo } from "./api/types";
import { ColourBySwitch, DecidedByLegend, type ColourBy } from "./components/DecidedByMap";
import { DataSidebar } from "./components/DataSidebar";
import { DuelControls } from "./components/DuelControls";
import { AbsentNote, NeverPredictedNote, NoGeometryNote, PeriodNote } from "./components/LegendNotes";
import { MapHeading } from "./components/MapHeading";
import { Naming } from "./components/Naming";
import { namesFor } from "./lib/labels";
import { DataLegend, PredictionLegend, RuleLegend, RuleMapDetail, TerritoriesLegend } from "./components/MapLegends";
import { MapStatus } from "./components/MapStatus";
import { ModeTable } from "./components/ModeTable";
import { ModelPanel } from "./components/ModelPanel";
import { PredictionSeries } from "./components/PredictionSeries";
import { PredictionWhatIf, WhatIfEntry } from "./components/PredictionWhatIf";
import { RuleDuel } from "./components/RuleDuel";
import { RuleInspector } from "./components/RuleInspector";
import { RuleLookupProvider } from "./components/RuleRef";
import { RuleStories } from "./components/RuleStories";
import { RulesControls } from "./components/RulesControls";
import { targetLabel } from "./components/SeriesChart";
import { StateMessage } from "./components/StateMessage";
import { Timeline } from "./components/Timeline";
import { WhatIfPanel } from "./components/WhatIfPanel";
import { WindowNavigator, type NavKind } from "./components/WindowNavigator";
import { useDataMode } from "./hooks/useDataMode";
import { useOptionalAsync } from "./hooks/useOptionalAsync";
import { useModelContext } from "./hooks/useModelContext";
import { useDefaultTime } from "./hooks/useDefaultTime";
import { firingScore, predictionScore } from "./hooks/defaultTimeScores";
import { usePredictionMode } from "./hooks/usePredictionMode";
import { useProvenance, type Provenance } from "./hooks/useProvenance";
import { useRuleDuel } from "./hooks/useRuleDuel";
import { useRuleStories } from "./hooks/useRuleStories";
import { useRulesMode } from "./hooks/useRulesMode";
import { useScenarioEntry } from "./hooks/useScenarioEntry";
import { isStaticData } from "./lib/dataMode";
import { useTerritories } from "./hooks/useTerritories";
import { useTimeWindow } from "./hooks/useTimeWindow";
import { scaleInObservedUnits } from "./lib/classifier";
import { domainUi } from "./lib/domainUi";
import { diffRows, duelEntries, withRuleMap } from "./lib/duel";
import { GOOD_COVERAGE, GOOD_FIRING, RULE_PROBE_HOURS } from "./lib/defaultTime";
import { entityRows } from "./lib/entityRows";
import { formatInstant, formatShortDate, sameInstant, unitLabel } from "./lib/format";
import { buildMapLayer } from "./lib/mapLayer";
import type { Mode } from "./lib/mode";
import { importancePeriod, neverPredictedIds, rankedRules } from "./lib/importance";
import { ruleColours } from "./lib/ruleColours";
import { legendTitle } from "./lib/ruleMapText";
import { stationTip } from "./lib/stationTip";
import { reproduceTarget } from "./lib/stories";
import { isMixture } from "./lib/mixture";
import { predictionRule } from "./lib/mixtureViews";
import { ZoneContext } from "./lib/zone";
import type { StationRow } from "./map/stations";
import { StationMap } from "./map/StationMap";
import { tr } from "./i18n";

export type { Mode, RulesView } from "./lib/mode";
export type { Provenance };

const BASEMAP: string | undefined = import.meta.env.VITE_BASEMAP_STYLE_URL || undefined;

interface Props {
  domain: DomainInfo;
  /** The selected task: the unit the user picks (a domain may serve several). */
  task: TaskInfo;
  mode: Mode;
  /** "Reproducir" a story moves the app to Rules mode. */
  onMode: (mode: Mode) => void;
  onDate: (label: string) => void;
  onProvenance: (p: Partial<Provenance>) => void;
  /** Prediction mode: "la decidió R04" links to the rule in Patrones. */
  onOpenRule?: (ruleId: string) => void;
  /** The entity selected on arrival (a station card of Patrones: «Ver su serie en Predicción», «Ver en Explorar»). */
  initialEntityId?: string | null;
}

/**
 * One task's workspace: the map, the side panel of the current mode and the timeline. It owns what the modes share
 * (the selected entity, the glue between sections) and composes the per-mode hooks, each of which owns its state and requests.
 */
export function Workspace({ domain, task: selectedTask, mode, onMode, onDate, onProvenance, onOpenRule, initialEntityId = null }: Props) {
  const { task, modelId, entities, card, rules, classifier, scheme, coverage, irregular, horizon, zone, unmodelledIds, modelRules, support } = useModelContext(domain, selectedTask);
  const ui = domainUi(domain.domain);
  // Contract v0.7: in a mixture of rules no rule decides; the views name the rule that adds the most to the predicted category.
  const mixture = rules.status === "ok" && isMixture(rules.data);
  const [entityId, setEntityId] = useState<string | null>(initialEntityId);
  const unmodelledSelected = entityId !== null && unmodelledIds.has(entityId);
  // Prediction mode can colour the map by the rule that decided each prediction; the colours follow the ranking of Patrones.
  const [colourBy, setColourBy] = useState<ColourBy>("prediction");

  // Static export: what it holds for this model (τ grid, window kinds, the τ of its stories). The controls offer nothing else.
  const timeWin = useTimeWindow({ coverage, irregular, zone, onDate, kinds: support?.windowKinds });
  const { setTimeIdx, setWindowKind, setAnchor, customWindow, setCustomWindow, times, time, kind, window, fetchTime, settling, staleInstant, answers } = timeWin;
  // The ranking of Patrones colours the rules everywhere (Predicción "regla que decidió", Explorar's territories) and
  // picks the rule Explorar opens on: the one that decides most, as the first card of Patrones.
  const importance = useOptionalAsync((s) => api.importance(modelId!, s), [modelId], (mode === "prediction" || mode === "rules") && modelId !== null);
  // undefined while the ranking loads; then its first rule, or the model's first rule when there is no ranking.
  const defaultRuleId: string | null | undefined =
    rules.status !== "ok" || importance.status === "loading" || importance.status === "idle"
      ? undefined
      : importance.status === "ok"
        ? (rankedRules(importance.data.rules)[0]?.rule_id ?? rules.data.rules[0]?.rule_id ?? null)
        : (rules.data.rules[0]?.rule_id ?? null);
  // Predicción opens at a weekday morning with good coverage; Explorar at a moment its opening rule fires in many
  // entities (not an empty-looking map); never over a time the user picked.
  const probeRule = mode === "rules" && !irregular && modelId !== null && defaultRuleId ? defaultRuleId : null;
  const choosingTime = useDefaultTime({
    enabled: !irregular && (mode === "prediction" || probeRule !== null),
    taskId: task?.task_id ?? "",
    score: mode === "prediction" ? predictionScore(task?.task_id ?? "") : firingScore(modelId ?? "", probeRule ?? ""),
    good: mode === "prediction" ? GOOD_COVERAGE : GOOD_FIRING,
    hours: mode === "prediction" ? undefined : RULE_PROBE_HOURS,
    times,
    zone,
    moved: timeWin.userMoved,
    pick: timeWin.pickDefault,
  });
  // Explorar draws nothing until its opening moment is chosen, so the map does not flash New Year's midnight first.
  const holdRulesTime = mode === "rules" && !irregular && (choosingTime || defaultRuleId === undefined);
  const rulesMode = useRulesMode({ mode, modelId, task, rules, irregular, coverage, classifier, entityId, unmodelledSelected, time: holdRulesTime ? { ...timeWin, fetchTime: null } : timeWin, defaultRuleId });
  const { ruleId, setRuleId, rulesView, setRulesView, view, setView, tau, setTau, emphasis, setEmphasis, setPickedSample, partitionFeature, setPartitionFeature } = rulesMode;
  const { ruleMap, windowSamples, samples, sample, traceAt, trace, observedPoint } = rulesMode;
  const { duel, setDuel, ruleB, setRuleB, duelView, setDuelView, ruleMapB } = useRuleDuel({ mapParams: rulesMode.mapParams, mapDeps: rulesMode.mapDeps, mapReady: rulesMode.mapReady, ruleId, modelRules });
  const { terrMeasure, setTerrMeasure, terrFocus, setTerrFocus, territories } = useTerritories({ mode, rulesView, modelId, window, tau, classifier, mixture });
  const storiesMode = useRuleStories({ mode, modelId, window, tau, storiesTau: support?.storiesTau });
  const { storiesOpen, setStoriesOpen, storiesWindow, setPinnedStoriesWindow, activeStory, setActiveStory, stories } = storiesMode;
  const { predictions, selectedSeriesState, pointSamples, scaleMax, windowMax } = usePredictionMode({ mode, task, irregular, coverage, entityId, unmodelledSelected, time, fetchTime: choosingTime ? null : fetchTime, window });
  const { observations, dataMax, observedMax } = useDataMode({ mode, task, irregular, fetchTime, window });
  const whatIf = useScenarioEntry({ mode, modelId, entityId, unmodelledSelected, irregular, fetchTime, staleInstant, predictions, answers, windowFrom: window?.from ?? null });
  useProvenance({ modelId, entities, card, rules, ruleMap, trace, predictions, observations, territories, scheme, onProvenance });

  // Static export, ¿Y si…?: a record without a sweep offers to go to the nearest instant that has one. A regular task's time
  // moves there; an irregular task has no instant to move, so that sample is the one traced.
  const goToInstant = (instant: string) => {
    if (!irregular) {
      const i = times.findIndex((t) => sameInstant(t, instant));
      if (i >= 0) setTimeIdx(i);
    } else if (mode === "rules") setPickedSample(instant);
    else whatIf.pick(instant);
  };

  const clearPins = () => {
    setCustomWindow(null);
    storiesMode.clearStoryPins();
  };

  if (modelId === null) {
    return <StateMessage kind="empty">{tr(<>La tarea {task?.task_id} todavía no tiene un modelo publicado.</>, <>Task {task?.task_id} has no published model yet.</>)}</StateMessage>;
  }
  if (entities.status === "error") {
    return (
      <StateMessage kind="error" onRetry={entities.reload}>
        {tr(<>No se pudieron cargar {ui.noun.many.startsWith("punto") ? "los" : "las"} {ui.noun.many}: {entities.error.message}</>, <>Could not load the {ui.noun.many}: {entities.error.message}</>)}
      </StateMessage>
    );
  }
  if (card.status === "error" || rules.status === "error") {
    const err = card.status === "error" ? card.error : rules.status === "error" ? rules.error : null;
    const retry = () => {
      card.reload();
      rules.reload();
    };
    return <StateMessage kind="error" onRetry={retry}>{tr(<>No se pudo cargar el modelo {modelId}: {err?.message}</>, <>Could not load model {modelId}: {err?.message}</>)}</StateMessage>;
  }
  if (entities.status !== "ok" || card.status !== "ok" || rules.status !== "ok") {
    return <StateMessage kind="loading">{tr(<>Cargando {ui.noun.many} y modelo…</>, <>Loading {ui.noun.many} and model…</>)}</StateMessage>;
  }
  if (!task || entities.data.features.length === 0) {
    return <StateMessage kind="empty">{isStaticData() ? tr(<>No hay {ui.noun.many} para esta tarea.</>, <>No {ui.noun.many} for this task.</>) : tr(<>La API no devolvió {ui.noun.many} para esta tarea.</>, <>The API returned no {ui.noun.many} for this task.</>)}</StateMessage>;
  }
  if (classifier && scheme === null) {
    return (
      <StateMessage kind="error">
        {tr(<>El modelo {modelId} es un clasificador pero no publica su esquema de categorías (<code>target_scheme</code>), y sin él no se puede dibujar.</>, <>Model {modelId} is a classifier but doesn't publish its category scheme (<code>target_scheme</code>), so it can't be drawn.</>)}
      </StateMessage>
    );
  }
  if (time === null || (!irregular && times.length === 0)) {
    return <StateMessage kind="empty">{tr("El modelo no declara cobertura temporal, así que no hay emisiones que explorar.", "The model declares no time coverage, so there are no issue times to explore.")}</StateMessage>;
  }
  if (choosingTime) return <StateMessage kind="loading">{tr("Buscando un momento con buena cobertura…", "Looking for a moment with good coverage…")}</StateMessage>;

  const noun = ui.noun;
  const Nouns = noun.many.charAt(0).toUpperCase() + noun.many.slice(1);
  const unit = unitLabel(task.unit);
  // "Sin referencia" exists only where the scheme is relative to a per-entity reference (NYC).
  const relativeScheme = scheme !== null && !scaleInObservedUnits(scheme, task.unit);
  const label = targetLabel(task.target);
  const { baseRows, nameOf } = entityRows(entities.data, unmodelledIds);
  const totalModelled = baseRows.length - unmodelledIds.size;

  const territoriesOn = mode === "rules" && rulesView === "territories";
  const territoriesNow = territoriesOn && territories.status === "ok" ? territories.data : null;
  const ruleMapNow = mode === "rules" && !territoriesOn && ruleMap.status === "ok" && !(view === "firing_strength" && settling) ? ruleMap.data : null;
  const predictionsNow = predictions.status === "ok" && !staleInstant && answers(predictions.data) ? predictions.data : null;
  const observationsNow = observations.status === "ok" && !staleInstant && answers(observations.data) ? observations.data : null;
  const dataSqrt = ui.dataScale === "sqrt";
  // "Regla que decidió" needs the ranking (importance, or the model's rule order while it is not published) and a deciding rule in the answer.
  const decidedAvailable = mode === "prediction" && importance.status !== "loading" && importance.status !== "error" && (predictionsNow?.features.some((f) => predictionRule(f.properties)) ?? false);
  const sharedColours =
    importance.status !== "loading" && importance.status !== "error"
      ? ruleColours((importance.status === "ok" ? rankedRules(importance.data.rules) : rules.data.rules).map((r) => r.rule_id))
      : null;
  const byRuleColours = decidedAvailable && colourBy === "rule" ? sharedColours : null;
  // Entities with no prediction at any time of the period: only meaningful where "sin referencia" and samples do not apply.
  const neverPredicted = mode === "prediction" && importance.status === "ok" && !relativeScheme && !irregular ? neverPredictedIds(importance.data, baseRows.filter((r) => r.missingReason !== "not_modelled").map((r) => r.entityId)) : undefined;
  const { rows, mapRows, layerOptions, domainRange } = buildMapLayer({
    mode, baseRows, entityId, rules: rules.data.rules, ruleId, scheme, relativeScheme, irregular, ruleMapNow, territoriesNow, predictionsNow, observationsNow,
    emphasis, terrFocus, scaleMax, windowMax, dataMax, observedMax, dataSqrt, neverPredicted, ruleColours: territoriesOn ? sharedColours : byRuleColours,
  });
  const observationOf = (id: string | null) =>
    id !== null && observations.status === "ok" ? (observations.data.features.find((f) => f.properties.entity_id === id)?.properties ?? null) : null;
  const territoryOf = (id: string) => (territories.status === "ok" ? territories.data.features.find((f) => f.properties.entity_id === id)?.properties : undefined);

  const withValue = rows.filter((r) => r.value !== null || (r.label ?? null) !== null).length;
  const noReferenceCount = rows.filter((r) => r.noReference).length;
  const valuesShown = layerOptions.kind !== "neutral";
  // Rule Duel: both maps arrive for the same parameters before anything is drawn or compared.
  const duelOn = mode === "rules" && rulesView === "rule" && duel && ruleB !== null;
  const duelReady = duelOn && ruleMap.status === "ok" && ruleMapB.status === "ok" && !(view === "firing_strength" && settling);
  const ruleDefA = rules.data.rules.find((r) => r.rule_id === ruleId);
  const ruleDefB = rules.data.rules.find((r) => r.rule_id === ruleB);
  const rowsB = duelReady && ruleMapB.status === "ok" ? withRuleMap(baseRows, ruleMapB.data) : baseRows;
  const entries = duelReady ? duelEntries(rows, rowsB) : [];
  const duelRows = duelReady ? { a: rows, b: rowsB, diff: diffRows(rows, entries) } : { a: baseRows, b: baseRows, diff: baseRows };
  const noGeometry = rows.filter((r) => r.geometry === null).length;
  const nValids = rows.flatMap((r) => (r.nValid === null || r.missingReason === "not_modelled" ? [] : [r.nValid]));
  const selectRule = (id: string) => {
    // Picking the rule that is B makes it A, and the old A becomes B (the two rules are never the same).
    if (duel && id === ruleB && ruleId !== null) setRuleB(ruleId);
    setRuleId(id);
    const first = rules.data.rules.find((r) => r.rule_id === id)?.antecedents[0]?.feature;
    if (first) setPartitionFeature(first);
  };
  // A rule picked in the territories legend focuses its territory (unless the user already chose the intensity view).
  const selectTerritoryRule = (id: string) => {
    selectRule(id);
    if (terrFocus === "all") setTerrFocus("territory");
  };
  // "Reproducir": the app goes to the exact request of the story (rule, metric, time or window, tau).
  const reproduce = (story: RuleStory, queryIndex: number) => {
    const target = reproduceTarget(story.queries[queryIndex] ?? story.queries[0]!);
    if (target === null) return;
    setPinnedStoriesWindow(storiesWindow);
    setActiveStory(story.story_id);
    onMode("rules");
    setDuel(false);
    if (target.tau !== null) setTau(target.tau);
    if (target.view === "territories") {
      setRulesView("territories");
      setTerrMeasure(target.measure);
      setCustomWindow({ from: target.from, to: target.to });
      setRuleId(story.rule_id);
      setTerrFocus("territory");
      return;
    }
    setRulesView("rule");
    setRuleId(target.ruleId);
    setView(target.metric);
    if (target.metric === "firing_strength" && target.time !== null) {
      const i = times.findIndex((t) => sameInstant(t, target.time));
      if (i >= 0) setTimeIdx(i);
      setCustomWindow(null);
    } else if (target.from !== null && target.to !== null) {
      setCustomWindow({ from: target.from, to: target.to });
    }
  };
  const sampleDate = (iso: string) => formatInstant(iso, zone);
  const rowById = new Map(rows.map((r) => [r.entityId, r]));
  // The tooltip is about the entity, whatever the map colours it by: it reads the table's row, not the map's recoloured one.
  const tipText = (m: StationRow) =>
    stationTip(rowById.get(m.entityId) ?? m, { mode, scheme, className: scheme ? namesFor([], scheme).cls : undefined, mixture, noun: noun.one, unit, zone, territoriesOn, terrMeasure, terrFocus, ruleId, territoryOf, observationOf: (id) => observationOf(id) });

  // An aggregate (territories, mean or frequency) spans a window, not one issue time.
  const aggregate = irregular || (mode === "rules" && (territoriesOn || view !== "firing_strength"));
  const periodNote = <PeriodNote window={window} aggregate={aggregate} time={time} split={card.data.manifest.split} />;
  const noGeometryNote = <NoGeometryNote count={noGeometry} />;
  const absentNote = (
    <>
      <AbsentNote absent={unmodelledIds.size} modelled={totalModelled} total={baseRows.length} noun={noun.many} extra={ui.absentNote} />
      {importance.status === "ok" && <NeverPredictedNote count={rows.filter((r) => r.noPredictions).length} noun={noun} period={importancePeriod(importance.data, zone)} />}
    </>
  );
  const rulesLegendDetail = <RuleMapDetail {...{ view, window, irregular, nValids, noun, periodNote, noGeometryNote, absentNote }} />;
  const common = { noun, Nouns, withValue, total: totalModelled, periodNote, noGeometryNote, absentNote, label, unit, horizon, irregular, domainRange };
  // Exactly one legend at a time: the rule's, the territories', the prediction's or the observations'.
  const legend =
    mode === "rules" && !territoriesOn && valuesShown && !duelOn ? (
      <RuleLegend view={view} tau={tau} scheme={scheme} Nouns={Nouns} withValue={withValue} total={totalModelled} detail={rulesLegendDetail} />
    ) : territoriesNow && (terrFocus !== "intensity" || ruleId) ? (
      <TerritoriesLegend
        {...common}
        data={territoriesNow}
        rules={rules.data.rules}
        ruleId={ruleId}
        focus={terrFocus}
        measure={terrMeasure}
        window={window!}
        colours={sharedColours}
        withDominant={rows.filter((r) => r.label).length}
        onSelect={selectTerritoryRule}
      />
    ) : byRuleColours ? (
      <DecidedByLegend
        colours={byRuleColours}
        decidedBy={rows.map((r) => r.decidedBy)}
        mixture={mixture}
        noun={noun}
        total={totalModelled}
        onOpenRule={onOpenRule}
        detail={
          <>
            {periodNote}
            {noGeometryNote}
            {absentNote}
          </>
        }
      />
    ) : mode === "prediction" && valuesShown ? (
      <PredictionLegend {...common} scheme={scheme} ui={ui} relativeScheme={relativeScheme} noReferenceCount={noReferenceCount} />
    ) : mode === "data" && valuesShown ? (
      <DataLegend {...common} sqrt={dataSqrt} observations={observations.status === "ok" ? observations.data : null} zone={zone} />
    ) : null;

  // Predicción puts the time controls above the map (the map is tall: below it they would be off screen).
  const timelineFirst = mode === "prediction";
  // Below the map (Explorar), the time controls come after every button of the entity table in the Tab order
  // (437 in Germany): a skip link, visible only on focus, goes straight to them (docs/qa A11Y-2).
  const focusTimeline = (e: MouseEvent<HTMLButtonElement>) =>
    e.currentTarget
      .closest(".workspace")
      ?.querySelector<HTMLElement>(".timeline-col input:not(:disabled), .timeline-col select:not(:disabled), .timeline-col button:not(:disabled)")
      ?.focus();
  const timeline = (
    <div className="timeline-col">
      {irregular && coverage && window ? (
        <WindowNavigator
          kind={(kind === "coverage" ? "month" : kind) as NavKind}
          window={window}
          coverage={coverage}
          kinds={support?.windowKinds}
          onKind={(k) => {
            setWindowKind(k);
            setPickedSample(null);
            clearPins();
          }}
          onAnchor={(iso) => {
            setAnchor(iso);
            setPickedSample(null);
            clearPins();
          }}
        />
      ) : (
        <Timeline
          times={times}
          index={timeWin.timeIdx}
          onIndex={(i) => {
            setTimeIdx(Math.min(times.length - 1, Math.max(0, i)));
            clearPins();
          }}
          horizonHours={horizon}
          stepHours={coverage?.step_hours ?? 1}
        />
      )}
    </div>
  );

  return (
    <ZoneContext.Provider value={zone}>
    <Naming variables={rules.data.variables} scheme={scheme} target={task?.target ?? selectedTask.target}>
    <RuleLookupProvider model={rules.data} importance={importance.status === "ok" ? importance.data : null} scheme={scheme} unit={unit} colourWithoutRanking={sharedColours !== null && importance.status !== "ok"}>
    <div className="workspace" data-domain={domain.domain} data-task={selectedTask.task_id} data-irregular={irregular ? "true" : undefined}>
      {timelineFirst ? timeline : (
        <button type="button" className="skip-link" onClick={focusTimeline}>
          {tr("Ir a la línea temporal", "Skip to the timeline")}
        </button>
      )}
      <section className="map-col" aria-label={tr("Mapa", "Map")}>
        <MapHeading
          mode={mode} noun={noun} irregular={irregular} label={label} unit={unit} horizon={horizon}
          territoriesOn={territoriesOn} duelOn={!!duelOn} ruleId={ruleId} ruleB={ruleB} view={view} tau={tau} terrFocus={terrFocus} terrMeasure={terrMeasure}
          scheme={scheme} ui={ui} relativeScheme={relativeScheme} selectedName={entityId ? nameOf(entityId) : null} byRule={byRuleColours !== null} mixture={mixture}
        />
        {decidedAvailable && <ColourBySwitch value={colourBy} onChange={setColourBy} regression={!classifier} mixture={mixture} />}
        {duelOn && ruleDefA && ruleDefB ? (
          <RuleDuel
            view={duelView}
            ruleA={ruleDefA}
            ruleB={ruleDefB}
            entries={entries}
            rowsA={duelRows.a}
            rowsB={duelRows.b}
            rowsDiff={duelRows.diff}
            layerOptions={duelReady ? layerOptions : { ...layerOptions, kind: "neutral", emphasis: null }}
            ready={duelReady}
            onSelect={setEntityId}
            basemapUrl={BASEMAP}
            noun={noun}
            measureTitle={legendTitle(view, tau)}
            detail={rulesLegendDetail}
            scheme={scheme}
          />
        ) : (
          <StationMap
            rows={mapRows}
            layerOptions={layerOptions}
            onSelect={setEntityId}
            basemapUrl={BASEMAP}
            tipText={tipText}
            plural={noun.many}
          />
        )}
        <MapStatus
          mode={mode} territoriesOn={territoriesOn} duelOn={!!duelOn} instantSettling={view === "firing_strength" && settling} staleInstant={staleInstant}
          ruleMap={ruleMap} ruleMapB={ruleMapB} territories={territories} predictions={predictions} observations={observations}
        />
        {legend && <div className="map-legend">{legend}</div>}
      </section>

      <aside className="rail" aria-label={tr("Panel lateral", "Side panel")}>
        {mode === "data" && (
          <DataSidebar
            noun={noun}
            irregular={irregular}
            label={label}
            window={window}
            observationsStatus={observations.status}
            entityId={entityId}
            entityName={entityId ? nameOf(entityId) : null}
            unmodelled={unmodelledSelected}
            observation={observationOf(entityId)}
          />
        )}

        {mode === "rules" && (
          <>
            {coverage && window && (
              <RulesControls
                noun={noun.one}
                irregular={irregular}
                classifier={classifier}
                mixture={mixture}
                coverage={coverage}
                window={window}
                rulesView={rulesView}
                onRulesView={setRulesView}
                view={view}
                onView={setView}
                ruleId={ruleId}
                tau={tau}
                onTau={setTau}
                emphasis={emphasis}
                onEmphasis={setEmphasis}
                terrMeasure={terrMeasure}
                onTerrMeasure={setTerrMeasure}
                terrFocus={terrFocus}
                onTerrFocus={setTerrFocus}
                kind={kind}
                onKind={setWindowKind}
                customWindow={customWindow}
                onClearPins={clearPins}
                taus={support?.taus}
                kinds={support?.windowKinds}
              />
            )}
            <RuleStories
              open={storiesOpen}
              onToggle={() => setStoriesOpen((o) => !o)}
              state={stories}
              onReproduce={reproduce}
              activeStory={activeStory}
            />
            {rulesView === "rule" && (
            <DuelControls
              on={duel}
              onToggle={setDuel}
              rules={rules.data.rules}
              modelId={modelId}
              ruleA={ruleId}
              ruleB={ruleB}
              onRuleA={selectRule}
              onRuleB={setRuleB}
              onSwap={() => {
                if (ruleId !== null && ruleB !== null) {
                  setRuleB(ruleId);
                  setRuleId(ruleB);
                }
              }}
              view={duelView}
              onView={setDuelView}
            />
            )}
            <RuleInspector
              rules={rules.data}
              ruleId={ruleId}
              onSelectRule={selectRule}
              scheme={scheme}
              relativeScheme={relativeScheme}
              partitionFeature={partitionFeature}
              onPartitionFeature={setPartitionFeature}
              noun={noun.one}
              entityId={entityId}
              entityName={entityId ? nameOf(entityId) : null}
              unmodelled={unmodelledSelected}
              trace={trace}
              staleInstant={staleInstant}
              observed={observedPoint ? { value: observedPoint.observed, label: observedPoint.observed_label ?? null } : null}
              irregular={irregular}
              window={window}
              samples={samples}
              samplesLoading={windowSamples.status === "loading"}
              sample={sample}
              onPickSample={setPickedSample}
              unit={task.unit}
            />
            {entityId && !unmodelledSelected && traceAt !== null && !(irregular && sample === undefined) && !(settling && !irregular) && (
              <WhatIfPanel
                key={`${modelId}|${entityId}|${traceAt}`}
                modelId={modelId}
                entityId={entityId}
                entityName={nameOf(entityId)}
                at={traceAt}
                variables={rules.data.variables}
                baseline={trace.status === "ok" && trace.data.entity_id === entityId && sameInstant(trace.data.issued_at_utc, traceAt) ? trace.data : null}
                classifier={classifier}
                mixture={mixture}
                onGoTo={goToInstant}
                within={irregular ? window : null}
              />
            )}
          </>
        )}

        {mode === "prediction" && whatIf.open && whatIf.at !== null && entityId && (
          <PredictionWhatIf
            modelId={modelId}
            entityId={entityId}
            entityName={nameOf(entityId)}
            at={whatIf.at}
            variables={rules.data.variables}
            trace={whatIf.trace}
            classifier={classifier}
            mixture={mixture}
            scheme={scheme}
            relativeScheme={relativeScheme}
            ui={ui}
            label={label}
            unit={unit}
            irregular={irregular}
            onClose={whatIf.close}
            onGoTo={goToInstant}
            within={irregular ? window : null}
          />
        )}
        {mode === "prediction" && !whatIf.open && (
          <PredictionSeries
            irregular={irregular}
            scheme={scheme}
            label={label}
            unit={unit}
            noun={noun.one}
            entityId={entityId}
            nameOf={nameOf}
            unmodelled={unmodelledSelected}
            predictions={predictions}
            selectedSeriesState={selectedSeriesState}
            pointSamples={pointSamples}
            time={time}
            window={window}
            whatIfEntry={whatIf.at !== null && whatIf.available ? <WhatIfEntry onOpen={whatIf.openWhatIf} /> : null}
            decidedBy={entityId ? (rows.find((r) => r.entityId === entityId)?.decidedBy ?? null) : null}
            rules={rules.data.rules}
            unweighted={rules.data.inference.rule_weighting === "none"}
            mixture={mixture}
            topShare={entityId ? (rows.find((r) => r.entityId === entityId)?.topShare ?? null) : null}
            predictedLabel={entityId ? (rows.find((r) => r.entityId === entityId)?.label ?? null) : null}
            onOpenRule={onOpenRule}
          />
        )}

        {mode === "prediction" && <ModelPanel card={card.data} unit={unit} brief />}

        <section aria-label={tr(`Tabla de ${noun.many}`, `Table of ${noun.many}`)}>
          <ModeTable
            mode={mode}
            noun={noun}
            unit={unit}
            irregular={irregular}
            scheme={scheme}
            rows={rows}
            layerOptions={layerOptions}
            domainRange={domainRange}
            entityId={entityId}
            onSelect={setEntityId}
            rules={rules.data.rules}
            onOpenRule={onOpenRule}
            mixture={mixture}
            dataSqrt={dataSqrt}
            sampleDate={sampleDate}
            sampleDay={(iso) => formatShortDate(iso, zone)}
            observationOf={observationOf}
            territoryOf={territoryOf}
            territoriesOn={territoriesOn}
            terrFocus={terrFocus}
            terrMeasure={terrMeasure}
            ruleId={ruleId}
            ruleColours={sharedColours}
            duel={duelOn && ruleDefA && ruleDefB ? { ready: duelReady, entries, ruleA: ruleDefA, ruleB: ruleDefB } : null}
          />
        </section>

        {mode === "rules" && <ModelPanel card={card.data} unit={scheme ? undefined : unit} />}
      </aside>

      {!timelineFirst && timeline}
    </div>
    </RuleLookupProvider>
    </Naming>
    </ZoneContext.Provider>
  );
}
