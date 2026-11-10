import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Ratchet for the ES/EN switch: source lines (not tests, not comments) that still carry Spanish text outside a `tr(...)`
 * call. Each translation PR lowers UNTRANSLATED_MAX to its new count; it can never go up. The heuristic looks for
 * Spanish letters (á é í ó ú ñ ¿ ¡), so a Spanish string without them escapes it: reviews still read the diff.
 */
const UNTRANSLATED_MAX = 2;

const ROOT = join(__dirname, "..");
const SPANISH = /[áéíóúñÁÉÍÓÚÑ¿¡]/;

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "test" || name === "i18n" || name === "generated" ? [] : sources(path);
    return /\.(ts|tsx)$/.test(name) && !/\.test\.(ts|tsx)$/.test(name) ? [path] : [];
  });
}

export function untranslated(): { file: string; line: number; text: string }[] {
  return sources(ROOT).flatMap((file) =>
    readFileSync(file, "utf8")
      .split("\n")
      .flatMap((text, i) => {
        const code = text.trim();
        if (code.startsWith("//") || code.startsWith("*") || code.startsWith("/*") || code.startsWith("{/*")) return [];
        const beforeComment = code.replace(/\s\/\/.*$/, "");
        return SPANISH.test(beforeComment) && !beforeComment.includes("tr(") ? [{ file: relative(ROOT, file), line: i + 1, text: code.slice(0, 120) }] : [];
      }),
  );
}

describe("i18n coverage", () => {
  it(`has no more than ${UNTRANSLATED_MAX} untranslated Spanish source lines`, () => {
    const left = untranslated();
    if (left.length > UNTRANSLATED_MAX) console.log(left.slice(0, 40).map((l) => `${l.file}:${l.line}  ${l.text}`).join("\n"));
    expect(left.length).toBeLessThanOrEqual(UNTRANSLATED_MAX);
  });
});
