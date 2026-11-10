import type { CSSProperties } from "react";
import { api } from "../api/client";
import type { EntityCollection, ModelCard, ModelRules, RuleImportanceResponse, TaskInfo } from "../api/types";
import { useAsync } from "../hooks/useAsync";
import { useOptionalAsync } from "../hooks/useOptionalAsync";
import { tr } from "../i18n";
import { pct, unitLabel, withUnit } from "../lib/format";
import { decidedShare, entityRanked, rankedRules } from "../lib/importance";
import { labelerFor, namesFor, ruleSentence } from "../lib/labels";
import { hitsWhenTop, isMixture, isMixtureImportance, leadShare } from "../lib/mixture";
import { barLabel, performanceReport } from "../lib/performance";
import { colourOf, otherRulesLabel, OTHER_RULES_COLOUR, ruleColours } from "../lib/ruleColours";
import { groupTerritories } from "../lib/tasks";
import { OutcomePill } from "./OutcomePill";
import { RuleSentenceView } from "./RuleSentenceView";
import { ACCENT, columnRange, TermGlyph } from "./TermGlyph";

/**
 * The landing's floating artifacts (DESIGN.md › Floating Product Artifact): small copies of what the demo shows, drawn
 * by the app's own helpers from the API's data for the task the demo opens on. They are decorative (hidden from screen
 * readers: the landing's text says everything), and an artifact whose data does not arrive is simply not drawn; no
 * number here is made up.
 */
export function LandingArtifacts() {
  const domains = useAsync((s) => api.domains(s), []);
  const first = domains.status === "ok" ? (groupTerritories(domains.data.domains)[0]?.territories[0] ?? null) : null;
  const task = first?.defaultTask ?? null;
  const modelId = task?.model_id ?? null;
  const on = modelId !== null;
  const rules = useAsync((s) => api.modelRules(modelId!, s), [modelId], on);
  const card = useAsync((s) => api.modelCard(modelId!, s), [modelId], on);
  const importance = useOptionalAsync((s) => api.importance(modelId!, s), [modelId], on);
  const entities = useAsync((s) => api.entities(first!.domain, task?.task_id, s), [task?.task_id], on);

  if (!task || !first) return null;
  const imp = importance.status === "ok" ? importance.data : null;
  const colours = imp ? ruleColours(rankedRules(imp.rules).map((r) => r.rule_id)) : null;
  const where = `${first.title} · ${task.horizon_hours > 0 ? `+${task.horizon_hours} h` : tr("misma muestra", "same sample")}`;
  return (
    <div className="lp-arts" aria-hidden="true" data-testid="landing-artifacts">
      {card.status === "ok" && <PerfArtifact card={card.data} where={where} unit={task.unit} />}
      {rules.status === "ok" && imp && colours && <RuleArtifact rules={rules.data} importance={imp} colours={colours} task={task} where={where} />}
      {entities.status === "ok" && imp && colours && <MapArtifact entities={entities.data} importance={imp} colours={colours} where={first.title} mixture={isMixtureImportance(imp)} />}
      {rules.status === "ok" && imp && colours && <RowArtifact rules={rules.data} importance={imp} colours={colours} task={task} />}
    </div>
  );
}

/** How the model does against the baselines on the test period, as the report shows it (Steep's region card). */
function PerfArtifact({ card, where, unit }: { card: ModelCard; where: string; unit: string }) {
  const classifier = card.target_scheme != null;
  const report = performanceReport(card, classifier ? "accuracy" : "mae");
  if (!report) return null;
  const model = report.bars.find((b) => b.key === "model")!;
  const fmtV = (v: number) => (classifier ? pct(v) : withUnit(v, unitLabel(unit), 2));
  const max = Math.max(...report.bars.map((b) => b.value)) || 1;
  const year = new Date(card.manifest.split.test_from_utc).getUTCFullYear();
  return (
    <figure className="lp-art lp-art--perf" data-testid="landing-perf">
      <div className="lp-perf-main">
        <p className="lp-art-label">{classifier ? tr("Acierto", "Accuracy") : tr("Error medio", "Mean error")}</p>
        <p className="lp-figure">{fmtV(model.value)}</p>
        <p className="lp-art-note">{tr(`ExFuzzy · ${where} · prueba ${year}`, `ExFuzzy · ${where} · test ${year}`)}</p>
        <ol className="lp-cols">
          {report.bars.map((b) => (
            <li key={b.key} className={b.key === "model" ? "lp-col-bar lp-col-bar--model" : "lp-col-bar"} style={{ "--h": `${(b.value / max) * 100}%` } as CSSProperties} />
          ))}
        </ol>
      </div>
      <table className="lp-perf-table">
        <tbody>
          {report.bars.map((b) => (
            <tr key={b.key} className={b.key === "model" ? "lp-row--model" : undefined}>
              <th scope="row">{barLabel(b.key, classifier)}</th>
              <td>{fmtV(b.value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}

/**
 * The rule that decides most, as its sentence, a term glyph and a ring of the predictions it decides (the peach card).
 * In a mixture of rules (v0.7) no rule decides: it is the rule that adds the most to the predicted category, and the ring
 * is `top_contributor_share`; without that figure the ring is not drawn.
 */
function RuleArtifact({ rules, importance, colours, task, where }: { rules: ModelRules; importance: RuleImportanceResponse; colours: ReadonlyMap<string, string>; task: TaskInfo; where: string }) {
  const top = rankedRules(importance.rules)[0];
  const rule = top ? rules.rules.find((r) => r.rule_id === top.rule_id) : undefined;
  if (!top || !rule) return null;
  const scheme = rules.target_scheme ?? null;
  const label = labelerFor(rules.variables);
  const first = rule.antecedents[0];
  const variable = first ? rules.variables.find((v) => v.feature === first.feature) : undefined;
  const range = columnRange(variable);
  const mixture = isMixture(rules);
  const figure = mixture ? (top.top_contributor_share ?? null) : decidedShare(top);
  const share = figure === null ? null : Math.max(0, Math.min(1, figure));
  const R = 40;
  const C = 2 * Math.PI * R;
  return (
    <figure className="lp-art lp-art--rule" data-testid="landing-rule">
        <p className="lp-art-label">
          <span className="lp-swatch" style={{ background: colourOf(colours, rule.rule_id) }} />
          {mixture ? tr(`Regla ${rule.rule_id} · la que más suma`, `Rule ${rule.rule_id} · the one that adds the most`) : tr(`Regla ${rule.rule_id} · la que más decide`, `Rule ${rule.rule_id} · the one that decides most`)}
        </p>
        <RuleSentenceView sentence={ruleSentence(rule, label, scheme, namesFor(rules.variables, scheme, task.target))} testId="landing-rule-sentence" />
        {variable && range && first && (
          <p className="lp-glyph">
            <TermGlyph variable={variable} term={first.term} range={range} fill={scheme?.classes.find((c) => c.label === first.term)?.color ?? ACCENT} />
          </p>
        )}
        {share !== null && (
        <div className="lp-ring-row">
          <svg className="lp-ring" viewBox="0 0 100 100" width="104" height="104">
            <circle cx="50" cy="50" r={R} className="lp-ring-track" />
            <circle cx="50" cy="50" r={R} className="lp-ring-fill" strokeDasharray={`${share * C} ${C}`} transform="rotate(-90 50 50)" />
            <text x="50" y="55" textAnchor="middle" className="lp-ring-text">{pct(share)}</text>
          </svg>
          <p className="lp-ring-note">
            {mixture ? tr("de las predicciones, esta es la regla que más suma a la categoría prevista", "of the predictions, this is the rule that adds the most to the predicted category") : tr("de las predicciones las decide esta regla", "of the predictions are decided by this rule")}
            {top.accuracy != null && (
              <>
                <br />
                <span className="lp-ring-hit">{mixture ? hitsWhenTop(top.accuracy) : tr(`acierta el ${pct(top.accuracy)}`, `right ${pct(top.accuracy)} of the time`)}</span>
              </>
            )}
            <br />
            <span className="lp-art-note">{where}</span>
          </p>
        </div>
        )}
      </figure>
  );
}

/** Where each rule decides most: the stations as dots in the rule's colour (Patrones › Por zonas, in miniature). */
function MapArtifact({ entities, importance, colours, where, mixture }: { entities: EntityCollection; importance: RuleImportanceResponse; colours: ReadonlyMap<string, string>; where: string; mixture: boolean }) {
  const byId = new Map(importance.entities.map((e) => [e.entity_id, e] as const));
  const points = entities.features.flatMap((f) => {
    const g = f.geometry;
    const top = entityRanked(byId.get(f.properties.entity_id))[0];
    // A mixture's station with no top rule (nothing supports its predicted category) is left out, not coloured.
    if (!g || g.type !== "Point" || !top || (mixture && leadShare(top) <= 0)) return [];
    const [lon, lat] = g.coordinates as [number, number];
    return [{ id: f.properties.entity_id, lon, lat, rule: top.rule_id }];
  });
  if (points.length < 10) return null;
  const lats = points.map((p) => p.lat);
  const lons = points.map((p) => p.lon);
  const [la0, la1, lo0, lo1] = [Math.min(...lats), Math.max(...lats), Math.min(...lons), Math.max(...lons)];
  const k = Math.cos((((la0 + la1) / 2) * Math.PI) / 180);
  const W = 240;
  const s = W / (((lo1 - lo0) * k) || 1);
  const H = Math.round((la1 - la0) * s) || W;
  const x = (lon: number) => 6 + (lon - lo0) * k * s;
  const y = (lat: number) => 6 + (la1 - lat) * s;
  const shown = [...colours.keys()].filter((id) => points.some((p) => p.rule === id));
  const others = points.some((p) => !colours.has(p.rule));
  return (
    <figure className="lp-art lp-art--map" data-testid="landing-map">
      <p className="lp-art-label">{mixture ? tr(`Dónde suma más cada regla · ${where}`, `Where each rule adds the most · ${where}`) : tr(`Dónde decide cada regla · ${where}`, `Where each rule decides · ${where}`)}</p>
      <svg viewBox={`0 0 ${W + 12} ${H + 12}`} className="lp-map">
        {points.map((p) => (
          <circle key={p.id} cx={x(p.lon)} cy={y(p.lat)} r={3.2} style={{ fill: colourOf(colours, p.rule) }} />
        ))}
      </svg>
      <ul className="lp-map-key">
        {shown.map((id) => (
          <li key={id}>
            <span className="lp-swatch" style={{ background: colourOf(colours, id) }} />
            {id}
          </li>
        ))}
        {others && (
          <li>
            <span className="lp-swatch" style={{ background: OTHER_RULES_COLOUR }} />
            {otherRulesLabel()}
          </li>
        )}
      </ul>
    </figure>
  );
}

/**
 * One row of the rule matrix (Patrones › Las reglas de un vistazo): a rule other than the one on the peach card, each
 * condition as its term glyph and complete phrase, the outcome and the share it decides (in a mixture, the share of predictions
 * it adds the most to, and the outcome is the category it supports most, never a conclusion). It is the highest-ranked rule
 * with a term that is not a class of the scheme, so the row shows a phrase such as «humedad alta»; else the second.
 */
function RowArtifact({ rules, importance, colours, task }: { rules: ModelRules; importance: RuleImportanceResponse; colours: ReadonlyMap<string, string>; task: TaskInfo }) {
  const scheme = rules.target_scheme ?? null;
  const isClass = (term: string) => scheme?.classes.some((c) => c.label === term) ?? false;
  const ranked = rankedRules(importance.rules).slice(1, 6);
  const pick = ranked.find((r) => rules.rules.find((d) => d.rule_id === r.rule_id)?.antecedents.some((a) => !isClass(a.term))) ?? ranked[0];
  const rule = pick ? rules.rules.find((r) => r.rule_id === pick.rule_id) : undefined;
  if (!pick || !rule) return null;
  const names = namesFor(rules.variables, scheme, task.target);
  const sentence = ruleSentence(rule, labelerFor(rules.variables), scheme, names);
  return (
    <figure className="lp-art lp-art--row" data-testid="landing-row">
      <p className="lp-art-label">{tr("Las reglas de un vistazo", "The rules at a glance")}</p>
      <div className="lp-row">
        <span className="lp-row-id">
          <span className="lp-swatch" style={{ background: colourOf(colours, rule.rule_id) }} />
          {rule.rule_id}
        </span>
        {rule.antecedents.map((a) => {
          const v = rules.variables.find((x) => x.feature === a.feature);
          const range = columnRange(v);
          const part = sentence.parts.find((p) => p.feature === a.feature && p.term === a.term);
          return (
            <span key={`${a.feature}|${a.term}`} className="rmx-tile lp-row-tile">
              {v && range && <TermGlyph variable={v} term={a.term} range={range} fill={part?.color ?? ACCENT} compact />}
              <span className="rmx-term">
                <em className="term-phrase">{names.phrase(a.feature, a.term)}</em>
              </span>
            </span>
          );
        })}
        <span className="rmx-arrow">→</span>
        <OutcomePill outcome={sentence.outcome} />
        {(!isMixture(rules) || pick.top_contributor_share != null) && <span className="lp-row-share">{pct(leadShare(pick))}</span>}
      </div>
    </figure>
  );
}
