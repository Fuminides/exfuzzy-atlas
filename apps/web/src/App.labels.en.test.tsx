import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type { DomainsResponse, ModelRules, TargetScheme } from "./api/types";
import { setLang } from "./i18n";
import { installApi, type FakeData } from "./test/fakeApi";
import * as cls from "./test/fixturesClass";
import { classifiedSummary, classifierImportance } from "./test/fixturesV05";
import { resetMaps } from "./test/maplibreMock";

vi.mock("maplibre-gl", async () => (await import("./test/maplibreMock")).maplibreFactory());

beforeEach(() => resetMaps());
afterEach(() => {
  vi.unstubAllGlobals();
  setLang("es");
});

/** Display names as the API serves them from contract v0.6: Spanish, with an English pair (the classes are data). */
const CLASSES: Record<string, [string, string]> = { low: ["Buena", "Good"], mid: ["Regular", "Moderate"], high: ["Mala o peor", "Poor or worse"] };
const VARIABLES: Record<string, string | undefined> = { y_t: "Current level", y_lag3: "Level 3 h ago", hour: "Hour of the day" }; // exo_t: Spanish only

/**
 * The synthetic classifier with v0.6 English fields. `english: false` serves the same Spanish names without any `*_en`
 * (an API before v0.6), so the fallback can be checked against the same screen.
 */
function bilingual(english = true): Partial<FakeData> {
  const en = <T,>(value: T): T | undefined => (english ? value : undefined);
  const scheme = (s: TargetScheme): TargetScheme => ({
    ...s,
    name: "Bandas inventadas de la serie",
    name_en: en("Made-up bands of the series"),
    classes: s.classes.map((c) => ({ ...c, display_label: CLASSES[c.label]![0], display_label_en: en(CLASSES[c.label]![1]) })) as TargetScheme["classes"],
  });
  const rules: ModelRules = {
    ...cls.rules,
    target_scheme: scheme(cls.rules.target_scheme!),
    variables: cls.rules.variables.map((v) => ({ ...v, label_en: en(VARIABLES[v.feature]) })),
  };
  const card = { ...cls.card, target_scheme: scheme(cls.card.target_scheme!) };
  const taskId = cls.card.manifest.task_id;
  const domains: DomainsResponse = {
    ...cls.domains,
    domains: cls.domains.domains.map((d) => ({ ...d, tasks: d.tasks.map((t) => ({ ...t, territory: "zona", territory_title: "Zona de prueba", territory_title_en: en("Test zone") })) })),
  };
  return {
    ...cls.classifierData(),
    domains,
    rules,
    card,
    summary: { ...classifiedSummary(rules, cls.entities, taskId), label: "Concentración observada", label_en: en("Observed concentration") },
    importance: classifierImportance(rules, cls.entities, taskId),
  };
}

const main = () => document.querySelector("main")!.textContent ?? "";
const sentences = () => screen.getAllByTestId("rule-sentence").map((s) => s.textContent ?? "");

describe("API labels in English (contract v0.6)", () => {
  it("Patterns in English shows the English class, variable and territory names, never the Spanish ones", async () => {
    installApi({}, bilingual());
    render(<App initialLang="en" initialTab="patrones" />);
    await screen.findByText("Which variables take part most");
    await waitFor(() => expect(sentences().length).toBeGreaterThan(0));
    const text = main();
    expect(text).toMatch(/\bGood\b/);
    expect(text).toContain("Level 3 h ago");
    expect(text).not.toMatch(/Buena|Mala o peor|Nivel hace 3 h|Zona de prueba/);
    // R01 is "IF y_lag3 IS Low THEN low": the rule sentence reads in English, with the English class
    expect(sentences()).toContain("If Level 3 h ago is low → Good");
    expect(screen.getByRole("button", { name: /Test zone/ })).toBeInTheDocument();
  });

  it("Prediction in English names the scheme and its classes in English in the legend and the footer", async () => {
    installApi({}, bilingual());
    render(<App initialLang="en" initialTab="prediccion" />);
    const legend = await screen.findByRole("region", { name: /^Legend: / }, { timeout: 4000 });
    await waitFor(() => expect(legend).toHaveTextContent("Made-up bands of the series"));
    expect([...legend.querySelectorAll(".class-chip")].map((c) => c.textContent)).toEqual(["Good", "Moderate", "Poor or worse"]);
    expect(legend).not.toHaveTextContent(/Buena|Bandas inventadas/);
    // the synthetic scheme is "analytical", not an official index: it has no official names to list (v0.6.1)
    expect(legend).not.toHaveTextContent("official names");
    await waitFor(() => expect(document.querySelector("footer")?.textContent).toContain("Made-up bands of the series"));
  });

  it("Summary in English names the observed variable and the territory in English", async () => {
    installApi({}, bilingual());
    render(<App initialLang="en" initialTab="resumen" />);
    await screen.findByRole("img", { name: /All the observations/ });
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Data summary: Test zone");
    expect(main()).toContain("observed concentration");
    expect(main()).toMatch(/\bGood\b/);
    expect(main()).not.toMatch(/Concentración observada|concentración observada|Buena\b|Zona de prueba/);
  });

  it("a variable without label_en keeps its Spanish label in English", async () => {
    installApi({}, bilingual());
    render(<App initialLang="en" initialTab="patrones" />);
    await screen.findByText("Which variables take part most");
    await waitFor(() => expect(main()).toContain("Variable exógena"));
  });

  it("an API without the *_en fields falls back to the Spanish names in English", async () => {
    installApi({}, bilingual(false));
    render(<App initialLang="en" initialTab="patrones" />);
    await screen.findByText("Which variables take part most");
    await waitFor(() => expect(sentences().length).toBeGreaterThan(0));
    expect(sentences()).toContain("If Nivel hace 3 h is low → Buena");
    expect(screen.getByRole("button", { name: /Zona de prueba/ })).toBeInTheDocument();
  });

  it("in Spanish the same API shows the Spanish names", async () => {
    installApi({}, bilingual());
    render(<App initialTab="patrones" />);
    await screen.findByText(/Qué variables intervienen más/);
    await waitFor(() => expect(sentences().length).toBeGreaterThan(0));
    expect(sentences()).toContain("Si Nivel hace 3 h es baja → Buena");
    expect(main()).not.toMatch(/\bGood\b|Level 3 h ago|Test zone/);
  });
});
