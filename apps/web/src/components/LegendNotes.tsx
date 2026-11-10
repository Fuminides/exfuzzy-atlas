import { tr } from "../i18n";
import type { SplitSpec } from "../api/types";
import { PERIOD_NOTE, splitPeriod, splitPeriodsIn, type TimeWindow } from "../lib/windows";

/**
 * Which train/validation/test periods the view touches. An aggregate (territories, mean or frequency) spans a window,
 * not one issue time: the note says which periods it touches.
 */
export function PeriodNote({ window, aggregate, time, split }: { window: TimeWindow | null; aggregate: boolean; time: string; split: SplitSpec }) {
  return window && aggregate ? (
    <p className="legend-count" data-testid="split-period">
      {tr("La ventana toca: ", "The window touches: ")}{splitPeriodsIn(window, split).map((p) => PERIOD_NOTE[p]).join("; ")}.
    </p>
  ) : (
    <p className="legend-count" data-testid="split-period">
      {tr(`Hora de emisión seleccionada en el ${PERIOD_NOTE[splitPeriod(time, split)]}.`, `Selected issue time: ${PERIOD_NOTE[splitPeriod(time, split)]}.`)}
    </p>
  );
}

export function NoGeometryNote({ count }: { count: number }) {
  return (
    count > 0 && (
      <p className="legend-count">
        {count === 1
          ? tr(`${count} entidad sin geometría. No se dibuja en el mapa, pero sigue en la tabla.`, `${count} entity without geometry. It isn't drawn on the map but stays in the table.`)
          : tr(`${count} entidades sin geometría. No se dibujan en el mapa, pero siguen en la tabla.`, `${count} entities without geometry. They aren't drawn on the map but stay in the table.`)}
      </p>
    )
  );
}

/** Entities the model has no data for (`modelled: false`) are drawn light and the legend says so ("sin modelo", never a class). */
export function AbsentNote({ absent, modelled, total, noun, extra }: { absent: number; modelled: number; total: number; noun: string; extra?: string }) {
  return (
    absent > 0 && (
      <p className="legend-count" data-testid="absent-note">
        <span className="marker marker--unmodelled" aria-hidden="true" /> {tr(`${modelled} de ${total} ${noun} con modelo; ${absent} sin modelo (gris claro).`, `${modelled} of ${total} ${noun} modelled; ${absent} not modelled (light grey).`)} {extra ?? tr("No tienen predicción ni activación.", "They have no prediction and no activation.")}
      </p>
    )
  );
}


/** Entities with no prediction at any time of the published period: drawn as small light dots, counted apart from the per-time gaps. */
export function NeverPredictedNote({ count, noun, period }: { count: number; noun: { one: string; many: string }; period: string }) {
  return (
    count > 0 && (
      <p className="legend-count" data-testid="never-predicted-note">
        <span className="marker marker--unmodelled" aria-hidden="true" />{" "}
        {tr(`${count} ${count === 1 ? noun.one : noun.many} sin predicciones ${period.startsWith("entre") ? period : `en ${period}`} (en gris claro).`,
          `${count} ${count === 1 ? noun.one : noun.many} with no predictions ${/^(between|entre)\b/.test(period) ? period : `in ${period}`} (in light grey).`,
        )}
      </p>
    )
  );
}
