import type { AsyncState } from "../hooks/useAsync";
import { tr } from "../i18n";
import type { RuleStoriesResponse, RuleStory } from "../api/types";
import { checkText, queryText } from "../lib/stories";
import { StateMessage } from "./StateMessage";
import { dec } from "../lib/format";

interface Props {
  /** The list is loaded only while the section is open. */
  open: boolean;
  onToggle: () => void;
  state: AsyncState<RuleStoriesResponse> & { reload?: () => void };
  /** "Reproducir": go to the exact request `queryIndex` of the story (rule, metric, time or window, tau). */
  onReproduce: (story: RuleStory, queryIndex: number) => void;
  /** The story whose query is on the map now, if any. */
  activeStory: string | null;
}

/** Stories are rendered as the API wrote them: the text is never paraphrased, shortened or completed. */
export function RuleStories({ open, onToggle, state, onReproduce, activeStory }: Props) {
  return (
    <section className="stories" aria-label={tr("Historias de reglas", "Rule stories")} data-testid="rule-stories">
      <h2>
        <button type="button" className="disclosure" aria-expanded={open} onClick={onToggle}>
          {tr("Historias", "Stories")}
        </button>
      </h2>
      {!open && <p className="muted">{tr("Frases sobre activaciones del modelo en la ventana elegida, con las consultas que las respaldan.", "Sentences about the model's activations in the chosen window, with the queries that back them.")}</p>}
      {open && state.status === "loading" && <StateMessage kind="loading">{tr("Cargando historias…", "Loading stories…")}</StateMessage>}
      {open && state.status === "error" && (
        <StateMessage kind="error" onRetry={state.reload}>
          {tr("No se pudieron cargar las historias: ", "Could not load the stories: ")}
          {state.error.message}
        </StateMessage>
      )}
      {open && state.status === "ok" && <Loaded data={state.data} onReproduce={onReproduce} activeStory={activeStory} />}
    </section>
  );
}

function Loaded({ data, onReproduce, activeStory }: { data: RuleStoriesResponse; onReproduce: Props["onReproduce"]; activeStory: string | null }) {
  return (
    <>
      <p className="muted">
        {tr(<>{data.stories.length} de {data.n_candidates} historias candidatas, ventana <code>[{data.time_from_utc}, {data.time_to_utc})</code> UTC, τ = {data.tau}. Cada historia describe activaciones del modelo y se puede comprobar con las consultas que lista.</>,
          <>{data.stories.length} of {data.n_candidates} candidate stories, window <code>[{data.time_from_utc}, {data.time_to_utc})</code> UTC, τ = {data.tau}. Each story describes the model&apos;s activations and can be checked with the queries it lists.</>)}
      </p>
      {data.stories.length === 0 && <p>{tr("No hay historias para esta ventana.", "There are no stories for this window.")}</p>}
      <ol className="story-list">
        {data.stories.map((s) => (
          <li key={s.story_id} className="story" data-story={s.story_id} data-kind={s.kind} aria-current={activeStory === s.story_id ? "true" : undefined}>
            <p className="story-text">{s.text}</p>
            <p>
              <button type="button" onClick={() => onReproduce(s, 0)} data-testid="story-reproduce">
                {tr("Reproducir", "Replay")}
              </button>{" "}
              <span className="muted">
                {s.queries.length === 1 ? tr("1 consulta", "1 query") : tr(`${s.queries.length} consultas (se reproduce la primera)`, `${s.queries.length} queries (the first one is replayed)`)} · {tr("puntuación", "score")} {dec(s.score, 3)}
              </span>
            </p>
            <details>
              <summary>{tr("Cifras y comprobaciones", "Figures and checks")}</summary>
              <dl className="story-numbers">
                {Object.entries(s.numbers).map(([k, v]) => (
                  <div key={k}>
                    <dt>
                      <code>{k}</code>
                    </dt>
                    <dd>{String(v)}</dd>
                  </div>
                ))}
              </dl>
              <h4>{tr("Consultas", "Queries")}</h4>
              <ol className="story-queries">
                {s.queries.map((q, i) => (
                  <li key={i}>
                    <button type="button" className="link" onClick={() => onReproduce(s, i)}>
                      {tr("Reproducir", "Replay")}
                    </button>
                    <code>{queryText(q)}</code>
                  </li>
                ))}
              </ol>
              <h4>{tr("Comprobaciones", "Checks")}</h4>
              <ul className="story-checks">
                {s.checks.map((c, i) => (
                  <li key={i}>{checkText(c)}</li>
                ))}
              </ul>
            </details>
          </li>
        ))}
      </ol>
      <details className="column-help">
        <summary>{tr("Cómo se ordenan", "How they are ordered")}</summary>
        <p>{data.score_definition}</p>
      </details>
    </>
  );
}
