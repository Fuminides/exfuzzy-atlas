import { locale, tr } from "../i18n";
import type { DistributionRow, SummaryResponse, TargetClass } from "../api/types";
import { dec, formatDate, pct, unitLabel, withUnit } from "./format";
import { className } from "./labels";

/**
 * Reading of `SummaryResponse` (contract v0.5): what the data say, with no model. Everything shown comes from the
 * precomputed rows; this module only picks a row, sums shares of classes and words the result.
 */

export const GROUPS = ["year", "month", "hour", "weekday"] as const;
export type CalendarGroup = (typeof GROUPS)[number];

// Built at call time (not at import): the language can change while the page is open.
const months = (): string[] => tr(["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"], ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]);
const weekdays = (): string[] => tr(["lun", "mar", "mié", "jue", "vie", "sáb", "dom"], ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]);

/** Every key a calendar group can have, so a missing one is shown as a gap and never skipped. Years are open-ended. */
export const GROUP_KEYS: Record<Exclude<CalendarGroup, "year">, string[]> = {
  month: Array.from({ length: 12 }, (_, i) => String(i + 1).padStart(2, "0")),
  hour: Array.from({ length: 24 }, (_, i) => String(i).padStart(2, "0")),
  weekday: Array.from({ length: 7 }, (_, i) => String(i)),
};

export const groupTitle = (group: CalendarGroup): string =>
  ({
    year: tr("Por año", "By year"),
    month: tr("Por mes", "By month"),
    hour: tr("Por hora del día", "By hour of the day"),
    weekday: tr("Por día de la semana", "By day of the week"),
  })[group];

export const keyLabel = (group: CalendarGroup, key: string): string =>
  group === "month" ? (months()[Number(key) - 1] ?? key) : group === "weekday" ? (weekdays()[Number(key)] ?? key) : key;

/** Groups with fewer observations than this are drawn pale and flagged in the table. */
export const LOW_N = 30;

export const isClassified = (s: Pick<SummaryResponse, "classes">): s is { classes: TargetClass[] } => !!s.classes && s.classes.length > 0;

/** First class counted as "worse": the middle one of the scheme (ICA: «Regular»), so the share is not 0 % by construction. */
export const defaultThreshold = (classes: readonly TargetClass[]): number => Math.min(classes.length - 1, Math.floor(classes.length / 2));

/** "o peor" for an official air-quality index, "o más" where the classes are only levels (taxi demand). */
export const orMore = (domain: string): string => (domain === "air" ? tr("o peor", "or worse") : tr("o más", "or more"));

/** "Regular o peor": the class where the count starts, plus what comes after it. */
export function thresholdLabel(classes: readonly TargetClass[], k: number, domain: string): string {
  const c = classes[k] ? className(classes[k]!) : "";
  return k >= classes.length - 1 ? c : `${c} ${orMore(domain)}`;
}

/** Share of the group's observations in classes `k` and above; null when the group has none (no data is not 0 %). */
export function worseShare(row: Pick<DistributionRow, "n" | "shares"> | undefined, k: number): number | null {
  if (!row || row.n === 0 || !row.shares) return null;
  return row.shares.slice(k).reduce((a, b) => a + b, 0);
}

export const median = (row: Pick<DistributionRow, "n" | "quantiles"> | undefined): number | null => (!row || row.n === 0 ? null : (row.quantiles?.p50 ?? null));

export function rowsOf(s: SummaryResponse, group: string): DistributionRow[] {
  return s.groups[group] ?? [];
}

export const totalRow = (s: SummaryResponse): DistributionRow | undefined => s.groups.all?.[0];

export function byKey(rows: readonly DistributionRow[]): Map<string, DistributionRow> {
  return new Map(rows.map((r) => [r.key, r]));
}

/** Entities that have observations in the summary. */
export const stationsWithData = (s: SummaryResponse): DistributionRow[] => rowsOf(s, "entity").filter((r) => r.n > 0);

/** Period of the data as UTC days, like every half-open period of the contract: "1 de enero de 2019 – 31 de diciembre de 2025". */
export function periodText(s: Pick<SummaryResponse, "period_from_utc" | "period_to_utc">): string {
  // the end of the period is exclusive: its last day is the one before
  const last = new Date(new Date(s.period_to_utc).getTime() - 1).toISOString();
  return `${formatDate(s.period_from_utc, "UTC")} – ${formatDate(last, "UTC")}`;
}

/** The segments of a stacked bar: one per class with a share, in the order of the scheme. */
export function segments(classes: readonly TargetClass[], shares: readonly number[]) {
  return classes.map((c, i) => ({ key: c.label, label: className(c), color: c.color ?? "#94a3b8", share: shares[i] ?? 0 }));
}

/** "74 % Buena · 23 % Razonablemente buena · …" (classes with no share left out). */
export const distributionText = (classes: readonly TargetClass[], shares: readonly number[]): string =>
  segments(classes, shares)
    .filter((s) => s.share > 0)
    .map((s) => `${pct(s.share)} ${s.label}`)
    .join(" · ");

/** "mediana 23 µg/m³ (la mitad de los valores entre 14 y 37 µg/m³)". */
export function quantileText(q: Record<string, number> | null | undefined, unit: string, digits = 1): string {
  if (!q || q.p50 === undefined) return tr("sin datos", "no data");
  const u = unitLabel(unit);
  const median = withUnit(q.p50, u, digits);
  if (q.p25 === undefined || q.p75 === undefined) return tr(`mediana ${median}`, `median ${median}`);
  const [lo, hi] = [dec(q.p25, digits), withUnit(q.p75, u, digits)];
  return tr(`mediana ${median} (la mitad de los valores entre ${lo} y ${hi})`, `median ${median} (half of the values between ${lo} and ${hi})`);
}

/** A count with the locale's thousands separator ("1.234.567" in Spanish, "1,234,567" in English). */
export const count = (n: number): string => n.toLocaleString(locale());

/** "NO₂ horario observado" stays as it is; "Oxígeno disuelto" becomes "oxígeno disuelto" in the middle of a sentence. */
export const lcFirst = (text: string): string => (/^\p{Lu}\p{Ll}/u.test(text) ? text.charAt(0).toLowerCase() + text.slice(1) : text);

/** "2019–2025" from the UTC period (the end is exclusive); "2025" when it is one year. */
export function yearsText(s: Pick<SummaryResponse, "period_from_utc" | "period_to_utc">): string {
  const from = new Date(s.period_from_utc).getUTCFullYear();
  const to = new Date(new Date(s.period_to_utc).getTime() - 1).getUTCFullYear();
  return from === to ? String(from) : `${from}–${to}`;
}

/** Share of all the observed hours that fall in one class (the base rate a rule's hit rate is read against); null when unknown. */
export function classShare(s: Pick<SummaryResponse, "classes" | "groups"> | null | undefined, classLabel: string): number | null {
  const i = s?.classes?.findIndex((c) => c.label === classLabel) ?? -1;
  const share = s ? s.groups.all?.[0]?.shares?.[i] : undefined;
  return i < 0 || share === undefined ? null : share;
}
