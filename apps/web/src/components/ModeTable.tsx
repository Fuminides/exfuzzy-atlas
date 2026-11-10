import { tr } from "../i18n";
import type { ModelRules, ObservationProperties, RuleDefinition, TargetScheme, TerritoryProperties } from "../api/types";
import { classColor } from "../lib/classifier";
import { VIRIDIS } from "../lib/colorScale";
import type { DuelEntry } from "../lib/duel";
import { fmt, fmtNum } from "../lib/format";
import type { Mode } from "../lib/mode";
import { colourOrModelOrder } from "../lib/ruleColours";
import { measureName, type TerritoryFocus } from "../lib/territories";
import type { LayerOptions } from "../map/mapLayers";
import type { StationRow } from "../map/stations";
import { DecidedByRule } from "./DecidedBy";
import { ruleColumnHeader } from "../lib/mixtureViews";
import { DuelTable } from "./DuelTable";
import { StationTable } from "./StationTable";

interface Props {
  mode: Mode;
  noun: { one: string; many: string };
  unit: string;
  irregular: boolean;
  scheme: TargetScheme | null;
  rows: readonly StationRow[];
  layerOptions: LayerOptions;
  domainRange: readonly [number, number];
  entityId: string | null;
  onSelect: (entityId: string) => void;
  rules: ModelRules["rules"];
  dataSqrt: boolean;
  sampleDate: (iso: string) => string;
  /** The same instant as a short day (table cells). */
  sampleDay: (iso: string) => string;
  observationOf: (id: string) => ObservationProperties | null;
  territoryOf: (id: string) => TerritoryProperties | undefined;
  territoriesOn: boolean;
  terrFocus: TerritoryFocus;
  terrMeasure: string;
  ruleId: string | null;
  /** The shared rule colours (ranking of Patrones) of the territories table. */
  ruleColours?: ReadonlyMap<string, string> | null;
  /** Rule Duel: when on, the table compares the two rules once both maps have arrived. */
  /** Prediction mode: opens the rule that decided a prediction in Patrones. */
  onOpenRule?: (ruleId: string) => void;
  /** Mixture of rules (v0.7): the rule column names the rule that adds the most, not the one that decided. */
  mixture?: boolean;
  duel: { ready: boolean; entries: readonly DuelEntry[]; ruleA: RuleDefinition; ruleB: RuleDefinition } | null;
}

/** The keyboard-navigable table beside the map: the same entities and selection as the map, in the columns of the mode. */
export function ModeTable(p: Props) {
  const { mode, noun, unit, irregular, scheme, territoriesOn, terrFocus, terrMeasure, ruleId } = p;
  if (p.duel) {
    return p.duel.ready ? (
      <DuelTable entries={p.duel.entries} selectedId={p.entityId} onSelect={p.onSelect} ruleA={p.duel.ruleA} ruleB={p.duel.ruleB} noun={noun} stops={VIRIDIS} />
    ) : (
      <p className="muted" role="status">{tr("Cargando los dos mapas del duelo…", "Loading the duel's two maps…")}</p>
    );
  }
  // Class colours: the rules in Rule Territories, the categories of a classifier otherwise.
  const classColors =
    mode === "rules" && territoriesOn
      ? new Map(p.rules.map((r) => [r.rule_id, colourOrModelOrder(p.ruleColours, p.rules, r.rule_id)]))
      : scheme
        ? new Map(scheme.classes.map((c) => [c.label, classColor(scheme, c.label)]))
        : undefined;
  return (
    <StationTable
      rows={p.rows}
      selectedId={p.entityId}
      onSelect={p.onSelect}
      stops={p.layerOptions.stops}
      domain={p.domainRange}
      scale={mode === "data" && p.dataSqrt ? "sqrt" : "linear"}
      valueHeader={
        mode === "data"
          ? tr(`Observado (${unit})`, `Observed (${unit})`)
          : territoriesOn
            ? terrFocus === "intensity" && ruleId
              ? tr(`Intensidad de ${ruleId} (${measureName(terrMeasure)})`, `Intensity of ${ruleId} (${measureName(terrMeasure)})`)
              : tr("Regla dominante", "Dominant rule")
            : mode === "rules"
              ? tr("Activación (0–1)", "Activation (0–1)")
              : scheme
                ? tr("Categoría prevista", "Predicted category")
                : tr(`Predicción (${unit})`, `Prediction (${unit})`)
      }
      formatValue={mode === "prediction" || mode === "data" ? (v) => `${fmtNum(v)} ${unit}` : undefined}
      classColors={mode === "prediction" ? classColors : territoriesOn && terrFocus !== "intensity" ? classColors : undefined}
      missingWord={territoriesOn ? (terrFocus === "intensity" ? tr("sin dato", "no data") : tr("sin regla dominante", "no dominant rule")) : undefined}
      showNValid={mode === "rules"}
      decided={mode === "prediction" && p.rows.some((r) => r.decidedBy) ? (r) => <DecidedByRule ruleId={r.decidedBy!} onOpenRule={p.onOpenRule} /> : undefined}
      decidedHeader={p.mixture ? ruleColumnHeader(true) : undefined}
      noun={noun}
      extra={
        irregular && mode === "prediction"
          ? {
              header: tr("Muestra (fecha · observado)", "Sample (date · observed)"),
              cell: (r) =>
                r.sample ? (
                  <>
                    {p.sampleDay(r.sample.at)}
                    {r.sample.observed !== null && <> · {fmtNum(r.sample.observed)} {unit}</>}
                  </>
                ) : (
                  "—"
                ),
            }
          : mode === "data"
            ? {
                header: irregular ? tr("Muestra (fecha de validez)", "Sample (valid date)") : tr("Observado el (validez)", "Observed at (valid time)"),
                cell: (r) => {
                  const at = p.observationOf(r.entityId)?.valid_at_utc;
                  return at && r.value !== null ? p.sampleDate(at) : "—";
                },
              }
            : territoriesOn && terrFocus !== "intensity"
              ? {
                  header: tr(`Valor (${measureName(terrMeasure)})`, `Value (${measureName(terrMeasure)})`),
                  cell: (r) => {
                    const v = p.territoryOf(r.entityId)?.dominant_value;
                    return v == null ? "—" : fmt(v);
                  },
                }
              : undefined
      }
    />
  );
}
