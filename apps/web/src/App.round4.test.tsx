import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { RULE_PALETTE } from "./lib/territories";
import { installApi } from "./test/fakeApi";
import { maps, resetMaps } from "./test/maplibreMock";
import { regressionV05 } from "./test/v05";

vi.mock("maplibre-gl", async () => (await import("./test/maplibreMock")).maplibreFactory());
// The default time is probed elsewhere (hooks/useDefaultTime.test.tsx); here the page opens at the first issue time.
vi.mock("./hooks/useDefaultTime", () => ({ useDefaultTime: () => false }));

beforeEach(() => resetMaps());
afterEach(() => vi.unstubAllGlobals());

describe("Predicción: compact time controls", () => {
  it("shows one plain local-time line and folds the UTC detail, zone, coverage and keys into 'Detalles de tiempo'", async () => {
    installApi();
    render(<App initialTab="prediccion" />);
    const line = await screen.findByTestId("timeline-line");
    expect(line).toHaveTextContent(/^Emisión: \d{1,2} \w+ 2025, \d\d:\d\d → prevé (las \d\d:\d\d|el .+) \(hora de Madrid\)$/);
    expect(line).not.toHaveTextContent("UTC");
    const details = screen.getByText("Detalles de tiempo").closest("details")!;
    expect(details).not.toHaveAttribute("open");
    expect(within(details).getByLabelText("Zona del campo")).toBeInTheDocument();
    expect(within(details).getByText(/Teclado:/)).toBeInTheDocument();
    expect(within(details).getByText("Cobertura")).toBeInTheDocument();
    expect(within(details).getByTestId("issue-time")).toHaveTextContent("UTC");
    // the controls stay reachable by their accessible names
    expect(screen.getByLabelText("Hora de emisión")).toBeInTheDocument();
    expect(screen.getByLabelText("Ir a fecha y hora")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Emisión siguiente" })).toBeInTheDocument();
  });
});

describe("Predicción of a regression", () => {
  it("says 'valor estimado' on the colour switch, not 'categoría prevista', and keeps the panels free of rule-intensity jargon", async () => {
    installApi({}, { ...regressionV05(), decidedBy: "R02" });
    render(<App initialTab="prediccion" />);
    const group = await screen.findByRole("group", { name: "Colorear el mapa por" });
    expect(within(group).getByRole("button", { name: "valor estimado" })).toHaveAttribute("aria-pressed", "true");
    expect(within(group).queryByRole("button", { name: "categoría prevista" })).toBeNull();
    expect(document.body).not.toHaveTextContent("La intensidad de las reglas no se muestra en este modo");
  });
});

describe("Explorar: one colour per rule everywhere", () => {
  it("colours the territories by the ranking of Patrones (the rule that decides most gets the first colour), not by model order", async () => {
    const base = regressionV05();
    const importance = { ...base.importance!, rules: base.importance!.rules.map((r, i) => ({ ...r, decided_share: [0.2, 0.3, 0.5][i] ?? 0 })) };
    installApi({}, { ...base, importance });
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await screen.findByRole("region", { name: /Leyenda: activación/ });
    await user.click(screen.getByRole("button", { name: "Territorios" }));
    const legend = await screen.findByRole("region", { name: /Leyenda: Territorios de reglas/ });
    const rank = ["R03", "R02", "R01"];
    const mapColours = () => {
      const paint = maps[maps.length - 1]!.layers["stations-valid"]!.paint!["circle-color"] as unknown[];
      const out = new Map<string, string>();
      for (let k = 2; k + 1 < paint.length - 1; k += 2) out.set(paint[k] as string, paint[k + 1] as string);
      return out;
    };
    await waitFor(() => expect(mapColours().get("R03")).toBe(RULE_PALETTE[0]));
    for (const [i, id] of rank.entries()) expect(mapColours().get(id)).toBe(RULE_PALETTE[i]);
    // the legend and the table use the same colours as the map
    for (const li of legend.querySelectorAll("li[data-rule]")) expect(li.getAttribute("data-color")).toBe(RULE_PALETTE[rank.indexOf(li.getAttribute("data-rule")!)]);
  });
});
