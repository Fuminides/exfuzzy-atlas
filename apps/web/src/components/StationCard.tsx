import { useEffect, useId, useRef } from "react";
import type { ModelRules, TargetScheme } from "../api/types";
import { locale, tr } from "../i18n";
import { articles } from "../lib/domainUi";
import { pct, sig3 } from "../lib/format";
import { ruleSentence, useFeatureLabel, useNames } from "../lib/labels";
import { colourOf } from "../lib/ruleColours";
import { classMix, distinguishing, entityLifts, topRules, type Profiles, type RuleLift, type ShareEntity, type ShareTable } from "../lib/stationProfiles";
import { distinguishHeading, distinguishLead, hereLabel, liftShort, liftSentence, mixNote, noneStandsOut, overallLabel, profileName, topHeading } from "../lib/stationWording";
import { RuleRef } from "./RuleRef";
import { RuleSentenceView } from "./RuleSentenceView";

/** How the model does at the entity against all of them: loading (the card is fetched on the first click), not published per entity, or the figures. */
export type ScoreState = { status: "loading" } | { status: "none" } | { status: "ok"; here: number; overall: number };

interface Props {
  entityId: string;
  name: string;
  noun: { one: string; many: string };
  /** The entity's share vector; undefined when the importance does not list it. */
  entity: ShareEntity | undefined;
  /** "sin modelo" (NYC zones the model has no data for). */
  unmodelled: boolean;
  table: ShareTable;
  profiles: Profiles | null;
  rules: ModelRules;
  scheme: TargetScheme | null;
  measure: string;
  colours: ReadonlyMap<string, string>;
  profileColour: (index: number) => string;
  unit: string;
  /** Accuracy for a classifier, the mean error for a regression. */
  scoreMetric: "accuracy" | "mae";
  score: ScoreState;
  onClose: () => void;
  onRule: (ruleId: string) => void;
  onOpenPrediction?: (entityId: string) => void;
  onOpenExplore?: (entityId: string) => void;
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** Two thin bars on one scale: the rule's share here (its colour) and everywhere (grey), each with its number. */
function PairedBars({ l, max, colour, mixture }: { l: RuleLift; max: number; colour: string; mixture: boolean }) {
  const w = (v: number) => `${Math.max(0.5, (v / max) * 100)}%`;
  return (
    <div className="sc-pair" role="img" aria-label={liftSentence(l.here, l.overall, l.lift, l.count, mixture)}>
      <span className="sc-pair-label">{hereLabel()}</span>
      <span className="sc-pair-track">
        <span className="sc-pair-bar" style={{ width: w(l.here), background: colour }} />
      </span>
      <span className="sc-pair-value">{pct(l.here)}</span>
      <span className="sc-pair-label">{overallLabel()}</span>
      <span className="sc-pair-track">
        <span className="sc-pair-bar sc-pair-bar--overall" style={{ width: w(l.overall) }} />
      </span>
      <span className="sc-pair-value">{pct(l.overall)}</span>
    </div>
  );
}

/** A 100 % bar of categories, 2-px gaps between them; the numbers are in the list under it. */
function MixBar({ mix, colours, label }: { mix: readonly number[]; colours: readonly string[]; label: string }) {
  return (
    <span className="sc-mix-bar" role="img" aria-label={label}>
      {mix.map((m, i) => (m > 0 ? <span key={i} style={{ flexGrow: m, background: colours[i] }} /> : null))}
    </span>
  );
}

/**
 * The card of one station / zone / sampling point, opened from the map or the table of "Por zonas": its name and type,
 * how many predictions it has and how the model does there against all of them (when the card publishes it per entity),
 * its profile, the 2–3 rules used there clearly more than everywhere (each as its sentence, with "here vs everywhere"
 * bars), the predicted category mix, and the ways on to its series in Predicción and to Explorar. Everything is
 * descriptive: a rule is used more here, it does not cause what happens here.
 */
export function StationCard(p: Props) {
  const { entityId, name, noun, entity, unmodelled, table, profiles, rules, scheme, measure, colours, unit, score, scoreMetric } = p;
  const mixture = measure === "rule_mixture"; // contract v0.7: the share is of the predictions where the rule adds the most
  const label = useFeatureLabel();
  const names = useNames();
  const headingId = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  const opener = useRef<Element | null>(null);
  const g = articles(noun.one);
  useEffect(() => {
    opener.current = document.activeElement;
    heading.current?.focus({ preventScroll: true });
    heading.current?.closest("section")?.scrollIntoView?.({ block: "nearest" });
  }, [entityId]);
  const close = () => {
    p.onClose();
    if (opener.current instanceof HTMLElement && opener.current.isConnected) opener.current.focus();
  };

  const n = entity?.n ?? 0;
  const lifts = entity && n > 0 ? entityLifts(table, entity) : [];
  const apart = distinguishing(lifts, 3);
  const shown = apart.length > 0 ? apart : entity && n > 0 ? topRules(table, entity, 2) : [];
  const max = Math.max(0.05, ...shown.flatMap((l) => [l.here, l.overall]));
  const profileIndex = profiles?.of.get(entityId);
  const profile = profileIndex === undefined ? null : profiles!.profiles[profileIndex]!;
  const classes = scheme?.classes ?? [];
  const classOf = (id: string) => {
    const c = rules.rules.find((r) => r.rule_id === id)?.consequent;
    return c?.type === "class" ? (c.term ?? null) : null;
  };
  const keys = classes.map((c) => c.label);
  const mixHere = entity && n > 0 && scheme ? classMix(table, entity.shares, classOf, keys, measure) : null;
  const mixAll = mixHere ? classMix(table, table.overall, classOf, keys, measure) : null;
  const classColours = classes.map((c) => c.color ?? "#94a3b8");
  const mixText = (mix: readonly number[]) =>
    classes
      .map((c, i) => `${names.cls(c.label)} ${pct(mix[i] ?? 0)}`)
      .join(" · ");
  const fmtScore = (v: number) => (scoreMetric === "mae" ? `${sig3(v)}${unit ? ` ${unit}` : ""}` : pct(v));
  // the big figure keeps the unit small beside it, as in the report hero
  const bigScore = (v: number) => (scoreMetric === "mae" && unit ? <>{sig3(v)} <span className="sc-kpi-unit">{unit}</span></> : fmtScore(v));

  return (
    <section className="station-card" aria-labelledby={headingId} data-testid="station-card" data-entity={entityId} onKeyDown={(e) => e.key === "Escape" && close()}>
      <header className="sc-hero">
        <p className="sc-eyebrow">
          {cap(noun.one)} · <span className="sc-id">{entityId}</span>
        </p>
        <h4 id={headingId} ref={heading} tabIndex={-1} className="sc-name">
          {name}
        </h4>
        <button type="button" className="sc-close" onClick={close} aria-label={tr(`Cerrar la ficha de ${name}`, `Close the card for ${name}`)}>
          ×
        </button>
        {n > 0 && (
          <dl className="sc-kpis">
            <div className="sc-kpi">
              <dt>{tr("Predicciones", "Predictions")}</dt>
              <dd>{n.toLocaleString(locale())}</dd>
            </div>
            {score.status !== "none" && (
              <div className="sc-kpi" data-testid="station-score">
                <dt>{scoreMetric === "mae" ? tr("Error medio", "Mean error") : tr("Acierto", "Accuracy")}</dt>
                {score.status === "ok" ? (
                  <>
                    <dd>{bigScore(score.here)}</dd>
                    <span className="sc-kpi-note">{tr(`${fmtScore(score.overall)} en el conjunto`, `${fmtScore(score.overall)} everywhere`)}</span>
                  </>
                ) : (
                  <dd className="sc-kpi-loading">…</dd>
                )}
              </div>
            )}
            {profile && (
              <div className="sc-kpi sc-kpi--profile" data-testid="station-profile">
                <dt>{tr("Perfil", "Profile")}</dt>
                <dd>
                  <span className="territory-swatch" style={{ background: p.profileColour(profile.index) }} aria-hidden="true" /> {profile.letter}
                </dd>
                <span className="sc-kpi-note">{profileName(profile)}</span>
              </div>
            )}
          </dl>
        )}
      </header>

      <div className="sc-body">
        {unmodelled ? (
          <p className="small">{tr(`El modelo no tiene datos de ${g.este} ${noun.one}, así que no hay predicciones ni reglas que mostrar.`, `The model has no data for this ${noun.one}, so there are no predictions or rules to show.`)}</p>
        ) : n === 0 ? (
          <p className="small">{tr(`${g.Este} ${noun.one} no tiene predicciones publicadas y no se le atribuye ninguna regla.`, `This ${noun.one} has no published predictions, so no rule is attributed to it.`)}</p>
        ) : (
          <>
            <h5 className="sc-section">{apart.length > 0 ? distinguishHeading(g.el === "el") : topHeading(mixture)}</h5>
            <p className="sc-lead muted small">
              {apart.length > 0
                ? distinguishLead()
                : noneStandsOut()}
            </p>
            <ol className="sc-rules">
              {shown.map((l) => {
                const def = rules.rules.find((r) => r.rule_id === l.ruleId);
                const colour = colourOf(colours, l.ruleId);
                return (
                  <li key={l.ruleId} className="sc-rule" data-rule={l.ruleId}>
                    <div className="sc-rule-head">
                      <RuleRef id={l.ruleId} onClick={() => p.onRule(l.ruleId)} hint={tr(`Mostrar ${l.ruleId} en el mapa`, `Show ${l.ruleId} on the map`)} />
                      {apart.length > 0 && <span className="sc-lift" title={liftSentence(l.here, l.overall, l.lift, l.count, mixture)}>{liftShort(l.lift)}</span>}
                    </div>
                    {def && <RuleSentenceView sentence={ruleSentence(def, label, scheme, names)} testId="station-rule-sentence" />}
                    <PairedBars l={l} max={max} colour={colour} mixture={mixture} />
                  </li>
                );
              })}
            </ol>

            {mixHere && mixAll && (
              <div className="sc-mix" data-testid="station-mix">
                <h5 className="sc-section">{tr("Categorías previstas", "Predicted categories")}</h5>
                <div className="sc-mix-rows">
                  <span className="sc-pair-label">{hereLabel()}</span>
                  <MixBar mix={mixHere} colours={classColours} label={tr(`Aquí: ${mixText(mixHere)}`, `Here: ${mixText(mixHere)}`)} />
                  <span className="sc-pair-label">{overallLabel()}</span>
                  <MixBar mix={mixAll} colours={classColours} label={tr(`En el conjunto: ${mixText(mixAll)}`, `Everywhere: ${mixText(mixAll)}`)} />
                </div>
                <ul className="sc-mix-legend">
                  {classes.map((c, i) => (
                    <li key={c.label}>
                      <span className="territory-swatch" style={{ background: classColours[i] }} aria-hidden="true" /> {names.cls(c.label)}{" "}
                      <strong>{pct(mixHere[i] ?? 0)}</strong> <span className="muted">({pct(mixAll[i] ?? 0)})</span>
                    </li>
                  ))}
                </ul>
                <p className="muted small">{mixNote()}</p>
              </div>
            )}
          </>
        )}

        {n > 0 && (p.onOpenPrediction || p.onOpenExplore) && (
          <div className="sc-actions">
            {p.onOpenPrediction && (
              <button type="button" className="sc-action sc-action--primary" onClick={() => p.onOpenPrediction!(entityId)}>
                {tr(<>Ver su serie en <em>Predicción</em></>, <>See its series in <em>Prediction</em></>)}
              </button>
            )}
            {p.onOpenExplore && (
              <button type="button" className="sc-action" onClick={() => p.onOpenExplore!(entityId)}>
                {tr(<>Ver en <em>Explorar</em></>, <>See in <em>Explore</em></>)}
              </button>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
