import { useState } from "react";
import type { FnirsModelCard, ModelRules } from "../api/types";
import { PageHead } from "../components/Card";
import { BenchCard } from "../components/ui/BenchCard";
import { Chips, type Chip } from "../components/ui/Chips";
import { Hero, HeroAccent } from "../components/ui/Hero";
import { KpiTiles, type Kpi } from "../components/ui/KpiTiles";
import { tr } from "../i18n";
import { dec, pct } from "../lib/format";
import { modelSize, standing } from "../lib/performance";

type Metric = "macro_f1" | "accuracy" | "mcc";
type Part = "test" | "validation" | "nested";

const METRICS: readonly Metric[] = ["macro_f1", "accuracy", "mcc"];
const metricName = (m: Metric): string => ({ macro_f1: tr("F1 macro", "Macro-F1"), accuracy: tr("Acierto", "Accuracy"), mcc: "MCC" })[m];
const metricNote = (m: Metric): string =>
  ({
    macro_f1: tr("F1 macro: las dos cargas cuentan igual. Con esta métrica se eligen los modelos.", "Macro-F1: both loads count the same. The models are selected on this metric."),
    accuracy: tr("Acierto: parte de los bloques con la carga correcta. Dos de cada tres bloques son de carga alta, así que decir siempre «alta» ya acierta el 67 %.", "Accuracy: the share of blocks with the right load. Two blocks in three are high load, so always saying “high” is already right 67% of the time."),
    mcc: tr("MCC (coeficiente de correlación de Matthews): 0 equivale al azar y 1 a acertarlo todo.", "MCC (Matthews correlation coefficient): 0 is chance level, 1 is getting everything right."),
  })[m];

export const estimatorName = (e: string): string =>
  ({
    exfuzzy: "ExFuzzy",
    svm_rbf: tr("SVM (núcleo RBF)", "SVM (RBF kernel)"),
    random_forest: tr("Random forest", "Random forest"),
    logistic_regression: tr("Regresión logística", "Logistic regression"),
    majority_class: tr("Clase mayoritaria", "Majority class"),
  })[e] ?? e;

/** A baseline inside a sentence, lower case with its article. */
const inSentence = (e: string): string =>
  ({
    svm_rbf: tr("la SVM", "the SVM"),
    random_forest: tr("el random forest", "the random forest"),
    logistic_regression: tr("la regresión logística", "logistic regression"),
    majority_class: tr("la clase mayoritaria", "the majority class"),
  })[e] ?? e;

/** «a, b y c» / "a, b and c". */
const joinAnd = (items: readonly string[]): string =>
  items.length < 2 ? items.join("") : `${items.slice(0, -1).join(", ")}${tr(" y ", " and ")}${items[items.length - 1]}`;
/** Spanish "de el" → "del", "a el" → "al". */
const contract = (text: string) => text.replace(/\bde el\b/g, "del").replace(/\ba el\b/g, "al");

const ORDER = ["exfuzzy", "svm_rbf", "random_forest", "logistic_regression", "majority_class"];

export interface Spread {
  estimator: string;
  values: { key: string; value: number }[];
  mean: number;
  sd: number;
}

/** Per estimator, the values of `part/<key>=…` rows of one metric, their mean and (sample) standard deviation. */
export function spreads(card: FnirsModelCard, part: Part, metric: Metric): Spread[] {
  const by = new Map<string, { key: string; value: number }[]>();
  for (const r of card.metrics) {
    const slice = r.slice ?? "all";
    if (r.metric !== metric || !slice.startsWith(`${part}/`)) continue;
    by.set(r.estimator, [...(by.get(r.estimator) ?? []), { key: slice.split("=")[1] ?? "", value: r.value }]);
  }
  return [...by.entries()]
    .map(([estimator, values]) => {
      const mean = values.reduce((a, v) => a + v.value, 0) / values.length;
      const sd = values.length > 1 ? Math.sqrt(values.reduce((a, v) => a + (v.value - mean) ** 2, 0) / (values.length - 1)) : 0;
      return { estimator, values, mean, sd };
    })
    .sort((a, b) => (ORDER.indexOf(a.estimator) + 99 * Number(!ORDER.includes(a.estimator))) - (ORDER.indexOf(b.estimator) + 99 * Number(!ORDER.includes(b.estimator))));
}

/**
 * The report's benchmark columns (vertical bars from zero, ExFuzzy in Sienna, a dashed line at its level, the value on
 * top), with what a spread adds: ± one standard deviation as a line with caps on the bar, and a dot per seed or group.
 */
function SpreadColumns({ rows, metric, unitWord, dotWord, highlight }: { rows: Spread[]; metric: Metric; unitWord: string; dotWord: string; highlight: string | null }) {
  const values = rows.flatMap((r) => [r.mean + r.sd, ...r.values.map((v) => v.value)]);
  const lo = metric === "mcc" ? Math.min(0, ...rows.flatMap((r) => r.values.map((v) => v.value))) : 0;
  const top = Math.min(1, Math.ceil((Math.max(...values) + 1e-9) * 10) / 10);
  const h = (v: number) => `${Math.max(0, Math.min(1, (v - lo) / (top - lo))) * 100}%`;
  const model = rows.find((r) => r.estimator === "exfuzzy");
  const fmtV = (v: number) => (metric === "accuracy" ? pct(v) : dec(v, 2));
  return (
    <>
      <div className="report-chart">
        <div className="report-plot">
          {model && <span className="report-ref" style={{ bottom: h(model.mean) }} aria-hidden="true" />}
          <ol className="report-bars" aria-label={tr(`${metricName(metric)} por modelo`, `${metricName(metric)} by model`)} data-testid="perf-bars" data-metric={metric}>
            {rows.map((r) => {
              const fixed = r.sd < 1e-12;
              const peak = Math.max(r.mean + r.sd, ...r.values.map((v) => v.value));
              return (
                <li key={r.estimator} className={`report-col report-col--spread${r.estimator === "exfuzzy" ? " report-col--model" : ""}`} data-estimator={r.estimator}>
                  <span className="report-col-label">{estimatorName(r.estimator)}</span>
                  <span className="report-col-bar" style={{ height: h(r.mean) }} />
                  {!fixed && <span className="report-sd" style={{ bottom: h(r.mean - r.sd), height: `calc(${h(r.mean + r.sd)} - ${h(r.mean - r.sd)})` }} aria-hidden="true" />}
                  {r.values.map((v) => (
                    <span
                      key={v.key}
                      className={`report-dot${highlight !== null && r.estimator === "exfuzzy" && v.key === highlight ? " report-dot--published" : ""}`}
                      style={{ bottom: h(v.value) }}
                      title={`${estimatorName(r.estimator)}, ${unitWord} ${v.key}: ${dec(v.value, 3)}`}
                    />
                  ))}
                  <span className="report-col-value report-spread-value" style={{ bottom: h(peak) }} data-raw={String(r.mean)} data-sd={String(r.sd)}>
                    {fmtV(r.mean)}
                    <span className="report-spread-sd">{fixed ? tr("igual en todas", "the same in all") : `± ${metric === "accuracy" ? pct(r.sd) : dec(r.sd, 2)}`}</span>
                  </span>
                </li>
              );
            })}
          </ol>
        </div>
      </div>
      <p className="report-foot muted">
        {metricNote(metric)}{" "}
        {tr(`Escala de ${fmtV(lo)} a ${fmtV(top)}. La barra es la media; la raya, ± una desviación típica; cada punto, ${dotWord}. La línea discontinua marca a ExFuzzy.`,
          `Scale from ${fmtV(lo)} to ${fmtV(top)}. The bar is the mean; the line, ± one standard deviation; each dot, ${dotWord}. The dashed line marks ExFuzzy.`)}
      </p>
    </>
  );
}

function MetricToggle({ metric, onMetric }: { metric: Metric; onMetric: (m: Metric) => void }) {
  return (
    <>
      <span className="report-direction"><span aria-hidden="true">↑ </span>{tr("más es mejor", "higher is better")}</span>
      <div className="report-toggle" role="group" aria-label={tr("Métrica", "Metric")}>
        {METRICS.map((m) => (
          <button key={m} type="button" aria-pressed={m === metric} onClick={() => onMetric(m)}>{metricName(m)}</button>
        ))}
      </div>
    </>
  );
}

/**
 * The performance report of a montage task, laid out like every other report (Informe de rendimiento): a hero with the
 * headline score, a verdict and key figures, then benchmark columns. The headline is the spread over people (nested
 * cross-validation by subject, every model refitted); the manuscript's split with its seeds follows.
 */
export function PerformanceTab({ card, rules, context }: { card: FnirsModelCard; rules: ModelRules; context: string }) {
  const [metric, setMetric] = useState<Metric>("macro_f1");
  const nested = spreads(card, "nested", metric);
  const test = spreads(card, "test", metric);
  const validation = spreads(card, "validation", metric);
  const hasNested = nested.some((s) => s.estimator === "exfuzzy");
  // the headline figures are always macro-F1 and accuracy, over people when the nested results exist
  const headPart: Part = hasNested ? "nested" : "test";
  const headF1 = spreads(card, headPart, "macro_f1");
  const model = headF1.find((s) => s.estimator === "exfuzzy");
  const acc = spreads(card, headPart, "accuracy").find((s) => s.estimator === "exfuzzy");
  const size = modelSize(rules);
  const nGroups = nested.find((s) => s.estimator === "exfuzzy")?.values.length ?? 0;
  const nSeeds = test.find((s) => s.estimator === "exfuzzy")?.values.length ?? 0;
  const nFolds = validation.find((s) => s.estimator === "exfuzzy")?.values.length ?? 0;
  const nSubjects = card.split.train_subjects.length + card.split.test_subjects.length;
  const nTest = card.metrics.find((r) => r.slice === "test")?.n ?? null;
  const published = card.metrics.find((r) => r.estimator === "exfuzzy" && r.slice === "test" && r.metric === "macro_f1")?.value ?? null;
  const groups: Record<"above" | "par" | "below", string[]> = { above: [], par: [], below: [] };
  if (model) for (const b of headF1) if (b.estimator !== "exfuzzy") groups[standing(model.mean, b.mean, true)].push(b.estimator);
  // Spanish repeats the preposition before each further name ("a la par de X y de Y"); English does not
  const names = (keys: string[], prep: string) => joinAnd(keys.map((k, i) => `${i > 0 && prep ? `${prep} ` : ""}${inSentence(k)}`));
  const parts = [
    groups.above.length ? contract(tr(`supera a ${names(groups.above, "a")}`, `beats ${names(groups.above, "")}`)) : null,
    groups.par.length ? contract(tr(`queda a la par de ${names(groups.par, "de")}`, `is on a par with ${names(groups.par, "")}`)) : null,
    groups.below.length ? contract(tr(`queda por debajo de ${names(groups.below, "de")}`, `does worse than ${names(groups.below, "")}`)) : null,
  ].filter((p): p is string => p !== null);
  const chips: Chip[] = model
    ? headF1.filter((b) => b.estimator !== "exfuzzy").map((b) => {
      const s = standing(model.mean, b.mean, true);
      const word = { above: tr("mejor que", "better than"), par: tr("a la par de", "on a par with"), below: tr("peor que", "worse than") }[s];
      return { key: b.estimator, tone: s, data: { "data-standing": s }, content: contract(`${word} ${inSentence(b.estimator)}`) };
    })
    : [];
  const kpis: Kpi[] = [
    ...(model ? [{ key: "main", accent: true, label: tr("F1 macro", "Macro-F1"), value: dec(model.mean, 2), note: `± ${dec(model.sd, 2)}` }] : []),
    ...(acc ? [{ key: "accuracy", label: tr("Acierto", "Accuracy"), value: pct(acc.mean), note: `± ${pct(acc.sd)}` }] : []),
    {
      key: "size", testId: "perf-size", label: tr("Modelo completo", "Whole model"), value: size.rules, unit: tr("reglas", "rules"),
      note: tr(`${dec(size.meanConditions, 1)} condiciones de media`, `${dec(size.meanConditions, 1)} conditions on average`),
    },
  ];
  const where = hasNested
    ? tr(`en las ${nSubjects} personas, cada una evaluada por un modelo ajustado sin ella`, `over all ${nSubjects} people, each scored by a model fitted without them`)
    : tr("en los sujetos de test del artículo", "on the manuscript's test subjects");
  const cell = (x: Spread | undefined) => (x ? <><span data-raw={String(x.mean)}>{dec(x.mean, 3)}</span> ± {dec(x.sd, 3)}</> : "—");
  return (
    <div className="page" data-testid="fnirs-performance-tab">
      <PageHead title={tr("Informe de rendimiento: modelo fNIRS", "Performance report: fNIRS model")} accent={tr("modelo fNIRS", "fNIRS model")}>
        {tr("Cómo distingue el modelo la carga baja de la alta en personas que no vio al ajustarse, frente a modelos de referencia con las mismas entradas.",
          "How well the model tells low from high load on people it did not see when it was fitted, compared with baseline models on the same inputs.")}
      </PageHead>

      {model && (
        <Hero
          label={tr("Resultado principal", "Headline result")}
          eyebrow={hasNested ? tr(`${context} · ${nGroups} grupos de personas`, `${context} · ${nGroups} groups of people`) : context}
          headline={tr(<>F1 macro de <HeroAccent>{dec(model.mean, 2)}</HeroAccent> en personas no vistas</>, <>Macro-F1 of <HeroAccent>{dec(model.mean, 2)}</HeroAccent> on unseen people</>)}
          verdict={parts.length > 0 ? <>{tr(`De media ${where}, el modelo`, `On average ${where}, the model`)} {parts.join("; ")}.</> : undefined}
          aside={<KpiTiles items={kpis} />}
        >
          <Chips items={chips} label={tr("Frente a cada referencia", "Against each baseline")} testId="perf-standing" />
        </Hero>
      )}

      {hasNested && (
        <BenchCard
          className="report-bench"
          label={tr("Personas que el modelo no vio", "People the model never saw")}
          title={tr("Personas que el modelo no vio", "People the model never saw")}
          subtitle={tr(`Se reparten las ${nSubjects} personas en ${nGroups} grupos. Cada grupo sirve de prueba una vez, y todos los modelos se ajustan de nuevo con las demás personas (también se vuelve a elegir la configuración de ExFuzzy sin ese grupo). El resultado de todos los modelos que aprenden cambia de un grupo a otro, sobre todo según qué personas se evalúan. La clase mayoritaria no cambia porque todas las personas hicieron la misma proporción de bloques fáciles y difíciles.`,
            `The ${nSubjects} people are split into ${nGroups} groups. Each group is the test set once, and every model is fitted again on the other people (ExFuzzy's configuration is also chosen again without that group). Every model that learns something scores differently from one group to the next, mostly depending on which people are evaluated. The majority class stays the same, since every person did the same share of easy and hard blocks.`)}
          actions={<MetricToggle metric={metric} onMetric={setMetric} />}
        >
          <SpreadColumns rows={nested} metric={metric} unitWord={tr("grupo", "group")} dotWord={tr(`un grupo de personas, con la media de ${nSeeds} semillas`, `one group of people, averaging ${nSeeds} seeds`)} highlight={null} />
        </BenchCard>
      )}

      <BenchCard
        className="report-bench"
        label={tr("El reparto del artículo", "The manuscript's split")}
        title={tr("El reparto del artículo", "The manuscript's split")}
        subtitle={tr(`Los ${card.split.test_subjects.length} sujetos de test del manuscrito${nTest ? ` (${nTest} bloques)` : ""}, con cada modelo ajustado con ${nSeeds} semillas en los demás. Es el reparto del modelo publicado, el de las reglas y los ensayos de las otras pestañas${published !== null ? ` (F1 macro ${dec(published, 2)}, el punto con borde)` : ""}. La SVM, la regresión logística y la clase mayoritaria no usan azar al ajustarse: con las mismas personas dan siempre el mismo modelo.`,
          `The manuscript's ${card.split.test_subjects.length} test subjects${nTest ? ` (${nTest} blocks)` : ""}, each model fitted with ${nSeeds} seeds on the others. It is the published model's split, the rules and trials of the other tabs${published !== null ? ` (macro-F1 ${dec(published, 2)}, the outlined dot)` : ""}. The SVM, logistic regression and the majority class use no randomness when fitted: with the same people they always give the same model.`)}
        actions={hasNested ? undefined : <MetricToggle metric={metric} onMetric={setMetric} />}
      >
        <SpreadColumns rows={test} metric={metric} unitWord={tr("semilla", "seed")} dotWord={tr("una semilla", "one seed")} highlight={String(card.seed)} />
      </BenchCard>

      <details className="report-details">
        <summary>{tr("Detalle técnico: tabla de evaluación", "Technical detail: evaluation table")}</summary>
        <div className="table-scroll">
          <table className="plain" data-testid="fnirs-report">
            <thead>
              <tr>
                <th scope="col">{tr("Modelo", "Model")}</th>
                <th scope="col" className="num">{tr(`${metricName(metric)}, ${nGroups} grupos de personas`, `${metricName(metric)}, ${nGroups} groups of people`)}</th>
                <th scope="col" className="num">{tr(`${metricName(metric)}, test del artículo (${nSeeds} semillas)`, `${metricName(metric)}, manuscript test (${nSeeds} seeds)`)}</th>
                <th scope="col" className="num">{tr(`${metricName(metric)}, validación de la selección (${nFolds} grupos)`, `${metricName(metric)}, selection validation (${nFolds} groups)`)}</th>
              </tr>
            </thead>
            <tbody>
              {test.map((s) => (
                <tr key={s.estimator} data-estimator={s.estimator}>
                  <th scope="row">{estimatorName(s.estimator)}</th>
                  <td className="num">{cell(nested.find((x) => x.estimator === s.estimator))}</td>
                  <td className="num">{cell(s)}</td>
                  <td className="num">{cell(validation.find((x) => x.estimator === s.estimator))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
