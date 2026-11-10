import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { setLang } from "../i18n";
import { boundedSum, condKey, extraConditions } from "../lib/conditions";
import { namesFor, ruleSentence } from "../lib/labels";
import { atLeast, earlyHours, hour, lateNight, rules, temperature, traceWith, variables } from "../test/fixturesConditions";
import { Naming } from "./Naming";
import { PartitionsPanel } from "./PartitionsPanel";
import { RuleSentenceView } from "./RuleSentenceView";
import { TermGlyph } from "./TermGlyph";

const noop = () => {};
const FORBIDDEN = /probabilidad|riesgo|contribuci|causa|certeza|confianza|probabilit|risk|contribut|caus(e|al)|certaint|confiden/i;

afterEach(() => setLang("es"));

const show = (variable: typeof hour, opts: { withConditions?: boolean; trace?: ReturnType<typeof traceWith> | null; ruleCondition?: typeof earlyHours | typeof atLeast | null } = {}) =>
  render(
    <Naming variables={variables} scheme={null} rules={rules}>
      <PartitionsPanel
        variable={variable}
        ruleTerm={null}
        conditions={opts.withConditions === false ? [] : extraConditions(rules, variable.feature)}
        ruleCondition={opts.ruleCondition ?? null}
        ruleId="R01"
        siblings={["temperature", "local_hour"]}
        onVariable={noop}
        onClose={noop}
        trace={opts.trace ?? null}
        stationName="Station"
      />
    </Naming>,
  );

describe("PartitionsPanel with ordinal and compound conditions (v0.8)", () => {
  it("draws a variable with no extra condition in use exactly as before", () => {
    const { container } = show(hour, { withConditions: false });
    expect(container.querySelectorAll("polyline.term")).toHaveLength(hour.terms.length);
    expect(container.querySelector(".term--sum")).toBeNull();
    expect(screen.queryByTestId("partition-conditions")).toBeNull();
    expect(container.querySelectorAll("tbody tr")).toHaveLength(hour.terms.length);
  });

  it("adds one dashed bounded-sum line per compound the model uses, on the same axes, with its display name", () => {
    const { container } = show(hour);
    const sums = container.querySelectorAll("polyline.term--sum");
    expect(sums).toHaveLength(2);
    expect(container.querySelectorAll("polyline.term:not(.term--sum)")).toHaveLength(hour.terms.length);
    const early = container.querySelector(`g[data-condition="${condKey(earlyHours)}"]`)!;
    expect(within(early as HTMLElement).getByText("Primeras horas")).toBeInTheDocument();
    // the line follows min(1, sum of the memberships) of the terms it covers, over the same x scale as the base terms
    const covered = hour.terms.filter((t) => earlyHours.terms.includes(t.name as never));
    const pts = early.querySelector("polyline")!.getAttribute("points")!.split(" ").map((p) => p.split(",").map(Number) as [number, number]);
    const baseLow = container.querySelector('polyline[data-term="Madrugada"]')!.getAttribute("points")!.split(" ").map((p) => p.split(",").map(Number) as [number, number]);
    expect(pts[0]![0]).toBe(baseLow[0]![0]); // starts at the left edge of the domain, like the base terms
    expect(pts.every(([, y]) => Number.isFinite(y))).toBe(true);
    expect(boundedSum(covered, 8)).toBeCloseTo(1, 12);
    // a compound without a display name is labelled by its internal name
    expect(container.querySelector(`g[data-condition="${condKey(lateNight)}"]`)).toHaveTextContent("late_night");
  });

  it("lists each condition in the table with what it covers and no base term is marked as used", () => {
    const { container } = show(hour, { ruleCondition: earlyHours });
    const row = container.querySelector<HTMLElement>(`tr[data-condition="${condKey(earlyHours)}"]`)!;
    expect(row).toHaveAttribute("aria-current", "true");
    expect(row).toHaveTextContent("Primeras horas");
    expect(row).toHaveTextContent("Madrugada o Mañana, 0–10 h");
    expect(row).toHaveTextContent("suma acotada");
    expect(container.querySelectorAll('tr[data-term][aria-current="true"]')).toHaveLength(0);
    expect(container.querySelector(".term--rule.term--sum")).not.toBeNull();
    expect(screen.getByTestId("partition-conditions")).toHaveTextContent("La línea discontinua suma las pertenencias");
  });

  it("shows the ordinal condition as «al menos Media» and takes the trace's μ without moving it to the base term", () => {
    const t = traceWith();
    const { container } = show(temperature, { trace: t, ruleCondition: atLeast });
    const row = container.querySelector<HTMLElement>(`tr[data-condition="${condKey(atLeast)}"]`)!;
    expect(row).toHaveTextContent("al menos media");
    expect(within(row).getByText("1,000")).toHaveAttribute("data-raw", "1");
    expect(container.querySelector(`circle[data-condition="${condKey(atLeast)}"]`)).toHaveAttribute("data-mu", "1");
    // the base term "Medium" got no μ from the at-least condition
    expect(container.querySelector('circle[data-term="Medium"]')).toBeNull();
    expect(container.querySelector('tr[data-term="Medium"]')).toHaveTextContent("ninguna regla usa este término");
    // R03's plain "High" keeps its μ on the base term
    expect(container.querySelector('circle[data-term="High"]')).toHaveAttribute("data-mu", "0.3");
  });

  it("marks the trace's μ of a compound from its operator and terms, not its internal name", () => {
    const { container } = show(hour, { trace: traceWith(), ruleCondition: earlyHours });
    expect(container.querySelector(`circle[data-condition="${condKey(earlyHours)}"]`)).toHaveAttribute("data-mu", "0.6");
    expect(container.querySelector('circle[data-term="early_hours"]')).toBeNull();
  });

  it("speaks English with the English display names", () => {
    setLang("en");
    const { container } = show(hour, { ruleCondition: earlyHours });
    const row = container.querySelector<HTMLElement>(`tr[data-condition="${condKey(earlyHours)}"]`)!;
    expect(row).toHaveTextContent("Early hours");
    expect(row).toHaveTextContent("Madrugada or Mañana, 0–10 h");
    expect(row).toHaveTextContent("bounded sum");
    expect(screen.getByTestId("partition-conditions")).toHaveTextContent("The dashed line adds up the memberships");
    expect(screen.getByTestId("partition-conditions").textContent).not.toMatch(FORBIDDEN);
    setLang("es");
    show(temperature);
    expect(document.body.textContent).not.toMatch(FORBIDDEN);
  });
});

describe("rule sentence and glyph with v0.8 conditions", () => {
  it("writes «al menos» after the verb and the compound's constituents in the tooltip", () => {
    const label = (f: string) => (f === "temperature" ? "Temperatura" : "Hora local");
    const { container } = render(
      <Naming variables={variables} scheme={null} rules={rules}>
        <RuleSentenceView sentence={ruleSentence(rules[0]!, label, null, namesFor(variables, null, null, rules))} />
      </Naming>,
    );
    expect(screen.getByTestId("rule-sentence")).toHaveTextContent("Si la temperatura es al menos media y la hora local es Primeras horas");
    expect(container.querySelector('em.term[title="Madrugada o Mañana, 0–10 h"]')).not.toBeNull();
  });

  it("fills the bounded sum in the glyph instead of one base term", () => {
    const { container } = render(<TermGlyph variable={hour} term="early_hours" range={[0, 23]} fill="#a05339" condition={earlyHours} />);
    expect(container.querySelectorAll("polygon.rmx-glyph-used")).toHaveLength(1);
    expect(container.querySelectorAll("polyline.rmx-glyph-term")).toHaveLength(hour.terms.length);
    const plain = render(<TermGlyph variable={hour} term="Mañana" range={[0, 23]} fill="#a05339" />);
    expect(plain.container.querySelectorAll("polyline.rmx-glyph-term")).toHaveLength(hour.terms.length - 1);
  });
});
