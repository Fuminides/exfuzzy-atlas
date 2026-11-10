import type { ObservationsResponse, PredictionsResponse, RuleDefinition, RuleMapResponse, RuleTerritoriesResponse, TargetScheme } from "../api/types";
import type { LayerOptions } from "../map/mapLayers";
import type { StationRow } from "../map/stations";
import { classColor } from "./classifier";
import { BLUES, MAGMA, VIRIDIS } from "./colorScale";
import { withRuleMap } from "./duel";
import type { Mode } from "./mode";
import { markNeverPredicted, observationRows, predictionRows } from "./predictions";
import { colourClasses, colourKey, colourOrModelOrder } from "./ruleColours";
import { DIMMED_RULE, territoryRows, type TerritoryFocus } from "./territories";

export const ACTIVATION_DOMAIN = [0, 1] as const;

interface Input {
  mode: Mode;
  baseRows: StationRow[];
  entityId: string | null;
  rules: readonly RuleDefinition[];
  ruleId: string | null;
  scheme: TargetScheme | null;
  relativeScheme: boolean;
  irregular: boolean;
  /** Only the answers that are for the instant (or window) on screen: null while loading, stale or failed. */
  ruleMapNow: RuleMapResponse | null;
  territoriesNow: RuleTerritoriesResponse | null;
  predictionsNow: PredictionsResponse | null;
  observationsNow: ObservationsResponse | null;
  emphasis: number;
  terrFocus: TerritoryFocus;
  /** The colour scales only grow while browsing (running maxima) or follow the data in hand (`*Max`). */
  scaleMax: number;
  windowMax: number;
  dataMax: number;
  observedMax: number;
  dataSqrt: boolean;
  /** Prediction mode: entities with no prediction at any time of the published period (importance). */
  neverPredicted?: ReadonlySet<string>;
  /** The shared rule colours (ranking of Patrones): Predicción colours each entity by the rule that decided its prediction (`decidedBy`) with them, and Territorios colours the dominant rule. */
  ruleColours?: ReadonlyMap<string, string> | null;
}

/**
 * The rows the table draws, the rows the map draws (the same ones, but labelled with the deciding rule when the map is
 * coloured by rule), how the map colours them, and the value range of the legend and the table.
 */
export function buildMapLayer(i: Input): { rows: StationRow[]; mapRows: StationRow[]; layerOptions: LayerOptions; domainRange: readonly [number, number] } {
  let rows = i.baseRows;
  let layerOptions: LayerOptions = {
    kind: "neutral",
    stops: VIRIDIS,
    domain: ACTIVATION_DOMAIN,
    emphasis: null,
    selectedId: i.entityId,
  };
  let domainRange: readonly [number, number] = ACTIVATION_DOMAIN;

  if (i.mode === "rules" && i.ruleMapNow) {
    rows = withRuleMap(i.baseRows, i.ruleMapNow);
    layerOptions = { ...layerOptions, kind: "values", emphasis: i.emphasis };
  }
  if (i.territoriesNow) {
    rows = territoryRows(i.baseRows, i.territoriesNow, i.terrFocus, i.ruleId);
    layerOptions =
      i.terrFocus === "intensity" && i.ruleId !== null
        ? { ...layerOptions, kind: "values", emphasis: null }
        : {
            kind: "categories",
            stops: VIRIDIS,
            domain: ACTIVATION_DOMAIN,
            emphasis: null,
            selectedId: i.entityId,
            classes: i.rules.map((r) => ({
              label: r.rule_id,
              color: i.terrFocus === "territory" && i.ruleId !== null && r.rule_id !== i.ruleId ? DIMMED_RULE : colourOrModelOrder(i.ruleColours, i.rules, r.rule_id),
            })),
          };
  }
  if (i.mode === "prediction" && i.predictionsNow && i.scheme) {
    // Classifier: colour by the predicted label with the scheme's colours; a numeric prediction is never drawn.
    const scheme = i.scheme;
    rows = predictionRows(i.baseRows, i.predictionsNow, { classifier: true, relativeScheme: i.relativeScheme, irregular: i.irregular });
    layerOptions = {
      kind: "categories",
      stops: MAGMA,
      domain: ACTIVATION_DOMAIN,
      emphasis: null,
      selectedId: i.entityId,
      classes: scheme.classes.map((c) => ({ label: c.label, color: classColor(scheme, c.label) })),
    };
  } else if (i.mode === "prediction" && i.predictionsNow) {
    const top = Math.max(i.scaleMax, i.windowMax);
    const step = top < 30 ? 2 : 10;
    domainRange = [0, Math.ceil(top / step) * step];
    rows = predictionRows(i.baseRows, i.predictionsNow, { classifier: false, relativeScheme: false, irregular: i.irregular });
    layerOptions = { kind: "values", stops: MAGMA, domain: domainRange, emphasis: null, selectedId: i.entityId };
  }
  // Data mode: the observed target as published; a different palette from predictions and activations.
  if (i.mode === "data" && i.observationsNow) {
    const top = Math.max(i.dataMax, i.observedMax);
    const step = top < 30 ? 2 : top < 300 ? 10 : 100;
    domainRange = [0, Math.ceil(top / step) * step];
    rows = observationRows(i.baseRows, i.observationsNow);
    layerOptions = { kind: "values", stops: BLUES, domain: domainRange, emphasis: null, scale: i.dataSqrt ? "sqrt" : "linear", selectedId: i.entityId };
  }
  if (i.mode === "prediction" && i.predictionsNow && i.neverPredicted && !i.relativeScheme && !i.irregular) rows = markNeverPredicted(rows, i.neverPredicted);
  let mapRows = rows;
  if (i.mode === "prediction" && i.predictionsNow && i.ruleColours) {
    const colours = i.ruleColours;
    mapRows = rows.map((r) => ({ ...r, value: null, label: r.decidedBy ? colourKey(colours, r.decidedBy) : null }));
    layerOptions = { kind: "categories", stops: MAGMA, domain: ACTIVATION_DOMAIN, emphasis: null, selectedId: i.entityId, classes: colourClasses(colours) };
  }
  return { rows, mapRows, layerOptions: { ...layerOptions, selectedId: i.entityId }, domainRange };
}
