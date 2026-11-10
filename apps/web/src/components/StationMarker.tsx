import { colorAt, type ColorStop } from "../lib/colorScale";

/**
 * Swatch that mirrors the map marker. A number (including 0) is a filled disc at its place on the
 * scale; null is a hollow grey ring. They must never look alike.
 */
export function StationMarker({
  value,
  domain,
  stops,
  scale = "linear",
}: {
  value: number | null;
  domain: readonly [number, number];
  stops: readonly ColorStop[];
  scale?: "linear" | "sqrt";
}) {
  if (value === null) return <span className="marker marker--missing" aria-hidden="true" />;
  const [lo, hi, v] = scale === "sqrt" ? [Math.sqrt(domain[0]), Math.sqrt(domain[1]), Math.sqrt(Math.max(0, value))] : [domain[0], domain[1], value];
  const t = (v - lo) / (hi - lo || 1);
  return <span className="marker marker--value" style={{ background: colorAt(stops, t) }} aria-hidden="true" />;
}
