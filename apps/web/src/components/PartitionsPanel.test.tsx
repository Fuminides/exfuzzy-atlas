import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { LinguisticVariable } from "../api/types";
import { fmt } from "../lib/format";
import { rules, trace } from "../test/fixtures";
import { PartitionsPanel } from "./PartitionsPanel";

const noop = () => {};
const variable = rules.variables.find((v) => v.feature === "no2_t")!;

const show = (v: LinguisticVariable, t: ReturnType<typeof trace> | null) =>
  render(
    <PartitionsPanel
      variable={v}
      ruleTerm="High"
      ruleId="R01"
      siblings={["no2_t", "wind_speed_t"]}
      onVariable={noop}
      onClose={noop}
      trace={t}
      stationName="Station"
    />,
  );

describe("PartitionsPanel", () => {
  it("draws each trapezoidal term as exactly the four param vertices (a,0) (b,1) (c,1) (d,0)", () => {
    const { container } = show(variable, null);
    const lines = container.querySelectorAll("polyline.term");
    expect(lines).toHaveLength(variable.terms.length);
    for (const term of variable.terms) {
      const line = container.querySelector(`polyline[data-term="${term.name}"]`)!;
      const [a, b, c, d] = term.params;
      expect(JSON.parse(line.getAttribute("data-vertices")!)).toEqual([[a, 0], [b, 1], [c, 1], [d, 0]]);
      expect(line.getAttribute("points")!.split(" ")).toHaveLength(4);
    }
  });

  it("places vertices on the axis by the variable's domain, in order, with no extra math", () => {
    const { container } = show(variable, null);
    const [lo, hi] = variable.domain as [number, number];
    const xs = (name: string) =>
      container.querySelector(`polyline[data-term="${name}"]`)!.getAttribute("points")!.split(" ").map((p) => Number(p.split(",")[0]));
    const low = xs("Low");
    // Low = [0, 0, 20, 40] on [0, 200]: x grows with the param, both ends of the shoulder coincide, 0 sits on the left edge.
    expect(low[0]).toBe(low[1]);
    expect(low[2]! > low[1]!).toBe(true);
    expect(low[3]! > low[2]!).toBe(true);
    const high = xs("High");
    expect(high[2]).toBe(high[3]); // [60, 80, 200, 200]: ends on the right edge of the domain
    expect(high[3]).toBeGreaterThan(low[3]!);
    expect(lo).toBe(0);
    expect(hi).toBe(200);
  });

  it("marks the station's input value and shows the mu from the trace, never computed", () => {
    const t = trace("SYN_A", "07:00");
    const { container } = show(variable, t);
    const input = t.feature_values.find((f) => f.feature === "no2_t")!.value!;
    expect(screen.getByTestId("input-marker")).toHaveAttribute("data-value", String(input));
    // Every antecedent of the trace on this variable shows up, with the trace's raw membership.
    const traced = t.rules.flatMap((r) => r.antecedents).filter((a) => a.feature === "no2_t");
    expect(traced.length).toBeGreaterThan(0);
    for (const a of traced) {
      const dot = container.querySelector(`circle[data-term="${a.term}"]`)!;
      expect(dot).toHaveAttribute("data-mu", String(a.membership));
      const row = container.querySelector<HTMLElement>(`tr[data-term="${a.term}"]`)!;
      expect(within(row).getByText(fmt(a.membership))).toHaveAttribute("data-raw", String(a.membership));
    }
    // A term no rule uses has no mu in the trace: said so, not computed.
    const unused = variable.terms.filter((term) => !traced.some((a) => a.term === term.name));
    for (const term of unused) {
      expect(within(container.querySelector<HTMLElement>(`tr[data-term="${term.name}"]`)!).getByText("ninguna regla usa este término")).toBeInTheDocument();
    }
  });

  it("lists gaussian terms with their params instead of drawing a curve", () => {
    const gaussian: LinguisticVariable = {
      feature: "g",
      domain: [0, 10],
      terms: [
        { name: "Mid", membership_type: "gaussian", params: [5, 2] },
        { name: "Hi", membership_type: "triangular", params: [5, 8, 8, 10] },
      ],
    };
    const { container } = show(gaussian, null);
    expect(container.querySelectorAll("polyline.term")).toHaveLength(1);
    expect(container.querySelector('polyline[data-term="Mid"]')).toBeNull();
    const row = screen.getByRole("row", { name: /^Mid/ });
    expect(row).toHaveTextContent("[5, 2]");
    expect(row).toHaveTextContent("no se dibuja");
    // Triangular uses the same four-vertex form.
    expect(JSON.parse(container.querySelector('polyline[data-term="Hi"]')!.getAttribute("data-vertices")!)).toEqual([[5, 0], [8, 1], [8, 1], [10, 0]]);
  });

  it("asks for a station when there is no trace and says so when the input is missing", () => {
    show(variable, null);
    expect(screen.getByText(/Elige una estación para marcar/)).toBeInTheDocument();
    expect(screen.queryByTestId("input-marker")).toBeNull();
  });
});
