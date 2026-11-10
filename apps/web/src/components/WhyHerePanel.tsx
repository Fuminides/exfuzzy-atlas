import type { AsyncState } from "../hooks/useAsync";
import { RuleRef } from "./RuleRef";
import { tr } from "../i18n";
import type { ModelRules, RuleTrace, TargetScheme } from "../api/types";
import { ruleTraceUrl } from "../api/client";
import { isStaticData } from "../lib/dataMode";
import { associationStory } from "../lib/association";
import { classColor, NO_COLOR, weightLabel } from "../lib/classifier";
import { fmt, fmtFine, fmtNum, formatInstant, sameSampleText, unitLabel, missingText } from "../lib/format";
import { useZone } from "../lib/zone";
import { ClassChip } from "./ClassChip";
import { MixtureTrace } from "./MixtureTrace";
import { capFirst, condText, labelerFor, ruleSentence, sentenceText, useFeatureLabel, useNames } from "../lib/labels";

interface Props {
  entityName: string | null;
  state: AsyncState<RuleTrace>;
  rules: ModelRules | null;
  selectedRuleId: string | null;
  onSelectRule: (ruleId: string) => void;
  /** Opens the linguistic partitions of an antecedent's variable. */
  onSelectFeature?: (feature: string) => void;
  /** Classifier: the model's target scheme (class colours). */
  scheme?: TargetScheme | null;
  /** Classifier: the observed concentration (and its category) at the valid time, when the series has it. */
  observed?: { value: number | null; label: string | null } | null;
  /** The scheme is relative to a per-entity reference (NYC): only then can a zone be "sin referencia". */
  relativeScheme?: boolean;
}

const Num = ({ v, fine }: { v: number; fine?: boolean }) => <span data-raw={String(v)}>{(fine ? fmtFine : fmt)(v)}</span>;

/** A small bar next to a number: decoration for comparing rows; the number beside it is the information. */
const Bar = ({ frac }: { frac: number }) => (
  <span className="mini-bar" aria-hidden="true">
    <i style={{ width: `${Math.round(Math.min(1, Math.max(0, frac)) * 100)}%` }} />
  </span>
);

// Built at render (not at import): the language can change while the page is open.
const firingHelp = () => tr("cuánto encajan las entradas con los antecedentes de la regla.", "how well the inputs match the rule's antecedents.");
const weightHelp = () =>
  tr("sale de los datos de entrenamiento y refleja, entre otras cosas, con qué frecuencia aparece la clase de la regla (las clases raras pesan menos).",
    "comes from the training data and reflects, among other things, how often the rule's class appears (rare classes weigh less).");
const assocHelp = () => tr("activación × peso. Decide la categoría la regla con mayor asociación.", "activation × weight. The rule with the highest association decides the category.");
const WHY = () => tr("¿Por qué aquí?", "Why here?");

export function WhyHerePanel({ entityName, state, rules, selectedRuleId, onSelectRule, onSelectFeature, scheme, observed, relativeScheme = false }: Props) {
  const zone = useZone();
  const fromContext = useFeatureLabel();
  const names = useNames();
  const label = rules ? labelerFor(rules.variables) : fromContext;
  if (state.status === "idle") {
    return (
      <section className="why" aria-label="Why here?">
        <h2>{WHY()}</h2>
        <p className="muted">{tr("Elige una estación en el mapa o en la tabla para ver cómo se activan las reglas allí.", "Pick a station on the map or in the table to see how the rules fire there.")}</p>
      </section>
    );
  }
  if (state.status === "loading") {
    return (
      <section className="why" aria-label="Why here?" aria-busy="true">
        <h2>
          {WHY()} {entityName}
        </h2>
        <p role="status">{tr("Cargando la traza de reglas…", "Loading the rule trace…")}</p>
      </section>
    );
  }
  if (state.status === "error") {
    return (
      <section className="why" aria-label="Why here?">
        <h2>
          {WHY()} {entityName}
        </h2>
        <p role="alert" className="error">
          {tr("No se pudo cargar la traza: ", "Could not load the trace: ")}
          {state.error.message}
        </p>
      </section>
    );
  }

  const t = state.data;
  const missing = t.feature_values.filter((f) => f.value === null);
  // Winning-rule classifier: the output is a class label (never a number) decided by the rule of highest association.
  const isClass = t.inference.family === "winning_rule_classifier";
  // Contract v0.7: a mixture of rules also outputs a class label, but no rule decides it (MixtureTrace says how it adds up).
  const mixture = t.inference.family === "rule_mixture_classifier";
  const classOut = isClass || mixture;
  const noOutput = classOut ? (t.prediction.label ?? null) === null : t.prediction.value === null;
  const inferenceSkipped = noOutput && t.prediction.missing_reason === "missing_input";
  const defOf = (id: string) => rules?.rules.find((r) => r.rule_id === id);
  const colorOf = (label: string) => (scheme ? classColor(scheme, label) : NO_COLOR);
  const winningId = t.prediction.winning_rule_id ?? null;
  const weighting = isClass ? t.inference.rule_weighting : undefined;
  // Unweighted model: every weight is 1, so the association is the activation; ties go to the first rule in model order.
  const unweighted = isClass && weighting === "none";
  const order = new Map(t.rules.map((r, i) => [r.rule_id, i]));
  const byAssociation = isClass
    ? [...t.rules].sort((a, b) =>
        unweighted
          ? b.firing_strength - a.firing_strength || order.get(a.rule_id)! - order.get(b.rule_id)!
          : (b.association_degree ?? -1) - (a.association_degree ?? -1) || a.rule_id.localeCompare(b.rule_id),
      )
    : [];
  const story = isClass ? associationStory(t.rules, winningId, unweighted) : null;
  const maxWeight = Math.max(0, ...t.rules.map((r) => r.weight ?? 0));
  const maxAssociation = Math.max(0, ...t.rules.map((r) => r.association_degree ?? 0));
  const selected = t.rules.find((r) => r.rule_id === selectedRuleId) ?? null;
  const others = t.rules
    .filter((r) => r.rule_id !== selectedRuleId)
    .sort((a, b) => b.firing_strength - a.firing_strength || a.rule_id.localeCompare(b.rule_id));
  // The unit of the observed value is the task's (viajes, µg/m³), not the scheme's (NYC: percentiles).
  const unit = unitLabel(t.prediction.unit);
  const sameSample = Date.parse(t.issued_at_utc) === Date.parse(t.valid_at_utc);
  // The issue time of the trace itself, so the link returns this same trace.
  const traceUrl = ruleTraceUrl(t.entity_id, t.model_id, t.issued_at_utc);
  // Observed with no reference class: the zone has no reference for this hour of the week, so no class is published.
  const noReference =
    relativeScheme && classOut && t.prediction.label == null && t.prediction.missing_reason === "prediction_unavailable" &&
    observed != null && observed.value !== null && observed.label === null;

  return (
    <section className="why" aria-label="Why here?">
      <h2>
        {WHY()} <span className="entity">{entityName ?? t.entity_id}</span>
      </h2>
      <p className="muted">
        {sameSample ? (
          <>
            {tr("Muestra", "Sample")} {formatInstant(t.issued_at_utc, zone)} · {sameSampleText()}
          </>
        ) : (
          tr(`Emisión ${formatInstant(t.issued_at_utc, zone)} · válido ${formatInstant(t.valid_at_utc, zone)}`, `Issue ${formatInstant(t.issued_at_utc, zone)} · valid ${formatInstant(t.valid_at_utc, zone)}`)
        )}{" "}
        · {tr("modelo", "model")} <code>{t.model_id}</code>
      </p>
      {/* a static site has no API: the request would mean nothing there */}
      {!isStaticData() && (
        <p className="muted trace-request">
          {tr("Petición reproducible:", "Reproducible request:")}{" "}
          <a href={traceUrl} target="_blank" rel="noreferrer" data-testid="trace-request">
            <code>GET {traceUrl}</code>
          </a>
        </p>
      )}

      <h3>{tr("Entradas", "Inputs")}</h3>
      <table className="plain">
        <thead>
          <tr>
            <th scope="col">Variable</th>
            <th scope="col">{tr("Valor", "Value")}</th>
            <th scope="col">{tr("Observado (UTC)", "Observed (UTC)")}</th>
          </tr>
        </thead>
        <tbody>
          {t.feature_values.map((f) => (
            <tr key={f.feature}>
              <th scope="row">{label(f.feature)}</th>
              <td>
                {f.value === null ? (
                  <span className="missing-text">
                    {tr("sin dato", "no data")}
                    {f.missing_reason ? ` · ${missingText(f.missing_reason)}` : ""}
                  </span>
                ) : (
                  <>
                    <span data-raw={String(f.value)}>{fmtNum(f.value)}</span> {f.unit ? unitLabel(f.unit) : ""}
                  </>
                )}
              </td>
              <td>{f.observed_at_utc ? formatInstant(f.observed_at_utc, zone) : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {inferenceSkipped && (
        <p role="alert" className="notice">
          {tr(`No se ejecutó la inferencia: falta ${missing.map((f) => label(f.feature)).join(", ")}.`, `Inference was not run: missing ${missing.map((f) => label(f.feature)).join(", ")}.`)}
        </p>
      )}

      {!inferenceSkipped && (
        <>
          <h3>{tr("Regla seleccionada", "Selected rule")}</h3>
          {selected ? (
            <div className="selected-rule">
              <p>
                <strong>{selected.rule_id}</strong> <span className="muted">{defOf(selected.rule_id) ? sentenceText(ruleSentence(defOf(selected.rule_id)!, label, scheme, names)) : ""}</span>
              </p>
              <table className="plain">
                <thead>
                  <tr>
                    <th scope="col">{tr("Antecedente", "Antecedent")}</th>
                    <th scope="col">μ</th>
                    <th scope="col">{tr("Modificador", "Modifier")}</th>
                    <th scope="col">{tr("μ efectiva", "effective μ")}</th>
                  </tr>
                </thead>
                <tbody>
                  {selected.antecedents.map((a) => (
                    <tr key={a.feature}>
                      <th scope="row" title={names.detail(a.feature, a) ?? undefined}>
                        {onSelectFeature ? (
                          <button
                            type="button"
                            className="link"
                            onClick={() => onSelectFeature(a.feature)}
                            aria-label={tr(`${condText(a, label, names)}: ver particiones de ${label(a.feature)}`, `${condText(a, label, names)}: show partitions of ${label(a.feature)}`)}
                          >
                            {capFirst(condText(a, label, names))}
                          </button>
                        ) : (
                          <>
                            {capFirst(condText(a, label, names))}
                          </>
                        )}
                      </th>
                      <td>
                        <Num v={a.membership} />
                      </td>
                      <td>{a.modifier ?? "—"}</td>
                      <td>{a.modifier !== null && a.modifier !== undefined ? <Num v={a.effective_membership} /> : "="}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p>
                <span title="firing_strength">{tr("Activación", "Activation")}</span>: <strong><Num v={selected.firing_strength} /></strong>
                {isClass && !unweighted && selected.weight != null && (
                  <>
                    {" "}
                    · {weightLabel()}: <Num v={selected.weight} fine />
                  </>
                )}
                {isClass && !unweighted && selected.association_degree != null && (
                  <>
                    {" "}
                    · {tr("grado de asociación (activación × peso):", "association degree (activation × weight):")} <strong><Num v={selected.association_degree} fine /></strong>
                  </>
                )}
                {!classOut && selected.effective_firing !== selected.firing_strength && (
                  <>
                    {" "}
                    · {tr(`tras el modo de reglas del modelo (${t.inference.rule_mode}):`, `after the model's rule mode (${t.inference.rule_mode}):`)} <Num v={selected.effective_firing} />
                  </>
                )}
              </p>
              <p className="muted">
                {tr(<>Operador del modelo (t-norma, <code>inference.tnorm</code>): <code>{t.inference.tnorm}</code> · familia <code>{t.inference.family}</code> · ex_fuzzy {t.inference.exfuzzy_version}</>,
                  <>Model operator (t-norm, <code>inference.tnorm</code>): <code>{t.inference.tnorm}</code> · family <code>{t.inference.family}</code> · ex_fuzzy {t.inference.exfuzzy_version}</>)}
              </p>
            </div>
          ) : (
            <p className="muted">{tr("Selecciona una regla en el panel para ver las μ de sus antecedentes.", "Select a rule in the panel to see the μ of its antecedents.")}</p>
          )}
        </>
      )}

      {classOut ? (
        <>
          <h3>{tr("Categoría prevista", "Predicted category")}</h3>
          {t.prediction.label ? (
            <p data-testid="predicted-label" data-class={t.prediction.label}>
              <ClassChip label={t.prediction.label} color={colorOf(t.prediction.label)} />{" "}
              <span className="muted">{tr(`válido ${formatInstant(t.valid_at_utc, zone)}`, `valid ${formatInstant(t.valid_at_utc, zone)}`)}</span>
            </p>
          ) : (
            noReference ? (
              <p className="missing-text" data-testid="no-reference">
                {tr("sin referencia (esta zona tuvo poco volumen a esa hora de la semana en el periodo de entrenamiento y no tiene nivel de referencia, así que no se publica categoría ni se compara con «normal»). Las reglas de abajo son lo que da el motor con estas entradas.",
                  "no reference (this zone had too little volume at that hour of the week in the training period to have a reference level, so no category is published and nothing is compared with “normal”). The rules below are what the engine outputs for these inputs.")}
              </p>
            ) : (
              <p className="missing-text">
                {tr("sin predicción", "no prediction")}
                {t.prediction.missing_reason === "prediction_unavailable" ? tr(" (con las entradas presentes ninguna regla se activó, así que no hay categoría)", " (no rule fired with the inputs present, so there is no category)") : t.prediction.missing_reason ? ` · ${missingText(t.prediction.missing_reason)}` : ""}
              </p>
            )
          )}
          {winningId && (
            <p data-testid="winning-rule-note">
              {unweighted
                ? tr(<>La categoría la decidió <strong>{winningId}</strong>, la regla con mayor activación (ante un empate, la primera en el orden del modelo).</>, <>Decided by <strong>{winningId}</strong>, the rule with the highest activation (on a tie, the first in the model&apos;s order).</>)
                : tr(<>La categoría la decidió <strong>{winningId}</strong>, la regla con mayor grado de asociación (activación × peso).</>, <>Decided by <strong>{winningId}</strong>, the rule with the highest association degree (activation × weight).</>)}
            </p>
          )}
          {observed && (observed.value !== null || observed.label !== null) && (
            <p data-testid="observed-class">
              {tr("Observado a la hora de validez:", "Observed at the valid time:")}{" "}
              {observed.value !== null ? (
                <strong data-raw={String(observed.value)}>
                  {fmtNum(observed.value)} {unit}
                </strong>
              ) : (
                tr("sin valor", "no value")
              )}
              {observed.label && (
                <>
                  {" → "}
                  <ClassChip label={observed.label} color={colorOf(observed.label)} />
                </>
              )}
            </p>
          )}
        </>
      ) : (
        <>
          <h3>{tr("Predicción del modelo", "Model prediction")}</h3>
          {t.prediction.value === null ? (
            <p className="missing-text">
              {tr("sin predicción", "no prediction")}
              {t.prediction.missing_reason ? ` · ${missingText(t.prediction.missing_reason)}` : ""}
            </p>
          ) : (
            <p>
              <strong data-raw={String(t.prediction.value)}>
                {fmtNum(t.prediction.value)} {unit}
              </strong>{" "}
              <span className="muted">{sameSample ? tr("estimado con las demás determinaciones de la misma muestra", "estimated from the other determinations of the same sample") : tr(`válido ${formatInstant(t.valid_at_utc, zone)}`, `valid ${formatInstant(t.valid_at_utc, zone)}`)}</span>
            </p>
          )}
        </>
      )}
      {t.prediction.fallback_used && (
        <p role="alert" className="notice">
          {tr(<>Valor de respaldo (<code>{t.inference.fallback}</code>): ninguna regla se activó, así que la salida no procede de las reglas.</>, <>Fallback value (<code>{t.inference.fallback}</code>): no rule fired, so the output doesn&apos;t come from the rules.</>)}
        </p>
      )}

      {!inferenceSkipped && isClass && (
        <>
          <h3>{unweighted ? tr("Reglas, por activación", "Rules, by activation") : tr("Reglas, por grado de asociación", "Rules, by association degree")}</h3>
          {story && (
            <div className="story" data-testid="association-story">
              <p data-testid="story-winner">{story.winner}</p>
              {story.loser && <p data-testid="story-loser">{story.loser}</p>}
            </div>
          )}
          <table className="plain association" aria-label={unweighted ? tr("Reglas por activación", "Rules by activation") : tr("Reglas por grado de asociación", "Rules by association degree")}>
            <thead>
              <tr>
                <th scope="col">{tr("Regla", "Rule")}</th>
                <th scope="col">{tr("Categoría", "Category")}</th>
                <th scope="col" title={tr(`Activación (0–1): ${firingHelp()}`, `Activation (0–1): ${firingHelp()}`)}>
                  {tr("Activación", "Activation")} <span className="muted">{tr("cuánto se activa", "how much it fires")}</span>
                </th>
                {!unweighted && (
                  <>
                    <th scope="col" title={tr(`Peso de la regla${weighting ? ` (${weighting})` : ""}: ${weightHelp()}`, `Rule weight${weighting ? ` (${weighting})` : ""}: ${weightHelp()}`)}>
                      {weightLabel()} <span className="muted">{tr("cuánto pesa", "how much it weighs")}</span>
                    </th>
                    <th scope="col" title={tr(`Asociación: ${assocHelp()}`, `Association: ${assocHelp()}`)}>
                      {tr("Asociación", "Association")} <span className="muted">{tr("decide", "decides")}</span>
                    </th>
                  </>
                )}
              </tr>
            </thead>
            <tbody>
              {byAssociation.map((r) => {
                const term = defOf(r.rule_id)?.consequent.term;
                const winner = r.rule_id === winningId;
                return (
                  <tr key={r.rule_id} data-rule={r.rule_id} data-winner={winner ? "true" : undefined} aria-current={winner ? "true" : undefined}>
                    <th scope="row">
                      <RuleRef id={r.rule_id} className="link" onClick={() => onSelectRule(r.rule_id)} buttonProps={{ "aria-label": tr(`Seleccionar regla ${r.rule_id}`, `Select rule ${r.rule_id}`) }}>
                        {r.rule_id}
                      </RuleRef>
                      {winner && <span className="badge-win">{tr("ganadora", "winner")}</span>}
                      {r.rule_id === selectedRuleId && <span className="muted">{tr(" (seleccionada)", " (selected)")}</span>}
                    </th>
                    <td>{term ? <ClassChip label={term} color={colorOf(term)} /> : "—"}</td>
                    <td>
                      <Num v={r.firing_strength} />
                      <Bar frac={r.firing_strength} />
                    </td>
                    {!unweighted && (
                    <>
                    <td>
                      {r.weight == null ? "—" : (
                        <>
                          <Num v={r.weight} fine />
                          <Bar frac={maxWeight > 0 ? r.weight / maxWeight : 0} />
                        </>
                      )}
                    </td>
                    <td>
                      {r.association_degree == null ? "—" : (
                        <>
                          <Num v={r.association_degree} fine />
                          <Bar frac={maxAssociation > 0 ? r.association_degree / maxAssociation : 0} />
                        </>
                      )}
                    </td>
                    </>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
          {unweighted ? (
            <p className="muted small" data-testid="unweighted-note">
              {tr("Las reglas de este modelo no llevan peso. Decide la que más se activa y, ante un empate, la primera en el orden del modelo, que es el orden de esta tabla.",
                "This model's rules carry no weight. The one that fires most decides, and on a tie the first in the model's order wins; this table follows that order.",
              )}
            </p>
          ) : (
          <details className="column-help">
            <summary>{tr("Cómo leer las tres columnas", "How to read the three columns")}</summary>
            <ul className="plain-list" data-testid="column-help">
              <li>{tr(<><strong>Activación</strong> (0–1, escala absoluta de la barra): </>, <><strong>Activation</strong> (0–1, absolute scale of the bar): </>)}{firingHelp()}</li>
              <li><strong>{weightLabel()}</strong>{tr(" (barra relativa al mayor peso de la tabla): ", " (bar relative to the largest weight in the table): ")}{weightHelp()}</li>
              <li>{tr(<><strong>Asociación</strong> (barra relativa a la mayor asociación de la tabla): </>, <><strong>Association</strong> (bar relative to the largest association in the table): </>)}{assocHelp()}</li>
            </ul>
          </details>
          )}
        </>
      )}

      {!inferenceSkipped && mixture && scheme && <MixtureTrace trace={t} scheme={scheme} onSelectRule={onSelectRule} selectedRuleId={selectedRuleId} />}

      {!inferenceSkipped && !classOut && (
        <>
          <h3>{selected ? tr("Otras reglas, por activación", "Other rules, by activation") : tr("Reglas, por activación", "Rules, by activation")}</h3>
          <ol className="ranking">
            {others.map((r) => (
              <li key={r.rule_id}>
                <RuleRef id={r.rule_id} className="ranking-rule" onClick={() => onSelectRule(r.rule_id)} buttonProps={{ "aria-label": tr(`Seleccionar regla ${r.rule_id}`, `Select rule ${r.rule_id}`) }}>
                  {r.rule_id}
                </RuleRef>{" "}
                <Num v={r.firing_strength} />
              </li>
            ))}
          </ol>
        </>
      )}

      {mixture ? null : unweighted ? (
        <p className="muted note">
          {tr("La activación solo sirve para ordenar las reglas y elegir una categoría.",
            "Activation only ranks the rules to pick a category.")}
        </p>
      ) : isClass ? (
        <p className="muted note">
          {tr("El grado de asociación (activación × peso) solo ordena las reglas para elegir una categoría.",
            "The association degree (activation × weight) only ranks the rules to pick a category.")}
        </p>
      ) : (
      <p className="muted note">
        {tr("La activación de una regla dice cuánto encajan las entradas con sus antecedentes.",
          "A rule's activation says how well the inputs match its antecedents.")}
      </p>
      )}
      {t.quality?.warnings && t.quality.warnings.length > 0 && (
        <p className="muted">{tr(`Avisos de calidad: ${t.quality.warnings.join("; ")}`, `Quality warnings: ${t.quality.warnings.join("; ")}`)}</p>
      )}
    </section>
  );
}
