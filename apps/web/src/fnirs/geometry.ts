/**
 * Geometry of the scalp drawing, from the served channel positions only (`MontageChannel.xy`); nothing is placed by hand.
 */

export type Point = readonly [number, number];

/** The dataset places its 36 channels in six areas (frontal, and four channels each around C3, C4, P3, P4 and POz). */
export const AREAS = 6;

/**
 * Channels grouped by proximity: the single-linkage tree of their `xy` cut into `k` groups (the `k - 1` longest links
 * removed). The groups are drawn as patches behind the channels; they carry no name and no value.
 */
export function proximityGroups<T extends { xy: Point }>(items: readonly T[], k = AREAS): T[][] {
  const n = items.length;
  const parent = items.map((_, i) => i);
  const find = (i: number): number => (parent[i] === i ? i : (parent[i] = find(parent[i]!)));
  const edges: [number, number, number][] = [];
  for (let i = 0; i < n; i++) for (let j = 0; j < i; j++) edges.push([Math.hypot(items[i]!.xy[0] - items[j]!.xy[0], items[i]!.xy[1] - items[j]!.xy[1]), i, j]);
  edges.sort((a, b) => a[0] - b[0]);
  let groups = n;
  for (const [, i, j] of edges) {
    if (groups <= k) break;
    const a = find(i);
    const b = find(j);
    if (a !== b) {
      parent[a] = b;
      groups--;
    }
  }
  const out = new Map<number, T[]>();
  items.forEach((item, i) => out.set(find(i), [...(out.get(find(i)) ?? []), item]));
  return [...out.values()];
}

/** Convex hull (monotone chain), counter-clockwise; fewer than three points come back as they are. */
export function convexHull(points: readonly Point[]): Point[] {
  const pts = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (pts.length < 3) return pts;
  const cross = (o: Point, a: Point, b: Point) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lower: Point[] = [];
  for (const p of pts) {
    while (lower.length >= 2 && cross(lower[lower.length - 2]!, lower[lower.length - 1]!, p) <= 0) lower.pop();
    lower.push(p);
  }
  const upper: Point[] = [];
  for (const p of [...pts].reverse()) {
    while (upper.length >= 2 && cross(upper[upper.length - 2]!, upper[upper.length - 1]!, p) <= 0) upper.pop();
    upper.push(p);
  }
  return [...lower.slice(0, -1), ...upper.slice(0, -1)];
}

/** One wedge of a pie centred at the origin: slice `i` of `n`, from 12 o'clock clockwise (SVG y points down). */
export function wedgePath(i: number, n: number, r: number): string {
  if (n === 1) return `M ${-r} 0 A ${r} ${r} 0 1 0 ${r} 0 A ${r} ${r} 0 1 0 ${-r} 0 Z`;
  const angle = (k: number) => -Math.PI / 2 + (2 * Math.PI * k) / n;
  const [a, b] = [angle(i), angle(i + 1)];
  const large = b - a > Math.PI ? 1 : 0;
  const f = (v: number) => v.toFixed(4);
  return `M 0 0 L ${f(r * Math.cos(a))} ${f(r * Math.sin(a))} A ${r} ${r} 0 ${large} 1 ${f(r * Math.cos(b))} ${f(r * Math.sin(b))} Z`;
}
