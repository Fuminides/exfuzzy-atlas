import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { emit, maps, resetMaps } from "./test/maplibreMock";
import { fake, installApi, json } from "./test/fakeApi";
import * as fx from "./test/fixtures";

vi.mock("maplibre-gl", async () => (await import("./test/maplibreMock")).maplibreFactory());
// These tests are about what Explorar shows at the fixture's first issue time; the opening-moment probe has its own tests
// (App.opening.test.tsx), so here every probe answers "no information" and the page stays at the first issue time.
vi.mock("./hooks/defaultTimeScores", async (orig) => ({ ...(await orig<typeof import("./hooks/defaultTimeScores")>()), firingScore: () => async () => null }));

beforeEach(() => {
  resetMaps();
  installApi();
});
afterEach(() => vi.unstubAllGlobals());

describe("App", () => {
  it("discovers the model from /domains and says so when the task has none", async () => {
    const noModel = {
      ...fx.domains,
      domains: fx.domains.domains.map((d) => ({ ...d, tasks: d.tasks.map((t) => ({ ...t, model_id: null })) })),
    };
    installApi({ "/domains": () => json(noModel) });
    render(<App initialTab="explorar" />);
    expect(await screen.findByText(/todavía no tiene un modelo publicado/)).toBeInTheDocument();
    expect(fake.calls.some((c) => c.includes("/models/"))).toBe(false);
  });

  it("shows the synthetic banner and, in Rules mode, the activation legend with a rule-map request", async () => {
    render(<App initialTab="explorar" />);
    expect(await screen.findByText(/DATOS SINTÉTICOS. No son mediciones reales/)).toBeInTheDocument();
    const legend = await screen.findByRole("region", { name: /Leyenda: activación de regla \(0–1\)/ });
    expect(legend).toHaveAttribute("data-domain", "0-1");
    // The first rule is selected and the rule map is asked for the issue time, as firing_strength.
    await waitFor(() =>
      expect(fake.calls.some((c) => c.includes("/rule-map") && c.includes("metric=firing_strength") && c.includes("time=2025-01-15T06%3A00%3A00Z"))).toBe(true),
    );
    // Footer provenance
    const footer = within(screen.getByRole("contentinfo"));
    expect(footer.getByText("synthetic-no2-h6-v0")).toBeInTheDocument();
    expect(footer.getByText("synthetic-fixture-v0")).toBeInTheDocument();
  });

  it("colours the map from rule-map values and distinguishes 0 from null at 08:00 UTC", async () => {
    render(<App initialTab="explorar" />);
    await screen.findByRole("region", { name: /Leyenda/ });
    fireEvent.change(screen.getByLabelText("Hora de emisión"), { target: { value: "2" } });
    await waitFor(() => expect(screen.getByTestId("issue-time")).toHaveTextContent("08:00 UTC"));
    // R01 at 08:00: SYN_A has firing 0, SYN_D has no inference (null).
    await waitFor(() => {
      const table = screen.getByRole("table", { name: /Estaciones/ });
      const a = within(table).getByRole("row", { name: /station A/i });
      const d = within(table).getByRole("row", { name: /station D/i });
      expect(a.querySelector(".marker--value")).not.toBeNull();
      expect(d).toHaveTextContent("sin dato");
      expect(d).toHaveTextContent("falta una entrada");
    });
    await waitFor(() => {
      const map = maps[maps.length - 1]!;
      const features = (map.sources["stations"] as { data: { features: { properties: { value: number | null } }[] } }).data.features;
      expect(features.map((f) => f.properties.value)).toContain(null);
      expect(features.map((f) => f.properties.value)).toContain(0);
    });
  });

  it("opens Why here? for a clicked station and keeps rule and station when the time moves", async () => {
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await screen.findByRole("region", { name: /Leyenda/ });
    await waitFor(() => expect(maps[0]?.layers["stations-valid"]).toBeDefined());
    // Click on the map layer selects the same station as the table does.
    emit("click", { features: [{ properties: { entity_id: "SYN_B" } }] }, "stations-valid");
    const panel = await screen.findByRole("region", { name: "Why here?" });
    await within(panel).findByText("t-norma", { exact: false });
    expect(fake.calls.some((c) => c.includes("/entities/SYN_B/rule-trace") && c.includes("model_id=synthetic-no2-h6-v0"))).toBe(true);
    await user.click(screen.getByRole("button", { name: /Regla R02/ }));
    await user.click(screen.getByRole("button", { name: "Emisión siguiente" }));
    await waitFor(() => expect(fake.calls.some((c) => c.includes("/entities/SYN_B/rule-trace") && c.includes("07%3A00"))).toBe(true));
    expect(screen.getByRole("button", { name: /Regla R02/ })).toHaveAttribute("aria-pressed", "true");
  });

  it("Prediction mode uses the concentration unit and not the activation legend", async () => {
    render(<App initialTab="prediccion" />);
    const user = userEvent.setup();
    const legend = await screen.findByRole("region", { name: /Leyenda: NO₂ previsto \(µg\/m³\)/ });
    expect(legend.textContent).not.toMatch(/activación/);
    expect(screen.queryByRole("region", { name: /activación de regla \(0–1\)/ })).toBeNull();
    expect(screen.getByRole("heading", { name: /Predicción del modelo: NO₂ a \+6 h \(µg\/m³\)/ })).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Synthetic station A (not real)" }));
    expect(await screen.findByRole("img", { name: /NO₂ observado y predicho \(µg\/m³\)/ })).toBeInTheDocument();
    expect(screen.queryByText("Reglas del modelo")).toBeNull();
  });

  it("Water is an honest placeholder driven by /domains", async () => {
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await screen.findByRole("region", { name: /Leyenda/ });
    await user.click(screen.getByRole("button", { name: /England water quality/ }));
    expect(await screen.findByText(/todavía no hay tareas, modelo ni datos/)).toBeInTheDocument();
  });

  it("shows an error with retry when the API is down", async () => {
    installApi({ "/domains": () => Promise.reject(new TypeError("offline")) });
    render(<App initialTab="explorar" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("make api");
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeInTheDocument();
  });
});
