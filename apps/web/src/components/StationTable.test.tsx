import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { VIRIDIS } from "../lib/colorScale";
import type { StationRow } from "../map/stations";
import { StationTable } from "./StationTable";

const geometry = { type: "Point", coordinates: [0, 0] } as StationRow["geometry"];
const rows: StationRow[] = [
  { entityId: "SYN_A", name: "Station A", value: 0, missingReason: null, nValid: 1, geometry },
  { entityId: "SYN_D", name: "Station D", value: null, missingReason: "missing_input", nValid: 0, geometry },
];

function setup() {
  const onSelect = vi.fn();
  render(
    <StationTable rows={rows} selectedId={null} onSelect={onSelect} stops={VIRIDIS} domain={[0, 1]} valueHeader="Activación (0–1)" showNValid />,
  );
  return onSelect;
}

describe("StationTable", () => {
  it("renders a 0 value and a null value differently, and the null one shows its missing_reason", () => {
    setup();
    const zero = screen.getByRole("row", { name: /Station A/ });
    const missing = screen.getByRole("row", { name: /Station D/ });
    // 0 is a real value: filled marker, number, no "sin dato".
    expect(zero.querySelector(".marker--value")).not.toBeNull();
    expect(zero.querySelector(".marker--missing")).toBeNull();
    expect(within(zero).getByText("0,000")).toBeInTheDocument();
    expect(zero).not.toHaveTextContent("sin dato");
    // null is not 0: hollow marker, "sin dato", the reason, and no number.
    expect(missing.querySelector(".marker--missing")).not.toBeNull();
    expect(missing.querySelector(".marker--value")).toBeNull();
    expect(missing).toHaveTextContent("sin dato");
    expect(missing).toHaveTextContent("falta una entrada");
    expect(missing).not.toHaveTextContent("0,000");
  });

  it("selects a station with the keyboard", async () => {
    const onSelect = setup();
    const user = userEvent.setup();
    await user.tab();
    expect(screen.getByRole("button", { name: "Station A" })).toHaveFocus();
    await user.keyboard("{Tab}{Enter}");
    expect(onSelect).toHaveBeenCalledWith("SYN_D");
  });

  it("with class colours shows the label chip, and 'sin predicción' with its reason for a null label", () => {
    const labelled: StationRow[] = [
      { ...rows[0]!, value: null, label: "Regular" },
      { ...rows[1]!, value: null, label: null, missingReason: "prediction_unavailable" },
    ];
    render(
      <StationTable
        rows={labelled}
        selectedId={null}
        onSelect={() => {}}
        stops={VIRIDIS}
        domain={[0, 1]}
        valueHeader="Categoría prevista"
        showNValid={false}
        classColors={new Map([["Regular", "#FFCC00"]])}
      />,
    );
    const a = screen.getByRole("row", { name: /Station A/ });
    expect(a.querySelector(".class-chip")).toHaveAttribute("data-class", "Regular");
    expect((a.querySelector(".class-swatch") as HTMLElement).style.background).toBe("rgb(255, 204, 0)");
    const d = screen.getByRole("row", { name: /Station D/ });
    expect(d).toHaveTextContent("sin predicción");
    expect(d).toHaveTextContent("predicción no disponible");
    expect(d.querySelector(".class-chip")).toBeNull();
  });
  it("lists 'sin referencia' apart from other missing predictions, with the hatch swatch and never a class chip", () => {
    const noRef: StationRow[] = [
      { entityId: "35", name: "Brownsville", value: null, label: null, noReference: true, missingReason: "prediction_unavailable", nValid: null, geometry },
      { entityId: "36", name: "Bushwick North", value: null, label: null, missingReason: "prediction_unavailable", nValid: null, geometry },
      { entityId: "4", name: "Alphabet City", value: null, label: "alta", missingReason: null, nValid: null, geometry },
    ];
    render(
      <StationTable
        rows={noRef}
        selectedId={null}
        onSelect={() => {}}
        stops={VIRIDIS}
        domain={[0, 1]}
        valueHeader="Categoría prevista"
        showNValid={false}
        classColors={new Map([["alta", "#4292C6"]])}
        noun={{ one: "zona de taxi", many: "zonas de taxi" }}
      />,
    );
    expect(screen.getByRole("table", { name: "Zonas de taxi (alternativa textual al mapa)" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Zona de taxi" })).toBeInTheDocument();
    const ref = screen.getByRole("row", { name: /Brownsville/ });
    expect(ref).toHaveTextContent("sin referencia");
    expect(ref.querySelector(".marker--noref")).not.toBeNull();
    expect(ref.querySelector(".class-chip")).toBeNull();
    const other = screen.getByRole("row", { name: /Bushwick North/ });
    expect(other).toHaveTextContent("sin predicción");
    expect(other).not.toHaveTextContent("sin referencia");
    expect(other.querySelector(".marker--missing")).not.toBeNull();
    expect(screen.getByRole("row", { name: /Alphabet City/ }).querySelector(".class-chip")).toHaveAttribute("data-class", "alta");
  });

  it("adds an extra column when asked (the sample date of Water points)", () => {
    render(
      <StationTable
        rows={rows}
        selectedId={null}
        onSelect={() => {}}
        stops={VIRIDIS}
        domain={[0, 1]}
        valueHeader="Predicción (mg/l)"
        showNValid={false}
        extra={{ header: "Muestra (fecha · observado)", cell: (r) => `muestra de ${r.name}` }}
      />,
    );
    expect(screen.getByRole("columnheader", { name: "Muestra (fecha · observado)" })).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /Station A/ })).toHaveTextContent("muestra de Station A");
  });
});
