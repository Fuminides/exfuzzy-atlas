import type { TargetScheme, TaskInfo } from "../api/types";
import { targetLabel } from "../components/SeriesChart";
import { isOfficialScheme } from "./classifier";
import { tr } from "../i18n";
import { schemeShort } from "./labels";
import { sameSampleText } from "./format";

/** What the task predicts, as a noun phrase: "la categoría ICA de NO₂", "el nivel relativo de recogidas de taxi", "el oxígeno disuelto". */
export function predictsText(task: Pick<TaskInfo, "target">, scheme: TargetScheme | null): string {
  const target = targetLabel(task.target);
  if (!scheme) return tr(`el ${target}`, `the ${target}`);
  const short = schemeShort(scheme);
  if (isOfficialScheme(scheme)) return short ? tr(`la categoría ${short} de ${target}`, `the ${short} category of ${target}`) : tr(`la categoría oficial de ${target}`, `the official category of ${target}`);
  return short ? tr(`el ${short.toLowerCase()} de ${target}`, `the ${short.toLowerCase()} of ${target}`) : tr(`el nivel de ${target}`, `the level of ${target}`);
}

/** The horizon in a sentence: "a +6 h"; horizon 0 is same-sample inference and is never a forecast. */
export const horizonClause = (hours: number): string => (hours === 0 ? `(${sameSampleText()})` : tr(`a +${hours} h`, `at +${hours} h`));

/** "+6 h" for labels; "misma muestra" at horizon 0. */
export const horizonShort = (hours: number): string => (hours === 0 ? tr("misma muestra", "same sample") : `+${hours} h`);
