import { LANGS, useLang } from "../i18n";

const NAMES = { es: "Español", en: "English" } as const;

/** ES | EN in the header. Each button is named in its own language, so a reader finds theirs whatever is showing. */
export function LanguageSwitch() {
  const { lang, setLang } = useLang();
  return (
    <div className="segmented lang-switch" role="group" aria-label="Idioma / Language">
      {LANGS.map((l) => (
        <button key={l} type="button" lang={l} aria-pressed={l === lang} aria-label={NAMES[l]} onClick={() => setLang(l)}>
          {l.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
