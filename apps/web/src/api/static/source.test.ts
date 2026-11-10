import { gzipSync } from "node:zlib";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../errors";
import { httpSource, memorySource } from "./source";

const body = (bytes: Uint8Array | string, status = 200) => {
  const data = typeof bytes === "string" ? new TextEncoder().encode(bytes) : bytes;
  return { status, ok: status >= 200 && status < 300, arrayBuffer: async () => data.slice().buffer } as unknown as Response;
};
const gz = (value: unknown) => new Uint8Array(gzipSync(JSON.stringify(value)));

describe("httpSource", () => {
  it("decompresses a gzip file, found by its magic bytes", async () => {
    const fetcher = vi.fn(async () => body(gz({ a: [1, 2, null] })));
    expect(await httpSource("/data/x/", { fetch: fetcher }).json("f.json.gz")).toEqual({ a: [1, 2, null] });
    expect(fetcher).toHaveBeenCalledWith("/data/x/f.json.gz");
  });

  it("reads plain JSON when the server already decoded the gzip", async () => {
    const source = httpSource("/d/", { fetch: async () => body(JSON.stringify({ ok: true })) });
    expect(await source.json("f.json.gz")).toEqual({ ok: true });
  });

  it("answers null for a missing file, also when a dev server answers 200 with its HTML page", async () => {
    expect(await httpSource("/d/", { fetch: async () => body("not found", 404) }).json("a")).toBeNull();
    expect(await httpSource("/d/", { fetch: async () => body("<!doctype html><title>app</title>") }).json("a")).toBeNull();
  });

  it("fails with an ApiError that says which file when the server fails or cannot be reached", async () => {
    const failing = httpSource("/d/", { fetch: async () => body("boom", 500) });
    await expect(failing.json("f.json.gz")).rejects.toMatchObject({ name: "ApiError", status: 500, message: expect.stringContaining("f.json.gz") });
    const offline = httpSource("/d/", { fetch: async () => Promise.reject(new TypeError("offline")) });
    await expect(offline.json("g.json.gz")).rejects.toBeInstanceOf(ApiError);
    await expect(httpSource("/d/", { fetch: async () => body("{broken") }).json("h")).rejects.toMatchObject({ status: null });
  });

  it("downloads a file once however many callers ask, and keeps it", async () => {
    const fetcher = vi.fn(async () => body(gz({ n: 1 })));
    const source = httpSource("/d/", { fetch: fetcher });
    const [a, b] = await Promise.all([source.json("f"), source.json("f")]);
    expect(a).toBe(b);
    await source.json("f");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("remembers a missing file for the page view instead of asking again", async () => {
    const fetcher = vi.fn(async () => body("", 404));
    const source = httpSource("/d/", { fetch: fetcher });
    await source.json("nope");
    await source.json("nope");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("drops the least recently used file when the byte budget is spent", async () => {
    const fetcher = vi.fn(async (url: string) => body(gz({ url, pad: "x".repeat(100) })));
    const source = httpSource("/d/", { fetch: fetcher as never, maxBytes: 250 });
    await source.json("a");
    await source.json("b");
    await source.json("a"); // a is now the most recent
    await source.json("c"); // over budget: b goes
    expect(fetcher).toHaveBeenCalledTimes(3);
    await source.json("a");
    expect(fetcher).toHaveBeenCalledTimes(3);
    await source.json("b");
    expect(fetcher).toHaveBeenCalledTimes(4);
  });

  it("lets one caller give up without cancelling the download for the others", async () => {
    const fetcher = vi.fn(async () => body(gz({ n: 1 })));
    const source = httpSource("/d/", { fetch: fetcher });
    const controller = new AbortController();
    const waiting = source.json("f", controller.signal);
    controller.abort();
    await expect(waiting).rejects.toMatchObject({ name: "AbortError" });
    expect(await source.json("f")).toEqual({ n: 1 });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});

describe("memorySource", () => {
  it("is null where there is no file", async () => {
    const source = memorySource({ a: { v: 1 } });
    expect(await source.json("a")).toEqual({ v: 1 });
    expect(await source.json("b")).toBeNull();
  });
});
