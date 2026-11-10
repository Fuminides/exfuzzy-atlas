import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { fake, installApi } from "../test/fakeApi";
import { classifiedSummary } from "../test/fixturesV05";
import * as cls from "../test/fixturesClass";
import { emit, maps, resetMaps } from "../test/maplibreMock";
import { classifierV05, regressionV05 } from "../test/v05";

vi.mock("maplibre-gl", async () => (await import("../test/maplibreMock")).maplibreFactory());

beforeEach(() => resetMaps());
afterEach(() => vi.unstubAllGlobals());

type Feature = { properties: { entity_id: string; value: number | null; missing_reason: string | null } };
const features = (): Feature[] => (maps[maps.length - 1]!.sources["stations"] as { data: { features: Feature[] } }).data.features;

describe("Resumen (classified variable)", () => {
  beforeEach(() => installApi({}, classifierV05()));

  it("has one title and one plain sentence about what is seen and when", async () => {
    render(<App initialTab="resumen" />);
    expect(await screen.findByRole("heading", { level: 1, name: "Resumen de datos: Zona de prueba" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Resumen de datos" })).toHaveAttribute("aria-selected", "true");
    const lead = screen.getByTestId("page-lead");
    expect(lead).toHaveTextContent("Estás viendo concentración observada en Zona de prueba");
    expect(lead).toHaveTextContent("1 de enero de 2024 – 31 de diciembre de 2024");
    expect(lead).toHaveTextContent("2 estaciones"); // the third station has no observations
    expect(lead).toHaveTextContent("sin ningún modelo detrás. Aquí no hay predicciones");
    expect(fake.calls.some((c) => c.startsWith("/api/v1/summary?task_id="))).toBe(true);
  });

  it("states the data in one quiet strip: a line of small facts and a thin stacked bar in the class colours, every segment written out", async () => {
    render(<App initialTab="resumen" />);
    const strip = await screen.findByRole("region", { name: "Qué hay en los datos" });
    const facts = within(strip).getByTestId("data-facts");
    expect(facts).toHaveTextContent("Zona de prueba");
    expect(facts).toHaveTextContent("Concentración observada");
    expect(facts).toHaveTextContent("2 de 3 estaciones");
    expect(facts).toHaveTextContent("1000 observaciones");
    expect(strip.querySelector(".dist-seg-text")).toBeNull(); // no big numbers inside the bar
    const bar = within(strip).getByRole("img", { name: /Todas las observaciones de Zona de prueba: 70\s% low · 20\s% mid · 10\s% high/ });
    const segs = [...bar.querySelectorAll<HTMLElement>(".dist-seg")];
    expect(segs.map((s) => s.dataset.class)).toEqual(["low", "mid", "high"]);
    expect(segs.map((s) => s.style.background)).toEqual(cls.scheme.classes.map(() => expect.stringMatching(/rgb|#/)));
    expect(segs.map((s) => Number(s.dataset.share))).toEqual([0.7, 0.2, 0.1].map((v) => expect.closeTo(v, 12)));
    expect(within(strip).getByText(/^70\s%$/, { selector: "strong" })).toBeInTheDocument();
    expect(document.querySelector(".facts")).toBeNull(); // the big KPI grid is gone
  });

  it("colours the stations by the share of hours in the worse classes and keeps a station with no data as missing, not 0", async () => {
    render(<App initialTab="resumen" />);
    await screen.findByRole("region", { name: /Dónde hay más horas en «mid o peor»/ });
    await waitFor(() => expect(features()).toHaveLength(3));
    const byId = Object.fromEntries(features().map((f) => [f.properties.entity_id, f.properties]));
    expect(byId["E1"]!.value).toBeCloseTo(0.5, 12); // 0.2 (mid) + 0.3 (high)
    expect(byId["E2"]!.value).toBeCloseTo(0.4, 12);
    expect(byId["E0"]!.value).toBeNull();
    expect(byId["E0"]!.missing_reason).toBe("no_observation");
    const legend = screen.getByRole("region", { name: /Leyenda: Horas en «mid o peor»/ });
    expect(legend).toHaveTextContent("Estaciones con datos: 2 de 3");
    expect(legend).toHaveTextContent("sin observaciones en esta estación (anillo hueco)");
  });

  it("ranks the stations in a table (the alternative to the map) with all of them, and 'sin datos' last", async () => {
    render(<App initialTab="resumen" />);
    const table = await screen.findByRole("table", { name: /Ranking de estaciones/ });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("Synthetic station E1");
    expect(rows[0]).toHaveTextContent(/50\s%/);
    expect(rows[1]).toHaveTextContent(/40\s%/);
    expect(rows[2]).toHaveTextContent("sin datos");
  });

  it("opens a station's own distribution from the map or the table", async () => {
    render(<App initialTab="resumen" />);
    const user = userEvent.setup();
    await waitFor(() => expect(maps[0]?.layers["stations-valid"]).toBeDefined());
    emit("click", { features: [{ properties: { entity_id: "E2" } }] }, "stations-valid");
    const card = await screen.findByRole("region", { name: "Synthetic station E2 (not real)" });
    expect(within(card).getByRole("img", { name: /Synthetic station E2.*: 60\s% low · 20\s% mid · 20\s% high/ })).toBeInTheDocument();
    expect(card).toHaveTextContent("300 observaciones");
    await user.click(within(screen.getByRole("table", { name: /Ranking/ })).getByRole("button", { name: "Synthetic station E0 (not real)" }));
    expect(await screen.findByRole("region", { name: "Synthetic station E0 (not real)" })).toHaveTextContent("no tiene observaciones en el periodo");
  });

  it("draws the trend by year, month, hour and weekday, with gaps labelled and few observations flagged", async () => {
    render(<App initialTab="resumen" />);
    for (const title of ["Por año", "Por mes", "Por hora del día", "Por día de la semana"]) expect(await screen.findByRole("heading", { name: title })).toBeInTheDocument();
    const month = screen.getByRole("img", { name: /Por mes: Horas en «mid o peor»\. 2 de 12 grupos con datos/ });
    expect(month.querySelectorAll("rect.bar")).toHaveLength(2); // January and March
    expect(month.querySelectorAll("rect.gap-mark").length).toBe(10); // the other ten months have no data: a gap, not a zero
    const table = month.closest(".card")!.querySelector("table")!;
    expect(within(table).getByRole("row", { name: /feb\s+sin datos/ })).toBeInTheDocument();
    expect(within(table).getByRole("row", { name: /mar.*20 \(pocas\)/ })).toBeInTheDocument();
  });
});

describe("Resumen (numeric variable)", () => {
  it("colours by the median, labels the unit and writes median and spread out", async () => {
    installApi({}, regressionV05());
    render(<App initialTab="resumen" />);
    await screen.findByRole("heading", { level: 1, name: /^Resumen de/ });
    await waitFor(() => expect(features()).toHaveLength(4));
    const byId = Object.fromEntries(features().map((f) => [f.properties.entity_id, f.properties.value]));
    expect(byId).toEqual({ SYN_A: null, SYN_B: 20, SYN_C: 30, SYN_D: 40 });
    expect(await screen.findByRole("region", { name: /Leyenda: Mediana de NO₂ horario observado/ })).toHaveTextContent("Estaciones con datos: 3 de 4");
    const headline = screen.getByRole("region", { name: "Qué hay en los datos" });
    expect(headline).toHaveTextContent(/Mediana 30\sµg\/m³/);
    expect(headline).toHaveTextContent(/la mitad de los valores entre 27 y 33\sµg\/m³/);
    const table = screen.getByRole("table", { name: /Ranking de estaciones/ });
    expect(within(table).getAllByRole("row")[1]).toHaveTextContent(/40,0\sµg\/m³/);
  });
});

describe("Resumen not published yet (404)", () => {
  it("says 'no disponible todavía' without an error or an empty chart, and the other tabs still work", async () => {
    installApi({}, classifierV05({ summary: false }));
    render(<App initialTab="resumen" />);
    const notYet = await screen.findByTestId("not-yet");
    expect(notYet).toHaveTextContent("El resumen de los datos: no disponible todavía.");
    expect([...notYet.querySelectorAll("em")].map((e) => e.textContent)).toEqual(["Patrones", "Predicción", "Explorar"]); // tab names in prose are in italics
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryAllByRole("img").filter((i) => !i.closest(".site-credits"))).toHaveLength(0); // the licence logo in the credits is not a chart
    await userEvent.setup().click(screen.getByRole("tab", { name: "Patrones" }));
    expect(await screen.findByRole("heading", { level: 1, name: /Patrones/ })).toBeInTheDocument();
    expect(screen.queryByTestId("data-line")).toBeNull(); // 404: the data line is omitted, nothing says "no disponible" there
  });

  it("a server error is still an error with a retry", async () => {
    installApi({ "/summary": () => Promise.resolve(new Response(JSON.stringify({ detail: "boom" }), { status: 500 })) }, classifierV05());
    render(<App initialTab="resumen" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudo cargar el resumen");
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeInTheDocument();
  });
});

it("the summary payload of a fixture is consistent with the contract (shares add up to 1)", () => {
  const s = classifiedSummary(cls.rules, cls.entities, "t");
  for (const rows of Object.values(s.groups)) for (const r of rows) if (r.n) expect(r.shares!.reduce((a, b) => a + b, 0)).toBeCloseTo(1, 9);
});
