import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { series } from "../test/fixtures";
import { SeriesChart } from "./SeriesChart";

describe("SeriesChart", () => {
  it("labels the concentration unit and breaks the prediction line at a missing value", () => {
    const sD = series.find((s) => s.entity_id === "SYN_D")!;
    const { container } = render(<SeriesChart series={sD} selectedIssue={null} />);
    expect(screen.getByRole("img")).toHaveAccessibleName(/NO₂ observado y predicho \(µg\/m³\)/);
    expect(container.textContent).toContain("NO₂ (µg/m³)");
    expect(container).toHaveTextContent("falta una entrada");
    // 6 points with the third prediction missing: two prediction segments, never one joined line.
    expect(container.querySelectorAll("polyline.pred")).toHaveLength(2);
    expect(container.querySelectorAll("polyline.obs")).toHaveLength(1);
  });
});
