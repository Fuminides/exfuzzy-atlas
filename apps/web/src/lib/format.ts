import type { MissingReason } from "../api/types";
import { getLang, locale, tr } from "../i18n";

/** Display format for memberships and activations (the raw value stays in `data-raw`). */
export const fmt = (n: number): string => dec(n, 3);

/**
 * Weights and associations are often tiny (a rule weight of 0.00064): at least 2 significant digits below 0.1, so a
 * non-zero number is never shown as "0.000". From 0.1 up it is `fmt`. The raw value stays in `data-raw`.
 */
export const fmtFine = (n: number): string => {
  const a = Math.abs(n);
  if (a === 0 || a >= 0.1) return fmt(n);
  // two significant digits; the zero a rounding leaves at the end ("0.000080") is dropped, keeping 3 decimals at least
  const sep = getLang() === "en" ? "\\." : ",";
  return dec(n, Math.max(3, 1 - Math.floor(Math.log10(a)))).replace(new RegExp(`(${sep}\\d{3}\\d*?)0+$`), "$1");
};

/** Compact display of a data value or parameter (4 significant digits); the raw number stays in `data-*`. */
/** Intl formatters per locale and options, built once (the language can change while the page is open). */
const formatters = new Map<string, Intl.NumberFormat | Intl.DateTimeFormat>();
function nf(key: string, options: Intl.NumberFormatOptions): Intl.NumberFormat {
  const k = `n|${locale()}|${key}`;
  let f = formatters.get(k) as Intl.NumberFormat | undefined;
  if (!f) formatters.set(k, (f = new Intl.NumberFormat(locale(), options)));
  return f;
}
function df(key: string, options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const k = `d|${locale()}|${key}`;
  let f = formatters.get(k) as Intl.DateTimeFormat | undefined;
  if (!f) formatters.set(k, (f = new Intl.DateTimeFormat(locale(), options)));
  return f;
}

export const fmtNum = (n: number): string => nf("sig4", { maximumSignificantDigits: 4, useGrouping: false }).format(n);

/** Zone shown next to UTC when a task does not say otherwise (the entity's own `timezone` replaces it). */
export const DEFAULT_ZONE = "Europe/Madrid";

const utcFormat = () => df("utc", { timeZone: "UTC", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const formatsFor = (zone: string) => ({
  clock: df(`clock|${zone}`, { timeZone: zone, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }),
  date: df(`date|${zone}`, { timeZone: zone, day: "numeric", month: "long", year: "numeric" }),
});

/** "15/01/2025, 06:00 UTC · 07:00 Europe/Madrid" (the second zone is the entity's: America/New_York for NYC). */
export function formatInstant(iso: string, zone: string = DEFAULT_ZONE): string {
  const d = new Date(iso);
  return `${utcFormat().format(d)} UTC · ${formatsFor(zone).clock.format(d)} ${zone}`;
}

export const formatDate = (iso: string, zone: string = DEFAULT_ZONE): string => formatsFor(zone).date.format(new Date(iso));

/** "4 dic 2025": the day of an instant in the entity's zone, for tables where the long form does not fit. */
export const formatShortDate = (iso: string, zone: string = DEFAULT_ZONE): string =>
  df(`short|${zone}`, { timeZone: zone, day: "numeric", month: "short", year: "numeric" }).format(new Date(iso)).replace(/\./g, "");

/** "2 ene 2025, 08:00": an instant on the wall clock of the entity's zone, for the plain time line. */
export const formatPlain = (iso: string, zone: string = DEFAULT_ZONE): string =>
  df(`plain|${zone}`, { timeZone: zone, day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
    .format(new Date(iso))
    .replace(/\./g, "");

const zoneCity = (zone: string): string | undefined =>
  ({ "Europe/Madrid": "Madrid", "Europe/Berlin": tr("Berlín", "Berlin"), "Europe/London": tr("Londres", "London"), "America/New_York": tr("Nueva York", "New York") })[zone];
/** "hora de Madrid" / "Madrid time": the zone in words (the IANA name stays in the time details). */
export const zoneName = (zone: string): string => {
  if (zone === "UTC") return "UTC";
  const city = zoneCity(zone) ?? (zone.split("/").pop() ?? zone).replace(/_/g, " ");
  return tr(`hora de ${city}`, `${city} time`);
};

/** "1 al 31 dic 2025" for the days [from, to) of a half-open UTC window (one day: "1 dic 2025"). */
export function windowDaysText(from: string, to: string): string {
  const last = new Date(Date.parse(to) - 1).toISOString();
  const a = formatShortDate(from, "UTC");
  const b = formatShortDate(last, "UTC");
  if (a === b) return a;
  const [da, ma, ya] = a.split(" ");
  const [, mb, yb] = b.split(" ");
  return ma === mb && ya === yb ? tr(`${da} al ${b}`, `${da}–${b}`) : tr(`${a} al ${b}`, `${a} – ${b}`);
}

export const addHours = (iso: string, hours: number): string =>
  new Date(new Date(iso).getTime() + hours * 3_600_000).toISOString().replace(".000Z", "Z");

/** Issue times covered by the model: from, from+step, ..., to (inclusive). */
export function issueTimes(coverage: { issued_from_utc: string; issued_to_utc: string; step_hours: number }): string[] {
  const out: string[] = [];
  const end = new Date(coverage.issued_to_utc).getTime();
  const step = coverage.step_hours * 3_600_000;
  for (let t = new Date(coverage.issued_from_utc).getTime(); t <= end; t += step) {
    out.push(new Date(t).toISOString().replace(".000Z", "Z"));
  }
  return out;
}

const unitLabels = (): Record<string, string> => ({
  "ug/m3": "µg/m³",
  trips: tr("viajes", "trips"),
  degC: "°C",
  days: tr("días", "days"),
  hour: "h",
  percentile: tr("percentil", "percentile"),
  ratio: tr("razón", "ratio"),
});
export const unitLabel = (unit: string): string => unitLabels()[unit] ?? unit;

/** Horizon 0 is inference on the same sample (Water), never "+0 h": a forecast is not what is shown. */
export const sameSampleText = (): string => tr("inferencia sobre la misma muestra", "inference on the same sample");
/**
 * @deprecated Fixed at import, so always the Spanish text: use `sameSampleText()`, which follows the language. Kept only
 * while other files still import it; remove once none does.
 */
export const SAME_SAMPLE: string = sameSampleText();
export const horizonText = (hours: number): string => (hours === 0 ? sameSampleText() : tr(`a +${hours} h`, `at +${hours} h`));

const missingLabels = (): Record<MissingReason, string> => ({
  no_observation: tr("sin observación", "no observation"),
  invalid_observation: tr("observación inválida", "invalid observation"),
  censored: tr("censurado", "censored"),
  missing_input: tr("falta una entrada", "missing input"),
  prediction_unavailable: tr("predicción no disponible", "prediction unavailable"),
  not_modelled: tr("sin modelo", "not modelled"),
});

/** Label of a missing reason as the rule-map / entity tables show it; an unknown reason never prints "undefined". */
export const missingText = (reason: string): string => missingLabels()[reason as MissingReason] ?? tr("motivo no documentado", "undocumented reason");

/** An entity with no prediction at any time of the published period (not the per-time "falta una entrada"). */
export const neverPredictedText = (): string => tr("sin predicciones en el periodo publicado", "no predictions in the published period");
/** @deprecated Fixed at import, so always the Spanish text: use `neverPredictedText()`. Kept while other files import it. */
export const NEVER_PREDICTED: string = neverPredictedText();

/** "2024-01-02 00:00 UTC": instants of the split periods, which are half-open [from, to) in UTC. */
export const utcStamp = (iso: string): string => `${iso.slice(0, 16).replace("T", " ")} UTC`;

/** Same instant, whatever the ISO spelling ("Z" vs "+00:00", with or without fractional seconds). */
export const sameInstant = (a: string, b: string | null): boolean => b !== null && Date.parse(a) === Date.parse(b);

/** Narrow no-break space: the thin space Spanish typography puts before "%" and between a number and its unit. */
export const THIN = " ";

/** Number in the interface's locale (comma decimal in Spanish, point in English) with exactly `digits` decimals. */
export function dec(n: number, digits = 1): string {
  return nf(`dec${digits}`, { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(n);
}

/**
 * A share in [0, 1] as a percentage, es-ES: "74 %" from 10 %, "2,6 %" below, "<0,1 %" for a share that is not 0 but
 * would round to it (a rare class is never shown as "0 %"). The % follows a thin space.
 */
export function pct(share: number): string {
  const v = share * 100;
  // Spanish typography puts a thin space before "%"; English does not.
  const sp = getLang() === "en" ? "" : THIN;
  if (v === 0) return `0${sp}%`;
  if (v < 0.05) return `<${dec(0.1, 1)}${sp}%`;
  return `${dec(v, v >= 10 ? 0 : 1)}${sp}%`;
}

/** Quantity with its unit separated by a thin space ("32,7 µg/m³"); `digits` decimals, and none when the unit is empty. */
export const withUnit = (n: number, unit: string, digits = 1): string => (unit ? `${dec(n, digits)}${THIN}${unit}` : dec(n, digits));


/** Number with 3 significant figures ("14,355" -> "14,4", "0,537" stays); from 1000 up it is a whole number. */
export const sig3 = (n: number): string => (Math.abs(n) >= 1000 ? dec(Math.round(n), 0) : nf("sig3", { maximumSignificantDigits: 3, useGrouping: false }).format(n));

/** Number with up to 3 decimals and no trailing zeros ("5,998", "12"). */
export const numShort = (n: number): string => nf("short3", { maximumFractionDigits: 3 }).format(n);
