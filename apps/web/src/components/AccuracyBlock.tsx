import type { MetricRow, ModelCard } from "../api/types";
import { classColor } from "../lib/classifier";
import { dec, pct, unitLabel, withUnit } from "../lib/format";
import { importancePeriod } from "../lib/importance";
import { count } from "../lib/summary";
import { Card, MoreInfo } from "./Card";
import { ClassChip } from "./ClassChip";
import { tr } from "../i18n";

// Built at render time (not at import): the language can change while the page is open.
const baselines = (): { estimator: string; classifier: string; regression: string }[] => [
  { estimator: "persistence", classifier: tr("repetir la categoría de la última observación", "repeating the category of the last observation"), regression: tr("repetir el último valor observado", "repeating the last observed value") },
  { estimator: "global_mean", classifier: "", regression: tr("dar siempre la media del entrenamiento", "always giving the training mean") },
  { estimator: "climatology_majority_class", classifier: tr("dar siempre la categoría más habitual", "always giving the most frequent category"), regression: "" },
];

/** The rows of the test slice; the published report names it "all" (validation rows are "validation/..."). */
const testRows = (card: ModelCard): MetricRow[] => (card.metrics?.rows ?? []).filter((r) => (r.slice ?? "all") === "all");

const get = (rows: readonly MetricRow[], estimator: string, metric: string) => rows.find((r) => r.estimator === estimator && r.metric === metric);

/** Words for how the model stands against the baseline on one metric (a tie within half a point or 0.5 % is a tie). */
export function verdict(model: number, base: number, higherIsBetter: boolean): "mejor" | "igual" | "peor" {
  const tol = 0.005 * Math.max(Math.abs(base), 1e-9);
  if (Math.abs(model - base) <= Math.max(tol, higherIsBetter ? 0.005 : 0)) return "igual";
  return model > base === higherIsBetter ? "mejor" : "peor";
}

type Verdict = ReturnType<typeof verdict>;

/** The verdict in a sentence ("el modelo queda por encima de esa referencia"). */
const verdictText = (v: Verdict): string =>
  ({
    mejor: tr("el modelo queda por encima de esa referencia", "the model does better than that reference"),
    igual: tr("el modelo no se distingue de esa referencia", "the model can't be told apart from that reference"),
    peor: tr("el modelo queda por debajo de esa referencia", "the model does worse than that reference"),
  })[v];

/** The verdict as a table cell. */
const verdictWord = (v: Verdict): string => ({ mejor: tr("mejor", "better"), igual: tr("igual", "same"), peor: tr("peor", "worse") })[v];

/** Words for the macro-F1 comparison; a gap under 0.01 is a tie (the figures are shown with two decimals). */
function macroF1Sentence(model: number, base: number): string {
  const m = dec(model, 2);
  const b = dec(base, 2);
  const lead = tr(`Si todas las categorías cuentan igual, también las poco frecuentes (F1 macro), obtiene ${m} frente a ${b}`, `If every category counts the same, rare ones included (macro-F1), it scores ${m} against ${b}`);
  if (Math.abs(model - base) < 0.01) return tr(`${lead}, sin diferencia apreciable.`, `${lead}, with no clear difference.`);
  return model > base ? `${lead}.` : tr(`${lead} y se queda por debajo.`, `${lead} and falls short.`);
}

/**
 * The always-visible model summary. A classifier: the hit rate of the test period and the macro-F1 (the metric the model
 * is selected on: every category counts the same, rare ones too), each next to the simplest baseline on the same rows,
 * worded as it falls (above, equal or below). A regression: the mean error next to its baseline. null when the card
 * publishes no such metrics.
 */
export function accuracySummary(card: ModelCard, unit: string): string | null {
  const rows = testRows(card);
  const scheme = card.target_scheme ?? null;
  const estimator = [...new Set(rows.map((r) => r.estimator))].find((e) => e.startsWith("exfuzzy"));
  if (!estimator) return null;
  const baseline = baselines().find((b) => get(rows, b.estimator, scheme ? "accuracy" : "mae"));
  const metric = scheme ? "accuracy" : "mae";
  const own = get(rows, estimator, metric);
  if (!own) return null;
  const ref = baseline ? get(rows, baseline.estimator, metric) : undefined;
  const words = scheme ? baseline?.classifier : baseline?.regression;
  const fmtV = (v: number) => (scheme ? pct(v) : withUnit(v, unitLabel(unit), 2));
  const v = fmtV(own.value);
  if (!scheme) {
    const theirs = ref && words ? tr(`, frente a ${fmtV(ref.value)} al ${words}`, `, against ${fmtV(ref.value)} when ${words}`) : "";
    return tr(`En el periodo de prueba, el error medio es ${v}${theirs}.`, `In the test period, the mean error is ${v}${theirs}.`);
  }
  const theirs = ref && words ? ` (${words}: ${fmtV(ref.value)})` : "";
  const f1 = get(rows, estimator, "macro_f1");
  const f1Ref = baseline ? get(rows, baseline.estimator, "macro_f1") : undefined;
  const f1Text = f1 && f1Ref ? ` ${macroF1Sentence(f1.value, f1Ref.value)}` : "";
  // The same hour yesterday (`persistence_24h`), when published: the forecast a rule base on yesterday can rediscover.
  const yAcc = get(rows, "persistence_24h", "accuracy");
  const yF1 = get(rows, "persistence_24h", "macro_f1");
  const ydayText =
    yAcc && yF1
      ? " " + tr(`Repetir la categoría de ayer a la misma hora acierta el ${pct(yAcc.value)} (F1 macro ${dec(yF1.value, 2)}).`,
          `Repeating yesterday's category at the same hour gets ${pct(yAcc.value)} right (macro-F1 ${dec(yF1.value, 2)}).`,
        )
      : "";
  return tr(`En el periodo de prueba, acierta la categoría en el ${v} de los casos${theirs}.${f1Text}${ydayText}`, `In the test period, it gets the category right in ${v} of the cases${theirs}.${f1Text}${ydayText}`);
}

/**
 * "¿Cuánto acierta?" in plain language, from the model card's test-period metrics (nothing is recomputed). A classifier
 * says how often the category is right overall and per category, next to the simplest baseline on the same rows; a
 * regression says its mean error. It describes this period and these stations; it is not a promise about the future.
 */
export function AccuracyBlock({ card, unit }: { card: ModelCard; unit: string }) {
  const rows = testRows(card);
  const scheme = card.target_scheme ?? null;
  const estimator = [...new Set(rows.map((r) => r.estimator))].find((e) => e.startsWith("exfuzzy"));
  const period = importancePeriod({ period_from_utc: card.manifest.split.test_from_utc, period_to_utc: card.manifest.split.test_to_utc });
  if (!estimator || rows.length === 0) {
    return (
      <Card title={tr("¿Cuánto acierta?", "How often is it right?")}>
        <p className="muted">{tr("Este modelo no publica métricas de evaluación.", "This model publishes no evaluation metrics.")}</p>
      </Card>
    );
  }
  const baseline = baselines().find((b) => get(rows, b.estimator, scheme ? "accuracy" : "mae"));

  if (scheme) {
    const acc = get(rows, estimator, "accuracy");
    const base = baseline ? get(rows, baseline.estimator, "accuracy") : undefined;
    const unknown = get(rows, estimator, "share_unknown")?.value ?? get(rows, estimator, "share_no_rule_fires")?.value ?? null;
    const far = get(rows, estimator, "share_off_by_2plus")?.value ?? null;
    const classes = scheme.classes.map((c) => c.label);
    const perClass = classes.filter((c) => get(rows, estimator, `recall[${c}]`));
    const smallest = perClass.reduce<number | null>((m, c) => Math.min(m ?? Infinity, get(rows, estimator, `recall[${c}]`)!.n), null);
    return (
      <Card title={tr("¿Cuánto acierta?", "How often is it right?")} subtitle={tr(`Resultados en el periodo de prueba (${period}), que el modelo no vio al entrenarse.`, `Results in the test period (${period}), which the model did not see in training.`)} className="accuracy">
        {acc && (
          <p className="lead" data-testid="accuracy-sentence">
            {tr(<>El modelo acierta la categoría en <strong>{dec(acc.value * 100, 0)}</strong> de cada 100 predicciones</>, <>The model gets the category right in <strong>{dec(acc.value * 100, 0)}</strong> out of every 100 predictions</>)}
            {base && baseline?.classifier
              ? tr(`. Para comparar, ${baseline.classifier} acierta ${dec(base.value * 100, 0)} de cada 100.`, `. For comparison, ${baseline.classifier} gets ${dec(base.value * 100, 0)} out of 100 right.`)
              : "."}
          </p>
        )}
        <p className="muted small">
          {acc ? tr(`Calculado sobre ${count(acc.n)} casos. `, `Based on ${count(acc.n)} cases. `) : ""}
          {unknown !== null && unknown > 0 ? tr(`En el ${pct(unknown)} de los casos el modelo no da categoría. `, `In ${pct(unknown)} of the cases the model gives no category. `) : ""}
          {far !== null ? tr(`Se equivoca por dos categorías o más en el ${pct(far)}.`, `It is off by two categories or more in ${pct(far)} of the cases.`) : ""}
        </p>
        {acc && base && baseline?.classifier && (
          <>
            <p className="callout" data-testid="baseline-verdict" data-verdict={verdict(acc.value, base.value, true)}>
              {tr(`Frente a ${baseline.classifier} (la referencia más simple, con las mismas filas), ${verdictText(verdict(acc.value, base.value, true))} en exactitud (${dec(acc.value * 100, 1)} frente a ${dec(base.value * 100, 1)} de cada 100). Un modelo que no mejora a la referencia no aporta más que repetir lo último observado.`,
                `Compared with ${baseline.classifier} (the simplest reference, on the same rows), ${verdictText(verdict(acc.value, base.value, true))} on accuracy (${dec(acc.value * 100, 1)} against ${dec(base.value * 100, 1)} out of 100). A model that doesn't beat the reference adds nothing over repeating the last observation.`)}
            </p>
            <table className="plain per-class" aria-label={tr("Comparación con la referencia", "Comparison with the reference")}>
              <caption>{tr("Modelo y referencia en las mismas filas del periodo de prueba", "Model and reference on the same rows of the test period")}</caption>
              <thead>
                <tr>
                  <th scope="col">{tr("Medida (0 a 1, mayor es mejor)", "Measure (0 to 1, higher is better)")}</th>
                  <th scope="col" className="num">{tr("Modelo", "Model")}</th>
                  <th scope="col" className="num">{tr("Referencia", "Reference")}</th>
                  <th scope="col">{tr("Resultado", "Result")}</th>
                </tr>
              </thead>
              <tbody>
                {[["accuracy", tr("Exactitud", "Accuracy")], ["balanced_accuracy", tr("Exactitud balanceada", "Balanced accuracy")], ["macro_f1", tr("F1 macro", "macro-F1")]].map(([m, name]) => {
                  const a = get(rows, estimator, m!);
                  const b = get(rows, baseline.estimator, m!);
                  return a && b ? (
                    <tr key={m} data-metric={m}>
                      <th scope="row">{name}</th>
                      <td className="num">{dec(a.value, 3)}</td>
                      <td className="num">{dec(b.value, 3)}</td>
                      <td>{verdictWord(verdict(a.value, b.value, true))}</td>
                    </tr>
                  ) : null;
                })}
              </tbody>
            </table>
          </>
        )}
        {perClass.length > 0 && (
          <table className="plain per-class" aria-label={tr("Acierto por categoría", "Hit rate per category")}>
            <caption>{tr("Por categoría", "Per category")}</caption>
            <thead>
              <tr>
                <th scope="col">{tr("Categoría", "Category")}</th>
                <th scope="col" className="num">{tr("Casos observados", "Observed cases")}</th>
                <th scope="col" className="num">{tr("La detecta", "Detected")}</th>
                <th scope="col" className="num">{tr("Cuando la prevé, acierta", "Right when predicted")}</th>
              </tr>
            </thead>
            <tbody>
              {perClass.map((c) => {
                const recall = get(rows, estimator, `recall[${c}]`);
                const precision = get(rows, estimator, `precision[${c}]`);
                return (
                  <tr key={c} data-class={c}>
                    <th scope="row"><ClassChip label={c} color={classColor(scheme, c)} /></th>
                    <td className="num">{recall ? count(recall.n) : "—"}</td>
                    <td className="num">{recall ? pct(recall.value) : "—"}</td>
                    <td className="num">{precision ? pct(precision.value) : tr("sin casos", "no cases")}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        {smallest !== null && smallest < 500 && (
          <p className="callout">{tr("Alguna categoría tiene pocos casos en el periodo de prueba, así que sus cifras son poco estables.", "At least one category has few cases in the test period, so its figures aren't very stable.")}</p>
        )}
        <MoreInfo summary={tr("Qué significan estas cifras", "What these figures mean")}>
          <p>
            {tr(`«La detecta» es la parte de los casos de una categoría que el modelo prevé como esa categoría. «Cuando la prevé, acierta» es la parte de sus previsiones de esa categoría que resultan correctas.`,
              `“Detected” is the share of a category's cases that the model predicts as that category. “Right when predicted” is the share of the model's predictions of that category that turn out correct.`)}
          </p>
        </MoreInfo>
      </Card>
    );
  }

  const mae = get(rows, estimator, "mae");
  const base = baseline ? get(rows, baseline.estimator, "mae") : undefined;
  const u = unitLabel(unit);
  return (
    <Card title={tr("¿Cuánto acierta?", "How often is it right?")} subtitle={tr(`Resultados en el periodo de prueba (${period}).`, `Results in the test period (${period}).`)} className="accuracy">
      {mae ? (
        <p className="lead" data-testid="accuracy-sentence">
          {tr(<>El error medio del modelo es de <strong>{withUnit(mae.value, u, 2)}</strong></>, <>The model&apos;s mean error is <strong>{withUnit(mae.value, u, 2)}</strong></>)}
          {base && baseline?.regression ? tr(`. Para comparar, ${baseline.regression} se equivoca de media ${withUnit(base.value, u, 2)}.`, `. For comparison, ${baseline.regression} is off by ${withUnit(base.value, u, 2)} on average.`) : "."}
        </p>
      ) : (
        <p className="muted">{tr("El modelo no publica el error medio.", "The model doesn't publish its mean error.")}</p>
      )}
      {mae && base && baseline?.regression && (
        <p className="callout" data-testid="baseline-verdict" data-verdict={verdict(mae.value, base.value, false)}>
          {tr(`Frente a ${baseline.regression} (la referencia más simple, con las mismas filas), ${verdictText(verdict(mae.value, base.value, false))} en error medio (${withUnit(mae.value, u, 2)} frente a ${withUnit(base.value, u, 2)}).`,
            `Compared with ${baseline.regression} (the simplest reference, on the same rows), ${verdictText(verdict(mae.value, base.value, false))} on mean error (${withUnit(mae.value, u, 2)} against ${withUnit(base.value, u, 2)}).`)}
        </p>
      )}
      {mae && <p className="muted small">{tr(`Calculado sobre ${count(mae.n)} casos del periodo de prueba.`, `Based on ${count(mae.n)} cases from the test period.`)}</p>}
    </Card>
  );
}
