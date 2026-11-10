import { LngLatBounds, Map as MapLibreMap, setWorkerUrl } from "maplibre-gl";
// MapLibre 6 finds its worker next to its own file; once bundled that path is gone, so point at the asset.
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import type { GeoJSONSource, GeoJSONSourceSpecification, MapLayerMouseEvent, StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef, useState } from "react";
import { getLang, tr } from "../i18n";
import {
  buildLayers,
  HATCH_IMAGE,
  LAYER_FILL,
  LAYER_FILL_MISSING,
  LAYER_MISSING,
  LAYER_NOREF,
  LAYER_UNMODELLED,
  LAYER_UNMODELLED_POINT,
  LAYER_VALID,
  SOURCE_ID,
  type LayerOptions,
} from "./mapLayers";
import { positions, toCollection, type StationRow } from "./stations";

setWorkerUrl(workerUrl);

/** Layers that can be hovered and clicked: circles for points, fills for polygons. */
const PICKABLE = [LAYER_VALID, LAYER_MISSING, LAYER_FILL, LAYER_NOREF, LAYER_FILL_MISSING, LAYER_UNMODELLED, LAYER_UNMODELLED_POINT];

/** 8x8 RGBA diagonal hatch (grey on white) for "sin referencia" polygons; no canvas needed. */
function hatchImage(): { width: number; height: number; data: Uint8Array } {
  const size = 8;
  const data = new Uint8Array(size * size * 4);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const on = (x + y) % size < 2;
      data.set(on ? [107, 114, 128, 255] : [255, 255, 255, 255], (y * size + x) * 4);
    }
  }
  return { width: size, height: size, data };
}

const boundsOf = (points: [number, number][]) => points.reduce((b, p) => b.extend(p), new LngLatBounds(points[0]!, points[0]!));

/** Breathing room around the stations: 70 px on a big map, a tenth of the short side on a small one (it must not eat the view). */
const fitPadding = (el: HTMLElement | null): number => {
  const short = el ? Math.min(el.clientWidth, el.clientHeight) : 0;
  return short > 0 ? Math.min(70, Math.max(16, Math.round(short * 0.1))) : 40;
};

export const DEFAULT_BASEMAP = "https://tiles.openfreemap.org/styles/positron";
const STYLE_TIMEOUT_MS = 8000;

/** Plain background: the stations are still drawn when the basemap cannot be loaded. */
export const FALLBACK_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: "background", type: "background", paint: { "background-color": "#f2f2f3" } }],
};

type BasemapStatus = "loading" | "ok" | "fallback";

/**
 * Keeps the camera of several maps together (Rule Duel: A and B side by side). A pan or zoom by the user on one map is
 * copied to the others; each member also learns that the user moved the view, so a later resize does not re-frame it.
 */
export interface MapLink {
  members: Map<MapLibreMap, () => void>;
}
/** Accessible name of the MapLibre canvas: what it is and how to move it with the keyboard (built at render: the language can change). */
export const canvasLabel = (): string => tr("Mapa interactivo: flechas para desplazarlo, + y − para acercar o alejar", "Interactive map: arrow keys to pan, + and − to zoom in or out");
/** The Spanish label, kept for callers that compare against it (A11y.test.tsx); new code uses `canvasLabel()`. */
export const CANVAS_LABEL = canvasLabel();

export const createMapLink = (): MapLink => ({ members: new Map() });

interface Props {
  rows: readonly StationRow[];
  layerOptions: LayerOptions;
  onSelect: (entityId: string) => void;
  basemapUrl?: string;
  /** Text of the hover tooltip for a station (defaults to its name). Hover is a convenience: the table has the same data. */
  tipText?: (row: StationRow) => string;
  /** What the entities are called in the accessible name and the fallback notice ("estaciones", "zonas"...). */
  plural?: string;
  /** Distinguishes this map from its siblings in the accessible name (Rule Duel: "Regla A (R07)"). */
  name?: string;
  /** Maps sharing a link move together. */
  link?: MapLink;
  /** Which entities the view is framed on (default: every one the model covers, not the "sin modelo" ones, which stay drawn but quiet). */
  fitTo?: (row: StationRow) => boolean;
}

/** The positions the camera frames: those of the entities `accept` takes (all of them when it takes none with geometry). */
function framePositions(rows: readonly StationRow[], accept: (row: StationRow) => boolean): [number, number][] {
  const framed = positions(rows.filter(accept));
  return framed.length > 0 ? framed : positions(rows);
}

const modelled = (row: StationRow) => row.missingReason !== "not_modelled";

export function StationMap({ rows, layerOptions, onSelect, basemapUrl = DEFAULT_BASEMAP, tipText, plural: pluralProp, name, link, fitTo = modelled }: Props) {
  const plural = pluralProp ?? tr("estaciones", "stations");
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const readyRef = useRef(false);
  const fittedRef = useRef("");
  const movedRef = useRef(false);
  const latest = useRef({ rows, layerOptions, onSelect, tipText, fitTo });
  latest.current = { rows, layerOptions, onSelect, tipText, fitTo };
  const [basemap, setBasemap] = useState<BasemapStatus>("loading");
  const [tip, setTip] = useState<{ x: number; y: number; text: string } | null>(null);

  // Adds/updates the stations source and the three circle layers from the latest props.
  const sync = () => {
    const map = mapRef.current;
    if (!map || !readyRef.current) return;
    const { rows: r, layerOptions: o } = latest.current;
    if (!map.hasImage(HATCH_IMAGE)) map.addImage(HATCH_IMAGE, hatchImage());
    const data = toCollection(r) as unknown as GeoJSONSourceSpecification["data"];
    const source = map.getSource(SOURCE_ID) as GeoJSONSource | undefined;
    if (source) source.setData(data);
    else map.addSource(SOURCE_ID, { type: "geojson", data });
    for (const spec of buildLayers(o)) {
      if (map.getLayer(spec.id)) {
        map.setFilter(spec.id, spec.filter ?? null);
        for (const [key, value] of Object.entries(spec.paint ?? {})) {
          // paint keys differ per layer type (circle-*, fill-*, line-*); MapLibre's typings only take one union at a time
          map.setPaintProperty(spec.id, key as "circle-color", value);
        }
      } else {
        map.addLayer(spec);
      }
    }
    const key = r.map((row) => row.entityId).join("|");
    if (key !== fittedRef.current) {
      fittedRef.current = key;
      movedRef.current = false;
      fit();
    }
  };

  // Frames all stations. Re-run when the container is resized (e.g. the legend appears), unless the user moved the map.
  const fit = () => {
    const map = mapRef.current;
    const points = framePositions(latest.current.rows, latest.current.fitTo);
    if (!map || points.length === 0) return;
    map.resize(); // the container may have changed size since the last frame MapLibre saw
    map.fitBounds(boundsOf(points), { padding: fitPadding(container.current), maxZoom: 13, duration: 0 });
  };

  useEffect(() => {
    if (!container.current) return;
    // Born already framed on the stations (no flash of another city, no whole country while the basemap loads).
    const first = framePositions(latest.current.rows, latest.current.fitTo);
    const map = new MapLibreMap({
      container: container.current,
      style: basemapUrl,
      ...(first.length > 0
        ? { bounds: boundsOf(first), fitBoundsOptions: { padding: fitPadding(container.current), maxZoom: 13 } }
        : { center: [-3.7, 40.42] as [number, number], zoom: 10.5 }),
      attributionControl: false,
    });
    // MapLibre makes its canvas a second region named "Map" (in English) inside ours, so a screen reader announced two
    // maps (docs/qa A11Y-4). The canvas takes the focus and handles the arrow keys itself: it is an application.
    const canvas = map.getCanvas();
    canvas.setAttribute("role", "application");
    canvas.setAttribute("aria-label", canvasLabel());
    mapRef.current = map;
    let usingFallback = false;
    const switchToFallback = () => {
      if (usingFallback) return;
      usingFallback = true;
      readyRef.current = false;
      setBasemap("fallback");
      map.setStyle(FALLBACK_STYLE, { diff: false });
    };
    const timer = window.setTimeout(() => {
      if (!readyRef.current) switchToFallback();
    }, STYLE_TIMEOUT_MS);
    map.on("style.load", () => {
      readyRef.current = true;
      window.clearTimeout(timer);
      if (!usingFallback) setBasemap("ok");
      sync();
    });
    // A failure before the style is ready (offline, blocked, bad URL) falls back to a plain background.
    map.on("error", () => {
      if (!readyRef.current) switchToFallback();
    });
    // Only gestures by the user (they carry an originalEvent) stop the automatic framing.
    for (const type of ["dragstart", "zoomstart"] as const) {
      map.on(type, (e: { originalEvent?: unknown }) => {
        if (e.originalEvent) movedRef.current = true;
      });
    }
    const members = link?.members;
    members?.set(map, () => (movedRef.current = true));
    if (members) {
      map.on("move", (e: { originalEvent?: unknown }) => {
        if (!e.originalEvent) return; // only the user's gestures are copied (jumpTo on a sibling has none: no echo)
        const camera = { center: map.getCenter(), zoom: map.getZoom(), bearing: map.getBearing(), pitch: map.getPitch() };
        for (const [other, markMoved] of members) {
          if (other === map) continue;
          other.jumpTo(camera);
          markMoved();
        }
      });
    }
    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(() => {
            if (readyRef.current && !movedRef.current) {
              map.resize();
              fit();
            }
          });
    observer?.observe(container.current);
    for (const layer of PICKABLE) {
      map.on("click", layer, (e: MapLayerMouseEvent) => pick(e));
      map.on("mouseenter", layer, () => (map.getCanvas().style.cursor = "pointer"));
      map.on("mouseleave", layer, () => {
        map.getCanvas().style.cursor = "";
        setTip(null);
      });
      map.on("mousemove", layer, (e: MapLayerMouseEvent) => {
        const id = e.features?.[0]?.properties?.entity_id;
        const row = latest.current.rows.find((r) => r.entityId === id);
        if (row) setTip({ x: e.point.x, y: e.point.y, text: latest.current.tipText?.(row) ?? row.name });
      });
    }
    function pick(e: { features?: { properties?: Record<string, unknown> }[] }) {
      const id = e.features?.[0]?.properties?.entity_id;
      if (typeof id === "string") latest.current.onSelect(id);
    }
    return () => {
      members?.delete(map);
      observer?.disconnect();
      window.clearTimeout(timer);
      readyRef.current = false;
      map.remove();
      mapRef.current = null;
    };
    // The map is created once per basemap URL; data and styling flow through `sync`.
  }, [basemapUrl]); // eslint-disable-line react-hooks/exhaustive-deps

  // Re-sync only when what is drawn changes (props are rebuilt on every parent render).
  const drawn = JSON.stringify([
    rows.map((r) => [r.entityId, r.value, r.label ?? null, r.missingReason]),
    layerOptions,
  ]);
  useEffect(sync, [drawn]);
  // The canvas is created once; its accessible name follows the language.
  const lang = getLang();
  useEffect(() => {
    mapRef.current?.getCanvas().setAttribute("aria-label", canvasLabel());
  }, [lang]);

  return (
    <div className="map-wrap">
      <div
        ref={container}
        className="map"
        role="region"
        aria-label={tr(`Mapa de ${plural}${name ? ` · ${name}` : ""}. La tabla de ${plural} permite hacer lo mismo con el teclado.`, `Map of ${plural}${name ? ` · ${name}` : ""}. The table of ${plural} does the same by keyboard.`)}
      />
      {tip && (
        <div className="map-tip" style={{ left: tip.x + 14, top: tip.y + 14 }} role="tooltip">
          {tip.text}
        </div>
      )}
      <p className="map-attribution" data-basemap={basemap}>
        {basemap === "fallback"
          ? tr(`Mapa base no disponible: fondo liso, ${plural} dibujadas igualmente.`, `Basemap unavailable: plain background, ${plural} drawn anyway.`)
          : tr("OpenFreeMap © OpenMapTiles · datos © OpenStreetMap contributors", "OpenFreeMap © OpenMapTiles · data © OpenStreetMap contributors")}
      </p>
    </div>
  );
}
