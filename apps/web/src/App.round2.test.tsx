import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { displayName } from "./lib/entityRows";
import { classShare } from "./lib/summary";
import { namesFor, officialNames, labelWithUnit } from "./lib/labels";
import { formatShortDate, sig3 } from "./lib/format";
import { installApi } from "./test/fakeApi";
import * as fx from "./test/fixturesClass";
import { maps, resetMaps } from "./test/maplibreMock";
import { classifierV05 } from "./test/v05";

vi.mock("maplibre-gl", async () => (await import("./test/maplibreMock")).maplibreFactory());

beforeEach(() => resetMaps());
afterEach(() => vi.unstubAllGlobals());

describe("Predicción: the rule that decided each prediction (v0.5.1)", () => {
  it("adds a column with the deciding rule, its sentence on hover, and a link that opens the rule in Patrones", async () => {
    installApi({}, { ...classifierV05(), decidedBy: "R02" });
    render(<App initialTab="prediccion" />);
    const user = userEvent.setup();
    const table = await screen.findByRole("table", { name: /Estaciones/ });
    await waitFor(() => expect(within(table).getByRole("columnheader", { name: "Regla que decidió" })).toBeInTheDocument());
    const link = await waitFor(() => {
      const l = within(table).getAllByRole("button", { name: "R02" })[0];
      expect(l).toBeDefined();
      return l!;
    });
    // the rule's card on hover or focus (it replaced the title tooltip): the sentence, and what a click does
    act(() => link.focus());
    expect(screen.getByTestId("rule-hovercard-sentence")).toHaveTextContent(/^Si .* → .+$/);
    expect(screen.getByRole("tooltip")).toHaveTextContent(/Ver la regla en Patrones$/);
    await user.click(link);
    expect(screen.getByRole("tab", { name: "Patrones" })).toHaveAttribute("aria-selected", "true");
    await waitFor(() => expect(document.querySelector("li.rule-card[data-rule='R02']")).toHaveAttribute("aria-current", "true"));
    // a tab clicked by hand starts clean: the rule is no longer pre-selected
    await user.click(screen.getByRole("tab", { name: "Resumen de datos" }));
    await user.click(screen.getByRole("tab", { name: "Patrones" }));
    await waitFor(() => expect(document.querySelector("li.rule-card[data-rule='R01']")).not.toBeNull());
    expect(document.querySelector("li.rule-card[aria-current='true']")).toBeNull();
  });

  it("says «la decidió R02» in the station detail, never as a cause", async () => {
    installApi({}, { ...classifierV05(), decidedBy: "R02" });
    render(<App initialTab="prediccion" />);
    const user = userEvent.setup();
    const table = await screen.findByRole("table", { name: /Estaciones/ });
    await user.click(within(table).getByRole("button", { name: /Synthetic station E1/ }));
    const box = await screen.findByTestId("decided-by");
    expect(box).toHaveTextContent("La decidió R02");
    expect(box).not.toHaveTextContent(/causa/);
    expect(within(box).getByRole("button", { name: "Ver la regla en Patrones" })).toBeInTheDocument();
  });

  it("has no such column when the API does not say which rule decided", async () => {
    installApi({}, classifierV05());
    render(<App initialTab="prediccion" />);
    const table = await screen.findByRole("table", { name: /Estaciones/ });
    expect(within(table).queryByRole("columnheader", { name: "Regla que decidió" })).toBeNull();
    expect(screen.queryByTestId("decided-by")).toBeNull();
  });

  it("keeps a one-line model quality summary visible next to the collapsed details", async () => {
    installApi({}, classifierV05());
    render(<App initialTab="prediccion" />);
    const brief = await screen.findByTestId("model-brief");
    expect(brief).toHaveTextContent(/Calidad del modelo\./);
    expect(brief.closest("details")).toBeNull();
    expect(document.querySelector("details.model-panel")).not.toHaveAttribute("open");
  });

  it("shows no raw missing_reason code and no bare task-type tag", async () => {
    installApi({}, classifierV05());
    render(<App initialTab="prediccion" />);
    await screen.findByRole("table", { name: /Estaciones/ });
    await waitFor(() => expect(maps.length).toBeGreaterThan(0));
    expect(document.body.textContent).not.toMatch(/missing_input|prediction_unavailable|no_observation|not_modelled/);
    expect(document.querySelector(".badge--task")).toBeNull();
  });
});

describe("Names: translated classes and term labels (v0.5.1), with graceful fallbacks", () => {
  const translated = () => {
    const data = classifierV05();
    const classes = fx.rules.target_scheme!.classes;
    const tr = (label: string) => `${label} (es)`;
    const scheme = { ...fx.rules.target_scheme!, classes: classes.map((c) => ({ ...c, display_label: tr(c.label) })) };
    const variables = fx.rules.variables.map((v, i) => (i === 0 ? { ...v, terms: v.terms.map((t) => ({ ...t, label: `${t.name} traducido` })) } : v));
    data.rules = { ...fx.rules, target_scheme: scheme, variables } as typeof fx.rules;
    data.card = { ...fx.card, target_scheme: scheme } as typeof fx.card;
    return { data, scheme };
  };

  it("writes chips and terms with the published names; the key stays in data-class", async () => {
    const { data } = translated();
    installApi({}, data);
    render(<App initialTab="patrones" />);
    await screen.findByText("Qué variables intervienen más");
    const sentence = within(document.querySelector("li.rule-card[data-rule='R01']")!).getByTestId("rule-sentence");
    const chip = sentence.querySelector<HTMLElement>(".class-chip")!;
    expect(chip.textContent).toMatch(/\(es\)$/);
    expect(chip.dataset.class).not.toMatch(/\(es\)/);
  });

  it("namesFor: term label, else class display name, else the readable fallback; official names listed once", () => {
    const scheme = { short_name: "EAQI", classes: [{ label: "Good", display_label: "Buena" }, { label: "Fair" }] };
    const names = namesFor([{ feature: "t", terms: [{ name: "Low", label: "baja temperatura", membership_type: "trapezoidal", params: [] }, { name: "Good", params: [], membership_type: "trapezoidal" }] }], scheme);
    expect(names.term("t", "Low")).toBe("baja temperatura");
    expect(names.term("t", "Good")).toBe("Buena");
    expect(names.term("t", "High")).toBe("alta");
    expect(names.cls("Good")).toBe("Buena");
    expect(names.cls("Fair")).toBe("Fair");
    expect(officialNames(scheme)).toBe("nombres oficiales EAQI: Good, Fair");
    expect(officialNames({ classes: [{ label: "Buena" }] })).toBeNull();
  });
});

describe("Formatting", () => {
  it("prints a unit once, in Spanish, and never mixes « (u)» with « · u»", () => {
    expect(labelWithUnit("Días desde pleno invierno", "days")).toBe("Días desde pleno invierno");
    expect(labelWithUnit("Temperatura del agua", "degC")).toBe("Temperatura del agua (°C)");
    expect(labelWithUnit("NO₂ hace 1 h (último dato)", "ug/m3")).toBe("NO₂ hace 1 h (último dato, µg/m³)");
    expect(labelWithUnit("Hora local", "hour")).toBe("Hora local");
    expect(labelWithUnit("Cociente", "ratio")).toBe("Cociente");
  });

  it("shows consequents with 3 significant figures", () => {
    expect(sig3(14.355)).toBe("14,4");
    expect(sig3(0.5372)).toBe("0,537");
    expect(sig3(5.9984)).toBe("6");
    expect(sig3(1234.5)).toBe("1235");
  });

  it("title-cases a name written fully in capitals and leaves other names alone", () => {
    expect(displayName("SOUTH LOW AT TIDAL SLUICE")).toBe("South Low at Tidal Sluice");
    expect(displayName("WHITEADDER WATER (B6461 ROAD BRIDGE)")).toBe("Whiteadder Water (B6461 Road Bridge)");
    expect(displayName("TWEED U/S CONFLUENCE WITH R TILL")).toBe("Tweed U/S Confluence with R Till");
    expect(displayName("FENHAM-LE-MOOR")).toBe("Fenham-le-Moor");
    expect(displayName("Pza. de España")).toBe("Pza. de España");
    expect(displayName("M-30")).toBe("M-30");
    expect(displayName("Elsterwerda, 1992-2020")).toBe("Elsterwerda (estación de 1992 a 2020)");
    expect(displayName("Elsterwerda")).toBe("Elsterwerda");
  });

  it("gives a short day for table cells", () => {
    expect(formatShortDate("2025-12-04T10:20:00Z", "Europe/London")).toBe("4 dic 2025");
  });

  it("classShare reads how often a class occurs in all the observed hours", () => {
    const s = { classes: [{ label: "a", lower: null, upper: 1 }, { label: "b", lower: 1, upper: null }], groups: { all: [{ key: "all", n: 10, shares: [0.75, 0.25] }] } };
    expect(classShare(s as never, "b")).toBe(0.25);
    expect(classShare(s as never, "zz")).toBeNull();
    expect(classShare(null, "a")).toBeNull();
  });
});
