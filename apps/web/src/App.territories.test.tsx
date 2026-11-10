import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RuleTerritoriesResponse } from "./api/types";
import { App } from "./App";
import { VIRIDIS } from "./lib/colorScale";
import { fmt } from "./lib/format";
import { DIMMED_RULE, RULE_PALETTE } from "./lib/territories";
import { fake, installApi, territoriesFor } from "./test/fakeApi";
import * as fx from "./test/fixtures";
import * as cls from "./test/fixturesClass";
import { withUnmodelledZones } from "./test/fixturesV04";
import { maps, resetMaps } from "./test/maplibreMock";

vi.mock("maplibre-gl", async () => (await import("./test/maplibreMock")).maplibreFactory());

afterEach(() => vi.unstubAllGlobals());

type Feature = { properties: { entity_id: string; value: number | null; label: string | null; missing_reason: string | null } };
const features = (): Feature[] => (maps[maps.length - 1]!.sources["stations"] as { data: { features: Feature[] } }).data.features;
const calls = (endpoint: string) => fake.calls.filter((c) => c.startsWith(`/api/v1${endpoint}?`)).map((c) => new URL(c, "http://x").searchParams);
const colorOf = (rule: string) => RULE_PALETTE[Number(rule.slice(1)) - 1]!;
const matchColors = () => {
  const paint = maps[maps.length - 1]!.layers["stations-valid"]!.paint!["circle-color"] as unknown[];
  const out = new Map<string, string>();
  for (let i = 2; i + 1 < paint.length - 1; i += 2) out.set(paint[i] as string, paint[i + 1] as string);
  return out;
};
/** What the fake API answers for a territories request (the web never recomputes it). */
const expected = (set: Parameters<typeof territoriesFor>[0], q: Record<string, string>) =>
  territoriesFor(set, new URLSearchParams(q)).body as RuleTerritoriesResponse;
const WEEK = { from: "2025-01-13T00:00:00Z", to: "2025-01-20T00:00:00Z" };
const SET = { entities: fx.entities, card: fx.card, rules: fx.rules, series: fx.series, traces: fx.traces, ruleMapFor: fx.ruleMapFor };

const openTerritories = async (user: ReturnType<typeof userEvent.setup>) => {
  render(<App initialTab="explorar" />);
  await screen.findByRole("region", { name: /Leyenda: activación/ });
  await user.click(screen.getByRole("button", { name: "Territorios" }));
  return screen.findByRole("region", { name: /Leyenda: Territorios de reglas/ });
};

describe("Rule Territories (E2) on a regressor", () => {
  beforeEach(() => {
    resetMaps();
    installApi();
  });

  it("asks /rule-territories for the window and the measure, and colours each station by the API's dominant rule", async () => {
    const user = userEvent.setup();
    const legend = await openTerritories(user);
    await waitFor(() => expect(calls("/rule-territories")).toHaveLength(1));
    const q = calls("/rule-territories")[0]!;
    expect([q.get("model_id"), q.get("measure"), q.get("from"), q.get("to"), q.get("tau")]).toEqual([fx.rules.model_id, "mean_activation", WEEK.from, WEEK.to, null]);
    const api = expected(SET, { measure: "mean_activation", ...WEEK });
    await waitFor(() => expect(features().some((f) => f.properties.label !== null)).toBe(true));
    for (const f of features()) {
      const dominant = api.features.find((x) => x.properties.entity_id === f.properties.entity_id)!.properties.dominant_rule_id;
      expect(f.properties.label).toBe(dominant);
      expect(f.properties.value).toBeNull(); // a category, never a value
    }
    // categorical colours: one per rule, from the rule palette, not the activation scale
    const colors = matchColors();
    for (const r of fx.rules.rules) expect(colors.get(r.rule_id)).toBe(colorOf(r.rule_id));
    expect(JSON.stringify([...colors.values()])).not.toContain(VIRIDIS[0]![1]);
    // the legend lists only the rules that dominate somewhere, with how many
    const present = new Map<string, number>();
    for (const f of api.features) if (f.properties.dominant_rule_id) present.set(f.properties.dominant_rule_id, (present.get(f.properties.dominant_rule_id) ?? 0) + 1);
    const items = within(legend).getAllByRole("listitem");
    expect(items.map((li) => li.getAttribute("data-rule"))).toEqual([...present.keys()].sort());
    for (const li of items) {
      expect(li.getAttribute("data-color")).toBe(colorOf(li.getAttribute("data-rule")!));
      expect(li).toHaveTextContent(`domina en ${present.get(li.getAttribute("data-rule")!)} de 4`);
    }
  });

  it("states the measure, tau, the tie-break, n_valid and that territories overlap; never says contribution or explanation", async () => {
    const legend = await openTerritories(userEvent.setup());
    expect(await screen.findByTestId("territory-title")).toHaveTextContent("Territorios de reglas: regla dominante por estación según la activación media");
    expect(within(legend).getByTestId("territory-overlap")).toHaveTextContent("Las reglas se solapan, y el color muestra solo la dominante según la activación media");
    expect(legend.textContent).not.toMatch(/contribución|explicación/);
    expect(within(legend).getByTestId("territory-measure")).toHaveTextContent("Activación media: media del grado de activación");
    expect(within(legend).getByTestId("territory-tau")).toHaveTextContent("no interviene en esta medida");
    expect(within(legend).getByTestId("territory-tiebreak")).toHaveTextContent("menor posición (R01 antes que R02)");
    // n_valid per station comes from the answer (the fake gives 10 + index to the stations with records)
    expect(within(legend).getByTestId("territory-nvalid")).toHaveTextContent("Registros válidos");
    expect(within(legend).getByTestId("territory-nvalid")).toHaveTextContent("de 0 a 13");
    expect(within(legend).getByTestId("territory-api-text")).toHaveTextContent("lowest position (R01 before R02, ...) wins");
    expect(legend).toHaveTextContent(`[${WEEK.from}, ${WEEK.to})`);
    // activation of a rule is the other legend: no sequential scale is shown here
    expect(screen.queryByRole("region", { name: /Leyenda: activación de regla/ })).toBeNull();
  });

  it("a station with no valid record (or no dominant rule) is 'sin regla dominante', not a colour", async () => {
    const legend = await openTerritories(userEvent.setup());
    await waitFor(() => expect(features().some((f) => f.properties.label !== null)).toBe(true));
    const first = features()[0]!;
    expect(first.properties.label).toBeNull();
    const row = document.querySelector(`table.stations tr[data-entity="${first.properties.entity_id}"]`)!;
    expect(row).toHaveTextContent("sin regla dominante");
    expect(row).toHaveTextContent("sin observación");
    expect(legend).toHaveTextContent("sin regla dominante (sin registros válidos");
    expect(legend).toHaveTextContent("Estaciones con regla dominante: 3 de 4");
  });

  it("activation_frequency states tau and sends it; changing tau asks again with it", async () => {
    const user = userEvent.setup();
    const legend = await openTerritories(user);
    await user.click(screen.getByRole("radio", { name: /Frecuencia ≥ τ/ }));
    await waitFor(() => expect(calls("/rule-territories").at(-1)!.get("measure")).toBe("activation_frequency"));
    expect(calls("/rule-territories").at(-1)!.get("tau")).toBe("0.5");
    expect(await screen.findByTestId("territory-tau")).toHaveTextContent("0,50");
    expect(screen.getByTestId("territory-title")).toHaveTextContent("según la frecuencia de activación (τ = 0,50)");
    fireEvent.change(screen.getByRole("slider", { name: /τ de la frecuencia/ }), { target: { value: "0.3" } });
    await waitFor(() => expect(calls("/rule-territories").at(-1)!.get("tau")).toBe("0.3"));
    expect(await screen.findByTestId("territory-tau")).toHaveTextContent("0,30");
    expect(within(legend).queryAllByTestId("territory-tau").length).toBeLessThanOrEqual(1);
    // back to a measure without tau: not sent
    await user.click(screen.getByRole("radio", { name: /Activación media/ }));
    await waitFor(() => expect(calls("/rule-territories").at(-1)!.get("measure")).toBe("mean_activation"));
    expect(calls("/rule-territories").at(-1)!.get("tau")).toBeNull();
  });

  it("winner_share is offered only to classifiers: disabled with a reason on a TSK regressor", async () => {
    const user = userEvent.setup();
    await openTerritories(user);
    expect(screen.getByRole("radio", { name: /Reglas ganadoras/ })).toBeDisabled();
    expect(screen.getByText(/«Reglas ganadoras» solo existe en clasificadores/)).toBeInTheDocument();
    expect(calls("/rule-territories").every((q) => q.get("measure") !== "winner_share")).toBe(true);
  });

  it("clicking a rule in the legend highlights its territory: the others dim, none disappear", async () => {
    const user = userEvent.setup();
    const legend = await openTerritories(user);
    const api = expected(SET, { measure: "mean_activation", ...WEEK });
    const target = api.features.find((f) => f.properties.dominant_rule_id)!.properties.dominant_rule_id!;
    await user.click(within(legend).getByRole("button", { name: new RegExp(`^${target} domina`) }));
    // the rail's selected rule follows (bidirectional selection) and the focus note names the territory
    expect(screen.getByRole("button", { name: new RegExp(`^Regla ${target}:`) })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("radio", { name: new RegExp(`Resaltar el territorio de ${target}`) })).toBeChecked();
    expect(await screen.findByTestId("territory-focus-note")).toHaveTextContent(`Territorio resaltado: ${target} domina en`);
    await waitFor(() => expect(matchColors().get(fx.rules.rules.find((r) => r.rule_id !== target)!.rule_id)).toBe(DIMMED_RULE));
    expect(matchColors().get(target)).toBe(colorOf(target));
    // dimmed, not removed: every station that had a dominant rule still has its label
    expect(features().filter((f) => f.properties.label !== null)).toHaveLength(api.features.filter((f) => f.properties.dominant_rule_id).length);
  });

  it("the intensity view of a rule uses the sequential activation scale with its own legend, apart from the rule colours", async () => {
    const user = userEvent.setup();
    const legend = await openTerritories(user);
    const api = expected(SET, { measure: "mean_activation", ...WEEK });
    const target = api.features.find((f) => f.properties.dominant_rule_id)!.properties.dominant_rule_id!;
    await user.click(within(legend).getByRole("button", { name: new RegExp(`^${target} domina`) }));
    await user.click(screen.getByRole("radio", { name: new RegExp(`Intensidad de ${target}`) }));
    const seq = await screen.findByRole("region", { name: new RegExp(`Leyenda: Intensidad de ${target}`) });
    expect(seq).toHaveAttribute("data-domain", "0-1");
    expect(screen.queryByRole("region", { name: /Leyenda: Territorios de reglas/ })).toBeNull();
    expect(seq).toHaveTextContent("La escala es secuencial y distinta de los colores de regla");
    await waitFor(() => expect(features().some((f) => f.properties.value !== null)).toBe(true));
    for (const f of features()) {
      const stats = api.features.find((x) => x.properties.entity_id === f.properties.entity_id)!.properties.rules?.find((r) => r.rule_id === target);
      expect(f.properties.value).toBe(stats?.mean_activation ?? null);
      expect(f.properties.label).toBeNull();
    }
    const paint = maps[maps.length - 1]!.layers["stations-valid"]!.paint!["circle-color"] as unknown[];
    expect(paint[0]).toBe("interpolate");
    expect(paint[4]).toBe(VIRIDIS[0]![1]);
  });

  it("the table lists the dominant rule with its colour and n_valid, and the value of the measure", async () => {
    await openTerritories(userEvent.setup());
    const api = expected(SET, { measure: "mean_activation", ...WEEK });
    const withRule = api.features.find((f) => f.properties.dominant_rule_id)!.properties;
    await waitFor(() => expect(document.querySelector(`table.stations tr[data-entity="${withRule.entity_id}"] .class-chip`)).not.toBeNull());
    const row = document.querySelector(`table.stations tr[data-entity="${withRule.entity_id}"]`)!;
    expect(row.querySelector(".class-chip")).toHaveAttribute("data-class", withRule.dominant_rule_id!);
    expect(row).toHaveTextContent(String(withRule.n_valid));
    expect(row).toHaveTextContent(fmt(withRule.dominant_value!));
    expect(screen.getByRole("columnheader", { name: "Valor (activación media)" })).toBeInTheDocument();
  });

  it("the window follows the selector and the timeline; a day asks for that day", async () => {
    const user = userEvent.setup();
    await openTerritories(user);
    await user.click(screen.getByRole("radio", { name: /Día \(UTC\)/ }));
    await waitFor(() => expect(calls("/rule-territories").at(-1)!.get("from")).toBe("2025-01-15T00:00:00Z"));
    expect(calls("/rule-territories").at(-1)!.get("to")).toBe("2025-01-16T00:00:00Z");
  });
});

describe("Rule Territories on a winning-rule classifier", () => {
  beforeEach(() => {
    resetMaps();
    installApi({}, cls.classifierData());
  });

  it("offers winner_share and sends it; the dominant rule is the API's argmax of that measure", async () => {
    const user = userEvent.setup();
    render(<App initialTab="explorar" />);
    await screen.findByRole("region", { name: /Leyenda: activación/ });
    await user.click(screen.getByRole("button", { name: "Territorios" }));
    const radio = await screen.findByRole("radio", { name: /Reglas ganadoras/ });
    expect(radio).toBeEnabled();
    await user.click(radio);
    await waitFor(() => expect(calls("/rule-territories").at(-1)!.get("measure")).toBe("winner_share"));
    const legend = await screen.findByRole("region", { name: /Leyenda: Territorios de reglas.*reglas ganadoras/ });
    expect(within(legend).getByTestId("territory-measure")).toHaveTextContent("Reglas ganadoras (solo clasificadores): fracción de los registros válidos de la entidad en los que la regla decidió la clase");
    expect(within(legend).getByTestId("territory-tau")).toHaveTextContent("no interviene en esta medida");
    const api = expected({ ...SET, ...cls.classifierData() } as Parameters<typeof territoriesFor>[0], {
      measure: "winner_share",
      from: calls("/rule-territories").at(-1)!.get("from")!,
      to: calls("/rule-territories").at(-1)!.get("to")!,
    });
    await waitFor(() => expect(features().some((f) => f.properties.label !== null)).toBe(true));
    for (const f of features()) {
      expect(f.properties.label).toBe(api.features.find((x) => x.properties.entity_id === f.properties.entity_id)!.properties.dominant_rule_id);
    }
  });
});

describe("Rule Territories with stations the model has no data for", () => {
  it("draws them quiet, never as a dominant rule, and counts only the modelled ones", async () => {
    resetMaps();
    installApi({}, { entities: withUnmodelledZones(fx.entities, 2) });
    const legend = await openTerritories(userEvent.setup());
    await waitFor(() => expect(features().some((f) => f.properties.label !== null)).toBe(true));
    for (const id of ["U1", "U2"]) {
      const f = features().find((x) => x.properties.entity_id === id)!;
      expect(f.properties.label).toBeNull();
      expect(f.properties.missing_reason).toBe("not_modelled");
    }
    expect(legend).toHaveTextContent("Estaciones con regla dominante: 3 de 4");
    expect(await screen.findByTestId("absent-note")).toHaveTextContent("4 de 6 estaciones con modelo; 2 sin modelo (gris claro)");
  });
});
