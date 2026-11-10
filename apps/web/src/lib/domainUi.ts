import { tr } from "../i18n";

/** What the web says per domain. Attribution and licences are not here: they come from the API (`attribution`, v0.4). */
export interface DomainUi {
  /** Name of the domain as a group heading when it serves several tasks (`DomainInfo.title` names one of them). */
  title: string;
  /** What an entity is called: "estación", "zona", "punto de muestreo". */
  noun: { one: string; many: string };
  /** Domain-specific sentence for the prediction legend (NYC: what the level is relative to). */
  predictionNote?: string;
  /** Name of the predicted level when the scheme is relative to a per-entity reference (NYC). */
  levelTitle?: string;
  /** Data mode: a count with a long tail (NYC trips per zone) is coloured on its square root; the legend says so. */
  dataScale?: "sqrt";
  /** What an entity "sin modelo" (`modelled: false`) means in this domain; shown in the legend when there are any. */
  absentNote?: string;
}

// Built at call time (not at import): the language can change while the page is open.
const air = (): DomainUi => ({
  title: tr("Calidad del aire", "Air quality"),
  noun: tr({ one: "estación", many: "estaciones" }, { one: "station", many: "stations" }),
});

const DOMAIN_UI: Record<string, () => DomainUi> = {
  air,
  mobility: () => ({
    title: tr("Movilidad urbana", "Urban mobility"),
    noun: tr({ one: "zona de taxi", many: "zonas de taxi" }, { one: "taxi zone", many: "taxi zones" }),
    levelTitle: tr("nivel de demanda de taxi amarillo", "yellow taxi demand level"),
    dataScale: "sqrt",
    absentNote: tr("Las zonas sin modelo (con poco volumen en el entrenamiento) aparecen en gris claro. No tienen predicción ni activación, y el gris no indica demanda baja.", "Zones that aren't modelled (low volume in training) appear in light grey. They have no prediction or activation, and the grey doesn't mean low demand."),
    predictionNote: tr("Nivel de demanda de taxi amarillo respecto a lo habitual en esa zona a esa hora de la semana (percentil del periodo de entrenamiento).", "Yellow taxi demand level relative to what is usual in that zone at that hour of the week (percentile of the training period)."),
  }),
  water: () => ({
    title: tr("Calidad del agua", "Water quality"),
    noun: tr({ one: "punto de muestreo", many: "puntos de muestreo" }, { one: "sampling point", many: "sampling points" }),
  }),
};

export const domainUi = (domain: string): DomainUi => (DOMAIN_UI[domain] ?? air)();

/**
 * Articles of an entity noun. Spanish: "punto de muestreo" is masculine, "estación" and "zona de taxi" are feminine.
 * English has one form ("a", "this", "the"); English sentences are better written whole without this helper.
 */
export function articles(noun: string): { un: string; este: string; ese: string; el: string; Este: string } {
  const m = noun.startsWith("punto");
  return tr(m ? { un: "un", este: "este", ese: "ese", el: "el", Este: "Este" } : { un: "una", este: "esta", ese: "esa", el: "la", Este: "Esta" }, { un: "a", este: "this", ese: "that", el: "the", Este: "This" });
}
