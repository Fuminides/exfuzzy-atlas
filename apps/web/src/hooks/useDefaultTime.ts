import { useEffect, useState } from "react";
import { candidateIndexes } from "../lib/defaultTime";
import type { Score } from "./defaultTimeScores";

interface Args {
  /** Regular tasks in Predicción and in Explorar (once its rule is known). */
  enabled: boolean;
  taskId: string;
  /** How good a moment is (0-1), or null when the answer is for another instant; a failure stops the probing. */
  score: Score;
  /** The first candidate scoring this much is taken; otherwise the best one. */
  good: number;
  /** Local hours probed on each candidate day (default: 08:00 only). */
  hours?: readonly number[];
  times: readonly string[];
  zone: string;
  /** Has the user already picked a time? Then the default never overrides it. */
  moved: { current: boolean };
  pick: (index: number) => void;
}

/**
 * A page opens at a representative moment, not at New Year's midnight with half the entities hollow: it probes a few
 * weekday moments and takes the first that scores `good` (or, if none does, the best, the first issue time winning ties).
 * Predicción scores the share of entities with a prediction; Explorar the share where its rule fires. Any failure keeps
 * the first issue time. Returns true while it is probing (nothing is drawn yet).
 */
export function useDefaultTime({ enabled, taskId, score, good, hours, times, zone, moved, pick }: Args): boolean {
  const [done, setDone] = useState(false);
  const active = enabled && times.length > 0 && !done;
  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    (async () => {
      // The first issue time is probed last: it is where the page opens when no weekday morning does any better.
      const probes: { index: number; share: number }[] = [];
      const indexes = candidateIndexes(times, zone, hours);
      for (const index of indexes.includes(0) ? indexes : [...indexes, 0]) {
        try {
          const share = await score(times[index]!, controller.signal);
          if (share === null) continue;
          probes.push({ index, share });
          if (share >= good) break;
        } catch {
          if (controller.signal.aborted) return;
          break;
        }
      }
      if (controller.signal.aborted) return;
      const enough = probes.find((p) => p.share >= good);
      const best = enough ?? [...probes].sort((a, b) => b.share - a.share || a.index - b.index)[0];
      if (best && !moved.current) pick(best.index);
      setDone(true);
    })();
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, taskId, times, zone]);
  return active;
}
