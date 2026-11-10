import { describe, expect, it } from "vitest";
import { VIRIDIS } from "../lib/colorScale";
import { buildLayers, LAYER_VALID, LINE_VALID, type LayerOptions } from "./mapLayers";

// docs/qa A11Y-1: the light end of every palette is below 3:1 against the basemap's land (#f2f3f0, OpenFreeMap
// positron), so the edge of a mark (point rim, polygon outline) must carry the contrast (WCAG 1.4.11).
const LAND = "#f2f3f0";
const lum = (hex: string) => {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0]! + 0.7152 * c[1]! + 0.0722 * c[2]!;
};
const contrast = (a: string, b: string) => {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
};
const options: LayerOptions = { kind: "values", stops: VIRIDIS, domain: [0, 1], emphasis: 0.5, selectedId: null };
const paint = (id: string) => buildLayers(options).find((l) => l.id === id)!.paint as Record<string, unknown>;

describe("map marks keep a visible edge on the light basemap", () => {
  it("valued points have a rim of at least 3:1 against the land", () => {
    expect(contrast(paint(LAYER_VALID)["circle-stroke-color"] as string, LAND)).toBeGreaterThanOrEqual(3);
    expect(paint(LAYER_VALID)["circle-stroke-width"]).toBeGreaterThan(0);
  });

  it("valued polygons have an outline of at least 3:1 against the land", () => {
    expect(contrast(paint(LINE_VALID)["line-color"] as string, LAND)).toBeGreaterThanOrEqual(3);
  });

  it("the palette ends that motivated it really are below 3:1 (ICA «Buena», viridis 1)", () => {
    expect(contrast("#00FFFF", LAND)).toBeLessThan(3);
    expect(contrast(VIRIDIS[VIRIDIS.length - 1]![1], LAND)).toBeLessThan(3);
  });
});
