import { locale, tr } from "../i18n";
import { useMemo, useState } from "react";
import type { EntityCollection, ModelRules, RuleImportanceResponse, TargetScheme } from "../api/types";
import { PURPLES, gradientCss } from "../lib/colorScale";
import { articles } from "../lib/domainUi";
import { entityRows } from "../lib/entityRows";
import { pct } from "../lib/format";
import { entityRanked, isRegressionImportance, rankedRules } from "../lib/importance";
import { isMixtureImportance, leadShare } from "../lib/mixture";
import { ruleSentence, sentenceText, useFeatureLabel, useNames } from "../lib/labels";
import { colourClasses, colourKey, colourOf, NEUTRAL_ZONE_COLOUR, OTHER_RULES_COLOUR, otherRulesLabel, presentRules, PROFILE_COLOURS, ruleColours } from "../lib/ruleColours";
import { characteristicRule, entityLifts, MIN_COUNT, MIN_LIFT, MIN_SHARE, profilesOf, shareTable, WEAK_SILHOUETTE, type RuleLift } from "../lib/stationProfiles";
import { characteristicNote, liftShort, modeLabel, modeSubtitle, noCharacteristic, noProfile, profileName, profilesNote, profileTitle, topNote, ZONE_MODES, type ZoneMode } from "../lib/stationWording";
import { StationMap } from "../map/StationMap";
import type { StationRow } from "../map/stations";
import { Card } from "./Card";
import { RuleRef } from "./RuleRef";
import { StationCard, type ScoreState } from "./StationCard";

const BASEMAP: string | undefined = import.meta.env.VITE_BASEMAP_STYLE_URL || undefined;

/** Map keys of the neutral entities: they carry a label (so they are drawn and can be clicked) but no rule or profile. */
const NONE_KEY = "__none__";
const profileKey = (index: number) => `profile:${index}`;
const profileColour = (index: number) => PROFILE_COLOURS[index % PROFILE_COLOURS.length]!;

interface Props {
  entities: EntityCollection;
  rules: ModelRules;
  importance: RuleImportanceResponse;
  scheme: TargetScheme | null;
  unit: string;
  noun: { one: string; many: string };
  /** The rule picked in the cards: the map then shows how much it decides in each zone. */
  ruleId: string | null;
  onRule: (ruleId: string | null) => void;
  entityId: string | null;
  onEntity: (entityId: string | null) => void;
  /** How the model does at an entity against all of them (from the model card, fetched on the first click). */
  scoreOf?: (entityId: string) => ScoreState;
  onOpenPrediction?: (entityId: string) => void;
  onOpenExplore?: (entityId: string) => void;
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/**
 * "Por zonas", beside the rules. Three ways to colour the zones with no rule picked:
 * - «Regla característica» (default): the rule most over-represented in each zone against all of them (lift), with a
 *   minimum support; a zone where none stands out is drawn white;
 * - «Perfiles»: zones grouped by their rule-share vectors (deterministic k-means), each profile named by its rules;
 * - «Regla que más decide»: the rule that decides most there (almost always the same persistence-like rule).
 * With a rule picked, the share of each zone's predictions it decides. Clicking a zone (map or table) opens its card.
 * Nothing here is an activation or an interpolation: a zone is a station or a published polygon.
 */
export function ZonesSection({ entities, rules, importance, scheme, unit, noun, ruleId, onRule, entityId, onEntity, scoreOf, onOpenPrediction, onOpenExplore }: Props) {
  const label = useFeatureLabel();
  const names = useNames();
  const [mode, setMode] = useState<ZoneMode>("characteristic");
  const g = articles(noun.one);
  const noPublished = tr(`sin predicciones publicadas en ${g.este} ${noun.one}`, `no predictions published at this ${noun.one}`);
  const regression = isRegressionImportance(importance);
  // contract v0.7: in a mixture of rules the share is of the predictions where the rule adds the most (no rule decides)
  const mixture = isMixtureImportance(importance);
  const { baseRows, nameOf } = useMemo(() => entityRows(entities, new Set()), [entities]);
  const unmodelled = useMemo(() => new Set(entities.features.filter((f) => f.properties.modelled === false).map((f) => f.properties.entity_id)), [entities]);
  const byId = useMemo(() => new Map(importance.entities.map((e) => [e.entity_id, e])), [importance]);
  const table = useMemo(() => shareTable(importance), [importance]);
  const shareOf = useMemo(() => new Map(table.entities.map((e) => [e.entityId, e])), [table]);
  const lifts = useMemo(() => new Map(table.entities.map((e) => [e.entityId, e.n > 0 ? entityLifts(table, e) : []])), [table]);
  const characteristic = useMemo(() => new Map([...lifts].map(([id, l]) => [id, characteristicRule(l)])), [lifts]);
  const profiles = useMemo(() => profilesOf(table), [table]);
  const rule = ruleId ? rules.rules.find((r) => r.rule_id === ruleId) : undefined;
  // One colour per rule, the same as in Predicción and the rule matrix: the rules that decide most, grey for the rest.
  const colours = useMemo(() => ruleColours(rankedRules(importance.rules).map((r) => r.rule_id)), [importance]);

  const rows: StationRow[] = baseRows.map((r) => {
    const e = byId.get(r.entityId);
    if (!e || e.n_predicted === 0) return { ...r, value: null, label: null, missingReason: "prediction_unavailable", noPredictions: true, nValid: e?.n_predicted ?? 0 };
    if (ruleId) {
      const picked = e.rules.find((x) => x.rule_id === ruleId);
      const share = picked ? leadShare(picked) : 0;
      return { ...r, value: share, label: null, missingReason: null, nValid: e.n_predicted };
    }
    if (mode === "characteristic") return { ...r, value: null, label: characteristic.get(r.entityId)?.ruleId ?? NONE_KEY, missingReason: null, nValid: e.n_predicted };
    if (mode === "profiles") {
      const p = profiles?.of.get(r.entityId);
      return { ...r, value: null, label: p === undefined ? NONE_KEY : profileKey(p), missingReason: null, nValid: e.n_predicted };
    }
    const top = entityRanked(e)[0];
    return { ...r, value: null, label: top?.rule_id ?? null, missingReason: top ? null : "prediction_unavailable", noPredictions: !top, nValid: e.n_predicted };
  });
  const ruleMode = mode !== "profiles";
  const legendIds = rows.map((r) => (ruleMode && r.label && r.label !== NONE_KEY ? r.label : null));
  const { coloured, others } = presentRules(colours, legendIds);
  const mapRows = rows.map((r) => (r.label && ruleMode && r.label !== NONE_KEY ? { ...r, label: colourKey(colours, r.label) } : r));
  const neutral = { label: NONE_KEY, color: NEUTRAL_ZONE_COLOUR };
  const classes = mode === "profiles" ? [...(profiles?.profiles ?? []).map((p) => ({ label: profileKey(p.index), color: profileColour(p.index) })), neutral] : [...colourClasses(colours), neutral];
  const nNeutral = rows.filter((r) => r.label === NONE_KEY).length;

  const values = rows.flatMap((r) => (r.value === null ? [] : [r.value]));
  const max = Math.max(0.05, Math.ceil(Math.max(0, ...values) * 20) / 20);
  const withValue = rows.filter((r) => r.value !== null || r.label).length;
  // Taxi zones: 110 of 263 have predictions, so the map frames those. A few stations without any are not worth cropping.
  const frameOnData = withValue < rows.length * 0.8;
  const none = tr("sin predicciones", "no predictions");
  const topShare = (id: string) => {
    const e = byId.get(id);
    const top = entityRanked(e)[0];
    return top ? { id: top.rule_id, share: leadShare(top) } : null;
  };
  const pickedShare = (r: StationRow) => (r.value === null ? none : pct(r.value));
  const pickedText = (id: string) =>
    mixture
      ? tr(`Parte de las predicciones de cada ${noun.one} en las que ${id} es la regla que más suma a la categoría prevista.`, `Share of each ${noun.one}'s predictions in which ${id} is the rule that adds the most to the predicted category.`)
      : tr(`Parte de las predicciones de cada ${noun.one} que decide la regla ${id}.`, `Share of each ${noun.one}'s predictions that rule ${id} decides.`);
  const sentenceOf = (id: string) => {
    const def = rules.rules.find((r) => r.rule_id === id);
    return def ? sentenceText(ruleSentence(def, label, scheme, names)) : id;
  };
  const charText = (l: RuleLift | null | undefined) => (l ? tr(`se usa más ${l.ruleId} (${pct(l.here)} aquí, ${pct(l.overall)} en el conjunto)`, `${l.ruleId} is used more (${pct(l.here)} here, ${pct(l.overall)} everywhere)`) : noCharacteristic());
  const profileOf = (id: string) => {
    const p = profiles?.of.get(id);
    return p === undefined ? null : profiles!.profiles[p]!;
  };
  const tip = (m: StationRow) => {
    const r = rows.find((x) => x.entityId === m.entityId) ?? m; // the map's label may be "otras reglas"
    if (ruleId) return `${r.name}: ${pickedShare(r)}`;
    if (!r.label) return `${r.name}: ${none}`;
    if (mode === "characteristic") return `${r.name}: ${charText(characteristic.get(r.entityId))}`;
    if (mode === "profiles") {
      const p = profileOf(r.entityId);
      return `${r.name}: ${p ? profileTitle(p) : noProfile()}`;
    }
    const t = topShare(r.entityId);
    return `${r.name}: ${t ? (mixture ? tr(`la regla que más suma es ${t.id} (${pct(t.share)})`, `rule ${t.id} adds the most (${pct(t.share)})`) : tr(`decide más la regla ${t.id} (${pct(t.share)})`, `rule ${t.id} decides most (${pct(t.share)})`)) : none}`;
  };
  const chooseMode = (m: ZoneMode) => {
    setMode(m);
    if (ruleId) onRule(null);
  };
  const onModeKey = (e: React.KeyboardEvent) => {
    const i = ZONE_MODES.indexOf(mode);
    const next = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : null;
    if (next === null) return;
    e.preventDefault();
    const m = ZONE_MODES[(next + ZONE_MODES.length) % ZONE_MODES.length]!;
    chooseMode(m);
    (e.currentTarget.querySelector(`[data-mode="${m}"]`) as HTMLElement | null)?.focus();
  };

  const ruleLegend = (
    <ol className="rule-legend">
      {coloured.map((c) => (
        <li key={c.id}>
          <RuleRef id={c.id} className="rule-legend-btn" onClick={() => onRule(c.id)} hint={tr(`Mostrar ${c.id} en el mapa`, `Show ${c.id} on the map`)}>
            <span className="territory-swatch" style={{ background: colourOf(colours, c.id) }} aria-hidden="true" />
            <strong>{c.id}</strong> <span className="muted small">{c.n}</span>
          </RuleRef>
        </li>
      ))}
      {others.ids.length > 0 && (
        <li>
          <span className="rule-legend-btn rule-legend-btn--other" title={others.ids.join(", ")}>
            <span className="territory-swatch" style={{ background: OTHER_RULES_COLOUR }} aria-hidden="true" />
            {otherRulesLabel()} ({others.ids.join(", ")}) <span className="muted small">{others.n}</span>
          </span>
        </li>
      )}
      {mode === "characteristic" && nNeutral > 0 && (
        <li>
          <span className="rule-legend-btn rule-legend-btn--other" data-testid="legend-none">
            <span className="territory-swatch" style={{ background: NEUTRAL_ZONE_COLOUR }} aria-hidden="true" />
            {noCharacteristic()} <span className="muted small">{nNeutral}</span>
          </span>
        </li>
      )}
    </ol>
  );

  return (
    <Card
      title={rule ? (mixture ? tr(`Dónde suma más ${rule.rule_id}`, `Where ${rule.rule_id} adds the most`) : tr(`Dónde decide ${rule.rule_id}`, `Where ${rule.rule_id} decides`)) : tr("Por zonas", "By zone")}
      level={3}
      className="map-card zones-card"
      subtitle={rule ? pickedText(rule.rule_id) : modeSubtitle(mode, noun.one, mixture)}
    >
      <div className="zones-modes" role="group" aria-label={tr("Colorear por", "Colour by")} onKeyDown={onModeKey}>
        <span className="zones-modes-label small muted" aria-hidden="true">{tr("Colorear por", "Colour by")}</span>
        <div className="segmented">
          {ZONE_MODES.map((m) => (
            <button key={m} type="button" data-mode={m} aria-pressed={!ruleId && mode === m} onClick={() => chooseMode(m)}>
              {modeLabel(m, mixture)}
            </button>
          ))}
        </div>
      </div>
      <div className="map-box">
        <StationMap
          rows={mapRows}
          layerOptions={
            ruleId
              ? { kind: "values", stops: PURPLES, domain: [0, max], emphasis: null, selectedId: entityId }
              : { kind: "categories", stops: PURPLES, domain: [0, 1], emphasis: null, selectedId: entityId, classes }
          }
          onSelect={onEntity}
          basemapUrl={BASEMAP}
          plural={noun.many}
          fitTo={frameOnData ? (r) => (r.nValid ?? 0) > 0 : () => true}
          tipText={tip}
        />
      </div>

      {ruleId ? (
        <section className="zones-legend" aria-label={mixture ? tr(`Leyenda: parte de las predicciones en las que ${ruleId} es la que más suma`, `Legend: share of the predictions in which ${ruleId} adds the most`) : tr(`Leyenda: parte de las predicciones que decide la regla ${ruleId}`, `Legend: share of the predictions that rule ${ruleId} decides`)} data-domain={`0-${max}`}>
          <div className="legend-bar" style={{ background: gradientCss(PURPLES) }} role="img" aria-label={tr(`Escala de ${pct(0)} a ${pct(max)}`, `Scale from ${pct(0)} to ${pct(max)}`)} />
          <ol className="legend-ticks">
            {[0, 0.5, 1].map((t) => (
              <li key={t}>{pct(t * max)}</li>
            ))}
          </ol>
          <p className="muted small">
            {pickedText(ruleId)} {tr("Es un recuento de predicciones publicadas.", "It is a count of published predictions.")}{" "}
            <button type="button" className="link" onClick={() => onRule(null)}>{tr(<>Volver a <em>{modeLabel(mode, mixture)}</em></>, <>Back to <em>{modeLabel(mode, mixture)}</em></>)}</button>
          </p>
          <p className="legend-missing small">
            <span className="marker marker--unmodelled" aria-hidden="true" /> {noPublished}
          </p>
        </section>
      ) : mode === "profiles" ? (
        <section className="zones-legend legend--rules" aria-label={tr("Leyenda: perfiles de reglas", "Legend: rule profiles")} data-testid="zones-legend" data-mode="profiles">
          {profiles ? (
            <>
              <ol className="rule-legend profile-legend">
                {profiles.profiles.map((p) => (
                  <li key={p.index} data-profile={p.letter}>
                    <span className="rule-legend-btn rule-legend-btn--static" title={p.naming.map((l) => `${l.ruleId} ${liftShort(l.lift)}: ${sentenceOf(l.ruleId)}`).join("\n")}>
                      <span className="territory-swatch" style={{ background: profileColour(p.index) }} aria-hidden="true" />
                      <strong>{p.letter}</strong> {profileName(p)} <span className="muted small">{p.entityIds.length}</span>
                    </span>
                  </li>
                ))}
                {nNeutral > 0 && (
                  <li>
                    <span className="rule-legend-btn rule-legend-btn--other">
                      <span className="territory-swatch" style={{ background: NEUTRAL_ZONE_COLOUR }} aria-hidden="true" />
                      {noProfile()} <span className="muted small">{nNeutral}</span>
                    </span>
                  </li>
                )}
              </ol>
              <p className="muted small">{profilesNote(profiles.k, profiles.silhouette, profiles.silhouette < WEAK_SILHOUETTE)}</p>
            </>
          ) : (
            <p className="muted small">{tr(`Hay muy pocos lugares con predicciones para agruparlos en perfiles.`, `There are too few places with predictions to group them into profiles.`)}</p>
          )}
          <p className="legend-missing small">
            <span className="marker marker--unmodelled" aria-hidden="true" /> {noPublished}
          </p>
        </section>
      ) : (
        <section
          className="zones-legend legend--rules"
          aria-label={mode === "characteristic" ? tr("Leyenda: regla característica de cada zona", "Legend: characteristic rule of each zone") : mixture ? tr("Leyenda: regla que más suma en cada zona", "Legend: rule that adds the most in each zone") : tr("Leyenda: regla que más decide en cada zona", "Legend: rule that decides most in each zone")}
          data-testid="zones-legend"
          data-mode={mode}
        >
          <p className="muted small">{mode === "characteristic" ? characteristicNote(MIN_SHARE, MIN_COUNT, MIN_LIFT, mixture) : topNote(mixture)}</p>
          {ruleLegend}
          <p className="legend-missing small">
            <span className="marker marker--unmodelled" aria-hidden="true" /> {noPublished}
          </p>
        </section>
      )}
      <p className="legend-count small">
        {tr(<>{cap(noun.many)} con predicciones: <strong>{withValue}</strong> de {rows.length}</>, <>{cap(noun.many)} with predictions: <strong>{withValue}</strong> of {rows.length}</>)}
      </p>

      {entityId ? (
        <StationCard
          key={entityId}
          entityId={entityId}
          name={nameOf(entityId)}
          noun={noun}
          entity={shareOf.get(entityId)}
          unmodelled={unmodelled.has(entityId)}
          table={table}
          profiles={profiles}
          rules={rules}
          scheme={scheme}
          measure={importance.measure}
          colours={colours}
          profileColour={profileColour}
          unit={unit}
          scoreMetric={regression ? "mae" : "accuracy"}
          score={scoreOf ? scoreOf(entityId) : { status: "none" }}
          onClose={() => onEntity(null)}
          onRule={(id) => onRule(id)}
          onOpenPrediction={onOpenPrediction}
          onOpenExplore={onOpenExplore}
        />
      ) : (
        <p className="zone-hint muted small">{tr(`Haz clic en ${g.un} ${noun.one} del mapa o de la tabla para ver su ficha.`, `Click a ${noun.one} on the map or in the table to see its card.`)}</p>
      )}

      <details className="zones-table">
        <summary>{tr("Ver como tabla", "Show as a table")}</summary>
        <div className="table-scroll">
          <table className="plain zone-table">
            <caption className="sr-only">
              {ruleId
                ? mixture
                  ? tr(`Tabla de ${noun.many}: parte de las predicciones en las que ${ruleId} es la que más suma`, `Table of ${noun.many}: share of the predictions in which ${ruleId} adds the most`)
                  : tr(`Tabla de ${noun.many}: parte de las predicciones que decide la regla ${ruleId}`, `Table of ${noun.many}: share of the predictions that rule ${ruleId} decides`)
                : tr(`Tabla de ${noun.many}: ${modeLabel(mode, mixture).toLowerCase()}`, `Table of ${noun.many}: ${modeLabel(mode, mixture).toLowerCase()}`)}
            </caption>
            <thead>
              <tr>
                <th scope="col">{cap(noun.one)}</th>
                {!ruleId && <th scope="col">{mode === "profiles" ? tr("Perfil", "Profile") : tr("Regla", "Rule")}</th>}
                {(ruleId || mode !== "profiles") && (
                  <th scope="col" className="num">
                    {ruleId ? (mixture ? tr(`Parte en que más suma ${ruleId}`, `Share where ${ruleId} adds the most`) : tr(`Parte que decide ${ruleId}`, `Share decided by ${ruleId}`)) : mode === "characteristic" ? tr("Aquí / en el conjunto", "Here / everywhere") : tr("Parte", "Share")}
                  </th>
                )}
                <th scope="col" className="num"><abbr title={tr("Predicciones publicadas", "Published predictions")}>n</abbr></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const c = characteristic.get(r.entityId);
                const t = topShare(r.entityId);
                const p = profileOf(r.entityId);
                const has = r.nValid !== null && r.nValid > 0;
                return (
                  <tr key={r.entityId} aria-selected={r.entityId === entityId} data-entity={r.entityId}>
                    <th scope="row">
                      <button type="button" className="link" onClick={() => onEntity(r.entityId)} aria-pressed={r.entityId === entityId}>
                        {r.name}
                      </button>
                    </th>
                    {!ruleId && (
                      <td>
                        {!has ? (
                          <span className="missing-text">{none}</span>
                        ) : mode === "characteristic" ? (
                          (c?.ruleId ?? <span className="missing-text">{noCharacteristic()}</span>)
                        ) : mode === "profiles" ? (
                          p ? profileTitle(p) : <span className="missing-text">{noProfile()}</span>
                        ) : (
                          (t?.id ?? <span className="missing-text">{none}</span>)
                        )}
                      </td>
                    )}
                    {(ruleId || mode !== "profiles") && (
                      <td className="num">
                        {ruleId ? (has ? pickedShare(r) : "—") : !has ? "—" : mode === "characteristic" ? (c ? `${pct(c.here)} / ${pct(c.overall)}` : "—") : t ? pct(t.share) : "—"}
                      </td>
                    )}
                    <td className="num">{has ? r.nValid!.toLocaleString(locale()) : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </details>
    </Card>
  );
}
