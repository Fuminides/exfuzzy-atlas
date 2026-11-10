import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ScenarioResponse } from "./api/types";
import { App } from "./App";
import { UnmodelledNotice } from "./components/UnmodelledNotice";
import { WHAT_IF_LABEL } from "./components/WhatIfPanel";
import { setLang } from "./i18n";
import { articles } from "./lib/domainUi";
import { measureThe } from "./lib/territories";
import { stationTip } from "./lib/stationTip";
import type { StationRow } from "./map/stations";
import { Root } from "./Root";
import { fake, installApi } from "./test/fakeApi";
import * as cls from "./test/fixturesClass";
import { mixtureRules, mixtureTrace, mixtureV07 } from "./test/fixturesMixture";
import { maps, resetMaps } from "./test/maplibreMock";

vi.mock("maplibre-gl", async () => (await import("./test/maplibreMock")).maplibreFactory());

beforeEach(() => resetMaps());
afterEach(() => {
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
  window.history.replaceState({}, "", "/");
  setLang("es");
});

type Feature = { properties: { entity_id: string; label: string | null } };
const features = (): Feature[] => (maps[maps.length - 1]!.sources["stations"] as { data: { features: Feature[] } }).data.features;
/** The winning-rule words a mixture view never uses. */
const WINNING = /decidi[óo]|decidid|ganador|decided|winning|winner/i;
const stationsTable = () => screen.getByRole("table", { name: /Estaciones|Stations/ });

describe("Predicción of a rule mixture: the rule that adds the most, never one that decided", () => {
  it("names the top rule in the table, the colour switch, the map title, the legend and the station detail (ES)", async () => {
    installApi({}, mixtureV07());
    render(<App initialTab="prediccion" />);
    const user = userEvent.setup();
    const group = await screen.findByRole("group", { name: "Colorear el mapa por" });
    expect(within(group).getByRole("button", { name: "regla que más suma" })).toBeInTheDocument();
    expect(within(group).queryByRole("button", { name: /decidió/ })).toBeNull();
    await waitFor(() => expect(features().some((f) => f.properties.label !== null)).toBe(true));
    expect(within(stationsTable()).getByRole("columnheader", { name: "Regla que más suma" })).toBeInTheDocument();
    expect(within(stationsTable()).getAllByText("R01").length).toBeGreaterThan(0);

    await user.click(within(group).getByRole("button", { name: "regla que más suma" }));
    await waitFor(() => expect(features().some((f) => f.properties.label === "R01")).toBe(true)); // coloured by top_rule_id
    expect(screen.getByRole("heading", { level: 2, name: /^Regla que más suma a la categoría prevista:/ })).toBeInTheDocument();
    const legend = screen.getByRole("region", { name: /Leyenda: Regla que más suma a la categoría prevista de cada estación/ });
    expect(legend).toHaveTextContent("ninguna regla decide sola");
    expect(legend).toHaveTextContent("Estaciones con regla que más suma:");
      expect(legend.textContent).not.toMatch(WINNING);

    await user.click(within(stationsTable()).getAllByRole("button")[0]!);
    const detail = await screen.findByTestId("decided-by");
    expect(detail).toHaveTextContent("La regla que más suma: R01");
    expect(within(detail).getByTestId("top-rule-share")).toHaveTextContent(/^R01 es la regla que más suma a .+: el 60 % de lo que suman las reglas que la apoyan\.$/);
    expect(within(detail).getByTestId("rule-sentence")).toHaveTextContent(/→ apoya sobre todo/);
    expect(detail.textContent).not.toMatch(WINNING);
    expect(detail.textContent).not.toMatch(/contribuci/i);
    // the rest of the Predicción view (map frame, table) has no winning-rule wording either
    const mapCol = document.querySelector(".map-col")!;
    expect(mapCol.textContent).not.toMatch(WINNING);
    expect(stationsTable().textContent).not.toMatch(WINNING);
  });

  it("says the same in English", async () => {
    installApi({}, mixtureV07());
    render(<App initialTab="prediccion" initialLang="en" />);
    const user = userEvent.setup();
    const group = await screen.findByRole("group", { name: "Colour the map by" });
    await user.click(within(group).getByRole("button", { name: "rule that adds the most" }));
    await waitFor(() => expect(features().some((f) => f.properties.label === "R01")).toBe(true));
    expect(within(stationsTable()).getByRole("columnheader", { name: "Rule that adds the most" })).toBeInTheDocument();
    const legend = screen.getByRole("region", { name: /Legend: Rule that adds the most to each station's predicted category/ });
    expect(legend).toHaveTextContent("no single rule decides");
    expect(legend.textContent).not.toMatch(WINNING);
    await user.click(within(stationsTable()).getAllByRole("button")[0]!);
    const detail = await screen.findByTestId("decided-by");
    expect(detail).toHaveTextContent("The rule that adds the most: R01");
    expect(within(detail).getByTestId("top-rule-share")).toHaveTextContent(/^R01 adds the most to .+: 60% of what the rules that support it add\.$/);
    expect(detail.textContent).not.toMatch(WINNING);
    expect(detail.textContent).not.toMatch(/caus(e|al)|contribution/i);
  });

  it("keeps «la decidió» for a winning-rule classifier", async () => {
    const { classifierV05 } = await import("./test/v05");
    installApi({}, { ...classifierV05(), decidedBy: "R02" });
    render(<App initialTab="prediccion" />);
    const group = await screen.findByRole("group", { name: "Colorear el mapa por" });
    expect(within(group).getByRole("button", { name: "regla que decidió" })).toBeInTheDocument();
    expect(within(stationsTable()).getByRole("columnheader", { name: "Regla que decidió" })).toBeInTheDocument();
  });

  it("offers no colour switch when no prediction names a top rule", async () => {
    const data = mixtureV07();
    installApi({}, { ...data, topRule: undefined });
    render(<App initialTab="prediccion" />);
    await screen.findByRole("table", { name: /Estaciones/ });
    await waitFor(() => expect(features().some((f) => f.properties.label !== null)).toBe(true));
    expect(screen.queryByRole("group", { name: "Colorear el mapa por" })).toBeNull();
    expect(screen.queryByTestId("decided-by")).toBeNull();
  });
});

describe("stationTip of a mixture", () => {
  const row: StationRow = { entityId: "E1", name: "E1", value: null, label: "high", decidedBy: "R01", missingReason: null, nValid: null, geometry: null };
  const ctx = { mode: "prediction" as const, scheme: cls.rules.target_scheme!, noun: "estación", unit: "", zone: "UTC", territoriesOn: false, terrMeasure: "mean_activation", terrFocus: "all" as const, ruleId: null, territoryOf: () => undefined, observationOf: () => null };

  it("writes «la que más suma», and «la decidió» only for the other families", () => {
    expect(stationTip(row, { ...ctx, mixture: true })).toBe("E1: high · la que más suma: R01");
    expect(stationTip(row, { ...ctx })).toBe("E1: high · la decidió R01");
    setLang("en");
    expect(stationTip(row, { ...ctx, mixture: true })).toBe("E1: high · adds the most: R01");
    expect(stationTip(row, { ...ctx })).toBe("E1: high · decided by R01");
  });
});

describe("Explorar › Territorios of a rule mixture", () => {
  it("disables «Reglas ganadoras» with the reason and never asks for winner_share", async () => {
    installApi({}, mixtureV07());
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await screen.findByRole("region", { name: /Leyenda: activación/ });
    await user.click(screen.getByRole("button", { name: "Territorios" }));
    await screen.findByRole("region", { name: /Leyenda: Territorios de reglas/ });
    const winner = screen.getByRole("radio", { name: /Reglas ganadoras/ });
    expect(winner).toBeDisabled();
    expect(screen.getByTestId("no-winner-share")).toHaveTextContent("ninguna regla decide sola, así que no hay ganadora que contar");
    expect(screen.getByRole("radio", { name: /Activación media/ })).toBeEnabled();
    expect(fake.calls.some((c) => c.includes("winner_share"))).toBe(false);
  });

  it("says it in English", async () => {
    installApi({}, mixtureV07());
    render(<App initialTab="explorar" initialLang="en" />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Territories" }));
    await screen.findByRole("region", { name: /Legend: Rule territories/ });
    expect(screen.getByRole("radio", { name: /Winning rules/ })).toBeDisabled();
    expect(screen.getByTestId("no-winner-share")).toHaveTextContent("no single rule decides, so there is no winner to count");
  });
});

describe("Duelo de reglas of a rule mixture", () => {
  it("compares activations only, and shows each rule as what it supports most, not as a conclusion", async () => {
    installApi({}, mixtureV07());
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("checkbox", { name: /Comparar dos reglas/ }));
    const duel = await screen.findByTestId("rule-duel");
    const sentences = within(duel).getAllByTestId("rule-sentence");
    expect(sentences).toHaveLength(2);
    for (const sentence of sentences) expect(sentence).toHaveTextContent(/→ apoya sobre todo/);
    expect(duel.textContent).not.toMatch(WINNING);
    expect(screen.getByRole("region", { name: "Duelo de reglas" }).textContent).not.toMatch(WINNING);
  });
});

describe("¿Y si…? on a rule mixture", () => {
  const rules = mixtureRules(cls.rules);
  const original = mixtureTrace(cls.trace("E1", "2024-01-06T10:00:00Z"), rules);
  const modified = structuredClone(original);
  modified.prediction = { ...modified.prediction, top_rule_id: "R03" };
  const response: ScenarioResponse = {
    schema_version: "0.7.0",
    data_version: cls.card.data_version,
    synthetic: true,
    model_id: original.model_id,
    entity_id: "E1",
    issued_at_utc: original.issued_at_utc,
    synthetic_what_if: true,
    label: WHAT_IF_LABEL,
    inputs: original.feature_values.map((f) => ({ feature: f.feature, unit: f.unit ?? null, origin: f.feature === "y_t" ? ("overridden" as const) : ("observed" as const), original_value: f.value, scenario_value: f.feature === "y_t" ? 5 : f.value, domain: null })),
    original,
    modified,
    rule_deltas: original.rules.map((r, i) => ({
      rule_id: r.rule_id,
      firing_original: r.firing_strength,
      firing_scenario: modified.rules[i]!.firing_strength,
      firing_delta: modified.rules[i]!.firing_strength - r.firing_strength,
      association_original: null,
      association_scenario: null,
      association_delta: null,
    })),
    prediction_change: {
      original_value: null,
      scenario_value: null,
      value_delta: null,
      original_label: original.prediction.label ?? null,
      scenario_label: original.prediction.label ?? null,
      label_changed: false,
      original_top_rule_id: original.prediction.top_rule_id ?? null,
      scenario_top_rule_id: "R03",
    },
  };

  const open = async (initialLang: "es" | "en" = "es") => {
    const data = mixtureV07();
    installApi({}, { ...data, extra: undefined, scenarioFor: () => ({ status: 200, body: response }) });
    render(<App initialTab="explorar" initialLang={initialLang} />);
    const user = userEvent.setup();
    const en = initialLang === "en";
    await screen.findByLabelText(en ? "Issue time" : "Hora de emisión");
    fireEvent.change(screen.getByLabelText(en ? "Issue time" : "Hora de emisión"), { target: { value: String((Date.parse(original.issued_at_utc) - Date.parse(cls.FIRST_ISSUE)) / 3_600_000) } });
    await waitFor(() => expect(screen.getByTestId("issue-time")).toHaveTextContent("10:00 UTC"));
    await user.click(within(screen.getByRole("table", { name: en ? /Stations/ : /Estaciones/ })).getByRole("button", { name: /\bE1\b/ }));
    const panel = await screen.findByTestId("whatif-panel");
    fireEvent.change((await within(panel).findAllByRole("spinbutton"))[0]!, { target: { value: "5" } });
    return { panel, result: await within(panel).findByTestId("whatif-result") };
  };

  it("shows the top rule before and after, not a winning rule, and no association column", async () => {
    const { panel, result } = await open();
    const text = within(panel).getByTestId("whatif-prediction");
    expect(text).toHaveTextContent(`Regla que más suma: ${original.prediction.top_rule_id} → R03`);
    expect(text).toHaveTextContent("la regla que más suma cambia");
    expect(text.textContent).not.toMatch(WINNING);
    expect(within(result).queryByRole("columnheader", { name: "Asociación (Δ)" })).toBeNull();
    expect(within(panel).getByTestId("whatif-label")).toHaveTextContent(WHAT_IF_LABEL);
  });

  it("says it in English", async () => {
    const { panel } = await open("en");
    const text = within(panel).getByTestId("whatif-prediction");
    expect(text).toHaveTextContent(`Rule that adds the most: ${original.prediction.top_rule_id} → R03`);
    expect(text).toHaveTextContent("the rule that adds the most changes");
    expect(text.textContent).not.toMatch(WINNING);
  });
});

describe("the landing of a rule mixture", () => {
  it("draws the rule that adds the most with top_contributor_share, and no «decide» in the cards", async () => {
    installApi({}, mixtureV07());
    render(<Root initialLang="es" />);
    const arts = await screen.findByTestId("landing-artifacts");
    const rule = await within(arts).findByTestId("landing-rule");
    expect(rule).toHaveTextContent("Regla R01 · la que más suma");
    expect(rule).toHaveTextContent("50 %"); // top_contributor_share of R01 in the fixture
    expect(rule).toHaveTextContent("esta es la regla que más suma a la categoría prevista");
    expect(rule).toHaveTextContent(/apoya sobre todo/);
    expect(rule).toHaveTextContent("acierta el 90 % de esas");
    const map = await within(arts).findByTestId("landing-map").catch(() => null);
    if (map) expect(map).toHaveTextContent("Dónde suma más cada regla");
    const row = await within(arts).findByTestId("landing-row");
    expect(row).toHaveTextContent("apoya sobre todo");
    expect(arts.textContent).not.toMatch(WINNING);
  });

  it("draws no ring when the API gives no top_contributor_share (no number is made up)", async () => {
    const data = mixtureV07();
    const importance = { ...data.importance!, rules: data.importance!.rules.map((r) => ({ ...r, top_contributor_share: null })) };
    installApi({}, { ...data, importance });
    render(<Root initialLang="es" />);
    const rule = await within(await screen.findByTestId("landing-artifacts")).findByTestId("landing-rule");
    expect(rule).toHaveTextContent("la que más suma");
    expect(rule.querySelector(".lp-ring")).toBeNull();
  });

  it("in English", async () => {
    installApi({}, mixtureV07());
    render(<Root initialLang="en" />);
    const rule = await within(await screen.findByTestId("landing-artifacts")).findByTestId("landing-rule");
    expect(rule).toHaveTextContent("Rule R01 · the one that adds the most");
    expect(rule).toHaveTextContent("this is the rule that adds the most to the predicted category");
    expect(rule.textContent).not.toMatch(WINNING);
  });
});

describe("copy: gender of the entity noun and article of the measure name", () => {
  const NOUNS = ["estación", "zona de taxi", "punto de muestreo"];
  const note = (noun: string) => {
    const { container, unmount } = render(<UnmodelledNotice name="X" noun={noun} />);
    const text = container.textContent!;
    unmount();
    return text;
  };

  it("the unmodelled notice agrees with the noun in Spanish", () => {
    expect(note("estación")).toContain("datos para esta estación");
    expect(note("zona de taxi")).toContain("datos para esta zona de taxi");
    expect(note("punto de muestreo")).toContain("datos para este punto de muestreo");
    expect(articles("punto de muestreo").ese).toBe("ese");
    expect(articles("zona de taxi").ese).toBe("esa");
  });

  it("and keeps «this» in English", () => {
    setLang("en");
    for (const n of ["station", "taxi zone", "sampling point"]) expect(note(n)).toContain(`data for this ${n}`);
    expect(NOUNS).toHaveLength(3);
  });

  it("the measure name takes its own article, singular or plural", () => {
    expect(measureThe("mean_activation")).toBe("la activación media");
    expect(measureThe("activation_frequency")).toBe("la frecuencia de activación");
    expect(measureThe("winner_share")).toBe("las reglas ganadoras");
    expect(measureThe("mean_activation", true)).toBe("La activación media");
    expect(measureThe("winner_share", true)).toBe("Las reglas ganadoras");
    setLang("en");
    expect(measureThe("mean_activation")).toBe("the mean activation");
    expect(measureThe("activation_frequency")).toBe("the activation frequency");
    expect(measureThe("winner_share")).toBe("the winning rules");
    expect(measureThe("winner_share", true)).toBe("The winning rules");
  });

  it("no legend, title or tip glues «la» in front of a measure name or an entity noun", async () => {
    // a winning-rule classifier, winner_share on the territories: «según las reglas ganadoras», never «la reglas ganadoras»
    const { classifierV05 } = await import("./test/v05");
    installApi({}, classifierV05());
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await screen.findByRole("region", { name: /Leyenda: activación/ });
    await user.click(screen.getByRole("button", { name: "Territorios" }));
    await user.click(screen.getByRole("radio", { name: /Reglas ganadoras/ }));
    const legend = await screen.findByRole("region", { name: /Leyenda: Territorios de reglas.*reglas ganadoras/ });
    expect(legend.textContent).toMatch(/según las reglas ganadoras/);
    expect(document.body.textContent).not.toMatch(/\bla reglas\b/i);
    expect(screen.getByTestId("territory-overlap")).toHaveTextContent(/en esa estación/);
    act(() => undefined);
  });
});
