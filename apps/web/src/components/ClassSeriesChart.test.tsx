import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { scheme, series } from "../test/fixturesClass";
import { missingText } from "../lib/format";
import { ClassSeriesChart } from "./ClassSeriesChart";

const e0 = series.find((s) => s.entity_id === "E0")!;

describe("ClassSeriesChart", () => {
  it("draws the class bands from the scheme, the observed line, and never a predicted numeric line", () => {
    const { container } = render(<ClassSeriesChart series={e0} scheme={scheme} selectedIssue="2024-01-06T10:00:00Z" />);
    // Bands of the scheme (the invented low/mid/high), with the scheme's colours.
    const bands = [...container.querySelectorAll("[data-band]")].map((g) => g.getAttribute("data-band"));
    expect(bands).toEqual(scheme.classes.map((c) => c.label).slice(0, bands.length));
    expect(bands.length).toBeGreaterThan(0);
    expect((container.querySelector("[data-band] rect") as SVGRectElement).style.fill).toBe("rgb(0, 255, 255)");
    // One observed polyline; nothing styled as prediction, and the contract says `prediction` is null in every point.
    expect(e0.points.every((p) => p.prediction === null)).toBe(true);
    expect(container.querySelectorAll("polyline.obs").length).toBeGreaterThan(0);
    expect(container.querySelector(".pred")).toBeNull();
    expect(container.querySelector("polyline.pred")).toBeNull();
    expect(screen.getByText(/no hay línea de concentración prevista/)).toBeInTheDocument();
  });

  it("shows observed and predicted categories as strips coloured by the scheme, with a grey gap for a null label", () => {
    const { container } = render(<ClassSeriesChart series={e0} scheme={scheme} selectedIssue={null} />);
    const observed = container.querySelectorAll('[data-strip="observed"] rect');
    const predicted = container.querySelectorAll('[data-strip="predicted"] rect');
    expect(observed).toHaveLength(e0.points.length);
    expect(predicted).toHaveLength(e0.points.length);
    const nullPredictions = e0.points.filter((p) => p.predicted_label === null).length;
    expect(nullPredictions).toBeGreaterThan(0);
    expect(container.querySelectorAll('[data-strip="predicted"] rect.cell--missing')).toHaveLength(nullPredictions);
    const first = e0.points[0]!;
    expect(predicted[0]!.getAttribute("data-class")).toBe(first.predicted_label);
    expect((predicted[0] as SVGRectElement).style.fill).toBe("rgb(0, 255, 255)"); // low = #00FFFF
  });

  it("lists, in the data table, the observed value and both categories, or 'sin predicción' with its reason", () => {
    render(<ClassSeriesChart series={e0} scheme={scheme} selectedIssue={null} />);
    const nullRow = e0.points.find((p) => p.predicted_label === null)!;
    const table = screen.getByRole("table", { hidden: true });
    const rows = within(table).getAllByRole("row", { hidden: true });
    const row = rows.find((r) => r.textContent?.includes("sin predicción"))!;
    expect(row).toHaveTextContent(missingText(nullRow.missing_reason!));
    expect(row.querySelector("[data-raw]")?.getAttribute("data-raw")).toBe(String(nullRow.observed));
  });
});
