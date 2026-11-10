import { useMemo, useState } from "react";
import { api } from "../api/client";
import type { LinguisticVariable, RuleTrace, ScenarioRequest, ScenarioResponse } from "../api/types";
import { tr } from "../i18n";
import { useAsync } from "../hooks/useAsync";
import { useDebounced } from "../hooks/useDebounced";
import { fmt, fmtFine, fmtNum, formatInstant, missingText, sameInstant, unitLabel } from "../lib/format";
import { isStaticData } from "../lib/dataMode";
import { gridIndex, nearestInstant } from "../lib/whatifSweeps";
import type { TimeWindow } from "../lib/windows";
import { useZone } from "../lib/zone";
import { useWhatIfSweeps } from "../hooks/useExportSupport";
import { changedRuleDeltas, membershipChanges, signed } from "../lib/whatif";
import { condText, useFeatureLabel, useNames } from "../lib/labels";
import { whatIfTopRuleLabel, whatIfTopRuleSame } from "../lib/mixtureViews";

/** The label the contract requires on every what-if; it is shown before, during and after any scenario (built at render: the language can change while the page is open). */
export const whatIfLabel = (): string => tr("respuesta del modelo ante entradas modificadas", "the model's response to modified inputs");
/** The Spanish label, read once at import (before App sets a language the interface is in Spanish): the Spanish tests compare against it. */
export const WHAT_IF_LABEL = whatIfLabel();

/** Wait this long after the last edit before asking the API (a slider drag fires dozens of changes). */
const EDIT_DEBOUNCE_MS = 300;
const SHOWN_ROWS = 8;

interface Props {
  modelId: string;
  entityId: string;
  entityName: string;
  /** Issue time of the published row the scenario starts from. */
  at: string;
  /** The model's variables: their `domain` is the allowed range of an override. */
  variables: readonly LinguisticVariable[];
  /** The observed row (the trace at `at`); null while it loads. */
  baseline: RuleTrace | null;
  classifier: boolean;
  /** Mixture of rules (v0.7): no winning rule and no association; the scenario names the rule that adds the most. */
  mixture?: boolean;
  /** Static export: go to an instant that has a sweep (the app moves its time, or picks that sample). */
  onGoTo?: (instant: string) => void;
  /** Static export, irregular tasks: the instants offered are the samples of this window. */
  within?: TimeWindow | null;
}

type Overrides = Record<string, number>;

const domainOf = (v: LinguisticVariable | undefined): [number, number] | null => {
  const d = v?.domain as unknown;
  return Array.isArray(d) && d.length === 2 && typeof d[0] === "number" && typeof d[1] === "number" ? [d[0], d[1]] : null;
};

/** A step that gives about 200 positions over the domain, rounded to one significant digit. */
function stepFor([lo, hi]: [number, number]): number {
  const raw = (hi - lo) / 200;
  if (!(raw > 0)) return 1;
  const p = 10 ** Math.floor(Math.log10(raw));
  return Math.max(p * Math.round(raw / p), p);
}

/**
 * What-if (E5): edits a copy of ONE published input row and asks the API to run the real inference again. The page
 * never recomputes memberships or firing. Nothing is written and the map and the dataset do not change. Remount it
 * (`key`) when the entity or the issue time changes: the edits belong to one row.
 */
export function WhatIfPanel({ modelId, entityId, entityName, at, variables, baseline, classifier, mixture = false, onGoTo, within = null }: Props) {
  const staticSite = isStaticData();
  const zone = useZone();
  // Static export: one input at a time, at the instants and on the grid of values that were precomputed.
  const sweeps = useWhatIfSweeps(modelId, entityId);
  const label = useFeatureLabel();
  const [overrides, setOverrides] = useState<Overrides>({});
  const [showAll, setShowAll] = useState(false);
  const settled = useDebounced(overrides, EDIT_DEBOUNCE_MS);
  const body: ScenarioRequest = { model_id: modelId, entity_id: entityId, at, overrides: settled };
  // The request follows the settled edits; what is shown follows the current ones (a reset hides the old answer at once).
  const result = useAsync((s) => api.scenario(body, s), [modelId, entityId, at, JSON.stringify(settled)], Object.keys(settled).length > 0);
  const pending = JSON.stringify(settled) !== JSON.stringify(overrides);
  const edited = Object.keys(overrides).length > 0;

  const byFeature = useMemo(() => new Map(variables.map((v) => [v.feature, v])), [variables]);
  const rows = baseline?.feature_values ?? [];
  const set = (feature: string, value: number | null) =>
    setOverrides((old) => {
      // a static export holds one input at a time: moving another one replaces the first
      const next = staticSite ? {} : { ...old };
      if (value === null || Number.isNaN(value)) delete next[feature];
      else next[feature] = value;
      return next;
    });

  if (staticSite) {
    if (sweeps.status === "loading" || sweeps.status === "idle") return null;
    if (sweeps.status === "error") {
      return (
        <section className="whatif" aria-label="What-if" data-testid="whatif-panel">
          <p role="alert" className="notice">{sweeps.error.message}</p>
        </section>
      );
    }
    const featured = sweeps.data?.at ?? [];
    if (featured.length === 0) return null;
    if (!featured.some((x) => sameInstant(x, at))) {
      const near = onGoTo ? nearestInstant(featured, at, within) : null;
      if (near === null) return null;
      return (
        <section className="whatif" aria-label="What-if" data-testid="whatif-panel">
          <h2>What-if · {entityName}</h2>
          <p className="whatif-label" data-testid="whatif-label" role="note">
            {whatIfLabel()}
          </p>
          <p>
            <button type="button" onClick={() => onGoTo!(near)} data-testid="whatif-goto">
              {tr(`Ir al instante con escenarios más cercano: ${formatInstant(near, zone)}`, `Go to the nearest instant with scenarios: ${formatInstant(near, zone)}`)}
            </button>
          </p>
        </section>
      );
    }
  }
  const grids = sweeps.status === "ok" ? (sweeps.data?.grid ?? {}) : {};

  return (
    <section className="whatif" aria-label="What-if" data-testid="whatif-panel">
      <h2>What-if · {entityName}</h2>
      <p className="whatif-label" data-testid="whatif-label" role="note">
        {whatIfLabel()}
      </p>
      <p className="muted">
        {staticSite
          ? tr(<>Mueve una entrada de este registro (emisión <code>{at}</code>) y se muestra la respuesta del modelo, calculada de antemano para cada paso de la variable. Es un escenario artificial. El mapa y el conjunto de datos no cambian.</>,
              <>Move one input of this record (issue <code>{at}</code>) and the model&apos;s response is shown, precomputed for each step of the variable. This is an artificial scenario. The map and the dataset stay as they are.</>)
          : tr(<>Cambia las entradas de este registro (emisión <code>{at}</code>) y el motor del modelo vuelve a ejecutarse sobre una copia modificada. Es un escenario artificial. El mapa y el conjunto de datos no cambian, y se rechazan los valores de entrada que quedan fuera del rango <code>domain</code> de la variable.</>,
              <>Change this record&apos;s inputs (issue <code>{at}</code>) and the model&apos;s engine runs again on a modified copy. This is an artificial scenario. The map and the dataset stay as they are, and input values outside the variable&apos;s <code>domain</code> range are rejected.</>)}
      </p>
      <div className="whatif-status" aria-live="polite" data-testid="whatif-status">
        {!baseline && <p role="status">{tr("Cargando las entradas observadas…", "Loading the observed inputs…")}</p>}
        {baseline && !edited && (
          <p className="muted" data-testid="whatif-idle">
            {tr("Todavía no has cambiado nada y se muestran los valores observados. Mueve una entrada para ver cómo responde el modelo.", "Nothing has changed yet, so these are the observed values. Move an input to see how the model responds.")}
          </p>
        )}
        {edited && (result.status === "loading" || pending) && (
          <p role="status">
            {staticSite ? tr("Cargando la respuesta del modelo…", "Loading the model's response…") : tr("Ejecutando el modelo con las entradas modificadas…", "Running the model with the modified inputs…")}
          </p>
        )}
        {edited && !pending && result.status === "error" && (
          <p role="alert" className="notice" data-testid="whatif-error">
            {tr("El escenario no se pudo ejecutar. ", "The scenario could not be run. ")}
            {result.error.message}
          </p>
        )}
        {edited && !pending && result.status === "ok" && <PredictionSummary r={result.data} classifier={classifier} mixture={mixture} />}
      </div>
      <p>
        <button type="button" onClick={() => setOverrides({})} disabled={!edited} data-testid="whatif-reset">
          {tr("Restablecer a los valores observados", "Reset to the observed values")}
        </button>
      </p>
      {baseline && (
        <ul className="whatif-inputs" aria-label={tr("Entradas del modelo", "Model inputs")}>
          {rows.map((fv) => {
            const variable = byFeature.get(fv.feature);
            const domain = domainOf(variable);
            const grid = grids[fv.feature];
            const overridden = overrides[fv.feature];
            const current = overridden ?? fv.value;
            return (
              <li key={fv.feature} data-feature={fv.feature} data-origin={overridden === undefined ? "observed" : "overridden"}>
                <span className="whatif-head">
                  <label htmlFor={`whatif-${fv.feature}`}>
                    {label(fv.feature)}
                    {fv.unit ? <span className="muted"> ({unitLabel(fv.unit)})</span> : null}
                  </label>
                  <span className="whatif-observed">
                    {tr("observado: ", "observed: ")}
                    {fv.value === null ? <em>{tr("sin dato", "no data")} ({missingText(fv.missing_reason ?? "no_observation")})</em> : <span data-raw={String(fv.value)}>{fmtNum(fv.value)}</span>}
                    {overridden !== undefined && (
                      <>
                        {" "}
                        · <strong>{tr("modificado: ", "modified: ")}{fmtNum(overridden)}</strong>
                      </>
                    )}
                    {domain && <span className="muted whatif-domain">{tr(` · rango permitido: ${fmtNum(domain[0])} a ${fmtNum(domain[1])}`, ` · allowed range: ${fmtNum(domain[0])} to ${fmtNum(domain[1])}`)}</span>}
                  </span>
                </span>
                <span className="whatif-controls">
                  {staticSite ? (
                    grid && (
                      <input
                        id={`whatif-${fv.feature}`}
                        type="range"
                        aria-label={tr(`${label(fv.feature)} (deslizador)`, `${label(fv.feature)} (slider)`)}
                        aria-valuetext={fmtNum(grid[gridIndex(grid, current)]!)}
                        data-grid={grid.length}
                        min={0}
                        max={grid.length - 1}
                        step={1}
                        value={gridIndex(grid, current)}
                        onChange={(e) => set(fv.feature, grid[Number(e.target.value)]!)}
                      />
                    )
                  ) : (
                    <>
                      {domain && (
                        <input
                          type="range"
                          aria-label={tr(`${label(fv.feature)} (deslizador)`, `${label(fv.feature)} (slider)`)}
                          min={domain[0]}
                          max={domain[1]}
                          step={stepFor(domain)}
                          value={Math.min(domain[1], Math.max(domain[0], current ?? domain[0]))}
                          onChange={(e) => set(fv.feature, Number(e.target.value))}
                        />
                      )}
                      <input
                        id={`whatif-${fv.feature}`}
                        type="number"
                        inputMode="decimal"
                        step="any"
                        min={domain?.[0]}
                        max={domain?.[1]}
                        value={overridden ?? ""}
                        placeholder={fv.value === null ? tr("sin dato", "no data") : fmtNum(fv.value)}
                        onChange={(e) => set(fv.feature, e.target.value === "" ? null : Number(e.target.value))}
                      />
                    </>
                  )}
                </span>
              </li>
            );
          })}
        </ul>
      )}
      {edited && !pending && result.status === "ok" && (
        <ScenarioResult r={result.data} classifier={classifier} mixture={mixture} showAll={showAll} onShowAll={setShowAll} />
      )}
    </section>
  );
}

/** The headline of the answer, kept above the inputs so it is in view while they are edited. */
function PredictionSummary({ r, classifier, mixture }: { r: ScenarioResponse; classifier: boolean; mixture: boolean }) {
  const pc = r.prediction_change;
  const unit = unitLabel(r.modified.prediction.unit);
  return (
    <div data-testid="whatif-summary">
      <p>
        <span className="badge-what-if" data-testid="whatif-flag">
          synthetic_what_if: {String(r.synthetic_what_if ?? true)}
        </span>{" "}
        <span className="muted">{tr("entrada artificial", "artificial input")}</span>
      </p>
      {classifier ? (
        <p data-testid="whatif-prediction">
          {tr("Categoría: ", "Category: ")}
          <strong>{pc.original_label ?? tr("sin categoría", "no category")}</strong> → <strong>{pc.scenario_label ?? tr("sin categoría", "no category")}</strong>{" "}
          <span className="muted">({pc.label_changed ? tr("la categoría cambia", "the category changes") : tr("la categoría no cambia", "the category does not change")})</span>
          <br />
          {mixture ? (
            <>
              {whatIfTopRuleLabel()}
              <strong>{pc.original_top_rule_id ?? tr("ninguna", "none")}</strong> → <strong>{pc.scenario_top_rule_id ?? tr("ninguna", "none")}</strong>{" "}
              <span className="muted">({whatIfTopRuleSame((pc.original_top_rule_id ?? null) === (pc.scenario_top_rule_id ?? null))})</span>
            </>
          ) : (
            <>
              {tr("Regla ganadora: ", "Winning rule: ")}
              <strong>{pc.original_winning_rule_id ?? tr("ninguna", "none")}</strong> → <strong>{pc.scenario_winning_rule_id ?? tr("ninguna", "none")}</strong>{" "}
              <span className="muted">
                ({pc.original_winning_rule_id === pc.scenario_winning_rule_id ? tr("la regla ganadora no cambia", "the winning rule does not change") : tr("la regla ganadora cambia", "the winning rule changes")})
              </span>
            </>
          )}
        </p>
      ) : (
        <p data-testid="whatif-prediction">
          {tr("Predicción:", "Prediction:")}{" "}
          <strong>{pc.original_value === null ? tr("sin predicción", "no prediction") : `${fmtNum(pc.original_value)} ${unit}`}</strong> →{" "}
          <strong>{pc.scenario_value === null ? tr("sin predicción", "no prediction") : `${fmtNum(pc.scenario_value)} ${unit}`}</strong>
          {pc.value_delta != null && <span className="muted"> (Δ {signed(pc.value_delta)} {unit})</span>}
        </p>
      )}
      {r.modified.quality?.warnings && r.modified.quality.warnings.length > 0 && (
        <ul className="warnings" aria-label={tr("Avisos del escenario", "Scenario warnings")}>
          {r.modified.quality.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ScenarioResult({ r, classifier, mixture, showAll, onShowAll }: { r: ScenarioResponse; classifier: boolean; mixture: boolean; showAll: boolean; onShowAll: (v: boolean) => void }) {
  const label = useFeatureLabel();
  const names = useNames();
  const memberships = membershipChanges(r);
  const deltas = changedRuleDeltas(r);
  const limit = (n: number) => (showAll ? n : SHOWN_ROWS);
  return (
    <div className="whatif-result" data-testid="whatif-result">
      <h3>{tr("Entradas", "Inputs")}</h3>
      <table className="whatif-table" data-testid="whatif-inputs-table">
        <thead>
          <tr>
            <th scope="col">Variable</th>
            <th scope="col">{tr("Origen", "Origin")}</th>
            <th scope="col">{tr("Original → escenario", "Original → scenario")}</th>
          </tr>
        </thead>
        <tbody>
          {r.inputs.map((i) => (
            <tr key={i.feature} data-origin={i.origin}>
              <th scope="row">
                {label(i.feature)}
              </th>
              <td>{i.origin === "overridden" ? tr("modificada", "modified") : tr("observada", "observed")}</td>
              <td>
                {i.original_value === null ? tr("sin dato", "no data") : fmtNum(i.original_value)} → {i.scenario_value === null ? tr("sin dato", "no data") : fmtNum(i.scenario_value)}
                {i.unit ? ` ${unitLabel(i.unit)}` : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>{tr("Pertenencias que cambian", "Memberships that change")}</h3>
      {memberships.length === 0 ? (
        <p className="muted">{tr("No cambia ninguna pertenencia a un término.", "No term membership changes.")}</p>
      ) : (
        <table className="whatif-table" data-testid="whatif-memberships">
          <thead>
            <tr>
              <th scope="col">{tr("Regla · condición", "Rule · condition")}</th>
              <th scope="col">{tr("μ original → escenario", "μ original → scenario")}</th>
            </tr>
          </thead>
          <tbody>
            {memberships.slice(0, limit(memberships.length)).map((m) => (
              <tr key={`${m.ruleId}|${m.feature}|${m.term}`}>
                <th scope="row">
                  {m.ruleId} · {condText(m, label, names)}
                </th>
                <td>
                  <span data-raw={String(m.before)}>{fmt(m.before)}</span> → <span data-raw={String(m.after)}>{fmt(m.after)}</span> <span className="muted">({signed(m.delta)})</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h3>{tr("Activación de las reglas", "Rule activation")}</h3>
      {deltas.length === 0 ? (
        <p className="muted">{tr("No cambia la activación de ninguna regla.", "No rule's activation changes.")}</p>
      ) : (
        <table className="whatif-table" data-testid="whatif-deltas">
          <thead>
            <tr>
              <th scope="col">{tr("Regla", "Rule")}</th>
              <th scope="col">{tr("Activación: original → escenario", "Activation: original → scenario")}</th>
              {classifier && !mixture && <th scope="col">{tr("Asociación (Δ)", "Association (Δ)")}</th>}
            </tr>
          </thead>
          <tbody>
            {deltas.slice(0, limit(deltas.length)).map((d) => (
              <tr key={d.rule_id} data-rule={d.rule_id}>
                <th scope="row">{d.rule_id}</th>
                <td>
                  {d.firing_original === null ? "—" : fmt(d.firing_original)} → {d.firing_scenario === null ? "—" : fmt(d.firing_scenario)}{" "}
                  {d.firing_delta !== null && <span className="muted">({signed(d.firing_delta)})</span>}
                </td>
                {classifier && !mixture && (
                  <td>
                    {d.association_delta == null ? "—" : `${fmtFine(d.association_original ?? 0)} → ${fmtFine(d.association_scenario ?? 0)} (${signed(d.association_delta, 4)})`}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {(memberships.length > SHOWN_ROWS || deltas.length > SHOWN_ROWS) && (
        <p>
          <button type="button" className="link" onClick={() => onShowAll(!showAll)}>
            {showAll ? tr("Mostrar solo los mayores cambios", "Show only the largest changes") : tr("Mostrar todos los cambios", "Show all changes")}
          </button>
        </p>
      )}
    </div>
  );
}
