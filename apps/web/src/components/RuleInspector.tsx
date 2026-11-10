import type { ModelRules, RuleTrace, SeriesPoint, TargetScheme } from "../api/types";
import type { AsyncState } from "../hooks/useAsync";
import type { TimeWindow } from "../lib/windows";
import { PartitionsPanel } from "./PartitionsPanel";
import { RuleDetail } from "./RuleDetail";
import { RuleRail } from "./RuleRail";
import { SamplePicker } from "./SamplePicker";
import { UnmodelledNotice } from "./UnmodelledNotice";
import { WhyHerePanel } from "./WhyHerePanel";
import { weightScale } from "../lib/mixture";

interface Props {
  rules: ModelRules;
  ruleId: string | null;
  onSelectRule: (id: string) => void;
  scheme: TargetScheme | null;
  relativeScheme: boolean;
  /** The variable whose partitions are open. */
  partitionFeature: string | null;
  onPartitionFeature: (feature: string | null) => void;
  noun: string;
  entityId: string | null;
  entityName: string | null;
  unmodelled: boolean;
  trace: AsyncState<RuleTrace>;
  /** Regular tasks: the instant is still being dragged, so the trace in hand is not the one on screen. */
  staleInstant: boolean;
  /** Classifier: the observed concentration at the valid time. */
  observed: { value: number | null; label: string | null } | null;
  /** Irregular tasks: the point's samples in the window and the one traced. */
  irregular: boolean;
  window: TimeWindow | null;
  samples: readonly SeriesPoint[];
  samplesLoading: boolean;
  sample: SeriesPoint | undefined;
  onPickSample: (issuedAt: string) => void;
  unit: string;
}

/** Rules mode, side panel: the rules, the selected one in detail, its partitions and "¿Por qué aquí?" for the selected entity. */
export function RuleInspector(p: Props) {
  const { rules, ruleId, scheme, entityId, entityName, unmodelled, trace, staleInstant, irregular, window, sample } = p;
  const rule = rules.rules.find((r) => r.rule_id === ruleId);
  const variable = p.partitionFeature ? rules.variables.find((v) => v.feature === p.partitionFeature) : undefined;
  return (
    <>
      <RuleRail rules={rules.rules} selectedId={ruleId} onSelect={p.onSelectRule} scheme={scheme} weighting={rules.inference.rule_weighting} />
      {rule && <RuleDetail rule={rule} onVariable={p.onPartitionFeature} scheme={scheme} weighting={rules.inference.rule_weighting} weightScale={weightScale(rules.rules)} />}
      {variable && (
        <PartitionsPanel
          variable={variable}
          ruleTerm={rule?.antecedents.find((a) => a.feature === variable.feature)?.term ?? null}
          ruleId={rule?.rule_id ?? null}
          siblings={[...new Set(rule?.antecedents.map((a) => a.feature) ?? [])]}
          onVariable={p.onPartitionFeature}
          onClose={() => p.onPartitionFeature(null)}
          trace={entityId && trace.status === "ok" && !staleInstant ? trace.data : null}
          stationName={entityName}
        />
      )}
      {irregular && entityId && !unmodelled && window && (
        <SamplePicker
          entityName={entityName!}
          samples={p.samples}
          loading={p.samplesLoading}
          selected={sample?.issued_at_utc ?? null}
          onSelect={p.onPickSample}
          unit={p.unit}
          windowText={`[${window.from.slice(0, 10)}, ${window.to.slice(0, 10)})`}
        />
      )}
      {entityId && unmodelled && <UnmodelledNotice name={entityName!} noun={p.noun} />}
      {!unmodelled && !(irregular && entityId && sample === undefined) && (
        <WhyHerePanel
          entityName={entityName}
          state={entityId ? (staleInstant ? { status: "loading" } : trace) : { status: "idle" }}
          rules={rules}
          selectedRuleId={ruleId}
          onSelectRule={p.onSelectRule}
          onSelectFeature={p.onPartitionFeature}
          scheme={scheme}
          observed={p.observed}
          relativeScheme={p.relativeScheme}
        />
      )}
    </>
  );
}
