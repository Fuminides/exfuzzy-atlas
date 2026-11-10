import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type { DomainsResponse, EntityCollection, ModelCard, ModelRules, RuleMapResponse, RuleTrace, SeriesResponse } from "./api/types";
import { fake, installApi, type FakeSet } from "./test/fakeApi";
import * as fx from "./test/fixtures";
import { maps, resetMaps } from "./test/maplibreMock";

vi.mock("maplibre-gl", async () => (await import("./test/maplibreMock")).maplibreFactory());
// These tests count the requests of browsing; the probing of the default time has its own tests (App.round4.test.tsx).
vi.mock("./hooks/useDefaultTime", () => ({ useDefaultTime: () => false }));

/**
 * Two air tasks in one domain (AT-070: Madrid and Germany). Germany is the Madrid fixture renamed (task, model, stations)
 * with its own attribution, time zone and ~400 stations spread over a country-sized box.
 */
const MADRID = "madrid_no2_h6";
const GERMANY = "germany_no2_h6";
const GERMANY_MODEL = "synthetic-de-no2-h6-v0";
const N_GERMANY = 400;

const renamed = <T,>(value: T): T =>
  JSON.parse(JSON.stringify(value).replaceAll(MADRID, GERMANY).replaceAll("synthetic-no2-h6-v0", GERMANY_MODEL).replaceAll("SYN_", "DE_").replaceAll("Synthetic station", "German station")) as T;

const EEA = { text: "European Environment Agency (EEA) air quality e-reporting, test credit.", license: "CC BY 4.0", url: "https://example.org/eea" };

function germanySet(): FakeSet {
  const base = renamed(fx.entities) as EntityCollection;
  const template = base.features[0]!;
  const extra = Array.from({ length: N_GERMANY - base.features.length }, (_, i) => ({
    ...template,
    id: `DE_X${i}`,
    geometry: { type: "Point" as const, coordinates: [6 + (i % 20) * 0.45, 47.3 + Math.floor(i / 20) * 0.38] as never },
    properties: { ...template.properties, entity_id: `DE_X${i}`, name: `German station X${i} (not real)` },
  }));
  const placed = base.features.map((f, i) => ({ ...f, geometry: { type: "Point" as const, coordinates: [8 + i, 50 + i] as never } }));
  const entities = { ...base, features: [...placed, ...extra].map((f) => ({ ...f, properties: { ...f.properties, timezone: "Europe/Berlin" } })) };
  const card = { ...renamed(fx.card), attribution: [EEA] } as ModelCard;
  return {
    entities,
    card,
    rules: renamed(fx.rules) as ModelRules,
    series: renamed(fx.series) as SeriesResponse[],
    traces: renamed(fx.traces) as RuleTrace[],
    // the golden rule maps are keyed by the Madrid model id; the response is renamed like everything else
    ruleMapFor: (q) => {
      const original = new URLSearchParams(q);
      original.set("model_id", "synthetic-no2-h6-v0");
      const golden = fx.ruleMapFor(original);
      return golden ? (renamed(golden) as RuleMapResponse) : undefined;
    },
  };
}

const twoAirTasks = (): DomainsResponse => {
  const air = fx.domains.domains.find((d) => d.domain === "air")!;
  // two territories: each task names its own (the fixture task already carries `territory: "madrid"`)
  const task = { ...air.tasks[0]!, territory: "madrid", territory_title: "Madrid" };
  const german = { ...task, task_id: GERMANY, model_id: GERMANY_MODEL, territory: "alemania", territory_title: "Alemania" };
  return {
    ...fx.domains,
    domains: fx.domains.domains.map((d) =>
      d.domain === "air" ? { ...d, tasks: [task, german] } : d,
    ),
  };
};

beforeEach(() => {
  resetMaps();
  installApi({}, { domains: twoAirTasks(), extra: [germanySet()] });
});
afterEach(() => vi.unstubAllGlobals());

const lastMap = () => maps[maps.length - 1]!;
const drawn = () => (lastMap().sources["stations"] as { data: { features: { properties: { entity_id: string } }[] } }).data.features.map((f) => f.properties.entity_id);
const entityCalls = () => fake.calls.filter((c) => c.startsWith("/api/v1/entities?"));
const footer = () => within(screen.getByRole("contentinfo"));

describe("several tasks in one domain", () => {
  it("lists one button per task, grouped under the domain, and starts on the first", async () => {
    render(<App initialTab="explorar" />);
    const group = await screen.findByRole("group", { name: "Calidad del aire" });
    const buttons = within(group).getAllByRole("button");
    expect(buttons.map((b) => b.textContent?.trim())).toEqual(["Madrid", "Alemania"]);
    expect(buttons[0]).toHaveAttribute("aria-pressed", "true");
    expect(buttons[1]).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByTestId(`task-type-${MADRID}`)).toBeNull();
    // the single-task domains keep their one button each
    expect(screen.getByRole("button", { name: /Calidad del agua|England water quality/ })).toBeInTheDocument();
    await waitFor(() => expect(drawn()).toEqual(fx.entities.features.map((f) => f.properties.entity_id)));
  });

  it("asks for the entities of the selected task only, and never without task_id", async () => {
    render(<App initialTab="explorar" />);
    await screen.findByRole("table", { name: /Estaciones/ });
    expect(entityCalls()).toEqual([`/api/v1/entities?domain=air&task_id=${MADRID}`]);
    await userEvent.setup().click(screen.getByRole("button", { name: /Alemania/ }));
    await waitFor(() => expect(entityCalls()).toContain(`/api/v1/entities?domain=air&task_id=${GERMANY}`));
    expect(entityCalls().every((c) => c.includes("task_id="))).toBe(true);
  });

  it("switching reloads entities, model, map and provenance of the new task without mixing them", async () => {
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await waitFor(() => expect(footer().getByText("synthetic-no2-h6-v0")).toBeInTheDocument());
    expect(await footer().findByTestId("attribution")).toHaveTextContent("Synthetic fixtures"); // Madrid's own credit
    await user.click(await screen.findByRole("button", { name: "Synthetic station A (not real)" }));
    expect(await screen.findByText(/seleccionada:/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Alemania/ }));
    await waitFor(() => expect(footer().getByText(GERMANY_MODEL)).toBeInTheDocument());
    expect(footer().queryByText("synthetic-no2-h6-v0")).toBeNull();
    await waitFor(() => expect(drawn()).toHaveLength(N_GERMANY));
    expect(drawn().every((id) => id.startsWith("DE_"))).toBe(true); // no Madrid station on the Germany map
    expect(screen.getByRole("button", { name: "German station A (not real)" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Synthetic station A (not real)" })).toBeNull();
    expect(screen.queryByText(/seleccionada:/)).toBeNull(); // the selection did not carry over
    expect(screen.getByRole("button", { name: /Alemania/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /Madrid/ })).toHaveAttribute("aria-pressed", "false");
    expect(footer().getByTestId("attribution")).toHaveTextContent("European Environment Agency (EEA)");
    expect(footer().getByTestId("attribution")).not.toHaveTextContent("Synthetic fixtures");
    expect(fake.calls.some((c) => c.startsWith(`/api/v1/models/${GERMANY_MODEL}`))).toBe(true);
    await waitFor(() => expect(fake.calls.some((c) => c.includes("/rule-map") && c.includes(`model_id=${GERMANY_MODEL}`))).toBe(true));

    // and back: Madrid's own stations and (no) credits again
    await user.click(screen.getByRole("button", { name: /Madrid/ }));
    await waitFor(() => expect(drawn()).toHaveLength(fx.entities.features.length));
    expect(footer().getByTestId("attribution")).toHaveTextContent("Synthetic fixtures");
    expect(drawn().some((id) => id.startsWith("DE_"))).toBe(false);
  });

  it("frames the map on the selected task's own stations (Germany is not a Madrid-sized box)", async () => {
    render(<App initialTab="explorar" />);
    await waitFor(() => expect(lastMap().fitted?.length).toBeGreaterThan(0));
    const lon = (pts: [number, number][]) => [Math.min(...pts.map((p) => p[0])), Math.max(...pts.map((p) => p[0]))];
    expect(lon(lastMap().fitted!)[1]).toBeLessThan(0); // Madrid: west of Greenwich
    await userEvent.setup().click(screen.getByRole("button", { name: /Alemania/ }));
    await waitFor(() => expect(drawn()).toHaveLength(N_GERMANY));
    await waitFor(() => expect(lastMap().fitted?.length).toBe(N_GERMANY + 1));
    const [west, east] = lon(lastMap().fitted!);
    expect(west).toBeGreaterThan(5);
    expect(east).toBeLessThan(16);
  });

  it("sends task_id with the prediction requests of the selected task", async () => {
    render(<App initialTab="prediccion" />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Alemania/ }));
    await waitFor(() => expect(fake.calls.some((c) => c.startsWith("/api/v1/predictions") && c.includes(`task_id=${GERMANY}`))).toBe(true));
    expect(fake.calls.some((c) => c.startsWith("/api/v1/predictions") && c.includes(`task_id=${MADRID}`))).toBe(false);
  });
});

describe("single-task domains", () => {
  it("keep one button per territory and still send task_id with /entities", async () => {
    installApi();
    render(<App initialTab="explorar" />);
    await screen.findByRole("table", { name: /Estaciones/ });
    expect(within(screen.getByRole("group", { name: "Calidad del aire" })).getAllByRole("button")).toHaveLength(1);
    expect(screen.queryByTestId(`task-type-${MADRID}`)).toBeNull();
    expect(entityCalls()).toEqual([`/api/v1/entities?domain=air&task_id=${MADRID}`]);
  });
});
