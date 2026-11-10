import { createContext, useContext } from "react";

/**
 * Interface language. The current language lives at module level so the pure text helpers of `lib/` (sentences,
 * numbers, dates) can read it without a hook; `App` sets it before rendering and re-renders the whole tree when it
 * changes. Every text keeps its two versions next to its use: `tr("Las reglas", "The rules")`.
 */
export type Lang = "es" | "en";
export const LANGS: readonly Lang[] = ["es", "en"];

let current: Lang = "es";

export const getLang = (): Lang => current;

export function setLang(lang: Lang): void {
  current = lang;
  if (typeof document !== "undefined") document.documentElement.lang = lang;
}

/** The Intl locale of the current language (numbers, dates): comma decimals in Spanish, point in English. */
export const locale = (): string => (current === "en" ? "en-GB" : "es-ES");

/** The text (or node) in the current language. Both versions are written where the text is used. */
export function tr<T>(es: T, en: T): T {
  return current === "en" ? en : es;
}

/** `tr` for a given language instead of the current one (pure helpers that take the language as an argument). */
export const trIn =
  (lang: Lang) =>
  <T>(es: T, en: T): T =>
    lang === "en" ? en : es;

/**
 * Text that comes from the API in the current language: its English version (contract v0.6 `*_en` fields) when the
 * interface is in English and the API sends one, else the Spanish one, which is also the fallback of an older API.
 */
export function localized(es: string, en: string | null | undefined): string;
export function localized(es: string | null | undefined, en: string | null | undefined): string | null | undefined;
export function localized(es: string | null | undefined, en: string | null | undefined): string | null | undefined {
  return current === "en" && en ? en : es;
}

export const LangContext =createContext<{ lang: Lang; setLang: (lang: Lang) => void }>({ lang: "es", setLang: () => {} });
export const useLang = () => useContext(LangContext);

const KEY = "atlas.lang";
const isLang = (v: string | null | undefined): v is Lang => v === "es" || v === "en";

/** The language to start in: `?lang=` first, then the one this browser chose, then the browser's own language. */
export function detectLang(): Lang {
  try {
    const fromUrl = new URLSearchParams(window.location.search).get("lang");
    if (isLang(fromUrl)) return fromUrl;
  } catch {
    /* no URL: keep looking */
  }
  try {
    const stored = window.localStorage.getItem(KEY);
    if (isLang(stored)) return stored;
  } catch {
    /* storage blocked */
  }
  return typeof navigator !== "undefined" && navigator.language?.toLowerCase().startsWith("es") ? "es" : "en";
}

/** Remember the choice in this browser (a convenience: without storage the browser's language decides next time). */
export function rememberLang(lang: Lang): void {
  try {
    window.localStorage.setItem(KEY, lang);
  } catch {
    /* storage blocked */
  }
}
