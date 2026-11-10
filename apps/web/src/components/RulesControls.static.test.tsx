import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RulesControls } from "./RulesControls";

vi.mock("../lib/dataMode", () => ({ isStaticData: () => true, staticDataBase: () => "/data/x/", STORIES_TAU: 0.5 }));

const base = {
  noun: "estación", irregular: false, classifier: true, coverage: { issued_from_utc: "2025-01-01T00:00:00Z", issued_to_utc: "2025-03-31T23:00:00Z", step_hours: 1 },
  window: { from: "2025-01-01T00:00:00Z", to: "2025-01-06T00:00:00Z" }, rulesView: "rule" as const, onRulesView: () => {}, view: "activation_frequency" as const,
  onView: () => {}, ruleId: "R01", tau: 0.5, onTau: () => {}, emphasis: 0.5, onEmphasis: () => {}, terrMeasure: "mean_activation" as const,
  onTerrMeasure: () => {}, terrFocus: "all" as const, onTerrFocus: () => {}, kind: "week" as const, onKind: () => {}, customWindow: null, onClearPins: () => {},
};

describe("rules controls on a static export", () => {
  it("moves τ over the values the export holds", () => {
    const onTau = vi.fn();
    render(<RulesControls {...base} taus={[0.25, 0.5, 0.75]} onTau={onTau} />);
    const slider = screen.getByLabelText(/τ de la frecuencia/) as HTMLInputElement;
    expect(slider.max).toBe("2");
    expect(slider.value).toBe("1");
    fireEvent.change(slider, { target: { value: "2" } });
    expect(onTau).toHaveBeenCalledWith(0.75);
  });

  it("offers no τ before the export is known", () => {
    render(<RulesControls {...base} />);
    expect(screen.queryByText(/τ de la frecuencia/)).toBeNull();
  });

  it("lists only the window kinds the export has", () => {
    render(<RulesControls {...base} taus={[0.5]} kinds={["week", "coverage"]} />);
    const labels = screen.getAllByRole("radio").map((r) => r.parentElement?.textContent ?? "");
    expect(labels.some((l) => /Día/.test(l))).toBe(false);
    expect(labels.some((l) => /Mes/.test(l))).toBe(false);
    expect(labels.some((l) => /Semana/.test(l))).toBe(true);
    expect(labels.some((l) => /cobertura/.test(l))).toBe(true);
  });
});
