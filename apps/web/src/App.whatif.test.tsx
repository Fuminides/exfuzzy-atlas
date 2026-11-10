import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ScenarioRequest, ScenarioResponse } from "./api/types";
import { App } from "./App";
import { WHAT_IF_LABEL } from "./components/WhatIfPanel";
import { fake, installApi } from "./test/fakeApi";
import * as fx from "./test/fixtures";
import * as cls from "./test/fixturesClass";
import { scenarioBody, scenarioFor, scenarioGolden, withUnmodelledZones } from "./test/fixturesV04";
import { emit, maps, resetMaps } from "./test/maplibreMock";

vi.mock("maplibre-gl", async () => (await import("./test/maplibreMock")).maplibreFactory());

afterEach(() => vi.unstubAllGlobals());

const SET = { entities: fx.entities, card: fx.card, rules: fx.rules, series: fx.series, traces: fx.traces, ruleMapFor: fx.ruleMapFor };
const stationsData = () => JSON.stringify((maps[maps.length - 1]!.sources["stations"] as { data: unknown }).data);
const input = () => screen.findByRole("spinbutton", { name: /Velocidad del viento/ });
const field = (panel: HTMLElement, feature: string) => panel.querySelector(`li[data-feature="${feature}"]`) as HTMLElement;
const posts = () => fake.posts.filter((p) => p.path === "/scenarios");

/** SYN_A at 07:00 UTC: the row the backend's golden scenario starts from. */
async function openWhatIf() {
  render(<App initialTab="explorar" />);
  const user = userEvent.setup();
  await screen.findByLabelText("Hora de emisión");
  fireEvent.change(screen.getByLabelText("Hora de emisión"), { target: { value: "1" } });
  await waitFor(() => expect(screen.getByTestId("issue-time")).toHaveTextContent("07:00 UTC"));
  await user.click(within(screen.getByRole("table", { name: /Estaciones/ })).getByRole("button", { name: "Synthetic station A (not real)" }));
  const panel = await screen.findByTestId("whatif-panel");
  await within(panel).findByRole("spinbutton", { name: /Velocidad del viento/ }); // the observed row has loaded
  return { user, panel };
}

describe("What-if (E5) on a regressor", () => {
  beforeEach(() => {
    resetMaps();
    installApi({}, { scenarioFor: scenarioFor(SET as never) });
  });

  it("always carries the label, before any edit, and says nothing is written", async () => {
    const { panel } = await openWhatIf();
    expect(within(panel).getByTestId("whatif-label")).toHaveTextContent(WHAT_IF_LABEL);
    expect(WHAT_IF_LABEL).toBe("respuesta del modelo ante entradas modificadas");
    expect(panel).toHaveTextContent("El mapa y el conjunto de datos no cambian");
    expect(within(panel).getByTestId("whatif-idle")).toBeInTheDocument();
    expect(posts()).toHaveLength(0); // nothing is asked until an input changes
  });

  it("offers the model's inputs of the row with their observed value and allowed range", async () => {
    const { panel } = await openWhatIf();
    const wind = field(panel, "wind_speed_t");
    expect(wind).toHaveTextContent("observado: 2,4");
    expect(wind).toHaveTextContent("rango permitido: 0 a 20");
    expect(wind).toHaveAttribute("data-origin", "observed");
    const slider = within(wind).getByRole("slider");
    expect([slider.getAttribute("min"), slider.getAttribute("max")]).toEqual(["0", "20"]);
    expect(within(panel).getByRole("spinbutton", { name: /NO₂ actual/ })).toBeInTheDocument();
  });

  it("POSTs {model_id, entity_id, at, overrides} once the edit settles, and shows the changed memberships, firing, and prediction", async () => {
    const { panel } = await openWhatIf();
    fireEvent.change(await input(), { target: { value: "5" } });
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect(posts()[0]!.body).toEqual({ model_id: fx.rules.model_id, entity_id: "SYN_A", at: "2025-01-15T07:00:00Z", overrides: { wind_speed_t: 5 } } satisfies ScenarioRequest);
    expect(posts()[0]!.body).toEqual(scenarioBody);
    const result = await within(panel).findByTestId("whatif-result");
    // flag and label
    expect(within(panel).getByTestId("whatif-flag")).toHaveTextContent("synthetic_what_if: true");
    expect(within(panel).getByTestId("whatif-label")).toHaveTextContent(WHAT_IF_LABEL);
    // the prediction, original -> scenario with the unit, both from the API
    const pc = scenarioGolden.prediction_change;
    expect(within(panel).getByTestId("whatif-prediction")).toHaveTextContent(/57,52 µg\/m³ → 30,32 µg\/m³/);
    expect(within(panel).getByTestId("whatif-prediction")).toHaveTextContent("−27,201");
    expect(pc.value_delta).toBeCloseTo(-27.2, 1);
    // inputs: observed vs overridden
    const row = within(within(result).getByTestId("whatif-inputs-table")).getByText("Velocidad del viento").closest("tr")!;
    expect(row).toHaveAttribute("data-origin", "overridden");
    expect(row).toHaveTextContent("modificada");
    expect(row).toHaveTextContent("2,4 → 5 m/s");
    const other = within(within(result).getByTestId("whatif-inputs-table")).getByText("NO₂ actual").closest("tr")!;
    expect(other).toHaveAttribute("data-origin", "observed");
    // memberships that change: the wind term of R01 goes from 0.400 to 0.000
    const memberships = within(result).getByTestId("whatif-memberships");
    expect(memberships).toHaveTextContent("R01 · Velocidad del viento es baja");
    expect(memberships).toHaveTextContent("0,400 → 0,000");
    // firing deltas: R01 -0.28, R03 +0.333, R02 unchanged and therefore not listed
    const deltas = within(result).getByTestId("whatif-deltas");
    expect(within(deltas).getByText("R01").closest("tr")).toHaveTextContent("0,280 → 0,000 (−0,280)");
    expect(within(deltas).getByText("R03").closest("tr")).toHaveTextContent("0,000 → 0,333 (+0,333)");
    expect(within(deltas).queryByText("R02")).toBeNull();
    // the field itself shows observed and overridden values
    const li = field(panel, "wind_speed_t");
    expect(li).toHaveAttribute("data-origin", "overridden");
    expect(li).toHaveTextContent("observado: 2,4");
    expect(li).toHaveTextContent("modificado: 5");
  });

  it("never alters the map, the table or the dataset: no other request, same drawn data", async () => {
    const { panel } = await openWhatIf();
    await waitFor(() => expect(stationsData()).toContain('"value":0.28')); // R01 at 07:00 for SYN_A, from /rule-map
    const before = stationsData();
    const requestsBefore = fake.calls.length;
    fireEvent.change(await input(), { target: { value: "5" } });
    await within(panel).findByTestId("whatif-result");
    expect(stationsData()).toBe(before);
    // only the scenario was asked (the POST is not in `calls`' GET list of data views)
    expect(fake.calls.slice(requestsBefore).filter((c) => /rule-map|predictions|observations|rule-territories|series/.test(c))).toEqual([]);
    expect(posts().every((p) => p.path === "/scenarios")).toBe(true);
  });

  it("a slider drag asks only for the settled value (one POST), with the dragged value in overrides", async () => {
    const { panel } = await openWhatIf();
    const slider = within(field(panel, "wind_speed_t")).getByRole("slider");
    for (const v of ["3", "6", "9", "12"]) fireEvent.change(slider, { target: { value: v } });
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect((posts()[0]!.body as ScenarioRequest).overrides).toEqual({ wind_speed_t: 12 });
  });

  it("reset returns to the observed values: clears the field and the result, and the label stays", async () => {
    const { user, panel } = await openWhatIf();
    fireEvent.change(await input(), { target: { value: "5" } });
    await within(panel).findByTestId("whatif-result");
    await user.click(within(panel).getByTestId("whatif-reset"));
    expect(await input()).toHaveValue(null);
    await waitFor(() => expect(within(panel).queryByTestId("whatif-result")).toBeNull());
    expect(within(panel).getByTestId("whatif-idle")).toBeInTheDocument();
    expect(within(panel).getByTestId("whatif-label")).toHaveTextContent(WHAT_IF_LABEL);
    expect(within(panel).getByTestId("whatif-reset")).toBeDisabled();
    expect(field(panel, "wind_speed_t")).toHaveAttribute("data-origin", "observed");
    expect(posts()).toHaveLength(1); // reset asks nothing
  });

  it("a rejected scenario (422) shows the API's reason, keeps the label, and shows no result", async () => {
    const { panel } = await openWhatIf();
    fireEvent.change(await input(), { target: { value: "999" } });
    const alert = await within(panel).findByTestId("whatif-error");
    expect(alert).toHaveAttribute("role", "alert");
    expect(alert).toHaveTextContent("422");
    expect(alert).toHaveTextContent("wind_speed_t=999 fuera del rango [0, 20]");
    expect(within(panel).queryByTestId("whatif-result")).toBeNull();
    expect(within(panel).getByTestId("whatif-label")).toHaveTextContent(WHAT_IF_LABEL);
    // fixing the value recovers
    fireEvent.change(await input(), { target: { value: "5" } });
    expect(await within(panel).findByTestId("whatif-result")).toBeInTheDocument();
    expect(within(panel).queryByTestId("whatif-error")).toBeNull();
  });

  it("starts from scratch when another station or instant is selected (the edits belong to one row)", async () => {
    const { user, panel } = await openWhatIf();
    fireEvent.change(await input(), { target: { value: "5" } });
    await within(panel).findByTestId("whatif-result");
    await user.click(within(screen.getByRole("table", { name: /Estaciones/ })).getByRole("button", { name: "Synthetic station B (not real)" }));
    const next = await screen.findByTestId("whatif-panel");
    expect(next).toHaveTextContent("What-if · Synthetic station B (not real)");
    expect(within(next).queryByTestId("whatif-result")).toBeNull();
    expect(await input()).toHaveValue(null);
  });

  it("is not offered for a station the model has no data for", async () => {
    installApi({}, { entities: withUnmodelledZones(fx.entities, 1) });
    render(<App initialTab="explorar" />);
    await screen.findByRole("region", { name: /Leyenda: activación/ });
    await waitFor(() => expect(maps[maps.length - 1]!.sources["stations"]).toBeDefined());
    emit("click", { features: [{ properties: { entity_id: "U1" } }] }, "stations-valid");
    expect(await screen.findByTestId("unmodelled-notice")).toBeInTheDocument();
    expect(screen.queryByTestId("whatif-panel")).toBeNull();
    expect(fake.calls.some((c) => c.includes("/entities/U1/rule-trace"))).toBe(false);
  });
});

describe("What-if on a winning-rule classifier", () => {
  /** An API-shaped scenario built from the class fixture trace: the class and the winning rule change. */
  const original = cls.trace("E1", "2024-01-06T10:00:00Z");
  const modified = structuredClone(original);
  const first = modified.rules[0]!;
  const winner = modified.rules.find((r) => r.rule_id === original.prediction.winning_rule_id)!;
  first.antecedents[0]!.membership = 0.9;
  first.firing_strength = first.effective_firing = 0.9;
  first.association_degree = 0.5;
  winner.association_degree = 0.01;
  modified.prediction = { ...modified.prediction, label: "low", winning_rule_id: first.rule_id };
  const response: ScenarioResponse = {
    schema_version: "0.4.0",
    data_version: fx.card.data_version,
    synthetic: true,
    model_id: original.model_id,
    entity_id: "E1",
    issued_at_utc: original.issued_at_utc,
    synthetic_what_if: true,
    label: WHAT_IF_LABEL,
    inputs: original.feature_values.map((f) => ({
      feature: f.feature,
      unit: f.unit ?? null,
      origin: f.feature === "y_t" ? ("overridden" as const) : ("observed" as const),
      original_value: f.value,
      scenario_value: f.feature === "y_t" ? 5 : f.value,
      domain: null,
    })),
    original,
    modified,
    rule_deltas: original.rules.map((r, i) => ({
      rule_id: r.rule_id,
      firing_original: r.firing_strength,
      firing_scenario: modified.rules[i]!.firing_strength,
      firing_delta: modified.rules[i]!.firing_strength - r.firing_strength,
      association_original: r.association_degree ?? null,
      association_scenario: modified.rules[i]!.association_degree ?? null,
      association_delta: (modified.rules[i]!.association_degree ?? 0) - (r.association_degree ?? 0),
    })),
    prediction_change: {
      original_value: null,
      scenario_value: null,
      value_delta: null,
      original_label: original.prediction.label ?? null,
      scenario_label: "low",
      label_changed: true,
      original_winning_rule_id: original.prediction.winning_rule_id ?? null,
      scenario_winning_rule_id: first.rule_id,
    },
  };

  beforeEach(() => {
    resetMaps();
    installApi({}, { ...cls.classifierData(), scenarioFor: () => ({ status: 200, body: response }) });
  });

  it("shows the change of class and of winning rule, with association, and keeps the label", async () => {
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await screen.findByRole("region", { name: /Leyenda: activación/ });
    fireEvent.change(screen.getByLabelText("Hora de emisión"), { target: { value: String((Date.parse(original.issued_at_utc) - Date.parse(cls.FIRST_ISSUE)) / 3_600_000) } });
    await waitFor(() => expect(screen.getByTestId("issue-time")).toHaveTextContent("10:00 UTC"));
    await user.click(within(screen.getByRole("table", { name: /Estaciones/ })).getByRole("button", { name: /\bE1\b/ }));
    const panel = await screen.findByTestId("whatif-panel");
    fireEvent.change(await within(panel).findByRole("spinbutton", { name: /Nivel actual/ }), { target: { value: "5" } });
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect((posts()[0]!.body as ScenarioRequest).overrides).toEqual({ y_t: 5 });
    const result = await within(panel).findByTestId("whatif-result");
    const text = within(panel).getByTestId("whatif-prediction");
    expect(text).toHaveTextContent("Categoría: high → low");
    expect(text).toHaveTextContent("la categoría cambia");
    expect(text).toHaveTextContent(`Regla ganadora: ${original.prediction.winning_rule_id} → ${first.rule_id}`);
    expect(text).toHaveTextContent("la regla ganadora cambia");
    expect(within(result).getByRole("columnheader", { name: "Asociación (Δ)" })).toBeInTheDocument();
    expect(within(panel).getByTestId("whatif-label")).toHaveTextContent(WHAT_IF_LABEL);
  });
});
