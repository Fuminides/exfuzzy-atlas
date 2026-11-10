import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { DomainInfo, RuleImportance, TaskInfo } from "../api/types";
import { Card, MoreInfo, NotYet, PageHead } from "../components/Card";
import { DataLine } from "../components/DataLine";
import { ModelExplanationCard } from "../components/ModelExplanationCard";
import { RuleCard } from "../components/RuleCard";
import { RuleMatrix } from "../components/RuleMatrix";
import { RuleLookupProvider, RuleRef } from "../components/RuleRef";
import { Chips } from "../components/ui/Chips";
import { Hero } from "../components/ui/Hero";
import { KpiTiles, type Kpi } from "../components/ui/KpiTiles";
import { StateMessage } from "../components/StateMessage";
import { Naming } from "../components/Naming";
import { VariableBars } from "../components/VariableBars";
import type { ScoreState } from "../components/StationCard";
import { ZonesSection } from "../components/ZonesSection";
import { useAsync } from "../hooks/useAsync";
import { useOptionalAsync } from "../hooks/useOptionalAsync";
import { tr, useLang } from "../i18n";
import type { Provenance } from "../hooks/useProvenance";
import { isClassifier, schemeOf } from "../lib/classifier";
import { domainUi, articles } from "../lib/domainUi";
import { dec, pct, unitLabel } from "../lib/format";
import { baseRate, decideText, importancePeriod, isRegressionImportance, noRuleShare, rankedRules, withheldOf, withheldShare } from "../lib/importance";
import { isMixture, leadShare, measuredNote, topRuleLabel, topRulesLabel, variableShareNote, weightScale } from "../lib/mixture";
import { labelerFor } from "../lib/labels";
import { entityScore, modelSize } from "../lib/performance";
import { MAX_RULE_COLOURS } from "../lib/ruleColours";
import { classShare } from "../lib/summary";
import { horizonClause, predictsText } from "../lib/taskText";

interface Props {
  domain: DomainInfo;
  task: TaskInfo;
  /** "Alemania": the hero's eyebrow names it. */
  territoryTitle: string;
  onProvenance: (p: Partial<Provenance>) => void;
  /** Takes the user to Resumen (the data line links to it). */
  onOpenSummary?: () => void;
  /** A rule to open selected (the link "ver la regla" of Predicción): it is picked on the map and scrolled to. */
  focusRule?: string | null;
  /** «Ver su serie en Predicción» on a station card: opens Predicción with that entity selected. */
  onOpenPrediction?: (entityId: string) => void;
  /** «Ver en Explorar» on a station card. */
  onOpenExplore?: (entityId: string) => void;
}

const FIRST = 8;
/** With the importance published, the cards shown first are the rules that decide at least this share; the rest fold. */
const MINOR_SHARE = 0.01;

/**
 * Patrones: the rules the model uses, written as sentences, how many predictions each decides and how often it is right
 * when it decides, overall and by zone. Importance here is "decides and hits" (CONTRACTS.md §12.3), never an activation.
 */
export function PatternsTab({ domain, task, territoryTitle, onProvenance, onOpenSummary, focusRule = null, onOpenPrediction, onOpenExplore }: Props) {
  const modelId = task.model_id ?? null;
  const rules = useAsync((s) => api.modelRules(modelId!, s), [modelId], modelId !== null);
  const importance = useOptionalAsync((s) => api.importance(modelId!, s), [modelId], modelId !== null);
  const entities = useAsync((s) => api.entities(domain.domain, task.task_id, s), [domain.domain, task.task_id]);
  const summary = useOptionalAsync((s) => api.summary(task.task_id, s), [task.task_id]);
  const [zoneRule, setZoneRule] = useState<string | null>(focusRule);
  const [zoneEntity, setZoneEntity] = useState<string | null>(null);
  // The model card (megabytes for Germany) only feeds the station card's per-entity score: fetched on the first click.
  const [wantCard, setWantCard] = useState(false);
  const card = useOptionalAsync((s) => api.modelCard(modelId!, s), [modelId], modelId !== null && wantCard);
  const openEntity = useCallback((id: string | null) => {
    setZoneEntity(id);
    if (id) setWantCard(true);
  }, []);
  const [showAll, setShowAll] = useState(false);
  const rulesData = rules.status === "ok" ? rules.data : null;
  const { lang } = useLang();
  const label = useMemo(() => labelerFor(rulesData?.variables ?? []), [rulesData, lang]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!rulesData || !focusRule) return;
    setShowAll(true);
    const t = window.setTimeout(() => document.querySelector(`.rule-card[data-rule="${focusRule}"]`)?.scrollIntoView?.({ block: "center" }), 50);
    return () => window.clearTimeout(t);
  }, [rulesData, focusRule]);
  useEffect(() => {
    if (rulesData) onProvenance({ modelId: rulesData.model_id, dataVersion: rulesData.data_version, synthetic: rulesData.synthetic === true });
  }, [rulesData, onProvenance]);

  if (modelId === null) return <StateMessage kind="empty">{tr(`La tarea ${task.task_id} todavía no tiene un modelo publicado.`, `Task ${task.task_id} has no published model yet.`)}</StateMessage>;
  if (rules.status === "error")
    return (
      <StateMessage kind="error" onRetry={rules.reload}>
        {tr("No se pudieron cargar las reglas: ", "Could not load the rules: ")}
        {rules.error.message}
      </StateMessage>
    );
  if (rules.status !== "ok") return <StateMessage kind="loading">{tr("Cargando las reglas del modelo…", "Loading the model's rules…")}</StateMessage>;

  const model = rules.data;
  const classifier = isClassifier(task, model);
  const scheme = classifier ? schemeOf(null, model) : null;
  const imp = importance.status === "ok" ? importance.data : null;
  const regression = imp ? isRegressionImportance(imp) : !classifier;
  // contract v0.7: a mixture of rules, where no rule decides alone (the figures are the top-rule shares)
  const mixture = isMixture(model);
  const unit = unitLabel(task.unit);
  const noun = domainUi(domain.domain).noun;
  const g = articles(noun.one);
  const byId = new Map<string, RuleImportance>((imp?.rules ?? []).map((r) => [r.rule_id, r]));
  const ranked = imp ? rankedRules(imp.rules).map((r) => r.rule_id) : model.rules.map((r) => r.rule_id);
  const order = ranked.flatMap((id) => model.rules.filter((r) => r.rule_id === id));
  // A few rules decide most predictions (Madrid: 3 of 15 decide 66 %): show those that do the work, fold the tail.
  const nMain = imp ? Math.max(1, order.filter((r) => leadShare(byId.get(r.rule_id) ?? {}) >= MINOR_SHARE).length) : FIRST;
  const visible = showAll ? order : order.slice(0, nMain);
  const nHidden = order.length - nMain;
  const predicts = predictsText(task, scheme);
  const noRule = imp ? noRuleShare(imp) : null;
  const withheld = imp && withheldOf(imp) > 0 ? withheldShare(imp) : null;
  const n = model.rules.length;
  const scale = mixture ? weightScale(model.rules) : 0;
  const horizon = horizonClause(task.horizon_hours);
  const size = modelSize(model);
  const ranking = imp ? rankedRules(imp.rules) : [];
  const top = ranking[0] && leadShare(ranking[0]) > 0 ? ranking[0] : null;
  // the rules with a colour of their own on the map, as chips that show the rule on hover
  const leaders = ranking.slice(0, MAX_RULE_COLOURS).filter((r) => leadShare(r) > 0);
  const topText = top ? decideText(top, regression, unit) : null;
  const kpis: Kpi[] = [
    { key: "size", accent: true, label: tr("Modelo completo", "Whole model"), value: size.rules, unit: tr("reglas", "rules"), note: tr(`${dec(size.meanConditions, 1)} condiciones de media`, `${dec(size.meanConditions, 1)} conditions on average`) },
    ...(top && topText
      ? [{ key: "top", label: mixture ? topRuleLabel() : tr("La regla que más decide", "The rule that decides most"), value: pct(leadShare(top)), note: <><RuleRef id={top.rule_id} />{mixture ? (top.accuracy != null ? tr(` · esas predicciones aciertan el ${pct(top.accuracy)}`, ` · those predictions are right ${pct(top.accuracy)} of the time`) : "") : topText.outcome ? ` · ${topText.outcome}` : ""}</> }]
      : []),
    ...(noRule !== null && noRule >= 0.005
      ? [{ key: "no-rule", label: tr("No dispara ninguna regla", "No rule fires"), value: pct(noRule), note: tr("de las horas con todos los datos de entrada", "of the hours with complete input data") }]
      : []),
  ];

  return (
    <Naming variables={model.variables} scheme={scheme} target={task.target}>
      <RuleLookupProvider model={model} importance={imp} scheme={scheme} unit={unit}>
      <div className="page page--wide" data-task={task.task_id}>
        <PageHead title={tr("Patrones: las reglas del modelo", "Patterns: the model's rules")}>
          {tr(
            <>
              Las <strong>{n} reglas</strong> que usa el modelo para {regression ? "estimar" : "prever"} {predicts} {horizon}
            </>,
            <>
              The <strong>{n} rules</strong> the model uses to {regression ? "estimate" : "predict"} {predicts} {horizon}
            </>,
          )}
          {imp && mixture
            ? tr(`, ordenadas por en cuántas predicciones de ${importancePeriod(imp)} son la que más suma a la categoría prevista. Ninguna regla decide sola: las que se cumplen suman su apoyo a cada categoría. Elige una regla para verla en el mapa.`, `, ordered by how many predictions in ${importancePeriod(imp)} they add the most to the predicted category. No rule decides alone: the rules that hold add up their support for each category. Pick a rule to see it on the map.`)
            : imp
            ? tr(`, ordenadas por cuántas predicciones deciden en ${importancePeriod(imp)}. Elige una regla para ver en el mapa dónde decide.`, `, ordered by how many predictions they decide in ${importancePeriod(imp)}. Pick a rule to see where it decides on the map.`)
            : mixture
            ? tr(". Ninguna regla decide sola: las que se cumplen suman su apoyo a cada categoría.", ". No rule decides alone: the rules that hold add up their support for each category.")
            : "."}
        </PageHead>

        <Hero
          label={tr("Las reglas en cifras", "The rules in figures")}
          eyebrow={`${territoryTitle} · ${task.horizon_hours > 0 ? `+${task.horizon_hours} h` : tr("misma muestra", "same sample")}${imp ? ` · ${importancePeriod(imp)}` : ""}`}
          aside={<KpiTiles items={kpis} row />}
        >
          {leaders.length > 0 && (
            <Chips
              label={mixture ? topRulesLabel() : tr("Las reglas que más deciden", "The rules that decide most")}
              testId="hero-leaders"
              items={leaders.map((r) => ({ key: r.rule_id, content: <><RuleRef id={r.rule_id} /><span className="chip-value">{pct(leadShare(r))}</span></> }))}
            />
          )}
        </Hero>

        {summary.status === "ok" && <DataLine summary={summary.data} noun={noun} onOpenSummary={onOpenSummary} />}

        {importance.status === "loading" && <StateMessage kind="loading">{mixture ? tr("Cargando las cifras de las reglas…", "Loading the rules' figures…") : tr("Calculando qué reglas deciden más…", "Working out which rules decide most…")}</StateMessage>}
        {importance.status === "error" && (
          <StateMessage kind="error" onRetry={importance.reload}>
            {mixture ? tr("No se pudieron cargar las cifras de las reglas: ", "Could not load the rules' figures: ") : tr("No se pudo cargar cuánto deciden y aciertan las reglas: ", "Could not load how much the rules decide and how often they are right: ")}
            {importance.error.message}
          </StateMessage>
        )}
        {importance.status === "unavailable" && (
          <NotYet what={mixture ? tr("Las cifras de las reglas", "The rules' figures") : tr("Cuánto deciden y aciertan las reglas", "How much the rules decide and how often they are right")}>
            {tr("Se calcula al publicar el modelo, y este todavía no lo tiene. Abajo están las reglas, sin cifras.", "It's computed when the model is published, and this one doesn't have it yet. The rules are below, without figures.")}
          </NotYet>
        )}

        <div className="patterns-grid">
          <div className="patterns-main">
            <RuleMatrix
              model={model}
              importance={imp}
              scheme={scheme}
              regression={regression}
              unit={unit}
              selected={zoneRule}
              onSelect={(id) => setZoneRule((old) => (old === id ? null : id))}
              showAll={showAll}
              onToggleAll={() => setShowAll((s) => !s)}
            />
            <ModelExplanationCard modelId={modelId} />
            <Card
              title={tr("Las reglas", "The rules")}
              subtitle={
                imp && mixture
                  ? tr("De la que en más predicciones es la que más suma a la que en menos. Debajo de cada una, su peso centrado para cada categoría. Pulsa una para verla en el mapa.", "From the one that adds the most in most predictions to the one that does in fewest. Under each, its centred weight for each category. Click one to see it on the map.")
                  : imp
                  ? tr("De la que decide más predicciones a la que decide menos. Pulsa una para verla en el mapa.", "From the one that decides most predictions to the one that decides fewest. Click one to see it on the map.")
                  : tr("En el orden del modelo.", "In the model's order.")
              }
            >
              <ol className="rule-cards">
                {visible.map((r) => (
                  <RuleCard
                    key={r.rule_id}
                    rule={r}
                    importance={byId.get(r.rule_id) ?? null}
                    regression={regression}
                    unit={unit}
                    scheme={scheme}
                    variables={model.variables}
                    rank={imp ? order.indexOf(r) + 1 : null}
                    weightScale={mixture ? scale : undefined}
                    baseRate={classifier && !mixture && r.consequent.type === "class" && r.consequent.term ? baseRate(imp, summary.status === "ok" ? classShare(summary.data, r.consequent.term) : null, r.consequent.term) : null}
                    selected={zoneRule === r.rule_id}
                    onSelect={(id) => setZoneRule((old) => (old === id ? null : id))}
                  />
                ))}
              </ol>
              {nHidden > 0 && (
                <button type="button" className="btn" onClick={() => setShowAll((s) => !s)}>
                  {showAll
                    ? tr(`Mostrar solo las ${nMain} primeras`, `Show only the first ${nMain}`)
                    : imp && mixture
                      ? nHidden === 1
                        ? tr("Mostrar 1 regla más (es la que más suma en menos del 1 % de las predicciones)", "Show 1 more rule (it adds the most in less than 1% of the predictions)")
                        : tr(`Mostrar ${nHidden} reglas más (cada una es la que más suma en menos del 1 % de las predicciones)`, `Show ${nHidden} more rules (each adds the most in less than 1% of the predictions)`)
                    : imp
                      ? nHidden === 1
                        ? tr("Mostrar 1 regla más (decide menos del 1 % de las predicciones)", "Show 1 more rule (it decides less than 1% of the predictions)")
                        : tr(`Mostrar ${nHidden} reglas más (cada una decide menos del 1 % de las predicciones)`, `Show ${nHidden} more rules (each decides less than 1% of the predictions)`)
                      : tr(`Mostrar las ${order.length} reglas`, `Show all ${order.length} rules`)}
                </button>
              )}
            </Card>
          </div>
          <aside className="patterns-aside" aria-label={tr("Mapa y variables", "Map and variables")}>
            {imp && entities.status === "ok" ? (
              <ZonesSection
                entities={entities.data}
                rules={model}
                importance={imp}
                scheme={scheme}
                unit={unit}
                noun={noun}
                ruleId={zoneRule}
                onRule={setZoneRule}
                entityId={zoneEntity}
                onEntity={openEntity}
                scoreOf={(id): ScoreState => {
                  if (card.status === "ok") {
                    const sc = entityScore(card.data, id);
                    return sc ? { status: "ok", here: sc.here, overall: sc.overall } : { status: "none" };
                  }
                  return card.status === "loading" || card.status === "idle" ? { status: "loading" } : { status: "none" };
                }}
                onOpenPrediction={onOpenPrediction}
                onOpenExplore={onOpenExplore}
              />
            ) : (
              <Card title={tr("Por zonas", "By zone")} level={3}>
                {imp && entities.status === "loading" && <StateMessage kind="loading">{tr("Cargando el mapa…", "Loading the map…")}</StateMessage>}
                {imp && entities.status === "error" && (
                  <StateMessage kind="error" onRetry={entities.reload}>
                    {tr("No se pudo cargar el mapa: ", "Could not load the map: ")}
                    {entities.error.message}
                  </StateMessage>
                )}
                {!imp && (
                  <NotYet what={tr("El reparto por zonas", "The breakdown by zone")}>
                    {mixture ? tr("Hacen falta las cifras de cada regla, y este modelo todavía no las ha publicado.", "It needs each rule's figures, which this model hasn't published yet.") : tr("Hace falta saber cuánto decide cada regla, y este modelo todavía no lo ha publicado.", "It needs the share each rule decides, which this model hasn't published yet.")}
                  </NotYet>
                )}
              </Card>
            )}
            {imp && (
              <Card
                title={tr("Qué variables intervienen más", "Which variables take part most")}
                level={3}
                className="vars-card"
                subtitle={
                  mixture
                    ? variableShareNote()
                    : regression
                    ? tr("Cuota media del promedio que aportan las reglas que usan cada variable.", "Mean share of the average taken up by the rules that use each variable.")
                    : tr("Parte de las predicciones decididas por reglas que usan cada variable.", "Share of the predictions decided by rules that use each variable.")
                }
              >
                <VariableBars variables={imp.variables} info={model.variables} label={label} regression={regression} mixture={mixture} compact />
                {noRule !== null && (noRule >= 0.005 || withheld !== null) && (
                  <p className="muted small" data-testid="no-rule">
                    {tr(<>En el <strong>{pct(noRule)}</strong> de las horas con todos los datos de entrada no dispara ninguna regla:</>, <>In <strong>{pct(noRule)}</strong> of the hours with complete input data, no rule fires:</>)}{" "}
                    {model.inference.fallback === "train_target_mean"
                      ? tr("el modelo da entonces la media del entrenamiento.", "the model then gives the training mean.")
                      : tr("el modelo no da predicción.", "the model gives no prediction.")}
                    {withheld !== null && (
                      <span data-testid="withheld">
                        {" "}
                        {tr(<>En otro <strong>{pct(withheld)}</strong> sí dispara una regla, pero no se publica predicción porque {g.el} {noun.one} no tiene nivel de referencia a esa hora. Esas horas no cuentan en las cifras.</>, <>In another <strong>{pct(withheld)}</strong> a rule does fire, but no prediction is published: the {noun.one} has no reference level at that hour. Those hours don't count in the figures.</>)}
                      </span>
                    )}
                  </p>
                )}
                <MoreInfo summary={tr("Cómo se mide", "How it is measured")}>
                  <p>
                    {mixture
                      ? measuredNote()
                      : regression
                      ? tr("Cada predicción es un promedio ponderado de las reglas. La cuota de cada regla es exacta, y las de una misma predicción suman 1. Una regla «decide» una predicción cuando su cuota es la mayor, y su error se mide en esas predicciones.", "Each prediction is a weighted average of the rules. Each rule's share is exact, and the shares in one prediction add up to 1. A rule “decides” a prediction when its share is the largest, and its error is measured on those predictions.")
                      : tr("Cada predicción la decide una sola regla, la de mayor grado de asociación (así funciona el clasificador). «Acierta» es la parte de esas decisiones (las que tienen observación) en la que la categoría coincide con la observada.", "Each prediction is decided by a single rule, the one with the highest association degree (that's how the classifier works). “Is right” is the share of those decisions (the ones with an observation) whose category matches the observed one.")}{" "}
                    {tr(`Las cifras son del periodo publicado (${importancePeriod(imp)}).`, `The figures are from the published period (${importancePeriod(imp)}).`)}
                  </p>
                  <p>{tr("Una regla usa varias variables, así que las barras de variables no suman el 100 %.", "A rule uses several variables, so the variable bars don't add up to 100%.")}</p>
                  {noRule !== null && noRule < 0.005 && withheld === null && (
                    <p data-testid="no-rule">{tr(`En el ${pct(noRule)} de las horas con todos los datos de entrada no dispara ninguna regla.`, `In ${pct(noRule)} of the hours with complete input data, no rule fires.`)}</p>
                  )}
                </MoreInfo>
              </Card>
            )}
          </aside>
        </div>
      </div>
      </RuleLookupProvider>
    </Naming>
  );
}
