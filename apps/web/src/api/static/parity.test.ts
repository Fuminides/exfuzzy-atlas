import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { gunzipSync } from "node:zlib";
import { describe, expect, it } from "vitest";
import { check, differences, GOLDEN_KINDS, type GoldenSample } from "./parity";
import type { Source } from "./source";
import { StaticStore } from "./store";

/**
 * Phase 5: the web builders against the exporter's golden samples.
 *
 *   ATLAS_STATIC_EXPORT=/path/to/data/<export_id> ATLAS_STATIC_GOLDEN=/path/to/golden/<export_id>/index.json.gz \
 *     npx vitest run src/api/static/parity.test.ts --maxWorkers=1
 *
 * Without both variables the sample test is skipped (CI has no export); the comparison itself is tested below.
 */
const exportDir = process.env.ATLAS_STATIC_EXPORT;
const goldenPath = process.env.ATLAS_STATIC_GOLDEN;

/** An export directory on disk as a `Source` (gzip or plain JSON; null where there is no file). */
function dirSource(root: string): Source {
  return {
    async json(path) {
      const file = join(root, path);
      if (!existsSync(file)) return null;
      const bytes = readFileSync(file);
      const text = bytes[0] === 0x1f && bytes[1] === 0x8b ? gunzipSync(bytes).toString("utf8") : bytes.toString("utf8");
      return JSON.parse(text);
    },
  };
}

const readGz = (file: string): unknown => JSON.parse((gunzipSync(readFileSync(file)).toString("utf8")));

/** The samples: `index.json.gz` is `{format, export_id, n, kinds, models: {<model_id>: {file, n}}}`, and each file a list of samples. */
function loadSamples(index: string): GoldenSample[] {
  const { models } = readGz(index) as { models: Record<string, { file: string }> };
  // ATLAS_STATIC_MODEL=<text>: only the models whose id contains it (the NYC and Germany bodies are large: one model at a time)
  const only = process.env.ATLAS_STATIC_MODEL;
  return Object.entries(models).filter(([id]) => !only || id.includes(only)).map(([, m]) => m).flatMap(({ file }) => readGz(join(dirname(index), file)) as GoldenSample[]);
}

describe.skipIf(!exportDir || !goldenPath)("parity with the golden samples", () => {
  const samples: GoldenSample[] = goldenPath ? loadSamples(goldenPath) : [];
  const store = new StaticStore(dirSource(exportDir ?? ""));

  it("has samples, of the kinds the exporter writes", () => {
    expect(samples.length).toBeGreaterThan(0);
    expect(samples.every((s) => (GOLDEN_KINDS as readonly string[]).includes(s.kind))).toBe(true);
  });

  it.each(samples.map((s, i) => [`${i} ${s.kind} ${s.model_id}`, s] as const))("%s", async (_, sample) => {
    expect(await check(store, sample)).toEqual([]);
  });
});

describe("differences", () => {
  it("compares floats to 1e-9 and everything else exactly", () => {
    expect(differences({ a: 1, b: [0.1 + 0.2, "x", null, true] }, { a: 1 + 1e-12, b: [0.3, "x", null, true] })).toEqual([]);
    expect(differences({ a: 1 }, { a: 1.001 })).toEqual(["$.a: 1 != 1.001"]);
    expect(differences({ a: 0 }, { a: null })).toEqual(["$.a: 0 != null"]);
    expect(differences({ a: "x" }, { a: "y" })).toHaveLength(1);
  });

  it("reports missing and extra keys and array lengths", () => {
    expect(differences({ a: 1, b: 2 }, { a: 1, c: 3 })).toEqual(["$.b: missing", "$.c: not in the API body"]);
    expect(differences([1, 2], [1])).toEqual(["$: length 2 != 1"]);
  });
});

describe("check", () => {
  it("takes no alias for a kind", async () => {
    const store = new StaticStore({ json: async () => null });
    await expect(check(store, { kind: "stories", model_id: "m", request: {}, status: 200, body: {} })).rejects.toThrow(/unknown golden kind/);
  });

  it("replays a sample, and compares the status and detail of an error", async () => {
    const files = new Map<string, unknown>();
    const store = new StaticStore({ json: async (path) => files.get(path) ?? null });
    const missing: GoldenSample = { kind: "ruleStories", model_id: "m", request: { modelId: "m", from: "2025-01-01T00:00:00Z", to: "2025-01-02T00:00:00Z", tau: 0.7 }, status: 422, body: { detail: "x" } };
    // the model is unknown to this empty export: 404, not the 422 the API gave
    expect((await check(store, missing)).join()).toContain("status: 422 != 404");
  });
});
