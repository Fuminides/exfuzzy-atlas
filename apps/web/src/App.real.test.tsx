import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { fake, installApi } from "./test/fakeApi";
import { fmtNum, formatShortDate } from "./lib/format";
import * as fx from "./test/fixturesReal";
import { withUnmodelledZones } from "./test/fixturesV04";
import { emit, maps, resetMaps } from "./test/maplibreMock";

vi.mock("maplibre-gl", async () => (await import("./test/maplibreMock")).maplibreFactory());

/** The real NYC and Water models (golden payloads, see fixturesReal.ts). */
beforeEach(() => {
  resetMaps();
  installApi({}, fx.realData());
});
afterEach(() => vi.unstubAllGlobals());

type Feature = { geometry: { type: string }; properties: { entity_id: string; value: number | null; label: string | null; no_reference: boolean } };
const features = (): Feature[] => (maps[maps.length - 1]!.sources["stations"] as { data: { features: Feature[] } }).data.features;
const layers = () => maps[maps.length - 1]!.layers;
const openDomain = async (user: ReturnType<typeof userEvent.setup>, name: RegExp) => user.click(await screen.findByRole("button", { name }));
const nycHour = (iso: string) => (Date.parse(iso) - Date.parse(fx.NYC_FIRST_ISSUE)) / 3_600_000;
const goToEvening = async () => {
  fireEvent.change(await screen.findByLabelText("Hora de emisión"), { target: { value: String(nycHour(fx.NYC_EVENING)) } });
  await waitFor(() => expect(screen.getByTestId("issue-time")).toHaveTextContent("23:00 UTC"));
};
const point = (entity: string) => fx.nyc.series.find((s) => s.entity_id === entity)!.points.find((p) => p.issued_at_utc === fx.NYC_EVENING)!;
const row = (entity: string) => document.querySelector(`table.stations tr[data-entity="${entity}"]`)!;

describe("domains", () => {
  it("lists all three domains as available, each with its own task type", async () => {
    installApi({}, { domains: fx.domains });
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    expect(await screen.findByRole("button", { name: "Madrid" })).toHaveAttribute("aria-pressed", "true");
    expect(document.querySelector('[data-testid^="task-type-"]')).toBeNull();
    await user.click(screen.getByRole("button", { name: /Ríos de Inglaterra/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: /Ríos de Inglaterra/ })).toHaveAttribute("aria-pressed", "true"));
    await user.click(screen.getByRole("button", { name: /Taxis de Nueva York/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: /Taxis de Nueva York/ })).toHaveAttribute("aria-pressed", "true"));
    expect(fx.domains.domains.every((d) => d.status === "available")).toBe(true);
  });

  it("each territory's domain sets the data-domain of the app root, which carries its background wash", async () => {
    installApi({}, { domains: fx.domains });
    render(<App initialTab="patrones" />);
    const user = userEvent.setup();
    const root = () => document.querySelector(".app")!;
    await waitFor(() => expect(root()).toHaveAttribute("data-domain", "air")); // Madrid
    await user.click(screen.getByRole("button", { name: /Ríos de Inglaterra/ }));
    await waitFor(() => expect(root()).toHaveAttribute("data-domain", "water"));
    await user.click(screen.getByRole("button", { name: /Taxis de Nueva York/ }));
    await waitFor(() => expect(root()).toHaveAttribute("data-domain", "mobility"));
  });

  it("switching resets the selection and uses each task's own model, scheme, timezone, units and attribution", async () => {
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await openDomain(user, /Taxis de Nueva York/);
    const footer = within(screen.getByRole("contentinfo"));
    await waitFor(() => expect(footer.getByText(fx.nyc.rules.model_id)).toBeInTheDocument());
    expect(footer.getByTestId("scheme-source")).toBeInTheDocument();
    // The attribution is what the API states (v0.4): the TLC declares no open licence and the footer says so.
    expect(footer.getByTestId("attribution")).toHaveTextContent("NYC Taxi & Limousine Commission (TLC) Trip Record Data");
    expect(footer.getByTestId("attribution")).toHaveTextContent("no declara una licencia abierta explícita");
    expect(footer.getByTestId("attribution")).toHaveTextContent("licencia: no declarada en la fuente");
    expect(footer.getByText("taxi_zones.zip")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Brownsville" }));
    expect(await screen.findByText(/seleccionada:/)).toBeInTheDocument();
    expect(await screen.findByLabelText("Hora de emisión")).toHaveAttribute("aria-valuetext", expect.stringContaining("America/New_York"));

    await openDomain(user, /Ríos de Inglaterra/);
    await waitFor(() => expect(footer.getByText(fx.water.rules.model_id)).toBeInTheDocument());
    expect(screen.queryByText(/seleccionad[oa]:/)).toBeNull(); // nothing selected in the new domain
    expect(footer.queryByTestId("scheme-source")).toBeNull(); // a regressor has no category scheme
    expect(footer.getByTestId("attribution")).toHaveTextContent("© Environment Agency copyright and/or database right 2025");
    expect(footer.getByTestId("attribution")).toHaveTextContent("licencia: Open Government Licence v3.0");
    expect(footer.queryByText("taxi_zones.zip")).toBeNull();
    expect(await screen.findByRole("table", { name: /Puntos de muestreo/ })).toBeInTheDocument();

    await openDomain(user, /Taxis de Nueva York/);
    expect(await screen.findByRole("table", { name: /Zonas de taxi/ })).toBeInTheDocument();
    expect(screen.queryByText(/seleccionad[oa]:/)).toBeNull();
  });
});

describe("NYC: polygons, categories and 'sin referencia'", () => {
  it("Prediction mode on a weekday evening: choropleth by predicted_label with the scheme's colours", async () => {
    render(<App initialTab="prediccion" />);
    const user = userEvent.setup();
    await openDomain(user, /Taxis de Nueva York/);
    await goToEvening();
    await waitFor(() => expect(features().some((f) => f.properties.label !== null)).toBe(true));

    // Real polygons, API label per zone, never a numeric value.
    expect(new Set(features().map((f) => f.geometry.type))).toEqual(new Set(["Polygon", "MultiPolygon"]));
    for (const f of features()) {
      expect(f.properties.value).toBeNull();
      expect(f.properties.label).toBe(point(f.properties.entity_id).predicted_label);
    }
    const colors = fx.nyc.card.target_scheme!.classes.flatMap((c) => [c.label, c.color]);
    expect(layers()["zones-fill"]!.paint!["fill-color"]).toEqual(["match", ["get", "label"], ...colors, "#94a3b8"]);
    expect(layers()["zones-fill"]!.filter).toEqual([
      "all",
      ["==", ["geometry-type"], "Polygon"],
      ["!=", ["get", "missing_reason"], "not_modelled"],
      ["==", ["typeof", ["get", "label"]], "string"],
    ]);
    expect(layers()["zones-no-reference"]!.paint!["fill-pattern"]).toBe("no-reference-hatch");

    expect(screen.getByRole("heading", { name: "Predicción del modelo: nivel de demanda de taxi amarillo previsto a +1 h" })).toBeInTheDocument();
    const legend = screen.getByRole("region", { name: /Leyenda: Nivel de demanda de taxi amarillo previsto/ });
    expect(legend).toHaveTextContent("respecto a lo habitual en esa zona a esa hora de la semana (percentil del periodo de entrenamiento)");
    expect(legend).toHaveTextContent("percentil ≥ 25 y < 75");
    expect(legend).not.toHaveTextContent("del target en su celda"); // the long scheme unit is not pasted next to each class
    expect(within(legend).getAllByRole("listitem").map((li) => li.getAttribute("data-class"))).toEqual(["baja", "normal", "alta", "muy alta"]);
    expect(legend).toHaveTextContent("Nivel de demanda de taxi amarillo respecto a lo habitual");
  });

  it("'sin referencia' zones are hatched with their own outline and listed as such, never as a class", async () => {
    render(<App initialTab="prediccion" />);
    const user = userEvent.setup();
    await openDomain(user, /Taxis de Nueva York/);
    await goToEvening();
    await waitFor(() => expect(features().some((f) => f.properties.label !== null)).toBe(true));

    for (const id of fx.NYC_NO_REFERENCE) {
      const p = point(id);
      expect([p.predicted_label, p.observed_label, p.missing_reason]).toEqual([null, null, "prediction_unavailable"]);
      const f = features().find((x) => x.properties.entity_id === id)!;
      expect(f.properties).toMatchObject({ label: null, value: null, no_reference: true });
      expect(row(id)).toHaveTextContent("sin referencia");
      expect(row(id).querySelector(".class-chip")).toBeNull();
      expect(row(id).querySelector(".marker--noref")).not.toBeNull();
    }
    expect(features().filter((f) => f.properties.no_reference).map((f) => f.properties.entity_id).sort()).toEqual([...fx.NYC_NO_REFERENCE].sort());
    // the hatch and its dashed outline only take zones with no label; the wash and grey outline take the other missing ones
    expect(JSON.stringify(layers()["zones-no-reference"]!.filter)).toContain('["==",["get","no_reference"],true]');
    expect(JSON.stringify(layers()["zones-missing"]!.filter)).toContain('["!=",["get","no_reference"],true]');
    expect(layers()["zones-line-no-reference"]!.paint!["line-dasharray"]).toBeDefined();
    const legend = screen.getByTestId("no-reference-legend");
    expect(legend).toHaveTextContent("sin referencia");
    expect(legend).toHaveTextContent("no se pinta como «normal» ni como clase");
    expect(legend).toHaveTextContent(`${fx.NYC_NO_REFERENCE.length}`);
    // zones with a class keep it
    expect(row(fx.NYC_ZONE).querySelector(".class-chip")).toHaveAttribute("data-class", point(fx.NYC_ZONE).predicted_label!);
  });

  it("draws zones without a model light and quiet, counts them apart, and keeps zones without geometry in the table only", async () => {
    const zero = { ...fx.nyc.entities, features: fx.nyc.entities.features.map((f) => (f.id === "41" ? { ...f, geometry: null } : f)) };
    const withZones = withUnmodelledZones(zero, 3);
    installApi({}, { ...fx.realData(), entities: withZones });
    render(<App initialTab="prediccion" />);
    const user = userEvent.setup();
    await openDomain(user, /Taxis de Nueva York/);
    await goToEvening();
    await waitFor(() => expect(features().length).toBeGreaterThan(0));
    expect(features().map((f) => f.properties.entity_id)).not.toContain("41");
    expect(features()).toHaveLength(withZones.features.length - 1);
    expect(row("41")).toHaveTextContent("sin geometría");
    // "N zonas con modelo de M": the zones without a model are not part of the count of zones with a prediction
    const note = await screen.findByTestId("absent-note");
    expect(note).toHaveTextContent(`${zero.features.length} de ${withZones.features.length} zonas de taxi con modelo; 3 sin modelo (gris claro)`);
    expect(note).toHaveTextContent("el gris no indica demanda baja");
    expect(screen.getByRole("region", { name: /Leyenda/ })).toHaveTextContent("1 entidad sin geometría");
    // They carry missing_reason "not_modelled" on the map, which draws them in the quiet layers, not as missing
    const unmodelled = features().filter((f) => f.properties.entity_id.startsWith("U"));
    expect(unmodelled).toHaveLength(3);
    for (const f of unmodelled) expect((f.properties as unknown as { missing_reason: string }).missing_reason).toBe("not_modelled");
    expect(layers()["zones-unmodelled"]!.paint!["fill-opacity"]).toBeLessThan(0.3);
    expect(row("U1")).toHaveTextContent("sin modelo");
    expect(row("U1")).not.toHaveTextContent("sin predicción");
    // counts: classes are counted over the zones that have a model
    expect(screen.getByRole("region", { name: /Leyenda/ })).toHaveTextContent(new RegExp(`Zonas de taxi con categoría prevista: \\d+ de ${zero.features.length}`));
  });

  it("local time is the zone's America/New_York, never Madrid", async () => {
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await openDomain(user, /Taxis de Nueva York/);
    await goToEvening();
    expect(screen.getByTestId("issue-time")).toHaveTextContent("19/03/2025, 23:00 UTC · 19:00 America/New_York");
    expect(screen.getByTestId("valid-time")).toHaveTextContent("20:00 America/New_York");
    expect(document.body).not.toHaveTextContent("Europe/Madrid");
    const zoneSelect = screen.getByLabelText("Zona del campo") as HTMLSelectElement;
    expect([...zoneSelect.options].map((o) => o.value)).toEqual(["UTC", "America/New_York"]);
    await user.selectOptions(zoneSelect, "America/New_York");
    expect(screen.getByLabelText("Ir a fecha y hora")).toHaveValue("2025-03-19T19:00"); // EDT, UTC-4
    expect(screen.getByLabelText("Hora de emisión")).toHaveAttribute("aria-valuetext", expect.stringContaining("19:00 America/New_York"));
    expect(await screen.findByText(/19 de marzo de 2025/)).toBeInTheDocument();
  });

  it("Rules mode: a zone with a winning rule shows it and the associations; the polygons carry the firing", async () => {
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await openDomain(user, /Taxis de Nueva York/);
    await goToEvening();
    await screen.findByRole("region", { name: /Leyenda: activación de regla/ });
    await waitFor(() => expect(features().some((f) => f.properties.value !== null)).toBe(true));
    const golden = fx.nyc.ruleMapFor(new URLSearchParams({ rule_id: "R01", metric: "firing_strength", time: fx.NYC_EVENING }))!;
    for (const f of features()) {
      expect(f.properties.value).toBe(golden.features.find((g) => g.properties.entity_id === f.properties.entity_id)!.properties.value);
    }
    expect(layers()["zones-fill"]!.paint!["fill-color"]).toEqual(layers()["stations-valid"]!.paint!["circle-color"]);
    expect(JSON.stringify(layers()["zones-fill"]!.paint!["fill-color"])).toContain('["get","value"]');

    emit("click", { features: [{ properties: { entity_id: fx.NYC_ZONE } }] }, "zones-fill");
    const panel = await screen.findByRole("region", { name: "Why here?" });
    const trace = fx.nyc.traces.find((t) => t.entity_id === fx.NYC_ZONE)!;
    expect(await within(panel).findByTestId("winning-rule-note")).toHaveTextContent(`La categoría la decidió ${trace.prediction.winning_rule_id}`);
    expect(panel.querySelector('tr[data-winner="true"]')!.getAttribute("data-rule")).toBe(trace.prediction.winning_rule_id);
    expect(within(panel).getByTestId("predicted-label")).toHaveAttribute("data-class", trace.prediction.label!);
    // Observed is a count of trips (not the scheme's percentile unit) with its reference class.
    const observed = point(fx.NYC_ZONE);
    expect(await within(panel).findByTestId("observed-class")).toHaveTextContent(`${observed.observed} viajes`);
    expect(panel).toHaveTextContent("19:00 America/New_York");
  });

  it("#51: a zone with no reference level shows 'sin referencia', no winner, and still lists the engine's associations", async () => {
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await openDomain(user, /Taxis de Nueva York/);
    await goToEvening();
    await screen.findByRole("region", { name: /Leyenda: activación de regla/ });
    emit("click", { features: [{ properties: { entity_id: "35" } }] }, "zones-fill");
    const panel = await screen.findByRole("region", { name: "Why here?" });
    const trace = fx.nyc.traces.find((t) => t.entity_id === "35")!;
    expect([trace.prediction.label, trace.prediction.winning_rule_id, trace.prediction.missing_reason]).toEqual([null, null, "prediction_unavailable"]);
    expect(await within(panel).findByTestId("no-reference")).toHaveTextContent("sin referencia");
    expect(within(panel).queryByTestId("winning-rule-note")).toBeNull();
    expect(within(panel).queryByTestId("predicted-label")).toBeNull();
    expect(panel.querySelector('tr[data-winner="true"]')).toBeNull();
    const associations = within(panel).getByRole("table", { name: "Reglas por grado de asociación" });
    expect(associations.querySelectorAll("tbody tr")).toHaveLength(trace.rules.length);
    expect(panel).toHaveTextContent("no reference level");
  });

  it("the table is still a working alternative to the map", async () => {
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await openDomain(user, /Taxis de Nueva York/);
    await goToEvening();
    await user.click(await screen.findByRole("button", { name: "Alphabet City" }));
    expect(row("4")).toHaveAttribute("aria-selected", "true");
    // the panel is "idle" for a render before the trace request starts: wait for the zone's name, do not read it once
    await waitFor(() => expect(screen.getByRole("region", { name: "Why here?" })).toHaveTextContent("Alphabet City"));
  });
});

describe("Water: irregular samples", () => {
  const windowRange = () => screen.findByTestId("window-range");
  const ruleMapCalls = () => fake.calls.filter((c) => c.includes("/rule-map")).map((c) => new URL(c, "http://x").searchParams);

  it("has no hourly timeline: it defaults to a monthly mean_activation window", async () => {
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await openDomain(user, /Ríos de Inglaterra/);
    expect(await windowRange()).toHaveTextContent("[2025-12-01 00:00 UTC, 2026-01-01 00:00 UTC) · 31 d");
    expect(screen.queryByLabelText("Hora de emisión")).toBeNull();
    expect(screen.queryByRole("button", { name: "+1 h" })).toBeNull();
    expect(screen.getByRole("button", { name: "Mes" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("irregular-note")).toHaveTextContent("no hay una por hora");
    await waitFor(() => expect(ruleMapCalls().length).toBeGreaterThan(0));
    for (const q of ruleMapCalls()) {
      expect(q.get("metric")).toBe("mean_activation");
      expect(q.get("time")).toBeNull();
      expect([q.get("from"), q.get("to")]).toEqual(["2025-12-01T00:00:00Z", "2026-01-01T00:00:00Z"]);
    }
    // an instant is meaningless here: that view is not offered
    expect(screen.queryByRole("radio", { name: /firing_strength/ })).toBeNull();
    expect(screen.getByRole("radio", { name: /Media en la ventana/ })).toBeChecked();
    expect(await screen.findByRole("region", { name: /Leyenda: activación media/ })).toHaveTextContent("Muestras válidas por punto de muestreo");
    expect(screen.getByRole("region", { name: /Leyenda/ })).toHaveTextContent("periodo de prueba");
  });

  it("the map shows 0 as a value and a point without samples as missing (0 is not null)", async () => {
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await openDomain(user, /Ríos de Inglaterra/);
    await windowRange();
    await waitFor(() => expect(features().length).toBeGreaterThan(0));
    await waitFor(() => expect(features().some((f) => f.properties.value === 0)).toBe(true));
    expect(new Set(features().map((f) => f.geometry.type))).toEqual(new Set(["Point"]));
    const byId = new Map(features().map((f) => [f.properties.entity_id, f.properties.value]));
    expect(byId.get(fx.WATER_POINT)).toBe(0);
    expect(byId.get(fx.WATER_EMPTY_POINT)).toBeNull();
    // the Rules rail shows regression consequents as numbers in mg/l, and flags duplicates as before
    const rail = screen.getByRole("region", { name: "Reglas del modelo" });
    const first = fx.water.rules.rules[0]!;
    expect(within(rail).getByRole("button", { name: new RegExp(`^Regla ${first.rule_id}:`) })).toHaveTextContent(`→ ${fmtNum(first.consequent.value!)} mg/l`);
    expect(screen.getByRole("region", { name: `Regla ${first.rule_id}` })).toHaveTextContent("Consecuente (constante de la regla)");
    const dup = fx.water.rules.rules.find((r) => r.duplicate_of);
    if (dup) expect(within(rail).getByRole("button", { name: new RegExp(`^Regla ${dup.rule_id}:.*mismas condiciones que ${dup.duplicate_of}`) })).toBeInTheDocument();
  });

  it("the window moves by month, day or year, never by hour, and the map follows it", async () => {
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await openDomain(user, /Ríos de Inglaterra/);
    await windowRange();
    expect(screen.getByRole("button", { name: "Ventana siguiente" })).toBeDisabled(); // the coverage ends in December 2025
    await user.click(screen.getByRole("button", { name: "Ventana anterior" }));
    expect(await windowRange()).toHaveTextContent("[2025-11-01 00:00 UTC, 2025-12-01 00:00 UTC) · 30 d");
    await waitFor(() => expect(ruleMapCalls().some((q) => q.get("from") === "2025-11-01T00:00:00Z" && q.get("to") === "2025-12-01T00:00:00Z")).toBe(true));
    await user.click(screen.getByRole("button", { name: "Semana" }));
    expect(await windowRange()).toHaveTextContent("[2025-10-27 00:00 UTC, 2025-11-03 00:00 UTC) · 7 d"); // Monday to Monday
    await user.click(screen.getByRole("button", { name: "Año" }));
    expect(await windowRange()).toHaveTextContent("[2025-01-01 00:00 UTC, 2026-01-01 00:00 UTC) · 365 d");
    fireEvent.change(screen.getByLabelText("Ir a fecha"), { target: { value: "2024-03-10" } });
    expect(await windowRange()).toHaveTextContent("[2024-01-01 00:00 UTC, 2025-01-01 00:00 UTC) · 366 d");
    expect(screen.getByRole("button", { name: "Ventana anterior" })).toBeDisabled();
    expect(fake.calls.filter((c) => c.includes("metric=firing_strength"))).toHaveLength(0);
  });

  it("Prediction mode: the latest sample of each point in the window, with its date, labelled as same-sample inference in mg/l", async () => {
    render(<App initialTab="prediccion" />);
    const user = userEvent.setup();
    await openDomain(user, /Ríos de Inglaterra/);
    const title = await screen.findByRole("heading", { name: /Última muestra de la ventana/ });
    expect(title).toHaveTextContent("oxígeno disuelto estimado (mg/l), inferencia sobre la misma muestra");
    expect(document.body).not.toHaveTextContent(/\+\s?0\s?h/);
    expect(screen.queryByLabelText("Hora de emisión")).toBeNull();
    await waitFor(() => expect(features().length).toBeGreaterThan(0));
    const december = (s: (typeof fx.water.series)[number]) => s.points.filter((p) => p.issued_at_utc >= "2025-12-01T00:00:00Z" && p.issued_at_utc < "2026-01-01T00:00:00Z");
    await waitFor(() => expect(features().some((f) => f.properties.value !== null)).toBe(true));
    for (const f of features()) {
      const last = december(fx.water.series.find((s) => s.entity_id === f.properties.entity_id)!).at(-1);
      expect(f.properties.value).toBe(last?.prediction ?? null); // the API's prediction, not interpolated, nor an hourly value
    }
    // ONE request for the window (each point's latest sample in it), not one per point and not hourly blocks
    const calls = fake.calls.filter((c) => c.startsWith("/api/v1/predictions?")).map((c) => new URL(c, "http://x").searchParams);
    expect(calls).toHaveLength(1);
    expect([calls[0]!.get("from"), calls[0]!.get("to"), calls[0]!.get("time")]).toEqual(["2025-12-01T00:00:00Z", "2026-01-01T00:00:00Z", null]);
    expect(fake.calls.filter((c) => c.startsWith("/api/v1/series?"))).toHaveLength(0);
    const legend = screen.getByRole("region", { name: /Leyenda: oxígeno disuelto estimado/ });
    expect(legend).toHaveTextContent("inferencia sobre la misma muestra");
    expect(legend).toHaveTextContent("mg/l");
    // the table gives the sample date next to the value, in local time
    const lastSample = december(fx.water.series.find((s) => s.entity_id === fx.WATER_POINT)!).at(-1)!;
    const table = screen.getByRole("table", { name: /Puntos de muestreo/ });
    expect(within(table).getByRole("columnheader", { name: /Muestra \(fecha · observado\)/ })).toBeInTheDocument();
    expect(row(fx.WATER_POINT)).toHaveTextContent(formatShortDate(lastSample.issued_at_utc, "Europe/London"));
    expect(row(fx.WATER_POINT)).toHaveTextContent(`${fmtNum(lastSample.observed!)} mg/l`);
    expect(row(fx.WATER_EMPTY_POINT)).toHaveTextContent("sin observación");
  });

  it("Prediction mode: a point's samples, observed against predicted by sample date", async () => {
    render(<App initialTab="prediccion" />);
    const user = userEvent.setup();
    await openDomain(user, /Ríos de Inglaterra/);
    await waitFor(() => expect(features().length).toBeGreaterThan(0));
    emit("click", { features: [{ properties: { entity_id: fx.WATER_POINT } }] }, "stations-valid");
    const chart = await screen.findByTestId("sample-chart");
    const samples = fx.water.series.find((s) => s.entity_id === fx.WATER_POINT)!.points;
    expect(chart.querySelectorAll("[data-sample]")).toHaveLength(samples.length);
    expect(chart.querySelectorAll("circle.obs")).toHaveLength(samples.filter((p) => p.observed !== null).length);
    expect(chart.querySelectorAll("rect.pred")).toHaveLength(samples.filter((p) => p.prediction !== null).length);
    expect(chart.querySelector("polyline")).toBeNull(); // no line between irregular samples
    expect(chart.querySelector("svg")).toHaveAccessibleName(/oxígeno disuelto observado y predicho por muestra \(mg\/l\)/);
    const dataRows = chart.querySelectorAll("tbody tr");
    expect(dataRows).toHaveLength(samples.length);
    expect(dataRows[0]!.querySelector('[data-raw]')).toHaveAttribute("data-raw", String(samples[0]!.observed));
    expect(chart.querySelectorAll('tr[data-in-window="true"]').length).toBeGreaterThan(0);
    expect(screen.getByTestId("same-sample-note")).toHaveTextContent("inferencia sobre la misma muestra");
    expect(screen.getByRole("heading", { name: /Modelo y evaluación/ })).toBeInTheDocument();
    expect(screen.getByText(/objetivo/)).toHaveTextContent("inferencia sobre la misma muestra");
    expect(document.body).not.toHaveTextContent(/\+\s?0\s?h/);
  });

  it("Rules mode: ¿Por qué aquí? asks for a sample of the point in the window, and traces it", async () => {
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await openDomain(user, /Ríos de Inglaterra/);
    await windowRange();
    emit("click", { features: [{ properties: { entity_id: fx.WATER_POINT } }] }, "stations-valid");
    const picker = await screen.findByRole("region", { name: "Muestra del punto" });
    const trace = fx.water.traces[0]!;
    await waitFor(() => expect(within(picker).getByRole("combobox")).toHaveValue(trace.issued_at_utc));
    const panel = await screen.findByRole("region", { name: "Why here?" });
    expect(await within(panel).findByText(/inferencia sobre la misma muestra/)).toBeInTheDocument();
    expect(panel).toHaveTextContent(`${fmtNum(trace.prediction.value!)} mg/l`);
    expect(fake.calls.some((c) => c.includes("/rule-trace") && c.includes(`at=${encodeURIComponent(trace.issued_at_utc)}`))).toBe(true);
    // the model's own rule text still says "(t+0h)" (published by A4); everything the web words itself does not
    expect(panel.querySelector(".muted")).not.toHaveTextContent(/\+\s?0\s?h/);
  });

  it("Rules mode: a point with no sample in the window says so instead of asking for a trace", async () => {
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await openDomain(user, /Ríos de Inglaterra/);
    await windowRange();
    emit("click", { features: [{ properties: { entity_id: fx.WATER_EMPTY_POINT } }] }, "stations-missing");
    await waitFor(() => expect(screen.getByTestId("no-samples")).toHaveTextContent("no tiene ninguna muestra en la ventana"));
    expect(screen.queryByRole("region", { name: "Why here?" })).toBeNull();
    expect(fake.calls.filter((c) => c.includes("/rule-trace"))).toHaveLength(0);
  });
});
