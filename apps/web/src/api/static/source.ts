import { tr } from "../../i18n";
import { ApiError } from "../errors";

/**
 * Where the export's files come from. `json` answers the parsed file, or `null` when the file does not exist: a missing
 * file means "no data there" and each builder answers it the way the API does (never as a 0).
 */
export interface Source {
  json(path: string, signal?: AbortSignal): Promise<unknown | null>;
}

const abortError = (): DOMException => new DOMException("Aborted", "AbortError");

/** The consumer stops waiting when its signal fires; the shared download goes on for whoever else needs the file. */
function abortable<T>(promise: Promise<T>, signal?: AbortSignal): Promise<T> {
  if (!signal) return promise;
  if (signal.aborted) return Promise.reject(abortError());
  return new Promise<T>((resolve, reject) => {
    const onAbort = () => reject(abortError());
    signal.addEventListener("abort", onAbort, { once: true });
    promise.then(
      (v) => {
        signal.removeEventListener("abort", onAbort);
        resolve(v);
      },
      (e: unknown) => {
        signal.removeEventListener("abort", onAbort);
        reject(e);
      },
    );
  });
}

async function inflate(bytes: Uint8Array<ArrayBuffer>): Promise<string> {
  const source = new ReadableStream<Uint8Array<ArrayBuffer>>({
    start(controller) {
      controller.enqueue(bytes);
      controller.close();
    },
  });
  return new Response(source.pipeThrough(new DecompressionStream("gzip"))).text();
}

/**
 * The text of a downloaded file. Pages may or may not send `Content-Encoding: gzip` for a `.gz` file: when the browser
 * has already decoded it the bytes are plain JSON, so the gzip magic bytes (1f 8b) decide whether to decompress.
 */
export async function fileText(bytes: Uint8Array<ArrayBuffer>): Promise<string> {
  return bytes.length >= 2 && bytes[0] === 0x1f && bytes[1] === 0x8b ? inflate(bytes) : new TextDecoder().decode(bytes);
}

/** A data file is a JSON object or array. Anything else (a dev server's HTML fallback, say) is not the file. */
const looksLikeJson = (text: string): boolean => {
  const c = text.trimStart()[0];
  return c === "{" || c === "[";
};

interface CacheEntry {
  value: unknown | null;
  cost: number;
}

export interface HttpSourceOptions {
  /** Approximate bytes of decoded JSON kept (least recently used out first). */
  maxBytes?: number;
  fetch?: typeof fetch;
}

/** Files fetched over HTTP, decompressed in the browser, with a byte-bounded LRU of the parsed files. */
export function httpSource(base: string, options: HttpSourceOptions = {}): Source {
  const maxBytes = options.maxBytes ?? 64 * 2 ** 20;
  const cache = new Map<string, CacheEntry>();
  const inflight = new Map<string, Promise<unknown | null>>();
  let total = 0;

  const remember = (path: string, value: unknown | null, cost: number) => {
    cache.set(path, { value, cost });
    total += cost;
    for (const [oldest, entry] of cache) {
      if (total <= maxBytes || oldest === path) break;
      cache.delete(oldest);
      total -= entry.cost;
    }
  };

  async function download(path: string): Promise<unknown | null> {
    const url = base + path;
    let response: Response;
    try {
      response = await (options.fetch ?? fetch)(url);
    } catch {
      throw new ApiError(tr(`No se pudo cargar el fichero de datos (${path})`, `Could not load the data file (${path})`), null);
    }
    if (response.status === 404) return null;
    if (!response.ok) {
      throw new ApiError(tr(`No se pudo cargar el fichero de datos (${path}): ${response.status}`, `Could not load the data file (${path}): ${response.status}`), response.status);
    }
    const text = await fileText(new Uint8Array(await response.arrayBuffer()));
    if (!looksLikeJson(text)) return null;
    try {
      const value: unknown = JSON.parse(text);
      remember(path, value, text.length);
      return value;
    } catch {
      throw new ApiError(tr(`El fichero de datos no es válido (${path})`, `The data file is not valid (${path})`), null);
    }
  }

  return {
    json(path, signal) {
      const hit = cache.get(path);
      if (hit) {
        cache.delete(path); // refresh: most recently used last
        cache.set(path, hit);
        return abortable(Promise.resolve(hit.value), signal);
      }
      let pending = inflight.get(path);
      if (!pending) {
        pending = download(path).then(
          (value) => {
            inflight.delete(path);
            if (value === null) remember(path, null, 0); // a missing file stays missing for this page view
            return value;
          },
          (error: unknown) => {
            inflight.delete(path);
            throw error;
          },
        );
        inflight.set(path, pending);
      }
      return abortable(pending, signal);
    },
  };
}

/** An export held in memory (tests, and the parity test's reader): `path -> parsed file`. */
export function memorySource(files: ReadonlyMap<string, unknown> | Record<string, unknown>): Source {
  const map = files instanceof Map ? files : new Map(Object.entries(files));
  return { json: (path) => Promise.resolve(map.has(path) ? map.get(path) : null) };
}
