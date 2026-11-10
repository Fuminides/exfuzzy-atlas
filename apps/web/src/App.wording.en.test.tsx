import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { setLang } from "./i18n";
import { installApi } from "./test/fakeApi";
import { resetMaps } from "./test/maplibreMock";
import userEvent from "@testing-library/user-event";
import { mixtureV07 } from "./test/fixturesMixture";
import { classifierV05, regressionV05 } from "./test/v05";

vi.mock("maplibre-gl", async () => (await import("./test/maplibreMock")).maplibreFactory());

beforeEach(() => resetMaps());
afterEach(() => {
  vi.unstubAllGlobals();
  setLang("es");
});

/**
 * The English mirror of App.wording.test.tsx for Patterns and Summary: a firing is not a probability, a risk, a
 * contribution, a cause, a certainty or a confidence. ("because" also matches /cause/: these tabs avoid it.)
 */
const FORBIDDEN = /probabilit|risk|contribut|caus(e|al)|certaint|confiden/i;
const IMPORTANCE_NEXT_TO_ACTIVATION = /importance[^.]{0,60}activation|activation[^.]{0,60}importance/i;

const ready = {
  resumen: () => screen.findByRole("img", { name: /All the observations/ }),
  patrones: () => screen.findByText("Which variables take part most"),
};
/** The tab's own text. The basemap credit and the site credits ("© OpenStreetMap contributors") are licence wording, not the tab's. */
const text = () => {
  const main = document.querySelector("main")!.cloneNode(true) as HTMLElement;
  main.querySelectorAll(".map-attribution, .site-credits").forEach((n) => n.remove());
  return main.textContent ?? "";
};

describe("wording guard (English)", () => {
  for (const tab of ["resumen", "patrones"] as const) {
    it(`${tab}: no probability, risk, contribution or causality words, and importance is never about activation`, async () => {
      installApi({}, classifierV05());
      render(<App initialLang="en" initialTab={tab} />);
      await ready[tab]();
      await waitFor(() => expect(text().length).toBeGreaterThan(200));
      expect(text()).not.toMatch(FORBIDDEN);
      expect(text()).not.toMatch(IMPORTANCE_NEXT_TO_ACTIVATION);
      expect(text()).not.toMatch(/activation/i); // activation belongs to Explore
      // none of the web's own Spanish is left (the API's labels, which are data, may be Spanish: they are not checked)
      expect(text()).not.toMatch(/\b(las|los|reglas|predicciones|estaciones|observaciones|datos|cada)\b/i);
    });
  }

  for (const [name, data] of [["classifier", classifierV05], ["mixture of rules (v0.7)", mixtureV07]] as const) {
    it(`patrones (${name}), with a rule picked on the map: same guard`, async () => {
      installApi({}, data());
      render(<App initialLang="en" initialTab="patrones" />);
      await ready.patrones();
      await userEvent.click(await screen.findByRole("button", { name: /Show rule R02 on the map/ }));
      await screen.findByRole("region", { name: /Legend: share of the predictions/ });
      expect(text()).not.toMatch(FORBIDDEN);
      expect(text()).not.toMatch(/activation/i);
    });
  }

  it("patrones (mixture of rules, v0.7): same guard, no rule is said to decide, no Spanish left", async () => {
    installApi({}, mixtureV07());
    render(<App initialLang="en" initialTab="patrones" />);
    await ready.patrones();
    await screen.findAllByTestId("class-weights");
    expect(text()).not.toMatch(FORBIDDEN);
    expect(text()).not.toMatch(/activation/i);
    expect(text().replace(/[Nn]o (single )?rule decides( alone)?/g, "").replace(/none decides alone/g, "")).not.toMatch(/decid|winn/i);
    expect(text()).not.toMatch(/\b(las|los|reglas|predicciones|estaciones|observaciones|datos|cada|apoya|suma)\b/i);
  });

  it("patrones (regression): same guard", async () => {
    installApi({}, regressionV05());
    render(<App initialLang="en" initialTab="patrones" />);
    await ready.patrones();
    expect(text()).not.toMatch(FORBIDDEN);
    expect(text()).not.toMatch(/activation/i);
  });
});
