import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { fmt, fmtNum } from "../lib/format";
import { labelerFor, termLabel } from "../lib/labels";
import { rules, trace } from "../test/fixtures";

const labelOf = labelerFor(rules.variables);
import { WhyHerePanel } from "./WhyHerePanel";

const noop = () => {};
const show = (t: ReturnType<typeof trace>, selected: string | null) =>
  render(
    <WhyHerePanel entityName="Station" state={{ status: "ok", data: t }} rules={rules} selectedRuleId={selected} onSelectRule={noop} />,
  );

describe("WhyHerePanel", () => {
  it("shows every antecedent mu, the firing and the model's t-norm exactly as in the trace", () => {
    const t = trace("SYN_A", "07:00");
    const entry = t.rules.find((r) => r.antecedents.length === 2)!;
    show(t, entry.rule_id);
    for (const a of entry.antecedents) {
      const row = screen.getByRole("row", { name: new RegExp(`${labelOf(a.feature)} es ${termLabel(a.term)}`) });
      const cell = within(row).getAllByText(fmt(a.membership))[0]!;
      expect(cell).toHaveAttribute("data-raw", String(a.membership));
    }
    const firing = screen.getByText(fmt(entry.firing_strength), { selector: "[data-raw]" });
    expect(firing).toHaveAttribute("data-raw", String(entry.firing_strength));
    expect(screen.getByText(t.inference.tnorm, { selector: "code" })).toBeInTheDocument();
    expect(t.inference.tnorm).toBe("product");
    // Prediction with unit and valid time.
    expect(screen.getByText(`${fmtNum(t.prediction.value!)} µg/m³`)).toBeInTheDocument();
    // Input values with units and observation time.
    const inputs = screen.getAllByRole("table")[0]!;
    expect(within(inputs).getByRole("row", { name: /NO₂ actual/ })).toHaveTextContent("µg/m³");
  });

  it("lists the other rules ranked by firing", () => {
    const t = trace("SYN_A", "07:00");
    show(t, "R01");
    const items = within(screen.getByRole("list")).getAllByRole("listitem").map((li) => li.textContent ?? "");
    const expected = t.rules
      .filter((r) => r.rule_id !== "R01")
      .sort((a, b) => b.firing_strength - a.firing_strength)
      .map((r) => r.rule_id);
    expect(items.map((s) => s.slice(0, 3))).toEqual(expected);
  });

  it("says inference did not run when an input is missing", () => {
    show(trace("SYN_D", "08:00"), "R01");
    expect(screen.getByRole("alert")).toHaveTextContent("No se ejecutó la inferencia: falta Velocidad del viento");
    expect(screen.getByText(/sin predicción/)).toHaveTextContent("falta una entrada");
  });

  it("warns when the prediction is the fallback value", () => {
    const t = trace("SYN_C", "11:00");
    expect(t.prediction.fallback_used).toBe(true);
    show(t, "R01");
    expect(screen.getByRole("alert")).toHaveTextContent(String(t.inference.fallback));
  });
});

describe("WhyHerePanel reproducible request", () => {
  it("links the exact GET of the shown trace (model, entity and its issue time)", () => {
    const t = trace("SYN_A", "07:00");
    show(t, null);
    const link = screen.getByTestId("trace-request");
    const url = new URL(link.getAttribute("href")!, "http://atlas.local");
    expect(url.pathname).toBe(`/api/v1/entities/${encodeURIComponent(t.entity_id)}/rule-trace`);
    expect(url.searchParams.get("model_id")).toBe(t.model_id);
    expect(url.searchParams.get("at")).toBe(t.issued_at_utc);
    expect(link).toHaveTextContent(`GET ${link.getAttribute("href")}`);
  });
});
