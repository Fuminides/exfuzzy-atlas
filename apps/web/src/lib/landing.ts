/**
 * When the landing page shows. It shows on the bare URL (a `?lang=` alone included); a URL that already carries app
 * state (`tab`, `domain`, `task`, `territory`, `entity`), `?demo=1` or a hash route goes straight to the app, so deep
 * links and the QA scripts keep working. Once the reader starts the demo, the choice is remembered for the browser
 * session, so a reload does not bounce them back (a convenience: without storage the landing simply shows again).
 */

const KEY = "atlas.demo.started";
const APP_STATE = ["tab", "domain", "task", "territory", "entity"];

/** Whether this URL goes straight to the app. */
export function skipsLanding(search: string, hash: string): boolean {
  if (hash.replace(/^#/, "") !== "") return true;
  const q = new URLSearchParams(search);
  if (q.get("demo") === "1") return true;
  return APP_STATE.some((k) => q.has(k));
}

export function startedThisSession(): boolean {
  try {
    return window.sessionStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

export function rememberStarted(started: boolean): void {
  try {
    if (started) window.sessionStorage.setItem(KEY, "1");
    else window.sessionStorage.removeItem(KEY);
  } catch {
    /* storage blocked: the landing shows again next time */
  }
}

/** The first view of this page load. */
export function opensOnLanding(): boolean {
  if (typeof window === "undefined") return false;
  return !skipsLanding(window.location.search, window.location.hash) && !startedThisSession();
}
