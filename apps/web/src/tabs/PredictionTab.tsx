import type { DomainInfo, TaskInfo } from "../api/types";
import { PageHead } from "../components/Card";
import { Naming } from "../components/Naming";
import { HorizonBox } from "../components/HorizonBox";
import { StateMessage } from "../components/StateMessage";
import { useModelContext } from "../hooks/useModelContext";
import type { Provenance } from "../hooks/useProvenance";
import { formatDate } from "../lib/format";
import { horizonClause, predictsText } from "../lib/taskText";
import { Workspace } from "../Workspace";
import { tr } from "../i18n";

const NO_VARIABLES: never[] = [];

interface Props {
  domain: DomainInfo;
  task: TaskInfo;
  territoryTitle: string;
  horizons: readonly number[];
  onDate: (label: string) => void;
  onProvenance: (p: Partial<Provenance>) => void;
  /** "la decidió R04" opens the rule in Patrones. */
  onOpenRule?: (ruleId: string) => void;
  /** Goes to the performance report (how much the model gets right, against the baselines). */
  onOpenReport?: () => void;
  /** The entity to open selected (a station card of Patrones). */
  focusEntity?: string | null;
}

/** Predicción: the horizon explained, the prediction map and series with "¿Y si…?", and how much the model gets right. */
export function PredictionTab({ domain, task, territoryTitle, horizons, onDate, onProvenance, onOpenRule, onOpenReport, focusEntity = null }: Props) {
  const ctx = useModelContext(domain, task);
  const { card, rules, scheme, zone } = ctx;
  if (ctx.modelId === null) return <StateMessage kind="empty">{tr(<>La tarea {task.task_id} todavía no tiene un modelo publicado.</>, <>Task {task.task_id} has no published model yet.</>)}</StateMessage>;
  const coverage = ctx.coverage;
  const ready = card.status === "ok" && rules.status === "ok" && coverage != null;
  const regular = ready && coverage.regular !== false;
  const predicts = predictsText(task, scheme);
  return (
    <Naming variables={rules.status === "ok" ? rules.data.variables : NO_VARIABLES} scheme={scheme} target={task.target}>
      <div className="page page--wide" data-task={task.task_id}>
        <PageHead title={tr(`Predicción: ${predicts} en ${territoryTitle}`, `Prediction: ${predicts} in ${territoryTitle}`)}>
          {ready && regular && task.horizon_hours > 0 ? (
            tr(<>Estás viendo lo que el modelo prevé {horizonClause(task.horizon_hours)} para cada {domain.domain === "mobility" ? "zona" : "estación"} de {territoryTitle}, junto a lo que se observó después. Los datos van de {formatDate(coverage.issued_from_utc, zone)} a {formatDate(coverage.issued_to_utc, zone)}.</>,
              <>
                You are looking at what the model predicts {horizonClause(task.horizon_hours)} for each {domain.domain === "mobility" ? "zone" : "station"} in {territoryTitle}, next to what was observed afterwards. The data run from{" "}
                {formatDate(coverage.issued_from_utc, zone)} to {formatDate(coverage.issued_to_utc, zone)}.
              </>,
            )
          ) : (
            tr(<>Estás viendo lo que el modelo estima para cada punto de {territoryTitle} frente a lo medido en esa misma muestra.</>,
              <>You are looking at what the model estimates for each point in {territoryTitle} against what was measured in that same sample.</>,
            )
          )}
        </PageHead>
        <div className="workspace-frame workspace-frame--time-first" data-testid="prediction-frame">
          <Workspace key={task.task_id} domain={domain} task={task} mode="prediction" onMode={() => {}} onDate={onDate} onProvenance={onProvenance} onOpenRule={onOpenRule} initialEntityId={focusEntity} />
        </div>
        {ready && <HorizonBox task={task} card={card.data} coverage={coverage} rules={rules.data} scheme={scheme} zone={zone} horizons={horizons} />}
        {ready && onOpenReport && (
          <p className="report-link" data-testid="report-link">
            {tr("¿Cuánto acierta este modelo frente a otros? ", "How does this model compare with others? ")}
            <button type="button" className="link link--go" onClick={onOpenReport}>
              {tr(<>Ver el <em>informe de rendimiento</em></>, <>See the <em>performance report</em></>)}
            </button>
          </p>
        )}
      </div>
    </Naming>
  );
}
