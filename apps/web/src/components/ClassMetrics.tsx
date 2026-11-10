import { Fragment, useState } from "react";
import type { MetricRow, TargetScheme } from "../api/types";
import { classColor } from "../lib/classifier";
import { fmt , dec } from "../lib/format";
import { ClassChip } from "./ClassChip";
import { tr } from "../i18n";

const MAIN = ["macro_f1", "balanced_accuracy", "accuracy"] as const;
// Built at render time (not at import): the language can change while the page is open.
const header = (m: (typeof MAIN)[number]): string =>
  ({ macro_f1: tr("F1 macro", "macro-F1"), balanced_accuracy: tr("Exactitud balanceada", "Balanced accuracy"), accuracy: tr("Exactitud", "Accuracy") })[m];
const estimatorLabel = (e: string): string | undefined =>
  ({
    exfuzzy: "ExFuzzy",
    exfuzzy_classifier: tr("ExFuzzy (clasificador)", "ExFuzzy (classifier)"),
    persistence: tr("Persistencia", "Persistence"),
    climatology_majority_class: tr("Clase mayoritaria (climatología)", "Majority class (climatology)"),
    hist_gradient_boosting: "HGB (gradient boosting)",
    hist_gradient_boosting_balanced: tr("HGB con pesos de clase", "HGB with class weights"),
    hist_gradient_boosting_regression_binned: tr("HGB de regresión, agrupado en categorías", "HGB regression, binned into categories"),
    hist_gradient_boosting_subsample: tr("HGB con el mismo submuestreo", "HGB with the same subsampling"),
  })[e];
const NO_PREDICTION = "no_prediction";

interface Props {
  /** Rows of the overall test slice. */
  rows: readonly MetricRow[];
  scheme: TargetScheme;
}

/**
 * Classification metrics of the published report, as it gives them: summary scores of every estimator on the same
 * test rows, and per-category recall/precision and the confusion matrix of the estimator picked below. Nothing is
 * recomputed. Neutral: the best value of a column is marked only when unique.
 */
export function ClassMetrics({ rows, scheme }: Props) {
  const estimators = [...new Set(rows.map((r) => r.estimator))].sort(
    (a, b) => Number(b.startsWith("exfuzzy")) - Number(a.startsWith("exfuzzy")),
  );
  const [picked, setPicked] = useState<string | null>(null);
  const detailEstimator = picked ?? estimators[0]!;
  const get = (est: string, metric: string) => rows.find((r) => r.estimator === est && r.metric === metric);
  const best = (metric: string): string | null => {
    const vals = estimators.flatMap((e) => (get(e, metric) ? [[e, get(e, metric)!.value] as const] : []));
    if (vals.length < 2) return null;
    const top = Math.max(...vals.map(([, v]) => v));
    const winners = vals.filter(([, v]) => v === top);
    return winners.length === 1 ? winners[0]![0] : null;
  };
  const bests = Object.fromEntries(MAIN.map((m) => [m, best(m)]));
  const extra = rows.filter((r) => !(MAIN as readonly string[]).includes(r.metric) && !r.metric.includes("["));
  const classes = scheme.classes.map((c) => c.label);
  const perClass = classes.filter((c) => get(detailEstimator, `recall[${c}]`) || get(detailEstimator, `precision[${c}]`));
  const hasConfusion = classes.some((a) => classes.some((b) => get(detailEstimator, `confusion[${a}>${b}]`)));
  const label = (e: string) => estimatorLabel(e) ?? e.replace(/_/g, " ");

  return (
    <>
      <table className="plain metrics" data-kind="classification">
        <caption>
          {tr("Mismo periodo de prueba y mismas filas para todos los estimadores. Puntuaciones sin unidad, de 0 a 1 (mayor es mejor).", "Same test period and same rows for every estimator. Unitless scores, from 0 to 1 (higher is better).")}
        </caption>
        <thead>
          <tr>
            <th scope="col">{tr("Estimador", "Estimator")}</th>
            {MAIN.map((m) => (
              <th key={m} scope="col">{header(m)}</th>
            ))}
            <th scope="col">n</th>
          </tr>
        </thead>
        <tbody>
          {estimators.map((e) => (
            <tr key={e}>
              <th scope="row">
                {label(e)}
              </th>
              {MAIN.map((m) => {
                const row = get(e, m);
                return (
                  <td key={m} data-best={bests[m] === e ? "true" : undefined} className={bests[m] === e ? "best" : undefined}>
                    {row ? <span data-raw={String(row.value)}>{fmt(row.value)}</span> : "—"}
                  </td>
                );
              })}
              <td>{get(e, "accuracy")?.n ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted">
        {tr("En negrita, el valor más favorable de cada columna, si solo hay uno. La F1 macro y la exactitud balanceada dan el mismo peso a todas las categorías, así que las que apenas aparecen en el periodo de prueba (columna «Observadas», abajo) las vuelven muy inestables.",
          "Bold marks the most favourable value in each column, when there is only one. Macro-F1 and balanced accuracy give every category the same weight, so categories that are rare in the test period (the “Observed” column below) make them very unstable.")}
      </p>

      {(perClass.length > 0 || hasConfusion) && (
        <>
          <label className="detail-pick">
            {tr("Detalle por categoría de", "Per-category detail of")}{" "}
            <select value={detailEstimator} onChange={(e) => setPicked(e.target.value)} aria-label={tr("Estimador para el detalle por categoría", "Estimator for the per-category detail")}>
              {estimators.map((e) => (
                <option key={e} value={e}>{label(e)}</option>
              ))}
            </select>
          </label>
          {perClass.length > 0 && (
            <table className="plain per-class">
              <caption>{tr("Por categoría observada (periodo de prueba)", "Per observed category (test period)")}</caption>
              <thead>
                <tr>
                  <th scope="col">{tr("Categoría", "Category")}</th>
                  <th scope="col">{tr("Observadas", "Observed")}</th>
                  <th scope="col">Recall</th>
                  <th scope="col">{tr("Precisión", "Precision")}</th>
                  <th scope="col">F1</th>
                </tr>
              </thead>
              <tbody>
                {perClass.map((c) => {
                  const cell = (m: string) => {
                    const r = get(detailEstimator, `${m}[${c}]`);
                    return r ? <span data-raw={String(r.value)}>{fmt(r.value)}</span> : "—";
                  };
                  return (
                    <tr key={c} data-class={c}>
                      <th scope="row"><ClassChip label={c} color={classColor(scheme, c)} /></th>
                      <td>{get(detailEstimator, `recall[${c}]`)?.n ?? "—"}</td>
                      <td>{cell("recall")}</td>
                      <td>{cell("precision")}</td>
                      <td>{cell("f1")}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
          {hasConfusion && (
            <table className="plain confusion">
              <caption>{tr("Matriz de confusión: filas = categoría observada, columnas = categoría prevista", "Confusion matrix: rows = observed category, columns = predicted category")}</caption>
              <thead>
                <tr>
                  <th scope="col">{tr("Observada \\ prevista", "Observed \\ predicted")}</th>
                  {classes.map((c) => (
                    <th key={c} scope="col">{c}</th>
                  ))}
                  <th scope="col">{tr("sin predicción", "no prediction")}</th>
                </tr>
              </thead>
              <tbody>
                {classes.map((a) => {
                  const total = get(detailEstimator, `confusion[${a}>${classes[0]}]`)?.n;
                  const cell = (b: string) => {
                    const r = get(detailEstimator, `confusion[${a}>${b}]`);
                    if (!r) return <td>—</td>;
                    const share = total ? dec((100 * r.value) / total, 1) : null;
                    const pct = share !== null ? tr(` (${share} %)`, ` (${share}%)`) : "";
                    return (
                      <td data-diagonal={a === b ? "true" : undefined} data-raw={String(r.value)}>
                        {r.value}
                        <span className="muted">{pct}</span>
                      </td>
                    );
                  };
                  return (
                    <tr key={a} data-class={a}>
                      <th scope="row"><ClassChip label={a} color={classColor(scheme, a)} /></th>
                      {classes.map((b) => (
                        <Fragment key={b}>{cell(b)}</Fragment>
                      ))}
                      {cell(NO_PREDICTION)}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </>
      )}

      {extra.length > 0 && (
        <details>
          <summary>{tr(`Otras métricas del informe (${extra.length})`, `Other metrics in the report (${extra.length})`)}</summary>
          <ul className="plain-list">
            {extra.map((r) => (
              <li key={`${r.estimator}/${r.metric}`}>
                <code>{r.estimator}</code> · <code>{r.metric}</code> = <span data-raw={String(r.value)}>{fmt(r.value)}</span> (n = {r.n})
              </li>
            ))}
          </ul>
        </details>
      )}
    </>
  );
}
