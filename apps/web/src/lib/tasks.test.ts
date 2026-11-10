import { describe, expect, it } from "vitest";
import type { DomainInfo, TaskInfo } from "../api/types";
import { findTask, groupTerritories, horizonButton, territoryTitle } from "./tasks";

const task = (task_id: string, over: Partial<TaskInfo> = {}): TaskInfo => ({
  task_id,
  task_type: "classification",
  target: "no2",
  unit: "ug/m3",
  horizon_hours: 6,
  status: "available",
  model_id: `m-${task_id}`,
  ...over,
});
const domain = (id: DomainInfo["domain"], tasks: TaskInfo[]): DomainInfo => ({ domain: id, title: `English ${id}`, status: "available", tasks });

describe("groupTerritories", () => {
  it("falls back to one territory per task while the backend fills no territory", () => {
    const g = groupTerritories([domain("air", [task("madrid_no2_h6"), task("de_no2_h6")]), domain("water", [task("uk_water_do", { horizon_hours: 0 })]), domain("mobility", [task("nyc_pickups_h1", { horizon_hours: 1 })])]);
    expect(g.map((x) => x.title)).toEqual(["Calidad del aire", "Calidad del agua", "Movilidad urbana"]);
    expect(g.flatMap((x) => x.territories.map((t) => t.title))).toEqual(["Madrid", "Alemania", "Ríos de Inglaterra", "Taxis de Nueva York"]);
    expect(g.flatMap((x) => x.territories.map((t) => t.tasks.length))).toEqual([1, 1, 1, 1]);
  });

  it("groups the tasks that share a territory and sorts them by horizon, keeping the domain's default task as the default", () => {
    const tasks = [6, 1, 24, 3, 12].map((h) => task(`madrid_no2_h${h}`, { horizon_hours: h, territory: "madrid", territory_title: "Madrid" }));
    const [air] = groupTerritories([domain("air", [...tasks, task("de_no2_h6")])]);
    expect(air!.territories.map((t) => t.id)).toEqual(["madrid", "de_no2_h6"]);
    const madrid = air!.territories[0]!;
    expect(madrid.tasks.map((t) => t.horizon_hours)).toEqual([1, 3, 6, 12, 24]);
    expect(madrid.defaultTask.task_id).toBe("madrid_no2_h6"); // first in the API order (§11.3)
  });

  it("skips a domain with no tasks and uses the API's own title for an unknown territory", () => {
    const g = groupTerritories([domain("water", []), domain("air", [task("paris_no2_h6", { territory: "paris", territory_title: "París" })])]);
    expect(g).toHaveLength(1);
    expect(g[0]!.territories[0]!.title).toBe("París");
    expect(territoryTitle("x", task("x"))).toBe("x");
  });

  it("shows the territory title the API gives, in preference to the web's own Spanish names", () => {
    const [g] = groupTerritories([domain("mobility", [task("nyc_pickups_h1", { territory: "nyc", territory_title: "Nueva York" })])]);
    expect(g!.territories[0]!.title).toBe("Nueva York");
  });

  it("finds a task with its territory", () => {
    const groups = groupTerritories([domain("air", [task("madrid_no2_h6", { territory: "madrid" }), task("madrid_no2_h3", { territory: "madrid", horizon_hours: 3 })])]);
    expect(findTask(groups, "madrid_no2_h3")?.territory.id).toBe("madrid");
    expect(findTask(groups, "nope")).toBeNull();
  });
});

describe("horizonButton", () => {
  it("writes +N h, and 'Misma muestra' for horizon 0 (never +0 h)", () => {
    expect([1, 3, 6, 12, 24, 0].map(horizonButton)).toEqual(["+1 h", "+3 h", "+6 h", "+12 h", "+24 h", "Misma muestra"]);
  });
});
