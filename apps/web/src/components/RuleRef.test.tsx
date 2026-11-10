import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { setLang } from "../i18n";
import { served } from "../test/fixturesPatterns";
import { Naming } from "./Naming";
import { RuleLookupProvider, RuleRef } from "./RuleRef";

afterEach(() => setLang("es"));

const de = served("de_h6");
const scheme = de.rules.target_scheme ?? null;
const [first, second] = [...de.importance.rules].sort((a, b) => (b.decided_share ?? 0) - (a.decided_share ?? 0));

function inModel(children: React.ReactNode, importance = de.importance) {
  return render(
    <Naming variables={de.rules.variables} scheme={scheme}>
      <RuleLookupProvider model={de.rules} importance={importance} scheme={scheme} unit="">
        {children}
      </RuleLookupProvider>
    </Naming>,
  );
}

describe("RuleRef: an inline rule id that shows the rule's card", () => {
  it("an id the model does not have, or no lookup at all, is plain text", () => {
    const { container } = inModel(<RuleRef id="R99" />);
    expect(container.querySelector("button")).toBeNull();
    expect(container).toHaveTextContent("R99");
    const bare = render(<RuleRef id={first!.rule_id} />);
    expect(bare.container.querySelector("button")).toBeNull();
    expect(bare.container).toHaveTextContent(first!.rule_id);
  });

  it("hover opens the card after a short delay, with the sentence, the terms and the published figures; leaving closes it", async () => {
    const user = userEvent.setup();
    inModel(<RuleRef id={first!.rule_id} />);
    const button = screen.getByRole("button", { name: first!.rule_id });
    expect(button).toHaveAttribute("aria-expanded", "false");
    await user.hover(button);
    const card = await screen.findByRole("tooltip");
    expect(button).toHaveAttribute("aria-describedby", card.id);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(card).toHaveTextContent(`Regla ${first!.rule_id}`);
    expect(screen.getByTestId("rule-hovercard-sentence")).toHaveTextContent(/^Si .+ → .+$/);
    expect(card.querySelectorAll(".rhc-term")).toHaveLength(de.rules.rules.find((r) => r.rule_id === first!.rule_id)!.antecedents.length);
    expect(card.querySelector('[data-figure="decided"]')).toHaveTextContent("Predicciones que decide");
    expect(card.querySelector('[data-figure="hits"]')).toHaveTextContent("Acierta");
    expect(card.textContent).not.toMatch(/probabilidad|importancia|activaci|causa|riesgo|contribuc/i);
    await user.unhover(button);
    await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull());
    expect(button).not.toHaveAttribute("aria-describedby");
  });

  it("keyboard focus opens it at once; Escape closes it, keeps the focus and does not reach the panel around it", async () => {
    const user = userEvent.setup();
    const onPanelEscape = vi.fn();
    inModel(
      <section onKeyDown={(e) => e.key === "Escape" && onPanelEscape()}>
        <RuleRef id={first!.rule_id} />
      </section>,
    );
    const button = screen.getByRole("button", { name: first!.rule_id });
    act(() => button.focus());
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("tooltip")).toBeNull();
    expect(button).toHaveFocus();
    expect(onPanelEscape).not.toHaveBeenCalled();
    await user.keyboard("{Escape}"); // closed already: the panel gets it
    expect(onPanelEscape).toHaveBeenCalledOnce();
  });

  it("a tap opens it and a second tap closes it (touch has no hover)", () => {
    inModel(<RuleRef id={first!.rule_id} />);
    const button = screen.getByRole("button", { name: first!.rule_id });
    fireEvent.touchStart(button);
    fireEvent.click(button);
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
    expect(button).toHaveAttribute("aria-expanded", "true");
    fireEvent.touchStart(button);
    fireEvent.click(button);
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("a tap elsewhere closes an open card", () => {
    inModel(
      <>
        <RuleRef id={first!.rule_id} />
        <p>fuera</p>
      </>,
    );
    fireEvent.click(screen.getByRole("button", { name: first!.rule_id }));
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByText("fuera"));
    expect(screen.queryByRole("tooltip")).toBeNull();
  });

  it("with an action of its own, a click runs it (no disclosure state) and hover still shows the card", async () => {
    const user = userEvent.setup();
    const onPick = vi.fn();
    inModel(<RuleRef id={second!.rule_id} onClick={() => onPick(second!.rule_id)} className="rule-legend-btn" buttonProps={{ "aria-pressed": false }} />);
    const button = screen.getByRole("button", { name: second!.rule_id });
    expect(button).not.toHaveAttribute("aria-expanded");
    expect(button).toHaveClass("rule-legend-btn");
    await user.click(button);
    expect(onPick).toHaveBeenCalledWith(second!.rule_id);
    expect(await screen.findByRole("tooltip")).toHaveTextContent(`Regla ${second!.rule_id}`); // the pointer is over it
  });

  it("without the importance the card says there are no figures yet, and the id chip has no rule colour", async () => {
    inModel(<RuleRef id={first!.rule_id} />, null as never);
    const button = screen.getByRole("button", { name: first!.rule_id });
    expect(button).toHaveClass("rule-ref--plain");
    act(() => button.focus());
    expect(screen.getByRole("tooltip")).toHaveTextContent("Todavía no hay cifras de lo que decide esta regla.");
    expect(screen.queryByTestId("rule-hovercard-figures")?.querySelector('[data-figure="decided"]') ?? null).toBeNull();
  });

  it("in English", async () => {
    setLang("en");
    inModel(<RuleRef id={first!.rule_id} />);
    act(() => screen.getByRole("button", { name: first!.rule_id }).focus());
    const card = screen.getByRole("tooltip");
    expect(card).toHaveTextContent(`Rule ${first!.rule_id}`);
    expect(card.querySelector('[data-figure="decided"]')).toHaveTextContent("Predictions it decides");
    expect(card).toHaveTextContent("Published period:");
  });
});
