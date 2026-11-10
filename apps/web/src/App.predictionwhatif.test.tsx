import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ScenarioRequest } from "./api/types";
import { App } from "./App";
import { displayName } from "./lib/entityRows";
import { WHAT_IF_LABEL } from "./components/WhatIfPanel";
import { fake, installApi } from "./test/fakeApi";
import * as fx from "./test/fixtures";
import * as cls from "./test/fixturesClass";
import * as real from "./test/fixturesReal";
import { scenarioBody, scenarioFor, withUnmodelledZones } from "./test/fixturesV04";
import { emit, maps, resetMaps } from "./test/maplibreMock";

vi.mock("maplibre-gl", async () => (await import("./test/maplibreMock")).maplibreFactory());

afterEach(() => vi.unstubAllGlobals());

const SET = { entities: fx.entities, card: fx.card, rules: fx.rules, series: fx.series, traces: fx.traces, ruleMapFor: fx.ruleMapFor };
const posts = () => fake.posts.filter((p) => p.path === "/scenarios");
const traceCalls = () => fake.calls.filter((c) => c.includes("/rule-trace"));
const entry = () => screen.queryByRole("button", { name: "¿Y si…?" });
const stationButton = (name: string) => within(screen.getByRole("table", { name: /Estaciones/ })).getByRole("button", { name });

/** Prediction mode of the regressor at 07:00 UTC, the issue time the backend's golden scenario starts from. */
async function predictionAt0700() {
  render(<App initialTab="prediccion" />);
  const user = userEvent.setup();
  await screen.findByLabelText("Hora de emisión");
  fireEvent.change(screen.getByLabelText("Hora de emisión"), { target: { value: "1" } });
  await waitFor(() => expect(screen.getByTestId("issue-time")).toHaveTextContent("07:00 UTC"));
  await screen.findByRole("region", { name: /Leyenda: NO₂ previsto/ });
  return user;
}

describe("What-if from Prediction mode on a regressor", () => {
  beforeEach(() => {
    resetMaps();
    installApi({}, { scenarioFor: scenarioFor(SET as never) });
  });

  it("is offered once an entity and a time are selected, and asks nothing until it is opened", async () => {
    const user = await predictionAt0700();
    expect(entry()).toBeNull(); // no entity yet
    await user.click(stationButton("Synthetic station A (not real)"));
    const open = await screen.findByRole("button", { name: "¿Y si…?" });
    expect(screen.getByTestId("whatif-entry")).toHaveTextContent("respuesta del modelo a entradas hipotéticas");
    expect(open).toBeInTheDocument();
    expect(screen.queryByTestId("whatif-panel")).toBeNull();
    expect(traceCalls()).toHaveLength(0);
    expect(posts()).toHaveLength(0);
  });

  it("opens the same What-if panel prefilled with the entity, the time and the observed inputs", async () => {
    const user = await predictionAt0700();
    await user.click(stationButton("Synthetic station A (not real)"));
    await user.click(await screen.findByRole("button", { name: "¿Y si…?" }));
    const panel = await screen.findByTestId("whatif-panel");
    expect(panel).toHaveTextContent("What-if · Synthetic station A (not real)");
    expect(panel).toHaveTextContent("2025-01-15T07:00:00Z");
    // the row it starts from is the published one: its trace at that issue time
    const trace = traceCalls().map((c) => new URL(c, "http://x"));
    expect(trace).toHaveLength(1);
    expect(trace[0]!.pathname).toContain("/entities/SYN_A/rule-trace");
    expect(trace[0]!.searchParams.get("at")).toBe("2025-01-15T07:00:00Z");
    const wind = await within(panel).findByRole("spinbutton", { name: /Velocidad del viento/ });
    expect(panel.querySelector('li[data-feature="wind_speed_t"]')).toHaveTextContent("observado: 2,4");
    expect(within(panel).getByTestId("whatif-label")).toHaveTextContent(WHAT_IF_LABEL);
    const intro = screen.getByTestId("prediction-whatif");
    expect(intro).toHaveTextContent("Es la respuesta del modelo a las entradas modificadas.");
    expect(intro.textContent).not.toMatch(/causal|probabilidad|contribución|riesgo/i);
    // and it is the same panel: an edit POSTs the scenario of this entity and time
    fireEvent.change(wind, { target: { value: "5" } });
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect(posts()[0]!.body).toEqual(scenarioBody);
    expect((posts()[0]!.body as ScenarioRequest).entity_id).toBe("SYN_A");
    await within(panel).findByTestId("whatif-result");
  });

  it("is absent for an entity the model has no data for, and never asks for its row", async () => {
    installApi({}, { entities: withUnmodelledZones(fx.entities, 1), scenarioFor: scenarioFor(SET as never) });
    const user = await predictionAt0700();
    await user.click(stationButton("Synthetic station A (not real)"));
    expect(await screen.findByRole("button", { name: "¿Y si…?" })).toBeInTheDocument();
    emit("click", { features: [{ properties: { entity_id: "U1" } }] }, "stations-valid");
    expect(await screen.findByTestId("unmodelled-notice")).toBeInTheDocument();
    expect(entry()).toBeNull();
    expect(screen.queryByTestId("whatif-panel")).toBeNull();
    expect(traceCalls()).toHaveLength(0);
  });

  it("returning to the prediction keeps the entity and the time, and loads nothing again", async () => {
    const user = await predictionAt0700();
    await user.click(stationButton("Synthetic station A (not real)"));
    await user.click(await screen.findByRole("button", { name: "¿Y si…?" }));
    const panel = await screen.findByTestId("whatif-panel");
    fireEvent.change(await within(panel).findByRole("spinbutton", { name: /Velocidad del viento/ }), { target: { value: "5" } });
    await within(panel).findByTestId("whatif-result");
    const dataCalls = () => fake.calls.filter((c) => /\/predictions|\/series/.test(c)).length;
    const before = dataCalls();

    await user.click(screen.getByTestId("whatif-back"));
    expect(screen.queryByTestId("whatif-panel")).toBeNull();
    expect(await screen.findByRole("img", { name: /NO₂ observado y predicho \(µg\/m³\) en SYN_A/ })).toBeInTheDocument();
    expect(screen.getByText("Synthetic station A (not real)", { selector: "strong" })).toBeInTheDocument(); // "Estación seleccionada"
    expect(stationButton("Synthetic station A (not real)")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("issue-time")).toHaveTextContent("07:00 UTC");
    expect(dataCalls()).toBe(before);

    // the entry is back, and a new visit starts from the observed values (the edits belonged to the closed panel)
    await user.click(screen.getByRole("button", { name: "¿Y si…?" }));
    const again = await screen.findByTestId("whatif-panel");
    expect(await within(again).findByTestId("whatif-idle")).toBeInTheDocument();
    expect(await within(again).findByRole("spinbutton", { name: /Velocidad del viento/ })).toHaveValue(null);
  });

  it("leaving the Predicción tab closes it; coming back shows the prediction view", async () => {
    const user = await predictionAt0700();
    await user.click(stationButton("Synthetic station A (not real)"));
    await user.click(await screen.findByRole("button", { name: "¿Y si…?" }));
    await screen.findByTestId("whatif-panel");
    await user.click(screen.getByRole("tab", { name: "Explorar" }));
    expect(screen.queryByTestId("prediction-whatif")).toBeNull();
    await user.click(screen.getByRole("tab", { name: "Predicción" }));
    expect(await screen.findByRole("heading", { name: /Predicción del modelo/ })).toBeInTheDocument();
    expect(screen.queryByTestId("prediction-whatif")).toBeNull();
  });

  it("says so when the row cannot be loaded, instead of an empty panel", async () => {
    const user = await predictionAt0700();
    installApi({ "/entities/SYN_A/rule-trace": () => Promise.resolve(new Response(JSON.stringify({ detail: "no trace" }), { status: 404 })) }, { scenarioFor: scenarioFor(SET as never) });
    await user.click(stationButton("Synthetic station A (not real)"));
    await user.click(await screen.findByRole("button", { name: "¿Y si…?" }));
    expect(await screen.findByText(/No se pudo cargar el registro de Synthetic station A/)).toBeInTheDocument();
    expect(screen.queryByTestId("whatif-panel")).toBeNull();
    expect(screen.getByTestId("whatif-back")).toBeInTheDocument();
  });
});

describe("What-if from Prediction mode on a classifier", () => {
  beforeEach(() => {
    resetMaps();
    installApi({}, cls.classifierData());
  });

  it("names the output as the predicted category (never a health risk)", async () => {
    render(<App initialTab="prediccion" />);
    const user = userEvent.setup();
    await screen.findByLabelText("Hora de emisión");
    const iso = "2024-01-06T10:00:00Z";
    fireEvent.change(screen.getByLabelText("Hora de emisión"), { target: { value: String((Date.parse(iso) - Date.parse(cls.FIRST_ISSUE)) / 3_600_000) } });
    await waitFor(() => expect(screen.getByTestId("issue-time")).toHaveTextContent("10:00 UTC"));
    await waitFor(() => expect(maps[maps.length - 1]!.sources["stations"]).toBeDefined());
    emit("click", { features: [{ properties: { entity_id: "E1" } }] }, "stations-valid");
    await user.click(await screen.findByRole("button", { name: "¿Y si…?" }));
    const intro = await screen.findByTestId("prediction-whatif");
    expect(intro).toHaveTextContent("Salida que se recalcula: categoría prevista de y");
    expect(intro.textContent).not.toMatch(/riesgo sanitario|probabilidad de/i);
    expect(await within(intro).findByTestId("whatif-label")).toHaveTextContent(WHAT_IF_LABEL);
    expect(traceCalls().map((c) => new URL(c, "http://x").searchParams.get("at"))).toEqual([iso]);
  });
});

describe("What-if from Prediction mode on irregular samples (Water)", () => {
  beforeEach(() => {
    resetMaps();
    installApi({}, real.realData());
  });

  const openWater = async () => {
    render(<App initialTab="prediccion" />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Ríos de Inglaterra/ }));
    await waitFor(() => expect(maps[maps.length - 1]!.sources["stations"]).toBeDefined());
    return user;
  };

  it("starts from the point's own latest sample in the window, and is not offered for a point without one", async () => {
    await openWater();
    emit("click", { features: [{ properties: { entity_id: real.WATER_POINT } }] }, "stations-valid");
    const open = await screen.findByRole("button", { name: "¿Y si…?" });
    const sample = real.water.traces[0]!.issued_at_utc;
    await userEvent.click(open);
    const panel = await screen.findByTestId("whatif-panel");
    expect(panel).toHaveTextContent(sample);
    expect(traceCalls().map((c) => new URL(c, "http://x").searchParams.get("at"))).toEqual([sample]);
    await userEvent.click(screen.getByTestId("whatif-back"));
    emit("click", { features: [{ properties: { entity_id: real.WATER_EMPTY_POINT } }] }, "stations-missing");
    const empty = real.water.entities.features.find((f) => f.properties.entity_id === real.WATER_EMPTY_POINT)!.properties.name!;
    await waitFor(() => expect(screen.getByText(displayName(empty), { selector: ".map-selected strong" })).toBeInTheDocument());
    expect(entry()).toBeNull();
    expect(screen.queryByTestId("whatif-panel")).toBeNull();
  });
});
