import { tr } from "../i18n";
import type { AsyncState } from "../hooks/useAsync";
import type { Mode } from "../lib/mode";
import { StateMessage } from "./StateMessage";

type Request = AsyncState<unknown> & { reload: () => void };

interface Props {
  mode: Mode;
  territoriesOn: boolean;
  duelOn: boolean;
  /** The rule map is an instant (firing_strength) that is still being dragged. */
  instantSettling: boolean;
  /** The instant of a regular task is still being dragged. */
  staleInstant: boolean;
  ruleMap: Request;
  ruleMapB: Request;
  territories: Request;
  predictions: Request;
  observations: Request;
}

/** "Actualizando…" while the map's request is in flight and its error with a retry, over the map. */
export function MapStatus({ mode, territoriesOn, duelOn, instantSettling, staleInstant, ruleMap, ruleMapB, territories, predictions, observations }: Props) {
  return (
    <>
      {mode === "rules" && !territoriesOn && (ruleMap.status === "loading" || (duelOn && ruleMapB.status === "loading") || instantSettling) && (
        <p className="map-status" role="status">{tr("Actualizando el mapa…", "Updating the map…")}</p>
      )}
      {territoriesOn && territories.status === "loading" && <p className="map-status" role="status">{tr("Actualizando territorios…", "Updating territories…")}</p>}
      {mode === "prediction" && (predictions.status === "loading" || staleInstant) && <p className="map-status" role="status">{tr("Cargando predicciones…", "Loading predictions…")}</p>}
      {mode === "data" && (observations.status === "loading" || staleInstant) && <p className="map-status" role="status">{tr("Cargando observaciones…", "Loading observations…")}</p>}
      {mode === "rules" && !territoriesOn && ruleMap.status === "error" && (
        <div className="map-status">
          <StateMessage kind="error" onRetry={ruleMap.reload}>{tr("No se pudo cargar el mapa de la regla: ", "Could not load the rule map: ")}{ruleMap.error.message}</StateMessage>
        </div>
      )}
      {territoriesOn && territories.status === "error" && (
        <div className="map-status">
          <StateMessage kind="error" onRetry={territories.reload}>{tr("No se pudieron cargar los territorios: ", "Could not load the territories: ")}{territories.error.message}</StateMessage>
        </div>
      )}
      {mode === "prediction" && predictions.status === "error" && (
        <div className="map-status">
          <StateMessage kind="error" onRetry={predictions.reload}>{tr("No se pudieron cargar las predicciones: ", "Could not load the predictions: ")}{predictions.error.message}</StateMessage>
        </div>
      )}
      {mode === "data" && observations.status === "error" && (
        <div className="map-status">
          <StateMessage kind="error" onRetry={observations.reload}>{tr("No se pudieron cargar las observaciones: ", "Could not load the observations: ")}{observations.error.message}</StateMessage>
        </div>
      )}
      {duelOn && ruleMapB.status === "error" && (
        <div className="map-status">
          <StateMessage kind="error" onRetry={ruleMapB.reload}>{tr("No se pudo cargar el mapa de la regla B: ", "Could not load rule B's map: ")}{ruleMapB.error.message}</StateMessage>
        </div>
      )}
    </>
  );
}
