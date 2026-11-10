import { getLang, trIn, type Lang } from "../i18n";
import { unitLabel } from "./format";

/**
 * Linguistic terms as complete phrases. A model publishes its terms as bare words («alta», «Medio>L», "High"); on screen
 * a term names what it qualifies: «demanda alta», «humedad media», "high demand". The nouns live in one table, keyed by
 * feature id (and by the target, for classes such as NYC's levels), with their Spanish gender. Terms that already say
 * everything (EAQI classes «Buena», named periods «Mediodía», Beaufort names «Brisa ligera») stay as the model publishes
 * them, and a feature the table does not know keeps today's label.
 */

type Gender = "m" | "f";
type Tr = <T>(es: T, en: T) => T;

interface Noun {
  /** The noun in the language asked for: «demanda», "demand". */
  name: string;
  /** Its Spanish gender (the article and the adjectives agree with it). */
  g: Gender;
  /**
   * The subject of a rule sentence, article included, when the published label names something else (NYC's «Nivel hace
   * 1 h (percentil)» is the level of demand, and its classes agree with «demanda») or names it awkwardly («Días desde
   * pleno invierno» for a season). Without it the subject is the published label.
   */
  subject?: string;
  /** Terms with their own complete wording: the phrase, and the verb and value that follow the subject in a sentence. */
  terms?: Record<string, { phrase: string; verb: string; value: string }>;
}

/** Hours behind the issue time of NYC's `rel_lagN` (already counted from the issue time; see `humanizeFeature`). */
const relLag = (feature: string): number | null => {
  const m = /^rel_lag(\d+)$/.exec(feature);
  return m ? Number(m[1]) : null;
};

/** "3 h", «1 semana» (as `lagText` of lib/labels, in the given language). */
const ago = (h: number, tr: Tr): string => {
  if (h >= 168 && h % 168 === 0) return h === 168 ? tr("1 semana", "1 week") : tr(`${h / 168} semanas`, `${h / 168} weeks`);
  return `${h} h`;
};

/** The noun of each feature (and target) of the published models, in one language. */
function nouns(tr: Tr, feature: string): Record<string, Noun> {
  const no2: Noun = { name: tr("nivel de NO₂", "NO₂ level"), g: "m" };
  const demand: Noun = { name: tr("demanda", "demand"), g: "f" };
  const lag = relLag(feature);
  return {
    // Germany (EEA NO₂): the NO₂ inputs are EAQI classes (complete), wind has Beaufort names, time has named bands
    no2,
    no2_last: no2,
    no2_yday_valid: no2,
    temperature: { name: tr("temperatura", "temperature"), g: "f" },
    relative_humidity: { name: tr("humedad", "humidity"), g: "f" },
    wind_speed: { name: tr("viento", "wind"), g: "m" },
    valid_hour_local: { name: tr("hora", "hour"), g: "f" },
    valid_weekday: { name: tr("día", "day"), g: "m" },
    // NYC taxis: the levels baja / normal / alta / muy alta are levels of demand relative to what is usual
    pickups: demand,
    rel_lag: { ...demand, subject: tr(`la demanda hace ${ago(lag ?? 0, tr)}`, `demand ${ago(lag ?? 0, tr)} ago`) },
    rel_mean24h: {
      ...demand,
      subject: tr("la demanda media de las 24 h previas", "mean demand over the previous 24 h"),
      terms: {
        Low: tr({ phrase: "demanda por debajo de lo habitual", verb: "está", value: "por debajo de lo habitual" }, { phrase: "demand below what is usual", verb: "is", value: "below what is usual" }),
        Medium: tr({ phrase: "demanda habitual", verb: "es", value: "la habitual" }, { phrase: "usual demand", verb: "is", value: "as usual" }),
        High: tr({ phrase: "demanda por encima de lo habitual", verb: "está", value: "por encima de lo habitual" }, { phrase: "demand above what is usual", verb: "is", value: "above what is usual" }),
      },
    },
    local_hour: { name: tr("hora", "hour"), g: "f" },
    local_dow: { name: tr("día", "day"), g: "m" },
    // Northumberland & Tyne rivers: L is the common detection limit the table harmonises censored results to
    dissolved_oxygen: { name: tr("oxígeno disuelto", "dissolved oxygen"), g: "m" },
    ammoniacal_nitrogen: { name: tr("nitrógeno amoniacal", "ammoniacal nitrogen"), g: "m" },
    orthophosphate_reactive: { name: tr("ortofosfato", "orthophosphate"), g: "m" },
    water_temperature: { name: tr("temperatura del agua", "water temperature"), g: "f" },
    ph: { name: "pH", g: "m" },
    days_from_midwinter: { name: tr("época del año", "time of year"), g: "f", subject: tr("la época del año", "the time of year") },
  };
}

/** The noun of a feature in `lang`: exact id first, then its family (`no2_lag3h` → NO₂, `rel_lag24` → demand). */
export function nounOf(feature: string, lang: Lang = getLang()): Noun | null {
  const table = nouns(trIn(lang), feature);
  const key = feature in table ? feature : /^no2_lag\d+h?$/.test(feature) ? "no2" : relLag(feature) !== null ? "rel_lag" : null;
  return key ? table[key]! : null;
}

type Level = "verylow" | "low" | "medium" | "normal" | "high" | "veryhigh";

/** A generic level, whichever language or case the model wrote it in ("High", «alta», «medio»). */
const LEVELS: Record<string, Level> = {
  "very low": "verylow", "muy baja": "verylow", "muy bajo": "verylow",
  low: "low", baja: "low", bajo: "low",
  medium: "medium", media: "medium", medio: "medium",
  normal: "normal",
  high: "high", alta: "high", alto: "high",
  "very high": "veryhigh", "muy alta": "veryhigh", "muy alto": "veryhigh",
};
const levelOf = (word: string | null | undefined): Level | null => (word ? (LEVELS[word.trim().toLowerCase()] ?? null) : null);

/** The generic adjective of a level, agreeing with the noun's gender in Spanish. */
const adjective = (level: Level, g: Gender, tr: Tr): string => {
  const [m, f, en] = (
    {
      verylow: ["muy bajo", "muy baja", "very low"],
      low: ["bajo", "baja", "low"],
      medium: ["medio", "media", "medium"],
      normal: ["normal", "normal", "normal"],
      high: ["alto", "alta", "high"],
      veryhigh: ["muy alto", "muy alta", "very high"],
    } as const
  )[level];
  return tr(g === "m" ? m : f, en);
};

/** Water's detection-limit terms: `<=L` (at or below the limit) and `Bajo>L`, `Medio>L`, `Alto>L` (levels above it). */
const ABOVE_LIMIT = /^(Bajo|Medio|Alto)>L$/;
const LIMIT_LEVEL: Record<string, Level> = { Bajo: "low", Medio: "medium", Alto: "high" };

/** What a term says about its variable: as a phrase on its own, and after the subject in a sentence. */
export interface TermWords {
  /** On its own: «demanda alta», "high demand"; a complete term as it is («Buena»). */
  phrase: string;
  /** The verb after the subject: «es», «está», "is". */
  verb: string;
  /** What follows the verb: «alta», «por encima de lo habitual», «Buena». */
  value: string;
  /** Whether the noun table knew the variable (a sentence then names it with an article). */
  known: boolean;
}

/**
 * The words of `term` of `variable` (a feature id, or the target for a class) in `lang`. `label` is today's label of the
 * term (the model's published name in that language, or its class name); it is kept for complete terms and for
 * variables the table does not know.
 */
export function termWords(variable: string, term: string, lang: Lang = getLang(), label?: string | null): TermWords {
  const tr = trIn(lang);
  const shown = label || term;
  const is = tr("es", "is");
  const noun = nounOf(variable, lang);
  if (!noun) return { phrase: shown, verb: is, value: shown, known: false };
  const own = noun.terms?.[term];
  if (own) return { ...own, known: true };
  const name = noun.name;
  if (term === "<=L") {
    const where = tr("en el límite de detección o por debajo", "at or below the detection limit");
    return { phrase: `${name} ${where}`, verb: tr("está", "is"), value: where, known: true };
  }
  const limit = ABOVE_LIMIT.exec(term);
  if (limit) {
    const a = adjective(LIMIT_LEVEL[limit[1]!]!, noun.g, tr);
    const above = tr("sobre el límite de detección", "above the detection limit");
    return { phrase: tr(`${name} ${a}, ${above}`, `${a} ${name}, ${above}`), verb: is, value: `${a}, ${above}`, known: true };
  }
  // A level term: the generic adjective agreed with the noun, unless the model published its own word for it
  // (Water's hour of the sample: «temprana», "early"), which then qualifies the noun as it is.
  const level = levelOf(term) ?? levelOf(label);
  if (level) {
    const word = label && !levelOf(label) ? label : null;
    // English puts a one-word adjective before the noun ("early hour") and a phrase after it
    if (word) return { phrase: tr(`${name} ${word}`, /\s/.test(word) ? `${name} ${word}` : `${word} ${name}`), verb: is, value: word, known: true };
    const a = adjective(level, noun.g, tr);
    return { phrase: tr(`${name} ${a}`, `${a} ${name}`), verb: is, value: a, known: true };
  }
  // a complete term (a class, a named period, a Beaufort name): as published
  return { phrase: shown, verb: is, value: shown, known: true };
}

/** The complete phrase of a term: «demanda alta», "high demand"; «Buena» stays «Buena». */
export const termPhrase = (variable: string, term: string, lang: Lang = getLang(), label?: string | null): string => termWords(variable, term, lang, label).phrase;

/** Units that a label carries in a trailing parenthesis and a sentence can drop ("Humedad relativa hace 1 h (%)"). */
function dropUnit(label: string, unit: string | null | undefined, tr: Tr): string {
  const m = /^(.*?)\s*\(([^()]*)\)$/.exec(label.trim());
  if (!m) return label;
  const inside = m[2]!.trim().toLowerCase();
  const units = new Set(["%", "h", tr("percentil", "percentile"), tr("razón", "ratio")]);
  if (unit) units.add(unitLabel(unit).toLowerCase()).add(unit.toLowerCase());
  return units.has(inside) ? m[1]! : label;
}

/** «Humedad relativa» → «humedad relativa»; a symbol or acronym keeps its case («NO₂», «pH»). */
const lowerFirst = (s: string): string => (/^\p{Lu}\p{Ll}/u.test(s) ? s.charAt(0).toLowerCase() + s.slice(1) : s);

/** One condition of a rule as a sentence: «la **humedad relativa hace 1 h** es *alta*». */
export interface ConditionWords {
  /** «el», «la», or "" (English; a variable the table does not know). */
  article: string;
  subject: string;
  verb: string;
  /** «al menos», «como mucho» (an ordinal condition, contract v0.8): between the verb and the value; absent for «es alta». */
  qualifier?: string;
  value: string;
}

/**
 * A condition in words, so the variable is named once and the term agrees with it: «la demanda hace 1 h es alta», «el
 * nitrógeno amoniacal de la muestra está en el límite de detección o por debajo», "relative humidity 1 h ago is high".
 * `label` is the variable's published label and `termLabel` today's label of the term. A variable the table does not
 * know reads as before: «<label> es <term>».
 */
export function conditionWords(variable: string, term: string, label: string, termLabel: string | null | undefined, unit?: string | null, lang: Lang = getLang()): ConditionWords {
  const tr = trIn(lang);
  const w = termWords(variable, term, lang, termLabel);
  const noun = nounOf(variable, lang);
  if (!w.known || !noun) return { article: "", subject: label, verb: w.verb, value: w.value };
  if (noun.subject) {
    const art = /^(el|la|los|las|the) /.exec(noun.subject);
    return { article: art ? art[1]! : "", subject: art ? noun.subject.slice(art[0].length) : noun.subject, verb: w.verb, value: w.value };
  }
  return { article: tr(noun.g === "m" ? "el" : "la", ""), subject: lowerFirst(dropUnit(label, unit, tr)), verb: w.verb, value: w.value };
}

/** The condition as plain text: «la humedad relativa hace 1 h es alta». */
export const conditionText = (c: ConditionWords): string => `${c.article ? `${c.article} ` : ""}${c.subject} ${c.verb} ${c.qualifier ? `${c.qualifier} ` : ""}${c.value}`;
