import type { StaticStore } from "./store";

/**
 * The parity check (spec section 13, phase 5): the golden samples are request/response pairs answered by the real API
 * (`ArtifactStore`); the static builders must give the same body from the exported shards.
 */

export interface GoldenSample {
  kind: string;
  model_id: string;
  /** The arguments of the matching `api.*` call, camelCase as `api/client.ts` takes them; for a scenario, the POST body. */
  request: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  status: number;
  /** The API's body after the redaction of local paths; for an error, `{detail}`. */
  body: unknown;
}

/** Floats agree to this relative/absolute tolerance (the contract's `PARITY_TOLERANCE`); everything else exactly. */
export const TOLERANCE = 1e-9;

/** The differences between two JSON values, as `path: what`; empty when they agree. */
export function differences(expected: unknown, got: unknown, path = "$", out: string[] = []): string[] {
  if (typeof expected === "number" && typeof got === "number") {
    const exact = Object.is(expected, got) || expected === got;
    if (!exact && !(Math.abs(expected - got) <= TOLERANCE * Math.max(1, Math.abs(expected), Math.abs(got)))) out.push(`${path}: ${expected} != ${got}`);
  } else if (Array.isArray(expected) || Array.isArray(got)) {
    if (!Array.isArray(expected) || !Array.isArray(got)) out.push(`${path}: array vs ${typeof got}`);
    else if (expected.length !== got.length) out.push(`${path}: length ${expected.length} != ${got.length}`);
    else expected.forEach((x, i) => differences(x, got[i], `${path}[${i}]`, out));
  } else if (expected !== null && got !== null && typeof expected === "object" && typeof got === "object") {
    const a = expected as Record<string, unknown>;
    const b = got as Record<string, unknown>;
    for (const key of new Set([...Object.keys(a), ...Object.keys(b)])) {
      if (!(key in a)) out.push(`${path}.${key}: not in the API body`);
      else if (!(key in b)) out.push(`${path}.${key}: missing`);
      else differences(a[key], b[key], `${path}.${key}`, out);
    }
  } else if (expected !== got) {
    out.push(`${path}: ${JSON.stringify(expected)} != ${JSON.stringify(got)}`);
  }
  return out;
}

/** The kinds the exporter writes (`GOLDEN_KINDS`, spec section 13), and nothing else. */
export const GOLDEN_KINDS = [
  "predictions", "observations", "ruleMapInstant", "ruleMapWindow", "ruleTerritories", "ruleStories", "ruleTrace", "series", "scenario",
] as const;

/** Replays a sample's request against the store: the call of `api.*` it stands for. */
export function replay(store: StaticStore, sample: GoldenSample): Promise<unknown> {
  const r = sample.request;
  switch (sample.kind) {
    case "predictions":
      return store.predictions(r as never);
    case "observations":
      return store.observations(r as never);
    case "ruleMapInstant":
    case "ruleMapWindow":
      return store.ruleMap(r as never);
    case "ruleTerritories":
      return store.ruleTerritories(r as never);
    case "ruleStories":
      return store.ruleStories(r as never);
    case "ruleTrace":
      return store.ruleTrace(r.entityId, r.modelId, r.at);
    case "series":
      return store.series(r as never);
    case "scenario":
      return store.scenario(r as never);
    default:
      throw new Error(`unknown golden kind ${sample.kind}`);
  }
}

/** Does the store answer this sample as the API did? Returns the differences (empty: parity). */
export async function check(store: StaticStore, sample: GoldenSample): Promise<string[]> {
  try {
    const body = await replay(store, sample);
    return sample.status === 200 ? differences(sample.body, body) : [`status: the API answered ${sample.status}, the store 200`];
  } catch (error) {
    const { status, detail } = error as { status?: number; detail?: string };
    if (status === undefined) throw error;
    const expected = (sample.body as { detail?: unknown } | null)?.detail;
    const out = status === sample.status ? [] : [`status: ${sample.status} != ${status}`];
    if (typeof expected === "string" && expected !== detail) out.push(`detail: ${JSON.stringify(expected)} != ${JSON.stringify(detail)}`);
    return out;
  }
}
