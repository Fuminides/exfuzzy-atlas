import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { setLang } from "../i18n";
import { emit, resetMaps } from "../test/maplibreMock";
import { fake, installApi } from "../test/fakeApi";
import { classifierV05, regressionV05 } from "../test/v05";

vi.mock("maplibre-gl", async () => (await import("../test/maplibreMock")).maplibreFactory());

beforeEach(() => resetMaps());
afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  setLang("es");
});

const cards = () => [...document.querySelectorAll<HTMLElement>("li.rule-card")];
const ready = () => screen.findByText("Which variables take part most");

/** Patterns in English: the same page, every sentence written whole in English; labels from the API stay as sent. */
describe("Patterns in English (classifier)", () => {
  beforeEach(() => installApi({}, classifierV05()));

  it("opens with the English title and lead: how many rules, what they predict, the horizon and the period", async () => {
    render(<App initialLang="en" initialTab="patrones" />);
    expect(await screen.findByRole("heading", { level: 1, name: "Patterns: the model's rules" })).toBeInTheDocument();
    const lead = screen.getByTestId("page-lead");
    await waitFor(() => expect(lead).toHaveTextContent("ordered by how many predictions they decide in 2024"));
    expect(lead).toHaveTextContent("The 4 rules the model uses to predict");
    expect(lead).toHaveTextContent("at +6 h");
  });

  it("writes the rules as English sentences around the model's own labels, with English numbers", async () => {
    render(<App initialLang="en" initialTab="patrones" />);
    await ready();
    const r1 = cards()[0]!;
    // "Nivel hace 3 h" and the class "low" are the API's labels (data, without *_en here); the generic term Low is the web's
    expect(within(r1).getByTestId("rule-sentence")).toHaveTextContent("If Nivel hace 3 h is low → low");
    expect(r1).toHaveTextContent("decides 40% of the predictions");
    expect(r1).toHaveTextContent("is right 92% of the time");
    expect(within(r1).getByTestId("base-rate")).toHaveTextContent("overall, that class is observed in 55% of the cases");
    expect(within(r1).getByRole("button", { name: "Show rule R01 on the map" })).toHaveAttribute("title", expect.stringContaining("360 of the 400 predictions it decides"));
    expect(cards()[3]).toHaveTextContent("no observations to check it against");
    expect(within(r1).getByRole("button", { name: "Show terms" })).toBeInTheDocument();
  });

  it("explains the variables, the hours with no rule and how it is measured in English", async () => {
    render(<App initialLang="en" initialTab="patrones" />);
    await ready();
    expect(screen.getByRole("list", { name: "Share of the predictions decided by rules that use each variable" })).toBeInTheDocument();
    expect(screen.getByTestId("no-rule")).toHaveTextContent("In 4.8% of the hours with complete input data, no rule fires: the model gives no prediction.");
    expect(screen.getByText("How it is measured")).toBeInTheDocument();
    expect(screen.getByTestId("data-line")).toHaveTextContent(/^Data: concentración observada, 2 stations, 2024 · 70% low · 20% mid · 10% high/);
    expect(screen.getByRole("button", { name: "See the data summary" })).toBeInTheDocument();
  });

  it("'By zone' speaks English: legend, count, a station's rules and the table", async () => {
    const user = userEvent.setup();
    render(<App initialLang="en" initialTab="patrones" />);
    await ready();
    expect(screen.getByRole("heading", { name: "By zone" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Legend: characteristic rule of each zone" })).toBeInTheDocument();
    expect(document.querySelector(".zones-card")).toHaveTextContent("Stations with predictions: 2 of 3");
    await user.click(within(cards()[1]!).getByRole("button", { name: "Show rule R02 on the map" }));
    expect(screen.getByRole("heading", { name: "Where R02 decides" })).toBeInTheDocument();
    // the negation names the same word the Spanish denies
    expect(screen.getByRole("region", { name: "Legend: share of the predictions that rule R02 decides" })).toHaveTextContent("It is a count of published predictions");
    await user.click(within(cards()[1]!).getByRole("button", { name: "Remove rule R02 from the map" }));
    emit("click", { features: [{ properties: { entity_id: "E1" } }] }, "stations-valid");
    const card = await screen.findByTestId("station-card");
    expect(card).toHaveTextContent("What sets it apart");
    expect(within(card).getByRole("img", { name: "Here it decides 60% of the predictions (180), compared with 40% across all of them: 1.5 times as much." })).toBeInTheDocument();
    const table = screen.getByRole("table", { name: /Table of stations: characteristic rule/ });
    expect(within(table).getByRole("row", { name: /E0.*no predictions/ })).toBeInTheDocument();
  });

  it("no longer carries the comparison with the baselines: it is in the performance report", async () => {
    render(<App initialLang="en" initialTab="patrones" />);
    await ready();
    expect(screen.queryByTestId("perf-bars")).toBeNull();
    expect(screen.queryByRole("heading", { name: "The whole model, against others" })).toBeNull();
  });
});

describe("Patterns in English (regression, folding, not published)", () => {
  it("regression: estimate, weight share and mean error", async () => {
    installApi({}, regressionV05());
    render(<App initialLang="en" initialTab="patrones" />);
    await ready();
    expect(cards()[0]).toHaveTextContent("decides 50% of the predictions · mean weight in the estimate: 50%");
    expect(cards()[0]).toHaveTextContent(/mean error 2\.5\sµg\/m³/);
    expect(screen.getByTestId("page-lead")).toHaveTextContent("to estimate");
    expect(screen.getByRole("list", { name: "Mean share of the average carried by the rules that use each variable" })).toBeInTheDocument();
  });

  it("folds the rules that decide less than 1% behind an English button", async () => {
    const data = classifierV05();
    const imp = data.importance!;
    data.importance = { ...imp, rules: imp.rules.map((r) => (r.rule_id === "R04" ? { ...r, decided_share: 0.004 } : r)) };
    installApi({}, data);
    render(<App initialLang="en" initialTab="patrones" />);
    const more = await screen.findByRole("button", { name: "Show 1 more rule (it decides less than 1% of the predictions)" });
    await userEvent.setup().click(more);
    expect(screen.getByRole("button", { name: "Show only the first 3" })).toBeInTheDocument();
  });

  it("importance not published: says so in English", async () => {
    installApi({}, classifierV05({ importance: false }));
    render(<App initialLang="en" initialTab="patrones" />);
    const notYet = await screen.findAllByTestId("not-yet");
    expect(notYet[0]).toHaveTextContent("How much the rules decide and how often they are right: not available yet.");
    expect(notYet[1]).toHaveTextContent("The breakdown by zone: not available yet.");
    await waitFor(() => expect(cards()).toHaveLength(4));
    expect(cards()[0]).toHaveTextContent("There are no figures yet for what this rule decides.");
    expect(fake.calls.some((c) => c.endsWith("/importance"))).toBe(true);
  });
});
