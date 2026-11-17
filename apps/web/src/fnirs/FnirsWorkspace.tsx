import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { DomainInfo, FnirsModelCard, ModelRules, MontageResponse, TaskInfo, TrialRecord, TrialTrace } from "../api/types";
import { Card, PageHead, TaskLine } from "../components/Card";
import { ClassChip } from "../components/ClassChip";
import { ClassWeights, WeightKey } from "../components/ClassWeights";
import { MixtureTrace } from "../components/MixtureTrace";
import { Naming } from "../components/Naming";
import { RuleLookupProvider } from "../components/RuleRef";
import { RuleSentenceView } from "../components/RuleSentenceView";
import { RuleTermsPlot } from "../components/RuleTermsPlot";
import { StateMessage } from "../components/StateMessage";
import type { Provenance } from "../hooks/useProvenance";
import { useAsync } from "../hooks/useAsync";
import { localized, tr } from "../i18n";
import { classColor } from "../lib/classifier";
import { dec, fmt, pct } from "../lib/format";
import { fullCondition, ruleSentence, useFeatureLabel, useNames } from "../lib/labels";
import { domainUi } from "../lib/domainUi";
import { weightScale } from "../lib/mixture";
import { bloodFill, divergingBin, DivergingLegend, MembershipLegend, membershipBin, ScalpMap, ruleWedges, signalColor, type ChannelMark } from "./ScalpMap";
import { PerformanceTab } from "./PerformanceTab";
import { TrialMatrix } from "./TrialMatrix";
import taskFigure from "../assets/fnirs/shin2018-fig1a.jpg";

type View = "rule" | "HbO" | "HbR";
export type FnirsTab = "reglas" | "canales" | "rendimiento";

interface Props {
  domain: DomainInfo;
  task: TaskInfo;
  tab: FnirsTab;
  onTab: (tab: FnirsTab) => void;
  onProvenance: (p: Partial<Provenance>) => void;
}

/**
 * A montage task (contract v0.9): no map and no time. Two tabs over the same loaded model: *Reglas* (the task, where the
 * rules look, every rule, the report) and *Canales* (every trial, the scalp of one trial, why it got its class). The
 * model and the choices (trial, rule, view) live here, so switching tabs refetches nothing and keeps the selection.
 */
export function FnirsWorkspace({ task, tab, onTab, onProvenance }: Props) {
  const modelId = task.model_id ?? "";
  const rules = useAsync((s) => api.modelRules(modelId, s), [modelId]);
  const montage = useAsync((s) => api.fnirsMontage(task.task_id, s), [task.task_id]);
  const card = useAsync((s) => api.fnirsCard(modelId, s), [modelId]);
  const trials = useAsync((s) => api.fnirsTrials(modelId, s), [modelId]);
  const [sampleId, setSampleId] = useState<string>("");
  const [chosenRule, setChosenRule] = useState<string | null>(null);
  const [view, setView] = useState<View>("rule");

  useEffect(() => {
    if (card.status !== "ok" || montage.status !== "ok") return;
    const c = card.data;
    onProvenance({
      synthetic: c.synthetic === true,
      dataVersion: c.data_version,
      modelId: c.model_id,
      geometrySource: montage.data.source_url,
      exfuzzyVersion: c.exfuzzy_version,
      schemeName: localized(c.target_scheme.name, c.target_scheme.name_en ?? null),
      schemeUrl: c.target_scheme.source_url,
      schemeNames: null,
      attribution: c.attribution ?? [],
    });
  }, [card, montage, onProvenance]);

  const failed = [rules, montage, card, trials].find((x) => x.status === "error");
  if (failed && failed.status === "error") {
    return <StateMessage kind="error" onRetry={failed.reload}>{failed.error.message}</StateMessage>;
  }
  if (rules.status !== "ok" || montage.status !== "ok" || card.status !== "ok" || trials.status !== "ok") {
    return <StateMessage kind="loading">{tr("Cargando el modelo fNIRS…", "Loading the fNIRS model…")}</StateMessage>;
  }
  const scheme = card.data.target_scheme;
  const sample = sampleId || trials.data.trials[0]?.sample_id || "";
  const openRule = (id: string) => {
    setChosenRule(id);
    setView("rule");
    onTab("canales");
  };
  return (
    <Naming variables={rules.data.variables} scheme={scheme} rules={rules.data.rules}>
      <RuleLookupProvider model={rules.data} importance={null} scheme={scheme} unit={scheme.unit} colourWithoutRanking>
        {tab === "rendimiento" ? (
          <PerformanceTab card={card.data} rules={rules.data} context={localized(task.territory_title ?? task.task_id, task.territory_title_en ?? null)} />
        ) : tab === "reglas" ? (
          <RulesTab rules={rules.data} montage={montage.data} card={card.data} trials={trials.data.trials} onOpenRule={openRule} onOpenChannels={() => onTab("canales")} />
        ) : (
          <ChannelsTab
            rules={rules.data} montage={montage.data} card={card.data} trials={trials.data.trials}
            sampleId={sample} onTrial={setSampleId} chosenRule={chosenRule} onRule={setChosenRule} view={view} onView={setView}
          />
        )}
      </RuleLookupProvider>
    </Naming>
  );
}

/** What the subjects did and what the model is asked, in plain words (Shin et al. 2018, Scientific Data 5:180003). */
function TaskIntro({ card, trials }: { card: FnirsModelCard; trials: readonly TrialRecord[] }) {
  const names = useNames();
  const scheme = card.target_scheme;
  const [low, high] = [scheme.classes[0]!, scheme.classes[scheme.classes.length - 1]!];
  const subjects = new Set(trials.map((t) => t.subject)).size;
  return (
    <Card title={tr("La tarea", "The task")} className="fnirs-task">
      <div className="fnirs-task-grid">
        <div>
          <h3>{tr("Qué hacía cada persona", "What each person did")}</h3>
          <p>
            {tr(`${subjects} personas hicieron una tarea de memoria: durante bloques de 40 s veían un dígito cada 2 s y pulsaban un botón para decir si era un objetivo. Cada persona hizo 27 bloques en tres sesiones, unos fáciles y otros difíciles.`,
              `${subjects} people did a memory task: in blocks of 40 s they saw a digit every 2 s and pressed a button to say whether it was a target. Each person did 27 blocks in three sessions, some easy and some hard.`)}
          </p>
          <figure className="fnirs-task-figure">
            <img src={taskFigure} width={756} height={487} loading="lazy" decoding="async"
              alt={tr("Secuencia de la tarea: una instrucción de 2 s, dígitos de 0,5 s seguidos de una cruz de 1,5 s, la palabra STOP y 20 s de reposo.", "Sequence of the task: a 2 s instruction, digits of 0.5 s each followed by a 1.5 s cross, the word STOP and 20 s of rest.")} />
            <figcaption className="muted small">
              {tr("Cómo se presentaba la tarea: una instrucción, un dígito cada 2 s durante 40 s, «STOP» y 20 s de reposo. ", "How the task was presented: an instruction, a digit every 2 s for 40 s, «STOP» and 20 s of rest. ")}
              <a href="https://doi.org/10.1038/sdata.2018.3" target="_blank" rel="noopener noreferrer">Shin et al. (2018), Scientific Data 5:180003</a>
              {tr(", figura 1a (recortada). ", ", figure 1a (cropped). ")}
              <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener noreferrer">CC BY 4.0</a>.
            </figcaption>
          </figure>
          <ul className="fnirs-task-levels">
            <li><ClassChip label={low.label} color={classColor(scheme, low.label)} />{" "}{tr("Tarea fácil: basta con reconocer cada dígito, sin recordar los anteriores.", "Easy task: each digit only has to be recognised, with no earlier digits to remember.")}</li>
            <li><ClassChip label={high.label} color={classColor(scheme, high.label)} />{" "}{tr("Tarea difícil: hay que decir si cada dígito es igual al de 2 o 3 posiciones antes, así que hay que recordar los últimos.", "Hard task: say whether each digit equals the one 2 or 3 positions back, so the last digits have to be held in memory.")}</li>
          </ul>
        </div>
        <div>
          <h3>{tr("Qué mide fNIRS", "What fNIRS measures")}</h3>
          <p>
            {tr("36 canales de luz infrarroja sobre el cuero cabelludo miden cuánto cambia la oxihemoglobina (HbO) y la desoxihemoglobina (HbR) en la corteza que tienen debajo: el rastro de la actividad de esa zona.",
              "36 near-infrared channels on the scalp measure how much oxyhaemoglobin (HbO) and deoxyhaemoglobin (HbR) change in the cortex beneath them: the trace of that area's activity.")}
          </p>
          <h3>{tr("Qué hace el modelo", "What the model does")}</h3>
          <p>
            {tr(`Para cada bloque toma el cambio medio de HbO y HbR de cada canal entre los segundos 10 y 40, respecto al reposo justo antes, y dice si el bloque era de ${names.cls(low.label).toLowerCase()} o de ${names.cls(high.label).toLowerCase()}. Lo dice con reglas que puedes leer.`,
              `For each block it takes the mean change of HbO and HbR at each channel from second 10 to 40, relative to the rest just before, and says whether the block was ${names.cls(low.label).toLowerCase()} or ${names.cls(high.label).toLowerCase()}. It says so with rules you can read.`)}
          </p>
        </div>
      </div>
    </Card>
  );
}

const ruleClassColor = (scheme: FnirsModelCard["target_scheme"], rule: ModelRules["rules"][number]): string =>
  rule.strongest_class ? classColor(scheme, rule.strongest_class) : "var(--slate)";

/** Channel id of each input. */
const channelOf = (montage: MontageResponse): Map<string, { channel: string; signal: string }> =>
  new Map(montage.channels.flatMap((c) => c.inputs.map((i) => [i.feature, { channel: c.channel_id, signal: i.signal }] as const)));

function RulesTab({ rules, montage, card, trials, onOpenRule, onOpenChannels }: {
  rules: ModelRules; montage: MontageResponse; card: FnirsModelCard; trials: readonly TrialRecord[];
  onOpenRule: (id: string) => void; onOpenChannels: () => void;
}) {
  const label = useFeatureLabel();
  const names = useNames();
  const scheme = card.target_scheme;
  const where = useMemo(() => channelOf(montage), [montage]);
  const wedges = ruleWedges(rules, montage, (r) => ruleClassColor(scheme, r), (r, a) => `${r.rule_id}: ${fullCondition(a, label, names)}`);
  const scale = weightScale(rules.rules);
  const tauKey = Object.keys(rules.rules[0]?.metrics ?? {}).find((k) => k.startsWith("activation_frequency_tau"));
  const tau = tauKey ? Number(tauKey.replace("activation_frequency_tau", "")) : null;
  return (
    <div className="page fnirs" data-testid="fnirs-rules-tab">
      <TaskLine>{domainUi("fnirs").task?.({ hours: 0, predicts: "", classes: "" })}</TaskLine>
      <PageHead title={tr("Las reglas del modelo fNIRS", "The rules of the fNIRS model")} accent="fNIRS">
        {tr(`${rules.rules.length} reglas deciden si un bloque de la tarea era de ${names.cls(scheme.classes[0]!.label).toLowerCase()} o de ${names.cls(scheme.classes[scheme.classes.length - 1]!.label).toLowerCase()}, mirando unos pocos canales cada una. Aquí están todas; en `,
          `${rules.rules.length} rules decide whether a block of the task was ${names.cls(scheme.classes[0]!.label).toLowerCase()} or ${names.cls(scheme.classes[scheme.classes.length - 1]!.label).toLowerCase()}, each looking at a few channels. Here they all are; in `)}
        <button type="button" className="link" onClick={onOpenChannels}>{tr("Canales", "Channels")}</button>
        {tr(" puedes comprobarlas ensayo a ensayo.", " you can check them trial by trial.")}
      </PageHead>

      <TaskIntro card={card} trials={trials} />

      <Card title={tr("Dónde miran las reglas", "Where the rules look")} subtitle={tr("Cada canal que usa una regla lleva una porción por regla, del color de la carga que esa regla apoya más.", "Each channel a rule uses carries one slice per rule, in the colour of the load that rule supports most.")}>
        <div className="fnirs-overview">
          <ScalpMap channels={montage.channels} wedges={wedges} label={tr("Canales que usan las reglas", "Channels the rules use")} testId="rules-scalp" />
          <div className="fnirs-overview-side">
            <ul className="fnirs-overview-legend">
              {scheme.classes.map((c) => (
                <li key={c.label}>
                  <ClassChip label={c.label} color={classColor(scheme, c.label)} />{" "}
                  <span className="muted small">{tr(`${rules.rules.filter((r) => r.strongest_class === c.label).length} reglas la apoyan`, `${rules.rules.filter((r) => r.strongest_class === c.label).length} rules support it`)}</span>
                </li>
              ))}
            </ul>
            <ul className="fnirs-channel-list" data-testid="rule-channels">
              {[...wedges.entries()].map(([ch, ws]) => (
                <li key={ch}>
                  <strong>{ch}</strong>{" "}
                  {ws.map((w) => (
                    <span key={w.ruleId} className="fnirs-channel-rule" title={w.text}>
                      <span className="class-swatch" style={{ background: w.color }} aria-hidden="true" />
                      {w.ruleId}
                    </span>
                  ))}
                </li>
              ))}
            </ul>
            <p className="muted small">
              {tr(`Las reglas usan ${wedges.size} de los ${montage.channels.length} canales. Las manchas grises agrupan los canales por cercanía (las seis zonas del montaje); el resto de canales son los puntos pequeños.`,
                `The rules use ${wedges.size} of the ${montage.channels.length} channels. The grey patches group the channels by proximity (the six areas of the montage); the other channels are the small dots.`)}
            </p>
          </div>
        </div>
      </Card>

      <Card title={tr(`Las ${rules.rules.length} reglas`, `The ${rules.rules.length} rules`)} subtitle={tr("No decide una sola regla: cada una suma a cada carga su peso por cuánto se cumple, y gana la carga con más total.", "No single rule decides: each adds its weight to each load in proportion to how much it holds, and the load with the largest total wins.")}>
        <WeightKey note={false} />
        <ol className="fnirs-rule-grid" data-testid="fnirs-rule-grid">
          {rules.rules.map((r) => {
            const marks = new Map<string, ChannelMark>();
            for (const a of r.antecedents) {
              const w = where.get(a.feature);
              if (w) marks.set(w.channel, { bin: 4, fill: signalColor(w.signal), detail: fullCondition(a, label, names), tag: w.signal });
            }
            const freq = tauKey ? r.metrics?.[tauKey] : undefined;
            return (
              <li key={r.rule_id} className="fnirs-rule-tile" data-rule={r.rule_id} style={{ ["--rule-class" as string]: ruleClassColor(scheme, r) }}>
                <div className="fnirs-rule-top">
                  <h3>{r.rule_id}</h3>
                  {r.strongest_class && <ClassChip label={r.strongest_class} color={classColor(scheme, r.strongest_class)} />}
                </div>
                <div className="fnirs-rule-body">
                  <ScalpMap channels={montage.channels} marks={marks} mini label={tr(`Canales de la regla ${r.rule_id}`, `Channels of rule ${r.rule_id}`)} testId={`mini-${r.rule_id}`} />
                  <RuleSentenceView sentence={ruleSentence(r, label, scheme, names)} testId={`tile-sentence-${r.rule_id}`} />
                </div>
                {r.class_weights_centred && (
                  <ClassWeights values={r.class_weights_centred} scheme={scheme} scale={scale} strongest={r.strongest_class ?? null} label={tr(`Pesos de ${r.rule_id}`, `Weights of ${r.rule_id}`)} testId={`weights-${r.rule_id}`} />
                )}
                {freq !== undefined && tau !== null && (
                  <p className="muted small" data-raw={String(freq)}>
                    {tr(`Se cumple (grado ≥ ${dec(tau, 1)}) en el ${pct(freq)} de los bloques de train.`, `Holds (degree ≥ ${dec(tau, 1)}) in ${pct(freq)} of the train blocks.`)}
                  </p>
                )}
                <details className="fnirs-terms">
                  <summary>{tr("Qué significan sus términos", "What its terms mean")}</summary>
                  <RuleTermsPlot rule={r} variables={rules.variables} />
                </details>
                <button type="button" className="link link--tab" onClick={() => onOpenRule(r.rule_id)}>{tr("Verla en los ensayos", "See it in the trials")}</button>
              </li>
            );
          })}
        </ol>
      </Card>

    </div>
  );
}

function ChannelsTab({ rules, montage, card, trials, sampleId, onTrial, chosenRule, onRule, view, onView }: {
  rules: ModelRules; montage: MontageResponse; card: FnirsModelCard; trials: readonly TrialRecord[];
  sampleId: string; onTrial: (id: string) => void; chosenRule: string | null; onRule: (id: string) => void;
  view: View; onView: (v: View) => void;
}) {
  const names = useNames();
  const scheme = card.target_scheme;
  const subjects = useMemo(() => {
    const seen = new Map<number, "train" | "test">();
    for (const t of trials) if (!seen.has(t.subject)) seen.set(t.subject, t.split);
    return [...seen.entries()].map(([subject, split]) => ({ subject, split }));
  }, [trials]);
  const record = trials.find((t) => t.sample_id === sampleId) ?? null;
  const subject = record?.subject ?? subjects[0]?.subject ?? 0;
  const ofSubject = trials.filter((t) => t.subject === subject);
  const trace = useAsync((s) => api.fnirsTrace(card.model_id, sampleId, s), [card.model_id, sampleId], sampleId !== "");
  const pickSubject = (s: number) => onTrial(trials.find((t) => t.subject === s)?.sample_id ?? "");
  const t = trace.status === "ok" ? trace.data : null;
  // the rule shown on the scalp: the one picked, else the one that adds the most to this trial's prediction, else the first
  const ruleId = chosenRule ?? t?.prediction.top_rule_id ?? t?.prediction.winning_rule_id ?? rules.rules[0]?.rule_id ?? null;
  const selectRule = (id: string) => {
    onRule(id);
    onView("rule");
  };
  return (
    <div className="page fnirs" data-testid="fnirs-workspace">
      <PageHead title={tr("Comprueba un ensayo", "Check a trial")} accent={tr("un ensayo", "a trial")}>
        {tr("Cada bloque de la tarea es un ensayo. Elige uno para ver qué midieron sus canales, cuánto se cumple cada regla y por qué el modelo le dio su carga.",
          "Each block of the task is a trial. Pick one to see what its channels measured, how much each rule holds and why the model gave it its load.")}
      </PageHead>

      <div className="fnirs-explore">
        <Card title={tr("Todos los ensayos", "All trials")} subtitle={tr(
          `Un sujeto por fila, un bloque por columna. Los de test (${card.split.test_subjects.join(", ")}) no se usaron para ajustar el modelo.`,
          `One subject per row, one block per column. The test subjects (${card.split.test_subjects.join(", ")}) were not used to fit the model.`,
        )}>
          <TrialMatrix trials={trials} scheme={scheme} sampleId={sampleId} onTrial={onTrial} />
          <div className="fnirs-picker-narrow">
            <TrialPicker subjects={subjects} subject={subject} onSubject={pickSubject} trials={ofSubject} sampleId={sampleId} onTrial={onTrial} testSubjects={card.split.test_subjects} scheme={scheme} />
          </div>
        </Card>
        <Card title={tr("El cuero cabelludo", "The scalp")} subtitle={record ? trialTitle(record, names.cls(record.observed_label)) : undefined}>
          <div className="segmented" role="group" aria-label={tr("Qué muestran los canales", "What the channels show")}>
            {(["rule", "HbO", "HbR"] as const).map((v) => (
              <button key={v} type="button" aria-pressed={view === v} onClick={() => onView(v)}>
                {v === "rule" ? tr(`Regla ${ruleId ?? ""}`, `Rule ${ruleId ?? ""}`) : <><span className={`signal-swatch signal-swatch--${v}`} aria-hidden="true" />{v}</>}
              </button>
            ))}
          </div>
          {trace.status === "error" && <StateMessage kind="error" onRetry={trace.reload}>{trace.error.message}</StateMessage>}
          {t ? <Scalp trace={t} montage={montage} rules={rules} view={view} ruleId={ruleId} /> : trace.status !== "error" && <StateMessage kind="loading">{tr("Cargando el ensayo…", "Loading the trial…")}</StateMessage>}
        </Card>
      </div>

      <div className="fnirs-main">
        <Card title={tr("Por qué esta carga", "Why this load")} level={2}>
          {t && record ? <TrialVerdict trace={t} record={record} rules={rules} scheme={scheme} ruleId={ruleId} onSelectRule={selectRule} /> : null}
        </Card>
      <Card title={tr("Las reglas en este ensayo", "The rules in this trial")} subtitle={tr("Cuánto se cumple cada una en el ensayo elegido.", "How much each one holds in the chosen trial.")}>
        <RuleList rules={rules} trace={t} selected={view === "rule" ? ruleId : null} onSelect={selectRule} />
      </Card>
      </div>
    </div>
  );
}

/** «Sujeto 3, bloque 1 (carga alta)»: the block's actual load by its shown name (the dataset's condition is not shown). */
const trialTitle = (r: TrialRecord, load: string): string =>
  tr(`Sujeto ${r.subject}, bloque ${r.trial} (${load.toLowerCase()})`, `Subject ${r.subject}, block ${r.trial} (${load.toLowerCase()})`);

function TrialPicker({ subjects, subject, onSubject, trials, sampleId, onTrial, testSubjects, scheme }: {
  subjects: readonly { subject: number; split: "train" | "test" }[];
  subject: number;
  onSubject: (s: number) => void;
  trials: readonly TrialRecord[];
  sampleId: string;
  onTrial: (id: string) => void;
  testSubjects: readonly number[];
  scheme: FnirsModelCard["target_scheme"];
}) {
  const names = useNames();
  const split = subjects.find((s) => s.subject === subject)?.split ?? "test";
  return (
    <div className="fnirs-picker" data-testid="trial-picker">
      <label>
        {tr("Sujeto", "Subject")}{" "}
        <select value={subject} onChange={(e) => onSubject(Number(e.target.value))} data-testid="subject-select">
          <optgroup label={tr(`Test (${testSubjects.length} sujetos que el modelo no vio)`, `Test (${testSubjects.length} subjects the model never saw)`)}>
            {subjects.filter((s) => s.split === "test").map((s) => <option key={s.subject} value={s.subject}>{s.subject}</option>)}
          </optgroup>
          <optgroup label={tr("Train (dentro de la muestra)", "Train (in-sample)")}>
            {subjects.filter((s) => s.split === "train").map((s) => <option key={s.subject} value={s.subject}>{s.subject}</option>)}
          </optgroup>
        </select>
      </label>
      <span className="badge" data-testid="split-badge">{split === "test" ? "test" : tr("train · dentro de la muestra", "train · in-sample")}</span>
      <div className="fnirs-blocks" role="group" aria-label={tr("Bloques del sujeto", "The subject's blocks")}>
        {trials.map((r) => {
          const hit = r.predicted_label === r.observed_label;
          return (
            <button
              key={r.sample_id}
              type="button"
              aria-pressed={r.sample_id === sampleId}
              onClick={() => onTrial(r.sample_id)}
              data-sample={r.sample_id}
              className={hit ? undefined : "fnirs-block--miss"}
              title={tr(`Bloque ${r.trial}: real ${names.cls(r.observed_label).toLowerCase()}, predicha ${r.predicted_label ? names.cls(r.predicted_label).toLowerCase() : "sin clase"}`, `Block ${r.trial}: actual ${names.cls(r.observed_label).toLowerCase()}, predicted ${r.predicted_label ? names.cls(r.predicted_label).toLowerCase() : "no class"}`)}
            >
              <span className="class-swatch" style={{ background: classColor(scheme, r.observed_label) }} aria-hidden="true" /> <strong>{r.trial}</strong>
              <span className={hit ? "muted" : "fnirs-miss"}>{hit ? " ✓" : tr(" fallo", " miss")}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function Scalp({ trace, montage, rules, view, ruleId }: { trace: TrialTrace; montage: MontageResponse; rules: ModelRules; view: View; ruleId: string | null }) {
  const label = useFeatureLabel();
  const names = useNames();
  const value = new Map(trace.feature_values.map((f) => [f.feature, f.value ?? null]));
  const usedByRules = useMemo(() => {
    const chOf = new Map(montage.channels.flatMap((c) => c.inputs.map((i) => [i.feature, c.channel_id] as const)));
    return new Set(rules.rules.flatMap((r) => r.antecedents.map((a) => chOf.get(a.feature)).filter((c): c is string => !!c)));
  }, [montage, rules]);
  const marks = new Map<string, ChannelMark>();
  let bound = 0;
  if (view !== "rule") {
    for (const c of montage.channels) for (const i of c.inputs) if (i.signal === view) bound = Math.max(bound, Math.abs(value.get(i.feature) ?? 0));
    for (const c of montage.channels) {
      const input = c.inputs.find((i) => i.signal === view);
      const v = input ? value.get(input.feature) : null;
      marks.set(c.channel_id, v == null
        ? { bin: null, detail: tr("sin valor", "no value") }
        : { bin: divergingBin(v, bound), fill: bloodFill(divergingBin(v, bound), view), detail: `${view}: ${v >= 0 ? "+" : ""}${dec(v * 1000, 3)} µmol/L` });
    }
  }
  const rule = rules.rules.find((r) => r.rule_id === ruleId) ?? null;
  const entry = trace.rules.find((r) => r.rule_id === ruleId) ?? null;
  const conditions: { channel: string; text: string; mu: number }[] = [];
  if (view === "rule" && rule && entry) {
    const chOf = new Map(montage.channels.flatMap((c) => c.inputs.map((i) => [i.feature, { channel: c.channel_id, signal: i.signal }] as const)));
    rule.antecedents.forEach((a, k) => {
      const where = chOf.get(a.feature);
      const mu = entry.antecedents[k]?.effective_membership ?? 0;
      if (!where) return;
      const text = fullCondition(a, label, names);
      conditions.push({ channel: where.channel, text, mu });
      const old = marks.get(where.channel);
      marks.set(where.channel, {
        bin: Math.min(old?.bin ?? 4, membershipBin(mu)),
        detail: [old?.detail, `${text}: ${fmt(mu)}`].filter(Boolean).join("\n"),
        tag: [old?.tag, where.signal].filter(Boolean).join("+"),
      });
    });
  }
  const mapLabel = view === "rule"
    ? tr(`Canales de la regla ${ruleId ?? ""} en este ensayo`, `Channels of rule ${ruleId ?? ""} in this trial`)
    : tr(`Cambio de ${view} en cada canal en este ensayo`, `Change of ${view} at each channel in this trial`);
  return (
    <div className="fnirs-scalp">
      <ScalpMap channels={montage.channels} marks={marks} usedByRules={view === "rule" ? usedByRules : new Set()} label={mapLabel} />
      {view === "rule" ? (
        <>
          {rule && <RuleSentenceView sentence={ruleSentence(rule, label, null, names)} testId="scalp-rule" />}
          <ul className="fnirs-conditions" data-testid="scalp-conditions">
            {conditions.map((c) => (
              <li key={`${c.channel}|${c.text}`}>
                <strong>{c.channel}</strong>: {c.text} — <span data-raw={String(c.mu)}>{fmt(c.mu)}</span>
              </li>
            ))}
          </ul>
          {entry && (
            <p className="muted small" data-testid="scalp-firing">
              {rules.inference.tnorm === "minimum"
                ? tr(`La regla se cumple en grado ${fmt(entry.firing_strength)}: el mínimo de sus condiciones.`, `The rule holds to degree ${fmt(entry.firing_strength)}: the minimum of its conditions.`)
                : tr(`La regla se cumple en grado ${fmt(entry.firing_strength)}: el producto de sus condiciones.`, `The rule holds to degree ${fmt(entry.firing_strength)}: the product of its conditions.`)}
            </p>
          )}
          <MembershipLegend />
        </>
      ) : (
        <DivergingLegend bound={bound} signal={view} />
      )}
      <p className="muted small">
        {montage.region_approximate
          ? tr("Posiciones: tabla de coordenadas del dataset. Regiones (al pasar el ratón): asignación aproximada de la demo ex-Fuzzy fNIRS.", "Positions: the dataset's coordinate table. Regions (on hover): approximate assignment of the ex-Fuzzy fNIRS demo.")
          : tr("Posiciones: tabla de coordenadas del dataset.", "Positions: the dataset's coordinate table.")}
      </p>
    </div>
  );
}

function TrialVerdict({ trace, record, rules, scheme, ruleId, onSelectRule }: { trace: TrialTrace; record: TrialRecord; rules: ModelRules; scheme: FnirsModelCard["target_scheme"]; ruleId: string | null; onSelectRule: (id: string) => void }) {
  const predicted = trace.prediction.label ?? null;
  return (
    <div className="fnirs-verdict" data-testid="trial-verdict">
      <p>
        {tr("Real: ", "Actual: ")}
        <ClassChip label={record.observed_label} color={classColor(scheme, record.observed_label)} /> · {tr("predicha: ", "predicted: ")}
        {predicted ? <ClassChip label={predicted} color={classColor(scheme, predicted)} /> : <span className="muted">{tr("sin clase (no se cumple ninguna regla)", "no class (no rule holds)")}</span>}
        {record.split === "train" && <span className="muted small">{tr(" · dentro de la muestra", " · in-sample")}</span>}
      </p>
      {rules.inference.family === "rule_mixture_classifier" ? (
        <MixtureTrace trace={trace} scheme={scheme} onSelectRule={onSelectRule} selectedRuleId={ruleId} />
      ) : (
        trace.prediction.winning_rule_id && (
          <p>
            {tr(`Decide la regla ${trace.prediction.winning_rule_id}.`, `Rule ${trace.prediction.winning_rule_id} decides.`)}{" "}
            <button type="button" className="link" onClick={() => onSelectRule(trace.prediction.winning_rule_id!)}>{tr("Verla en el cuero cabelludo", "See it on the scalp")}</button>
          </p>
        )
      )}
    </div>
  );
}

function RuleList({ rules, trace, selected, onSelect }: { rules: ModelRules; trace: TrialTrace | null; selected: string | null; onSelect: (id: string) => void }) {
  const label = useFeatureLabel();
  const names = useNames();
  const firing = new Map(trace?.rules.map((r) => [r.rule_id, r.firing_strength]) ?? []);
  return (
    <ol className="fnirs-rules" data-testid="fnirs-rules">
      {rules.rules.map((r) => {
        const f = firing.get(r.rule_id);
        return (
          <li key={r.rule_id} aria-current={r.rule_id === selected ? "true" : undefined} data-rule={r.rule_id}>
            <button type="button" className="link" onClick={() => onSelect(r.rule_id)} aria-label={tr(`Ver la regla ${r.rule_id} en el cuero cabelludo`, `See rule ${r.rule_id} on the scalp`)}>
              {r.rule_id}
            </button>
            <RuleSentenceView sentence={ruleSentence(r, label, null, names)} testId={`rule-${r.rule_id}`} />
            {f !== undefined && (
              <span className="fnirs-firing" data-raw={String(f)}>
                <span className="fnirs-firing-bar" style={{ width: `${Math.round(f * 100)}%` }} aria-hidden="true" />
                {tr(`se cumple ${fmt(f)}`, `holds ${fmt(f)}`)}
              </span>
            )}
          </li>
        );
      })}
    </ol>
  );
}

