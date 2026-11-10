import type { DomainInfo, MissingReason, ModelCard, ModelRules, TargetClass, TargetScheme } from "../api/types";
import { tr } from "../i18n";
import { fmtNum, unitLabel } from "./format";
import { className, schemeName, schemeShort } from "./labels";

/** Colour of a class the scheme does not colour (never invented from the label). */
export const NO_COLOR = "#94a3b8";

type TaskLike = Pick<DomainInfo["tasks"][number], "task_type">;

/** A classification task: `task_type` from /domains, or a classifier inference family (winning rule, v0.7 rule mixture). */
export function isClassifier(task: TaskLike | undefined, rules: Pick<ModelRules, "inference"> | null): boolean {
  return task?.task_type === "classification" || rules?.inference.family === "winning_rule_classifier" || rules?.inference.family === "rule_mixture_classifier";
}

/** The scheme the model publishes (card first, then the rules payload). */
export const schemeOf = (card: Pick<ModelCard, "target_scheme"> | null, rules: Pick<ModelRules, "target_scheme"> | null): TargetScheme | null =>
  card?.target_scheme ?? rules?.target_scheme ?? null;

export const classColor = (scheme: TargetScheme, label: string): string =>
  scheme.classes.find((c) => c.label === label)?.color ?? NO_COLOR;

/** Is the scheme an official index? Read from the contract's `kind` (v0.4), never guessed from the source URL. */
export const isOfficialScheme = (scheme: Pick<TargetScheme, "kind">): boolean => scheme.kind === "official_index";

/** A level relative to what is usual for the entity (NYC percentiles): not an index and not an absolute amount. */
export const isRelativeKind = (scheme: Pick<TargetScheme, "kind">): boolean => scheme.kind === "percentile_reference";

/** Qualifier of the scheme in titles, from `kind`: an official index says so, a relative level says it is not one. */
export const schemeQualifier = (scheme: TargetScheme): string =>
  isOfficialScheme(scheme)
    ? tr("índice oficial", "official index")
    : isRelativeKind(scheme)
      ? tr(`${schemeShort(scheme) ?? "nivel relativo"}: relativo a lo habitual, no es un índice oficial`, `${schemeShort(scheme) ?? "relative level"}: relative to what is usual, not an official index`)
      : schemeName(scheme);

/** The scheme's compact name (`short_name`, e.g. "ICA", or `short_name_en` in English); null when the model does not publish one. */
export const schemeAcronym = (scheme: Pick<TargetScheme, "short_name" | "short_name_en">): string | null => schemeShort(scheme);

/** "categoría ICA prevista de NO₂" (subject without the horizon); a relative level reads "nivel relativo previsto de ...". */
export const classTitle = (scheme: TargetScheme, targetName: string): string =>
  isRelativeKind(scheme)
    ? tr(`${(schemeShort(scheme) ?? "nivel relativo").toLowerCase()} previsto de ${targetName}`, `predicted ${(schemeShort(scheme) ?? "relative level").toLowerCase()} for ${targetName}`)
    : tr(`categoría${schemeAcronym(scheme) ? ` ${schemeAcronym(scheme)}` : ""} prevista de ${targetName}`, `predicted ${schemeAcronym(scheme) ? `${schemeAcronym(scheme)} ` : ""}category for ${targetName}`);

/** Do the scheme's bounds live on the same axis as the observed values? (Not in NYC: its bounds are percentiles of a count.) */
export const scaleInObservedUnits = (scheme: Pick<TargetScheme, "unit">, seriesUnit: string): boolean =>
  unitLabel(scheme.unit) === unitLabel(seriesUnit);

/**
 * "Sin referencia": the target was observed but its zone and hour of the week have no reference level, so no class is
 * published (publish: `prediction_label = null`, `prediction_unavailable`, `observed_label = null`). It is not
 * "normal" and not a prediction that failed; the row keeps its engine firings.
 */
export const isNoReference = (p: {
  observed: number | null;
  observed_label?: string | null;
  predicted_label?: string | null;
  missing_reason?: MissingReason | null;
}): boolean =>
  (p.predicted_label ?? null) === null &&
  p.missing_reason === "prediction_unavailable" &&
  p.observed !== null &&
  (p.observed_label ?? null) === null;

const isPercentile = (scheme: Pick<TargetScheme, "unit">): boolean => /^percentil/i.test(scheme.unit);

/** Unit of a scheme's bounds as a short word: NYC's long percentile description becomes "percentil". */
export const boundsUnit = (scheme: Pick<TargetScheme, "unit">): string =>
  isPercentile(scheme) ? tr("percentil", "percentile") : unitLabel(scheme.unit);

/** Bounds of a class in the scheme's convention (`upper_inclusive` by default: (lower, upper]). */
export function boundsText(c: TargetClass, scheme: TargetScheme): string {
  const unit = boundsUnit(scheme);
  const lo = c.lower === null ? null : fmtNum(c.lower);
  const hi = c.upper === null ? null : fmtNum(c.upper);
  const [loOp, hiOp] = scheme.boundary === "lower_inclusive" ? ["≥", "<"] : [">", "≤"];
  // "percentil ≥ 25 y < 75" reads better than a trailing unit; concentrations keep "> 40 y ≤ 90 µg/m³".
  const [pre, post] = isPercentile(scheme) ? [`${unit} `, ""] : ["", ` ${unit}`];
  if (lo !== null && hi !== null) return tr(`${pre}${loOp} ${lo} y ${hiOp} ${hi}${post}`, `${pre}${loOp} ${lo} and ${hiOp} ${hi}${post}`);
  if (hi !== null) return `${pre}${hiOp} ${hi}${post}`;
  if (lo !== null) return `${pre}${loOp} ${lo}${post}`;
  return tr("sin límites", "no bounds");
}

/** A class that stands for several official categories: the contract lists them in `merged_from` (v0.4). */
export const isMergedClass = (c: TargetClass): boolean => (c.merged_from?.length ?? 0) > 0;

export const mergedNote = (c: TargetClass, scheme: TargetScheme): string =>
  tr(`«${className(c)}» reúne las categorías oficiales ${joinList(c.merged_from ?? [])} (${boundsText(c, scheme)}), que el modelo no distingue.`, `“${className(c)}” groups the official categories ${joinList(c.merged_from ?? [])} (${boundsText(c, scheme)}), which the model doesn't tell apart.`);

const joinList = (items: readonly string[]): string =>
  items.length <= 1 ? (items[0] ?? "") : tr(`${items.slice(0, -1).join(", ")} y ${items[items.length - 1]}`, `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`);

/** Display name of the rule weight: plain Spanish; the weighting the inference declares ("dominance_score") goes in a tooltip. */
export function weightLabel(): string {
  return tr("peso", "weight");
}

/** The technical id of the weighting, for a `title` tooltip (undefined when the inference does not declare one). */
export const weightTitle = (weighting: ModelRules["inference"]["rule_weighting"] | undefined): string | undefined =>
  weighting ? tr(`Peso de la regla (${weighting})`, `Rule weight (${weighting})`) : undefined;
