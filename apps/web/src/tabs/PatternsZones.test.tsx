import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EntityCollection, ModelCard, RuleImportanceResponse } from "../api/types";
import { App } from "../App";
import { setLang } from "../i18n";
import { fake, installApi, type FakeData } from "../test/fakeApi";
import { emit, maps, resetMaps } from "../test/maplibreMock";
import { classifierV05 } from "../test/v05";

vi.mock("maplibre-gl", async () => (await import("../test/maplibreMock")).maplibreFactory());

beforeEach(() => resetMaps());
afterEach(() => {
  vi.unstubAllGlobals();
  setLang("es");
});

type Feature = { properties: { entity_id: string; label: string | null } };
const features = (): Feature[] => (maps[maps.length - 1]!.sources["stations"] as { data: { features: Feature[] } }).data.features;
const labels = () => Object.fromEntries(features().map((f) => [f.properties.entity_id, f.properties.label]));

/**
 * The synthetic classifier with seven stations: E0 without predictions, three "R01" stations and three "R02" ones, so
 * the profiles have something to group. Overall, R01 decides 45 % and R02 55 % (the pooled shares of the six). E1
 * carries a per-station accuracy in the card (80 % against 62 % overall).
 */
function sevenStations(): Partial<FakeData> {
  const base = classifierV05();
  const ents = base.entities as EntityCollection;
  const proto = ents.features[1]!;
  const extra = ["E3", "E4", "E5", "E6"].map((id, i) => ({
    ...proto,
    properties: { ...proto.properties, entity_id: id, name: `Synthetic station ${id} (not real)` },
    geometry: { type: "Point" as const, coordinates: [-3.7 + i * 0.01, 40.4 + i * 0.01] as [number, number] },
  }));
  const imp = base.importance as RuleImportanceResponse;
  const zone = (id: string, a: number, b: number) => ({ entity_id: id, n_predicted: 300, rules: [{ rule_id: "R01", decided_share: a, accuracy: 0.9 }, { rule_id: "R02", decided_share: b, accuracy: 0.8 }] });
  const card = base.card as ModelCard;
  return {
    ...base,
    entities: { ...ents, features: [...ents.features, ...extra] },
    importance: {
      ...imp,
      rules: imp.rules.map((r) => ({ ...r, decided_share: { R01: 0.45, R02: 0.55 }[r.rule_id] ?? 0 })),
      entities: [zone("E1", 0.6, 0.4), zone("E2", 0.3, 0.7), zone("E3", 0.62, 0.38), zone("E4", 0.58, 0.42), zone("E5", 0.28, 0.72), zone("E6", 0.32, 0.68)],
    },
    card: { ...card, metrics: { ...card.metrics!, rows: [...card.metrics!.rows, { estimator: "exfuzzy", metric: "accuracy", value: 0.8, n: 280, slice: "entity=E1" }] } },
  };
}

describe("Por zonas: colouring modes", () => {
  beforeEach(() => installApi({}, sevenStations()));

  it("opens on «Regla característica», switches to «Perfiles» and «Regla que más decide», each with its legend", async () => {
    const user = userEvent.setup();
    render(<App initialTab="patrones" />);
    await waitFor(() => expect(features()).toHaveLength(7));
    const modes = screen.getByRole("group", { name: "Colorear por" });
    expect(within(modes).getByRole("button", { name: "Regla característica" })).toHaveAttribute("aria-pressed", "true");
    // R01 60 % against 45 %: ×1,33; R02 70 % against 55 %: ×1,27; E6, R02 68 %: ×1,24, below 1,25: «sin regla característica»
    expect(labels()).toMatchObject({ E0: null, E1: "R01", E2: "R02", E5: "R02", E6: "__none__" });
    expect(screen.getByTestId("legend-none")).toHaveTextContent(/sin regla característica\s*1/);
    expect(screen.getByTestId("zones-legend")).toHaveTextContent(/al menos el 5\s% y 5 de las predicciones del lugar, y al menos 1,25 veces su parte general/);

    await user.click(within(modes).getByRole("button", { name: "Perfiles" }));
    const legend = screen.getByRole("region", { name: "Leyenda: perfiles de reglas" });
    expect([...legend.querySelectorAll("li[data-profile]")].map((li) => li.textContent)).toEqual(["A más R01 3", "B más R02 3"]);
    expect(legend).toHaveTextContent(/2 perfiles agrupan los lugares/);
    expect(labels()).toMatchObject({ E1: "profile:0", E3: "profile:0", E2: "profile:1", E0: null });
    expect(screen.getByRole("table", { name: /Tabla de estaciones: perfiles/ })).toHaveTextContent("Perfil A · más R01");

    await user.click(within(modes).getByRole("button", { name: "Regla que más decide" }));
    expect(screen.getByRole("region", { name: /Leyenda: regla que más decide/ })).toBeInTheDocument();
    expect(labels()).toMatchObject({ E1: "R01", E2: "R02" });
  });

  it("moves between the modes with the arrow keys", async () => {
    const user = userEvent.setup();
    render(<App initialTab="patrones" />);
    await waitFor(() => expect(features()).toHaveLength(7));
    const first = screen.getByRole("button", { name: "Regla característica" });
    first.focus();
    await user.keyboard("{ArrowRight}");
    const profiles = screen.getByRole("button", { name: "Perfiles" });
    expect(profiles).toHaveAttribute("aria-pressed", "true");
    expect(profiles).toHaveFocus();
    await user.keyboard("{ArrowLeft}{ArrowLeft}");
    expect(screen.getByRole("button", { name: "Regla que más decide" })).toHaveFocus();
  });

  it("never names a probability, a cause or an activation in the default view", async () => {
    render(<App initialTab="patrones" />);
    await waitFor(() => expect(features()).toHaveLength(7));
    const text = document.querySelector(".zones-card")!.textContent ?? "";
    expect(text).not.toMatch(/probabilidad|riesgo|contribuci[oó]n|causa|activaci[oó]n|importancia/i);
  });
});

describe("Por zonas: the station card", () => {
  beforeEach(() => installApi({}, sevenStations()));

  it("opens from the map with its name, figures, profile and what sets it apart", async () => {
    render(<App initialTab="patrones" />);
    await waitFor(() => expect(maps[0]?.layers["stations-valid"]).toBeDefined());
    emit("click", { features: [{ properties: { entity_id: "E1" } }] }, "stations-valid");
    const card = await screen.findByTestId("station-card");
    expect(within(card).getByRole("heading", { level: 4, name: "Synthetic station E1 (not real)" })).toHaveFocus();
    expect(card).toHaveTextContent(/^Estación · E1/);
    await waitFor(() => expect(within(card).getByTestId("station-score")).toHaveTextContent(/Acierto\s*80\s%\s*62\s% en el conjunto/));
    expect(within(card).getByTestId("station-profile")).toHaveTextContent(/Perfil\s*A\s*más R01/);
    expect(card).toHaveTextContent("Qué la distingue");
    expect([...card.querySelectorAll<HTMLElement>("li.sc-rule")].map((l) => l.dataset.rule)).toEqual(["R01"]); // R02 40 % vs 55 %: used less here
    expect(within(card).getAllByTestId("station-rule-sentence")[0]).toHaveTextContent("Si Nivel hace 3 h es baja → low");
    // the predicted mix: each prediction has the class of the rule that decides it
    expect(within(card).getByTestId("station-mix")).toHaveTextContent(/low\s*60\s%/);
    // the card fetched the model card for the score only once a station was clicked
    expect(fake.calls.filter((c) => /\/models\/[^/]+$/.test(c.split("?")[0]!))).toHaveLength(1);
  });

  it("is keyboard accessible: opens from the table, Escape closes it and gives the focus back", async () => {
    const user = userEvent.setup();
    render(<App initialTab="patrones" />);
    await waitFor(() => expect(features()).toHaveLength(7));
    await user.click(screen.getByText("Ver como tabla"));
    const row = screen.getByRole("button", { name: "Synthetic station E2 (not real)" });
    row.focus();
    await user.keyboard("{Enter}");
    const card = await screen.findByTestId("station-card");
    expect(within(card).getByRole("heading", { level: 4 })).toHaveFocus();
    await user.tab();
    expect(within(card).getByRole("button", { name: "Cerrar la ficha de Synthetic station E2 (not real)" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByTestId("station-card")).toBeNull();
    expect(row).toHaveFocus();
  });

  it("«Ver su serie en Predicción» opens Predicción with that station selected", async () => {
    const user = userEvent.setup();
    render(<App initialTab="patrones" />);
    await waitFor(() => expect(maps[0]?.layers["stations-valid"]).toBeDefined());
    emit("click", { features: [{ properties: { entity_id: "E2" } }] }, "stations-valid");
    const open = await screen.findByRole("button", { name: "Ver su serie en Predicción" });
    expect(open.querySelector("em")).toHaveTextContent("Predicción"); // the tab's name is in italics, the button is not a tab
    await user.click(open);
    expect(screen.getByRole("tab", { name: "Predicción" })).toHaveAttribute("aria-selected", "true");
    await waitFor(() => expect(fake.calls.some((c) => c.startsWith("/api/v1/series") && c.includes("entity_id=E2"))).toBe(true));
    await waitFor(() => expect(maps.length).toBe(2)); // Predicción's own map
    await waitFor(() => expect(JSON.stringify(maps[1]!.layers["stations-selected"]?.filter)).toContain('"E2"'));
  });

  it("«Ver en Explorar» opens Explorar with that station selected; another way to a tab selects nothing", async () => {
    const user = userEvent.setup();
    render(<App initialTab="patrones" />);
    await waitFor(() => expect(maps[0]?.layers["stations-valid"]).toBeDefined());
    emit("click", { features: [{ properties: { entity_id: "E5" } }] }, "stations-valid");
    await user.click(await screen.findByRole("button", { name: "Ver en Explorar" }));
    expect(screen.getByRole("tab", { name: "Explorar" })).toHaveAttribute("aria-selected", "true");
    await waitFor(() => expect(maps.length).toBe(2)); // Explorar's own map
    await waitFor(() => expect(JSON.stringify(maps[1]!.layers["stations-selected"]?.filter)).toContain('"E5"'));
    expect(document.querySelector('#tabpanel tr[aria-selected="true"]')).toHaveAttribute("data-entity", "E5");
    const before = maps.length;
    await user.click(screen.getByRole("tab", { name: "Predicción" }));
    await waitFor(() => expect(maps.length > before && maps[maps.length - 1]!.layers["stations-selected"] !== undefined).toBe(true));
    expect(JSON.stringify(maps[maps.length - 1]!.layers["stations-selected"]!.filter)).not.toContain('"E5"');
  });
});

describe("Por zonas in English", () => {
  beforeEach(() => installApi({}, sevenStations()));

  it("names the modes, the legend and the card in English", async () => {
    const user = userEvent.setup();
    render(<App initialLang="en" initialTab="patrones" />);
    await waitFor(() => expect(features()).toHaveLength(7));
    const modes = screen.getByRole("group", { name: "Colour by" });
    expect(within(modes).getAllByRole("button").map((b) => b.textContent)).toEqual(["Characteristic rule", "Profiles", "Rule that decides most"]);
    expect(screen.getByTestId("zones-legend")).toHaveTextContent(/at least 5% and 5 of the place's predictions, and at least 1.25 times its overall share/);
    await user.click(within(modes).getByRole("button", { name: "Profiles" }));
    expect(screen.getByRole("region", { name: "Legend: rule profiles" })).toHaveTextContent(/A more R01 3/);
    emit("click", { features: [{ properties: { entity_id: "E1" } }] }, "stations-valid");
    const card = await screen.findByTestId("station-card");
    expect(card).toHaveTextContent(/^Station · E1/);
    expect(card).toHaveTextContent("What sets it apart");
    await waitFor(() => expect(within(card).getByTestId("station-score")).toHaveTextContent(/Accuracy\s*80%\s*62% everywhere/));
    expect(within(card).getByTestId("station-profile")).toHaveTextContent(/Profile\s*A\s*more R01/);
    expect(within(card).getByRole("button", { name: "Close the card for Synthetic station E1 (not real)" })).toBeInTheDocument();
    expect(card.textContent).not.toMatch(/probabilit|risk|contribut|caus(e|al)|certaint|confiden|activation|importance/i);
    await user.click(within(card).getByRole("button", { name: "See its series in Prediction" }));
    expect(screen.getByRole("tab", { name: "Prediction" })).toHaveAttribute("aria-selected", "true");
  });
});
