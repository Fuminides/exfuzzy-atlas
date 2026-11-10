import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { WhyHerePanel } from "./components/WhyHerePanel";
import { setLang } from "./i18n";
import { pct } from "./lib/format";
import { ruleFigures } from "./lib/ruleFigures";
import { installApi } from "./test/fakeApi";
import { mixtureV07 } from "./test/fixturesMixture";
import { resetMaps } from "./test/maplibreMock";
import { classifierV05 } from "./test/v05";

vi.mock("maplibre-gl", async () => (await import("./test/maplibreMock")).maplibreFactory());

beforeEach(() => resetMaps());
afterEach(() => {
  vi.unstubAllGlobals();
  setLang("es");
});

const cards = () => [...document.querySelectorAll<HTMLElement>("li.rule-card")];

/** Contract v0.7: a mixture of rules in Patrones, the hovercard figures and ¿Por qué aquí?. */
describe("a mixture of rules (contract v0.7)", () => {
  it("Patrones: the hero, the matrix and the cards show what each rule adds to each category, not what it decides", async () => {
    installApi({}, mixtureV07());
    render(<App initialTab="patrones" />);
    await screen.findByRole("table", { name: /Matriz de reglas/ });
    expect(screen.queryByTestId("rule-matrix-headline")).toBeNull();
    expect(screen.queryByText(/suman apoyo a cada categoría\. R01 es la que más suma/)).toBeNull();
    expect(screen.getByTestId("page-lead")).toHaveTextContent("Ninguna regla decide sola");

    // the matrix: one column per class with the centred weight (signed, so colour is not the only cue), no «Entonces»
    const matrix = screen.getByRole("table", { name: /Matriz de reglas/ });
    expect(within(matrix).queryByRole("columnheader", { name: "Entonces" })).toBeNull();
    expect(within(matrix).getByRole("columnheader", { name: "La que más suma" })).toBeInTheDocument();
    const r1 = matrix.querySelector('tr[data-rule="R01"]')!;
    expect(r1.querySelector('td[data-class="low"]')).toHaveTextContent("+1,60");
    expect(r1.querySelector('td[data-class="high"]')).toHaveTextContent("−1,40");
    expect(r1.querySelector('td[data-class="low"]')).toHaveClass("rmx-wcell--strongest");
    expect(r1.querySelector('td[data-class="high"]')).toHaveTextContent("supresión");
    expect(r1.querySelector("td.rmx-share")).toHaveTextContent("50 %");
    expect(screen.getByTestId("class-weights-key")).toHaveTextContent("− supresión");

    // a card: sentence with the class it supports most (never the consequent), its weights and its figures
    const card = cards()[0]!;
    expect(within(card).getByTestId("rule-sentence")).toHaveTextContent("apoya sobre todo");
    expect(within(card).getByTestId("rule-sentence")).not.toHaveTextContent("→ low"); // R01's consequent
    const weights = within(card).getByTestId("class-weights");
    expect(weights.querySelector('li[data-class="high"]')).toHaveAttribute("data-sign", "suppression");
    expect(weights.querySelector('li[data-class="low"]')).toHaveAttribute("data-sign", "support");
    const metrics = within(card).getByTestId("rule-metrics");
    expect(metrics).toHaveTextContent("es la que más suma a la categoría prevista en el 50 % de las predicciones");
    expect(metrics).toHaveTextContent("sin ella cambiaría la categoría del 30 % de las predicciones");
    expect(within(card).queryByTestId("base-rate")).toBeNull();
    // R04 mostly suppresses mid
    const r4 = cards().find((c) => c.dataset.rule === "R04") ?? null;
    if (r4) expect(within(r4).getByTestId("class-weights").querySelector('li[data-class="mid"]')).toHaveAttribute("data-sign", "suppression");

    // the variables card and how it is measured
    expect(screen.getByText(/Parte de las predicciones en las que la regla que más suma a la categoría prevista usa cada variable/)).toBeInTheDocument();
  });

  it("Patrones › Por zonas: a picked rule is where it adds the most, in words of the mixture", async () => {
    installApi({}, mixtureV07());
    render(<App initialTab="patrones" />);
    await userEvent.click(await screen.findByRole("button", { name: /Mostrar en el mapa la regla R02/ }));
    expect(await screen.findByRole("heading", { name: "Dónde suma más R02" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: /Leyenda: parte de las predicciones en las que R02 es la que más suma/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Regla que más suma" })).toBeInTheDocument();
  });

  it("Patrones in English", async () => {
    installApi({}, mixtureV07());
    render(<App initialLang="en" initialTab="patrones" />);
    await screen.findByRole("table", { name: /^Rule matrix/ });
    expect(screen.queryByTestId("rule-matrix-headline")).toBeNull();
    expect(screen.queryByText(/add up support for each category\. R01 adds the most/)).toBeNull();
    const card = cards()[0]!;
    expect(within(card).getByTestId("rule-sentence")).toHaveTextContent("supports");
    expect(within(card).getByTestId("rule-metrics")).toHaveTextContent("adds the most to the predicted category in 50% of the predictions");
    expect(within(card).getByTestId("class-weights").querySelector('li[data-class="high"]')).toHaveTextContent("−1.40");
  });

  it("a winning-rule classifier keeps its views: «Entonces», «Predicciones que decide», no weight bars", async () => {
    installApi({}, classifierV05());
    render(<App initialTab="patrones" />);
    const matrix = await screen.findByRole("table", { name: /Matriz de reglas/ });
    await waitFor(() => expect(within(matrix).getByRole("columnheader", { name: "Predicciones que decide" })).toBeInTheDocument());
    expect(within(matrix).getByRole("columnheader", { name: "Entonces" })).toBeInTheDocument();
    expect(screen.queryByTestId("class-weights")).toBeNull();
    expect(cards()[0]!.querySelector('[data-testid="rule-metrics"]')).toHaveTextContent("decide el 40 % de las predicciones");
  });

  it("the hovercard's figures: the share where it adds the most, how often those are right, and without it", () => {
    const data = mixtureV07();
    const rule = data.rules!.rules[0]!;
    const figures = ruleFigures({ rule, importance: data.importance!, weighting: data.rules!.inference.rule_weighting, unit: "" });
    expect(figures.map((f) => f.key)).toEqual(["top", "hits", "decisive"]);
    expect(figures.map((f) => f.value)).toEqual([pct(0.5), pct(0.9), pct(0.3)]);
    expect(figures.map((f) => f.label).join(" ")).not.toMatch(/decid/i);
  });

  it("¿Por qué aquí?: the scores, what each rule that holds adds to each category, and the top rule", () => {
    const data = mixtureV07();
    const t = data.traces!.find((x) => x.prediction.label && x.prediction.top_rule_id)!;
    render(<WhyHerePanel entityName="E" state={{ status: "ok", data: t }} rules={data.rules!} selectedRuleId={null} onSelectRule={() => {}} scheme={data.rules!.target_scheme} />);
    const panel = screen.getByTestId("mixture-trace");
    expect(screen.getByTestId("predicted-label")).toHaveAttribute("data-class", t.prediction.label!);
    expect(within(panel).getByTestId("top-rule-note")).toHaveTextContent(`es la regla que más suma a ${t.prediction.label}`);
    const scores = within(panel).getByRole("table", { name: "Puntuación de cada categoría" });
    for (const [c, v] of Object.entries(t.prediction.class_scores!)) expect(scores.querySelector(`tr[data-class="${c}"] strong`)).toHaveAttribute("data-raw", String(v));
    const adds = within(panel).getByRole("table", { name: /Lo que suma cada regla que se cumple/ });
    const holding = t.rules.filter((r) => r.firing_strength > 0);
    expect(adds.querySelectorAll("tbody tr")).toHaveLength(holding.length);
    for (const r of holding)
      for (const [c, v] of Object.entries(r.class_contributions_centred!)) expect(adds.querySelector(`tr[data-rule="${r.rule_id}"] td[data-class="${c}"] [data-raw]`)).toHaveAttribute("data-raw", String(v));
    // no winning-rule wording, no association table, no «contribución»
    expect(screen.queryByTestId("winning-rule-note")).toBeNull();
    expect(document.body.textContent!.replace(/[Nn]inguna regla decide sola/g, "")).not.toMatch(/decid|ganador|contribuci/i);
  });

  it("¿Por qué aquí? in English", () => {
    setLang("en");
    const data = mixtureV07();
    const t = data.traces!.find((x) => x.prediction.label && x.prediction.top_rule_id)!;
    render(<WhyHerePanel entityName="E" state={{ status: "ok", data: t }} rules={data.rules!} selectedRuleId={null} onSelectRule={() => {}} scheme={data.rules!.target_scheme} />);
    expect(screen.getByTestId("top-rule-note")).toHaveTextContent(`adds the most to ${t.prediction.label}`);
    expect(screen.getByRole("table", { name: "Score of each category" })).toBeInTheDocument();
    expect(document.body.textContent!.replace(/No single rule decides/g, "")).not.toMatch(/decid|winn|contribut/i);
  });
});
