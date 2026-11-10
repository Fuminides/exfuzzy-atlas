import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { DomainInfo, EntityCollection, SummaryResponse, TaskInfo } from "../api/types";
import { Card, MoreInfo, NotYet, PageHead } from "../components/Card";
import { DistributionBar } from "../components/DistributionBar";
import { GroupChart } from "../components/GroupChart";
import { Legend } from "../components/Legend";
import { StateMessage } from "../components/StateMessage";
import { StationMap } from "../map/StationMap";
import type { StationRow } from "../map/stations";
import { useAsync, type AsyncState } from "../hooks/useAsync";
import { useOptionalAsync } from "../hooks/useOptionalAsync";
import { localized, tr } from "../i18n";
import type { Provenance } from "../hooks/useProvenance";
import { BLUES, ORANGES } from "../lib/colorScale";
import { domainUi, articles } from "../lib/domainUi";
import { entityRows } from "../lib/entityRows";
import { pct, unitLabel, withUnit } from "../lib/format";
import { className, officialNames } from "../lib/labels";
import {
  byKey,
  count,
  defaultThreshold,
  GROUPS,
  isClassified,
  lcFirst,
  median,
  periodText,
    rowsOf,
  stationsWithData,
  thresholdLabel,
  totalRow,
  worseShare,
} from "../lib/summary";
import { QuantileStrip } from "../components/QuantileStrip";

const BASEMAP: string | undefined = import.meta.env.VITE_BASEMAP_STYLE_URL || undefined;

interface Props {
  domain: DomainInfo;
  task: TaskInfo;
  territoryTitle: string;
  onProvenance: (p: Partial<Provenance>) => void;
}

/** Resumen: what the observed data say, with no model. Everything comes from the precomputed `SummaryResponse`. */
export function SummaryTab({ domain, task, territoryTitle, onProvenance }: Props) {
  const summary = useOptionalAsync((s) => api.summary(task.task_id, s), [task.task_id]);
  const entities = useAsync((s) => api.entities(domain.domain, task.task_id, s), [domain.domain, task.task_id]);
  const data = summary.status === "ok" ? summary.data : null;
  useEffect(() => {
    if (data) onProvenance({ dataVersion: data.data_version, synthetic: data.synthetic === true });
  }, [data, onProvenance]);

  if (summary.status === "loading" || summary.status === "idle") return <StateMessage kind="loading">{tr("Cargando el resumen de los datos…", "Loading the data summary…")}</StateMessage>;
  if (summary.status === "error")
    return (
      <StateMessage kind="error" onRetry={summary.reload}>
        {tr("No se pudo cargar el resumen: ", "Could not load the summary: ")}
        {summary.error.message}
      </StateMessage>
    );
  if (summary.status === "unavailable") {
    return (
      <div className="page">
        <PageHead title={tr(`Resumen de datos: ${territoryTitle}`, `Data summary: ${territoryTitle}`)}>
          {tr(`Cómo son los datos observados en ${territoryTitle}.`, `What the observed data in ${territoryTitle} look like.`)}
        </PageHead>
        <NotYet what={tr("El resumen de los datos", "The data summary")}>
          {tr(<>Se calcula al publicar el modelo y esta tarea todavía no lo tiene. Las pestañas <em>Patrones</em>, <em>Predicción</em> y <em>Explorar</em> siguen funcionando.</>, <>It&apos;s computed when the model is published, and this task doesn&apos;t have one yet. The <em>Patterns</em>, <em>Prediction</em> and <em>Explore</em> tabs still work.</>)}
        </NotYet>
      </div>
    );
  }
  return <SummaryView summary={summary.data} entities={entities} territoryTitle={territoryTitle} domainId={domain.domain} />;
}

type EntitiesState = AsyncState<EntityCollection> & { reload: () => void };

function SummaryView({ summary, entities, territoryTitle, domainId }: { summary: SummaryResponse; entities: EntitiesState; territoryTitle: string; domainId: string }) {
  const classified = isClassified(summary);
  const classes = summary.classes ?? [];
  const [threshold, setThreshold] = useState(() => (classified ? defaultThreshold(classes) : 0));
  const [selected, setSelected] = useState<string | null>(null);
  const unit = unitLabel(summary.unit);
  const noun = domainUi(domainId).noun;
  const g = articles(noun.one);
  const all = totalRow(summary);
  const withData = stationsWithData(summary);
  const entityData = useMemo(() => byKey(rowsOf(summary, "entity")), [summary]);
  const worse = classified ? thresholdLabel(classes, threshold, domainId) : "";

  const base = entities.status === "ok" ? entityRows(entities.data, new Set()) : null;
  const rows: StationRow[] = (base?.baseRows ?? []).map((r) => {
    const d = entityData.get(r.entityId);
    const value = classified ? worseShare(d, threshold) : median(d);
    return { ...r, value, missingReason: value === null ? "no_observation" : null, nValid: d?.n ?? 0 };
  });
  const values = rows.flatMap((r) => (r.value === null ? [] : [r.value]));
  const domainRange: readonly [number, number] = classified
    ? [0, Math.max(0.05, Math.ceil(Math.max(0, ...values) * 20) / 20)]
    : values.length
      ? [Math.min(...values), Math.max(...values) > Math.min(...values) ? Math.max(...values) : Math.min(...values) + 1]
      : [0, 1];
  const nameOf = base?.nameOf ?? ((id: string) => id);
  const fmtValue = (v: number) => (classified ? pct(v) : withUnit(v, unit));
  const total = rows.length;
  const placed = rows.filter((r) => r.value !== null).length;
  const selectedRow = selected ? entityData.get(selected) : undefined;
  const ranking = [...rows].sort((a, b) => (b.value ?? -Infinity) - (a.value ?? -Infinity) || a.name.localeCompare(b.name, "es"));
  const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
  const stations = withData.length === 1 ? noun.one : noun.many;
  const label = lcFirst(localized(summary.label, summary.label_en));
  const noData = tr("sin datos", "no data");
  // «Moderada o peor» in Spanish, “Moderate or worse” in English: the class is data, the quotes follow the language
  const quoted = tr(`«${worse}»`, `“${worse}”`);

  return (
    <div className="page" data-task={summary.task_id}>
      <PageHead title={tr(`Resumen de datos: ${territoryTitle}`, `Data summary: ${territoryTitle}`)}>
        {tr(<>Estás viendo <strong>{label}</strong> en {territoryTitle}, medido en {withData.length} {stations} entre {periodText(summary)}. Son datos observados, sin ningún modelo detrás. Aquí no hay predicciones.</>, <>You are looking at <strong>{label}</strong> in {territoryTitle}, measured at {withData.length} {stations} over {periodText(summary)}. These are observed data with no model, so there are no predictions here.</>)}
      </PageHead>

      <section className="data-strip" aria-label={tr("Qué hay en los datos", "What is in the data")}>
        <p className="data-facts small" data-testid="data-facts">
          <span>{territoryTitle}</span>
          <span>{localized(summary.label, summary.label_en)}{classified ? "" : ` (${unit})`}</span>
          <span>{periodText(summary)}</span>
          <span>
            {withData.length}
            {total > 0 && total !== withData.length ? tr(` de ${total}`, ` of ${total}`) : ""} {stations}
          </span>
          <span>
            {all ? count(all.n) : "—"} {tr("observaciones", "observations")}
          </span>
          {classified && officialNames({ classes }) && <span>{officialNames({ classes })}</span>}
        </p>
        {all && classified && all.shares ? (
          <DistributionBar classes={classes} shares={all.shares} subject={tr(`Todas las observaciones de ${territoryTitle}`, `All the observations in ${territoryTitle}`)} compact />
        ) : all ? (
          <QuantileStrip quantiles={all.quantiles ?? null} unit={unit} />
        ) : (
          <p className="muted small">{tr("Sin observaciones.", "No observations.")}</p>
        )}
        {summary.notes && summary.notes.length > 0 && (
          <MoreInfo summary={tr("Cómo se calcula", "How it is computed")}>
            <ul className="plain-list">
              {summary.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          </MoreInfo>
        )}
      </section>

      <div className="grid-2">
        <Card
          title={classified ? tr(`Dónde hay más horas en ${quoted}`, `Where hours in ${quoted} are most frequent`) : tr(`Mediana por ${noun.one}`, `Median by ${noun.one}`)}
          subtitle={
            classified
              ? tr(`Porcentaje de las horas observadas de cada ${noun.one} que caen en ${quoted}.`, `Percentage of each ${noun.one}'s observed hours that fall in ${quoted}.`)
              : tr(`Mediana de ${label} en cada ${noun.one}.`, `Median of ${label} at each ${noun.one}.`)
          }
          className="map-card"
          actions={
            classified && classes.length > 2 ? (
              <label className="inline-select">
                {tr("Contar desde la clase", "Count from the class")}
                <select value={threshold} onChange={(e) => setThreshold(Number(e.target.value))}>
                  {classes.slice(1).map((c, i) => (
                    <option key={c.label} value={i + 1}>
                      {className(c)}
                    </option>
                  ))}
                </select>
              </label>
            ) : undefined
          }
        >
          {entities.status === "loading" && <StateMessage kind="loading">{tr("Cargando el mapa…", "Loading the map…")}</StateMessage>}
          {entities.status === "error" && (
            <StateMessage kind="error" onRetry={entities.reload}>
              {tr("No se pudo cargar el mapa: ", "Could not load the map: ")}
              {entities.error.message}
            </StateMessage>
          )}
          {entities.status === "ok" && (
            <>
              <div className="map-box">
                <StationMap
                  rows={rows}
                  layerOptions={{ kind: "values", stops: classified ? ORANGES : BLUES, domain: domainRange, emphasis: null, selectedId: selected }}
                  onSelect={setSelected}
                  basemapUrl={BASEMAP}
                  plural={noun.many}
                  tipText={(r) => `${r.name}: ${r.value === null ? noData : fmtValue(r.value)}`}
                />
              </div>
              <Legend
                title={classified ? tr(`Horas en ${quoted}`, `Hours in ${quoted}`) : tr(`Mediana de ${label}`, `Median of ${label}`)}
                note={
                  classified
                    ? tr(`Parte de las observaciones de cada ${noun.one} que caen en esa clase. Es un dato observado.`, `Share of each ${noun.one}'s observations in that class. Observed data.`)
                    : tr(`Mediana de las observaciones de cada ${noun.one} (${unit}). Es un dato observado.`, `Median of each ${noun.one}'s observations (${unit}). Observed data.`)
                }
                stops={classified ? ORANGES : BLUES}
                domain={domainRange}
                ticks={[0, 0.5, 1].map((t) => fmtValue(domainRange[0] + t * (domainRange[1] - domainRange[0])))}
                nValid={placed}
                total={total}
                countLabel={tr(`${cap(noun.many)} con datos`, `${cap(noun.many)} with data`)}
                missingLabel={tr(`sin observaciones en ${g.este} ${noun.one} (anillo hueco)`, `no observations at this ${noun.one} (hollow ring)`)}
              />
            </>
          )}
        </Card>

        <div className="stack">
          <Card
            title={selected ? nameOf(selected) : tr(`Elige ${g.un} ${noun.one}`, `Choose a ${noun.one}`)}
            subtitle={selected ? tr("Su distribución en todo el periodo.", "Its distribution over the whole period.") : tr("Haz clic en el mapa o en la tabla para ver su distribución.", "Click on the map or in the table to see its distribution.")}
            className="station-card"
          >
            {selected && selectedRow && selectedRow.n > 0 ? (
              <>
                {classified && selectedRow.shares ? (
                  <DistributionBar classes={classes} shares={selectedRow.shares} subject={nameOf(selected)} />
                ) : (
                  <QuantileStrip quantiles={selectedRow.quantiles ?? null} unit={unit} />
                )}
                <p className="muted small">{tr(`${count(selectedRow.n)} observaciones.`, `${count(selectedRow.n)} observations.`)}</p>
              </>
            ) : selected ? (
              <p>{tr(`${g.Este} ${noun.one} no tiene observaciones en el periodo, así que no se muestra ningún valor.`, `This ${noun.one} has no observations in the period, so no value is shown.`)}</p>
            ) : (
              <p className="muted">
                {classified
                  ? tr(`Se verá el reparto entre ${classes.map(className).join(", ")}.`, `You'll see the split between ${classes.map(className).join(", ")}.`)
                  : tr(`Se verá la mediana y el rango de los valores en ${unit}.`, `You'll see the median and the range of the values in ${unit}.`)}
              </p>
            )}
          </Card>

          <Card
            title={tr(`Ranking de ${noun.many}`, `Ranking of ${noun.many}`)}
            subtitle={classified ? tr(`De más a menos horas en ${quoted}.`, `From most to fewest hours in ${quoted}.`) : tr("De mayor a menor mediana.", "From highest to lowest median.")}
            className="ranking-card"
          >
            <div className="table-scroll">
              <table className="plain ranking-table">
                <caption className="sr-only">
                  {classified
                    ? tr(`Ranking de ${noun.many} (alternativa textual al mapa): horas en ${quoted}`, `Ranking of ${noun.many} (text alternative to the map): hours in ${quoted}`)
                    : tr(`Ranking de ${noun.many} (alternativa textual al mapa): mediana`, `Ranking of ${noun.many} (text alternative to the map): median`)}
                </caption>
                <thead>
                  <tr>
                    <th scope="col" className="num">#</th>
                    <th scope="col">{cap(noun.one)}</th>
                    <th scope="col" className="num">{classified ? tr(`Horas en ${quoted}`, `Hours in ${quoted}`) : tr(`Mediana (${unit})`, `Median (${unit})`)}</th>
                    <th scope="col" className="num">{tr("Observaciones", "Observations")}</th>
                  </tr>
                </thead>
                <tbody>
                  {ranking.map((r, i) => (
                    <tr key={r.entityId} aria-selected={r.entityId === selected} data-entity={r.entityId}>
                      <td className="num">{r.value === null ? "—" : i + 1}</td>
                      <th scope="row">
                        <button type="button" className="link" onClick={() => setSelected(r.entityId)} aria-pressed={r.entityId === selected}>
                          {r.name}
                        </button>
                      </th>
                      <td className="num">{r.value === null ? <span className="missing-text">{noData}</span> : fmtValue(r.value)}</td>
                      <td className="num">{r.nValid ? count(r.nValid) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      </div>

      <div className="charts-title">
        <h2>{tr("Cómo cambia con el tiempo", "How it changes over time")}</h2>
        <p className="muted">
          {classified
            ? tr(`Porcentaje de las observaciones en ${quoted}, agrupadas por calendario local (${summary.timezone}).`, `Percentage of the observations in ${quoted}, grouped by the local calendar (${summary.timezone}).`)
            : tr(`Mediana y rango intercuartílico de ${label}, agrupadas por calendario local (${summary.timezone}).`, `Median and interquartile range of ${label}, grouped by the local calendar (${summary.timezone}).`)}
        </p>
      </div>
      <div className="grid-2 charts">
        {GROUPS.map((g) => (
          <GroupChart key={g} group={g} rows={rowsOf(summary, g)} classified={classified ? { from: threshold, label: worse } : null} unit={unit} />
        ))}
      </div>
    </div>
  );
}
