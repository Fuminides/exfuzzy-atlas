import type { DomainInfo, TaskInfo } from "../api/types";
import { localized, tr } from "../i18n";
import { domainUi } from "./domainUi";

/**
 * Territories and horizons (contract v0.5, CONTRACTS.md §12). A territory groups the tasks of one domain that differ only
 * in `horizon_hours`; the web shows one territory with a discrete horizon selector. Until the backend fills
 * `TaskInfo.territory` every task is its own territory.
 */

export interface Territory {
  /** `TaskInfo.territory`, or the `task_id` of the only task when the backend has not set it. */
  id: string;
  domain: string;
  title: string;
  /** Tasks of the territory, shortest horizon first. */
  tasks: TaskInfo[];
  /** The task opened by default (the domain's first task that belongs here: the contract orders the default first). */
  defaultTask: TaskInfo;
}

export interface TerritoryGroup {
  domain: string;
  /** Domain title in the interface language ("Calidad del aire", "Air quality"). */
  title: string;
  territories: Territory[];
}

/** Names of the territories the project publishes; used only while the API gives no `territory_title` (`_en`, v0.6). */
const territoryNames = (): Record<string, string> => {
  const [germany, england, nyc] = [tr("Alemania", "Germany"), tr("Ríos de Inglaterra", "Rivers of England"), tr("Taxis de Nueva York", "New York taxis")];
  return {
    madrid: "Madrid",
    madrid_no2_h6: "Madrid",
    de: germany,
    germany,
    de_no2_h6: germany,
    germany_no2_h6: germany,
    uk: england,
    uk_water_do: england,
    nyc,
    nyc_pickups_h1: nyc,
  };
};

export const territoryTitle = (id: string, task: TaskInfo): string => {
  const names = territoryNames();
  return localized(task.territory_title, task.territory_title_en) ?? names[id] ?? names[task.task_id] ?? task.title ?? task.task_id;
};

/**
 * Groups every domain's tasks into territories. `domain.tasks` comes with the default task first (§11.3), so the first
 * task met for a territory is its default; the tasks themselves are sorted by horizon for the selector.
 */
export function groupTerritories(domains: readonly DomainInfo[]): TerritoryGroup[] {
  return domains
    .filter((d) => d.tasks.length > 0)
    .map((d) => {
      const byId = new Map<string, TaskInfo[]>();
      for (const t of d.tasks) byId.set(t.territory ?? t.task_id, [...(byId.get(t.territory ?? t.task_id) ?? []), t]);
      const territories = [...byId].map(([id, tasks]): Territory => ({
        id,
        domain: d.domain,
        title: territoryTitle(id, tasks[0]!),
        tasks: [...tasks].sort((a, b) => a.horizon_hours - b.horizon_hours),
        defaultTask: tasks[0]!,
      }));
      return { domain: d.domain, title: domainUi(d.domain).title, territories };
    });
}

/** The territory that holds `taskId`, with the task itself. */
export function findTask(groups: readonly TerritoryGroup[], taskId: string): { territory: Territory; task: TaskInfo } | null {
  for (const g of groups) {
    for (const territory of g.territories) {
      const task = territory.tasks.find((t) => t.task_id === taskId);
      if (task) return { territory, task };
    }
  }
  return null;
}

/** "+6 h" for the selector; horizon 0 is not a forecast and is never written as "+0 h". */
export const horizonButton = (hours: number): string => (hours === 0 ? tr("Misma muestra", "Same sample") : `+${hours} h`);
