import { useEffect, useState } from "react";
import { api, seriesWindow } from "../api/client";
import type { ModelCard, ModelRules, RuleMapMetric, TaskInfo } from "../api/types";
import { addHours, sameInstant } from "../lib/format";
import { ruleMapQuery, type DuelParams } from "../lib/duel";
import type { Mode, RulesView } from "../lib/mode";
import { useAsync, type AsyncState } from "./useAsync";
import type { useTimeWindow } from "./useTimeWindow";

interface Args {
  mode: Mode;
  modelId: string | null;
  task: TaskInfo | undefined;
  rules: AsyncState<ModelRules>;
  irregular: boolean;
  coverage: ModelCard["coverage"] | null;
  classifier: boolean;
  entityId: string | null;
  unmodelledSelected: boolean;
  time: ReturnType<typeof useTimeWindow>;
  /** The rule to open on (the ranking's first); undefined while it is not known yet. */
  defaultRuleId?: string | null;
}

/**
 * Rules mode, "Regla" view (E1): the selected rule, the measure and its parameters, the rule map, and the selected
 * entity's trace ("¿Por qué aquí?"). The territories, duel and stories sections build on `ruleId`, `tau` and `mapParams`.
 */
export function useRulesMode({ mode, modelId, task, rules, irregular, coverage, classifier, entityId, unmodelledSelected, time, defaultRuleId }: Args) {
  const { fetchTime, window } = time;
  const [ruleId, setRuleId] = useState<string | null>(null);
  const [rulesView, setRulesView] = useState<RulesView>("rule");
  // null = the task's default: irregular tasks (Water) start on a window aggregate, regular ones on an instant.
  const [viewState, setView] = useState<RuleMapMetric | null>(null);
  const [tau, setTau] = useState(0.5);
  const [emphasis, setEmphasis] = useState(0.5);
  // Irregular tasks: the sample picked for the trace.
  const [pickedSample, setPickedSample] = useState<string | null>(null);
  const [partitionFeature, setPartitionFeature] = useState<string | null>(null);
  const view: RuleMapMetric = viewState ?? (irregular ? "mean_activation" : "firing_strength");

  // The opening rule: the one that decides most (`defaultRuleId`, from the ranking), once it is known.
  useEffect(() => {
    if (rules.status === "ok" && ruleId === null && defaultRuleId !== undefined) setRuleId(defaultRuleId ?? rules.data.rules[0]?.rule_id ?? null);
  }, [rules, ruleId, defaultRuleId]);

  // Everything but the rule is shared: both requests of a duel are built from this one set of parameters.
  const mapParams = (): DuelParams =>
    view === "firing_strength"
      ? { modelId: modelId!, metric: view, time: fetchTime! }
      : { modelId: modelId!, metric: view, from: window!.from, to: window!.to, tau: view === "activation_frequency" ? tau : undefined };
  const mapDeps = [modelId, view, view === "firing_strength" ? fetchTime : null, window?.from, window?.to, tau];
  const mapReady = mode === "rules" && rulesView === "rule" && modelId !== null && fetchTime !== null && window !== null;

  const ruleMap = useAsync(
    (s) => api.ruleMap(ruleMapQuery(mapParams(), ruleId!), s),
    [...mapDeps, ruleId],
    mapReady && ruleId !== null,
  );

  // Irregular tasks: a trace exists only at a sample's own issue time, so the point's samples in the window are listed
  // and the latest one is traced unless another is picked.
  const windowSamples = useAsync(
    (s) => seriesWindow({ taskId: task!.task_id, entityId: entityId!, from: window!.from, to: window!.to }, s),
    [task?.task_id, entityId, window?.from, window?.to],
    irregular && mode === "rules" && task !== undefined && entityId !== null && !unmodelledSelected && window !== null,
  );
  const samples = windowSamples.status === "ok" ? windowSamples.data.points : [];
  const sample = irregular ? (samples.find((p) => sameInstant(p.issued_at_utc, pickedSample)) ?? samples[samples.length - 1]) : undefined;
  const traceAt = irregular ? (sample?.issued_at_utc ?? null) : fetchTime;
  const trace = useAsync(
    (s) => api.ruleTrace(entityId!, modelId!, traceAt!, s),
    [modelId, entityId, traceAt],
    mode === "rules" && modelId !== null && entityId !== null && !unmodelledSelected && traceAt !== null,
  );

  // Classifier "¿Por qué aquí?": the observed concentration at the valid time (the series point of this issue time).
  const observedSeries = useAsync(
    (s) => api.series({ taskId: task!.task_id, entityId: entityId!, from: traceAt!, to: addHours(traceAt!, coverage?.step_hours ?? 1) }, s),
    [task?.task_id, entityId, traceAt],
    mode === "rules" && classifier && task !== undefined && entityId !== null && !unmodelledSelected && traceAt !== null,
  );
  const observedPoint = observedSeries.status === "ok" ? observedSeries.data.points.find((p) => sameInstant(p.issued_at_utc, traceAt)) : undefined;

  return {
    ruleId, setRuleId, rulesView, setRulesView, view, setView, tau, setTau, emphasis, setEmphasis,
    setPickedSample, partitionFeature, setPartitionFeature,
    mapParams, mapDeps, mapReady, ruleMap, windowSamples, samples, sample, traceAt, trace, observedPoint,
  };
}
