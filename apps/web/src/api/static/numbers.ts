/** Numeric matches (a what-if grid value, a tau): relative 1e-9 with an absolute floor of 1e-9 (spec section 2, `fmt.close`). */
export const close = (a: number, b: number): boolean => Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(a), Math.abs(b));
