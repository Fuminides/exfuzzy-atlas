import type {
  CircleLayerSpecification,
  ExpressionSpecification,
  FillLayerSpecification,
  FilterSpecification,
  LineLayerSpecification,
} from "maplibre-gl";
import type { ColorStop } from "../lib/colorScale";

export const SOURCE_ID = "stations";
export const LAYER_VALID = "stations-valid";
export const LAYER_MISSING = "stations-missing";
export const LAYER_SELECTED = "stations-selected";
/** Polygon entities (NYC taxi zones): fill by value or class, a hatched fill for "sin referencia", outlines. */
export const LAYER_FILL = "zones-fill";
export const LAYER_NOREF = "zones-no-reference";
export const LAYER_FILL_MISSING = "zones-missing";
export const LINE_VALID = "zones-line";
export const LINE_MISSING = "zones-line-missing";
export const LINE_NOREF = "zones-line-no-reference";
export const LINE_SELECTED = "zones-line-selected";
/** Entities the model has no data for (`modelled: false`, NYC low-volume zones): drawn light and quiet, never as missing. */
export const LAYER_UNMODELLED = "zones-unmodelled";
export const LINE_UNMODELLED = "zones-line-unmodelled";
export const LAYER_UNMODELLED_POINT = "stations-unmodelled";
/** Image id of the hatch used by LAYER_NOREF (registered by the map component). */
export const HATCH_IMAGE = "no-reference-hatch";

export type MapLayerSpec = CircleLayerSpecification | FillLayerSpecification | LineLayerSpecification;

export interface LayerOptions {
  /**
   * "values": colour by `properties.value`; "categories": colour by `properties.label` with `classes` (classifier
   * prediction, rule territories); "neutral": no value layer (no rule chosen).
   */
  kind: "values" | "categories" | "neutral";
  stops: readonly ColorStop[];
  /** Value range mapped onto the scale: [0, 1] for activation, [0, max] for concentration. */
  domain: readonly [number, number];
  /** Visual emphasis only: stations below it are dimmed, never removed. null = no dimming. */
  emphasis: number | null;
  /** "sqrt": the colour follows the square root of the value (counts with a long tail); the legend says so. */
  scale?: "linear" | "sqrt";
  selectedId: string | null;
  /** Colour of each class label, from the model's target scheme (kind "categories"). */
  classes?: readonly { label: string; color: string }[];
}

/** The value as the API sent it. The client never computes memberships or firing. */
const VALUE: ExpressionSpecification = ["get", "value"];
const HAS_VALUE: ExpressionSpecification = ["==", ["typeof", VALUE], "number"];
const NO_VALUE: ExpressionSpecification = ["!=", ["typeof", VALUE], "number"];
const LABEL: ExpressionSpecification = ["get", "label"];
const HAS_LABEL: ExpressionSpecification = ["==", ["typeof", LABEL], "string"];
const NO_LABEL: ExpressionSpecification = ["!=", ["typeof", LABEL], "string"];
const NOTHING = false;
const IS_POINT: ExpressionSpecification = ["==", ["geometry-type"], "Point"];
const IS_POLYGON: ExpressionSpecification = ["==", ["geometry-type"], "Polygon"];
const UNMODELLED: ExpressionSpecification = ["==", ["get", "missing_reason"], "not_modelled"];
const MODELLED: ExpressionSpecification = ["!=", ["get", "missing_reason"], "not_modelled"];
const NO_REFERENCE: ExpressionSpecification = ["==", ["get", "no_reference"], true];
const NEVER_PREDICTED: ExpressionSpecification = ["==", ["get", "no_predictions"], true];
const SOMETIMES_PREDICTED: ExpressionSpecification = ["!=", ["get", "no_predictions"], true];
/** Drawn light and quiet: no model, or no prediction at any time of the published period. */
const QUIET: ExpressionSpecification = ["any", UNMODELLED, NEVER_PREDICTED];
const HAS_REFERENCE: ExpressionSpecification = ["!=", ["get", "no_reference"], true];

/** Data-driven colour: interpolates `properties.value` over the palette. */
export function colorExpression(
  stops: readonly ColorStop[],
  domain: readonly [number, number],
  scale: "linear" | "sqrt" = "linear",
): ExpressionSpecification {
  // sqrt: the stops sit on the square root of the value, so a few large counts do not flatten everything else.
  const [lo, hi] = scale === "sqrt" ? [Math.sqrt(domain[0]), Math.sqrt(domain[1])] : domain;
  const span = hi > lo ? hi - lo : 1;
  return [
    "interpolate",
    ["linear"],
    scale === "sqrt" ? ["sqrt", ["max", VALUE, 0]] : VALUE,
    ...stops.flatMap(([p, color]) => [lo + p * span, color] as [number, string]),
  ];
}

/** Categorical colour: the class label looked up in the scheme's colours. */
export function classColorExpression(classes: readonly { label: string; color: string }[]): ExpressionSpecification {
  return ["match", LABEL, ...classes.flatMap((c) => [c.label, c.color]), "#94a3b8"] as ExpressionSpecification;
}

const all = (...parts: FilterSpecification[]): FilterSpecification => ["all", ...parts] as FilterSpecification;

/** The value layers' filter: which features have something to colour, per kind of view. */
function validFilter(o: LayerOptions): FilterSpecification {
  return o.kind === "categories" ? HAS_LABEL : o.kind === "values" ? HAS_VALUE : true;
}
// "Sin modelo" entities are never "missing": they have their own, quieter layers.
function missingParts(o: LayerOptions): FilterSpecification[] {
  return o.kind === "categories" ? [NO_LABEL, MODELLED, SOMETIMES_PREDICTED] : o.kind === "values" ? [NO_VALUE, MODELLED, SOMETIMES_PREDICTED] : [NOTHING];
}

/**
 * Station dots shrink when the map is zoomed out: a country-wide view (about 400 EEA stations over Germany, zoom 5)
 * would otherwise be a blob of overlapping 22 px circles. From zoom 11 (a city, e.g. Madrid) they keep their full size.
 */
const zoomScaled = (radius: number | ExpressionSpecification): ExpressionSpecification => [
  "interpolate",
  ["linear"],
  ["zoom"],
  4,
  ["*", 0.4, radius],
  8,
  ["*", 0.7, radius],
  11,
  radius,
];

export function buildLayers(o: LayerOptions): MapLayerSpec[] {
  const emphasised: ExpressionSpecification | null =
    o.emphasis === null ? null : [">=", VALUE, o.emphasis];
  const pick = <T extends number | string>(on: T, off: T): T | ExpressionSpecification =>
    emphasised ? ["case", emphasised, on, off] : on;

  const categorical = o.kind === "categories";
  const colored = o.kind === "values" || categorical;
  const color = categorical ? classColorExpression(o.classes ?? []) : colorExpression(o.stops, o.domain, o.scale);

  // ---- polygons (real areas): a choropleth of the API value or class; only for `observed_polygon` entities.
  const fill: FillLayerSpecification = {
    id: LAYER_FILL,
    type: "fill",
    source: SOURCE_ID,
    filter: all(IS_POLYGON, MODELLED, validFilter(o)),
    paint: colored
      ? { "fill-color": color, "fill-opacity": pick(0.85, 0.3) }
      : { "fill-color": "#64748b", "fill-opacity": 0.55 },
  };
  // "Sin referencia" (observed, no reference level): a hatch, never a class colour.
  const noReference: FillLayerSpecification = {
    id: LAYER_NOREF,
    type: "fill",
    source: SOURCE_ID,
    filter: all(IS_POLYGON, NO_REFERENCE, ...missingParts(o)),
    paint: { "fill-pattern": HATCH_IMAGE, "fill-opacity": 0.9 },
  };
  // No value / no class for another reason: a pale wash (so it can be hovered and clicked) with a grey outline.
  const fillMissing: FillLayerSpecification = {
    id: LAYER_FILL_MISSING,
    type: "fill",
    source: SOURCE_ID,
    filter: all(IS_POLYGON, HAS_REFERENCE, ...missingParts(o)),
    paint: { "fill-color": "#ffffff", "fill-opacity": 0.55 },
  };
  const lineValid: LineLayerSpecification = {
    id: LINE_VALID,
    type: "line",
    source: SOURCE_ID,
    filter: all(IS_POLYGON, MODELLED, validFilter(o)),
    // Mid-grey, not white: a pale zone («baja», #deebf7) must keep a visible edge against the basemap (A11Y-1).
    paint: { "line-color": "#64748b", "line-width": 0.7, "line-opacity": 0.9 },
  };
  const lineMissing: LineLayerSpecification = {
    id: LINE_MISSING,
    type: "line",
    source: SOURCE_ID,
    filter: all(IS_POLYGON, HAS_REFERENCE, ...missingParts(o)),
    paint: { "line-color": "#4b5563", "line-width": 2, "line-opacity": 1 },
  };
  const lineNoReference: LineLayerSpecification = {
    id: LINE_NOREF,
    type: "line",
    source: SOURCE_ID,
    filter: all(IS_POLYGON, NO_REFERENCE, ...missingParts(o)),
    paint: { "line-color": "#374151", "line-width": 1.6, "line-dasharray": [2, 1.5], "line-opacity": 1 },
  };
  const lineSelected: LineLayerSpecification = {
    id: LINE_SELECTED,
    type: "line",
    source: SOURCE_ID,
    filter: all(IS_POLYGON, ["==", ["get", "entity_id"], o.selectedId ?? ""]),
    paint: { "line-color": "#0f172a", "line-width": 3.5, "line-opacity": 1 },
  };

  const fillUnmodelled: FillLayerSpecification = {
    id: LAYER_UNMODELLED,
    type: "fill",
    source: SOURCE_ID,
    filter: all(IS_POLYGON, QUIET),
    paint: { "fill-color": "#cbd5e1", "fill-opacity": 0.22 },
  };
  const lineUnmodelled: LineLayerSpecification = {
    id: LINE_UNMODELLED,
    type: "line",
    source: SOURCE_ID,
    filter: all(IS_POLYGON, QUIET),
    paint: { "line-color": "#cbd5e1", "line-width": 0.5, "line-opacity": 0.8 },
  };
  const pointUnmodelled: CircleLayerSpecification = {
    id: LAYER_UNMODELLED_POINT,
    type: "circle",
    source: SOURCE_ID,
    filter: all(IS_POINT, QUIET),
    paint: { "circle-color": "#cbd5e1", "circle-opacity": 0.6, "circle-radius": 4, "circle-stroke-width": 0 },
  };

  // ---- points (stations, sampling points). Circle layers also draw polygon vertices, hence the Point guard.
  const valid: CircleLayerSpecification = {
    id: LAYER_VALID,
    type: "circle",
    source: SOURCE_ID,
    filter: all(IS_POINT, MODELLED, validFilter(o)),
    paint: colored
      ? {
          "circle-color": color,
          "circle-radius": zoomScaled(pick(11, 8)),
          "circle-opacity": pick(0.95, 0.35),
          // A dark rim, not a white one: the light end of every palette (ICA «Buena» cyan, viridis yellow) is below
          // 3:1 against the light basemap, so the rim is what makes the point visible (WCAG 1.4.11, docs/qa A11Y-1).
          "circle-stroke-color": "#1f2937",
          "circle-stroke-width": 1,
          "circle-stroke-opacity": pick(0.9, 0.4),
        }
      : {
          "circle-color": "#64748b",
          "circle-radius": zoomScaled(9),
          "circle-opacity": 0.85,
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 1.5,
          "circle-stroke-opacity": 1,
        },
  };
  // null is NOT 0: hollow grey ring, no fill. The "sin dato" reason is in the legend, table and station card.
  const missing: CircleLayerSpecification = {
    id: LAYER_MISSING,
    type: "circle",
    source: SOURCE_ID,
    filter: all(IS_POINT, ...missingParts(o)),
    paint: {
      "circle-color": "#ffffff",
      "circle-opacity": 0,
      "circle-radius": zoomScaled(9),
      "circle-stroke-color": "#4b5563",
      "circle-stroke-width": 2.5,
      "circle-stroke-opacity": 1,
    },
  };
  const selected: CircleLayerSpecification = {
    id: LAYER_SELECTED,
    type: "circle",
    source: SOURCE_ID,
    filter: all(IS_POINT, ["==", ["get", "entity_id"], o.selectedId ?? ""]),
    paint: {
      "circle-color": "#ffffff",
      "circle-opacity": 0,
      "circle-radius": zoomScaled(15),
      "circle-stroke-color": "#0f172a",
      "circle-stroke-width": 3,
      "circle-stroke-opacity": 1,
    },
  };
  // Polygons are drawn under the points; within each group fills come before outlines.
  return [
    fillUnmodelled,
    lineUnmodelled,
    fill,
    noReference,
    fillMissing,
    lineValid,
    lineMissing,
    lineNoReference,
    lineSelected,
    pointUnmodelled,
    valid,
    missing,
    selected,
  ];
}
