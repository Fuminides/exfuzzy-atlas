import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setLang } from "./i18n";
import { skipsLanding } from "./lib/landing";
import { Root } from "./Root";
import { installApi, json } from "./test/fakeApi";
import { resetMaps } from "./test/maplibreMock";
import { classifierV05 } from "./test/v05";

vi.mock("maplibre-gl", async () => (await import("./test/maplibreMock")).maplibreFactory());

beforeEach(() => {
  resetMaps();
  installApi({}, classifierV05());
});
afterEach(() => {
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
  window.history.replaceState({}, "", "/");
  setLang("es");
});

const landing = () => screen.queryByTestId("landing");
const tabs = () => screen.queryByRole("tablist", { name: /Secciones|Sections/ });

describe("the landing page", () => {
  it("opens on the bare URL: one h1, a one-line subtitle, how a model reads and the three territories", () => {
    render(<Root initialLang="es" />);
    expect(landing()).not.toBeNull();
    expect(tabs()).toBeNull();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Explicando mapas con reglas");
    expect(landing()!.querySelector(".lp-sub")).toHaveTextContent(/^Un estudio de calidad del aire, calidad del agua y demanda de taxis\.$/);
    expect(landing()!.querySelector(".lp-kicker")).toHaveTextContent("Una demostración de ex_fuzzy con datos públicos reales");
    expect(screen.getByRole("link", { name: "Saltar al contenido" })).toBeInTheDocument();
    const text = landing()!.textContent!;
    expect(text).toContain("ex_fuzzy");
    expect(text).toContain("Ese grado mide cuánto encaja la regla con lo observado");
    for (const t of ["Alemania", "Ríos de Northumberland y Tyne (Inglaterra)", "Nueva York"]) expect(screen.getByRole("heading", { level: 3, name: t })).toBeInTheDocument();
    expect(text).toMatch(/EAQI.*NO₂/);
    expect(screen.getAllByRole("button", { name: "Empezar la demo" }).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "Ver cómo funciona" })).toBeInTheDocument();
  });

  it("is written whole in English, and the language switch works on it", async () => {
    render(<Root initialLang="en" />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Explaining maps with rules");
    expect(landing()!.querySelector(".lp-sub")).toHaveTextContent(/^A study of air quality, water quality and taxi demand\.$/);
    expect(screen.getAllByRole("button", { name: "Start the demo" }).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "How it works" })).toBeInTheDocument();
    expect(landing()).toHaveTextContent("Northumberland and Tyne rivers (England)");
    await userEvent.setup().click(screen.getByRole("button", { name: "Español" }));
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Explicando mapas con reglas");
  });

  it("the title's second line is the italic accent, in both languages", () => {
    const { unmount } = render(<Root initialLang="es" />);
    expect(screen.getByRole("heading", { level: 1 }).querySelector("em.lp-accent")).toHaveTextContent("con reglas");
    unmount();
    render(<Root initialLang="en" />);
    expect(screen.getByRole("heading", { level: 1 }).querySelector("em.lp-accent")).toHaveTextContent("with rules");
  });

  it("no longer has «Qué verás» or «Qué no es», and says no \"it is not\" about the model", () => {
    render(<Root initialLang="es" />);
    const text = landing()!.textContent!;
    for (const gone of ["Qué verás", "Qué no es", "Las reglas enteras", "No da consejos de salud"]) expect(text).not.toContain(gone);
    expect(landing()!.querySelector(".lp-not, .lp-split, .lp-list")).toBeNull();
    expect(text).toContain("Ese grado mide cuánto encaja la regla con lo observado.");
    expect(text).not.toMatch(/No es una probabilidad|no es una probabilidad/);
    expect(within(landing()!).getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual(["Un modelo hecho de frases", "Datos públicos de tres lugares", "Empieza por las reglas"]);
  });

  it("each territory card has one static map with its alt text, ES and EN", () => {
    const { unmount } = render(<Root initialLang="es" />);
    const cards = [...landing()!.querySelectorAll<HTMLElement>("li.lp-card")];
    expect(cards.map((c) => c.dataset.territory)).toEqual(["air", "water", "mobility"]);
    for (const c of cards) expect(c.querySelectorAll("img")).toHaveLength(1);
    expect(cards.map((c) => c.querySelector("img")!.getAttribute("alt"))).toEqual(["Estaciones de medida en Alemania", "Puntos de muestreo en los ríos de Northumberland y Tyne", "Zonas de taxi de Nueva York"]);
    // a static SVG asset (vite inlines the small ones as a data URI), never a tile or a remote URL
    for (const c of cards) expect(c.querySelector("img")!.getAttribute("src")).toMatch(/^(\/src\/assets\/landing\/\w+\.svg|data:image\/svg\+xml)/);
    unmount();
    render(<Root initialLang="en" />);
    expect([...landing()!.querySelectorAll("li.lp-card img")].map((i) => i.getAttribute("alt"))).toEqual(["Measurement stations in Germany", "Sampling points on the Northumberland and Tyne rivers", "Taxi zones of New York"]);
  });

  it("the tab named in the prose is in italics (Patrones / Patterns)", () => {
    const { unmount } = render(<Root initialLang="es" />);
    const end = landing()!.querySelector(".lp-end .lp-text")!;
    expect(end).toHaveTextContent("La demo se abre en Patrones, con las reglas del primer territorio.");
    expect([...end.querySelectorAll("em")].map((e) => e.textContent)).toEqual(["Patrones"]);
    unmount();
    render(<Root initialLang="en" />);
    expect([...landing()!.querySelectorAll(".lp-end .lp-text em")].map((e) => e.textContent)).toEqual(["Patterns"]);
  });

  it("«Empezar la demo» opens the app, remembers it for the session and puts the focus on the app's main heading", async () => {
    render(<Root initialLang="es" />);
    await userEvent.setup().click(screen.getAllByRole("button", { name: "Empezar la demo" })[0]!);
    expect(landing()).toBeNull();
    expect(tabs()).not.toBeNull();
    expect(window.sessionStorage.getItem("atlas.demo.started")).toBe("1");
    const h1 = await screen.findByRole("heading", { level: 1, name: "Patrones: las reglas del modelo" });
    await waitFor(() => expect(h1).toHaveFocus());
  });

  it("keeps the language chosen on the landing in the app", async () => {
    render(<Root initialLang="es" />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "English" }));
    await user.click(screen.getAllByRole("button", { name: "Start the demo" })[0]!);
    expect(await screen.findByRole("heading", { level: 1, name: "Patterns: the model's rules" })).toBeInTheDocument();
  });

  it("a reload after starting opens the app (session memory)", () => {
    window.sessionStorage.setItem("atlas.demo.started", "1");
    render(<Root initialLang="es" />);
    expect(landing()).toBeNull();
    expect(tabs()).not.toBeNull();
  });

  it("«Sobre esta demo» in the app's header reopens the landing and forgets the start", async () => {
    window.sessionStorage.setItem("atlas.demo.started", "1");
    render(<Root initialLang="es" />);
    await userEvent.setup().click(screen.getByRole("button", { name: "Sobre esta demo" }));
    expect(landing()).not.toBeNull();
    expect(window.sessionStorage.getItem("atlas.demo.started")).toBeNull();
    await waitFor(() => expect(screen.getByRole("heading", { level: 1 })).toHaveFocus());
  });

  it("a deep link, ?demo=1 or a hash route goes straight to the app; ?lang= alone does not", () => {
    window.history.replaceState({}, "", "/?demo=1");
    const { unmount } = render(<Root initialLang="es" />);
    expect(landing()).toBeNull();
    unmount();
    window.history.replaceState({}, "", "/?lang=en");
    render(<Root initialLang="en" />);
    expect(landing()).not.toBeNull();
    expect(skipsLanding("", "")).toBe(false);
    expect(skipsLanding("?lang=es", "")).toBe(false);
    expect(skipsLanding("?demo=0", "")).toBe(false);
    for (const q of ["?demo=1", "?tab=prediccion", "?domain=air", "?task=de_no2_h1", "?entity=DEBW118", "?lang=en&tab=patrones"]) expect(skipsLanding(q, "")).toBe(true);
    expect(skipsLanding("", "#/patrones")).toBe(true);
  });

  it("its floating artifacts are drawn from the API's data and hidden from screen readers", async () => {
    render(<Root initialLang="es" />);
    const arts = await screen.findByTestId("landing-artifacts");
    expect(arts).toHaveAttribute("aria-hidden", "true");
    const rule = await within(arts).findByTestId("landing-rule");
    // the rule that decides most in the fixture's importance, with its share in the ring
    const top = [...classifierV05().importance!.rules].sort((a, b) => (b.decided_share ?? 0) - (a.decided_share ?? 0))[0]!;
    expect(rule).toHaveTextContent(`Regla ${top.rule_id}`);
    expect(within(arts).getByTestId("landing-perf")).toHaveTextContent("ExFuzzy");
  });

  it("without the API the landing still says everything and draws no artifact (no number is made up)", async () => {
    installApi({ "/domains": () => Promise.resolve(json({ detail: "down" }, 503)) }, classifierV05());
    render(<Root initialLang="es" />);
    await waitFor(() => expect(screen.getByRole("heading", { level: 1 })).toBeInTheDocument());
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByTestId("landing-artifacts")).toBeNull();
    expect(landing()).toHaveTextContent("Datos públicos de tres lugares");
  });
});
