import { afterEach, describe, expect, it, vi } from "vitest";
import { seriesWindow } from "./client";
import { series } from "../test/fixtures";

afterEach(() => vi.unstubAllGlobals());

const page = (points: typeof series[number]["points"], next: string | null) =>
  Promise.resolve(new Response(JSON.stringify({ ...series[0]!, points, next_cursor: next }), { status: 200 }));

describe("seriesWindow", () => {
  it("asks for [from, to) and follows next_cursor until it is null", async () => {
    const pts = series[0]!.points;
    const calls: URLSearchParams[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string) => {
        const q = new URL(input, "http://x").searchParams;
        calls.push(q);
        return q.get("cursor") === null ? page(pts.slice(0, 3), pts[3]!.issued_at_utc) : page(pts.slice(3), null);
      }),
    );
    const out = await seriesWindow({ taskId: "t", entityId: "SYN_A", from: "2025-01-14T00:00:00Z", to: "2025-01-20T00:00:00Z" });
    expect(calls).toHaveLength(2);
    expect(calls.every((q) => q.get("from") === "2025-01-14T00:00:00Z" && q.get("to") === "2025-01-20T00:00:00Z")).toBe(true);
    expect(calls[1]!.get("cursor")).toBe(pts[3]!.issued_at_utc);
    expect(out.points).toEqual(pts);
    expect(out.next_cursor).toBeNull();
  });
});
