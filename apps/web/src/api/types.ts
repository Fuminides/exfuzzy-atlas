// Re-exports of the types generated from the contract schemas (`npm run gen:types`).
export type { DomainsResponse, DomainInfo, TaskInfo } from "./generated/DomainsResponse";
export type { EntityCollection, EntityFeature } from "./generated/EntityCollection";
export type { Health } from "./generated/Health";
export type { ModelCard, MetricsReport, MetricRow, SplitSpec } from "./generated/ModelCard";
export type {
  ModelRules,
  RuleDefinition,
  LinguisticVariable,
  LinguisticTerm,
  TargetScheme,
  TargetClass,
} from "./generated/ModelRules";
export type {
  RuleMapResponse,
  RuleMapFeature,
  RuleMapProperties,
  RuleMapMetric,
  MissingReason,
} from "./generated/RuleMapResponse";
export type { RuleTrace, RuleTraceEntry, AntecedentTrace, FeatureValue } from "./generated/RuleTrace";
export type { SeriesResponse, SeriesPoint } from "./generated/SeriesResponse";
export type { Attribution1 as AttributionItem } from "./generated/EntityCollection";
export type { PredictionsResponse, PredictionFeature, PredictionProperties } from "./generated/PredictionsResponse";
export type { ObservationsResponse, ObservationFeature, ObservationProperties } from "./generated/ObservationsResponse";
export type {
  RuleTerritoriesResponse,
  TerritoryFeature,
  TerritoryProperties,
  TerritoryRuleStats,
  TerritoryMeasure,
} from "./generated/RuleTerritoriesResponse";
export type { RuleStoriesResponse, RuleStory, StoryCheck, StoryQuery } from "./generated/RuleStoriesResponse";
export type { ScenarioRequest } from "./generated/ScenarioRequest";
export type { ScenarioResponse, ScenarioInput, PredictionChange, RuleDelta } from "./generated/ScenarioResponse";
export type {
  RuleImportanceResponse,
  RuleImportance,
  EntityImportance,
  EntityRuleImportance,
  VariableImportance,
} from "./generated/RuleImportanceResponse";
export type { SummaryResponse, DistributionRow } from "./generated/SummaryResponse";
export type { ModelExplanation, ExplanationText } from "./generated/ModelExplanation";
// contract v0.9: montage tasks (fNIRS)
export type { MontageResponse, MontageChannel, SensorInput } from "./generated/MontageResponse";
export type { FnirsModelCard, SubjectSplit, MetricRow as FnirsMetricRow } from "./generated/FnirsModelCard";
export type { TrialsResponse, TrialRecord } from "./generated/TrialsResponse";
export type { TrialTrace } from "./generated/TrialTrace";
