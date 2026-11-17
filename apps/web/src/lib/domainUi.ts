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
  /** The task in one sentence (the «Tarea» line that opens the first tab), from the task's own horizon and classes. */
  task?: (t: TaskContext) => string;
}

/** What a task statement may use: the horizon, «la categoría EAQI de NO₂», and the class names in the interface language. */
export interface TaskContext {
  hours: number;
  predicts: string;
  /** «Buena, Aceptable, Moderada o Mala o peor». */
  classes: string;
}

// Built at call time (not at import): the language can change while the page is open.
const air = (): DomainUi => ({
  title: tr("Calidad del aire", "Air quality"),
  noun: tr({ one: "estación", many: "estaciones" }, { one: "station", many: "stations" }),
  task: ({ hours, predicts, classes }) =>
    tr(`Prever, ${hours} h antes, ${predicts}${classes ? ` (${classes})` : ""} en cada estación de medida.`, `Predict, ${hours} h ahead, ${predicts}${classes ? ` (${classes})` : ""} at each measuring station.`),
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
    task: ({ hours, classes }) =>
      tr(`Prever, ${hours} h antes, si la demanda de taxi amarillo en cada zona será ${classes} respecto a lo habitual en esa zona a esa hora de la semana.`, `Predict, ${hours} h ahead, whether yellow-taxi demand in each zone will be ${classes} relative to what is usual for that zone at that hour of the week.`),
  }),
  fnirs: () => ({
    title: tr("Actividad cerebral (fNIRS)", "Brain activity (fNIRS)"),
    task: () => tr("A partir de la actividad cerebral medida con fNIRS, distinguir si una persona hacía una tarea de memoria fácil o difícil.", "From brain activity measured with fNIRS, tell whether a person was doing an easy or a hard memory task."),
    noun: tr({ one: "ensayo", many: "ensayos" }, { one: "trial", many: "trials" }),
  }),
  water: () => ({
    title: tr("Calidad del agua", "Water quality"),
    noun: tr({ one: "punto de muestreo", many: "puntos de muestreo" }, { one: "sampling point", many: "sampling points" }),
    task: () => tr("Estimar el oxígeno disuelto de cada muestra de río a partir de lo que mide esa misma muestra.", "Estimate the dissolved oxygen of each river sample from what that same sample measures."),
  }),
};

export const domainUi = (domain: string): DomainUi => (DOMAIN_UI[domain] ?? air)();

/** «a, b, c o d» / "a, b, c or d": a list of options in a sentence. */
export function listOr(items: readonly string[]): string {
  if (items.length < 2) return items.join("");
  return `${items.slice(0, -1).join(", ")}${tr(" o ", " or ")}${items[items.length - 1]}`;
}

/**
 * Articles of an entity noun. Spanish: "punto de muestreo" is masculine, "estación" and "zona de taxi" are feminine.
 * English has one form ("a", "this", "the"); English sentences are better written whole without this helper.
 */
export function articles(noun: string): { un: string; este: string; ese: string; el: string; Este: string } {
  const m = noun.startsWith("punto");
  return tr(m ? { un: "un", este: "este", ese: "ese", el: "el", Este: "Este" } : { un: "una", este: "esta", ese: "esa", el: "la", Este: "Esta" }, { un: "a", este: "this", ese: "that", el: "the", Este: "This" });
}
