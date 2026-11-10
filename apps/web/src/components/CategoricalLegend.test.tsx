import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { icaScheme, scheme } from "../test/fixturesClass";
import { CategoricalLegend } from "./CategoricalLegend";

const show = (s: typeof icaScheme) =>
  render(
    <CategoricalLegend
      title="categoría ICA prevista de NO₂ (índice oficial)"
      note="No es un riesgo."
      scheme={s}
      nValid={3}
      total={4}
      countLabel="Estaciones con categoría prevista"
      missingLabel="sin predicción (el motivo se indica en la tabla)"
    />,
  );

describe("CategoricalLegend", () => {
  it("lists the scheme's classes in order with their official colours, bounds and unit", () => {
    show(icaScheme);
    const items = within(screen.getByRole("list", { name: /Categorías/ })).getAllByRole("listitem");
    expect(items.map((li) => li.getAttribute("data-class"))).toEqual(["Buena", "Razonablemente buena", "Regular", "Desfavorable o peor"]);
    expect(items.map((li) => li.getAttribute("data-color"))).toEqual(["#00FFFF", "#00B050", "#FFCC00", "#FF3300"]);
    expect(items[0]).toHaveTextContent("≤ 40 µg/m³");
    expect(items[3]).toHaveTextContent("> 120 y ≤ 1000 µg/m³");
    expect((items[0]!.querySelector(".class-swatch") as HTMLElement).style.background).toBe("rgb(0, 255, 255)");
  });

  it("names the scheme with a link to its source and says what the colours are not", () => {
    show(icaScheme);
    const link = screen.getByRole("link", { name: /Índice Nacional de Calidad del Aire/ });
    expect(link).toHaveAttribute("href", icaScheme.source_url);
    expect(screen.getByText("No es un riesgo.")).toBeInTheDocument();
  });

  it("explains the merged class and shows no note for a scheme without one", () => {
    const { unmount } = show(icaScheme);
    expect(screen.getByTestId("merged-class-note")).toHaveTextContent(
      "«Desfavorable o peor» reúne las categorías oficiales Desfavorable, Muy desfavorable y Extremadamente desfavorable (> 120 y ≤ 1000 µg/m³)",
    );
    unmount();
    show(scheme);
    expect(screen.queryByTestId("merged-class-note")).toBeNull();
  });

  it("counts stations with a category and keeps 'sin predicción' as its own entry", () => {
    show(icaScheme);
    expect(screen.getByText(/Estaciones con categoría prevista/)).toHaveTextContent("3 de 4");
    expect(screen.getByText(/sin predicción/)).toBeInTheDocument();
  });
});
