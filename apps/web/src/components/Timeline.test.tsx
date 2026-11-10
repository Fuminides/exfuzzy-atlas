import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { issueTimes } from "../lib/format";
import { ZoneContext } from "../lib/zone";
import { Timeline } from "./Timeline";

const coverage = (step: number) => ({ issued_from_utc: "2025-01-01T00:00:00Z", issued_to_utc: "2025-12-31T23:00:00Z", step_hours: step });
const times = issueTimes(coverage(1)); // 8,760 issue times

function Harness({ start = 100, list = times, step = 1 }: { start?: number; list?: string[]; step?: number }) {
  const [i, setI] = useState(start);
  return <Timeline times={list} index={i} onIndex={setI} horizonHours={6} stepHours={step} />;
}
const issue = () => screen.getByTestId("issue-time").textContent ?? "";

describe("Timeline at real scale", () => {
  it("has 8,760 issue times and the slider spans all of them", () => {
    expect(times).toHaveLength(8760);
    render(<Harness />);
    expect(screen.getByLabelText("Hora de emisión")).toHaveAttribute("max", "8759");
  });

  it("jumps -1 d / -1 h / +1 h / +1 d with labelled buttons", async () => {
    const user = userEvent.setup();
    render(<Harness start={100} />); // 2025-01-05 04:00 UTC
    expect(issue()).toContain("05/01/2025, 04:00 UTC");
    await user.click(screen.getByRole("button", { name: "Avanzar 1 día" }));
    expect(issue()).toContain("06/01/2025, 04:00 UTC");
    await user.click(screen.getByRole("button", { name: "Avanzar 1 hora" }));
    expect(issue()).toContain("06/01/2025, 05:00 UTC");
    await user.click(screen.getByRole("button", { name: "Retroceder 1 hora" }));
    await user.click(screen.getByRole("button", { name: "Retroceder 1 día" }));
    expect(issue()).toContain("05/01/2025, 04:00 UTC");
  });

  it("disables jumps that would leave the coverage", () => {
    render(<Harness start={5} />);
    expect(screen.getByRole("button", { name: "Retroceder 1 día" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Retroceder 1 hora" })).toBeEnabled();
  });

  it("has the same jumps on the keyboard (PageUp/PageDown = ∓1 d, Shift+arrows = ∓1 h)", () => {
    render(<Harness start={100} />);
    const slider = screen.getByLabelText("Hora de emisión");
    fireEvent.keyDown(slider, { key: "PageDown" });
    expect(issue()).toContain("06/01/2025, 04:00 UTC");
    fireEvent.keyDown(slider, { key: "ArrowRight", shiftKey: true });
    expect(issue()).toContain("06/01/2025, 05:00 UTC");
    fireEvent.keyDown(slider, { key: "ArrowLeft", shiftKey: true });
    fireEvent.keyDown(slider, { key: "PageUp" });
    expect(issue()).toContain("05/01/2025, 04:00 UTC");
    expect(slider).toHaveAttribute("aria-keyshortcuts", expect.stringContaining("PageDown"));
    expect(screen.getByRole("button", { name: "Avanzar 1 día" })).toHaveAttribute("aria-keyshortcuts", "PageDown");
  });

  it("goes to a typed date-time in UTC and shows both zones", () => {
    render(<Harness />);
    fireEvent.change(screen.getByLabelText("Ir a fecha y hora"), { target: { value: "2025-07-15T12:00" } });
    expect(issue()).toContain("15/07/2025, 12:00 UTC · 14:00 Europe/Madrid");
  });

  it("goes to a typed date-time in Europe/Madrid when that zone is chosen", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.selectOptions(screen.getByLabelText("Zona del campo"), "Europe/Madrid");
    fireEvent.change(screen.getByLabelText("Ir a fecha y hora"), { target: { value: "2025-07-15T12:00" } });
    expect(issue()).toContain("15/07/2025, 10:00 UTC · 12:00 Europe/Madrid");
  });

  it("snaps a time outside the coverage to its edge and says so", () => {
    render(<Harness />);
    fireEvent.change(screen.getByLabelText("Ir a fecha y hora"), { target: { value: "2026-03-01T00:00" } });
    expect(issue()).toContain("31/12/2025, 23:00 UTC");
    expect(screen.getByRole("status")).toHaveTextContent("Fuera de la cobertura");
  });

  it("with 6-hourly issue times, a 1 h jump is not offered but a day jump is", () => {
    const six = issueTimes(coverage(6));
    render(<Harness list={six} step={6} start={10} />);
    expect(screen.getByRole("button", { name: "Avanzar 1 hora" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Avanzar 1 día" })).toBeEnabled();
    fireEvent.change(screen.getByLabelText("Ir a fecha y hora"), { target: { value: "2025-02-01T08:00" } });
    expect(issue()).toContain("01/02/2025, 06:00 UTC");
    expect(screen.getByRole("status")).toHaveTextContent("más cercana");
  });
  it("shows local time in the entities' zone (America/New_York for NYC), never Madrid", async () => {
    const user = userEvent.setup();
    render(
      <ZoneContext.Provider value="America/New_York">
        <Harness start={0} list={issueTimes({ issued_from_utc: "2025-03-19T23:00:00Z", issued_to_utc: "2025-03-21T23:00:00Z", step_hours: 1 })} />
      </ZoneContext.Provider>,
    );
    expect(issue()).toBe("19/03/2025, 23:00 UTC · 19:00 America/New_York");
    expect(screen.getByTestId("valid-time")).toHaveTextContent("20/03/2025, 05:00 UTC · 01:00 America/New_York");
    expect(document.body).not.toHaveTextContent("Madrid");
    const zone = screen.getByLabelText("Zona del campo") as HTMLSelectElement;
    expect([...zone.options].map((o) => o.value)).toEqual(["UTC", "America/New_York"]);
    await user.selectOptions(zone, "America/New_York");
    expect(screen.getByLabelText("Ir a fecha y hora")).toHaveValue("2025-03-19T19:00");
  });

  it("horizon 0 is the same sample, not '+0 h'", () => {
    render(<Timeline times={["2025-12-03T08:15:00Z"]} index={0} onIndex={() => {}} horizonHours={0} stepHours={1} />);
    expect(screen.getByText(/Hora de validez/)).toHaveTextContent("inferencia sobre la misma muestra");
    expect(document.body).not.toHaveTextContent(/\+\s?0\s?h/);
  });
});
