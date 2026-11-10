import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { Naming } from "../components/Naming";
import { RuleMatrix } from "../components/RuleMatrix";
import { setLang } from "../i18n";
import { installApi } from "../test/fakeApi";
import { served, servedAsClassifier } from "../test/fixturesPatterns";
import { maps, resetMaps } from "../test/maplibreMock";

vi.mock("maplibre-gl", async () => (await import("../test/maplibreMock")).maplibreFactory());

beforeEach(() => resetMaps());
afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  setLang("es");
});

const cards = () => [...document.querySelectorAll<HTMLElement>("li.rule-card")];
const rowIds = (table: HTMLElement) => within(table).getAllByRole("row").slice(1).map((r) => r.getAttribute("data-rule"));
const headers = (table: HTMLElement) => within(table).getAllByRole("columnheader").map((h) => h.textContent);
const rowOf = (table: HTMLElement, id: string) => table.querySelector<HTMLElement>(`tbody tr[data-rule="${id}"]`)!;
/** What a cell says, leaving out the decoration a screen reader skips (aria-hidden: glyphs, arrow, bars). */
const spoken = (el: Element): string => [...el.childNodes].map((n) => (n.nodeType === Node.TEXT_NODE ? n.textContent : n instanceof Element && n.getAttribute("aria-hidden") !== "true" ? spoken(n) : "")).join("");
const cellTexts = (row: HTMLElement) => within(row).getAllByRole("cell").map((c) => spoken(c).replace(/\s+/g, " ").trim());
type Feature = { properties: { entity_id: string; value: number | null } };
const mapValue = (id: string) => ((maps[maps.length - 1]!.sources["stations"] as { data: { features: Feature[] } }).data.features.find((f) => f.properties.entity_id === id)?.properties.value ?? null);

describe("the rule matrix of Patrones: Madrid +1 h (weighted, 1-2 conditions over 9 inputs)", () => {
  beforeEach(() => installApi({}, servedAsClassifier("madrid_h1")));

  it("is a table before the cards: a row per rule as the cards rank them, a column per used input, then outcome, share and hits", async () => {
    render(<App initialTab="patrones" />);
    const table = await screen.findByRole("table", { name: /Matriz de reglas/ });
    await waitFor(() => expect(rowIds(table)).toEqual(["R01", "R02", "R08", "R07"]));
    expect(rowIds(table)).toEqual(cards().map((c) => c.dataset.rule));
    expect(headers(table)).toEqual(["Regla", "NO₂ hace 1 h (último dato)", "Humedad relativa hace 1 h (%)", "Hora de validez (local)", "Entonces", "Predicciones que decide", "Acierta"]);
    // R02: the term on each input it uses, "no la usa" elsewhere, then what it predicts, its share and its hit rate
    expect(cellTexts(rowOf(table, "R02"))).toEqual(["Razonablemente buena", "humedad alta", "no la usa", "Razonablemente buena", "6,7 %", "67 %"]);
    expect(rowOf(table, "R02").querySelectorAll("svg.rmx-glyph polygon.rmx-glyph-used")).toHaveLength(2);
    // the matrix comes before the list of cards
    const matrixCard = table.closest("section")!;
    expect(matrixCard.compareDocumentPosition(cards()[0]!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(matrixCard).getByRole("heading", { name: "Las reglas de un vistazo" })).toBeInTheDocument();
    expect(matrixCard.textContent).not.toMatch(/importancia|probabilidad|activaci|causa|riesgo|contribuc/i);
  });

  it("hovering or focusing a row writes its sentence; ArrowDown walks the rows; Enter picks the rule on the map and in the cards", async () => {
    render(<App initialTab="patrones" />);
    const user = userEvent.setup();
    const table = await screen.findByRole("table", { name: /Matriz de reglas/ });
    await waitFor(() => expect(maps[maps.length - 1]?.sources["stations"]).toBeDefined());
    await user.hover(rowOf(table, "R02"));
    expect(screen.getByTestId("rule-matrix-sentence")).toHaveTextContent("Si el NO₂ hace 1 h (último dato) es Razonablemente buena y la humedad relativa hace 1 h es alta → Razonablemente buena");
    await user.unhover(rowOf(table, "R02"));
    expect(screen.queryByTestId("rule-matrix-sentence")).toBeNull();

    const r01 = within(table).getByRole("button", { name: /^R01: Si el NO₂ hace 1 h \(último dato\) es Buena → Buena$/ });
    act(() => r01.focus());
    expect(screen.getByTestId("rule-matrix-sentence")).toHaveTextContent("Si el NO₂ hace 1 h (último dato) es Buena → Buena");
    await user.keyboard("{ArrowDown}");
    const r02 = within(table).getByRole("button", { name: /^R02:/ });
    expect(r02).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(r02).toHaveAttribute("aria-pressed", "true");
    expect(rowOf(table, "R02")).toHaveAttribute("aria-current", "true");
    expect(cards()[1]).toHaveAttribute("aria-current", "true"); // the card of R02
    await waitFor(() => expect(mapValue("E1")).toBeCloseTo(0.3, 12)); // the map shows the share R02 decides in each zone
    await user.keyboard("{Enter}"); // again: released everywhere
    expect(r02).toHaveAttribute("aria-pressed", "false");
    expect(cards()[1]).not.toHaveAttribute("aria-current");
  });

  it("clicking a row picks the rule; clicking a card lights its row", async () => {
    render(<App initialTab="patrones" />);
    const user = userEvent.setup();
    const table = await screen.findByRole("table", { name: /Matriz de reglas/ });
    await user.click(within(rowOf(table, "R08")).getAllByRole("cell")[3]!); // anywhere on the row
    expect(cards()[2]).toHaveAttribute("aria-current", "true");
    await user.click(within(cards()[3]!).getByRole("button", { name: /Mostrar en el mapa la regla R07/ }));
    expect(rowOf(table, "R07")).toHaveAttribute("aria-current", "true");
    expect(rowOf(table, "R08")).not.toHaveAttribute("aria-current");
  });

  it("folds the rules under 1 % together with the cards; unfolding adds their columns at the end", async () => {
    render(<App initialTab="patrones" />);
    const user = userEvent.setup();
    const table = await screen.findByRole("table", { name: /Matriz de reglas/ });
    await user.click(screen.getByRole("button", { name: "Ver también las 5 reglas que deciden menos del 1 %" }));
    expect(rowIds(table)).toEqual(["R01", "R02", "R08", "R07", "R04", "R05", "R03", "R06", "R09"]);
    expect(cards()).toHaveLength(9);
    expect(headers(table).slice(1, 5)).toEqual(["NO₂ hace 1 h (último dato)", "Humedad relativa hace 1 h (%)", "Hora de validez (local)", "NO₂ hace 2 h"]);
    await user.click(screen.getByRole("button", { name: "Ocultar las reglas que deciden menos del 1 %" }));
    expect(rowIds(table)).toHaveLength(4);
    expect(cards()).toHaveLength(4);
  });

  it("in English: the same table, the API's English labels, every heading and name in English", async () => {
    render(<App initialLang="en" initialTab="patrones" />);
    const user = userEvent.setup();
    const table = await screen.findByRole("table", { name: /^Rule matrix/ });
    await waitFor(() => expect(rowIds(table)).toEqual(["R01", "R02", "R08", "R07"]));
    expect(headers(table)).toEqual(["Rule", "NO₂ 1 h ago (latest value)", "Relative humidity 1 h ago (%)", "Hour of the valid time (local)", "Then", "Predictions it decides", "Is right"]);
    expect(cellTexts(rowOf(table, "R02"))).toEqual(["Reasonably good", "high humidity", "not used", "Reasonably good", "6.7%", "67%"]);
    const matrixCard = table.closest("section")!;
    expect(within(matrixCard).getByRole("heading", { name: "The rules at a glance" })).toBeInTheDocument();
    await user.hover(rowOf(table, "R02"));
    expect(screen.getByTestId("rule-matrix-sentence")).toHaveTextContent("If NO₂ 1 h ago (latest value) is Reasonably good and relative humidity 1 h ago is high → Reasonably good");
    expect(within(table).getByRole("button", { name: /^R08: If hour of the valid time \(local\) is Evening → Moderate$/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Also show the 5 rules that decide less than 1%" })).toBeInTheDocument();
    expect(matrixCard.textContent).not.toMatch(/importance|probabilit|activation|caus(e|al)|risk|contribution|[áéíóúñ]/i);
  });
});

describe("the rule matrix of Patrones: Madrid +6 h (7 rules of 1 condition, unweighted)", () => {
  beforeEach(() => installApi({}, servedAsClassifier("madrid_h6")));

  it("three rules decide 99 %: two columns, one shaded term per row", async () => {
    render(<App initialTab="patrones" />);
    const table = await screen.findByRole("table", { name: /Matriz de reglas/ });
    await waitFor(() => expect(rowIds(table)).toEqual(["R02", "R03", "R01"]));
    expect(headers(table)).toEqual(["Regla", "NO₂ ayer a la hora de validez", "Viento hace 1 h (m/s)", "Entonces", "Predicciones que decide", "Acierta"]);
    expect(cellTexts(rowOf(table, "R03"))).toEqual(["Razonablemente buena", "no la usa", "Razonablemente buena", "15 %", "43 %"]);
    expect(cellTexts(rowOf(table, "R01"))).toEqual(["no la usa", "Brisa gentil-moderada", "Buena", "3,2 %", "96 %"]);
    for (const id of ["R02", "R03", "R01"]) expect(rowOf(table, id).querySelectorAll(".rmx-glyph-used")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Ver también las 4 reglas que deciden menos del 1 %" })).toBeInTheDocument();
    expect(screen.queryByTestId("rule-matrix-headline")).toBeNull();
    expect(screen.queryByText(/de sus 7 reglas deciden/)).toBeNull();
    expect(screen.getByRole("region", { name: "Las reglas en cifras" }).querySelector(".hero-eyebrow")).toHaveTextContent("Zona de prueba · +6 h · 2025"); // the context line stays
  });

  it("in English", async () => {
    render(<App initialLang="en" initialTab="patrones" />);
    const table = await screen.findByRole("table", { name: /^Rule matrix/ });
    await waitFor(() => expect(rowIds(table)).toEqual(["R02", "R03", "R01"]));
    expect(headers(table)).toEqual(["Rule", "NO₂ yesterday at the valid time", "Wind 1 h ago (m/s)", "Then", "Predictions it decides", "Is right"]);
    expect(cellTexts(rowOf(table, "R01"))).toEqual(["not used", "Gentle to moderate breeze", "Good", "3.2%", "96%"]);
    expect(screen.getByTestId("rule-matrix-key")).toHaveTextContent("the term the rule asks for, inside the variable's range (its other terms in grey)");
    expect(screen.queryByTestId("rule-matrix-headline")).toBeNull();
    expect(screen.queryByText(/of its 7 rules decide/)).toBeNull();
    expect(screen.getByRole("region", { name: "The rules in figures" }).querySelector(".hero-eyebrow")).toHaveTextContent("Zona de prueba · +6 h · 2025");
  });
});

describe("the rule matrix on its own", () => {
  const water = served("water");

  it("the additive regression (Water, 39 rules): the value it gives and the mean error; a detection-limit term is a visible bar", () => {
    render(
      <Naming variables={water.rules.variables} scheme={null}>
        <RuleMatrix model={water.rules} importance={water.importance} scheme={null} regression unit="mg/l" selected={null} onSelect={() => {}} showAll={false} onToggleAll={() => {}} />
      </Naming>,
    );
    const table = screen.getByRole("table", { name: /Matriz de reglas/ });
    expect(rowIds(table)).toHaveLength(14);
    expect(headers(table).slice(-3)).toEqual(["Entonces", "Predicciones que decide", "Error medio (mg/l)"]);
    const r12 = rowOf(table, "R12"); // orthophosphate ≤ detection limit: params [0.01, 0.01, 0.01, 0.01]
    expect(cellTexts(r12)).toContain("ortofosfato en el límite de detección o por debajo");
    expect(r12.querySelector("rect.rmx-glyph-used")).not.toBeNull();
    expect(cellTexts(r12).slice(-3)).toEqual(["14,9 mg/l", "15 %", "0,537"]);
    expect(screen.getByRole("button", { name: "Ver también las 25 reglas que deciden menos del 1 %" })).toBeInTheDocument();
  });

  it("without the importance: model order, no share or hit columns, and the fold says how many rules there are", async () => {
    const nyc = served("nyc_h1");
    const toggle = vi.fn();
    render(
      <Naming variables={nyc.rules.variables} scheme={nyc.rules.target_scheme ?? null}>
        <RuleMatrix model={nyc.rules} importance={null} scheme={nyc.rules.target_scheme ?? null} regression={false} unit="" selected={null} onSelect={() => {}} showAll={false} onToggleAll={toggle} />
      </Naming>,
    );
    const table = screen.getByRole("table", { name: /Matriz de reglas/ });
    expect(rowIds(table)).toEqual(["R01", "R02", "R03", "R04", "R05", "R06", "R07", "R08"]);
    expect(headers(table).slice(-1)).toEqual(["Entonces"]);
    expect(screen.getByTestId("rule-matrix-key")).toHaveTextContent("Columnas: primero la variable que usan más reglas.");
    await userEvent.setup().click(screen.getByRole("button", { name: "Ver las 10 reglas en la matriz" }));
    expect(toggle).toHaveBeenCalledOnce();
  });

  it("Home and End jump to the first and the last row", async () => {
    const de = served("de_h6");
    render(
      <Naming variables={de.rules.variables} scheme={de.rules.target_scheme ?? null}>
        <RuleMatrix model={de.rules} importance={de.importance} scheme={de.rules.target_scheme ?? null} regression={false} unit="" selected={null} onSelect={() => {}} showAll={false} onToggleAll={() => {}} />
      </Naming>,
    );
    const user = userEvent.setup();
    const buttons = within(screen.getByRole("table")).getAllByRole("button");
    act(() => buttons[2]!.focus());
    await user.keyboard("{End}");
    expect(buttons[buttons.length - 1]).toHaveFocus();
    await user.keyboard("{Home}");
    expect(buttons[0]).toHaveFocus();
    await user.keyboard("{ArrowUp}"); // stays on the first
    expect(buttons[0]).toHaveFocus();
  });
});
