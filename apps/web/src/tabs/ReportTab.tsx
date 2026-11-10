import type { DomainInfo, TaskInfo } from "../api/types";
import { AccuracyBlock } from "../components/AccuracyBlock";
import { PageHead } from "../components/Card";
import { ModelPanel } from "../components/ModelPanel";
import { Naming } from "../components/Naming";
import { PerformanceChart } from "../components/PerformanceChart";
import { StateMessage } from "../components/StateMessage";
import { useModelContext } from "../hooks/useModelContext";
import { tr } from "../i18n";
import { unitLabel } from "../lib/format";
import { importancePeriod } from "../lib/importance";
import { horizonClause, predictsText } from "../lib/taskText";

const NO_VARIABLES: never[] = [];

interface Props {
  domain: DomainInfo;
  task: TaskInfo;
  territoryTitle: string;
}

/**
 * Informe de rendimiento / Performance report: how the model of this horizon does on the test period against the
 * standard baselines (bars), how often it is right per category, and the full evaluation table. All from the model
 * card's report; nothing is recomputed.
 */
export function ReportTab({ domain, task, territoryTitle }: Props) {
  const ctx = useModelContext(domain, task);
  const { card, rules, scheme } = ctx;
  if (ctx.modelId === null) return <StateMessage kind="empty">{tr(<>La tarea {task.task_id} todavía no tiene un modelo publicado.</>, <>Task {task.task_id} has no published model yet.</>)}</StateMessage>;
  if (card.status === "error") return <StateMessage kind="error" onRetry={card.reload}>{tr("No se pudo cargar la ficha del modelo: ", "Could not load the model card: ")}{card.error.message}</StateMessage>;
  if (card.status !== "ok" || rules.status !== "ok") return <StateMessage kind="loading">{tr("Cargando el informe…", "Loading the report…")}</StateMessage>;
  const period = importancePeriod({ period_from_utc: card.data.manifest.split.test_from_utc, period_to_utc: card.data.manifest.split.test_to_utc });
  // The hero's eyebrow takes the years only ("2025", "2024–2025"); the lead keeps the period in full.
  const split = card.data.manifest.split;
  const fromYear = new Date(split.test_from_utc).getUTCFullYear();
  const toYear = new Date(Date.parse(split.test_to_utc) - 1).getUTCFullYear();
  const years = fromYear === toYear ? String(fromYear) : `${fromYear}–${toYear}`;
  const predicts = predictsText(task, scheme);
  const unit = unitLabel(task.unit);
  const when = task.horizon_hours > 0 ? ` ${horizonClause(task.horizon_hours)}` : "";
  return (
    <Naming variables={rules.status === "ok" ? rules.data.variables : NO_VARIABLES} scheme={scheme} target={task.target} rules={rules.status === "ok" ? rules.data.rules : NO_VARIABLES}>
      <div className="page" data-task={task.task_id}>
        <PageHead title={tr(`Informe de rendimiento: ${territoryTitle}`, `Performance report: ${territoryTitle}`)}>
          {tr(<>Cómo predice el modelo {predicts}{when} en el periodo de prueba ({period}), frente a modelos de referencia sobre las mismas predicciones.</>,
            <>How well the model predicts {predicts}{when} in the test period ({period}), compared with baseline models on the same predictions.</>)}
        </PageHead>
        <PerformanceChart card={card.data} rules={rules.data} period={years} unit={task.unit} context={`${territoryTitle} · ${task.horizon_hours > 0 ? `+${task.horizon_hours} h` : tr("misma muestra", "same sample")}`} />
        <details className="report-details">
          <summary>{tr("Detalle técnico: acierto por categoría y tabla de evaluación", "Technical detail: accuracy per category and evaluation table")}</summary>
          <AccuracyBlock card={card.data} unit={unit} />
          <ModelPanel card={card.data} unit={unit} />
        </details>
      </div>
    </Naming>
  );
}
