import { locale, tr } from "../i18n";
import { dec, pct, THIN } from "./format";
import type { Profile } from "./stationProfiles";

/**
 * Every phrase of the "Por zonas" colouring modes and the station card that names the per-entity rule share, in one
 * place. The share is "the rule that decides the prediction" (winning rule, TSK) or, for a mixture of rules (contract
 * v0.7, `mixture = true`), "the rule that adds the most to the predicted category": no rule of a mixture decides.
 * Descriptive wording only: a rule "is used more here"; it never causes or explains what happens there.
 */

export type ZoneMode = "characteristic" | "profiles" | "top";
export const ZONE_MODES: readonly ZoneMode[] = ["characteristic", "profiles", "top"];

export const modeLabel = (m: ZoneMode, mixture = false): string =>
  ({
    characteristic: tr("Regla característica", "Characteristic rule"),
    profiles: tr("Perfiles", "Profiles"),
    top: mixture ? tr("Regla que más suma", "Rule that adds the most") : tr("Regla que más decide", "Rule that decides most"),
  })[m];

/** The card's subtitle for each mode (`one`: "estación", "zona de taxi"…). */
export const modeSubtitle = (m: ZoneMode, one: string, mixture = false): string =>
  mixture
    ? ({
        characteristic: tr(`La regla que más a menudo es la que más suma en cada ${one}, en comparación con el conjunto. Elige una regla para ver dónde es la que más suma.`, `The rule that most often adds the most in each ${one}, compared with all of them. Choose a rule to see where it adds the most.`),
        profiles: tr(`Grupos de ${one === "punto de muestreo" ? "puntos" : "lugares"} en los que las mismas reglas son, en proporciones parecidas, las que más suman.`, `Groups of places where the same rules add the most, in similar proportions.`),
        top: tr(`La regla que más suma a la categoría prevista en más predicciones de cada ${one}. Elige una regla para ver dónde es la que más suma.`, `The rule that adds the most to the predicted category in most predictions of each ${one}. Choose a rule to see where it adds the most.`),
      })[m]
    : ({
    characteristic: tr(`La regla que más se usa en cada ${one} en comparación con el conjunto. Elige una regla para ver dónde decide.`, `The rule used most in each ${one} compared with all of them. Choose a rule to see where it decides.`),
    profiles: tr(`Grupos de ${one === "punto de muestreo" ? "puntos" : "lugares"} en los que el modelo reparte las predicciones entre sus reglas de forma parecida.`, `Groups of places where the model splits its predictions among its rules in a similar way.`),
    top: tr(`La regla que más predicciones decide en cada ${one}. Elige una regla para ver dónde decide.`, `The rule that decides most predictions in each ${one}. Choose a rule to see where it decides.`),
  })[m];

export const noCharacteristic = (): string => tr("sin regla característica", "no characteristic rule");
export const noProfile = (): string => tr("sin perfil (pocas predicciones)", "no profile (few predictions)");

/** "×1,5": how many times the rule's share here is its share overall. */
export const liftShort = (lift: number): string => `×${dec(lift, lift >= 10 ? 0 : 1)}`;

/** The share of one rule at one entity, as a clause. */
export const shareHere = (share: number, mixture = false): string =>
  mixture ? tr(`es la que más suma en el ${pct(share)} de sus predicciones`, `adds the most in ${pct(share)} of its predictions`) : tr(`decide el ${pct(share)} de sus predicciones`, `decides ${pct(share)} of its predictions`);
export const shareOverall = (share: number): string => tr(`el ${pct(share)} en el conjunto`, `${pct(share)} across all of them`);

/** One rule's line in the station card: here against everywhere, and how many times more. */
export const liftSentence = (here: number, overall: number, lift: number, count: number, mixture = false): string =>
  mixture
    ? tr(`Aquí es la que más suma en el ${pct(here)} de las predicciones (${count.toLocaleString(locale())}), frente al ${pct(overall)} en el conjunto: ${dec(lift, 1)} veces más.`, `Here it adds the most in ${pct(here)} of the predictions (${count.toLocaleString(locale())}), compared with ${pct(overall)} across all of them: ${dec(lift, 1)} times as much.`)
    : tr(`Aquí decide el ${pct(here)} de las predicciones (${count.toLocaleString(locale())}), frente al ${pct(overall)} en el conjunto: ${dec(lift, 1)} veces más.`, `Here it decides ${pct(here)} of the predictions (${count.toLocaleString(locale())}), compared with ${pct(overall)} across all of them: ${dec(lift, 1)} times as much.`);

export const hereLabel = (): string => tr("aquí", "here");
export const overallLabel = (): string => tr("en el conjunto", "everywhere");

/** «más R03 y R07»; «sin regla destacada» when no rule clears the bars in the profile. */
export function profileName(p: Pick<Profile, "naming">): string {
  const ids = p.naming.map((l) => l.ruleId);
  if (ids.length === 0) return tr("sin regla destacada", "no rule stands out");
  return ids.length === 1 ? tr(`más ${ids[0]}`, `more ${ids[0]}`) : tr(`más ${ids[0]} y ${ids[1]}`, `more ${ids[0]} and ${ids[1]}`);
}
export const profileTitle = (p: Pick<Profile, "letter" | "naming">): string => tr(`Perfil ${p.letter} · ${profileName(p)}`, `Profile ${p.letter} · ${profileName(p)}`);

/** The legend's explanation of each mode: what a colour means and the bars a rule has to clear. */
/** A threshold share as a whole percentage ("5 %"), not pct's "5,0 %". */
const whole = (share: number): string => tr(`${Math.round(share * 100)}${THIN}%`, `${Math.round(share * 100)}%`);

export const characteristicNote = (minShare: number, minCount: number, minLift: number, mixture = false): string =>
  mixture
    ? tr(`Cada color es la regla que, en comparación con el conjunto, más a menudo es la que más suma a la categoría prevista en ese lugar: su parte de las predicciones de allí dividida por su parte en todos. Solo se tiene en cuenta si es la que más suma en al menos el ${whole(minShare)} y ${minCount} de las predicciones del lugar, y al menos ${dec(minLift, 2)} veces su parte general.`,`Each colour is the rule that, compared with all places, most often adds the most to the predicted category there: its share of the predictions there divided by its share everywhere. A rule only counts if it adds the most in at least ${whole(minShare)} and ${minCount} of the place's predictions, and at least ${dec(minLift, 2)} times its overall share.`)
    : tr(`Cada color es la regla que más se usa en ese lugar en comparación con el conjunto, medida como su parte de las predicciones de allí dividida por su parte en todos. Solo se tiene en cuenta si decide al menos el ${whole(minShare)} y ${minCount} de las predicciones del lugar, y al menos ${dec(minLift, 2)} veces su parte general.`, `Each colour is the rule used most in that place compared with all of them, measured as its share of the predictions there divided by its share everywhere. A rule only counts if it decides at least ${whole(minShare)} and ${minCount} of the place's predictions, and at least ${dec(minLift, 2)} times its overall share.`);
export const profilesNote = (k: number, silhouette: number, weak: boolean): string =>
  tr(`${k} perfiles agrupan los lugares por cómo se reparten sus predicciones entre las reglas (k-medias con semilla fija; k elegido por la silueta, ${dec(silhouette, 2)}). Cada perfil se nombra por las reglas que más se usan en él frente al conjunto.${weak ? " Los perfiles apenas se separan, así que tómalos solo como orientación." : ""}`, `${k} profiles group the places by how their predictions split among the rules (k-means with a fixed seed; k chosen by the silhouette, ${dec(silhouette, 2)}). Each profile is named after the rules used most in it compared with all of them.${weak ? " The profiles barely separate, so take them as a rough guide." : ""}`);
export const topNote = (mixture = false): string =>
  mixture ? tr("Cada color es una regla (una categoría, no una escala). Pulsa una para ver dónde es la que más suma.", "Each colour is a rule (a category, not a scale). Click one to see where it adds the most.") : tr("Cada color es una regla (una categoría, no una escala). Pulsa una para ver dónde decide.", "Each colour is a rule (a category, not a scale). Click one to see where it decides.");

export const distinguishHeading = (masculine: boolean): string => tr(`Qué ${masculine ? "lo" : "la"} distingue`, "What sets it apart");
export const topHeading = (mixture = false): string => (mixture ? tr("Las reglas que más suman aquí", "The rules that add the most here") : tr("Las reglas que más deciden aquí", "The rules that decide most here"));
export const mixNote = (): string => tr("Cada predicción lleva la categoría de la regla que la decide. Entre paréntesis, la cifra del conjunto.", "Each prediction takes the category of the rule that decides it. In brackets, the share across all places.");
export const distinguishLead = (): string => tr("Reglas que aquí se usan claramente más que en el conjunto (×2 es el doble de su parte general).", "Rules used clearly more here than overall (×2 means double their share everywhere).");
export const noneStandsOut = (): string => tr("Ninguna regla se usa aquí claramente más que en el conjunto.", "No rule is used clearly more here than overall.");
