import { useState } from "react";
import { api } from "../api/client";
import type { ModelRules } from "../api/types";
import type { DuelView } from "../components/DuelControls";
import { defaultRuleB, ruleMapQuery, type DuelParams } from "../lib/duel";
import { useAsync } from "./useAsync";

interface Args {
  /** The shared request of the rule map (from `useRulesMode`): rule B differs from rule A only in the rule. */
  mapParams: () => DuelParams;
  mapDeps: readonly unknown[];
  mapReady: boolean;
  ruleId: string | null;
  modelRules: ModelRules["rules"];
}

/** Rule Duel (E4): rule A is the selected rule; B is another rule of the same model, with its own rule map. */
export function useRuleDuel({ mapParams, mapDeps, mapReady, ruleId, modelRules }: Args) {
  const [duel, setDuel] = useState(false);
  const [ruleBState, setRuleB] = useState<string | null>(null);
  const [duelView, setDuelView] = useState<DuelView>("side");
  const ruleB =
    duel && ruleBState !== null && ruleBState !== ruleId && modelRules.some((r) => r.rule_id === ruleBState)
      ? ruleBState
      : duel
        ? defaultRuleB(modelRules, ruleId)
        : null;
  const ruleMapB = useAsync(
    (s) => api.ruleMap(ruleMapQuery(mapParams(), ruleB!), s),
    [...mapDeps, ruleB],
    mapReady && ruleId !== null && ruleB !== null,
  );
  return { duel, setDuel, ruleB, setRuleB, duelView, setDuelView, ruleMapB };
}
