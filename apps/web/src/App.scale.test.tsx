import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MetricsReport, ModelCard, ModelRules } from "./api/types";
import { App } from "./App";
import { fake, installApi, json } from "./test/fakeApi";
import * as fx from "./test/fixtures";
import { labelerFor } from "./lib/labels";

const labelOf = labelerFor(fx.rules.variables);
import { MADRID_ATTRIBUTION } from "./test/fixturesV04";
import { maps, resetMaps } from "./test/maplibreMock";

vi.mock("maplibre-gl", async () => (await import("./test/maplibreMock")).maplibreFactory());
// These tests count the requests of browsing; the probing of the default time has its own tests (App.round4.test.tsx).
vi.mock("./hooks/useDefaultTime", () => ({ useDefaultTime: () => false }));

beforeEach(() => resetMaps());
afterEach(() => vi.unstubAllGlobals());

const HOUR = 3_600_000;
const params = (path: string) => new URL(path, "http://x").searchParams;
const callsTo = (endpoint: string) => fake.calls.filter((c) => c.startsWith(`/api/v1${endpoint}?`)).map(params);
const yearCoverage = { issued_from_utc: "2025-01-01T00:00:00Z", issued_to_utc: "2025-12-31T23:00:00Z", step_hours: 1 };
const withCoverage = (coverage: ModelCard["coverage"]): ModelCard => ({ ...fx.card, coverage });
/** The workspace is up (timeline present); with a year-long coverage there is no golden rule-map for 2025-01-01, so no legend. */
const ready = () => screen.findByLabelText("Hora de emisión");
const featuresOf = (map: (typeof maps)[number]) =>
  (map.sources["stations"] as { data: { features: { properties: { entity_id: string } }[] } }).data.features;

describe("Prediction mode at scale", () => {
  it("asks ONE /predictions for the selected issue time and loads a series only for the selected entity, in a 6-day block", async () => {
    installApi();
    render(<App initialTab="prediccion" />);
    const user = userEvent.setup();
    await screen.findByLabelText("Hora de emisión");
    await screen.findByRole("region", { name: /Leyenda: NO₂ previsto/ });
    // One request for all entities: an issue time, no per-entity series, no window.
    const predictions = callsTo("/predictions");
    expect(predictions).toHaveLength(1);
    expect(predictions[0]!.get("task_id")).toBe(fx.card.manifest.task_id);
    expect(predictions[0]!.get("time")).toBe("2025-01-15T06:00:00Z");
    expect(predictions[0]!.get("from")).toBeNull();
    expect(callsTo("/series")).toHaveLength(0);
    // Selecting an entity loads its series only (the chart), around the selected time and never the full coverage.
    await user.click(within(screen.getByRole("table", { name: /Estaciones/ })).getByRole("button", { name: "Synthetic station B (not real)" }));
    await waitFor(() => expect(callsTo("/series")).toHaveLength(1));
    const q = callsTo("/series")[0]!;
    expect(q.get("entity_id")).toBe("SYN_B");
    const t = Date.parse("2025-01-15T06:00:00Z");
    const from = Date.parse(q.get("from")!);
    const to = Date.parse(q.get("to")!);
    expect(to - from).toBeLessThanOrEqual(7 * 24 * HOUR);
    expect(t - from).toBeGreaterThanOrEqual(48 * HOUR);
    expect(to - t).toBeGreaterThanOrEqual(48 * HOUR);
    expect(callsTo("/predictions")).toHaveLength(1);
    // The legend says what the scale is based on.
    expect(screen.getByText(/se ajusta a las predicciones cargadas/)).toBeInTheDocument();
  });

  it("with 8,760 issue times, each settled time asks one /predictions; the selected series is re-requested only outside its block", async () => {
    installApi({}, { card: withCoverage(yearCoverage) });
    render(<App initialTab="prediccion" />);
    const user = userEvent.setup();
    await ready();
    await waitFor(() => expect(callsTo("/predictions")).toHaveLength(1));
    await user.click(within(screen.getByRole("table", { name: /Estaciones/ })).getByRole("button", { name: "Synthetic station B (not real)" }));
    await waitFor(() => expect(callsTo("/series")).toHaveLength(1));
    const slider = screen.getByLabelText("Hora de emisión");
    fireEvent.change(slider, { target: { value: "5" } }); // 2025-01-01 05:00, same 48 h block
    await screen.findByText(/01\/01\/2025, 05:00 UTC/);
    await waitFor(() => expect(callsTo("/predictions")).toHaveLength(2));
    expect(callsTo("/predictions")[1]!.get("time")).toBe("2025-01-01T05:00:00Z");
    expect(callsTo("/series")).toHaveLength(1);
    fireEvent.change(slider, { target: { value: "4000" } }); // 2025-06-16 16:00
    await waitFor(() => expect(callsTo("/series")).toHaveLength(2));
    const t = Date.parse("2025-06-16T16:00:00Z");
    const q = callsTo("/series")[1]!;
    expect(Date.parse(q.get("from")!)).toBeLessThanOrEqual(t - 48 * HOUR);
    expect(Date.parse(q.get("to")!)).toBeGreaterThan(t + 48 * HOUR);
    // Entities without a prediction at that time are shown as such, not as 0.
    const table = await screen.findByRole("table", { name: /Estaciones/ });
    await waitFor(() => expect(within(table).getAllByText(/predicción no disponible/).length).toBe(4));
  });

  it("keeps its own title, unit and legend, and shows the model panel with the metrics table", async () => {
    const metrics: MetricsReport = {
      model_id: fx.card.manifest.model_id,
      task_id: fx.card.manifest.task_id,
      split: fx.card.manifest.split,
      rows: [
        { estimator: "exfuzzy", metric: "mae", value: 7.5, n: 100 },
        { estimator: "persistence", metric: "mae", value: 9.25, n: 100 },
      ],
    };
    installApi({}, { card: { ...fx.card, metrics } });
    render(<App initialTab="prediccion" />);
    await screen.findByLabelText("Hora de emisión");
    expect(await screen.findByRole("heading", { name: /Predicción del modelo: NO₂ a \+6 h/ })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /activación de regla/ })).toBeNull();
    const table = screen.getByRole("table", { name: /Mismo periodo de prueba/ });
    expect(within(table).getByText("9,250")).toBeInTheDocument();
    expect(screen.getByText(/hand-written toy rule base/)).toBeInTheDocument(); // manifest.warnings
  });
});

describe("Aggregate window selector", () => {
  const pick = async (user: ReturnType<typeof userEvent.setup>, name: RegExp) => user.click(screen.getByRole("radio", { name }));

  it("sends half-open [from, to) windows of at most 366 days containing the selected time", async () => {
    installApi();
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await screen.findByRole("region", { name: /Leyenda/ });
    await pick(user, /Media en la ventana/);
    // Default window: the UTC week (Monday to Monday) that contains 2025-01-15 (a Wednesday).
    await waitFor(() => expect(callsTo("/rule-map").some((q) => q.get("metric") === "mean_activation")).toBe(true));
    const windows = () => callsTo("/rule-map").filter((q) => q.get("metric") === "mean_activation").map((q) => [q.get("from"), q.get("to")]);
    expect(windows().at(-1)).toEqual(["2025-01-13T00:00:00Z", "2025-01-20T00:00:00Z"]);
    await pick(user, /Día \(UTC\)/);
    await waitFor(() => expect(windows().at(-1)).toEqual(["2025-01-15T00:00:00Z", "2025-01-16T00:00:00Z"]));
    await pick(user, /Mes \(UTC\)/);
    await waitFor(() => expect(windows().at(-1)).toEqual(["2025-01-01T00:00:00Z", "2025-02-01T00:00:00Z"]));
    await pick(user, /Toda la cobertura/);
    await waitFor(() => expect(windows().at(-1)).toEqual(["2025-01-15T06:00:00Z", "2025-01-15T12:00:00Z"]));
    for (const [from, to] of windows()) {
      expect((Date.parse(to!) - Date.parse(from!)) / (24 * HOUR)).toBeLessThanOrEqual(366);
      expect(Date.parse(to!)).toBeGreaterThan(Date.parse(from!));
    }
    // The golden whole-coverage answer is painted, and the legend states the window and n_valid.
    const legend = await screen.findByRole("region", { name: /Leyenda: activación media/ });
    expect(legend).toHaveTextContent("[2025-01-15T06:00:00Z, 2025-01-15T12:00:00Z)");
    expect(legend).toHaveTextContent("Emisiones válidas por estación");
  });

  it("offers the whole coverage for a year (365 d) but not for two years", async () => {
    installApi({}, { card: withCoverage(yearCoverage) });
    const { unmount } = render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await ready();
    await pick(user, /Media en la ventana/);
    expect(screen.getByRole("radio", { name: /Toda la cobertura/ })).toBeEnabled();
    await pick(user, /Toda la cobertura/);
    await waitFor(() => {
      const q = callsTo("/rule-map").filter((c) => c.get("metric") === "mean_activation").at(-1)!;
      expect([q.get("from"), q.get("to")]).toEqual(["2025-01-01T00:00:00Z", "2026-01-01T00:00:00Z"]);
    });
    unmount();
    resetMaps();
    installApi({}, { card: withCoverage({ ...yearCoverage, issued_to_utc: "2026-12-31T23:00:00Z" }) });
    render(<App initialTab="explorar" />);
    await ready();
    await pick(user, /Media en la ventana/);
    expect(screen.getByRole("radio", { name: /Toda la cobertura/ })).toBeDisabled();
    expect(screen.getByText(/supera los 366 días/)).toBeInTheDocument();
    for (const q of callsTo("/rule-map")) {
      if (q.get("metric") === "mean_activation") {
        expect((Date.parse(q.get("to")!) - Date.parse(q.get("from")!)) / (24 * HOUR)).toBeLessThanOrEqual(366);
      }
    }
  });
});

describe("Rules at scale", () => {
  const withDuplicate = (): ModelRules => ({
    ...fx.rules,
    rules: fx.rules.rules.map((r) =>
      r.rule_id === "R02" ? { ...r, antecedents: fx.rules.rules[0]!.antecedents, duplicate_of: "R01", metrics: { mean_activation: 0.25 } } : r,
    ),
  });

  it("badges rules with duplicate_of and keeps all rules in the rail", async () => {
    installApi({}, { rules: withDuplicate() });
    render(<App initialTab="explorar" />);
    await screen.findByRole("region", { name: /Leyenda/ });
    const rail = screen.getByRole("region", { name: "Reglas del modelo" });
    expect(within(rail).getAllByRole("button", { name: /^Regla/ })).toHaveLength(3);
    expect(within(rail).getByRole("button", { name: /^Regla R02/ })).toHaveTextContent("mismas condiciones que R01 (dispara igual)");
    expect(within(rail).getByRole("button", { name: /^Regla R02/ })).toHaveTextContent("activación media 0,250");
  });

  it("opens the partitions from a rule and from an antecedent, with the station's input and mu from the trace", async () => {
    installApi();
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await screen.findByRole("region", { name: /Leyenda/ });
    expect(screen.queryByRole("region", { name: "Particiones lingüísticas" })).toBeNull();
    await user.click(screen.getByRole("button", { name: /^Regla R01/ }));
    const panel = await screen.findByRole("region", { name: "Particiones lingüísticas" });
    const first = fx.rules.rules[0]!.antecedents[0]!.feature;
    expect(within(panel).getByRole("heading")).toHaveTextContent(labelOf(first));
    // Pick a station: the panel marks its input, with mu from the trace of that station and time.
    await user.click(screen.getByRole("button", { name: "Synthetic station A (not real)" }));
    const t = fx.trace("SYN_A", "06:00");
    await waitFor(() => expect(within(panel).getByTestId("input-marker")).toHaveAttribute("data-value", String(t.feature_values.find((f) => f.feature === first)!.value)));
    const traced = t.rules.flatMap((r) => r.antecedents).find((a) => a.feature === first)!;
    expect(panel.querySelector(`circle[data-term="${traced.term}"]`)).toHaveAttribute("data-mu", String(traced.membership));
    // An antecedent in "¿Por qué aquí?" switches the panel to that variable.
    const other = fx.rules.rules[0]!.antecedents[1]!.feature;
    await user.click(await screen.findByRole("button", { name: new RegExp(`^${labelOf(other)} es .*: ver particiones de ${labelOf(other)}`) }));
    expect(within(panel).getByRole("heading")).toHaveTextContent(labelOf(other));
    await user.click(within(panel).getByRole("button", { name: "Cerrar particiones lingüísticas" }));
    expect(screen.queryByRole("region", { name: "Particiones lingüísticas" })).toBeNull();
  });
});

describe("Real geometry details", () => {
  it("keeps an entity with geometry: null off the map and lists it as 'sin geometría'", async () => {
    const entities = structuredClone(fx.entities);
    entities.features[3]!.geometry = null;
    installApi({}, { entities });
    render(<App initialTab="explorar" />);
    await screen.findByRole("region", { name: /Leyenda/ });
    await waitFor(() => expect(maps[0]?.sources["stations"]).toBeDefined());
    const drawn = featuresOf(maps[maps.length - 1]!).map((f) => f.properties.entity_id);
    expect(drawn).toEqual(entities.features.slice(0, 3).map((f) => f.properties.entity_id));
    const table = screen.getByRole("table", { name: /Estaciones/ });
    const name = entities.features[3]!.properties.name!;
    expect(within(table).getByRole("row", { name: new RegExp(name.replace(/[()]/g, "\\$&")) })).toHaveTextContent("sin geometría");
    expect(screen.getByRole("region", { name: /Leyenda/ })).toHaveTextContent("1 entidad sin geometría");
  });

  it("does not show the synthetic banner when payloads are synthetic: false, and shows real provenance and attribution", async () => {
    installApi({ "/health": () => json({ status: "ok", schema_version: "0.4.0", mode: "artifacts" }) }, { real: true, card: { ...fx.card, attribution: MADRID_ATTRIBUTION } });
    render(<App initialTab="explorar" />);
    await screen.findByRole("region", { name: /Leyenda/ });
    await waitFor(() => expect(fake.calls.some((c) => c.includes("/rule-map"))).toBe(true));
    await screen.findByText(/artifacts/);
    expect(screen.queryByText(/DATOS SINTÉTICOS/)).toBeNull();
    const footer = within(screen.getByRole("contentinfo"));
    // The attribution is whatever the API states (v0.4): its text, the licence it declares, and "no declarada" when it declares none.
    expect(footer.getByTestId("attribution")).toHaveTextContent("Ayuntamiento de Madrid, Servicio de Calidad del Aire");
    expect(footer.getByTestId("attribution")).toHaveTextContent("CC BY 4.0");
    expect(footer.getByTestId("attribution")).toHaveTextContent("licencia: no declarada en la fuente");
    expect(footer.getByText("Fuente: API")).toBeInTheDocument();
    expect(footer.getByText(fx.card.data_version)).toBeInTheDocument();
    expect(footer.getByText(fx.rules.model_id)).toBeInTheDocument();
    expect(footer.getByText("synthetic-fixture")).toBeInTheDocument(); // geometry source
    expect(footer.getByText(fx.rules.inference.exfuzzy_version)).toBeInTheDocument();
  });

  it("does not attribute synthetic fixtures to the Ayuntamiento: the footer shows what the API says, which is that they are invented", async () => {
    installApi();
    render(<App initialTab="explorar" />);
    await screen.findByText(/DATOS SINTÉTICOS/);
    await screen.findByRole("region", { name: /Leyenda/ });
    const attribution = await screen.findByTestId("attribution");
    expect(attribution).toHaveTextContent("Synthetic fixtures: invented stations and values, not a real source.");
    expect(attribution).not.toHaveTextContent("Ayuntamiento");
  });
});
