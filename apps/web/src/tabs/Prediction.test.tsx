import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ModelCard } from "../api/types";
import { AccuracyBlock, verdict } from "../components/AccuracyBlock";
import { exampleIssue, inputColumns } from "../components/HorizonBox";
import { App } from "../App";
import { installApi } from "../test/fakeApi";
import * as cls from "../test/fixturesClass";
import { resetMaps } from "../test/maplibreMock";
import { classifierV05 } from "../test/v05";
import { labelerFor } from "../lib/labels";
import type { ObservationsResponse } from "../api/types";
import { setLang } from "../i18n";

vi.mock("maplibre-gl", async () => (await import("../test/maplibreMock")).maplibreFactory());

beforeEach(() => resetMaps());
afterEach(() => vi.unstubAllGlobals());

describe("Predicción: the horizon box", () => {
  it("explains in one sentence what is predicted and for when, with an example hour in local time", async () => {
    installApi({}, classifierV05());
    render(<App initialTab="prediccion" />);
    const sentence = await screen.findByTestId("horizon-sentence");
    expect(sentence).toHaveTextContent(/Con los datos disponibles a la hora de emisión \(p\. ej\. 08:00 hora local\), el modelo prevé el nivel de y para las 14:00 \(\+6 h\)\./);
    expect(screen.getByTestId("page-lead")).toHaveTextContent("a +6 h");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(/^Predicción:/);
  });

  it("picks an example issue at 08:00 local a week into the coverage", () => {
    const iso = exampleIssue({ issued_from_utc: "2025-01-01T00:00:00Z", issued_to_utc: "2025-12-31T16:00:00Z", step_hours: 1 }, "Europe/Madrid");
    expect(iso).toBe("2025-01-08T07:00:00Z"); // 08:00 in Madrid in winter
  });

  it("groups the inputs by how old they are at the issue time, read from the published observed_at and never guessed", () => {
    const at = "2025-03-04T07:00:00Z";
    const input = (feature: string, observed: string, source = "madrid-air") => ({ feature, value: 1, unit: "ug/m3", observed_at_utc: observed, source_id: source, missing_reason: null });
    const obs = {
      features: [
        { properties: { issued_at_utc: null, inputs: [] } },
        {
          properties: {
            issued_at_utc: at,
            inputs: [input("no2_last", "2025-03-04T06:00:00Z"), input("no2_lag3h", "2025-03-04T03:00:00Z"), input("wind_speed", "2025-03-04T06:00:00Z", "madrid-meteo"), input("valid_hour_local", at, "calendar")],
          },
        },
      ],
    } as unknown as ObservationsResponse;
    const cols = inputColumns(obs, labelerFor([]), new Map([["no2_last", "ug/m3"]]));
    expect(cols.map((c) => c.lagHours)).toEqual([4, 1, 0]); // oldest first
    expect(cols[1]!.inputs.map((i) => i.label)).toEqual(["NO₂ hace 1 h (último dato, µg/m³)", "Velocidad del viento"]);
    expect(cols[2]!.inputs.map((i) => i.label)).toEqual(["Hora de validez (local)"]);
  });
});

describe("Predicción: ¿Cuánto acierta?", () => {
  const card = { ...cls.card, target_scheme: cls.icaScheme, metrics: { ...cls.card.metrics!, rows: cls.icaMetrics.rows } } as ModelCard;

  it("says in plain words how often the category is right, next to the simplest baseline on the same rows, and per category", () => {
    render(<AccuracyBlock card={card} unit="u" />);
    const lead = screen.getByTestId("accuracy-sentence");
    expect(lead).toHaveTextContent(/El modelo acierta la categoría en 74 de cada 100 predicciones\./);
    expect(lead).toHaveTextContent(/repetir la categoría de la última observación acierta \d+ de cada 100/);
    const table = screen.getByRole("table", { name: "Acierto por categoría" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(cls.icaScheme.classes.length);
    expect(rows[0]).toHaveTextContent(/Buena\s*151\.101\s*80\s%\s*90\s%/);
    expect(screen.getByText(/periodo de prueba \(2024\)|periodo de prueba \(entre/)).toBeInTheDocument();
  });

  it("makes the comparison with the baseline visible, and says plainly when the model is below it", () => {
    render(<AccuracyBlock card={card} unit="u" />);
    const v = screen.getByTestId("baseline-verdict");
    expect(v).toHaveAttribute("data-verdict", "peor"); // 0.736 against persistence 0.769 in the real ICA report
    expect(v).toHaveTextContent(/el modelo queda por debajo de esa referencia en exactitud \(73,6 frente a 76,9 de cada 100\)/);
    const table = screen.getByRole("table", { name: "Comparación con la referencia" });
    expect(within(table).getByRole("row", { name: /Exactitud\s+0,736\s+0,769\s+peor/ })).toBeInTheDocument();
    expect(within(table).getAllByRole("row")).toHaveLength(4); // header, accuracy, balanced accuracy, macro F1
  });

  it("verdict: a tie within half a point is a tie; direction follows the metric", () => {
    expect([verdict(0.8, 0.7, true), verdict(0.7, 0.8, true), verdict(0.7, 0.703, true)]).toEqual(["mejor", "peor", "igual"]);
    expect([verdict(2, 3, false), verdict(3, 2, false), verdict(2.001, 2, false)]).toEqual(["mejor", "peor", "igual"]);
  });

  it("says so when the model publishes no metrics", () => {
    render(<AccuracyBlock card={{ ...card, metrics: null } as unknown as ModelCard} unit="u" />);
    expect(screen.getByText("Este modelo no publica métricas de evaluación.")).toBeInTheDocument();
  });
});

describe("Prediction in English: how often is it right?", () => {
  const card = { ...cls.card, target_scheme: cls.icaScheme, metrics: { ...cls.card.metrics!, rows: cls.icaMetrics.rows } } as ModelCard;
  afterEach(() => setLang("es"));

  it("says the hit rate, the verdict against the baseline and the per-category table in English", () => {
    setLang("en");
    render(<AccuracyBlock card={card} unit="u" />);
    expect(screen.getByRole("heading", { name: "How often is it right?" })).toBeInTheDocument();
    const lead = screen.getByTestId("accuracy-sentence");
    expect(lead).toHaveTextContent(/^The model gets the category right in 74 out of every 100 predictions\. For comparison, repeating the category of the last observation gets \d+ out of 100 right\.$/);
    const v = screen.getByTestId("baseline-verdict");
    expect(v).toHaveAttribute("data-verdict", "peor");
    expect(v).toHaveTextContent(/the model does worse than that reference on accuracy \(73\.6 against 76\.9 out of 100\)/);
    const table = screen.getByRole("table", { name: "Comparison with the reference" });
    expect(within(table).getByRole("row", { name: /Accuracy\s+0\.736\s+0\.769\s+worse/ })).toBeInTheDocument();
    const perClass = screen.getByRole("table", { name: "Hit rate per category" });
    expect(within(perClass).getAllByRole("row")[1]).toHaveTextContent(/Buena\s*151,101\s*80%\s*90%/);
    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/probabilit|risk|contribut|caus(e|al)|certaint|confiden/i);
    expect(text).not.toMatch(/[áéíóúñ¿¡]/);
  });

  it("says so in English when the model publishes no metrics", () => {
    setLang("en");
    render(<AccuracyBlock card={{ ...card, metrics: null } as unknown as ModelCard} unit="u" />);
    expect(screen.getByText("This model publishes no evaluation metrics.")).toBeInTheDocument();
  });

  it("horizon box: the sentence, the example and the leakage note are in English", async () => {
    installApi({}, classifierV05());
    render(<App initialLang="en" initialTab="prediccion" />);
    const sentence = await screen.findByTestId("horizon-sentence");
    expect(sentence).toHaveTextContent(/^With the data available at the issue time \(e\.g\. 08:00 local time\), the model predicts .+ for 14:00 \(\+6 h\)\.$/);
    expect(screen.getByRole("heading", { name: "What does it predict for?" })).toBeInTheDocument();
    expect(screen.getByText("How the model avoids data from the future")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(/^Prediction:/);
    expect(screen.getByTestId("page-lead")).toHaveTextContent(/^You are looking at what the model predicts .+ for each station in .+, next to what was observed afterwards\. The data run from .+ to .+\.$/);
  });
});
