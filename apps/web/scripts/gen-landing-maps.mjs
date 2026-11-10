// Draws the three small territory maps of the landing page (src/assets/landing/{air,water,mobility}.svg) from the
// entities.geojson each published model ships: the German stations (points), the river sampling points (points) and
// the NYC taxi zones (polygons). Nothing else is drawn: no basemap, no tiles, no outline that is not in the data, so
// the pictures need no tile attribution and carry no made-up geometry. The files are committed; rerun with
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

/** One path of round dots: a zero-length segment with a round cap is a circle, at a fraction of <circle>'s bytes. */
function dots(file, title, features, diameter) {
  const coords = features.map((f) => f.geometry.coordinates);
  const project = projector(coords);
  const d = coords.map((c) => project(c)).map(([x, y]) => `M${num(x)} ${num(y)}h0`).join("");
  write(file, svg(title, `<path d="${d}" fill="none" stroke="${INK}" stroke-width="${diameter}" stroke-linecap="round" opacity=".85"/>`), features.length);
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

dots("air.svg", "Stations in Germany", entities("de_no2_h1"), 3.4);
dots("water.svg", "River sampling points in Northumberland and Tyne", entities("uk_water_do"), 4.2);
zones("mobility.svg", "Taxi zones of New York", entities("nyc_pickups_h1"));
