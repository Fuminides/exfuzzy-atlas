import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { VIRIDIS } from "../lib/colorScale";
import { Legend } from "./Legend";

describe("Legend", () => {
  it("renders the 0-1 activation scale, its title and the valid count", () => {
    render(
      <Legend
        title="activación de regla (0–1)"
        note="No es una probabilidad."
        stops={VIRIDIS}
        domain={[0, 1]}
        ticks={["0", "0.25", "0.5", "0.75", "1"]}
        nValid={3}
        total={4}
        missingLabel="sin dato"
        countLabel="Estaciones con valor válido"
      />,
    );
    const legend = screen.getByRole("region", { name: /activación de regla \(0–1\)/ });
    expect(legend).toHaveAttribute("data-domain", "0-1");
    const ticks = within(legend).getAllByRole("listitem").map((li) => li.textContent);
    expect(ticks[0]).toBe("0");
    expect(ticks[ticks.length - 1]).toBe("1");
    expect(within(legend).getByText("sin dato", { exact: false })).toBeInTheDocument();
    expect(legend).toHaveTextContent("3 de 4");
  });
});
