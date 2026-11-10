import { describe, expect, it } from "vitest";
import { MAGMA, VIRIDIS } from "../lib/colorScale";
import {
  buildLayers,
  HATCH_IMAGE,
  LAYER_FILL,
  LAYER_FILL_MISSING,
  LAYER_MISSING,
  LAYER_NOREF,
  LAYER_SELECTED,
  LAYER_UNMODELLED,
  LAYER_UNMODELLED_POINT,
  LAYER_VALID,
  LINE_MISSING,
  LINE_NOREF,
  LINE_SELECTED,
  LINE_UNMODELLED,
  LINE_VALID,
  type LayerOptions,
} from "./mapLayers";

const opts: LayerOptions = { kind: "values", stops: VIRIDIS, domain: [0, 1], emphasis: 0.5, selectedId: "SYN_B" };
const layer = (o: LayerOptions, id: string) => {
  const l = buildLayers(o).find((x) => x.id === id)!;
  return { ...l, paint: l.paint as Record<string, unknown>, filter: l.filter as unknown[] };
};
// Circle layers only draw Point features (they would otherwise also draw polygon vertices).
const POINT = ["==", ["geometry-type"], "Point"];
const POLYGON = ["==", ["geometry-type"], "Polygon"];
// Entities the model has no data for have their own layers: the value, class and missing layers never take them.
const MODELLED = ["!=", ["get", "missing_reason"], "not_modelled"];
const UNMODELLED = ["==", ["get", "missing_reason"], "not_modelled"];
const SOMETIMES = ["!=", ["get", "no_predictions"], true];
const QUIET = ["any", UNMODELLED, ["==", ["get", "no_predictions"], true]];

describe("buildLayers", () => {
  it("colours the value layer from properties.value with a data-driven expression", () => {
    const color = layer(opts, LAYER_VALID).paint!["circle-color"] as unknown[];
    expect(color.slice(0, 3)).toEqual(["interpolate", ["linear"], ["get", "value"]]);
    // stops cover the whole 0-1 domain with the viridis palette
    expect(color[3]).toBe(0);
    expect(color[4]).toBe(VIRIDIS[0]![1]);
    expect(color[color.length - 2]).toBe(1);
    expect(color[color.length - 1]).toBe(VIRIDIS[VIRIDIS.length - 1]![1]);
  });

  it("shrinks station dots when zoomed out (a country-wide map with ~400 stations) and keeps full size from city zoom", () => {
    for (const id of [LAYER_VALID, LAYER_MISSING, LAYER_SELECTED]) {
      const r = layer(opts, id).paint["circle-radius"] as unknown[];
      expect(r.slice(0, 3)).toEqual(["interpolate", ["linear"], ["zoom"]]);
      expect(r[3]).toBeLessThan(r[5] as number); // zoom 4 < zoom 8
      expect(r[r.length - 2]).toBe(11); // the last stop is zoom 11: from there on the dot keeps its full size
    }
    expect(layer(opts, LAYER_VALID).paint["circle-radius"]).toEqual([
      "interpolate", ["linear"], ["zoom"], 4, ["*", 0.4, ["case", [">=", ["get", "value"], 0.5], 11, 8]], 8, ["*", 0.7, ["case", [">=", ["get", "value"], 0.5], 11, 8]], 11, ["case", [">=", ["get", "value"], 0.5], 11, 8],
    ]);
  });

  it("dims (does not remove) points below the visual emphasis threshold", () => {
    const l = layer(opts, LAYER_VALID);
    expect(l.filter).toEqual(["all", POINT, MODELLED, ["==", ["typeof", ["get", "value"]], "number"]]);
    expect(JSON.stringify(l.paint!["circle-opacity"])).toContain('[">=",["get","value"],0.5]');
    const noEmphasis = layer({ ...opts, emphasis: null }, LAYER_VALID);
    expect(noEmphasis.paint!["circle-opacity"]).toBe(0.95);
  });

  it("draws null as a separate hollow grey ring that is never styled by value", () => {
    const l = layer(opts, LAYER_MISSING);
    expect(l.filter).toEqual(["all", POINT, ["!=", ["typeof", ["get", "value"]], "number"], MODELLED, SOMETIMES]);
    expect(l.paint!["circle-opacity"]).toBe(0);
    expect(l.paint!["circle-stroke-width"]).toBeGreaterThan(2);
    expect(JSON.stringify(l.paint)).not.toContain('"get","value"');
  });

  it("uses the concentration domain and palette for prediction, and highlights the selection", () => {
    const l = layer({ ...opts, stops: MAGMA, domain: [0, 80], emphasis: null }, LAYER_VALID);
    const color = l.paint!["circle-color"] as unknown[];
    expect(color[color.length - 2]).toBe(80);
    expect(color[4]).toBe(MAGMA[0]![1]);
    expect(layer(opts, LAYER_SELECTED).filter).toEqual(["all", POINT, ["==", ["get", "entity_id"], "SYN_B"]]);
  });

  it("neutral kind has no value-driven colour and no missing layer", () => {
    const neutral = { ...opts, kind: "neutral" } as LayerOptions;
    expect(JSON.stringify(layer(neutral, LAYER_VALID).paint)).not.toContain('"get","value"');
    expect(layer(neutral, LAYER_MISSING).filter).toEqual(["all", POINT, false]);
  });

  it("categories kind colours by the class label with the scheme's colours and keeps null labels as hollow rings", () => {
    const cat: LayerOptions = {
      ...opts,
      kind: "categories",
      emphasis: null,
      classes: [
        { label: "Buena", color: "#00FFFF" },
        { label: "Regular", color: "#FFCC00" },
      ],
    };
    const valid = layer(cat, LAYER_VALID);
    expect(valid.paint!["circle-color"]).toEqual(["match", ["get", "label"], "Buena", "#00FFFF", "Regular", "#FFCC00", "#94a3b8"]);
    expect(valid.filter).toEqual(["all", POINT, MODELLED, ["==", ["typeof", ["get", "label"]], "string"]]);
    expect(layer(cat, LAYER_MISSING).filter).toEqual(["all", POINT, ["!=", ["typeof", ["get", "label"]], "string"], MODELLED, SOMETIMES]);
    expect(JSON.stringify(valid.paint)).not.toContain('"get","value"');
  });
  describe("polygons (taxi zones)", () => {
    const cat: LayerOptions = {
      ...opts,
      kind: "categories",
      emphasis: null,
      classes: [
        { label: "baja", color: "#DEEBF7" },
        { label: "muy alta", color: "#08306B" },
      ],
    };

    it("fills polygons from the API class label with the scheme's colours (a choropleth, not an interpolation)", () => {
      const fill = layer(cat, LAYER_FILL);
      expect(fill.type).toBe("fill");
      expect(fill.paint["fill-color"]).toEqual(["match", ["get", "label"], "baja", "#DEEBF7", "muy alta", "#08306B", "#94a3b8"]);
      expect(fill.filter).toEqual(["all", POLYGON, MODELLED, ["==", ["typeof", ["get", "label"]], "string"]]);
      expect(JSON.stringify(fill.paint)).not.toContain('"get","value"');
    });

    it("fills polygons from the API value with the same data-driven expression as the circles", () => {
      const fill = layer(opts, LAYER_FILL);
      expect(fill.paint["fill-color"]).toEqual(layer(opts, LAYER_VALID).paint["circle-color"]);
      expect(fill.filter).toEqual(["all", POLYGON, MODELLED, ["==", ["typeof", ["get", "value"]], "number"]]);
      expect(JSON.stringify(fill.paint["fill-opacity"])).toContain('[">=",["get","value"],0.5]');
    });

    it("draws 'sin referencia' as a hatch with a dashed outline, never with a class colour", () => {
      const noRef = layer(cat, LAYER_NOREF);
      expect(noRef.paint["fill-pattern"]).toBe(HATCH_IMAGE);
      expect(noRef.paint["fill-color"]).toBeUndefined();
      expect(noRef.filter).toEqual(["all", POLYGON, ["==", ["get", "no_reference"], true], ["!=", ["typeof", ["get", "label"]], "string"], MODELLED, SOMETIMES]);
      expect(layer(cat, LINE_NOREF).paint["line-dasharray"]).toBeDefined();
      // a polygon with a class never takes the hatch: the hatch requires a missing label
      expect(JSON.stringify(layer(cat, LAYER_FILL).filter)).not.toContain("no_reference");
    });

    it("draws other missing polygons as a pale wash with a solid grey outline, apart from the hatch", () => {
      const missing = layer(cat, LAYER_FILL_MISSING);
      expect(missing.paint["fill-color"]).toBe("#ffffff");
      expect(missing.filter).toEqual(["all", POLYGON, ["!=", ["get", "no_reference"], true], ["!=", ["typeof", ["get", "label"]], "string"], MODELLED, SOMETIMES]);
      expect(layer(cat, LINE_MISSING).paint["line-color"]).toBe("#4b5563");
      expect(layer(cat, LINE_MISSING).paint["line-dasharray"]).toBeUndefined();
    });

    it("draws 'sin modelo' entities light and quiet: a faint fill and thin line, a small dot for a point, never the heavy missing outline", () => {
      const fill = layer(cat, LAYER_UNMODELLED);
      expect(fill.filter).toEqual(["all", POLYGON, QUIET]);
      expect(fill.paint["fill-opacity"]).toBeLessThan(0.3);
      expect(layer(cat, LINE_UNMODELLED).paint["line-width"]).toBeLessThan(1);
      expect(layer(cat, LINE_UNMODELLED).filter).toEqual(["all", POLYGON, QUIET]);
      const dot = layer(cat, LAYER_UNMODELLED_POINT);
      expect(dot.filter).toEqual(["all", POINT, QUIET]);
      expect(dot.paint["circle-radius"]).toBeLessThan(6);
      // the missing layers exclude them in every kind
      for (const o of [cat, opts]) {
        expect(JSON.stringify(layer(o, LINE_MISSING).filter)).toContain("not_modelled");
        expect(layer(o, LINE_MISSING).paint["line-width"]).toBeGreaterThan(layer(o, LINE_UNMODELLED).paint["line-width"] as number);
      }
    });

    it("colours on the square root of the value when asked (Data mode counts), with the same stops", () => {
      const sqrt = layer({ ...opts, domain: [0, 100], scale: "sqrt", emphasis: null }, LAYER_VALID).paint["circle-color"] as unknown[];
      expect(sqrt.slice(0, 3)).toEqual(["interpolate", ["linear"], ["sqrt", ["max", ["get", "value"], 0]]]);
      expect(sqrt[3]).toBe(0);
      expect(sqrt[sqrt.length - 2]).toBe(10); // sqrt(100)
    });

    it("outlines valid polygons thinly and the selected one thickly", () => {
      expect(layer(cat, LINE_VALID).paint["line-width"]).toBeLessThan(2);
      const sel = layer({ ...cat, selectedId: "4" }, LINE_SELECTED);
      expect(sel.filter).toEqual(["all", POLYGON, ["==", ["get", "entity_id"], "4"]]);
      expect(sel.paint["line-width"]).toBeGreaterThan(3);
    });

    it("keeps polygons under the points in the layer order", () => {
      const ids = buildLayers(cat).map((l) => l.id);
      expect(ids.indexOf(LAYER_FILL)).toBeLessThan(ids.indexOf(LINE_VALID));
      expect(ids.indexOf(LINE_SELECTED)).toBeLessThan(ids.indexOf(LAYER_VALID));
    });
  });
});
