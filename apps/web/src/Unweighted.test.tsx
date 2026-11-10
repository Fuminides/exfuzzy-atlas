import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { ModelCard, RuleTrace } from "./api/types";
import { accuracySummary } from "./components/AccuracyBlock";
import { DecidedBy } from "./components/DecidedBy";
import { RuleRail } from "./components/RuleRail";
import { PerformanceChart } from "./components/PerformanceChart";
import { WhyHerePanel } from "./components/WhyHerePanel";
import { setLang } from "./i18n";
import { associationStory } from "./lib/association";
import { performanceReport } from "./lib/performance";
import { card, rules, scheme, trace } from "./test/fixturesClass";

afterEach(() => setLang("es"));

/** The fixture trace made unweighted, as ex_fuzzy exports it: rule_weighting "none", weight 1, association = firing. */
function unweighted(t: RuleTrace, firings: Record<string, number>): RuleTrace {
  return {
    ...t,
    inference: { ...t.inference, rule_weighting: "none" },
    rules: t.rules.map((r) => {
      const f = firings[r.rule_id] ?? 0;
      return { ...r, firing_strength: f, effective_firing: f, weight: 1, association_degree: f };
    }),
  };
}

const base = trace("E0", "2024-01-06T10:00:00Z");
const ids = base.rules.map((r) => r.rule_id);
// two rules tie at 1.0: the first in the model's order wins
const tied = unweighted({ ...base, prediction: { ...base.prediction, winning_rule_id: ids[0]! } }, { [ids[0]!]: 1, [ids[1]!]: 1, [ids[2]!]: 0.4 });

describe("an unweighted classifier (rule_weighting: none)", () => {
  it("tells the story as 'the rule that fires most, the first in model order on a tie', with no weight or association", () => {
    const story = associationStory(tied.rules, ids[0]!, true)!;
    expect(story.winner).toBe(`${ids[0]} decide la categoría. Se activa con grado 1,000, igual que ${ids[1]}. En este modelo las reglas no llevan peso y, ante un empate, decide la primera en el orden del modelo.`);
    expect(story.loser).toBeNull();
    setLang("en");
    expect(associationStory(tied.rules, ids[0]!, true)!.winner).toContain("on a tie, the first in the model's order decides");
  });

  it("¿Por qué aquí? drops the weight and association columns and sorts by activation, ties in model order", () => {
    render(<WhyHerePanel entityName="Station" state={{ status: "ok", data: tied }} rules={rules} selectedRuleId={null} onSelectRule={() => {}} scheme={scheme} />);
    const table = screen.getByRole("table", { name: "Reglas por activación" });
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).not.toContain(expect.stringMatching(/Peso|Asociación/));
    expect(within(table).queryByText(/Asociación/)).toBeNull();
    const order = within(table).getAllByRole("row").slice(1).map((r) => r.getAttribute("data-rule"));
    expect(order.slice(0, 3)).toEqual([ids[0], ids[1], ids[2]]);
    expect(screen.getByTestId("unweighted-note")).toHaveTextContent("no llevan peso");
    expect(screen.getByTestId("winning-rule-note")).toHaveTextContent("la regla con mayor activación (ante un empate, la primera en el orden del modelo)");
    expect(screen.queryByText(/activación × peso/)).toBeNull();
  });

  it("«La decidió…» and the rule list say nothing about a weight", () => {
    render(<DecidedBy ruleId={ids[0]!} rules={rules.rules} scheme={scheme} unweighted />);
    expect(screen.getByTestId("decided-by")).toHaveTextContent("Es la regla que más se activó (ante un empate, la primera en el orden del modelo)");
    expect(screen.getByTestId("decided-by")).not.toHaveTextContent("mayor peso");
    render(<RuleRail rules={rules.rules.map((r) => ({ ...r, weight: 1 }))} selectedId={null} onSelect={() => {}} scheme={scheme} weighting="none" />);
    expect(screen.queryByText(/· peso 1/)).toBeNull();
  });
});

describe("the same hour yesterday (persistence_24h) next to the model", () => {
  const rows = (card.metrics?.rows ?? []).filter((r) => r.estimator.startsWith("exfuzzy") || r.estimator === "persistence");
  const own = rows.find((r) => r.estimator.startsWith("exfuzzy") && r.metric === "macro_f1" && (r.slice ?? "all") === "all")!;
  const withYday = {
    ...card,
    metrics: {
      ...card.metrics!,
      rows: [
        ...card.metrics!.rows,
        { estimator: "persistence_24h", metric: "macro_f1", value: own.value, n: own.n, slice: "all" },
        { estimator: "persistence_24h", metric: "accuracy", value: 0.8, n: own.n, slice: "all" },
      ],
    },
  } as ModelCard;

  it("the performance report has a bar for it and says the model is on a par with it", () => {
    expect(performanceReport(withYday, "macro_f1")!.bars.find((b) => b.key === "persistence_24h")?.value).toBe(own.value);
    render(<PerformanceChart card={withYday} rules={rules} period="2024" unit="" context="Zona · +6 h" />);
    const bar = screen.getByTestId("perf-bars").querySelector('[data-key="persistence_24h"]')!;
    expect(bar).toHaveTextContent("Repetir la de ayer a la misma hora");
    const standing = [...screen.getByTestId("perf-standing").querySelectorAll("li")].find((li) => li.textContent?.includes("ayer"))!;
    expect(standing).toHaveAttribute("data-standing", "par");
  });

  it("the model-quality summary adds it, and nothing when the report has no such row", () => {
    expect(accuracySummary(withYday, "")).toMatch(/Repetir la categoría de ayer a la misma hora acierta el 80\s%/);
    expect(accuracySummary(card, "")).not.toMatch(/ayer a la misma hora/);
  });
});
