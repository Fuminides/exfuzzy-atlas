import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ModelCard } from "../api/types";
import { formatDate, issueTimes, sameInstant } from "../lib/format";
import { coverageFits, windowFor, type TimeWindow, type WindowKind } from "../lib/windows";
import { useDebounced } from "./useDebounced";
import { tr, useLang } from "../i18n";

/** Wait this long after the last slider move before asking the API for a new issue time. */
const SCRUB_DEBOUNCE_MS = 150;
/** The kind to fall back on when the static export has no windows of the one asked for. */
const WINDOW_PREFERENCE: readonly WindowKind[] = ["week", "month", "day", "year", "coverage"];

interface Args {
  coverage: ModelCard["coverage"] | null;
  irregular: boolean;
  zone: string;
  onDate: (label: string) => void;
  /** Static export: the window kinds it holds; a kind it lacks is replaced by the first it has. */
  kinds?: readonly WindowKind[];
}

/**
 * The time axis of every mode: the selected issue time (regular tasks) or anchor (irregular ones), the window kind and
 * the window it gives, a story's custom window, and the debounced time the API is asked for.
 */
export function useTimeWindow({ coverage, irregular, zone, onDate, kinds }: Args) {
  // The date label is text: it is sent again when the language changes.
  const { lang } = useLang();
  const [timeIdx, setTimeIdxRaw] = useState(0);
  // Once the user (or a story) has picked a time, the representative default never replaces it.
  const userMoved = useRef(false);
  const setTimeIdx = useCallback((i: number) => {
    userMoved.current = true;
    setTimeIdxRaw(i);
  }, []);
  const [windowKindState, setWindowKind] = useState<WindowKind | null>(null);
  // Irregular tasks: an instant inside the selected window (default: the end of the coverage).
  const [anchor, setAnchor] = useState<string | null>(null);
  // "Reproducir" a story can pin a window that is not one of the window kinds.
  const [customWindow, setCustomWindow] = useState<TimeWindow | null>(null);

  const wanted: WindowKind = windowKindState ?? (irregular ? "month" : "week");
  const windowKind: WindowKind = kinds && !kinds.includes(wanted) ? (WINDOW_PREFERENCE.find((k) => kinds.includes(k)) ?? wanted) : wanted;
  const times = useMemo(() => (coverage && !irregular ? issueTimes(coverage) : []), [coverage, irregular]);
  const time = irregular ? (coverage ? (anchor ?? coverage.issued_to_utc) : null) : (times[timeIdx] ?? null);

  useEffect(() => {
    if (time && !irregular) onDate(formatDate(time, zone));
  }, [time, irregular, zone, onDate, lang]);

  // Aggregates use a half-open window [from, to) containing the selected time, or the whole coverage if the API allows it.
  const kind: WindowKind = windowKind === "coverage" && coverage && !coverageFits(coverage) ? "week" : windowKind;
  const kindWindow = coverage && time ? windowFor(kind, time, coverage) : null;
  // A story's window (reproducir) replaces the kind window until the user picks a kind or moves in time.
  const window = customWindow ?? kindWindow;
  useEffect(() => {
    if (irregular && window) {
      const from = formatDate(window.from, "UTC");
      const to = formatDate(new Date(Date.parse(window.to) - 1).toISOString(), "UTC");
      onDate(tr(`ventana del ${from} al ${to}`, `window from ${from} to ${to}`));
    }
  }, [irregular, window?.from, window?.to, onDate, lang]); // eslint-disable-line react-hooks/exhaustive-deps

  // Slider drags over thousands of steps: ask the API only once the time has settled, and never show stale data meanwhile.
  const fetchTime = useDebounced(time, SCRUB_DEBOUNCE_MS);
  const settling = fetchTime !== time;
  // The instant is still being dragged: the answer in hand belongs to the previous one and is never drawn.
  const staleInstant = settling && !irregular;
  // An answer is drawn only if it is the one for the instant (or window) on screen: `useAsync` swaps its state one render late.
  const answers = (r: { issued_at_utc?: string | null; time_from_utc?: string | null }): boolean =>
    irregular
      ? r.time_from_utc != null && window !== null && sameInstant(r.time_from_utc, window.from)
      : r.issued_at_utc != null && fetchTime !== null && sameInstant(r.issued_at_utc, fetchTime);

  return { timeIdx, setTimeIdx, userMoved, pickDefault: setTimeIdxRaw, setWindowKind, setAnchor, customWindow, setCustomWindow, times, time, kind, window, fetchTime, settling, staleInstant, answers };
}
