import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { fmt } from "../lib/format";
import { rules, scheme, trace } from "../test/fixturesClass";
import { WhyHerePanel } from "./WhyHerePanel";

const show = (t: ReturnType<typeof trace>, selected: string | null, extra: Partial<Parameters<typeof WhyHerePanel>[0]> = {}) =>
  render(
    <WhyHerePanel
      entityName="Station"
      state={{ status: "ok", data: t }}
      rules={rules}
      selectedRuleId={selected}
      onSelectRule={() => {}}
      scheme={scheme}
      {...extra}
    />,
  );

describe("WhyHerePanel for a winning-rule classifier", () => {
  const t = trace("E0", "2024-01-06T10:00:00Z");
  const rows = () => within(screen.getByRole("table", { name: "Reglas por grado de asociación" })).getAllByRole("row").slice(1);

  it("lists every rule with firing, weight and association exactly as in the trace, sorted by association", () => {
    show(t, "R01");
    const ordered = [...t.rules].sort((a, b) => b.association_degree! - a.association_degree! || a.rule_id.localeCompare(b.rule_id));
    expect(rows().map((r) => r.getAttribute("data-rule"))).toEqual(ordered.map((r) => r.rule_id));
    for (const entry of t.rules) {
      const row = rows().find((r) => r.getAttribute("data-rule") === entry.rule_id)!;
      const raw = [...row.querySelectorAll("[data-raw]")].map((n) => n.getAttribute("data-raw"));
      expect(raw).toEqual([String(entry.firing_strength), String(entry.weight), String(entry.association_degree)]);
    }
    // association = firing x weight, as the contract validator enforces.
    for (const e of t.rules) expect(e.association_degree).toBeCloseTo(e.firing_strength * e.weight!, 9);
  });

  it("highlights the winning rule given by winning_rule_id and says it decided the category", () => {
    expect(t.prediction.winning_rule_id).toBe("R04");
    show(t, "R02");
    const winners = rows().filter((r) => r.getAttribute("data-winner") === "true");
    expect(winners.map((r) => r.getAttribute("data-rule"))).toEqual([t.prediction.winning_rule_id]);
    expect(winners[0]).toHaveTextContent("ganadora");
    expect(screen.getByTestId("winning-rule-note")).toHaveTextContent("La categoría la decidió R04, la regla con mayor grado de asociación");
    // R02 fires too, but with lower association: it is selected, not the winner.
    const r02 = rows().find((r) => r.getAttribute("data-rule") === "R02")!;
    expect(r02.getAttribute("data-winner")).toBeNull();
    expect(r02).toHaveTextContent("(seleccionada)");
  });

  it("shows the predicted label with its scheme colour and the observed concentration and category", () => {
    show(t, null, { observed: { value: 42.1, label: "mid" } });
    const label = screen.getByTestId("predicted-label");
    expect(label).toHaveAttribute("data-class", t.prediction.label!);
    const high = scheme.classes.find((c) => c.label === t.prediction.label)!;
    expect((label.querySelector(".class-swatch") as HTMLElement).style.background).toBe("rgb(255, 51, 0)");
    expect(high.color).toBe("#FF3300");
    const observed = screen.getByTestId("observed-class");
    expect(observed).toHaveTextContent("42,1");
    expect(observed.querySelector(".class-chip")).toHaveAttribute("data-class", "mid");
  });

  it("shows no numeric prediction", () => {
    show(t, null);
    expect(t.prediction.value).toBeNull();
    expect(screen.queryByText("Predicción del modelo")).toBeNull();
  });

  it("selects a rule from the association table", async () => {
    const onSelectRule = vi.fn();
    show(t, null, { onSelectRule });
    await userEvent.setup().click(screen.getByRole("button", { name: "Seleccionar regla R02" }));
    expect(onSelectRule).toHaveBeenCalledWith("R02");
  });

  it("shows 'sin predicción' with its reason and no association table when an input is missing", () => {
    show(trace("E0", "2024-01-06T09:00:00Z"), null);
    expect(screen.getByRole("alert")).toHaveTextContent("No se ejecutó la inferencia: falta Variable exógena");
    expect(screen.getByText(/sin predicción/)).toHaveTextContent("falta una entrada");
    expect(screen.queryByTestId("predicted-label")).toBeNull();
    expect(screen.queryByTestId("winning-rule-note")).toBeNull();
    expect(screen.queryByRole("table", { name: "Reglas por grado de asociación" })).toBeNull();
  });

  it("explains a null label with inputs present (no rule fires) and highlights no winner", () => {
    const base = trace("E1", "2024-01-06T10:00:00Z");
    const silent = {
      ...base,
      prediction: { ...base.prediction, label: null, winning_rule_id: null, missing_reason: "prediction_unavailable" as const },
      rules: base.rules.map((r) => ({ ...r, firing_strength: 0, effective_firing: 0, association_degree: 0 })),
    };
    show(silent, null);
    expect(screen.getByText(/sin predicción/)).toHaveTextContent("ninguna regla se activó");
    expect(screen.getByText(/ninguna regla se activó/)).toBeInTheDocument();
    expect(rows().some((r) => r.getAttribute("data-winner") === "true")).toBe(false);
    expect(screen.getAllByText(fmt(0)).length).toBeGreaterThan(0);
  });
});
