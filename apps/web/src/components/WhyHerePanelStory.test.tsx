import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { RuleTrace } from "../api/types";
import * as cls from "../test/fixturesClass";
import * as real from "../test/fixturesReal";
import { WhyHerePanel } from "./WhyHerePanel";

const nyc = () => real.nyc.traces.find((t) => t.entity_id === real.NYC_ZONE && t.issued_at_utc === real.NYC_EVENING)!;
const show = (t: RuleTrace, props: Partial<Parameters<typeof WhyHerePanel>[0]> = {}) =>
  render(
    <WhyHerePanel
      entityName="Zona"
      state={{ status: "ok", data: t }}
      rules={real.nyc.rules}
      selectedRuleId="R08"
      onSelectRule={() => {}}
      scheme={real.nyc.card.target_scheme}
      relativeScheme
      {...props}
    />,
  );
const table = () => screen.getByRole("table", { name: "Reglas por grado de asociación" });

describe("¿Por qué aquí? separates how much a rule fires from how much it weighs", () => {
  it("explains the winner and the strongest-firing loser with the trace's numbers", () => {
    show(nyc());
    expect(screen.getByTestId("story-winner")).toHaveTextContent(
      "R01 decide la categoría. Se activa con grado 0,894 y su peso es 0,062, así que su asociación (activación × peso) es 0,056, la mayor de todas las reglas.",
    );
    expect(screen.getByTestId("story-loser")).toHaveTextContent(
      "R08 se activa por completo (1,000), más que R01 (0,894), pero su peso (0,031) es menor que el de R01 (0,062), así que su asociación (0,031) queda por debajo de la de R01 (0,056).",
    );
    // the numbers in the sentence are the ones in the table, which are the trace's raw values
    const r08 = within(table()).getAllByRole("row").find((r) => r.getAttribute("data-rule") === "R08")!;
    const t = nyc().rules.find((r) => r.rule_id === "R08")!;
    expect([...r08.querySelectorAll("[data-raw]")].map((n) => n.getAttribute("data-raw"))).toEqual([
      String(t.firing_strength),
      String(t.weight),
      String(t.association_degree),
    ]);
  });

  it("has a column each for activación, peso and asociación, with a tooltip on the weight that says where it comes from", () => {
    show(nyc());
    const heads = within(table()).getAllByRole("columnheader");
    expect(heads.map((h) => h.textContent)).toEqual([
      "Regla",
      "Categoría",
      "Activación cuánto se activa",
      "peso cuánto pesa",
      "Asociación decide",
    ]);
    const weight = heads[3]!;
    expect(weight.getAttribute("title")).toContain("sale de los datos de entrenamiento");
    expect(weight.getAttribute("title")).toContain("con qué frecuencia aparece la clase");
    expect(weight.getAttribute("title")).not.toMatch(/probabilidad|confianza|riesgo/);
    // the same text is on the page for keyboard and touch users
    expect(screen.getByTestId("column-help")).toHaveTextContent("sale de los datos de entrenamiento");
    // the bars are decoration: three per rule at most, hidden from assistive technology
    const bars = table().querySelectorAll(".mini-bar");
    expect(bars.length).toBe(nyc().rules.length * 3);
    expect([...bars].every((b) => b.getAttribute("aria-hidden") === "true")).toBe(true);
  });

  it("never calls the weight or the association a probability, confidence, importance or risk (only to deny it)", () => {
    show(nyc());
    const text = document.body.textContent!;
    for (const sentence of text.split(/(?<=[.!?])\s+/)) {
      if (/probabilidad|confianza|importancia|riesgo/i.test(sentence)) expect(sentence).toMatch(/\bno\b|\bni\b|\bnunca\b/i);
    }
  });

  it("shows tiny weights and associations with two significant digits instead of 0.000", () => {
    const t = nyc();
    const tiny: RuleTrace = {
      ...t,
      rules: t.rules.map((r) => (r.rule_id === "R03" ? { ...r, weight: 0.00064, association_degree: 0.00064 } : r)),
    };
    show(tiny);
    const r03 = within(table()).getAllByRole("row").find((r) => r.getAttribute("data-rule") === "R03")!;
    expect(r03).toHaveTextContent("0,00064");
    expect(r03).not.toHaveTextContent("0,001");
  });

  it("explains nothing when no rule won (no rule fires)", () => {
    const t = nyc();
    show({ ...t, prediction: { ...t.prediction, label: null, winning_rule_id: null, missing_reason: "prediction_unavailable" } });
    expect(screen.queryByTestId("association-story")).toBeNull();
  });
});

describe("'sin referencia' is NYC wording", () => {
  const noRef = () => real.nyc.traces.find((t) => t.entity_id === real.NYC_NO_REFERENCE[0] && t.issued_at_utc === real.NYC_EVENING)!;

  it("NYC: a zone with observed demand and no reference level says so", () => {
    show(noRef(), { observed: { value: 12, label: null } });
    expect(screen.getByTestId("no-reference")).toHaveTextContent("sin referencia");
  });

  it("an absolute scheme (Madrid ICA) with the same pattern says 'sin predicción', never 'sin referencia'", () => {
    const t = cls.trace("E1", "2024-01-06T10:00:00Z");
    const silent: RuleTrace = {
      ...t,
      prediction: { ...t.prediction, label: null, winning_rule_id: null, missing_reason: "prediction_unavailable" },
    };
    render(
      <WhyHerePanel entityName="E1" state={{ status: "ok", data: silent }} rules={cls.rules} selectedRuleId={null} onSelectRule={() => {}} scheme={cls.scheme} observed={{ value: 12, label: null }} />,
    );
    expect(screen.queryByTestId("no-reference")).toBeNull();
    expect(document.body).not.toHaveTextContent(/sin referencia|nivel de referencia/);
    expect(screen.getByText(/sin predicción/)).toHaveTextContent("ninguna regla se activó");
  });
});
