import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { ZoneContext } from "../lib/zone";
import { windowFor } from "../lib/windows";
import { WindowNavigator, type NavKind } from "./WindowNavigator";

const coverage = { issued_from_utc: "2024-01-02T07:46:00Z", issued_to_utc: "2025-12-22T10:14:00Z", step_hours: 1 };

function Harness() {
  const [kind, setKind] = useState<NavKind>("month");
  const [anchor, setAnchor] = useState(coverage.issued_to_utc);
  return (
    <ZoneContext.Provider value="Europe/London">
      <WindowNavigator kind={kind} window={windowFor(kind, anchor, coverage)} coverage={coverage} onKind={setKind} onAnchor={setAnchor} />
    </ZoneContext.Provider>
  );
}

describe("WindowNavigator (irregular sample times)", () => {
  it("has window controls and no hour-by-hour controls", () => {
    render(<Harness />);
    expect(screen.queryByRole("slider")).toBeNull();
    expect(screen.queryByRole("button", { name: /hora/i })).toBeNull();
    expect(screen.getByRole("group", { name: "Tamaño de la ventana" })).toBeInTheDocument();
    expect(screen.getByTestId("window-range")).toHaveTextContent("[2025-12-01 00:00 UTC, 2026-01-01 00:00 UTC) · 31 d");
    expect(screen.getByTestId("irregular-note")).toHaveTextContent("No se avanza hora a hora");
    // the plain line is on top; the UTC range, coverage and the note are in the folded details
    expect(screen.getByTestId("timeline-line")).toHaveTextContent("Muestras del 1 al 31 dic 2025");
    expect(screen.getByText("Detalles de tiempo").closest("details")).not.toHaveAttribute("open");
  });

  it("moves by window, stops at the ends of the coverage, and jumps to a date", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const next = screen.getByRole("button", { name: "Ventana siguiente" });
    expect(next).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Ventana anterior" }));
    expect(screen.getByTestId("window-range")).toHaveTextContent("[2025-11-01");
    expect(next).toBeEnabled();
    fireEvent.change(screen.getByLabelText("Ir a fecha"), { target: { value: "2024-01-20" } });
    expect(screen.getByTestId("window-range")).toHaveTextContent("[2024-01-01 00:00 UTC, 2024-02-01 00:00 UTC)");
    expect(screen.getByRole("button", { name: "Ventana anterior" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Año" }));
    expect(screen.getByRole("button", { name: "Año" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("window-range")).toHaveTextContent("· 366 d");
  });

  it("shows the coverage in the entities' zone", () => {
    render(<Harness />);
    expect(screen.getByText(/de 02\/01\/2024, 07:46 UTC · 07:46 Europe\/London a 22\/12\/2025, 10:14 UTC · 10:14 Europe\/London/)).toBeInTheDocument();
  });
});
