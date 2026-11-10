import { createContext, useContext } from "react";
import { getLang, localized, tr } from "../i18n";
import type { LinguisticVariable, RuleDefinition, TargetScheme } from "../api/types";
import { sig3, unitLabel } from "./format";
import { strongestText } from "./mixture";
import { conditionText, conditionWords, termPhrase, type ConditionWords } from "./termPhrases";

/**
 * Names of the model's inputs for people. The model publishes `variables[].label` (v0.5) and `label_en` (v0.6); when
 * they are missing the web falls back to a readable name made from the feature, so an internal identifier (`no2_lag3h`)
 * is never on screen.
 */

const words_ = (): Record<string, string> => ({
  no2: "NO₂", o3: "O₃", so2: "SO₂", co: "CO", pm10: "PM10", pm25: tr("PM2,5", "PM2.5"), ph: "pH", nh4: "NH₄",
  dow: tr("día de la semana", "day of the week"),
});

const known = (): Record<string, string> => ({
  no2_last: tr("NO₂ hace 1 h (último dato)", "NO₂ 1 h ago (latest value)"),
  wind_speed: tr("Velocidad del viento", "Wind speed"),
  temperature: tr("Temperatura", "Temperature"),
  relative_humidity: tr("Humedad relativa", "Relative humidity"),
  valid_hour_local: tr("Hora de validez (local)", "Hour of the valid time (local)"),
  valid_weekday: tr("Día de la semana de validez", "Weekday of the valid time"),
  local_hour: tr("Hora local", "Local hour"),
  local_dow: tr("Día de la semana", "Weekday"),
  rel_mean24h: tr("Demanda relativa media de las últimas 24 h", "Mean relative demand over the last 24 h"),
  ammoniacal_nitrogen: tr("Nitrógeno amoniacal", "Ammoniacal nitrogen"),
  orthophosphate_reactive: tr("Ortofosfato reactivo", "Reactive orthophosphate"),
  water_temperature: tr("Temperatura del agua", "Water temperature"),
  days_from_midwinter: tr("Días desde pleno invierno", "Days from midwinter"),
  ph: "pH",
});

/** "3 h", "1 semana" ("1 week"): a lag in hours as a person would say it (whole weeks only above a week). */
export function lagText(hours: number): string {
  if (hours >= 168 && hours % 168 === 0) return hours === 168 ? tr("1 semana", "1 week") : tr(`${hours / 168} semanas`, `${hours / 168} weeks`);
  return `${hours} h`;
}

const words = (name: string): string => {
  const dict = words_();
  const parts = name.split("_").filter(Boolean).map((w) => dict[w] ?? w);
  const text = parts.join(" ");
  return text.charAt(0).toUpperCase() + text.slice(1);
};

/** Readable name of a feature identifier (fallback of `variables[].label`). */
export function humanizeFeature(feature: string): string {
  const name = known()[feature];
  if (name) return name;
  // `x_lag3h` counts hours behind the last available hour, which is itself 1 h before the issue time: the real age is N + 1 h
  // (the labels the backend publishes say "hace 4 h"). `rel_lag24` (no "h") is already counted from the issue time.
  const lag = /^(.+?)_lag(\d+)(h?)$/.exec(feature);
  if (lag) {
    const [, base, n, h] = lag;
    const hours = Number(n) + (h ? 1 : 0);
    if (base === "rel") return tr(`Demanda relativa hace ${lagText(hours)}`, `Relative demand ${lagText(hours)} ago`);
    return tr(`${words(base!)} hace ${lagText(hours)}`, `${words(base!)} ${lagText(hours)} ago`);
  }
  const last = /^(.+)_last$/.exec(feature);
  if (last) return tr(`${words(last[1]!)} hace 1 h (último dato)`, `${words(last[1]!)} 1 h ago (latest value)`);
  return words(feature);
}

type Described = Pick<LinguisticVariable, "feature" | "label" | "label_en" | "unit">;

/** Name of every input as shown to people: the published label in the interface language, else the humanised feature. */
export function labelerFor(variables: readonly Described[]): (feature: string) => string {
  // an hour of the day is not measured in hours: "Hora local de la muestra (h)" reads "Hora local de la muestra"
  const tidy = (label: string, unit: string | null | undefined) => (unit === "h" || unit === "hour" ? label.replace(/\s*\(h\)$/, "") : label);
  const byFeature = new Map(variables.map((v) => [v.feature, v] as const));
  return (feature) => {
    const v = byFeature.get(feature);
    const label = localized(v?.label, v?.label_en);
    return label ? tidy(label, v?.unit) : humanizeFeature(feature);
  };
}

/** What an input is and when it is known, in the interface language (`description` / `description_en`). */
export const describeVariable = (v: Pick<LinguisticVariable, "description" | "description_en">): string | null => localized(v.description, v.description_en) ?? null;

/** Units that are not a measuring unit but the kind of the number (hour of day, weekday...): no unit is shown. */
const NOT_A_UNIT = new Set(["h", "hour", "day", "weekday_index", "ratio", "percentile", "pH"]);

/** Unit to print next to an input; "" when the unit only says what kind of number it is. */
export function displayUnit(unit: string | null | undefined): string {
  if (!unit) return "";
  if (unit === "percentile") return tr("percentil", "percentile");
  return NOT_A_UNIT.has(unit) ? "" : unitLabel(unit);
}

/**
 * The label with its unit, once: "NO₂ hace 3 h (µg/m³)". A unit the label already names is not repeated, and a label
 * with its own parenthesis takes the unit inside it ("NO₂ hace 1 h (último dato, µg/m³)"), never in a second one.
 */
export function labelWithUnit(label: string, unit: string | null | undefined): string {
  const u = displayUnit(unit);
  if (!u || label.toLowerCase().includes(u.toLowerCase())) return label;
  const own = /^(.*)\(([^()]*)\)$/.exec(label.trim());
  return own ? `${own[1]!.trimEnd()} (${own[2]}, ${u})` : `${label} (${u})`;
}

const termWords = (): Record<string, string> => ({ low: tr("baja", "low"), medium: tr("media", "medium"), high: tr("alta", "high") });

/** A linguistic term as shown: the three generic terms in the interface language, every other term is the model's own word. */
export const termLabel = (term: string): string => termWords()[term.toLowerCase()] ?? term;

type Classy = { label: string; display_label?: string | null; display_label_en?: string | null };

/**
 * A class as shown: its name in the interface language when the model publishes one (EAQI "Good" -> "Buena"; ICA
 * "Buena" -> "Good" in English, v0.6), else its label.
 */
export const className = (c: Classy): string => localized(c.display_label || c.label, c.display_label_en);

type Named = Pick<TargetScheme, "name"> & Partial<Pick<TargetScheme, "name_en">>;
type ShortNamed = Partial<Pick<TargetScheme, "short_name" | "short_name_en">>;

/** The scheme's name in the interface language (`name` / `name_en`, v0.6). */
export const schemeName = (scheme: Named): string => localized(scheme.name, scheme.name_en);

/** The scheme's compact name in the interface language ("ICA", "Nivel relativo" / "Relative level"); null when none. */
export const schemeShort = (scheme: ShortNamed): string | null => localized(scheme.short_name, scheme.short_name_en) ?? null;

/**
 * "nombres oficiales EAQI: Good, Fair, ..." when the shown names are not the scheme's own; null when they are the same,
 * and null for a scheme that is not an official index (NYC's relative level is Atlas's own: it has no official names).
 */
export function officialNames(scheme: (ShortNamed & { kind?: TargetScheme["kind"]; classes: readonly Classy[] }) | null | undefined): string | null {
  if (!scheme || (scheme.kind != null && scheme.kind !== "official_index")) return null;
  if (!scheme.classes.some((c) => className(c) !== c.label)) return null;
  const list = scheme.classes.map((c) => c.label).join(", ");
  const name = schemeShort(scheme);
  const short = name ? ` ${name}` : "";
  return tr(`nombres oficiales${short}: ${list}`, `official${short} names: ${list}`);
}

/** What the model's terms and classes are called on screen: published names first, then the readable fallback. */
export interface Names {
  /** Today's label of a term: the model's word («alta», «Buena»). */
  term: (feature: string, term: string) => string;
  /** The term as a complete phrase («humedad alta», "high demand"; «Buena» as it is): see lib/termPhrases.ts. */
  phrase: (feature: string, term: string) => string;
  /** A condition in words, the variable named once and the term agreeing with it («la demanda hace 1 h es alta»). */
  cond: (feature: string, term: string, label: string) => ConditionWords;
  cls: (label: string) => string;
  /** A class as a complete phrase: NYC's «alta» is «demanda alta»; EAQI's «Buena» stays. */
  clsPhrase: (label: string) => string;
}

export const DEFAULT_NAMES: Names = {
  term: (_f, term) => termLabel(term),
  phrase: (f, term) => termPhrase(f, term, getLang(), termLabel(term)),
  cond: (f, term, label) => conditionWords(f, term, label, termLabel(term), null, getLang()),
  cls: (label) => label,
  clsPhrase: (label) => label,
};

/**
 * Names of a model's terms and classes. `target` is the task's target (`pickups`), whose noun completes the class
 * names of a relative level («demanda alta»).
 */
export function namesFor(
  variables: readonly (Pick<LinguisticVariable, "feature" | "terms"> & Partial<Pick<LinguisticVariable, "unit">>)[],
  scheme: { classes: readonly Classy[] } | null | undefined,
  target?: string | null,
): Names {
  const terms = new Map(variables.flatMap((v) => v.terms.map((t) => [`${v.feature}|${t.name}`, t] as const)));
  const units = new Map(variables.map((v) => [v.feature, v.unit ?? null] as const));
  const classes = new Map((scheme?.classes ?? []).map((c) => [c.label, c] as const));
  // names are picked at call time, so a memoised `Names` follows the interface language
  const cls = (label: string): string | undefined => {
    const c = classes.get(label);
    return c ? className(c) : undefined;
  };
  // the term's own label, else the class name when the term is a class of the scheme (the NO₂ inputs), else the term
  const term = (feature: string, name: string): string => {
    const t = terms.get(`${feature}|${name}`);
    return localized(t?.label, t?.label_en) || cls(name) || termLabel(name);
  };
  return {
    term,
    phrase: (feature, name) => termPhrase(feature, name, getLang(), term(feature, name)),
    cond: (feature, name, label) => conditionWords(feature, name, label, term(feature, name), units.get(feature), getLang()),
    cls: (label) => cls(label) ?? label,
    clsPhrase: (label) => (target ? termPhrase(target, label, getLang(), cls(label) ?? label) : (cls(label) ?? label)),
  };
}

export const NamesContext = createContext<Names>(DEFAULT_NAMES);
export const useNames = (): Names => useContext(NamesContext);

/** The context every component reads input names from; the default needs no model. */
export const LabelContext = createContext<(feature: string) => string>(humanizeFeature);
export const useFeatureLabel = (): ((feature: string) => string) => useContext(LabelContext);

export interface SentencePart {
  feature: string;
  label: string;
  term: string;
  termText: string;
  /** The condition in words (lib/termPhrases.ts): «la» **demanda hace 1 h** «es» *alta*. */
  words: ConditionWords;
  /** Official class colour when the term is a class of the scheme (the NO₂ inputs are classes of the ICA). */
  color: string | null;
  modifier: number | null;
}

/** The text with its first letter in capitals (a condition that opens a line: «La demanda hace 1 h es alta»). */
export const capFirst = (s: string): string => s.charAt(0).toUpperCase() + s.slice(1);

/** One condition as words: «el NO₂ hace 4 h es Buena», «la demanda hace 1 h es alta». */
export const condText = (a: { feature: string; term: string }, label: (feature: string) => string, names: Names = DEFAULT_NAMES): string =>
  conditionText(names.cond(a.feature, a.term, label(a.feature)));

/** The consequent of a rule as plain pieces: a class (with colour), a number with unit, or a fuzzy term. */
export type Outcome =
  | { kind: "class"; key: string; label: string; color: string | null }
  /** v0.7 rule mixture: no conclusion of its own (the consequent plays no part); the class it supports most, if any. */
  | { kind: "mixture"; key: string | null; label: string | null; color: string | null }
  | { kind: "value"; text: string }
  | { kind: "term"; label: string };

export interface RuleSentence {
  parts: SentencePart[];
  outcome: Outcome;
}

const colorOfClass = (scheme: TargetScheme | null | undefined, name: string): string | null => scheme?.classes.find((c) => c.label === name)?.color ?? null;

/** A rule as "Si <variable> es <término> y ... → <resultado>", with no raw identifiers. */
export function ruleSentence(rule: RuleDefinition, label: (feature: string) => string, scheme: TargetScheme | null | undefined, names: Names = DEFAULT_NAMES): RuleSentence {
  const parts = rule.antecedents.map((a) => ({
    feature: a.feature,
    label: label(a.feature),
    term: a.term,
    termText: names.term(a.feature, a.term),
    words: names.cond(a.feature, a.term, label(a.feature)),
    color: colorOfClass(scheme, a.term),
    modifier: a.modifier ?? null,
  }));
  const c = rule.consequent;
  const strongest = rule.strongest_class ?? null;
  const outcome: Outcome =
    rule.class_weights_centred
      ? { kind: "mixture", key: strongest, label: strongest ? names.clsPhrase(strongest) : null, color: strongest ? colorOfClass(scheme, strongest) : null }
      : c.type === "class"
      ? { kind: "class", key: c.term ?? "", label: c.term ? names.clsPhrase(c.term) : tr("sin clase", "no class"), color: colorOfClass(scheme, c.term ?? "") }
      : c.type === "crisp" && c.value !== null && c.value !== undefined
        ? { kind: "value", text: `${sig3(c.value)}${c.unit ? ` ${unitLabel(c.unit)}` : ""}` }
        : { kind: "term", label: c.term ? termLabel(c.term) : tr("sin resultado", "no outcome") };
  return { parts, outcome };
}

/** The sentence as plain text (accessible names, tests). */
export function sentenceText(s: RuleSentence): string {
  const out = s.outcome.kind === "value" ? s.outcome.text : s.outcome.kind === "mixture" ? strongestText(s.outcome.label) : s.outcome.label;
  return tr(`Si ${s.parts.map((p) => conditionText(p.words)).join(" y ")} → ${out}`, `If ${s.parts.map((p) => conditionText(p.words)).join(" and ")} → ${out}`);
}
