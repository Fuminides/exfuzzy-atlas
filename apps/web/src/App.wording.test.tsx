import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App, type Tab } from "./App";
import { installApi } from "./test/fakeApi";
import { resetMaps } from "./test/maplibreMock";
import userEvent from "@testing-library/user-event";
import { mixtureV07 } from "./test/fixturesMixture";
import { classifierV05, regressionV05 } from "./test/v05";

vi.mock("maplibre-gl", async () => (await import("./test/maplibreMock")).maplibreFactory());

beforeEach(() => resetMaps());
afterEach(() => vi.unstubAllGlobals());

/** Words that must never describe what the new tabs show: a firing is not a probability, a risk, a contribution or a cause. */
const FORBIDDEN = /probabilidad|riesgo|contribuci[oó]n|causa(?:l|s)?\b|causalidad|certeza|confianza/i;
/** Importance means "decides and hits"; it must never sit next to the word activation, in either order. */
const IMPORTANCE_NEXT_TO_ACTIVATION = /importancia[^.]{0,60}activaci[oó]n|activaci[oó]n[^.]{0,60}importancia/i;

const ready: Record<Tab, () => Promise<unknown>> = {
  resumen: () => screen.findByRole("img", { name: /Todas las observaciones/ }),
  patrones: () => screen.findByText("Qué variables intervienen más"),
  prediccion: () => screen.findByTestId("report-link"),
  rendimiento: () => screen.findByTestId("perf-bars"),
  explorar: () => screen.findByRole("region", { name: /Leyenda/ }),
};

/** Text of what the redesign owns on each tab (Predicción and Explorar also host the expert tools, which have their own tests). */
const owned = (tab: Tab): string => {
  if (tab === "prediccion") return ["header.page-head", ".horizon-box", ".accuracy"].map((s) => document.querySelector(s)?.textContent ?? "").join(" ");
  return document.querySelector("main")!.textContent ?? "";
};

describe("wording guard", () => {
  for (const tab of ["resumen", "patrones", "prediccion", "rendimiento"] as const) {
    it(`${tab}: no probability, risk, contribution or causality words, and importance is never about activation`, async () => {
      installApi({}, classifierV05());
      render(<App initialTab={tab} />);
      await ready[tab]();
      await waitFor(() => expect(owned(tab).length).toBeGreaterThan(200));
      const text = owned(tab);
      expect(text).not.toMatch(FORBIDDEN);
      expect(text).not.toMatch(IMPORTANCE_NEXT_TO_ACTIVATION);
      expect(text).not.toMatch(/activaci[oó]n/i); // activation belongs to Explorar
    });
  }

  it("patrones (regression): same guard", async () => {
    installApi({}, regressionV05());
    render(<App initialTab="patrones" />);
    await ready.patrones();
    expect(owned("patrones")).not.toMatch(FORBIDDEN);
    expect(owned("patrones")).not.toMatch(/activaci[oó]n/i);
  });

  // The legend of Por zonas changes once a rule is picked (its own sentence): the guard reads it too.
  for (const [name, data] of [["classifier", classifierV05], ["mixture of rules (v0.7)", mixtureV07]] as const) {
    it(`patrones (${name}), with a rule picked on the map: same guard`, async () => {
      installApi({}, data());
      render(<App initialTab="patrones" />);
      await ready.patrones();
      await userEvent.click(await screen.findByRole("button", { name: /Mostrar en el mapa la regla R02/ }));
      await screen.findByRole("region", { name: /Leyenda: parte de las predicciones/ });
      const text = owned("patrones");
      expect(text).not.toMatch(FORBIDDEN);
      expect(text).not.toMatch(/activaci[oó]n/i);
    });
  }

  it("patrones (mixture of rules, v0.7): same guard, and no rule is said to decide", async () => {
    installApi({}, mixtureV07());
    render(<App initialTab="patrones" />);
    await ready.patrones();
    await screen.findAllByTestId("class-weights");
    const text = owned("patrones");
    expect(text).not.toMatch(FORBIDDEN);
    expect(text).not.toMatch(IMPORTANCE_NEXT_TO_ACTIVATION);
    expect(text).not.toMatch(/activaci[oó]n/i);
    // «ninguna regla decide sola» is the only way «decide» may appear
    expect(text.replace(/[Nn]inguna regla decide sola/g, "")).not.toMatch(/decid|ganador/i);
  });

  it("explorar: activation is labelled as what it is, and 'importancia' never appears about it", async () => {
    installApi({}, classifierV05());
    render(<App initialTab="explorar" />);
    await ready.explorar();
    expect(screen.getByTestId("page-lead")).toHaveTextContent("La activación (0–1)");
    expect(screen.getByTestId("page-lead")).toHaveTextContent("mide lo bien que se cumple la condición de la regla");
    expect(owned("explorar")).not.toMatch(/importancia/i);
  });

  it("no raw identifier of the models' inputs appears in the new tabs", async () => {
    installApi({}, classifierV05());
    render(<App initialTab="patrones" />);
    await ready.patrones();
    expect(owned("patrones")).not.toMatch(/\b(y_t|y_lag3|exo_t)\b/);
  });
});
