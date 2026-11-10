import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { fmtNum } from "../lib/format";
import { describe, expect, it, vi } from "vitest";
import type { RuleDefinition } from "../api/types";
import { rules } from "../test/fixtures";
import * as cls from "../test/fixturesClass";
import { RuleRail } from "./RuleRail";

const base = rules.rules;
/** R02 shares R01's antecedents (as a GA can produce) and R03 carries published metrics. */
const withMetrics: RuleDefinition[] = [
  { ...base[0]!, metrics: { n_antecedents: 2, mean_activation: 0.1234, "activation_frequency_tau0.5": 0.0567 } },
  { ...base[0]!, rule_id: "R02", position: 1, duplicate_of: "R01", metrics: { n_antecedents: 2, mean_activation: 0.1234 } },
  base[2]!,
];

describe("RuleRail", () => {
  it("badges a duplicate with its first rule and never merges it", () => {
    render(<RuleRail rules={withMetrics} selectedId={null} onSelect={() => {}} />);
    const list = screen.getByRole("list");
    expect(within(list).getAllByRole("listitem")).toHaveLength(3);
    const r2 = screen.getByRole("button", { name: /^Regla R02/ });
    expect(r2).toHaveTextContent("mismas condiciones que R01 (dispara igual)");
    expect(screen.getByRole("button", { name: /^Regla R01/ })).not.toHaveTextContent("mismas condiciones");
  });

  it("labels the published metrics by name and never calls them importance or probability", () => {
    const { container } = render(<RuleRail rules={withMetrics} selectedId={null} onSelect={() => {}} />);
    const r1 = screen.getByRole("button", { name: /^Regla R01/ });
    expect(r1).toHaveTextContent("activación media 0,123");
    expect(r1).toHaveTextContent("frecuencia de activación ≥ 0,5 0,057");
    expect(container.textContent).not.toMatch(/importanc|probabilidad|%/i);
  });

  it("filters by free text on feature or term, and by feature", async () => {
    const user = userEvent.setup();
    render(<RuleRail rules={base} selectedId={null} onSelect={() => {}} />);
    expect(screen.getByRole("status")).toHaveTextContent("3 de 3 reglas");
    await user.type(screen.getByRole("searchbox"), "wind");
    const shown = screen.getAllByRole("button", { name: /^Regla/ }).map((b) => b.textContent?.slice(0, 3));
    const expected = base.filter((r) => r.antecedents.some((a) => a.feature.includes("wind"))).map((r) => r.rule_id);
    expect(shown).toEqual(expected);
    expect(screen.getByRole("status")).toHaveTextContent(`${expected.length} de 3 reglas`);
    await user.clear(screen.getByRole("searchbox"));
    await user.type(screen.getByRole("searchbox"), "zzz");
    expect(screen.getByText("Ninguna regla coincide con el filtro.")).toBeInTheDocument();
    await user.clear(screen.getByRole("searchbox"));
    await user.selectOptions(screen.getByLabelText("Variable"), "no2_t");
    expect(screen.getAllByRole("button", { name: /^Regla/ }).length).toBe(base.filter((r) => r.antecedents.some((a) => a.feature === "no2_t")).length);
  });

  it("selects a rule on click", async () => {
    const onSelect = vi.fn();
    render(<RuleRail rules={base} selectedId="R01" onSelect={onSelect} />);
    await userEvent.setup().click(screen.getByRole("button", { name: /^Regla R03/ }));
    expect(onSelect).toHaveBeenCalledWith("R03");
    expect(screen.getByRole("button", { name: /^Regla R01/ })).toHaveAttribute("aria-pressed", "true");
  });
});

describe("RuleRail for a classifier", () => {
  it("shows each consequent as a coloured class chip with the rule weight labelled as the dominance score", () => {
    render(<RuleRail rules={cls.rules.rules} selectedId={null} onSelect={() => {}} scheme={cls.scheme} weighting="dominance_score" />);
    for (const r of cls.rules.rules) {
      const btn = screen.getByRole("button", { name: new RegExp(`^Regla ${r.rule_id}:`) });
      const chip = btn.querySelector(".class-chip")!;
      expect(chip).toHaveAttribute("data-class", r.consequent.term!);
      const color = cls.scheme.classes.find((c) => c.label === r.consequent.term)!.color!;
      const rgb = [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16)).join(", ");
      expect((chip.querySelector(".class-swatch") as HTMLElement).style.background).toBe(`rgb(${rgb})`);
      expect(btn).toHaveTextContent(`peso ${fmtNum(r.weight!)}`);
    }
  });

  it("never calls the weight an importance or a probability", () => {
    const { container } = render(<RuleRail rules={cls.rules.rules} selectedId={null} onSelect={() => {}} scheme={cls.scheme} weighting="dominance_score" />);
    expect(container.textContent).not.toMatch(/importanc|probabilidad|riesgo/i);
  });
});
