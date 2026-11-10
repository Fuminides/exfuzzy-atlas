import type { DomainInfo, TaskInfo } from "../api/types";
import { PageHead } from "../components/Card";
import type { Provenance } from "../hooks/useProvenance";
import type { Mode } from "../lib/mode";
import { Workspace } from "../Workspace";
import { tr } from "../i18n";

export type ExploreMode = Exclude<Mode, "prediction">;

// Built at render time (not at import): the language can change while the page is open.
const modes = (): { id: ExploreMode; label: string; lead: React.ReactNode }[] => [
  {
    id: "rules",
    label: tr("Reglas en el mapa", "Rules on the map"),
    lead: tr(<>Estás viendo cómo las observaciones de cada estación activan una regla del modelo, hora a hora. La activación (0–1) mide lo bien que se cumple la condición de la regla.</>,
      <>
        You are looking at how each station's observations activate one of the model's rules, hour by hour. The activation (0–1) measures how well the rule&apos;s condition holds.
      </>,
    ),
  },
  {
    id: "data",
    label: tr("Datos observados", "Observed data"),
    lead: tr(<>Estás viendo los valores observados y las entradas del modelo en cada estación, tal como se publicaron.</>,
      <>You are looking at the observed values and the model&apos;s inputs at each station, as they were published.</>,
    ),
  },
];

interface Props {
  domain: DomainInfo;
  task: TaskInfo;
  mode: ExploreMode;
  onMode: (m: ExploreMode) => void;
  territoryTitle: string;
  onDate: (label: string) => void;
  onProvenance: (p: Partial<Provenance>) => void;
  /** The entity to open selected (a station card of Patrones). */
  focusEntity?: string | null;
}

/** Explorar: the expert tools (rule firing map, territories, rule duel, stories, data mode, what-if) with the same labels as the rest. */
export function ExploreTab({ domain, task, mode, onMode, territoryTitle, onDate, onProvenance, focusEntity = null }: Props) {
  const MODES = modes();
  const current = MODES.find((m) => m.id === mode)!;
  return (
    <div className="page page--wide" data-task={task.task_id}>
      <PageHead title={tr(`Explorar ${territoryTitle}`, `Explore ${territoryTitle}`)}>{current.lead}</PageHead>
      <div className="modes" role="group" aria-label={tr("Vista", "View")}>
        {MODES.map((m) => (
          <button key={m.id} type="button" aria-pressed={mode === m.id} onClick={() => onMode(m.id)}>
            {m.label}
          </button>
        ))}
      </div>
      <div className="workspace-frame" data-testid="explore-frame">
        <Workspace
          key={task.task_id}
          domain={domain}
          task={task}
          mode={mode}
          onMode={(m) => (m === "prediction" ? undefined : onMode(m))}
          onDate={onDate}
          onProvenance={onProvenance}
          initialEntityId={focusEntity}
        />
      </div>
    </div>
  );
}
