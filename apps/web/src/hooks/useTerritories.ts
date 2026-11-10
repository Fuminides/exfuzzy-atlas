import { useState } from "react";
import { api } from "../api/client";
import type { TerritoryMeasure } from "../api/types";
import type { Mode, RulesView } from "../lib/mode";
import type { TerritoryFocus } from "../lib/territories";
import type { TimeWindow } from "../lib/windows";
import { useAsync } from "./useAsync";

interface Args {
  mode: Mode;
  rulesView: RulesView;
  modelId: string | null;
  window: TimeWindow | null;
  tau: number;
  classifier: boolean;
  /** A mixture of rules (v0.7) is a classifier with no winning rule: `winner_share` answers 422. */
  mixture?: boolean;
}

/** Rule Territories (E2): the dominant rule per entity over the window, for one measure, optionally focused on one rule. */
export function useTerritories({ mode, rulesView, modelId, window, tau, classifier, mixture = false }: Args) {
  const [terrMeasureState, setTerrMeasure] = useState<TerritoryMeasure>("mean_activation");
  const [terrFocus, setTerrFocus] = useState<TerritoryFocus>("all");
  // `winner_share` exists only for winning-rule classifiers (not for regressors, nor for a mixture of rules).
  const terrMeasure: TerritoryMeasure = (classifier && !mixture) || terrMeasureState !== "winner_share" ? terrMeasureState : "mean_activation";
  // tau only matters to the frequency.
  const territories = useAsync(
    (s) =>
      api.ruleTerritories(
        { modelId: modelId!, from: window!.from, to: window!.to, measure: terrMeasure, tau: terrMeasure === "activation_frequency" ? tau : undefined },
        s,
      ),
    [modelId, window?.from, window?.to, terrMeasure, terrMeasure === "activation_frequency" ? tau : null],
    mode === "rules" && rulesView === "territories" && modelId !== null && window !== null,
  );
  return { terrMeasure, setTerrMeasure, terrFocus, setTerrFocus, territories };
}
