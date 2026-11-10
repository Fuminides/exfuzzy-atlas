import { useState } from "react";
import type { ModelCard, ModelRules } from "../api/types";
import { tr } from "../i18n";
import { dec, pct, unitLabel, withUnit } from "../lib/format";
import { BenchCard } from "./ui/BenchCard";
import { Chips, type Chip } from "./ui/Chips";
import { Hero, HeroAccent } from "./ui/Hero";
import { KpiTiles, type Kpi } from "./ui/KpiTiles";
import { barLabel, modelSize, performanceReport, reportMetrics, standing, type BarKey, type ReportMetric } from "../lib/performance";

interface Props {
  card: ModelCard;
  rules: ModelRules;
  /** The test period in words ("2025"). */
  period: string;
  unit: string;
  /** "Madrid · +6 h": what the eyebrow names. */
  context: string;
}

const metricName = (m: ReportMetric): string => ({ macro_f1: tr("F1 macro", "Macro-F1"), accuracy: tr("Acierto", "Accuracy"), mae: tr("Error medio", "Mean error") })[m];

const metricNote = (m: ReportMetric): string =>
  ({
    macro_f1: tr("F1 macro: todas las categorías cuentan igual, también las poco frecuentes. Con esta métrica se eligen los modelos.", "Macro-F1: every category counts the same, rare ones too. The models are selected on this metric."),
    accuracy: tr("Acierto: parte de las predicciones con la categoría correcta. Cuando una categoría domina, hasta un modelo trivial acierta mucho.", "Accuracy: the share of predictions with the right category. When one category dominates, even a trivial model is often right."),
    mae: tr("Error medio absoluto, en la unidad de la variable.", "Mean absolute error, in the variable's unit."),
  })[m];

/** "a, b y c" / "a, b and c". */
const list = (items: string[]): string =>
  items.length <= 1 ? (items[0] ?? "") : `${items.slice(0, -1).join(", ")} ${tr("y", "and")} ${items[items.length - 1]}`;

/** A baseline's name inside a sentence, in lower case with its article (bar labels and titles keep the capitalised name). */
function inSentence(key: BarKey, classifier: boolean): string {
  switch (key) {
    case "persistence":
      return classifier ? tr("repetir la última categoría", "repeating the last category") : tr("repetir el último valor", "repeating the last value");
    case "persistence_24h":
      return classifier ? tr("repetir la de ayer a la misma hora", "repeating yesterday's at the same hour") : tr("repetir el de ayer a la misma hora", "repeating yesterday's at the same hour");
    case "linear":
      return classifier ? tr("la regresión logística", "logistic regression") : tr("la regresión lineal", "linear regression");
    case "forest":
      return tr("el Random Forest", "the random forest");
    default:
      return "ExFuzzy";
  }
}

/** Spanish "de" / "a" before the article "el" contract: «de el» → «del», «a el» → «al». */
const contract = (text: string) => text.replace(/\bde el\b/g, "del").replace(/\ba el\b/g, "al");

/**
 * The performance report, presented like a model launch: a hero with the headline score, a one-sentence verdict and
 * three key figures; then a benchmark chart (vertical bars from zero, the model in the accent colour with a reference
 * line at its level, the value on top of every bar). Macro-F1 by default, accuracy on demand; a regression shows its
 * mean error. Every number comes from the model card's evaluation report.
 */
export function PerformanceChart({ card, rules, period, unit, context }: Props) {
  const metrics = reportMetrics(card);
  const [metric, setMetric] = useState<ReportMetric>(metrics[0]!);
  const report = performanceReport(card, metric);
  const classifier = card.target_scheme != null;
  const size = modelSize(rules);
  // The headline figures are always the selection metric (and accuracy for a classifier), whatever the chart shows.
  const main = performanceReport(card, classifier ? "macro_f1" : "mae");
  if (!report || !main) {
    return (
      <section className="bench report-bench">
        <p className="muted">{tr("Este modelo no publica métricas de evaluación comparables.", "This model publishes no comparable evaluation metrics.")}</p>
      </section>
    );
  }
  const fmtV = (v: number) => (metric === "accuracy" ? pct(v) : metric === "mae" ? withUnit(v, unitLabel(unit), 2) : dec(v, 2));
  const model = report.bars.find((b) => b.key === "model")!;
  const max = Math.max(...report.bars.map((b) => b.value));
  // Bars start at zero; the scale ends at the next tenth above the largest value (or 15 % above it for an error).
  const top = metric === "mae" ? Math.max(max * 1.15, 1e-9) : Math.min(1, Math.ceil((max + 1e-9) * 10) / 10);
  const h = (v: number) => `${Math.max(0, Math.min(1, v / top)) * 100}%`;

  const headline = main.bars.find((b) => b.key === "model")!.value;
  const accuracy = classifier ? (performanceReport(card, "accuracy")?.bars.find((b) => b.key === "model")?.value ?? null) : null;
  const headlineText = classifier ? dec(headline, 2) : withUnit(headline, unitLabel(unit), 2);

  // The verdict, on the selection metric: which baselines the model beats, ties and trails.
  const groups: Record<"above" | "par" | "below", BarKey[]> = { above: [], par: [], below: [] };
  for (const b of main.bars) if (b.key !== "model") groups[standing(headline, b.value, main.higherIsBetter)].push(b.key);
  // Spanish repeats the preposition before each further name ("a la par de X y de Y"); English does not.
  const names = (keys: BarKey[], prep: string) => list(keys.map((k, i) => `${i > 0 && prep ? `${prep} ` : ""}${inSentence(k, classifier)}`));
  const parts = [
    groups.above.length ? contract(tr(`supera a ${names(groups.above, "a")}`, `beats ${names(groups.above, "")}`)) : null,
    groups.par.length ? contract(tr(`queda a la par de ${names(groups.par, "de")}`, `is on a par with ${names(groups.par, "")}`)) : null,
    groups.below.length ? contract(tr(`queda por debajo de ${names(groups.below, "de")}`, `does worse than ${names(groups.below, "")}`)) : null,
  ].filter((p): p is string => p !== null);

  const chips: Chip[] = main.bars
    .filter((b) => b.key !== "model")
    .map((b) => {
      const s = standing(headline, b.value, main.higherIsBetter);
      const word = { above: tr("mejor que", "better than"), par: tr("a la par de", "on a par with"), below: tr("peor que", "worse than") }[s];
      return { key: b.key, tone: s, data: { "data-standing": s }, content: contract(`${word} ${inSentence(b.key, classifier)}`) };
    });
  const kpis: Kpi[] = [
    { key: "main", accent: true, label: classifier ? tr("F1 macro", "Macro-F1") : tr("Error medio", "Mean error"), value: headlineText },
    ...(accuracy !== null ? [{ key: "accuracy", label: tr("Acierto", "Accuracy"), value: pct(accuracy) }] : []),
    {
      key: "size",
      testId: "perf-size",
      label: tr("Modelo completo", "Whole model"),
      value: size.rules,
      unit: tr("reglas", "rules"),
      note: tr(`${dec(size.meanConditions, 1)} condiciones de media`, `${dec(size.meanConditions, 1)} conditions on average`),
    },
  ];

  return (
    <>
      <Hero
        label={tr("Resultado principal", "Headline result")}
        eyebrow={tr(`${context} · periodo de prueba ${period}`, `${context} · test period ${period}`)}
        headline={
          classifier
            ? tr(<>F1 macro de <HeroAccent>{headlineText}</HeroAccent> con {size.rules} reglas</>,
              <>Macro-F1 of <HeroAccent>{headlineText}</HeroAccent> with {size.rules} rules</>)
            : tr(<>Error medio de <HeroAccent>{headlineText}</HeroAccent> con {size.rules} reglas</>,
              <>Mean error of <HeroAccent>{headlineText}</HeroAccent> with {size.rules} rules</>)
        }
        verdict={parts.length > 0 ? <>{tr("En el periodo de prueba, el modelo", "In the test period, the model")} {parts.join("; ")}.</> : undefined}
        aside={<KpiTiles items={kpis} />}
      >
        <Chips items={chips} label={tr("Frente a cada referencia", "Against each baseline")} testId="perf-standing" />
      </Hero>

      <BenchCard
        className="report-bench"
        label={tr("Comparación con modelos de referencia", "Comparison with baseline models")}
        title={tr("ExFuzzy frente a los modelos de referencia", "ExFuzzy against the baseline models")}
        subtitle={tr("Las mismas predicciones del periodo de prueba, que el modelo no vio al entrenarse.", "The same test-period predictions, from a period the model didn't see in training.")}
        actions={
          <>
            <span className="report-direction" data-testid="perf-direction" data-higher-is-better={String(report.higherIsBetter)}>
              <span aria-hidden="true">{report.higherIsBetter ? "↑ " : "↓ "}</span>
              {report.higherIsBetter ? tr("más es mejor", "higher is better") : tr("menos es mejor", "lower is better")}
            </span>
            {metrics.length > 1 && (
              <div className="report-toggle" role="group" aria-label={tr("Métrica", "Metric")}>
                {metrics.map((m) => (
                  <button key={m} type="button" aria-pressed={m === metric} onClick={() => setMetric(m)}>
                    {metricName(m)}
                  </button>
                ))}
              </div>
            )}
          </>
        }
      >
        <div className="report-chart">
          <div className="report-plot">
            <span className="report-ref" style={{ bottom: h(model.value) }} aria-hidden="true" />
            <ol className="report-bars" aria-label={tr(`${metricName(metric)} por modelo`, `${metricName(metric)} by model`)} data-testid="perf-bars" data-metric={metric}>
              {report.bars.map((b) => (
                <li key={b.key} className={`report-col${b.key === "model" ? " report-col--model" : ""}`} data-key={b.key} data-estimator={b.estimator}>
                  <span className="report-col-label">{barLabel(b.key, classifier)}</span>
                  <span className="report-col-bar" style={{ height: h(b.value) }}>
                    <span className="report-col-value" data-raw={String(b.value)}>
                      {fmtV(b.value)}
                    </span>
                  </span>
                </li>
              ))}
            </ol>
          </div>
        </div>
        <p className="report-foot muted">
          {metricNote(metric)}{" "}
          {tr(`«${barLabel("linear", classifier)}» y «${barLabel("forest", classifier)}» son las variantes que mejor puntuaron en el periodo de validación, con las mismas entradas. Escala de 0 a ${fmtV(top)}. La línea discontinua marca a ExFuzzy.`,
            `“${barLabel("linear", classifier)}” and “${barLabel("forest", classifier)}” are the variants that scored best on the validation period, with the same inputs. Scale from 0 to ${fmtV(top)}. The dashed line marks ExFuzzy.`)}
        </p>
      </BenchCard>
    </>
  );
}
