import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { LandingArtifacts } from "../components/LandingArtifacts";
import type { FnirsModelCard, ModelRules, MontageResponse, TrialsResponse, TrialTrace } from "../api/types";
import { json } from "../test/fakeApi";
import raw from "../test/fnirsFixture.json";
import { convexHull, proximityGroups, wedgePath } from "./geometry";
import { bloodFill, divergingBin, membershipBin, signalColor } from "./ScalpMap";

/** A synthetic montage task (random trials, real ex_fuzzy fit and publication; tests/services/test_fnirs_publish.py). */
const fx = raw as unknown as { rules: ModelRules; montage: MontageResponse; card: FnirsModelCard; trials: TrialsResponse; traces: Record<string, TrialTrace> };
const MODEL = fx.card.model_id;
const domains = {
  schema_version: "0.9.0", data_version: "synthetic", synthetic: true,
  domains: [{
    domain: "fnirs", title: "Brain activity (fNIRS)", status: "available",
    tasks: [{ task_id: "fnirs_nback", task_type: "classification", target: "n-back load", unit: "n", horizon_hours: 0, status: "available", model_id: MODEL, title: "n-back", territory: "fnirs_nback", territory_title: "Cuero cabelludo (36 canales NIRS)", territory_title_en: "Scalp (36 NIRS channels)", view: "montage" }],
  }],
};

const calls: string[] = [];
beforeEach(() => {
  calls.length = 0;
  vi.stubGlobal("fetch", (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://x");
    calls.push(url.pathname + url.search);
    const q = url.searchParams;
    switch (url.pathname) {
      case "/api/v1/health": return json({ status: "ok", schema_version: "0.9.0", mode: "artifacts" });
      case "/api/v1/domains": return json(domains);
      case `/api/v1/models/${MODEL}/rules`: return json(fx.rules);
      case "/api/v1/fnirs/montage": return json(fx.montage);
      case "/api/v1/fnirs/card": return json(fx.card);
      case "/api/v1/fnirs/trials": return json(fx.trials);
      case "/api/v1/fnirs/trace": {
        const t = fx.traces[q.get("sample_id") ?? ""];
        return t ? json(t) : json({ detail: "unknown sample_id" }, 404);
      }
      default: return json({ detail: `not served: ${url.pathname}` }, 404);
    }
  });
});
afterEach(() => vi.unstubAllGlobals());

const trace1 = fx.traces["s03-t01"]!;

const toChannels = async () => {
  await screen.findByTestId("fnirs-rule-grid");
  fireEvent.click(screen.getByRole("tab", { name: "Canales" }));
  return screen.findByTestId("scalp-conditions");
};

describe("fNIRS montage task: Reglas", () => {
  it("opens on its own two tabs, Reglas first, with the task stated", async () => {
    render(<App />);
    expect(await screen.findByRole("heading", { level: 1, name: "Las reglas del modelo fNIRS" })).toBeInTheDocument();
    expect(screen.getByTestId("task-line")).toHaveTextContent(/^Tarea\s*A partir de la actividad cerebral medida con fNIRS/);
    expect(screen.getByRole("heading", { level: 1 }).querySelector(".title-accent")).toHaveTextContent("fNIRS");
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Reglas", "Canales", "Rendimiento"]);
    const figure = screen.getByRole("img", { name: /Secuencia de la tarea/ }).closest("figure")!;
    expect(figure).toHaveTextContent(/Shin et al\. \(2018\).*figura 1a \(recortada\).*CC BY 4\.0/);
    expect(within(figure).getByRole("link", { name: "CC BY 4.0" })).toHaveAttribute("href", "https://creativecommons.org/licenses/by/4.0/");
    expect(screen.getByRole("tab", { name: "Reglas" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("heading", { name: "La tarea" })).toBeInTheDocument();
    expect(document.body.textContent).toMatch(/27 bloques en tres sesiones, unos fáciles y otros difíciles/);
    // the dataset's condition names (0-back, 2-back, 3-back) are jargon to a reader: none is shown
    expect(document.body.textContent).not.toMatch(/\d-back|n-back/);
    expect(calls.some((c) => c.startsWith("/api/v1/entities") || c.startsWith("/api/v1/fnirs/trace"))).toBe(false);
  });

  it("shows the classes by their clear names, keeping the dataset's as the key", async () => {
    render(<App />);
    await screen.findByTestId("fnirs-rule-grid");
    const chips = [...document.querySelectorAll(".fnirs-task-levels .class-chip")];
    expect(chips.map((c) => c.getAttribute("data-class"))).toEqual(fx.card.target_scheme.classes.map((c) => c.label));
    expect(chips.map((c) => c.textContent)).toEqual(fx.card.target_scheme.classes.map((c) => c.display_label));
  });

  it("every rule has a tile, and every channel a rule reads carries one wedge per rule", async () => {
    render(<App />);
    const grid = await screen.findByTestId("fnirs-rule-grid");
    expect([...grid.querySelectorAll("li[data-rule]")].map((li) => li.getAttribute("data-rule"))).toEqual(fx.rules.rules.map((r) => r.rule_id));
    const channelOf = new Map(fx.montage.channels.flatMap((c) => c.inputs.map((i) => [i.feature, c.channel_id] as const)));
    const expected = new Map<string, string[]>();
    for (const r of fx.rules.rules) for (const a of r.antecedents) {
      const ch = channelOf.get(a.feature)!;
      expected.set(ch, [...new Set([...(expected.get(ch) ?? []), r.rule_id])]);
    }
    const scalp = screen.getByTestId("rules-scalp");
    for (const [ch, ids] of expected) expect(scalp.querySelector(`[data-channel="${ch}"]`)!.getAttribute("data-rules")).toBe(ids.join(" "));
    expect(scalp.querySelectorAll("[data-rules]")).toHaveLength(expected.size);
  });

  it("'See it in the trials' opens Canales with that rule on the scalp", async () => {
    render(<App />);
    const grid = await screen.findByTestId("fnirs-rule-grid");
    const last = fx.rules.rules[fx.rules.rules.length - 1]!.rule_id;
    fireEvent.click(within(grid.querySelector(`li[data-rule="${last}"]`) as HTMLElement).getByRole("button", { name: "Verla en los ensayos" }));
    expect(await screen.findByRole("button", { name: `Regla ${last}` })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("tab", { name: "Canales" })).toHaveAttribute("aria-selected", "true");
  });

  it("Rendimiento: the report's layout, with mean ± sd over groups of people and over seeds for every model", async () => {
    render(<App />);
    await screen.findByTestId("fnirs-rule-grid");
    fireEvent.click(screen.getByRole("tab", { name: "Rendimiento" }));
    const tab = await screen.findByTestId("fnirs-performance-tab");
    // the same anatomy as every report: hero with the headline, verdict chips and key figures, then benchmark columns
    const people = fx.card.metrics.filter((m) => m.estimator === "exfuzzy" && m.metric === "macro_f1" && m.slice?.startsWith("nested/fold="));
    const pMean = people.reduce((a, m) => a + m.value, 0) / people.length;
    expect(within(tab).getByRole("region", { name: "Resultado principal" })).toHaveTextContent(/F1 macro de .* en personas no vistas/);
    expect(within(tab).getByTestId("perf-standing")).toBeInTheDocument();
    expect(within(tab).getByTestId("perf-size")).toHaveTextContent(String(fx.rules.rules.length));
    const peopleCard = within(tab).getByRole("region", { name: "Personas que el modelo no vio" });
    const col = peopleCard.querySelector('.report-col[data-estimator="exfuzzy"]')!;
    expect(Number(col.querySelector("[data-raw]")!.getAttribute("data-raw"))).toBeCloseTo(pMean, 12);
    expect(col.querySelectorAll(".report-dot")).toHaveLength(people.length);
    // over people every model varies, also the ones without randomness
    expect(peopleCard.querySelector('.report-col[data-estimator="svm_rbf"]')).not.toHaveTextContent("igual en todas");
    // the manuscript's split: seeds, the published one marked, the seed-free models said so
    const seeds = fx.card.metrics.filter((m) => m.estimator === "exfuzzy" && m.metric === "macro_f1" && m.slice?.startsWith("test/seed="));
    const mean = seeds.reduce((a, m) => a + m.value, 0) / seeds.length;
    const sd = Math.sqrt(seeds.reduce((a, m) => a + (m.value - mean) ** 2, 0) / (seeds.length - 1));
    const split = within(tab).getByRole("region", { name: "El reparto del artículo" });
    const ex = split.querySelector('.report-col[data-estimator="exfuzzy"]')!;
    expect(Number(ex.querySelector("[data-raw]")!.getAttribute("data-raw"))).toBeCloseTo(mean, 12);
    expect(Number(ex.querySelector("[data-sd]")!.getAttribute("data-sd"))).toBeCloseTo(sd, 12);
    expect(ex.querySelectorAll(".report-dot--published")).toHaveLength(1);
    expect(split.querySelector('.report-col[data-estimator="svm_rbf"]')).toHaveTextContent("igual en todas");
    fireEvent.click(within(peopleCard).getByRole("button", { name: "MCC" }));
    expect(tab).toHaveTextContent(/coeficiente de correlación de Matthews/);
  });


});

describe("fNIRS montage task: Canales", () => {
  it("the matrix has one cell per trial, test subjects first, marking the misses", async () => {
    render(<App />);
    await toChannels();
    const matrix = screen.getByTestId("trial-matrix");
    const cells = [...matrix.querySelectorAll("[role=gridcell]")];
    expect(cells).toHaveLength(fx.trials.trials.length);
    expect(matrix.querySelector("[role=row][data-subject]")!.getAttribute("data-subject")).toBe("3");
    for (const cell of cells) {
      const t = fx.trials.trials.find((x) => x.sample_id === cell.getAttribute("data-sample"))!;
      const miss = t.predicted_label != null && t.predicted_label !== t.observed_label;
      expect(cell.textContent === "×").toBe(miss);
    }
    expect(cells.filter((c) => c.getAttribute("tabindex") === "0")).toHaveLength(1);
  });

  it("rule view: the top rule's channels show the memberships of the trace", async () => {
    render(<App />);
    const conditions = await toChannels();
    expect(document.body.textContent).not.toMatch(/\d-back|n-back/);
    const top = trace1.prediction.top_rule_id!;
    const entry = trace1.rules.find((r) => r.rule_id === top)!;
    const shown = [...conditions.querySelectorAll("[data-raw]")].map((e) => Number(e.getAttribute("data-raw")));
    expect(shown).toEqual(entry.antecedents.map((a) => a.effective_membership));
    const rule = fx.rules.rules.find((r) => r.rule_id === top)!;
    const channels = new Map(fx.montage.channels.flatMap((c) => c.inputs.map((i) => [i.feature, c.channel_id] as const)));
    const scalp = screen.getByTestId("scalp");
    for (const [k, a] of rule.antecedents.entries()) {
      const g = scalp.querySelector(`[data-channel="${channels.get(a.feature)}"]`)!;
      expect(Number(g.getAttribute("data-bin"))).toBeLessThanOrEqual(membershipBin(entry.antecedents[k]!.effective_membership));
    }
    expect(screen.getByTestId("scalp-firing")).toHaveTextContent(/producto de sus condiciones/);
  });

  it("data view: every channel coloured by its value on this trial's own symmetric scale", async () => {
    render(<App />);
    await toChannels();
    fireEvent.click(screen.getByRole("button", { name: "HbO" }));
    const hbo = fx.montage.channels.map((c) => c.inputs.find((i) => i.signal === "HbO")!.feature);
    const values = new Map(trace1.feature_values.map((f) => [f.feature, f.value!]));
    const bound = Math.max(...hbo.map((f) => Math.abs(values.get(f)!)));
    await waitFor(() => expect(screen.getByTestId("scalp-legend")).toHaveTextContent("µmol/L"));
    for (const c of fx.montage.channels) {
      const v = values.get(c.inputs.find((i) => i.signal === "HbO")!.feature)!;
      expect(Number(screen.getByTestId("scalp").querySelector(`[data-channel="${c.channel_id}"]`)!.getAttribute("data-bin"))).toBe(divergingBin(v, bound));
    }
  });

  it("a cell of the matrix and the arrow keys pick the trial; a class won by the bias names no supporting rule", async () => {
    render(<App />);
    await toChannels();
    const matrix = screen.getByTestId("trial-matrix");
    fireEvent.click(matrix.querySelector('[data-sample="s03-t03"]')!);
    await waitFor(() => expect(calls).toContain(`/api/v1/fnirs/trace?model_id=${MODEL}&sample_id=s03-t03`));
    const verdict = await screen.findByTestId("trial-verdict");
    await waitFor(() => expect(within(verdict).getByTestId("top-rule-note")).toHaveTextContent(/Ninguna regla apoya/));
    fireEvent.keyDown(matrix, { key: "ArrowLeft" });
    await waitFor(() => expect(matrix.querySelector('[aria-selected="true"]')!.getAttribute("data-sample")).toBe("s03-t02"));
  });

  it("the selection survives a round trip through Reglas", async () => {
    render(<App />);
    await toChannels();
    fireEvent.click(screen.getByTestId("trial-matrix").querySelector('[data-sample="s03-t03"]')!);
    fireEvent.click(screen.getByRole("tab", { name: "Reglas" }));
    await screen.findByTestId("fnirs-rule-grid");
    fireEvent.click(screen.getByRole("tab", { name: "Canales" }));
    await waitFor(() => expect(screen.getByTestId("trial-matrix").querySelector('[aria-selected="true"]')!.getAttribute("data-sample")).toBe("s03-t03"));
  });

  it("a train subject is marked in-sample (the narrow-screen picker)", async () => {
    render(<App />);
    await toChannels();
    fireEvent.change(screen.getByTestId("subject-select"), { target: { value: "1" } });
    expect(screen.getByTestId("split-badge")).toHaveTextContent("dentro de la muestra");
  });
});

describe("fNIRS montage task in English", () => {
  it("speaks English, and never calls a firing a probability or a risk", async () => {
    render(<App initialLang="en" />);
    expect(await screen.findByRole("heading", { level: 1, name: "The rules of the fNIRS model" })).toBeInTheDocument();
    expect(screen.getByTestId("task-line")).toHaveTextContent(/^Task\s*From brain activity measured with fNIRS/);
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual(["Rules", "Channels", "Performance"]);
    fireEvent.click(screen.getByRole("tab", { name: "Channels" }));
    await screen.findByTestId("scalp-conditions");
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/Sujeto|Bloque|Regla |se cumple|Carga baja/);
    expect(text).toMatch(/Low load/);
    expect(text).not.toMatch(/\d-back|n-back/);
    expect(text).not.toMatch(/probab|risk|riesgo/i);
  });
});

describe("scalp geometry", () => {
  it("groups the dataset's 36 channels into its six areas by proximity alone", () => {
    const groups = proximityGroups(fx.montage.channels.map((c) => ({ ...c, xy: c.xy as unknown as [number, number] })));
    expect(groups.map((g) => g.length).sort((a, b) => b - a)).toEqual([16, 4, 4, 4, 4, 4]);
  });

  it("hull and wedges", () => {
    expect(convexHull([[0, 0], [1, 0], [1, 1], [0, 1], [0.5, 0.5]])).toHaveLength(4);
    expect(wedgePath(0, 1, 1)).toContain("A 1 1");
    expect(wedgePath(1, 3, 1)).toMatch(/^M 0 0 L /);
  });
});

describe("scalp bins", () => {
  it("diverging bins are symmetric and clamp at the bound", () => {
    expect(divergingBin(0, 1)).toBe(0);
    expect(divergingBin(0.1, 1)).toBe(0);
    expect(divergingBin(0.3, 1)).toBe(1);
    expect(divergingBin(-0.5, 1)).toBe(-2);
    expect(divergingBin(-0.7, 1)).toBe(-3);
    expect(divergingBin(2, 1)).toBe(4);
    expect(divergingBin(1, 0)).toBe(0);
  });

  it("blood scale: red towards oxygenated, blue towards deoxygenated, for each signal", () => {
    expect(bloodFill(3, "HbO")).toBe("var(--oxy-3)");
    expect(bloodFill(-2, "HbO")).toBe("var(--deoxy-2)");
    expect(bloodFill(3, "HbR")).toBe("var(--deoxy-3)");
    expect(bloodFill(-4, "HbR")).toBe("var(--oxy-4)");
    expect(bloodFill(0, "HbO")).toBe("var(--div-mid)");
    expect([signalColor("HbO"), signalColor("HbR")]).toEqual(["var(--hbo)", "var(--hbr)"]);
  });

  it("membership bins: 0 only for 0, then quarters", () => {
    expect([0, 0.01, 0.25, 0.26, 0.5, 0.99, 1].map(membershipBin)).toEqual([0, 1, 1, 2, 2, 4, 4]);
  });
});

describe("fNIRS on the landing", () => {
  it("the hero draws where the fNIRS rules look, from the served rules and montage", async () => {
    render(<LandingArtifacts />);
    const card = await screen.findByTestId("landing-scalp");
    const map = within(card).getByTestId("landing-scalp-map");
    const used = new Set(fx.rules.rules.flatMap((r) => r.antecedents.map((a) => fx.montage.channels.find((c) => c.inputs.some((i) => i.feature === a.feature))?.channel_id)).filter(Boolean));
    expect(map.querySelectorAll("[data-rules]")).toHaveLength(used.size);
    expect(card).toHaveTextContent(`${fx.rules.rules.length} rules, ${used.size} of ${fx.montage.channels.length} channels`);
    expect(screen.getByTestId("landing-artifacts")).toHaveAttribute("aria-hidden", "true");
  });
});
