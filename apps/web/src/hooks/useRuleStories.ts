import { useState } from "react";
import { api } from "../api/client";
import type { Mode } from "../lib/mode";
import type { TimeWindow } from "../lib/windows";
import { useAsync } from "./useAsync";

/** Rule Stories shown at once. */
const STORIES_LIMIT = 10;

interface Args {
  mode: Mode;
  modelId: string | null;
  window: TimeWindow | null;
  tau: number;
  /** Static export: the single τ its stories are computed at. The stories follow it, not the slider. */
  storiesTau?: number;
}

/** Rule Stories: loaded when the section is opened, for the selected window or the one pinned by a "reproducir". */
export function useRuleStories({ mode, modelId, window, tau: sliderTau, storiesTau }: Args) {
  const tau = storiesTau ?? sliderTau;
  const [storiesOpen, setStoriesOpen] = useState(false);
  const [pinnedStoriesWindow, setPinnedStoriesWindow] = useState<TimeWindow | null>(null);
  const [activeStory, setActiveStory] = useState<string | null>(null);
  // The selected window, or the one the list was last shown for after a "reproducir".
  const storiesWindow = pinnedStoriesWindow ?? window;
  const stories = useAsync(
    (s) => api.ruleStories({ modelId: modelId!, from: storiesWindow!.from, to: storiesWindow!.to, tau, limit: STORIES_LIMIT }, s),
    [modelId, storiesWindow?.from, storiesWindow?.to, tau],
    mode === "rules" && storiesOpen && modelId !== null && storiesWindow !== null,
  );
  const clearStoryPins = () => {
    setPinnedStoriesWindow(null);
    setActiveStory(null);
  };
  return { storiesOpen, setStoriesOpen, storiesWindow, setPinnedStoriesWindow, activeStory, setActiveStory, stories, clearStoryPins };
}
