import type { ObservationProperties } from "../api/types";
import { tr } from "../i18n";
import type { AsyncState } from "../hooks/useAsync";
import type { TimeWindow } from "../lib/windows";
import { DataPanel } from "./DataPanel";
import { StateMessage } from "./StateMessage";
import { UnmodelledNotice } from "./UnmodelledNotice";

interface Props {
  noun: { one: string; many: string };
  irregular: boolean;
  label: string;
  window: TimeWindow | null;
  observationsStatus: AsyncState<unknown>["status"];
  entityId: string | null;
  entityName: string | null;
  unmodelled: boolean;
  observation: ObservationProperties | null;
}

/** Data mode, side panel: what the selected entity published, without going through the model. */
export function DataSidebar({ noun, irregular, label, window, observationsStatus, entityId, entityName, unmodelled, observation }: Props) {
  return (
    <>
      <section className="data-intro" aria-label={tr("Modo Data", "Data mode")}>
        <h2>{tr("Modo Data", "Data mode")}</h2>
        <p className="muted">
          {tr(<>Valores observados y publicados, sin pasar por el modelo. Aparecen el objetivo ({label}) en su hora de validez y cada entrada del modelo en el instante que indica. Un hueco se muestra como «sin dato» con su motivo.</>,
            <>Observed, published values that don&apos;t go through the model. You see the target ({label}) at its valid time and each model input at the instant it states. A gap shows as “no data” with its reason.</>,
          )}
        </p>
        {irregular && window && (
          <p className="muted" data-testid="irregular-window-hint">
            {tr(<>Ventana <code>[{window.from}, {window.to})</code> UTC, elegida en la línea temporal de abajo. De cada {noun.one} se muestra la última muestra de la ventana.</>,
              <>Window <code>[{window.from}, {window.to})</code> UTC, chosen on the timeline below. For each {noun.one}, the latest sample in the window is shown.</>,
            )}
          </p>
        )}
      </section>
      {observationsStatus === "ok" && !entityId && (
        <p className="muted">{tr(`Elige ${irregular ? "un" : "una"} ${noun.one} en el mapa o en la tabla para ver sus observaciones.`, `Pick a ${noun.one} on the map or in the table to see its observations.`)}</p>
      )}
      {entityId && unmodelled && <UnmodelledNotice name={entityName!} noun={noun.one} />}
      {entityId && !unmodelled && observationsStatus === "ok" && <DataPanel entityName={entityName!} observation={observation} targetName={label} />}
      {entityId && !unmodelled && observationsStatus === "loading" && <StateMessage kind="loading">{tr("Cargando observaciones…", "Loading observations…")}</StateMessage>}
    </>
  );
}
