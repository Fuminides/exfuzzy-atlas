import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { BLUES, MAGMA, VIRIDIS } from "./lib/colorScale";
import { labelerFor } from "./lib/labels";
import { fake, installApi } from "./test/fakeApi";
import * as fx from "./test/fixtures";
import * as real from "./test/fixturesReal";
import { withUnmodelledZones } from "./test/fixturesV04";
import { emit, maps, resetMaps } from "./test/maplibreMock";

vi.mock("maplibre-gl", async () => (await import("./test/maplibreMock")).maplibreFactory());
// These tests are about what Explorar shows at the fixture's first issue time; the opening-moment probe has its own tests
// (App.opening.test.tsx), so here every probe answers "no information" and the page stays at the first issue time.
vi.mock("./hooks/defaultTimeScores", async (orig) => ({ ...(await orig<typeof import("./hooks/defaultTimeScores")>()), firingScore: () => async () => null }));

afterEach(() => vi.unstubAllGlobals());

const labelOf = labelerFor(fx.rules.variables);
type Feature = { properties: { entity_id: string; value: number | null; missing_reason: string | null } };
const features = (): Feature[] => (maps[maps.length - 1]!.sources["stations"] as { data: { features: Feature[] } }).data.features;
const calls = (endpoint: string) => fake.calls.filter((c) => c.startsWith(`/api/v1${endpoint}?`)).map((c) => new URL(c, "http://x").searchParams);
const openData = async () => {
  render(<App initialTab="explorar" />);
  await userEvent.setup().click(await screen.findByRole("button", { name: "Datos observados" }));
};
const rowOf = (entity: string) => document.querySelector(`table.stations tr[data-entity="${entity}"]`)!;

describe("Data mode (observations as published)", () => {
  beforeEach(() => {
    resetMaps();
    installApi();
  });

  it("asks /observations once for the selected issue time, and nothing from the model or the rules", async () => {
    await openData();
    await screen.findByRole("region", { name: /Leyenda: NO₂ observado/ });
    const q = calls("/observations");
    expect(q).toHaveLength(1);
    expect([q[0]!.get("task_id"), q[0]!.get("time"), q[0]!.get("from")]).toEqual([fx.card.manifest.task_id, "2025-01-15T06:00:00Z", null]);
    expect(calls("/predictions")).toHaveLength(0);
    expect(calls("/rule-map")).toHaveLength(0);
    expect(calls("/series")).toHaveLength(0);
  });

  it("draws the observed target at valid_at with its own title, legend and palette, apart from Prediction and Rules", async () => {
    await openData();
    expect(await screen.findByRole("heading", { name: "Datos observados: NO₂ medido en la hora de validez (emisión + 6 h) (µg/m³)" })).toBeInTheDocument();
    const legend = await screen.findByRole("region", { name: /Leyenda: NO₂ observado \(µg\/m³\)/ });
    expect(legend).toHaveTextContent("Valor medido en la hora de validez (emisión + 6 h): 15/01/2025, 12:00 UTC");
    expect(legend).toHaveTextContent("tal como se publicó");
    expect(screen.queryByRole("region", { name: /Leyenda: activación/ })).toBeNull();
    expect(screen.queryByRole("region", { name: /previsto/ })).toBeNull();
    // the colours are the observation palette: neither the activation (viridis) nor the prediction (magma) one
    await waitFor(() => expect(features().some((f) => f.properties.value !== null)).toBe(true));
    const paint = maps[maps.length - 1]!.layers["stations-valid"]!.paint!["circle-color"] as unknown[];
    expect(paint[4]).toBe(BLUES[0]![1]);
    expect(paint).not.toContain(VIRIDIS[0]![1]);
    expect(paint).not.toContain(MAGMA[0]![1]);
    // the values are the observations at 06:00 + 6 h, not the predictions
    const at = (id: string) => fx.series.find((s) => s.entity_id === id)!.points.find((p) => p.issued_at_utc === "2025-01-15T06:00:00Z")!;
    for (const f of features()) {
      expect(f.properties.value).toBe(at(f.properties.entity_id).observed);
      expect(f.properties.value).not.toBe(at(f.properties.entity_id).prediction);
    }
  });

  it("keeps a missing observation missing (a reason, never 0), counts it out and does not interpolate", async () => {
    const series = structuredClone(fx.series);
    series.find((s) => s.entity_id === "SYN_C")!.points[0]!.observed = null;
    installApi({}, { series });
    await openData();
    const legend = await screen.findByRole("region", { name: /Leyenda: NO₂ observado/ });
    await waitFor(() => expect(features().find((f) => f.properties.entity_id === "SYN_C")?.properties.value).toBeNull());
    expect(features().find((f) => f.properties.entity_id === "SYN_A")!.properties.value).toBe(32.7);
    expect(features().filter((f) => f.properties.value === 0)).toHaveLength(0);
    expect(legend).toHaveTextContent("Estaciones con observación: 3 de 4");
    expect(legend).toHaveTextContent("sin observación (el motivo se indica en la tabla; no es 0)");
    expect(rowOf("SYN_C")).toHaveTextContent("sin dato");
    expect(rowOf("SYN_C")).toHaveTextContent("sin observación");
    expect(rowOf("SYN_C")).not.toHaveTextContent(/\b0 µg/);
    // the map has the hollow-ring layer for it and no surface layer at all
    expect(Object.keys(maps[maps.length - 1]!.layers).some((id) => /heat|surface|interp/i.test(id))).toBe(false);
  });

  it("shows, for the selected station, the target at valid_at and the inputs with unit, source and observation instant", async () => {
    await openData();
    await waitFor(() => expect(features().some((f) => f.properties.value !== null)).toBe(true));
    emit("click", { features: [{ properties: { entity_id: "SYN_A" } }] }, "stations-valid");
    const panel = await screen.findByRole("region", { name: "Observaciones de la entidad" });
    expect(panel).toHaveTextContent("Observaciones de Synthetic station A (not real)");
    expect(panel).toHaveTextContent("se observa en la hora de validez");
    expect(panel).toHaveTextContent("15/01/2025, 12:00 UTC"); // 06:00 + 6 h
    const trace = fx.trace("SYN_A", "06:00");
    const target = within(panel).getByText("NO₂", { selector: "th" }).closest("tr")!;
    expect(target).toHaveTextContent("objetivo");
    expect(target).toHaveTextContent("32,7 µg/m³");
    for (const v of trace.feature_values) {
      const row = within(panel).getByText(labelOf(v.feature), { selector: "th" }).closest("tr")!;
      expect(row).toHaveTextContent("entrada");
      expect(row).toHaveTextContent(String(Number(v.value!.toPrecision(4))));
      expect(row).toHaveTextContent(v.source_id!);
    }
    expect(panel).toHaveTextContent("Son valores publicados.");
  });

  it("an input that is missing says so with its reason and is never shown as 0", async () => {
    const traces = structuredClone(fx.traces);
    const t = traces.find((x) => x.entity_id === "SYN_B" && x.issued_at_utc === "2025-01-15T06:00:00Z")!;
    t.feature_values[1] = { ...t.feature_values[1]!, value: null, missing_reason: "missing_input" };
    installApi({}, { traces });
    await openData();
    await waitFor(() => expect(features().some((f) => f.properties.value !== null)).toBe(true));
    emit("click", { features: [{ properties: { entity_id: "SYN_B" } }] }, "stations-valid");
    const panel = await screen.findByRole("region", { name: "Observaciones de la entidad" });
    const row = within(panel).getByText(labelOf(t.feature_values[1]!.feature), { selector: "th" }).closest("tr")!;
    expect(row).toHaveTextContent("sin dato");
    expect(row).toHaveTextContent("falta una entrada");
    expect(within(row).getByTestId("data-missing")).toBeInTheDocument();
  });

  it("moving the timeline asks for the new issue time and never draws the previous answer", async () => {
    await openData();
    await waitFor(() => expect(features().some((f) => f.properties.value !== null)).toBe(true));
    fireEvent.change(screen.getByLabelText("Hora de emisión"), { target: { value: "2" } });
    await waitFor(() => expect(calls("/observations").at(-1)!.get("time")).toBe("2025-01-15T08:00:00Z"));
    await waitFor(() => expect(features().find((f) => f.properties.entity_id === "SYN_A")?.properties.value).toBe(52));
  });

  it("a station without a model says 'sin modelo' in the panel and offers no observations", async () => {
    installApi({}, { entities: withUnmodelledZones(fx.entities, 1) });
    await openData();
    await screen.findByRole("region", { name: /Leyenda: NO₂ observado/ });
    await userEvent.setup().click(within(screen.getByRole("table", { name: /Estaciones/ })).getByRole("button", { name: "Zona sin modelo 1" }));
    expect(await screen.findByTestId("unmodelled-notice")).toHaveTextContent("sin modelo");
    expect(screen.queryByRole("region", { name: "Observaciones de la entidad" })).toBeNull();
    expect(rowOf("U1")).toHaveTextContent("sin modelo");
  });
});

describe("Data mode on irregular samples (Water)", () => {
  beforeEach(() => {
    resetMaps();
    installApi({}, real.realData());
  });

  it("asks for the window [from, to) (each point's latest sample) and shows the sample's own date", async () => {
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Ríos de Inglaterra/ }));
    await user.click(await screen.findByRole("button", { name: "Datos observados" }));
    await waitFor(() => expect(calls("/observations")).toHaveLength(1));
    const q = calls("/observations")[0]!;
    expect([q.get("from"), q.get("to"), q.get("time")]).toEqual(["2025-12-01T00:00:00Z", "2026-01-01T00:00:00Z", null]);
    expect(await screen.findByRole("heading", { name: /Datos observados: última muestra de cada punto de muestreo en la ventana/ })).toBeInTheDocument();
    const last = real.water.series.find((s) => s.entity_id === real.WATER_POINT)!.points.filter((p) => p.issued_at_utc >= "2025-12-01T00:00:00Z").at(-1)!;
    await waitFor(() => expect(features().find((f) => f.properties.entity_id === real.WATER_POINT)?.properties.value).toBe(last.observed));
    expect(rowOf(real.WATER_EMPTY_POINT)).toHaveTextContent("sin dato");
    expect(rowOf(real.WATER_EMPTY_POINT)).toHaveTextContent("sin observación");
    expect(screen.getByRole("columnheader", { name: /Muestra \(fecha de validez\)/ })).toBeInTheDocument();
  });
});
