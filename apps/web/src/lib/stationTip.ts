import type { ObservationProperties, TargetScheme, TerritoryProperties } from "../api/types";
import type { StationRow } from "../map/stations";
import { fmt, fmtNum, formatInstant, missingText, neverPredictedText } from "./format";
import { tr } from "../i18n";
import { articles } from "./domainUi";
import type { Mode } from "./mode";
import { tipRule } from "./mixtureViews";
import { measureName, measureThe, type TerritoryFocus } from "./territories";

interface Ctx {
  mode: Mode;
  scheme: TargetScheme | null;
  /** What an entity is called ("estación"). */
  noun: string;
  unit: string;
  zone: string;
  territoriesOn: boolean;
  terrMeasure: string;
  terrFocus: TerritoryFocus;
  ruleId: string | null;
  territoryOf: (id: string) => TerritoryProperties | undefined;
  observationOf: (id: string) => ObservationProperties | null;
  /** Translated class name (the model's `display_label`); the label itself when absent. */
  className?: (label: string) => string;
  /** Mixture of rules (v0.7): the rule named is the one that adds the most, never one that "decided". */
  mixture?: boolean;
}

/** The map's hover text for one entity; it says what the value is in the current mode and why a value is missing. */
export function stationTip(r: StationRow, c: Ctx): string {
  const sampleDate = (iso: string) => formatInstant(iso, c.zone);
  const noData = () => tr(`${r.name}: sin dato${r.missingReason ? ` · ${missingText(r.missingReason)}` : ""}`, `${r.name}: no data${r.missingReason ? ` · ${missingText(r.missingReason)}` : ""}`);
  if (r.missingReason === "not_modelled") return tr(`${r.name}: sin modelo (el modelo no tiene datos para ${articles(c.noun).este} ${c.noun})`, `${r.name}: not modelled (the model has no data for this ${c.noun})`);
  if (c.territoriesOn) {
    const t = c.territoryOf(r.entityId);
    return r.label
      ? tr(`${r.name}: regla dominante ${r.label} según ${measureThe(c.terrMeasure)} (${r.nValid ?? "?"} registros válidos)`, `${r.name}: dominant rule ${r.label} by ${measureName(c.terrMeasure)} (${r.nValid ?? "?"} valid records)`)
      : c.terrFocus === "intensity" && r.value !== null
        ? tr(`${r.name}: ${c.ruleId} · ${measureName(c.terrMeasure)} = ${fmt(r.value)} (${r.nValid ?? "?"} registros válidos)`, `${r.name}: ${c.ruleId} · ${measureName(c.terrMeasure)} = ${fmt(r.value)} (${r.nValid ?? "?"} valid records)`)
        : tr(`${r.name}: sin regla dominante${t ? ` (${t.n_valid} registros válidos)` : ""}`, `${r.name}: no dominant rule${t ? ` (${t.n_valid} valid records)` : ""}`);
  }
  if (c.mode === "data") {
    const o = c.observationOf(r.entityId);
    return r.value !== null
      ? tr(`${r.name}: ${fmtNum(r.value)} ${c.unit} observado${o?.valid_at_utc ? ` el ${formatInstant(o.valid_at_utc, c.zone)}` : ""}`, `${r.name}: ${fmtNum(r.value)} ${c.unit} observed${o?.valid_at_utc ? ` at ${formatInstant(o.valid_at_utc, c.zone)}` : ""}`)
      : noData();
  }
  if (c.mode === "prediction" && r.noPredictions) return `${r.name}: ${neverPredictedText()}`;
  const decided = c.mode === "prediction" && r.decidedBy ? tipRule(c.mixture ?? false, r.decidedBy) : "";
  return c.mode === "prediction" && c.scheme
    ? r.label
      ? `${r.name}: ${c.className?.(r.label) ?? r.label}${decided}`
      : r.noReference
        ? tr(`${r.name}: sin referencia (sin nivel de referencia para esa hora de la semana)`, `${r.name}: no reference (no reference level for that hour of the week)`)
        : tr(`${r.name}: sin predicción${r.missingReason ? ` · ${missingText(r.missingReason)}` : ""}`, `${r.name}: no prediction${r.missingReason ? ` · ${missingText(r.missingReason)}` : ""}`)
    : r.value !== null
    ? `${r.name}: ${c.mode === "prediction" ? `${fmt(r.value)} ${c.unit}${r.sample ? tr(` (muestra del ${sampleDate(r.sample.at)})`, ` (sample of ${sampleDate(r.sample.at)})`) : ""}${decided}` : fmt(r.value)}`
    : noData();
}
