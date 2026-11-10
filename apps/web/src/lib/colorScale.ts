/** Perceptually uniform sequential scales, sampled at 5 stops (matplotlib viridis / magma). */
export type ColorStop = readonly [position: number, color: string];

/** Rule activation, [0, 1]. */
export const VIRIDIS: readonly ColorStop[] = [
  [0, "#440154"],
  [0.25, "#3b528b"],
  [0.5, "#21918c"],
  [0.75, "#5ec962"],
  [1, "#fde725"],
];

/** Predicted concentration; a different palette on purpose so it is never read as activation. */
export const MAGMA: readonly ColorStop[] = [
  [0, "#000004"],
  [0.25, "#51127c"],
  [0.5, "#b73779"],
  [0.75, "#fc8961"],
  [1, "#fcfdbf"],
];

/** Observed values (Data mode): one blue hue, so a measurement is never read as an activation or a prediction. */
export const BLUES: readonly ColorStop[] = [
  [0, "#deebf7"],
  [0.25, "#9ecae1"],
  [0.5, "#4292c6"],
  [0.75, "#2171b5"],
  [1, "#08306b"],
];

/** Share of hours in the worse classes (Resumen map): one orange hue, so it is never read as an activation, a prediction or a measurement. */
export const ORANGES: readonly ColorStop[] = [
  [0, "#fff5eb"],
  [0.25, "#fdd0a2"],
  [0.5, "#fd8d3c"],
  [0.75, "#d94801"],
  [1, "#7f2704"],
];

/** Share of predictions a rule decides (Patrones, by zone): a violet hue, never the viridis of rule activation. */
export const PURPLES: readonly ColorStop[] = [
  [0, "#f2f0f7"],
  [0.25, "#cbc9e2"],
  [0.5, "#9e9ac8"],
  [0.75, "#756bb1"],
  [1, "#54278f"],
];

const hex = (c: string): [number, number, number] => [
  parseInt(c.slice(1, 3), 16),
  parseInt(c.slice(3, 5), 16),
  parseInt(c.slice(5, 7), 16),
];

/** Colour for display only (swatches); the map itself uses the data-driven expression. */
export function colorAt(stops: readonly ColorStop[], t: number): string {
  const x = Math.min(1, Math.max(0, t));
  for (let i = 1; i < stops.length; i++) {
    const [p1, c1] = stops[i]!;
    const [p0, c0] = stops[i - 1]!;
    if (x <= p1) {
      const f = (x - p0) / (p1 - p0);
      const a = hex(c0);
      const b = hex(c1);
      const mix = a.map((v, k) => Math.round(v + (b[k]! - v) * f));
      return `rgb(${mix[0]}, ${mix[1]}, ${mix[2]})`;
    }
  }
  return stops[stops.length - 1]![1];
}

export const gradientCss = (stops: readonly ColorStop[]): string =>
  `linear-gradient(to right, ${stops.map(([p, c]) => `${c} ${p * 100}%`).join(", ")})`;
