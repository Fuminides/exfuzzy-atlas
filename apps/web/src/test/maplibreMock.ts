
/** Records what the app asks MapLibre to draw; no WebGL involved. */
export interface FakeMap {
  style: unknown;
  sources: Record<string, unknown>;
  layers: Record<string, { id: string; filter?: unknown; paint?: Record<string, unknown> }>;
  handlers: Record<string, ((e: unknown) => void)[]>;
  fitBoundsCalls: number;
  styleSets: unknown[];
  images: Record<string, unknown>;
  jumps?: unknown[];
  /** Points the last `fitBounds` was asked to frame. */
  fitted?: [number, number][];
  /** Attributes the component set on the canvas (role, accessible name). */
  canvasAttributes?: Record<string, string>;
}
export const maps: FakeMap[] = [];
/** When true the fake style loads right away, like a reachable basemap. */
export const control = { autoLoad: true };

export function resetMaps() {
  maps.length = 0;
  control.autoLoad = true;
}

/** Fires an event on the most recent fake map. */
export function emit(type: string, payload?: unknown, layerId?: string) {
  const m = maps[maps.length - 1]!;
  for (const h of m.handlers[layerId ? `${type}:${layerId}` : type] ?? []) h(payload);
}

class FakeMapImpl {
  rec: FakeMap;
  constructor(opts: { style: unknown }) {
    this.rec = { style: opts.style, sources: {}, layers: {}, handlers: {}, fitBoundsCalls: 0, styleSets: [], images: {} };
    maps.push(this.rec);
  }
  on(type: string, a: unknown, b?: unknown) {
    const [layer, fn] = typeof a === "string" ? [a, b] : [undefined, a];
    const key = layer ? `${type}:${layer}` : type;
    (this.rec.handlers[key] ??= []).push(fn as (e: unknown) => void);
    if (type === "style.load" && control.autoLoad) queueMicrotask(() => (fn as () => void)());
  }
  getSource(id: string) {
    const s = this.rec.sources[id];
    return s ? { setData: (d: unknown) => (this.rec.sources[id] = { ...(s as object), data: d }) } : undefined;
  }
  addSource(id: string, spec: unknown) {
    this.rec.sources[id] = spec;
  }
  hasImage(id: string) {
    return id in this.rec.images;
  }
  addImage(id: string, image: unknown) {
    this.rec.images[id] = image;
  }
  getLayer(id: string) {
    return this.rec.layers[id];
  }
  addLayer(spec: { id: string }) {
    this.rec.layers[spec.id] = JSON.parse(JSON.stringify(spec));
  }
  setFilter(id: string, f: unknown) {
    this.rec.layers[id]!.filter = f;
  }
  setPaintProperty(id: string, k: string, v: unknown) {
    (this.rec.layers[id]!.paint ??= {})[k] = v;
  }
  setStyle(s: unknown) {
    this.rec.styleSets.push(s);
    this.rec.layers = {};
    this.rec.sources = {};
    this.rec.images = {};
  }
  resize() {}
  fitBounds(bounds?: FakeBounds) {
    this.rec.fitBoundsCalls++;
    this.rec.fitted = bounds?.points;
  }
  center = { lng: -3.7, lat: 40.42 };
  getCenter() {
    return this.center;
  }
  getZoom() {
    return 10.5;
  }
  getBearing() {
    return 0;
  }
  getPitch() {
    return 0;
  }
  jumpTo(camera: unknown) {
    (this.rec.jumps ??= []).push(camera);
  }
  getCanvas() {
    const attrs = (this.rec.canvasAttributes ??= {});
    return { style: {}, setAttribute: (k: string, v: string) => (attrs[k] = v) };
  }
  remove() {}
}

class FakeBounds {
  points: [number, number][];
  constructor(a?: [number, number]) {
    this.points = a ? [a] : []; // the app passes the same point twice (only the first is kept), then extends
  }
  extend(p: [number, number]) {
    this.points.push(p);
    return this;
  }
}

export const maplibreFactory = () => ({ Map: FakeMapImpl, LngLatBounds: FakeBounds, setWorkerUrl: () => {} });
