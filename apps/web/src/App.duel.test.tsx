import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RuleMapResponse } from "./api/types";
import { App } from "./App";
import { fmt } from "./lib/format";
import { fmtDiff } from "./lib/duel";
import { fake, installApi } from "./test/fakeApi";
import * as fx from "./test/fixtures";
import * as real from "./test/fixturesReal";
import * as cls from "./test/fixturesClass";
import { withUnmodelledZones } from "./test/fixturesV04";
import { maps, resetMaps } from "./test/maplibreMock";

vi.mock("maplibre-gl", async () => (await import("./test/maplibreMock")).maplibreFactory());

type Feature = { geometry: { type: string }; properties: { entity_id: string; value: number | null } };
const featuresOf = (i: number): Feature[] => (maps[i]!.sources["stations"] as { data: { features: Feature[] } }).data.features;
/** The two maps of the latest duel (A, B) or the single difference map. */
const lastMaps = (n: number) => maps.slice(-n).map((_, k) => maps.length - n + k);
const ruleMapCalls = () => fake.calls.filter((c) => c.startsWith("/api/v1/rule-map?")).map((c) => new URL(c, "http://x").searchParams);
const duelBox = () => screen.getByRole("region", { name: "Duelo de reglas" });
const startDuel = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.click(await screen.findByRole("checkbox", { name: /Comparar dos reglas/ }));
  await screen.findByTestId("rule-duel");
};
const valuesOf = (r: RuleMapResponse) => new Map(r.features.map((f) => [f.properties.entity_id, f.properties.value]));
const row = (entity: string) => document.querySelector(`table.duel-table tr[data-entity="${entity}"]`)!;

afterEach(() => vi.unstubAllGlobals());

describe("Rule Duel on points (Madrid-like mock model, regression)", () => {
  /** 08:00 UTC: SYN_D is missing in both rules; the override also drops SYN_B in A only and SYN_C in B only. */
  const ruleMapFor = (q: URLSearchParams): RuleMapResponse | undefined => {
    const base = fx.ruleMapFor(q);
    if (!base || q.get("time") !== "2025-01-15T08:00:00Z") return base;
    const drop = q.get("rule_id") === "R01" ? "SYN_B" : q.get("rule_id") === "R02" ? "SYN_C" : null;
    return {
      ...base,
      features: base.features.map((f) =>
        f.properties.entity_id === drop ? { ...f, properties: { ...f.properties, value: null, n_valid: 0, missing_reason: "no_observation" as const } } : f,
      ),
    };
  };
  beforeEach(() => {
    resetMaps();
    installApi({}, { ruleMapFor });
  });

  const goTo8 = async () => {
    fireEvent.change(await screen.findByLabelText("Hora de emisión"), { target: { value: "2" } });
    await waitFor(() => expect(screen.getByTestId("issue-time")).toHaveTextContent("08:00 UTC"));
  };

  it("is off by default: one map, one legend, the single-rule view as before", async () => {
    render(<App initialTab="explorar" />);
    await screen.findByRole("region", { name: /Leyenda: activación de regla/ }, { timeout: 4000 });
    expect(screen.queryByTestId("rule-duel")).toBeNull();
    expect(screen.getByRole("checkbox", { name: /Comparar dos reglas/ })).not.toBeChecked();
  });

  it("asks for A and B with identical parameters: only rule_id differs, same model, metric and instant", async () => {
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await goTo8();
    await startDuel(user);
    await waitFor(() => expect(ruleMapCalls().some((q) => q.get("rule_id") === "R02" && q.get("time") === "2025-01-15T08:00:00Z")).toBe(true));
    const at8 = ruleMapCalls().filter((q) => q.get("time") === "2025-01-15T08:00:00Z");
    const a = at8.find((q) => q.get("rule_id") === "R01")!;
    const b = at8.find((q) => q.get("rule_id") === "R02")!;
    const without = (q: URLSearchParams) => [...q.entries()].filter(([k]) => k !== "rule_id").sort().join("|");
    expect(without(a)).toBe(without(b));
    expect(a.get("metric")).toBe("firing_strength");
    // every request of the whole session is for the one model
    expect(new Set(ruleMapCalls().map((q) => q.get("model_id")))).toEqual(new Set([fx.rules.model_id]));
  });

  it("window measures keep the same from, to and tau for A and B", async () => {
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await startDuel(user);
    await user.click(screen.getByRole("radio", { name: /Frecuencia ≥ τ/ }));
    await waitFor(() => expect(ruleMapCalls().filter((q) => q.get("metric") === "activation_frequency" && q.get("rule_id") === "R02").length).toBeGreaterThan(0));
    const freq = ruleMapCalls().filter((q) => q.get("metric") === "activation_frequency");
    const a = freq.find((q) => q.get("rule_id") === "R01")!;
    const b = freq.find((q) => q.get("rule_id") === "R02")!;
    for (const k of ["from", "to", "tau", "model_id", "metric"]) expect(b.get(k)).toBe(a.get(k));
    expect(a.get("time")).toBeNull();
    expect(b.get("time")).toBeNull();
    expect(a.get("tau")).toBe("0.5");
  });

  it("draws A and B on two maps with the same colour scale, and one shared 0-1 legend", async () => {
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await goTo8();
    await startDuel(user);
    const [ia, ib] = lastMaps(2) as [number, number];
    await waitFor(() => expect(featuresOf(ia).some((f) => f.properties.value !== null)).toBe(true));
    await waitFor(() => expect(featuresOf(ib).some((f) => f.properties.value !== null)).toBe(true));
    const valuesA = valuesOf(ruleMapFor(new URLSearchParams(`model_id=${fx.rules.model_id}&rule_id=R01&metric=firing_strength&time=2025-01-15T08:00:00Z`))!);
    const valuesB = valuesOf(ruleMapFor(new URLSearchParams(`model_id=${fx.rules.model_id}&rule_id=R02&metric=firing_strength&time=2025-01-15T08:00:00Z`))!);
    for (const f of featuresOf(ia)) expect(f.properties.value).toBe(valuesA.get(f.properties.entity_id));
    for (const f of featuresOf(ib)) expect(f.properties.value).toBe(valuesB.get(f.properties.entity_id));
    // same palette over the same [0, 1]; the same emphasis
    for (const layer of ["stations-valid", "stations-missing"]) {
      expect(maps[ia]!.layers[layer]!.paint).toEqual(maps[ib]!.layers[layer]!.paint);
      expect(maps[ia]!.layers[layer]!.filter).toEqual(maps[ib]!.layers[layer]!.filter);
    }
    const color = maps[ia]!.layers["stations-valid"]!.paint!["circle-color"] as (string | number)[];
    expect(color.slice(0, 3)).toEqual(["interpolate", ["linear"], ["get", "value"]]);
    expect(color[3]).toBe(0);
    expect(color[color.length - 2]).toBe(1);
    // one legend, 0-1, naming A and B; no separate legend per map
    const legends = screen.getAllByRole("region", { name: /^Leyenda/ });
    expect(legends).toHaveLength(1);
    expect(legends[0]).toHaveAttribute("data-domain", "0-1");
    expect(legends[0]).toHaveTextContent("A y B comparten la escala 0–1 y la leyenda");
    expect(legends[0]).toHaveTextContent("A (R01) y B (R02)");
    expect(legends[0]).toHaveTextContent("Es el grado de activación que calcula el motor del modelo");
    // the two maps have different accessible names
    expect(screen.getByRole("region", { name: /Mapa de estaciones · A, regla R01/ })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: /Mapa de estaciones · B, regla R02/ })).toBeInTheDocument();
  });

  it("the difference view is A - B on a diverging scale centred at 0, with missing on either side left missing", async () => {
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await goTo8();
    await startDuel(user);
    // the difference map reuses pane A's map instance (the camera stays), so its index is A's
    const [id] = lastMaps(2) as [number, number];
    await user.click(screen.getByRole("radio", { name: /Diferencia de activación \(A − B\)/ }));
    await waitFor(() => expect(featuresOf(id).some((f) => f.properties.value !== null)).toBe(true));
    const iso = `model_id=${fx.rules.model_id}&metric=firing_strength&time=2025-01-15T08:00:00Z&rule_id=`;
    const a = valuesOf(ruleMapFor(new URLSearchParams(iso + "R01"))!);
    const b = valuesOf(ruleMapFor(new URLSearchParams(iso + "R02"))!);
    const got = new Map(featuresOf(id).map((f) => [f.properties.entity_id, f.properties.value]));
    expect(got.get("SYN_A")).toBe(a.get("SYN_A")! - b.get("SYN_A")!); // 0.667 - 0 (a real 0 on the B side)
    expect(got.get("SYN_B")).toBeNull(); // missing in A only
    expect(got.get("SYN_C")).toBeNull(); // A is a real 0, B is missing: not 0 - nothing
    expect(got.get("SYN_D")).toBeNull(); // missing in both
    // diverging stops over [-1, 1], neutral at 0
    const color = maps[id]!.layers["stations-valid"]!.paint!["circle-color"] as (string | number)[];
    expect(color.filter((x): x is number => typeof x === "number")).toEqual([-1, -0.5, 0, 0.5, 1]);
    expect(color[color.indexOf(0) + 1]).toBe("#f1f1f1");
    expect(JSON.stringify(maps[id]!.layers["stations-missing"]!.filter)).toContain("typeof");
    // the label is the one the spec asks for, in the legend and the title of the map
    const legend = screen.getByRole("region", { name: /^Leyenda: diferencia de activación \(A − B\)/ });
    expect(legend).toHaveAttribute("data-domain", "-1-1");
    expect(legend).toHaveTextContent("diferencia de activación (A − B)");
    expect(legend).toHaveTextContent("el resultado es «sin dato»");
    expect(screen.getAllByRole("region", { name: /^Leyenda/ })).toHaveLength(1);
  });

  it("the table lists A, B and A - B per entity; a missing side reads 'sin dato' and the difference 'sin diferencia'", async () => {
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await goTo8();
    await startDuel(user);
    await waitFor(() => expect(row("SYN_A")).toHaveTextContent(fmtDiff(0.6666666666666666)));
    const table = screen.getByRole("table", { name: "Duelo R01 frente a R02" });
    expect(within(table).getByRole("columnheader", { name: /A · R01/ })).toBeInTheDocument();
    expect(within(table).getByRole("columnheader", { name: "A − B" })).toBeInTheDocument();
    expect(table.querySelector("caption")).toHaveTextContent("A − B es la diferencia de activación");
    const cell = (id: string, side: string) => row(id).querySelector(`td[data-side="${side}"]`)!;
    expect(cell("SYN_A", "a").querySelector("[data-raw]")!.getAttribute("data-raw")).toBe(String(0.6666666666666666));
    expect(cell("SYN_A", "b")).toHaveTextContent(fmt(0)); // a real 0 is shown as 0
    expect(cell("SYN_B", "a")).toHaveTextContent("sin dato · sin observación");
    expect(cell("SYN_B", "diff")).toHaveTextContent("sin diferencia (falta A)");
    expect(cell("SYN_C", "a")).toHaveTextContent(fmt(0));
    expect(cell("SYN_C", "b")).toHaveTextContent("sin dato");
    expect(cell("SYN_C", "diff")).toHaveTextContent("sin diferencia (falta B)");
    expect(cell("SYN_D", "diff")).toHaveTextContent("sin diferencia (faltan A y B)");
    expect(cell("SYN_D", "a")).toHaveTextContent("falta una entrada");
  });

  it("selection is shared: a click on map A, map B, or the table selects the same entity everywhere", async () => {
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await goTo8();
    await startDuel(user);
    const [ia, ib] = lastMaps(2) as [number, number];
    await waitFor(() => expect(featuresOf(ib).some((f) => f.properties.value !== null)).toBe(true));
    const selectedOn = (i: number) => JSON.stringify(maps[i]!.layers["stations-selected"]!.filter);
    const clickOn = (i: number, id: string) => maps[i]!.handlers["click:stations-valid"]!.forEach((h) => h({ features: [{ properties: { entity_id: id } }] }));
    const bothSelect = (id: string) =>
      waitFor(() => {
        expect(row(id)).toHaveAttribute("aria-selected", "true");
        expect(selectedOn(ia)).toContain(id);
        expect(selectedOn(ib)).toContain(id);
      });
    clickOn(ia, "SYN_A");
    await bothSelect("SYN_A");
    clickOn(ib, "SYN_C");
    await bothSelect("SYN_C");
    await user.click(within(row("SYN_B") as HTMLElement).getByRole("button"));
    await bothSelect("SYN_B");
    expect(screen.getByText(/Estación seleccionada:/)).toBeInTheDocument();
  });

  it("keyboard: arrows move between entities in the table and Enter selects", async () => {
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await goTo8();
    await startDuel(user);
    await waitFor(() => expect(row("SYN_A")).toHaveTextContent(fmtDiff(0.6666666666666666)));
    const buttons = within(screen.getByRole("table", { name: "Duelo R01 frente a R02" })).getAllByRole("button");
    buttons[0]!.focus();
    await user.keyboard("{ArrowDown}");
    expect(buttons[1]).toHaveFocus();
    await user.keyboard("{ArrowDown}{ArrowUp}");
    expect(buttons[1]).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(buttons[1]).toHaveAttribute("aria-pressed", "true");
    expect(buttons[0]).toHaveAttribute("aria-pressed", "false");
  });

  it("offers only the rules of this model: two selectors, no model chooser, and says why there is no cross-model duel", async () => {
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await startDuel(user);
    const box = duelBox();
    const selects = within(box).getAllByRole("combobox");
    expect(selects).toHaveLength(2);
    const ids = fx.rules.rules.map((r) => r.rule_id);
    for (const s of selects) {
      const options = within(s).getAllByRole("option").map((o) => (o as HTMLOptionElement).value);
      expect(options.every((o) => ids.includes(o))).toBe(true);
    }
    // A and B can never be the same rule
    const [a, b] = selects as HTMLSelectElement[];
    expect([a!.value, b!.value]).toEqual(["R01", "R02"]);
    expect(within(a!).queryByRole("option", { name: /^R02/ })).toBeNull();
    expect(within(b!).queryByRole("option", { name: /^R01/ })).toBeNull();
    const scope = within(box).getByTestId("duel-scope");
    expect(scope).toHaveTextContent(fx.rules.model_id);
    expect(scope).toHaveTextContent("Entre modelos no hay correspondencia de reglas");
    expect(scope).toHaveTextContent("la «R07» de uno no equivale a la «R07» de otro");
    expect(within(box).queryByText(/otro modelo|modelo B|comparar modelos/i)).toBeNull();
  });

  it("changing B asks the API for the new rule only, and the swap exchanges A and B", async () => {
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await startDuel(user);
    await user.selectOptions(within(duelBox()).getByRole("combobox", { name: "Regla B" }), "R03");
    await waitFor(() => expect(ruleMapCalls().some((q) => q.get("rule_id") === "R03")).toBe(true));
    expect(screen.getByRole("heading", { name: /Duelo: regla R01 \(A\) frente a regla R03 \(B\)/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Intercambiar A y B/ }));
    expect(await screen.findByRole("heading", { name: /Duelo: regla R03 \(A\) frente a regla R01 \(B\)/ })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Duelo R03 frente a R01" })).toBeInTheDocument();
    // picking in the rail the rule that is B makes it A, and A becomes B
    await user.click(within(screen.getByRole("region", { name: "Reglas del modelo" })).getByRole("button", { name: /^Regla R01:/ }));
    expect(await screen.findByRole("heading", { name: /Duelo: regla R01 \(A\) frente a regla R03 \(B\)/ })).toBeInTheDocument();
  });

  it("turning the duel off returns to the single-rule view", async () => {
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await startDuel(user);
    await user.click(screen.getByRole("checkbox", { name: /Comparar dos reglas/ }));
    expect(screen.queryByTestId("rule-duel")).toBeNull();
    expect(await screen.findByRole("region", { name: /Leyenda: activación de regla \(0–1\)/ })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: /Estaciones/ })).toBeInTheDocument();
  });
});

describe("Rule Duel on polygons (real NYC model; rule B derived for the test)", () => {
  /** The real payloads only hold R01 at this hour: R02 is R01 halved, with zone 39 missing, built here for the test. */
  const ruleMapFor = (q: URLSearchParams): RuleMapResponse | undefined => {
    if (q.get("rule_id") !== "R02") return real.nyc.ruleMapFor(new URLSearchParams([...q.entries()].map(([k, v]) => (k === "rule_id" ? [k, "R01"] : [k, v]))));
    const base = real.nyc.ruleMapFor(new URLSearchParams([...q.entries()].map(([k, v]) => (k === "rule_id" ? [k, "R01"] : [k, v]))));
    return (
      base && {
        ...base,
        rule_id: "R02",
        features: base.features.map((f) => ({
          ...f,
          properties: {
            ...f.properties,
            rule_id: "R02",
            value: f.properties.entity_id === "39" ? null : f.properties.value! / 2,
            missing_reason: f.properties.entity_id === "39" ? ("missing_input" as const) : null,
          },
        })),
      }
    );
  };
  beforeEach(() => {
    resetMaps();
    installApi({}, { ...real.realData(), ruleMapFor, entities: withUnmodelledZones(real.nyc.entities, 3) });
  });

  const openNyc = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(await screen.findByRole("button", { name: /Taxis de Nueva York/ }));
    const hours = (Date.parse(real.NYC_EVENING) - Date.parse(real.NYC_FIRST_ISSUE)) / 3_600_000;
    fireEvent.change(await screen.findByLabelText("Hora de emisión"), { target: { value: String(hours) } });
    await waitFor(() => expect(screen.getByTestId("issue-time")).toHaveTextContent("23:00 UTC"));
  };

  it("draws two choropleths of real zones with the same scale, difference A - B on polygons, and keeps zones without a reference level", async () => {
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await openNyc(user);
    await startDuel(user);
    const [ia, ib] = lastMaps(2) as [number, number];
    await waitFor(() => expect(featuresOf(ib).some((f) => f.properties.value !== null)).toBe(true));
    expect(new Set(featuresOf(ia).map((f) => f.geometry.type))).toEqual(new Set(["Polygon", "MultiPolygon"]));
    expect(maps[ia]!.layers["zones-fill"]!.paint).toEqual(maps[ib]!.layers["zones-fill"]!.paint);
    expect(maps[ia]!.layers["zones-fill"]!.paint!["fill-color"]).toEqual(maps[ib]!.layers["zones-fill"]!.paint!["fill-color"]);
    // zones 35 and 39 have no reference LEVEL (a prediction concept), but the engine fires there: they hold activations, not 'missing'
    const a = new Map(featuresOf(ia).map((f) => [f.properties.entity_id, f.properties.value]));
    const b = new Map(featuresOf(ib).map((f) => [f.properties.entity_id, f.properties.value]));
    expect(a.get("35")).not.toBeNull();
    expect(b.get("35")).toBe(a.get("35")! / 2);
    expect(a.get("39")).not.toBeNull();
    expect(b.get("39")).toBeNull();
    // the difference
    await user.click(screen.getByRole("radio", { name: /Diferencia de activación \(A − B\)/ }));
    const id = ia;
    await waitFor(() => expect(featuresOf(id).some((f) => f.properties.value !== null && f.properties.value !== a.get(f.properties.entity_id))).toBe(true));
    const d = new Map(featuresOf(id).map((f) => [f.properties.entity_id, f.properties.value]));
    expect(d.get("35")).toBe(a.get("35")! - a.get("35")! / 2);
    expect(d.get("39")).toBeNull(); // B missing: not A - 0
    expect(maps[id]!.layers["zones-fill"]!.paint!["fill-color"]).toEqual(expect.arrayContaining(["interpolate", ["linear"], ["get", "value"], -1, "#542788"]));
    expect(row("39")).toHaveTextContent("sin diferencia (falta B)");
    // wording that belongs to NYC is in NYC
    expect(screen.getByTestId("absent-note")).toHaveTextContent("3 sin modelo");
  });

  it("asks both rules for the same model and instant in local time of the zone", async () => {
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await openNyc(user);
    await startDuel(user);
    await waitFor(() => expect(ruleMapCalls().some((q) => q.get("rule_id") === "R02")).toBe(true));
    const calls = ruleMapCalls().filter((q) => q.get("time") === real.NYC_EVENING);
    const pairs = ["R01", "R02"].map((r) => calls.find((q) => q.get("rule_id") === r)!);
    expect(pairs[0]!.get("model_id")).toBe(real.nyc.rules.model_id);
    expect(pairs[1]!.get("model_id")).toBe(pairs[0]!.get("model_id"));
    expect(pairs[1]!.get("metric")).toBe(pairs[0]!.get("metric"));
  });
});

describe("Rule Duel on irregular samples (real Water model: windows only)", () => {
  beforeEach(() => {
    resetMaps();
    installApi({}, real.realData());
  });

  it("compares window aggregates of the same window; there is no instant to compare", async () => {
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Ríos de Inglaterra/ }));
    await startDuel(user);
    await waitFor(() => expect(ruleMapCalls().some((q) => q.get("rule_id") === "R02")).toBe(true));
    const a = ruleMapCalls().find((q) => q.get("rule_id") === "R01")!;
    const b = ruleMapCalls().find((q) => q.get("rule_id") === "R02")!;
    for (const q of [a, b]) {
      expect(q.get("metric")).toBe("mean_activation");
      expect(q.get("time")).toBeNull();
      expect([q.get("from"), q.get("to")]).toEqual(["2025-12-01T00:00:00Z", "2026-01-01T00:00:00Z"]);
    }
    const [ia, ib] = lastMaps(2) as [number, number];
    await waitFor(() => expect(featuresOf(ib).some((f) => f.properties.value !== null)).toBe(true));
    expect(featuresOf(ia).every((f) => f.geometry.type === "Point")).toBe(true);
    // a point without samples in the window is missing on both sides and has no difference
    const legend = screen.getByRole("region", { name: /^Leyenda/ });
    expect(legend).toHaveTextContent("Muestras válidas por punto de muestreo");
    expect(row(real.WATER_EMPTY_POINT)).toHaveTextContent("sin diferencia (faltan A y B)");
    // 0 is a value: the first point has mean activation 0 in R01 and a real difference
    const a0 = valuesOf(real.water.ruleMapFor(a)!).get(real.WATER_POINT);
    const b0 = valuesOf(real.water.ruleMapFor(b)!).get(real.WATER_POINT);
    expect(a0).toBe(0);
    expect(b0).not.toBeNull();
    expect(row(real.WATER_POINT).querySelector('td[data-side="diff"] [data-raw]')!.getAttribute("data-raw")).toBe(String(a0! - b0!));
  });
});

describe("wording that belongs to NYC only", () => {
  beforeEach(() => {
    resetMaps();
    installApi({}, cls.classifierData());
  });

  it("Madrid-like classifier never says 'sin referencia' or 'sin modelo', in Rules, a duel or Prediction", async () => {
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await screen.findByLabelText("Hora de emisión");
    await startDuel(user);
    expect(document.body).not.toHaveTextContent(/sin referencia|sin modelo|nivel de referencia/);
    await user.click(screen.getByRole("tab", { name: "Predicción" }));
    await screen.findByRole("region", { name: /Leyenda: categoría prevista/ });
    expect(document.body).not.toHaveTextContent(/sin referencia|sin modelo|nivel de referencia/);
  });
});

