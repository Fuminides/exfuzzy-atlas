import type { MetricRow, ModelCard } from "../api/types";
import { fmt, horizonText, utcStamp } from "../lib/format";
import { accuracySummary } from "./AccuracyBlock";
import { ClassMetrics } from "./ClassMetrics";
import { tr } from "../i18n";

interface Props {
  card: ModelCard;
  /** Collapsed by default except where evaluation is the point (Prediction mode). */
  open?: boolean;
  /** Unit of the target (regression): MAE and RMSE are in it. */
  unit?: string;
  /** Always-visible one-line summary above the collapsed details (Predicción). */
  brief?: boolean;
}

const MAIN = ["mae", "rmse", "r2"] as const;
const HEADER: Record<(typeof MAIN)[number], string> = { mae: "MAE", rmse: "RMSE", r2: "R²" };
// Built at render time (not at import): the language can change while the page is open.
const estimatorLabel = (e: string): string | undefined =>
  ({
    exfuzzy: "ExFuzzy",
    persistence: tr("Persistencia", "Persistence"),
    climatology: tr("Climatología", "Climatology"),
    ridge: "Ridge",
    hist_gradient_boosting: "HGB (gradient boosting)",
  })[e];
const overall = (r: MetricRow) => (r.slice ?? "all") === "all";

/** Compact evaluation table (ExFuzzy and baselines, same test split) plus the run's split, warnings and data version. */
export function ModelPanel({ card, open = false, unit, brief = false }: Props) {
  const { manifest, metrics } = card;
  // A published target scheme means a classifier: its report has classification metrics, not MAE/RMSE/R².
  const scheme = card.target_scheme ?? null;
  const rows = (metrics?.rows ?? []).filter(overall);
  const estimators = [...new Set(rows.map((r) => r.estimator))].sort((a, b) => Number(b === "exfuzzy") - Number(a === "exfuzzy"));
  const get = (est: string, metric: string) => rows.find((r) => r.estimator === est && r.metric === metric);
  const best = (metric: (typeof MAIN)[number]): string | null => {
    const vals = estimators.flatMap((e) => (get(e, metric) ? [[e, get(e, metric)!.value] as const] : []));
    if (vals.length < 2) return null;
    const pick = metric === "r2" ? Math.max : Math.min;
    const target = pick(...vals.map(([, v]) => v));
    const winners = vals.filter(([, v]) => v === target);
    return winners.length === 1 ? winners[0]![0] : null;
  };
  const bests = Object.fromEntries(MAIN.map((m) => [m, best(m)]));
  const extra = rows.filter((r) => !(MAIN as readonly string[]).includes(r.metric));
  const s = manifest.split;
  const splitDiffers = metrics !== null && metrics !== undefined && JSON.stringify(metrics.split) !== JSON.stringify(s);

  const line = brief ? accuracySummary(card, unit ?? "") : null;
  return (
    <>
    {brief && (
      <p className="model-brief" data-testid="model-brief">
        <strong>{tr("Calidad del modelo.", "Model quality.")}</strong> {line ?? tr("Este modelo no publica métricas de evaluación.", "This model publishes no evaluation metrics.")}
      </p>
    )}
    <details className="model-panel" open={open}>
      <summary>
        <h2>{tr("Modelo y evaluación", "Model and evaluation")}</h2>
      </summary>
      <p className="muted">
        <code>{manifest.model_id}</code> · {tr("objetivo", "target")} <code>{manifest.target}</code> {horizonText(manifest.horizon_hours)} · ex_fuzzy{" "}
        {manifest.exfuzzy_version} · <code>data_version</code> <code>{card.data_version}</code> · {tr("semilla", "seed")} {manifest.seed}
      </p>

      <h3>{tr("Partición temporal (semiabierta, UTC)", "Time split (half-open, UTC)")}</h3>
      <dl className="split">
        <div><dt>{tr("Entrenamiento", "Training")}</dt><dd>[{utcStamp(s.train_from_utc)}, {utcStamp(s.train_to_utc)})</dd></div>
        {s.validation_from_utc && s.validation_to_utc && (
          <div><dt>{tr("Validación", "Validation")}</dt><dd>[{utcStamp(s.validation_from_utc)}, {utcStamp(s.validation_to_utc)})</dd></div>
        )}
        <div><dt>{tr("Prueba", "Test")}</dt><dd>[{utcStamp(s.test_from_utc)}, {utcStamp(s.test_to_utc)})</dd></div>
        <div><dt>{tr("Margen (embargo)", "Gap (embargo)")}</dt><dd>{s.embargo_hours} h</dd></div>
      </dl>
      {splitDiffers && <p className="notice">{tr("La partición del informe de métricas no coincide con la del manifiesto.", "The metrics report's split doesn't match the manifest's.")}</p>}

      <h3>{scheme ? tr("Clasificación en el periodo de prueba", "Classification in the test period") : tr("Error en el periodo de prueba", "Error in the test period")}</h3>
      {!metrics || estimators.length === 0 ? (
        <p className="muted">{tr("Este modelo no publica métricas de evaluación.", "This model publishes no evaluation metrics.")}</p>
      ) : scheme ? (
        <ClassMetrics rows={rows} scheme={scheme} />
      ) : (
        <>
          <table className="plain metrics">
            <caption>
              {tr(`Mismo periodo de prueba y mismas filas para todos los estimadores. MAE y RMSE en ${unit ?? "la unidad del objetivo"}, y R² sin unidad.`, `Same test period and same rows for every estimator. MAE and RMSE are in ${unit ?? "the target's unit"}, and R² has no unit.`)}
            </caption>
            <thead>
              <tr>
                <th scope="col">{tr("Estimador", "Estimator")}</th>
                {MAIN.map((m) => (
                  <th key={m} scope="col">{HEADER[m]}</th>
                ))}
                <th scope="col">n</th>
              </tr>
            </thead>
            <tbody>
              {estimators.map((e) => (
                <tr key={e}>
                  <th scope="row">
                    {estimatorLabel(e) ?? e.replace(/_/g, " ")}
                  </th>
                  {MAIN.map((m) => {
                    const row = get(e, m);
                    return (
                      <td key={m} data-best={bests[m] === e ? "true" : undefined} className={bests[m] === e ? "best" : undefined}>
                        {row ? <span data-raw={String(row.value)}>{fmt(row.value)}</span> : "—"}
                      </td>
                    );
                  })}
                  <td>{get(e, "mae")?.n ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted">
            {tr("En negrita, el valor más favorable de cada columna (menor MAE/RMSE, mayor R²), si solo hay uno.",
              "Bold marks the most favourable value in each column (lowest MAE/RMSE, highest R²), when there is only one.")}
          </p>
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
      )}

      {manifest.warnings && manifest.warnings.length > 0 && (
        <>
          <h3>{tr("Avisos del entrenamiento", "Training warnings")}</h3>
          <ul className="warnings">
            {manifest.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </>
      )}
    </details>
    </>
  );
}
