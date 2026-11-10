import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { fake, installApi } from "./test/fakeApi";
import * as fx from "./test/fixturesClass";
import { MADRID_ATTRIBUTION } from "./test/fixturesV04";
import { emit, maps, resetMaps } from "./test/maplibreMock";
import { fmtNum, missingText } from "./lib/format";

vi.mock("maplibre-gl", async () => (await import("./test/maplibreMock")).maplibreFactory());

beforeEach(() => {
  resetMaps();
  installApi({}, fx.classifierData());
});
afterEach(() => vi.unstubAllGlobals());

const issueIndex = (iso: string) => (Date.parse(iso) - Date.parse(fx.FIRST_ISSUE)) / 3_600_000;
const goTo = async (iso: string) => {
  fireEvent.change(screen.getByLabelText("Hora de emisión"), { target: { value: String(issueIndex(iso)) } });
  await waitFor(() => expect(screen.getByTestId("issue-time")).toHaveTextContent(iso.slice(11, 16)));
};
const labelAt = (entity: string, iso: string) => fx.series.find((s) => s.entity_id === entity)!.points.find((p) => p.issued_at_utc === iso)!;
const stationFeatures = () =>
  (maps[maps.length - 1]!.sources["stations"] as { data: { features: { properties: { entity_id: string; value: number | null; label: string | null } }[] } }).data.features;

describe("App with a winning-rule classifier", () => {
  it("shows no bare task-type tag (it told a reader nothing)", async () => {
    render(<App initialTab="explorar" />);
    await screen.findByRole("table", { name: /Estaciones/ });
    expect(document.querySelector('[data-testid^="task-type-"]')).toBeNull();
  });

  it("Prediction mode: categorical legend from the scheme, title, labels on the map and 'sin predicción' for null labels", async () => {
    render(<App initialTab="prediccion" />);
    await screen.findByLabelText("Hora de emisión");
    const iso = "2024-01-06T09:00:00Z";
    await goTo(iso);

    expect(await screen.findByRole("heading", { name: /Predicción del modelo: categoría prevista de y a \+6 h \(Synthetic bands/ })).toBeInTheDocument();
    const legend = await screen.findByRole("region", { name: /Leyenda: categoría prevista de y/ });
    const items = within(legend).getAllByRole("listitem");
    expect(items.map((li) => li.getAttribute("data-class"))).toEqual(fx.scheme.classes.map((c) => c.label));
    expect(items.map((li) => li.getAttribute("data-color"))).toEqual(fx.scheme.classes.map((c) => c.color));
    expect(within(legend).getByRole("link", { name: /Synthetic bands/ })).toHaveAttribute("href", fx.scheme.source_url);
    expect(legend).toHaveTextContent("Categoría que el modelo prevé para la hora de validez");
    expect(legend.textContent).not.toMatch(/riesgo|probabilidad/i);
    expect(screen.queryByRole("region", { name: /Leyenda: activación/ })).toBeNull();

    // The map gets labels, never a numeric prediction, coloured by a class lookup.
    await waitFor(() => expect(stationFeatures().some((f) => f.properties.label !== null)).toBe(true));
    for (const f of stationFeatures()) {
      expect(f.properties.value).toBeNull();
      expect(f.properties.label).toBe(labelAt(f.properties.entity_id, iso).predicted_label);
    }
    const paint = maps[maps.length - 1]!.layers["stations-valid"]!.paint!["circle-color"] as unknown[];
    expect(paint.slice(0, 2)).toEqual(["match", ["get", "label"]]);
    expect(paint).toContain("#FF3300");

    // E0 has no predicted class at this hour: "sin predicción" with the series' reason, not a value.
    const e0 = labelAt("E0", iso);
    expect(e0.predicted_label).toBeNull();
    const table = screen.getByRole("table", { name: /Estaciones/ });
    const nullRow = [...table.querySelectorAll("tr[data-entity]")].find((r) => r.getAttribute("data-entity") === "E0")!;
    expect(nullRow).toHaveTextContent("sin predicción");
    expect(nullRow).toHaveTextContent(missingText(e0.missing_reason!));
    expect(nullRow).not.toHaveTextContent(e0.missing_reason!);
    const labelled = [...table.querySelectorAll("tr[data-entity]")].find((r) => r.getAttribute("data-entity") === "E1")!;
    expect(labelled.querySelector(".class-chip")).toHaveAttribute("data-class", labelAt("E1", iso).predicted_label ?? "x");
    expect(table).not.toHaveTextContent(/µg|\d+\.\d+ u/);
  });

  it("Prediction mode: the selected station's chart has bands and category strips and no predicted line", async () => {
    render(<App initialTab="prediccion" />);
    await screen.findByLabelText("Hora de emisión");
    await goTo("2024-01-06T09:00:00Z");
    await waitFor(() => expect(stationFeatures().length).toBeGreaterThan(0));
    emit("click", { features: [{ properties: { entity_id: "E0" } }] }, "stations-valid");
    const chart = await screen.findByRole("img", { name: /observado .* y categoría prevista en E0/ });
    expect(chart.querySelectorAll("[data-band]").length).toBeGreaterThan(0);
    expect(chart.querySelectorAll('[data-strip="predicted"] rect').length).toBeGreaterThan(0);
    expect(chart.querySelector("polyline.pred, .pred")).toBeNull();
    expect(screen.getByRole("heading", { name: /Observado vs categoría prevista/ })).toBeInTheDocument();
    // Classification metrics instead of MAE/RMSE/R2.
    expect(screen.getByRole("heading", { name: "Clasificación en el periodo de prueba" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "MAE" })).toBeNull();
  });

  it("Rules mode: class chips and weights in the rail, activation legend, and the winning rule in ¿Por qué aquí?", async () => {
    render(<App initialTab="explorar" />);
    const iso = "2024-01-06T10:00:00Z";
    await screen.findByRole("region", { name: /Leyenda: activación de regla \(0–1\)/ });
    await goTo(iso);
    // The map still shows firing_strength of the selected rule at the issue time.
    await waitFor(() =>
      expect(fake.calls.some((c) => c.includes("/rule-map") && c.includes("metric=firing_strength") && c.includes("time=2024-01-06T10%3A00%3A00Z"))).toBe(true),
    );
    const rail = screen.getByRole("region", { name: "Reglas del modelo" });
    expect(within(rail).getAllByText(/^\s*· peso/).length).toBe(fx.rules.rules.length);
    expect(rail.querySelectorAll(".class-chip").length).toBe(fx.rules.rules.length);
    expect(screen.getByRole("region", { name: /Leyenda: activación/ })).toHaveTextContent("Muestra la activación de la regla elegida");

    emit("click", { features: [{ properties: { entity_id: "E0" } }] }, "stations-valid");
    const panel = await screen.findByRole("region", { name: "Why here?" });
    const trace = fx.trace("E0", iso);
    await within(panel).findByTestId("winning-rule-note");
    expect(within(panel).getByTestId("winning-rule-note")).toHaveTextContent(`La categoría la decidió ${trace.prediction.winning_rule_id}`);
    const winner = panel.querySelector('tr[data-winner="true"]')!;
    expect(winner.getAttribute("data-rule")).toBe(trace.prediction.winning_rule_id);
    const entry = trace.rules.find((r) => r.rule_id === trace.prediction.winning_rule_id)!;
    expect([...winner.querySelectorAll("[data-raw]")].map((n) => n.getAttribute("data-raw"))).toContain(String(entry.association_degree));
    expect(within(panel).getByTestId("predicted-label")).toHaveAttribute("data-class", trace.prediction.label!);
    // Observed concentration and category come from the series point of this issue time.
    const observed = labelAt("E0", iso);
    expect(await within(panel).findByTestId("observed-class")).toHaveTextContent(fmtNum(observed.observed!));
    expect(within(panel).getByTestId("observed-class").querySelector(".class-chip")).toHaveAttribute("data-class", observed.observed_label!);
  });

  it("footer: scheme source link always, and the data attribution exactly as the API states it", async () => {
    const { unmount } = render(<App initialTab="explorar" />);
    const link = await screen.findByRole("link", { name: /Synthetic bands/ });
    expect(link).toHaveAttribute("href", fx.scheme.source_url);
    expect(screen.queryByTestId("attribution")).toBeNull(); // this payload states none
    unmount();
    resetMaps();
    installApi({}, { ...fx.classifierData(), real: true, card: { ...fx.card, attribution: MADRID_ATTRIBUTION } });
    render(<App initialTab="explorar" />);
    expect(await within(screen.getByRole("contentinfo")).findByRole("link", { name: /Synthetic bands/ })).toBeInTheDocument();
    expect(await screen.findByTestId("attribution")).toHaveTextContent("Ayuntamiento de Madrid");
  });

  it("errors clearly when a classifier publishes no target_scheme", async () => {
    installApi({}, { ...fx.classifierData(), card: { ...fx.card, target_scheme: null }, rules: { ...fx.rules, target_scheme: null } });
    render(<App initialTab="explorar" />);
    expect(await screen.findByText(/no publica su esquema de categorías/)).toBeInTheDocument();
  });
});
