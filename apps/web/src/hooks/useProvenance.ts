import { useEffect } from "react";
import type { AttributionItem, EntityCollection, ModelCard, ModelRules, ObservationsResponse, PredictionsResponse, RuleMapResponse, RuleTerritoriesResponse, RuleTrace, TargetScheme } from "../api/types";
import { officialNames, schemeName } from "../lib/labels";
import type { AsyncState } from "./useAsync";
import { tr, useLang } from "../i18n";

export interface Provenance {
  synthetic: boolean;
  dataVersion: string | null;
  modelId: string;
  geometrySource: string | null;
  exfuzzyVersion: string | null;
  /** Classifier: the target scheme and where it comes from (footer attribution). */
  schemeName: string | null;
  schemeUrl: string | null;
  /** "nombres oficiales EAQI: Good, Fair..." when the class names shown are translated; null otherwise. */
  schemeNames: string | null;
  /** Credit and licence of the data sources, as the API states them (`attribution`, v0.4). */
  attribution: readonly AttributionItem[];
}

const EMPTY_ATTRIBUTION: readonly AttributionItem[] = [];

interface Args {
  modelId: string | null;
  entities: AsyncState<EntityCollection>;
  card: AsyncState<ModelCard>;
  rules: AsyncState<ModelRules>;
  ruleMap: AsyncState<RuleMapResponse>;
  trace: AsyncState<RuleTrace>;
  predictions: AsyncState<PredictionsResponse>;
  observations: AsyncState<ObservationsResponse>;
  territories: AsyncState<RuleTerritoriesResponse>;
  scheme: TargetScheme | null;
  onProvenance: (p: Partial<Provenance>) => void;
}

/** Provenance for the footer / banner: reported to the app whenever a response it depends on changes. */
export function useProvenance({ modelId, entities, card, rules, ruleMap, trace, predictions, observations, territories, scheme, onProvenance }: Args) {
  // Part of the provenance is text (the per-point sources, the official names): it is reported again when the language changes.
  const { lang } = useLang();
  useEffect(() => {
    const p: Partial<Provenance> = { modelId: modelId ?? "" };
    const synthetic =
      (entities.status === "ok" && entities.data.synthetic === true) ||
      (card.status === "ok" && card.data.synthetic === true) ||
      (rules.status === "ok" && rules.data.synthetic === true) ||
      (ruleMap.status === "ok" && ruleMap.data.synthetic === true) ||
      (trace.status === "ok" && trace.data.synthetic === true) ||
      (predictions.status === "ok" && predictions.data.synthetic === true) ||
      (observations.status === "ok" && observations.data.synthetic === true) ||
      (territories.status === "ok" && territories.data.synthetic === true);
    p.synthetic = synthetic;
    // Reset what a previous domain left behind until this one has loaded.
    p.dataVersion = card.status === "ok" ? card.data.data_version : null;
    p.exfuzzyVersion = rules.status === "ok" ? rules.data.inference.exfuzzy_version : null;
    p.schemeName = scheme ? schemeName(scheme) : null;
    p.schemeUrl = scheme?.source_url ?? null;
    p.schemeNames = officialNames(scheme);
    p.attribution = (card.status === "ok" ? card.data.attribution : undefined) ?? (entities.status === "ok" ? entities.data.attribution : undefined) ?? EMPTY_ATTRIBUTION;
    if (entities.status === "ok") {
      // One source for the whole collection (Madrid, NYC); per-point sources (Water) are not one URL to show.
      const sources = new Set(entities.data.features.map((f) => f.properties.geometry_source));
      p.geometrySource = sources.size === 1 ? [...sources][0]! : sources.size > 1 ? tr(`${sources.size} fuentes (una por punto)`, `${sources.size} sources (one per point)`) : null;
    } else p.geometrySource = null;
    onProvenance(p);
  }, [modelId, entities, card, rules, ruleMap, trace, predictions, observations, territories, scheme, onProvenance, lang]);
}
