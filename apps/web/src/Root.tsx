import { useEffect, useRef, useState } from "react";
import { App } from "./App";
import { Landing } from "./components/Landing";
import { getLang, LangContext, rememberLang, setLang, type Lang } from "./i18n";
import { opensOnLanding, rememberStarted } from "./lib/landing";

/** How long the app may take to show its first page title after «Empezar la demo» (the API answers first). */
const FOCUS_WAIT_MS = 15000;

/**
 * The page's first screen: the landing (what you are about to see) on the bare URL, the app after «Empezar la demo» or
 * on a URL that already carries app state (lib/landing.ts). It sits outside `App`, so `render(<App />)` in the tests
 * opens the app as before. «Sobre esta demo» in the app's header comes back here.
 */
export function Root({ initialLang }: { initialLang: Lang }) {
  const [view, setView] = useState<"landing" | "app">(() => (opensOnLanding() ? "landing" : "app"));
  const [lang, setLangState] = useState<Lang>(initialLang);
  // Set when the reader moves between the two screens, so focus follows them (never on the first load).
  const moved = useRef(false);
  if (view === "landing") setLang(lang);
  const chooseLang = (l: Lang) => {
    rememberLang(l);
    setLangState(l);
  };
  const start = () => {
    rememberStarted(true);
    moved.current = true;
    setView("app");
  };
  const about = () => {
    rememberStarted(false);
    moved.current = true;
    setLangState(getLang()); // the language the reader chose in the app
    setView("landing");
  };

  useEffect(() => {
    if (!moved.current) return;
    window.scrollTo?.(0, 0);
    if (view === "landing") {
      document.getElementById("landing-title")?.focus({ preventScroll: true });
      return;
    }
    // The app's main heading (the title of the open tab) appears once its data arrives: focus it then.
    const t0 = Date.now();
    const timer = window.setInterval(() => {
      const h1 = document.querySelector<HTMLElement>("#tabpanel h1");
      if (h1) {
        if (!h1.hasAttribute("tabindex")) h1.setAttribute("tabindex", "-1");
        h1.focus({ preventScroll: true });
      }
      if (h1 || Date.now() - t0 > FOCUS_WAIT_MS) window.clearInterval(timer);
    }, 100);
    return () => window.clearInterval(timer);
  }, [view]);

  if (view === "app") return <App initialLang={lang} onAbout={about} />;
  return (
    <LangContext.Provider value={{ lang, setLang: chooseLang }}>
      <Landing onStart={start} />
    </LangContext.Provider>
  );
}
