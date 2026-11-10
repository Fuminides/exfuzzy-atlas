import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { installApi } from "./test/fakeApi";
import * as real from "./test/fixturesReal";
import { resetMaps } from "./test/maplibreMock";

vi.mock("maplibre-gl", async () => (await import("./test/maplibreMock")).maplibreFactory());

beforeEach(() => {
  resetMaps();
  installApi({}, real.realData());
});
afterEach(() => vi.unstubAllGlobals());

describe("¿Por qué aquí? in the app (real NYC trace)", () => {
  it("explains the winner and the strongest-firing loser for the selected zone", async () => {
    render(<App initialTab="explorar" />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /Taxis de Nueva York/ }));
    const hours = (Date.parse(real.NYC_EVENING) - Date.parse(real.NYC_FIRST_ISSUE)) / 3_600_000;
    fireEvent.change(await screen.findByLabelText("Hora de emisión"), { target: { value: String(hours) } });
    await waitFor(() => expect(screen.getByTestId("issue-time")).toHaveTextContent("23:00 UTC"));
    const zone = real.nyc.entities.features.find((f) => f.properties.entity_id === real.NYC_ZONE)!.properties.name!;
    await user.click(within(screen.getByRole("table", { name: /Zonas de taxi/ })).getByRole("button", { name: zone }));
    const panel = await screen.findByRole("region", { name: "Why here?" });
    const story = await within(panel).findByTestId("association-story");
    expect(story).toHaveTextContent("R01 decide la categoría");
    expect(story).toHaveTextContent("R08 se activa por completo (1,000)");
    expect(story).toHaveTextContent("queda por debajo de la de R01 (0,056)");
    // the rule texts in the rail keep short numbers as the model publishes them
    expect(within(panel).getByTestId("winning-rule-note")).toBeInTheDocument();
  });
});
