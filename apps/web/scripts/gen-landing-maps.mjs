// Draws the small territory maps of the landing page (src/assets/landing/{air,water,mobility,fnirs}.svg) from the
// entities.geojson each published model ships: the German stations (points), the river sampling points (points) and
// the NYC taxi zones (polygons); and the 36 NIRS channels from configs/fnirs/montage.json (the dataset's positions,
// projected as the contract's head_projection: azimuthal equidistant from the vertex, nose up). Under the dots: the land
// from Natural Earth 1:10m (public domain; src/assets/landing/outlines.json, Germany whole and Great Britain cropped
// around the river points) and, for the scalp, the head the app draws (fnirs/ScalpMap.tsx). No basemap and no tiles,
// so the pictures need no tile attribution. The files are committed; rerun with
//   npm run gen:landing-maps [-- <published dir>]      (default: ../../artifacts/published, read only)
// Colours are DESIGN.md's (Ink #17191c, Mist #f2f2f3); an <img> cannot read the page's CSS variables.
import { mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const published = process.argv[2] ?? join(here, "..", "..", "..", "artifacts", "published");
const outDir = join(here, "..", "src", "assets", "landing");
mkdirSync(outDir, { recursive: true });

const INK = "#17191c";
const MIST = "#f2f2f3";
const EDGE = "#c9cbd1";
const outlines = JSON.parse(readFileSync(join(here, "..", "src", "assets", "landing", "outlines.json"), "utf8"));
const W = 400;
const H = 300;
const MARGIN = 16;
/** Simplification tolerance of the polygons, in viewBox units (0.6 of a unit is far below a pixel on a card). */
const TOLERANCE = 0.6;

const registry = JSON.parse(readFileSync(join(published, "registry.json"), "utf8"));
const entities = (taskId) => JSON.parse(readFileSync(join(published, registry.tasks[taskId].model_id, "entities.geojson"), "utf8")).features;

const num = (v) => String(Math.round(v * 10) / 10);

/** Equirectangular, scaled by cos(latitude of the middle): enough for a picture of a region of a few degrees. */
function projector(lonLats) {
  const lons = lonLats.map((p) => p[0]);
  const lats = lonLats.map((p) => p[1]);
  const [lon0, lon1, lat0, lat1] = [Math.min(...lons), Math.max(...lons), Math.min(...lats), Math.max(...lats)];
  const k = Math.cos((((lat0 + lat1) / 2) * Math.PI) / 180);
  const w = (lon1 - lon0) * k;
  const h = lat1 - lat0;
  const scale = Math.min((W - 2 * MARGIN) / w, (H - 2 * MARGIN) / h);
  const dx = (W - w * scale) / 2;
  const dy = (H - h * scale) / 2;
  return ([lon, lat]) => [dx + (lon - lon0) * k * scale, dy + (lat1 - lat) * scale];
}

/** Douglas-Peucker on an open polyline. */
function simplify(pts, tol) {
  if (pts.length < 3) return pts;
  const [a, b] = [pts[0], pts[pts.length - 1]];
  const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
  let far = -1;
  let dmax = 0;
  for (let i = 1; i < pts.length - 1; i++) {
    const p = pts[i];
    const d = len === 0 ? Math.hypot(p[0] - a[0], p[1] - a[1]) : Math.abs((b[0] - a[0]) * (a[1] - p[1]) - (a[0] - p[0]) * (b[1] - a[1])) / len;
    if (d > dmax) [dmax, far] = [d, i];
  }
  if (dmax <= tol) return [a, b];
  return [...simplify(pts.slice(0, far + 1), tol).slice(0, -1), ...simplify(pts.slice(far), tol)];
}

function svg(title, body) {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" role="img"><title>${title}</title>${body}</svg>\n`;
}

/** The land under the dots, as one evenodd path. */
const land = (rings, project) =>
  `<path d="${rings.map((r) => `M${r.map((c) => project(c)).map(([x, y]) => `${num(x)} ${num(y)}`).join("L")}Z`).join("")}" fill="${MIST}" fill-rule="evenodd" stroke="${EDGE}" stroke-width="1" stroke-linejoin="round"/>`;

/**
 * One path of round dots (a zero-length segment with a round cap is a circle, at a fraction of <circle>'s bytes) over
 * the land, framed on the outline too when `outline.fit` (Germany whole), else on the dots alone (the rivers).
 */
function dots(file, title, features, diameter, outline) {
  const coords = features.map((f) => f.geometry.coordinates);
  const project = projector(outline.fit ? [...coords, ...outline.rings.flat()] : coords);
  const d = coords.map((c) => project(c)).map(([x, y]) => `M${num(x)} ${num(y)}h0`).join("");
  write(file, svg(title, `${land(outline.rings, project)}<path d="${d}" fill="none" stroke="${INK}" stroke-width="${diameter}" stroke-linecap="round" opacity=".85"/>`), features.length);
}

function zones(file, title, features) {
  const polys = features.flatMap((f) => (f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates));
  const project = projector(polys.flat(2));
  const d = polys
    .flatMap((poly) => poly)
    .map((ring) => {
      const pts = simplify(ring.map((c) => project(c)), TOLERANCE);
      return pts.length < 4 ? "" : `M${pts.slice(0, -1).map(([x, y]) => `${num(x)} ${num(y)}`).join("L")}Z`;
    })
    .join("");
  write(file, svg(title, `<path d="${d}" fill="${MIST}" fill-rule="evenodd" stroke="${INK}" stroke-width=".5" stroke-linejoin="round"/>`), features.length);
}

function write(file, text, n) {
  const path = join(outDir, file);
  writeFileSync(path, text);
  console.log(`${file}: ${n} features, ${statSync(path).size} bytes`);
}

dots("air.svg", "Stations in Germany", entities("de_no2_h1"), 3.4, outlines.air);
dots("water.svg", "River sampling points in Northumberland and Tyne", entities("uk_water_do"), 4.2, outlines.water);
zones("mobility.svg", "Taxi zones of New York", entities("nyc_pickups_h1"));

/** The NIRS channels, as `MontageChannel.xy` (contract v0.9): radius = polar angle / 90°, nose up, right ear right. */
function channels(file, title, montagePath, diameter) {
  const doc = JSON.parse(readFileSync(montagePath, "utf8"));
  const xy = doc.channels.map(({ xyz: [x, y, z] }) => {
    const n = Math.hypot(x, y, z);
    const r = Math.acos(Math.max(-1, Math.min(1, z / n))) / (Math.PI / 2);
    const p = Math.hypot(x, y);
    return p === 0 ? [0, 0] : [(r * x) / p, (r * y) / p];
  });
  // the head of fnirs/ScalpMap.tsx, in head units (the ear plane is the unit circle): skull 1.09, nose to 1.23
  const scale = (H / 2 - MARGIN) / 1.24;
  const X = (x) => num(W / 2 + x * scale);
  const Y = (y) => num(H / 2 - y * scale);
  const head = [
    `<path d="M${X(-1.09)} ${Y(0.18)}C${X(-1.22)} ${Y(0.14)} ${X(-1.22)} ${Y(-0.14)} ${X(-1.09)} ${Y(-0.18)}M${X(1.09)} ${Y(0.18)}C${X(1.22)} ${Y(0.14)} ${X(1.22)} ${Y(-0.14)} ${X(1.09)} ${Y(-0.18)}M${X(-0.13)} ${Y(1.075)}L${X(0)} ${Y(1.23)}L${X(0.13)} ${Y(1.075)}" fill="${MIST}" stroke="${EDGE}" stroke-width="1.5" stroke-linejoin="round"/>`,
    `<circle cx="${X(0)}" cy="${Y(0)}" r="${num(1.09 * scale)}" fill="${MIST}" stroke="${EDGE}" stroke-width="1.5"/>`,
  ].join("");
  const d = xy.map(([x, y]) => `M${X(x)} ${Y(y)}h0`).join("");
  write(file, svg(title, `${head}<path d="${d}" fill="none" stroke="${INK}" stroke-width="${diameter}" stroke-linecap="round" opacity=".85"/>`), xy.length);
}

channels("fnirs.svg", "NIRS channels on the scalp", join(here, "..", "..", "..", "configs", "fnirs", "montage.json"), 8);
