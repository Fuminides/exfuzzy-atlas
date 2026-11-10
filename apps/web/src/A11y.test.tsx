import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { installApi } from "./test/fakeApi";
import { maps, resetMaps } from "./test/maplibreMock";
import { CANVAS_LABEL } from "./map/StationMap";
import { classifierV05 } from "./test/v05";

vi.mock("maplibre-gl", async () => (await import("./test/maplibreMock")).maplibreFactory());

beforeEach(() => resetMaps());
afterEach(() => vi.unstubAllGlobals());

describe("docs/qa A11Y-2: the time controls are one keystroke away where they come after the map", () => {
  it("Explorar offers «Ir a la línea temporal», which moves the focus to the time slider", async () => {
    installApi({}, classifierV05());
    render(<App />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("tab", { name: "Explorar" }));
    const skip = await screen.findByRole("button", { name: "Ir a la línea temporal" });
    const slider = await screen.findByRole("slider", { name: "Hora de emisión" });
    await waitFor(() => expect(slider).not.toBeDisabled());
    await user.click(skip);
    expect(slider).toHaveFocus();
  });

  it("Predicción has no skip link: its time controls already come before the map", async () => {
    installApi({}, classifierV05());
    render(<App />);
    await userEvent.setup().click(await screen.findByRole("tab", { name: "Predicción" }));
    await screen.findByRole("slider", { name: "Hora de emisión" });
    expect(screen.queryByRole("button", { name: "Ir a la línea temporal" })).toBeNull();
  });
});

describe("docs/qa A11Y-4: one map region, in Spanish", () => {
  it("the MapLibre canvas is an application with a Spanish name, not a second region called «Map»", async () => {
    installApi({}, classifierV05());
    render(<App />);
    await userEvent.setup().click(await screen.findByRole("tab", { name: "Explorar" }));
    await waitFor(() => expect(maps.length).toBeGreaterThan(0));
    for (const m of maps) expect(m.canvasAttributes).toEqual({ role: "application", "aria-label": CANVAS_LABEL });
  });
});
