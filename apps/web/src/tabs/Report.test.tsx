import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { setLang } from "../i18n";
import { installApi } from "../test/fakeApi";
import { resetMaps } from "../test/maplibreMock";
import { classifierV05 } from "../test/v05";

vi.mock("maplibre-gl", async () => (await import("../test/maplibreMock")).maplibreFactory());

beforeEach(() => resetMaps());
afterEach(() => {
  vi.unstubAllGlobals();
  setLang("es");
});

describe("Informe de rendimiento", () => {
  it("is its own tab with the bars, the per-category accuracy and the evaluation table; the metric switches", async () => {
    installApi({}, classifierV05());
    render(<App initialTab="rendimiento" />);
    const bars = await screen.findByTestId("perf-bars");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(/^Informe de rendimiento: /);
    expect(bars).toHaveAttribute("data-metric", "macro_f1");
    expect(within(bars).getAllByRole("listitem")[0]).toHaveTextContent("ExFuzzy");
    expect(screen.getByRole("heading", { name: "¿Cuánto acierta?" })).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Acierto" }));
    expect(screen.getByTestId("perf-bars")).toHaveAttribute("data-metric", "accuracy");
  });

  it("Predicción links to it instead of repeating the evaluation", async () => {
    installApi({}, classifierV05());
    render(<App initialTab="prediccion" />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Ver el informe de rendimiento" }));
    expect(screen.getByRole("tab", { name: "Informe de rendimiento" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByTestId("perf-bars")).toBeInTheDocument();
  });

  it("in English: 'Performance report', 'Macro-F1 | Accuracy', and no probability, risk or cause words", async () => {
    installApi({}, classifierV05());
    render(<App initialLang="en" initialTab="rendimiento" />);
    await screen.findByTestId("perf-bars");
    expect(screen.getByRole("tab", { name: "Performance report" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("group", { name: "Metric" })).toHaveTextContent("Macro-F1Accuracy");
    const own = document.querySelector("main")!.cloneNode(true) as HTMLElement;
    own.querySelectorAll(".site-credits").forEach((n) => n.remove()); // "© OpenStreetMap contributors" is licence wording
    expect(own.textContent).not.toMatch(/probabilit|risk|contribut|caus(e|al)|certaint|confiden/i);
  });
});
