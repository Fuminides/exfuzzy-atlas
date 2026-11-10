import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { installApi } from "./test/fakeApi";
import * as fx from "./test/fixturesClass";
import { maps, resetMaps } from "./test/maplibreMock";
import { classifierV05 } from "./test/v05";
import { RULE_PALETTE } from "./lib/territories";

vi.mock("maplibre-gl", async () => (await import("./test/maplibreMock")).maplibreFactory());

beforeEach(() => resetMaps());
afterEach(() => vi.unstubAllGlobals());

type Feature = { properties: { entity_id: string; label: string | null } };
const lastMap = () => maps[maps.length - 1]!;
const features = (): Feature[] => (lastMap().sources["stations"] as { data: { features: Feature[] } }).data.features;
/** The colour the last map paints a label with (the `match` expression of its fill/circle layer). */
const paintOf = (label: string): string | undefined => {
  const expr = Object.values(lastMap().layers).flatMap((l) => Object.values(l.paint ?? {})).map((v) => JSON.stringify(v)).find((s) => s.includes(`"${label}"`) && s.startsWith('["match"'));
  const m = expr ? new RegExp(`"${label}","(#[0-9a-fA-F]{6})"`).exec(expr) : null;
  return m?.[1];
};

describe("Predicción: colour by the rule that decided", () => {
  it("offers the switch only when the API names the deciding rule, with the category as the default", async () => {
    installApi({}, classifierV05());
    render(<App initialTab="prediccion" />);
    await screen.findByRole("table", { name: /Estaciones/ });
    expect(screen.queryByRole("group", { name: "Colorear el mapa por" })).toBeNull();
  });

  it("recolours the map by rule, with the colours of Patrones, a legend of the rules present and a sentence on hover", async () => {
    installApi({}, { ...classifierV05(), decidedBy: "R02" });
    render(<App initialTab="prediccion" />);
    const user = userEvent.setup();
    const group = await screen.findByRole("group", { name: "Colorear el mapa por" });
    expect(within(group).getByRole("button", { name: "categoría prevista" })).toHaveAttribute("aria-pressed", "true");
    await waitFor(() => expect(features().some((f) => f.properties.label !== null)).toBe(true));
    const byCategory = features().map((f) => f.properties.label);
    expect(byCategory).not.toContain("R02");

    await user.click(within(group).getByRole("button", { name: "regla que decidió" }));
    await waitFor(() => expect(features().some((f) => f.properties.label === "R02")).toBe(true));
    // R02 is the second rule of the ranking (it decides 30 %): the second colour of the shared palette
    expect(paintOf("R02")).toBe(RULE_PALETTE[1]);
    const legend = screen.getByRole("region", { name: /Leyenda: Regla que decidió la predicción de cada/ });
    const item = within(legend).getByRole("button", { name: /R02/ });
    act(() => item.focus()); // the rule's card replaced the title tooltip
    expect(screen.getByTestId("rule-hovercard-sentence")).toHaveTextContent(/^Si .* → .+$/);
    expect(screen.getByRole("tooltip")).toHaveTextContent(/Ver la regla en Patrones$/);
    expect(within(legend).queryByText("R01")).toBeNull(); // only the rules present are listed
    expect(legend).toHaveTextContent(/Los colores son categorías, no una escala/);
    expect(legend.textContent).not.toMatch(/causa|probabilidad/i);
    expect(document.body.textContent).not.toMatch(/importancia de (la )?activaci/i);
    // the table keeps the predicted category
    const table = screen.getByRole("table", { name: /Estaciones/ });
    expect(within(table).getAllByText(/low|normal|high/i).length).toBeGreaterThan(0);

    await user.click(within(group).getByRole("button", { name: "categoría prevista" }));
    await waitFor(() => expect(features().some((f) => f.properties.label === "R02")).toBe(false));
  });

  it("paints a rule in Patrones' zones map with the same colour as in Predicción", async () => {
    installApi({}, { ...classifierV05(), decidedBy: "R02" });
    render(<App initialTab="patrones" />);
    await screen.findByText("Qué variables intervienen más");
    await waitFor(() => expect(features().some((f) => f.properties.label)).toBe(true));
    const inPatrones = paintOf("R02");
    expect(inPatrones).toBe(RULE_PALETTE[1]);
    const user = userEvent.setup();
    await user.click(screen.getByRole("tab", { name: "Predicción" }));
    await user.click(await screen.findByRole("button", { name: "regla que decidió" }));
    await waitFor(() => expect(features().some((f) => f.properties.label === "R02")).toBe(true));
    expect(paintOf("R02")).toBe(inPatrones);
  });
});

describe("Patrones: the zones map is framed on the zones that have predictions", () => {
  it("leaves out the zones with no predictions", async () => {
    installApi({}, classifierV05());
    render(<App initialTab="patrones" />);
    await screen.findByText("Qué variables intervienen más");
    await waitFor(() => expect(lastMap().fitted?.length).toBeGreaterThan(0));
    const ids = features().length;
    expect(ids).toBe(fx.entities.features.length);
    // importance lists every entity but the first: its points are not in the frame
    const first = fx.entities.features[0]!.geometry as { coordinates: [number, number] };
    expect(lastMap().fitted!.some((p) => p[0] === first.coordinates[0] && p[1] === first.coordinates[1])).toBe(false);
  });
});
