import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { whatIfLabel } from "./components/WhatIfPanel";
import { setLang } from "./i18n";
import { installApi } from "./test/fakeApi";
import * as fx from "./test/fixtures";
import { scenarioFor, storiesGolden } from "./test/fixturesV04";
import { resetMaps } from "./test/maplibreMock";
import { classifierV05 } from "./test/v05";

vi.mock("maplibre-gl", async () => (await import("./test/maplibreMock")).maplibreFactory());
// As in App.data/App.whatif: Explorar stays at the fixture's first issue time (the opening probe has its own tests).
vi.mock("./hooks/defaultTimeScores", async (orig) => ({ ...(await orig<typeof import("./hooks/defaultTimeScores")>()), firingScore: () => async () => null }));

beforeEach(() => resetMaps());
afterEach(() => {
  vi.unstubAllGlobals();
  setLang("es");
});

/** The English mirror of App.wording's guard: a firing, an association or a weight is never any of these. */
const FORBIDDEN = /probabilit|risk|contribut|caus(e|al)|certaint|confiden/gi;
/** Every forbidden word that appears is denied, as the Spanish "no es una probabilidad" ("not a probability"). */
const deniedOnly = (text: string) => {
  // the basemap credit ("© OpenStreetMap contributors") is attribution, not a claim about the model
  const flat = text.replace(/\s+/g, " ").replace(/OpenStreetMap contributors/g, "OpenStreetMap");
  for (const m of flat.matchAll(FORBIDDEN)) expect(flat.slice(Math.max(0, m.index! - 60), m.index), `«${m[0]}» in «${flat.slice(Math.max(0, m.index! - 60), m.index! + 30)}»`).toMatch(/\b(not|nor|no|never|neither)\b/i);
};
const main = () => document.querySelector("main")!.textContent ?? "";
const stationButton = (entity: string) => document.querySelector<HTMLButtonElement>(`table.stations tr[data-entity="${entity}"] button`)!;
const SET = { entities: fx.entities, card: fx.card, rules: fx.rules, series: fx.series, traces: fx.traces, ruleMapFor: fx.ruleMapFor };

async function openExplore() {
  render(<App initialLang="en" initialTab="explorar" />);
  await screen.findByRole("heading", { name: /^Rule R\d+: / }, { timeout: 4000 });
  return userEvent.setup();
}

describe("Predicción in English", () => {
  it("map, legend and time controls are in English, and the redesigned parts never call anything a probability or a risk", async () => {
    installApi({}, classifierV05());
    render(<App initialLang="en" initialTab="prediccion" />);
    await screen.findByTestId("report-link");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(/^Prediction:/);
    expect(screen.getByRole("button", { name: "See the performance report" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: /^Model prediction: / })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Map" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Side panel" })).toBeInTheDocument();
    expect(screen.getByLabelText("Issue time")).toBeInTheDocument();
    // what App.wording owns on this tab, in English
    const owned = ["header.page-head", ".horizon-box", ".accuracy"].map((s) => document.querySelector(s)?.textContent ?? "").join(" ");
    expect(owned.length).toBeGreaterThan(200);
    expect(owned).not.toMatch(FORBIDDEN);
    expect(owned).not.toMatch(/activation/i); // activation belongs to Explorar
    expect(owned).not.toMatch(/[áéíóúñ¿¡]/);
  });

  it("the regressor's map, the What-if entry and its panel speak English", async () => {
    installApi({}, { scenarioFor: scenarioFor(SET as never) });
    render(<App initialLang="en" initialTab="prediccion" />);
    const user = userEvent.setup();
    await screen.findByLabelText("Issue time");
    fireEvent.change(screen.getByLabelText("Issue time"), { target: { value: "1" } });
    await waitFor(() => expect(screen.getByTestId("issue-time")).toHaveTextContent("07:00 UTC"));
    expect(await screen.findByRole("heading", { name: "Predicted NO₂ (µg/m³)" })).toBeInTheDocument();
    await user.click(stationButton("SYN_A"));
    expect(await screen.findByRole("button", { name: "What if…?" })).toBeInTheDocument();
    expect(screen.getByTestId("whatif-entry")).toHaveTextContent("the model's answer to hypothetical inputs");
    await user.click(screen.getByRole("button", { name: "What if…?" }));
    const panel = await screen.findByTestId("whatif-panel");
    expect(within(panel).getByTestId("whatif-label")).toHaveTextContent("the model's response to modified inputs");
    deniedOnly(main());
  });
});

describe("Explorar in English", () => {
  it("rules on the map: the lead labels activation as what it is, and 'importance' only appears to deny it", async () => {
    installApi({}, classifierV05());
    render(<App initialLang="en" initialTab="explorar" />);
    const lead = await screen.findByTestId("page-lead");
    expect(lead).toHaveTextContent("The activation (0–1)");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(/^Explore /);
    const view = screen.getByRole("group", { name: "View" });
    expect(within(view).getAllByRole("button").map((b) => b.textContent)).toEqual(["Rules on the map", "Observed data"]);
    await screen.findByRole("heading", { name: /^Rule R\d+: / }, { timeout: 4000 });
    expect(screen.getByRole("button", { name: "Territories" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Skip to the timeline" })).toBeInTheDocument();
    const text = main().replace(/\s+/g, " ");
    for (const m of text.matchAll(/importance/gi)) expect(text.slice(Math.max(0, m.index! - 45), m.index)).toMatch(/\b(not|nor|never)\b/i);
    deniedOnly(text);
  });

  it("observed data: heading, legend and side panel in English", async () => {
    installApi();
    const user = await openExplore();
    await user.click(screen.getByRole("button", { name: "Observed data" }));
    expect(await screen.findByRole("heading", { name: "Observed data: NO₂ measured at the valid time (issue + 6 h) (µg/m³)" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Data mode" })).toHaveTextContent("A gap shows as “no data” with its reason");
    expect(screen.getByTestId("page-lead")).toHaveTextContent("as they were published");
    expect(await screen.findByRole("heading", { name: "Observed NO₂ (µg/m³)" })).toBeInTheDocument();
    deniedOnly(main());
  });

  it("territories: the map heading names the dominant rule and the measure in English", async () => {
    installApi();
    const user = await openExplore();
    await user.click(screen.getByRole("button", { name: "Territories" }));
    expect((await screen.findAllByRole("heading", { name: /^Rule territories: dominant rule per .+ by mean activation/ })).length).toBeGreaterThan(0);
    deniedOnly(main());
  });

  it("rule duel: the controls and the duel heading are in English", async () => {
    installApi();
    const user = await openExplore();
    const box = screen.getByRole("region", { name: "Rule duel" });
    await user.click(within(box).getByRole("checkbox", { name: "Compare two rules (A and B)" }));
    await screen.findByTestId("rule-duel");
    expect(screen.getByRole("heading", { name: /^Duel: rule R\d+ \(A\) vs rule R\d+ \(B\): / })).toBeInTheDocument();
    expect(within(box).getByRole("radio", { name: "Activation difference (A − B)" })).toBeInTheDocument();
    deniedOnly(main());
  });

  it("stories: the API's sentences as sent, the web's own text in English", async () => {
    installApi({}, { stories: () => storiesGolden });
    const user = await openExplore();
    await user.click(screen.getByRole("button", { name: "Stories" }));
    const replay = await screen.findAllByTestId("story-reproduce");
    expect(replay[0]).toHaveTextContent("Replay");
    const box = screen.getByRole("region", { name: "Rule stories" });
    expect(box).toHaveTextContent(`${storiesGolden.stories.length} of ${storiesGolden.n_candidates} candidate stories`);
    for (const s of storiesGolden.stories) expect(within(box).getByText(s.text, { exact: true })).toBeInTheDocument();
  });

  it("what-if: the label in English from the first render", async () => {
    installApi({}, { scenarioFor: scenarioFor(SET as never) });
    const user = await openExplore();
    fireEvent.change(screen.getByLabelText("Issue time"), { target: { value: "1" } });
    await waitFor(() => expect(screen.getByTestId("issue-time")).toHaveTextContent("07:00 UTC"));
    await user.click(stationButton("SYN_A"));
    const panel = await screen.findByTestId("whatif-panel");
    expect(within(panel).getByTestId("whatif-label")).toHaveTextContent(whatIfLabel());
    expect(whatIfLabel()).toBe("the model's response to modified inputs");
    expect(panel).toHaveTextContent("The map and the dataset stay as they are");
    expect(await screen.findByRole("region", { name: "Why here?" })).toBeInTheDocument();
    deniedOnly(main());
  });
});
