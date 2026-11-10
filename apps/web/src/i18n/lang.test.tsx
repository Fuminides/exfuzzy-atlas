import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { dec, fmtFine, pct, THIN } from "../lib/format";
import { count } from "../lib/summary";
import { installApi } from "../test/fakeApi";
import { resetMaps } from "../test/maplibreMock";
import { classifierV05 } from "../test/v05";
import { detectLang, setLang, tr } from ".";

vi.mock("maplibre-gl", async () => (await import("../test/maplibreMock")).maplibreFactory());

beforeEach(() => resetMaps());
afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  setLang("es");
});

describe("language switch", () => {
  it("starts in the language it is given and switches the interface, keeping the tab and remembering the choice", async () => {
    installApi({}, classifierV05());
    render(<App initialLang="en" initialTab="prediccion" />);
    const tabs = await screen.findByRole("tablist", { name: "Sections" });
    expect(within(tabs).getAllByRole("tab").map((t) => t.textContent)).toEqual(["Patterns", "Performance report", "Data summary", "Prediction", "Explore"]);
    expect(within(tabs).getByRole("tab", { name: "Prediction" })).toHaveAttribute("aria-selected", "true");
    expect(document.documentElement.lang).toBe("en");
    await userEvent.setup().click(screen.getByRole("button", { name: "Español" }));
    const es = screen.getByRole("tablist", { name: "Secciones" });
    expect(within(es).getByRole("tab", { name: "Predicción" })).toHaveAttribute("aria-selected", "true");
    expect(document.documentElement.lang).toBe("es");
    expect(window.localStorage.getItem("atlas.lang")).toBe("es");
  });

  it("detects ?lang= first, then the stored choice, then the browser's language", () => {
    window.localStorage.setItem("atlas.lang", "es");
    vi.stubGlobal("location", { ...window.location, search: "?lang=en" });
    expect(detectLang()).toBe("en");
    vi.stubGlobal("location", { ...window.location, search: "" });
    expect(detectLang()).toBe("es");
    window.localStorage.clear();
    vi.stubGlobal("navigator", { language: "en-US" });
    expect(detectLang()).toBe("en");
    vi.stubGlobal("navigator", { language: "es-ES" });
    expect(detectLang()).toBe("es");
  });
});

describe("numbers follow the language", () => {
  it("Spanish: comma decimals, thin space before %, dot thousands; English: point decimals, no space, comma thousands", () => {
    setLang("es");
    expect([dec(0.329, 2), pct(0.24), pct(0.0004), fmtFine(0.00008), count(1234567), tr("sí", "yes")]).toEqual(["0,33", `24${THIN}%`, `<0,1${THIN}%`, "0,00008", "1.234.567", "sí"]);
    setLang("en");
    expect([dec(0.329, 2), pct(0.24), pct(0.0004), count(1234567), tr("sí", "yes")]).toEqual(["0.33", "24%", "<0.1%", "1,234,567", "yes"]);
    expect(fmtFine(0.00008)).toBe("0.00008");
  });
});
