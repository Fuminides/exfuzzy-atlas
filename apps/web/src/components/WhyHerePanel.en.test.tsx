import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { setLang } from "../i18n";
import { rules, scheme, trace } from "../test/fixturesClass";
import { WhyHerePanel } from "./WhyHerePanel";

afterEach(() => setLang("es"));

/** The words a firing, a weight or an association must never be called (the English mirror of the Spanish guard). */
const FORBIDDEN = /probabilit|risk|contribut|caus(e|al)|certaint|confiden/gi;

/** Every forbidden word that appears must sit inside a negation ("not a probability", "nor a … risk"), as in Spanish. */
function onlyNegated(text: string) {
  for (const m of text.matchAll(FORBIDDEN)) expect(text.slice(Math.max(0, m.index! - 60), m.index)).toMatch(/\b(not|nor|neither)\b/i);
}

describe("WhyHerePanel in English", () => {
  it("classifier: headings, the winner, the association story and the column help are in English, and every forbidden word is negated", () => {
    setLang("en");
    const t = trace("E0", "2024-01-06T10:00:00Z");
    const { container } = render(
      <WhyHerePanel entityName="Station" state={{ status: "ok", data: t }} rules={rules} selectedRuleId="R02" onSelectRule={() => {}} scheme={scheme} />,
    );
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("Why here? Station");
    expect(screen.getByRole("heading", { name: "Predicted category" })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Rules by association degree" })).toBeInTheDocument();
    expect(screen.getByTestId("winning-rule-note")).toHaveTextContent("Decided by R04, the rule with the highest association degree (activation × weight).");
    expect(screen.getByTestId("story-loser")).toHaveTextContent("R02 fires fully (1.000), the same as R04 (1.000), but its weight (0.086) is lower than that of R04 (0.112)");
    expect(screen.getByText("winner")).toBeInTheDocument();
    expect(screen.getByTestId("column-help")).toHaveTextContent("how well the inputs match the rule's antecedents.");
    const titles = [...container.querySelectorAll("[title]")].map((n) => n.getAttribute("title")).join(" ");
    const text = `${container.textContent} ${titles}`.replace(/\s+/g, " ");
    expect(text).toContain("only ranks the rules to pick a category.");
    onlyNegated(text);
  });

  it("regression: the activation note says what the activation is", () => {
    setLang("en");
    const t = trace("E0", "2024-01-06T10:00:00Z");
    const reg: typeof t = { ...t, inference: { ...t.inference, family: "tsk_zero_order" } };
    const { container } = render(<WhyHerePanel entityName="Station" state={{ status: "ok", data: reg }} rules={rules} selectedRuleId={null} onSelectRule={() => {}} />);
    expect(screen.getByRole("heading", { name: "Rules, by activation" })).toBeInTheDocument();
    expect(container).toHaveTextContent("A rule's activation says how well the inputs match its antecedents.");
    onlyNegated(container.textContent!.replace(/\s+/g, " "));
  });

  it("idle and error states are in English", () => {
    setLang("en");
    const { rerender } = render(<WhyHerePanel entityName={null} state={{ status: "idle" }} rules={rules} selectedRuleId={null} onSelectRule={() => {}} />);
    expect(screen.getByText("Pick a station on the map or in the table to see how the rules fire there.")).toBeInTheDocument();
    rerender(<WhyHerePanel entityName="Station" state={{ status: "error", error: new Error("boom") }} rules={rules} selectedRuleId={null} onSelectRule={() => {}} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Could not load the trace: boom");
  });
});
