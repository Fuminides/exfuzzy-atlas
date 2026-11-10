import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type { DomainsResponse } from "./api/types";
import { fake, installApi } from "./test/fakeApi";
import * as cls from "./test/fixturesClass";
import { resetMaps } from "./test/maplibreMock";
import { classifierV05 } from "./test/v05";

vi.mock("maplibre-gl", async () => (await import("./test/maplibreMock")).maplibreFactory());

beforeEach(() => resetMaps());
afterEach(() => vi.unstubAllGlobals());

const base = cls.domains.domains[0]!.tasks[0]!;
/** One territory with five horizons (the way the backend will publish them), plus a second territory and an empty domain. */
const horizons = (hours: number[], defaultHours = 6): DomainsResponse => {
  const tasks = hours.map((h) => ({ ...base, task_id: `zona_h${h}`, horizon_hours: h, territory: "zona", territory_title: "Zona de prueba", model_id: h === 6 ? base.model_id : null }));
  tasks.sort((a, b) => Number(b.horizon_hours === defaultHours) - Number(a.horizon_hours === defaultHours)); // the API lists the default first
  return { ...cls.domains, domains: [{ ...cls.domains.domains[0]!, tasks: [...tasks, { ...base, task_id: "otra_h6", territory: "otra", territory_title: "Otra zona", model_id: null }] }] };
};
const names = (el: HTMLElement) => within(el).getAllByRole("button").map((b) => b.textContent?.trim());

describe("territory selector, sections and horizon", () => {
  it("opens on Patrones (the rules are the focus), with the four sections in order and a group per domain", async () => {
    installApi({}, classifierV05());
    render(<App />);
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent(/^Patrones/);
    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual(["Patrones", "Informe de rendimiento", "Resumen de datos", "Predicción", "Explorar"]);
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    expect(within(screen.getByRole("navigation", { name: "Territorio" })).getByRole("group", { name: "Calidad del aire" })).toBeInTheDocument();
    expect(screen.getByTestId("horizon")).toBeInTheDocument(); // the rules depend on the model's horizon
    await userEvent.setup().click(screen.getByRole("tab", { name: "Resumen de datos" }));
    expect(screen.queryByTestId("horizon")).toBeNull(); // the summary is data: no horizon
  });

  it("moves between sections with the arrow keys and Home/End, and each tab labels its panel", async () => {
    installApi({}, classifierV05());
    render(<App />);
    const user = userEvent.setup();
    const tab = (n: string) => screen.getByRole("tab", { name: n });
    await screen.findByRole("tabpanel");
    tab("Patrones").focus();
    await user.keyboard("{ArrowRight}");
    expect(tab("Informe de rendimiento")).toHaveAttribute("aria-selected", "true");
    expect(tab("Informe de rendimiento")).toHaveFocus();
    expect(screen.getByRole("tabpanel")).toHaveAccessibleName("Informe de rendimiento");
    await user.keyboard("{End}");
    expect(tab("Explorar")).toHaveAttribute("aria-selected", "true");
    await user.keyboard("{ArrowRight}");
    expect(tab("Patrones")).toHaveAttribute("aria-selected", "true");
  });

  it("offers a segmented horizon control over the territory's tasks, sorted, with the default one pressed, and a click changes the task", async () => {
    installApi({ "/domains": () => Promise.resolve(new Response(JSON.stringify(horizons([24, 3, 6, 1, 12])), { status: 200 })) }, classifierV05());
    render(<App initialTab="patrones" />);
    const user = userEvent.setup();
    const control = await screen.findByRole("group", { name: "Horizonte de predicción" });
    expect(names(control)).toEqual(["+1 h", "+3 h", "+6 h", "+12 h", "+24 h"]);
    expect(within(control).getByRole("button", { name: "+6 h" })).toHaveAttribute("aria-pressed", "true"); // the territory's default task
    expect(screen.getAllByRole("group", { name: "Calidad del aire" })[0]!).toHaveTextContent("Zona de pruebaOtra zona"); // one button per territory, not per horizon
    await user.click(within(control).getByRole("button", { name: "+3 h" }));
    await waitFor(() => expect(within(control).getByRole("button", { name: "+3 h" })).toHaveAttribute("aria-pressed", "true"));
    expect(fake.calls.some((c) => c.includes("/entities") && c.includes("task_id=zona_h3"))).toBe(true);
    expect(screen.getByRole("button", { name: "Zona de prueba" })).toHaveAttribute("aria-pressed", "true"); // still the same territory
  });

  it("with one horizon shows a fixed, explained label (not a disabled control)", async () => {
    installApi({}, classifierV05());
    render(<App initialTab="patrones" />);
    const fixed = await screen.findByTestId("horizon-fixed");
    expect(fixed).toHaveTextContent("+6 h");
    expect(fixed).toHaveTextContent("único horizonte disponible por ahora");
    expect(within(screen.getByTestId("horizon")).queryAllByRole("button")).toHaveLength(0);
  });

  it("says that horizon 0 is same-sample inference", async () => {
    const water: DomainsResponse = { ...cls.domains, domains: [{ ...cls.domains.domains[0]!, tasks: [{ ...base, horizon_hours: 0, territory: "zona", territory_title: "Zona de prueba" }] }] };
    installApi({ "/domains": () => Promise.resolve(new Response(JSON.stringify(water), { status: 200 })) }, classifierV05());
    render(<App initialTab="patrones" />);
    const fixed = await screen.findByTestId("horizon-fixed");
    expect(fixed).toHaveTextContent("Misma muestra");
    expect(fixed).toHaveTextContent("inferencia");
    expect(fixed.textContent).not.toMatch(/\+0 h/);
  });

  it("starts the horizon at the task the API lists first, even when it is not the shortest", async () => {
    installApi({ "/domains": () => Promise.resolve(new Response(JSON.stringify(horizons([1, 3, 6, 12, 24], 6)), { status: 200 })) }, classifierV05());
    render(<App initialTab="patrones" />);
    await screen.findByRole("group", { name: "Horizonte de predicción" });
    // the /entities request is sent by an effect after the horizon renders: wait for it, do not race it
    await waitFor(() => expect(fake.calls.some((c) => c.includes("/entities") && c.includes("task_id=zona_h6"))).toBe(true));
    expect(fake.calls.some((c) => c.includes("task_id=zona_h1"))).toBe(false);
  });
});
