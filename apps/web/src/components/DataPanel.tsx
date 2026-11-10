import type { FeatureValue, ObservationProperties } from "../api/types";
import { tr } from "../i18n";
import { fmtNum, formatInstant, missingText, unitLabel } from "../lib/format";
import { useZone } from "../lib/zone";
import { useFeatureLabel } from "../lib/labels";
import { isStaticData } from "../lib/dataMode";

interface Props {
  entityName: string;
  /** The entity's feature of the `/observations` answer; null when the answer has none for it. */
  observation: ObservationProperties | null;
  targetName: string;
}

function ValueCell({ v }: { v: FeatureValue }) {
  if (v.value === null) {
    return (
      <span className="missing-text" data-testid="data-missing">
        {tr("sin dato", "no data")} · {missingText(v.missing_reason ?? "no_observation")}
      </span>
    );
  }
  return (
    <span data-raw={String(v.value)}>
      {fmtNum(v.value)} {v.unit ? unitLabel(v.unit) : ""}
    </span>
  );
}

/**
 * Data mode, selected entity: the target observed at `valid_at` and the model's inputs of that issue time, exactly as
 * published, with unit, source and the instant each one was observed. A missing value says why; it is never shown as 0.
 * Nothing here is predicted, interpolated or derived from rules.
 */
export function DataPanel({ entityName, observation, targetName }: Props) {
  const zone = useZone();
  const label = useFeatureLabel();
  if (!observation) {
    return (
      <section className="data-panel" aria-label={tr("Observaciones de la entidad", "Observations of the entity")}>
        <h2>{tr(`Observaciones de ${entityName}`, `Observations of ${entityName}`)}</h2>
        <p className="muted">{isStaticData() ? tr("No hay observaciones de esta entidad en el instante elegido.", "No observations for this entity at the chosen instant.") : tr("La API no devolvió observaciones para esta entidad en el instante elegido.", "The API returned no observations for this entity at the chosen instant.")}</p>
      </section>
    );
  }
  const rows: { v: FeatureValue; role: "objetivo" | "entrada" }[] = [
    ...(observation.target ? [{ v: observation.target, role: "objetivo" as const }] : []),
    ...observation.inputs.map((v) => ({ v, role: "entrada" as const })),
  ];
  const issued = observation.issued_at_utc ? formatInstant(observation.issued_at_utc, zone) : "—";
  const valid = observation.valid_at_utc ? <strong>{formatInstant(observation.valid_at_utc, zone)}</strong> : "—";
  return (
    <section className="data-panel" aria-label={tr("Observaciones de la entidad", "Observations of the entity")}>
      <h2>{tr(`Observaciones de ${entityName}`, `Observations of ${entityName}`)}</h2>
      <p className="muted">
        {tr(<>Emisión {issued}. El objetivo ({targetName}) se observa en la hora de validez {valid}, y cada entrada en el instante que indica. Son valores publicados.</>,
          <>Issue {issued}. The target ({targetName}) is observed at the valid time {valid}, and each input at the instant it states. These are published values.</>,
        )}
      </p>
      {observation.target_label && (
        <p data-testid="data-target-label">
          {tr("Categoría del objetivo observado: ", "Observed target category: ")}<strong>{observation.target_label}</strong>
        </p>
      )}
      <table className="data-table">
        <caption>{tr("Valores observados", "Observed values")}</caption>
        <thead>
          <tr>
            <th scope="col">Variable</th>
            <th scope="col">{tr("Valor", "Value")}</th>
            <th scope="col">{tr("Observado el", "Observed at")}</th>
            <th scope="col">{tr("Fuente", "Source")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ v, role }) => (
            <tr key={`${role}:${v.feature}`} data-role={role} data-feature={v.feature}>
              <th scope="row">
                {role === "objetivo" ? targetName.charAt(0).toUpperCase() + targetName.slice(1) : label(v.feature)}
                <span className="muted"> · {role === "objetivo" ? tr("objetivo", "target") : tr("entrada", "input")}</span>
              </th>
              <td>
                <ValueCell v={v} />
              </td>
              <td>{v.observed_at_utc ? formatInstant(v.observed_at_utc, zone) : "—"}</td>
              <td>{v.source_id ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
