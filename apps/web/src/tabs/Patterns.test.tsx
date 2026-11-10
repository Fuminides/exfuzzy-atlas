import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { fake, installApi } from "../test/fakeApi";
import { emit, maps, resetMaps } from "../test/maplibreMock";
import { classifierV05, regressionV05 } from "../test/v05";

vi.mock("maplibre-gl", async () => (await import("../test/maplibreMock")).maplibreFactory());

beforeEach(() => resetMaps());
afterEach(() => vi.unstubAllGlobals());

type Feature = { properties: { entity_id: string; value: number | null; label: string | null; missing_reason: string | null } };
const features = (): Feature[] => (maps[maps.length - 1]!.sources["stations"] as { data: { features: Feature[] } }).data.features;
const cards = () => [...document.querySelectorAll<HTMLElement>("li.rule-card")];

describe("Patrones (classifier)", () => {
  beforeEach(() => installApi({}, classifierV05()));

  it("opens with one title and a sentence: how many rules, what they predict, at which horizon and over which period", async () => {
    render(<App initialTab="patrones" />);
    expect(await screen.findByRole("heading", { level: 1, name: "Patrones: las reglas del modelo" })).toBeInTheDocument();
    const lead = await screen.findByTestId("page-lead");
    await waitFor(() => expect(lead).toHaveTextContent("ordenadas por cuántas predicciones deciden en 2024"));
    expect(lead).toHaveTextContent("Las 4 reglas que usa el modelo para prever");
    expect(lead).toHaveTextContent("a +6 h");
    expect(fake.calls.some((c) => c.endsWith("/importance"))).toBe(true);
  });

  it("writes every rule as a sentence with variable labels, never the feature identifier, ordered by what it decides", async () => {
    render(<App initialTab="patrones" />);
    await screen.findByText("Qué variables intervienen más");
    expect(cards().map((c) => c.dataset.rule)).toEqual(["R01", "R02", "R03", "R04"]);
    const first = within(cards()[0]!).getByTestId("rule-sentence");
    expect(first).toHaveTextContent("Si Nivel hace 3 h es baja → low");
    expect(first.querySelector("strong.var")).toHaveTextContent("Nivel hace 3 h");
    expect(first.querySelector(".class-chip[data-class='low']")).not.toBeNull(); // the consequent is a class chip
    expect(document.body.textContent).not.toMatch(/y_lag3|exo_t|\bIS\b/);
  });

  it("has one metrics row per rule: how much it decides, how often it is right, and how often its class occurs overall", async () => {
    render(<App initialTab="patrones" />);
    await screen.findByText("Qué variables intervienen más");
    const r1 = cards()[0]!;
    expect(r1).toHaveTextContent(/decide el 40\s% de las predicciones/);
    expect(r1).toHaveTextContent(/acierta el 92\s%/);
    expect(r1.querySelector(".rule-bar > span")).toHaveStyle({ width: "40%" });
    // "acierta el 92 %" means little alone: the class the rule predicts occurs in 55 % of the same predictions (v0.5.2 observed_class_shares)
    expect(within(r1).getByTestId("base-rate")).toHaveTextContent(/en general, esa clase se observa en el 55\s% de los casos/);
    // the footnote is a tooltip on the card (a visible line only when many decisions could not be checked)
    expect(within(r1).getByRole("button", { name: /Mostrar en el mapa la regla R01/ })).toHaveAttribute("title", expect.stringContaining("360 de las 400 predicciones que decide"));
    expect(r1).not.toHaveTextContent("Se pudo comprobar");
    expect(cards()[3]).toHaveTextContent("sin observaciones con las que comprobarlo"); // accuracy null: nothing to check, never 0 %
    expect(within(cards()[3]!).queryByTestId("base-rate")).toBeNull();
  });

  it("falls back to Resumen's share of all the observed hours when the importance has no observed_class_shares", async () => {
    const base = classifierV05();
    installApi({}, { ...base, importance: { ...base.importance!, observed_class_shares: null } });
    render(<App initialTab="patrones" />);
    await screen.findByText("Qué variables intervienen más");
    expect(within(cards()[0]!).getByTestId("base-rate")).toHaveTextContent(/en general, esa clase se observa en el 70\s% de las horas/);
  });

  it("shows the share of decisions by variable as horizontal bars, labelled, most used first", async () => {
    render(<App initialTab="patrones" />);
    await screen.findByText("Qué variables intervienen más");
    const bars = screen.getByRole("list", { name: /Parte de las predicciones decididas por reglas que usan cada variable/ });
    const rows = [...bars.querySelectorAll("li")];
    expect(rows.map((r) => r.dataset.feature)).toEqual(["y_t", "y_lag3", "exo_t", "hour"]);
    expect(rows[0]).toHaveTextContent("Nivel actual");
    expect(rows[0]).toHaveTextContent(/80\s%/);
    expect(rows[1]).toHaveTextContent("Nivel hace 3 h");
    expect(document.querySelector<HTMLElement>("li[data-feature='y_t'] .hbar-fill")).toHaveStyle({ width: "80%" });
  });

  it("is honest about the hours with no rule: no prediction", async () => {
    render(<App initialTab="patrones" />);
    const note = await screen.findByTestId("no-rule");
    expect(note).toHaveTextContent(/En el 4,8\s% de las horas con todos los datos de entrada no dispara ninguna regla: el modelo no da predicción/);
  });

  it("expands the terms of a rule with the partitions panel, named by label", async () => {
    render(<App initialTab="patrones" />);
    const user = userEvent.setup();
    await screen.findByText("Qué variables intervienen más");
    await user.click(within(cards()[0]!).getByRole("button", { name: "Ver términos" }));
    const plot = within(cards()[0]!).getByTestId("rule-terms");
    expect(plot).toHaveTextContent("Nivel hace 3 h");
    expect(plot.querySelector("polyline.term--rule")).not.toBeNull(); // the term the rule uses is the thick one
    expect(within(cards()[0]!).queryByRole("region", { name: "Particiones lingüísticas" })).toBeNull(); // inline, not the full panel
    await user.click(within(cards()[0]!).getByRole("button", { name: "Ocultar términos" }));
    expect(within(cards()[0]!).queryByTestId("rule-terms")).toBeNull();
  });

  it("'Por zonas': each station shows its characteristic rule (a category) until a rule is picked, then the share it decides", async () => {
    render(<App initialTab="patrones" />);
    const user = userEvent.setup();
    await waitFor(() => expect(features()).toHaveLength(3));
    // E0 has no predictions in the importance payload: missing, never a rule
    const byId = () => Object.fromEntries(features().map((f) => [f.properties.entity_id, f.properties]));
    expect(byId()["E0"]).toMatchObject({ label: null, value: null, missing_reason: "prediction_unavailable" });
    expect(byId()["E1"]!.label).toBe("R01"); // 60 % here against 40 % overall
    expect(byId()["E2"]!.label).toBe("R02"); // 60 % against 30 %
    expect(screen.getByRole("region", { name: /Leyenda: regla característica/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Regla que más decide" }));
    expect(screen.getByRole("region", { name: /Leyenda: regla que más decide/ })).toBeInTheDocument();
    expect(document.querySelector(".zones-card")).toHaveTextContent("Estaciones con predicciones: 2 de 3");
    // clicking the card picks the rule: the map then shows the share of decided predictions per station
    await user.click(within(cards()[1]!).getByRole("button", { name: /Mostrar en el mapa la regla R02/ }));
    await waitFor(() => expect(byId()["E1"]!.value).toBeCloseTo(0.3, 12)); // R02 decides 30 % of E1's predictions
    expect(byId()["E2"]!.value).toBeCloseTo(0.6, 12);
    expect(byId()["E0"]!.value).toBeNull();
    expect(screen.getByRole("region", { name: /Leyenda: parte de las predicciones que decide la regla R02/ })).toHaveTextContent("Es un recuento de predicciones publicadas");
    expect(cards()[1]).toHaveAttribute("aria-current", "true");
    // and again: the card is released and the map goes back to the rule that decides most
    await user.click(within(cards()[1]!).getByRole("button", { name: /Quitar del mapa la regla R02/ }));
    await waitFor(() => expect(byId()["E1"]!.label).toBe("R01"));
  });

  it("opens a station's card when it is clicked, and has a table alternative with every station", async () => {
    render(<App initialTab="patrones" />);
    await waitFor(() => expect(maps[0]?.layers["stations-valid"]).toBeDefined());
    emit("click", { features: [{ properties: { entity_id: "E1" } }] }, "stations-valid");
    const card = await screen.findByTestId("station-card");
    expect(within(card).getByRole("heading", { level: 4 })).toHaveTextContent("Synthetic station E1 (not real)");
    const list = [...card.querySelectorAll<HTMLElement>("li.sc-rule")];
    expect(list.map((l) => l.dataset.rule)).toEqual(["R01"]); // R02 decides 30 % here and 30 % overall: nothing sets it apart
    expect(within(list[0]!).getByRole("img", { name: /Aquí decide el 60\s% de las predicciones \(180\), frente al 40\s% en el conjunto: 1,5 veces más/ })).toBeInTheDocument();
    expect(card).toHaveTextContent(/Predicciones\s*300/);
    const table = screen.getByRole("table", { name: /Tabla de estaciones/ });
    expect(within(table).getAllByRole("row")).toHaveLength(4);
    expect(within(table).getByRole("row", { name: /E0.*sin predicciones/ })).toBeInTheDocument();
  });
});

describe("Patrones: rules first", () => {
  it("puts the rule cards in the main column before the variables, which are a compact side card", async () => {
    installApi({}, classifierV05());
    render(<App initialTab="patrones" />);
    await screen.findByText("Qué variables intervienen más");
    const main = document.querySelector(".patterns-main")!;
    const aside = document.querySelector(".patterns-aside")!;
    expect(main.querySelector("li.rule-card")).not.toBeNull();
    expect(aside.querySelector("ul.hbars--compact")).not.toBeNull();
    expect(main.compareDocumentPosition(aside) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy(); // rules first in reading order
    expect(aside).toHaveTextContent(/hora/i);
    expect(aside.querySelector("[data-testid=no-rule]")).not.toBeNull(); // the n_no_rule note stays, small
  });

  it("has one slim line of data context from /summary that links to Resumen, and omits it on 404", async () => {
    installApi({}, classifierV05());
    const { unmount } = render(<App initialTab="patrones" />);
    const user = userEvent.setup();
    const line = await screen.findByTestId("data-line");
    expect(line).toHaveTextContent(/Datos: concentración observada, 2 estaciones, 2024 · 70\s% low · 20\s% mid · 10\s% high/);
    await user.click(within(line).getByRole("button", { name: "Ver el resumen de los datos" }));
    expect(screen.getByRole("tab", { name: "Resumen de datos" })).toHaveAttribute("aria-selected", "true");
    unmount();
    resetMaps();
    installApi({}, classifierV05({ summary: false }));
    render(<App initialTab="patrones" />);
    await screen.findByText("Qué variables intervienen más");
    expect(screen.queryByTestId("data-line")).toBeNull();
  });
});

describe("Patrones with withheld predictions (n_withheld)", () => {
  it("says how many hours fire a rule but have no published prediction, next to the hours with no rule, and keeps both out of the figures", async () => {
    const data = classifierV05();
    data.importance = { ...data.importance!, n_withheld: 150 } as typeof data.importance;
    installApi({}, data);
    render(<App initialTab="patrones" />);
    const note = await screen.findByTestId("no-rule");
    expect(note).toHaveTextContent(/En el 4,2\s% de las horas con todos los datos de entrada no dispara ninguna regla/); // 50 of 1,200
    expect(screen.getByTestId("withheld")).toHaveTextContent(/En otro 13\s% sí dispara una regla, pero no se publica predicción/);
  });

  it("shows nothing about withheld hours when there are none", async () => {
    installApi({}, classifierV05());
    render(<App initialTab="patrones" />);
    await screen.findByTestId("no-rule");
    expect(screen.queryByTestId("withheld")).toBeNull();
  });
});

describe("Patrones (additive regression)", () => {
  it("shows the exact weight share and the MAE instead of an accuracy", async () => {
    installApi({}, regressionV05());
    render(<App initialTab="patrones" />);
    await screen.findByText("Qué variables intervienen más");
    const first = cards()[0]!;
    expect(first).toHaveTextContent(/decide el 50\s% de las predicciones · peso medio en la estimación: 50\s%/);
    expect(first).toHaveTextContent(/error medio 2,5\sµg\/m³/);
    expect(first.textContent).not.toMatch(/acierta/);
    expect(first).toHaveTextContent("Si NO₂ actual es alta (inventada) y Velocidad del viento es baja (inventada) → 72 µg/m³");
    expect(screen.getByRole("list", { name: /Cuota media del promedio/ })).toBeInTheDocument();
    expect(screen.getByTestId("page-lead")).toHaveTextContent("para estimar");
  });
});

describe("Patrones not published yet (404)", () => {
  it("lists the rules without numbers, says importance is not available yet, and does not break", async () => {
    installApi({}, classifierV05({ importance: false }));
    render(<App initialTab="patrones" />);
    const notYet = await screen.findAllByTestId("not-yet");
    expect(notYet[0]).toHaveTextContent("Cuánto deciden y aciertan las reglas: no disponible todavía.");
    expect(notYet[1]).toHaveTextContent("El reparto por zonas: no disponible todavía.");
    await waitFor(() => expect(cards()).toHaveLength(4));
    expect(cards().map((c) => c.dataset.rule)).toEqual(["R01", "R02", "R03", "R04"]); // the model's own order
    expect(cards()[0]).toHaveTextContent("Todavía no hay cifras de lo que decide esta regla");
    expect(cards()[0]!.querySelector(".rule-bar")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByTestId("page-lead")).not.toHaveTextContent("ordenadas por");
  });
});

describe("Patrones folds the rules that decide almost nothing", () => {
  it("shows the rules that decide at least 1 % and folds the rest behind a button that says why", async () => {
    const data = classifierV05();
    const imp = data.importance!;
    data.importance = { ...imp, rules: imp.rules.map((r) => (r.rule_id === "R04" ? { ...r, decided_share: 0.004 } : r)) };
    installApi({}, data);
    render(<App initialTab="patrones" />);
    const more = await screen.findByRole("button", { name: "Mostrar 1 regla más (decide menos del 1 % de las predicciones)" });
    expect(cards().map((c) => c.dataset.rule)).toEqual(["R01", "R02", "R03"]);
    await userEvent.setup().click(more);
    expect(cards().map((c) => c.dataset.rule)).toEqual(["R01", "R02", "R03", "R04"]);
    expect(screen.getByRole("button", { name: "Mostrar solo las 3 primeras" })).toBeInTheDocument();
  });

  it("writes the share next to its bar, so the number that ranks the cards is readable", async () => {
    installApi({}, classifierV05());
    render(<App initialTab="patrones" />);
    await waitFor(() => expect(cards()[0]!.querySelector(".rule-share-value")).toHaveTextContent(/^40\s%$/));
  });
});
