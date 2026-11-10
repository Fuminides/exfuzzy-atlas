import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { water } from "../test/fixturesReal";
import { SampleChart } from "./SampleChart";

const series = water.series[0]!;
const w = { from: "2025-12-01T00:00:00Z", to: "2026-01-01T00:00:00Z" };

describe("SampleChart", () => {
  it("draws one pair of marks per sample (circle = observed, diamond = predicted) and no line between samples", () => {
    render(<SampleChart series={series} window={w} />);
    const chart = screen.getByTestId("sample-chart");
    expect(chart.querySelectorAll("[data-sample]")).toHaveLength(series.points.length);
    expect(chart.querySelectorAll("circle.obs")).toHaveLength(series.points.length);
    expect(chart.querySelectorAll("rect.pred")).toHaveLength(series.points.length);
    expect(chart.querySelector("polyline, path")).toBeNull();
    expect(chart.querySelector(".window-band")).not.toBeNull();
    expect(screen.getByRole("img")).toHaveAccessibleName(`oxígeno disuelto observado y predicho por muestra (mg/l) en ${series.entity_id}`);
    expect(chart).toHaveTextContent("inferencia sobre la misma muestra");
  });

  it("lists every sample in a table with its local time and the API values, marking those in the window", () => {
    render(<SampleChart series={series} window={w} />);
    const table = screen.getByRole("table", { name: new RegExp(`Muestras de ${series.entity_id} \\(mg/l\\)`) });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(series.points.length);
    const first = series.points[0]!;
    expect(rows[0]).toHaveTextContent("Europe/Madrid"); // no provider here: the default zone; the app wraps it in the entities' zone
    expect(rows[0]!.querySelectorAll("[data-raw]")[0]).toHaveAttribute("data-raw", String(first.observed));
    const inWindow = series.points.filter((p) => p.issued_at_utc >= w.from && p.issued_at_utc < w.to);
    expect(table.querySelectorAll('tr[data-in-window="true"]')).toHaveLength(inWindow.length);
  });

  it("keeps a missing prediction as a missing value with its reason, not as a mark", () => {
    const p = series.points[0]!;
    const missing = { ...series, points: [{ ...p, prediction: null, missing_reason: "missing_input" as const }] };
    render(<SampleChart series={missing} window={null} />);
    expect(screen.getByTestId("sample-chart").querySelectorAll("rect.pred")).toHaveLength(0);
    expect(screen.getByTestId("sample-chart")).toHaveTextContent("falta una entrada");
  });

  it("says so when a point has no samples", () => {
    render(<SampleChart series={{ ...series, points: [] }} window={w} />);
    expect(screen.getByText(/no tiene muestras/)).toBeInTheDocument();
  });
});
