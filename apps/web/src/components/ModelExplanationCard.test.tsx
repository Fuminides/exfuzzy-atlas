import { act, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { setLang } from "../i18n";
import * as cls from "../test/fixturesClass";
import { fake, installApi } from "../test/fakeApi";
import { resetMaps } from "../test/maplibreMock";
import { classifierExplanation, classifierV05 } from "../test/v05";

vi.mock("maplibre-gl", async () => (await import("../test/maplibreMock")).maplibreFactory());

beforeEach(() => resetMaps());
afterEach(() => {
  vi.unstubAllGlobals();
  setLang("es");
});

const ready = (name: string) => screen.findByText(name);
const card = () => screen.getByTestId("model-explanation");

describe("«Qué hacen estas reglas» (contract v0.6.2)", () => {
  it("shows only the Spanish points above the rules (not the headline or paragraphs), with the AI note", async () => {
    installApi({}, classifierV05());
    render(<App initialTab="patrones" />);
    expect(await screen.findByRole("heading", { name: "Qué hacen estas reglas" })).toBeInTheDocument();
    expect(card()).toHaveTextContent("El modelo no prevé nunca la categoría más alta.");
    expect(card()).not.toHaveTextContent("Casi todas las predicciones las decide R01");
    expect(card()).not.toHaveTextContent("R01 decide el 40 % de las predicciones");
    expect(within(card()).getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByTestId("ai-note")).toHaveTextContent(
      "Texto redactado por Claude (IA) a partir de las reglas y las métricas publicadas de este modelo. Todavía no lo ha revisado ninguna persona.",
    );
    // below «Las reglas de un vistazo», above the rule cards
    const glance = screen.getByRole("heading", { name: "Las reglas de un vistazo" });
    expect(glance.compareDocumentPosition(card()) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const rules = screen.getByRole("heading", { name: "Las reglas" });
    expect(card().compareDocumentPosition(rules) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("turns the rule ids of a point into rule cards, only for the rules this model has", async () => {
    const base = classifierExplanation(cls.rules.model_id, cls.rules.data_version);
    const explanation = { ...base, es: { ...base.es, points: ["R04 y R99 no se parecen.", ...base.es.points.slice(1)] } };
    installApi({}, { ...classifierV05(), explanation });
    render(<App initialTab="patrones" />);
    await screen.findByRole("heading", { name: "Qué hacen estas reglas" });
    const point = within(card()).getAllByRole("listitem")[0]!;
    expect(point).toHaveTextContent("R04 y R99 no se parecen.");
    expect(within(point).getAllByRole("button").map((b) => b.textContent)).toEqual(["R04"]);
    act(() => within(point).getByRole("button", { name: "R04" }).focus());
    expect(await screen.findByRole("tooltip")).toHaveTextContent("Regla R04");
  });

  it("says when a person has reviewed the text", async () => {
    installApi({}, { ...classifierV05(), explanation: classifierExplanation(cls.rules.model_id, cls.rules.data_version, true) });
    render(<App initialTab="patrones" />);
    expect(await screen.findByTestId("ai-note")).toHaveTextContent(", y revisado por una persona.");
    expect(screen.getByTestId("ai-note")).not.toHaveTextContent("Todavía no");
  });

  it("in English: the English text and note", async () => {
    installApi({}, classifierV05());
    render(<App initialLang="en" initialTab="patrones" />);
    expect(await screen.findByRole("heading", { name: "What these rules do" })).toBeInTheDocument();
    expect(card()).toHaveTextContent("The model never predicts the highest category.");
    expect(card()).not.toHaveTextContent("Almost every prediction");
    expect(card()).not.toHaveTextContent("El modelo no prevé");
    expect(screen.getByTestId("ai-note")).toHaveTextContent("Text written by Claude (AI) from this model's published rules and metrics. No one has reviewed it yet.");
  });

  it("a model without an explanation (404) shows nothing in its place", async () => {
    installApi({}, classifierV05({ explanation: false }));
    render(<App initialTab="patrones" />);
    await ready("Qué variables intervienen más");
    await waitFor(() => expect(fake.calls.some((c) => c.endsWith("/explanation"))).toBe(true));
    expect(screen.queryByRole("heading", { name: "Qué hacen estas reglas" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("ai-note")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("a failing request is an error with a retry, and the rules still show", async () => {
    const path = `/models/${cls.rules.model_id}/explanation`;
    installApi({ [path]: async () => new Response(JSON.stringify({ detail: "boom" }), { status: 500 }) }, classifierV05());
    render(<App initialTab="patrones" />);
    expect(await screen.findByText(/No se pudo cargar la explicación de las reglas/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Las reglas" })).toBeInTheDocument();
  });
});
