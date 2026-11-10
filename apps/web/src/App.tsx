import { useCallback, useState } from "react";
import { LangContext, localized, rememberLang, setLang, tr, type Lang } from "./i18n";
import { LanguageSwitch } from "./components/LanguageSwitch";
import { api } from "./api/client";
import { isStaticData } from "./lib/dataMode";
import { StateMessage } from "./components/StateMessage";
import { SyntheticBanner } from "./components/SyntheticBanner";
import { SiteCredits } from "./components/SiteCredits";
import { useAsync } from "./hooks/useAsync";
import { domainUi } from "./lib/domainUi";
import { findTask, groupTerritories, horizonButton } from "./lib/tasks";
import { ExploreTab, type ExploreMode } from "./tabs/ExploreTab";
import { PatternsTab } from "./tabs/PatternsTab";
import { PredictionTab } from "./tabs/PredictionTab";
import { ReportTab } from "./tabs/ReportTab";
import { SummaryTab } from "./tabs/SummaryTab";
import type { Provenance } from "./Workspace";

export type Tab = "resumen" | "patrones" | "prediccion" | "rendimiento" | "explorar";

// Labels are built at render time (not at import): the language can change while the page is open.
const TAB_IDS: readonly Tab[] = ["patrones", "rendimiento", "resumen", "prediccion", "explorar"];
const tabLabel = (t: Tab): string =>
  ({
    patrones: tr("Patrones", "Patterns"),
    resumen: tr("Resumen de datos", "Data summary"),
    prediccion: tr("Predicción", "Prediction"),
    rendimiento: tr("Informe de rendimiento", "Performance report"),
    explorar: tr("Explorar", "Explore"),
  })[t];
const domainStatus = (status: string): string => ({ planned: tr("planificado", "planned"), active: tr("activo", "active") })[status] ?? status;

interface Props {
  /** Tab shown first (Patrones by default: the rules are the focus). */
  initialTab?: Tab;
  initialExplore?: ExploreMode;
  /** Interface language to start in (main.tsx detects it; tests default to Spanish). */
  initialLang?: Lang;
  /** Reopens the landing page (Root): the header then shows «Sobre esta demo». */
  onAbout?: () => void;
}

export function App({ initialTab = "patrones", initialExplore = "rules", initialLang = "es", onAbout }: Props) {
  const [lang, setLangState] = useState<Lang>(initialLang);
  // Set before anything below renders: the pure text helpers read the module-level language.
  setLang(lang);
  const chooseLang = (l: Lang) => {
    rememberLang(l);
    setLangState(l);
  };
  const domains = useAsync((s) => api.domains(s), []);
  // A static site has no server to ask: the footer does not show a health label.
  const staticSite = isStaticData();
  const health = useAsync((s) => api.health(s), [], !staticSite);
  // The unit the user selects is a territory; its horizon picks one of its tasks. null = the first territory's default task.
  const [taskId, setTaskId] = useState<string | null>(null);
  // A domain with no tasks yet is listed as a placeholder; picking it replaces the tabs' content with an honest notice.
  const [emptyId, setEmptyId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>(initialTab);
  // Set by "la decidió R04" in Predicción: Patrones then opens with that rule selected. Any other way to a tab clears it.
  const [focusRule, setFocusRule] = useState<string | null>(null);
  // Set by a station card of Patrones: Predicción or Explorar then open with that entity selected. Cleared like focusRule.
  const [focusEntity, setFocusEntity] = useState<string | null>(null);
  const showTab = (t: Tab) => {
    setFocusRule(null);
    setFocusEntity(null);
    setTab(t);
  };
  const openRule = (ruleId: string) => {
    setFocusRule(ruleId);
    setFocusEntity(null);
    setTab("patrones");
  };
  const openEntity = (t: "prediccion" | "explorar") => (entityId: string) => {
    setFocusRule(null);
    setFocusEntity(entityId);
    setTab(t);
    document.querySelector(".topbar")?.scrollIntoView?.({ block: "start" });
  };
  const [exploreMode, setExploreMode] = useState<ExploreMode>(initialExplore);
  const [date, setDate] = useState<string | null>(null);
  const [prov, setProv] = useState<Provenance>({
    synthetic: false,
    dataVersion: null,
    modelId: "",
    geometrySource: null,
    exfuzzyVersion: null,
    schemeName: null,
    schemeUrl: null,
    schemeNames: null,
    attribution: [],
  });
  const onProvenance = useCallback(
    (p: Partial<Provenance>) =>
      setProv((old) => {
        const next = { ...old, ...p };
        return (Object.keys(next) as (keyof Provenance)[]).every((k) => next[k] === old[k]) ? old : next;
      }),
    [],
  );

  const list = domains.status === "ok" ? domains.data.domains : [];
  const groups = groupTerritories(list);
  const first = groups[0]?.territories[0]?.defaultTask.task_id ?? null;
  const found = findTask(groups, taskId ?? first ?? "") ?? (first ? findTask(groups, first) : null);
  const emptyDomain = list.find((d) => d.domain === emptyId && d.tasks.length === 0);
  const domain = emptyDomain ? undefined : found ? list.find((d) => d.domain === found.territory.domain) : undefined;
  const territory = found?.territory;
  const task = found?.task;
  const selectTerritory = (taskOfTerritory: string) => {
    // Each task has its own model, scheme, timezone, entities and attribution: nothing carries over.
    if (taskOfTerritory !== task?.task_id) setDate(null);
    setTaskId(taskOfTerritory);
    setFocusRule(null);
    setFocusEntity(null);
    setEmptyId(null);
  };
  const synthetic = prov.synthetic || (domains.status === "ok" && domains.data.synthetic === true);

  const onTabKey = (e: React.KeyboardEvent) => {
    const i = TAB_IDS.indexOf(tab);
    const next = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : e.key === "Home" ? 0 : e.key === "End" ? TAB_IDS.length - 1 : null;
    if (next === null) return;
    e.preventDefault();
    const target = TAB_IDS[(next + TAB_IDS.length) % TAB_IDS.length]!;
    showTab(target);
    document.getElementById(`tab-${target}`)?.focus();
  };

  return (
    <LangContext.Provider value={{ lang, setLang: chooseLang }}>
    <div className="app" data-domain={domain?.domain}>
      <SyntheticBanner show={synthetic} />
      <header className="topbar">
        <div className="topbar-row">
          <p className="brand">ExFuzzy Atlas</p>
          <nav aria-label={tr("Territorio", "Territory")} className="territories">
            {groups.map((g) => (
              <div key={g.domain} className="territory-group" role="group" aria-label={g.title}>
                <span className="territory-group-label">{g.title}</span>
                <div className="segmented">
                  {g.territories.map((t) => (
                    <button
                      key={t.id}
                      type="button"
                      aria-pressed={!emptyDomain && t.id === territory?.id && g.domain === territory.domain}
                      onClick={() => selectTerritory(t.defaultTask.task_id)}
                      data-testid={`territory-${t.id}`}
                    >
                      {t.title}
                    </button>
                  ))}
                </div>
              </div>
            ))}
            {list
              .filter((d) => d.tasks.length === 0)
              .map((d) => (
                <div key={d.domain} className="territory-group" role="group" aria-label={d.title}>
                  <span className="territory-group-label">{domainUi(d.domain).title}</span>
                  <div className="segmented">
                    <button type="button" aria-pressed={emptyId === d.domain} onClick={() => setEmptyId(d.domain)}>
                      {d.title} <span className="badge">{domainStatus(d.status)}</span>
                    </button>
                  </div>
                </div>
              ))}
          </nav>
          <div className="topbar-end">
            {onAbout && (
              <button type="button" className="link about-link" onClick={onAbout}>
                {tr("Sobre esta demo", "About this demo")}
              </button>
            )}
            <LanguageSwitch />
          </div>
        </div>
        <div className="topbar-row topbar-row--tabs">
          <div role="tablist" aria-label={tr("Secciones", "Sections")} className="tabbar" onKeyDown={onTabKey}>
            {TAB_IDS.map((t) => (
              <button
                key={t}
                id={`tab-${t}`}
                type="button"
                role="tab"
                aria-selected={tab === t}
                aria-controls="tabpanel"
                tabIndex={tab === t ? 0 : -1}
                onClick={() => showTab(t)}
              >
                {tabLabel(t)}
              </button>
            ))}
          </div>
          {territory && task && tab !== "resumen" && (
            <div className="horizon" role="group" aria-label={tr("Horizonte de predicción", "Forecast horizon")} data-testid="horizon">
              <span className="horizon-label">{tr("Horizonte", "Horizon")}</span>
              {territory.tasks.length > 1 ? (
                <div className="segmented">
                  {territory.tasks.map((t) => (
                    <button key={t.task_id} type="button" aria-pressed={t.task_id === task.task_id} onClick={() => selectTerritory(t.task_id)}>
                      {horizonButton(t.horizon_hours)}
                    </button>
                  ))}
                </div>
              ) : (
                <p className="horizon-fixed" data-testid="horizon-fixed">
                  <strong>{task.horizon_hours === 0 ? tr("Misma muestra", "Same sample") : `+${task.horizon_hours} h`}</strong>
                  <span className="muted small">
                    {task.horizon_hours === 0
                      ? tr(" · inferencia", " · inference")
                      : tr(" · único horizonte disponible por ahora", " · the only horizon available for now")}
                  </span>
                </p>
              )}
            </div>
          )}
          {date && (tab === "prediccion" || tab === "explorar") && (
            <p className="topbar-date" aria-label={tr("Fecha", "Date")}>
              {date}
            </p>
          )}
        </div>
      </header>

      <main id="tabpanel" role="tabpanel" aria-labelledby={`tab-${tab}`}>
        {domains.status === "loading" && <StateMessage kind="loading">{tr("Cargando territorios…", "Loading territories…")}</StateMessage>}
        {domains.status === "error" && (
          <StateMessage kind="error" onRetry={domains.reload}>
            {staticSite ? (
              <>{domains.error.message}.</>
            ) : (
              <>
                {tr("No se pudo contactar con la API: ", "Could not reach the API: ")}
                {domains.error.message}.{" "}
                {tr(<>En desarrollo, arranca la API mock con <code>make api</code> desde la raíz del repositorio.</>, <>In development, start the mock API with <code>make api</code> from the repository root.</>)}
              </>
            )}
          </StateMessage>
        )}
        {domains.status === "ok" && !domain && !emptyDomain && !found && <StateMessage kind="empty">{staticSite ? tr("No hay datos de ningún territorio.", "No data for any territory.") : tr("La API no devuelve ningún territorio.", "The API returned no territories.")}</StateMessage>}
        {emptyDomain && !domain && (
          <div className="placeholder" role="status">
            <h2>{emptyDomain.title}</h2>
            <p>
              {tr("Dominio ", "Domain ")}
              <strong>{domainStatus(emptyDomain.status)}</strong>
              {tr(
                ": todavía no hay tareas, modelo ni datos, así que aquí no se muestra ningún valor.",
                ": no tasks, model or data yet, so no value is shown here.",
              )}
            </p>
          </div>
        )}
        {domain && task && territory && (
          <>
            {tab === "resumen" && <SummaryTab key={task.task_id} domain={domain} task={task} territoryTitle={territory.title} onProvenance={onProvenance} />}
            {tab === "patrones" && <PatternsTab key={task.task_id} domain={domain} task={task} territoryTitle={territory.title} onProvenance={onProvenance} onOpenSummary={() => showTab("resumen")} focusRule={focusRule} onOpenPrediction={openEntity("prediccion")} onOpenExplore={openEntity("explorar")} />}
            {tab === "prediccion" && (
              <PredictionTab
                key={task.task_id}
                domain={domain}
                task={task}
                territoryTitle={territory.title}
                horizons={territory.tasks.map((t) => t.horizon_hours)}
                onDate={setDate}
                onProvenance={onProvenance}
                onOpenRule={openRule}
                onOpenReport={() => showTab("rendimiento")}
                focusEntity={focusEntity}
              />
            )}
            {tab === "rendimiento" && <ReportTab key={task.task_id} domain={domain} task={task} territoryTitle={territory.title} />}
            {tab === "explorar" && (
              <ExploreTab key={task.task_id} domain={domain} task={task} mode={exploreMode} onMode={setExploreMode} territoryTitle={territory.title} onDate={setDate} onProvenance={onProvenance} focusEntity={focusEntity} />
            )}
          </>
        )}
        <div className="app-credits">
          <SiteCredits />
        </div>
      </main>

      <footer className="footer">
        {!staticSite && <span>API: {health.status === "ok" ? `${health.data.status} (${health.data.mode})` : health.status === "error" ? tr("no disponible", "unavailable") : "…"}</span>}
        <span>{synthetic ? tr("Fuente: datos sintéticos", "Source: synthetic data") : staticSite ? tr("Fuente: datos publicados", "Source: published data") : tr("Fuente: API", "Source: API")}</span>
        <details className="footer-provenance">
          <summary>{tr("Versiones y procedencia", "Versions and provenance")}</summary>
          <p>
            data_version: <code>{prov.dataVersion ?? "—"}</code> · model_id: <code>{prov.modelId || "—"}</code> · {tr("geometría", "geometry")}: <code>{prov.geometrySource ?? "—"}</code> · ex_fuzzy:{" "}
            <code>{prov.exfuzzyVersion ?? "—"}</code>
          </p>
        </details>
        {prov.schemeUrl && (
          <span data-testid="scheme-source">
            {tr("Esquema de categorías:", "Category scheme:")}{" "}
            <a href={prov.schemeUrl} target="_blank" rel="noopener noreferrer">
              {prov.schemeName ?? prov.schemeUrl}
            </a>
            {prov.schemeNames && <> · {prov.schemeNames}</>}
          </span>
        )}
        {prov.attribution.length > 0 && (
          <details className="footer-attribution" data-testid="attribution">
            <summary>
              {tr("Atribución", "Attribution")} ({prov.attribution.length}): {[...new Set(prov.attribution.map((a) => a.license ?? tr("licencia no declarada", "licence not stated")))].join(" · ")}
            </summary>
            <ul>
              {prov.attribution.map((a) => (
                <li key={`${a.url}${a.text}`}>
                  {localized(a.text, a.text_en)}
                  {a.url && (
                    <>
                      {" "}
                      <a href={a.url} target="_blank" rel="noopener noreferrer">
                        {tr("fuente", "source")}
                      </a>
                    </>
                  )}{" "}
                  <span className="muted">· {tr("licencia", "licence")}: {a.license ?? tr("no declarada en la fuente", "not stated by the source")}</span>
                </li>
              ))}
            </ul>
          </details>
        )}
      </footer>
    </div>
    </LangContext.Provider>
  );
}
