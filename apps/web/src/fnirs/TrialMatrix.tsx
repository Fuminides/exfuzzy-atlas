import { useRef } from "react";
import type { FnirsModelCard, TrialRecord } from "../api/types";
import { ClassChip } from "../components/ClassChip";
import { tr } from "../i18n";
import { classColor } from "../lib/classifier";
import { useNames } from "../lib/labels";

type Scheme = FnirsModelCard["target_scheme"];

/** Rows of the matrix: one subject each, test subjects first (the order of the trials body), trials by block. */
export function subjectRows(trials: readonly TrialRecord[]): { subject: number; split: "train" | "test"; trials: TrialRecord[] }[] {
  const rows = new Map<number, { subject: number; split: "train" | "test"; trials: TrialRecord[] }>();
  for (const t of trials) {
    const row = rows.get(t.subject) ?? { subject: t.subject, split: t.split, trials: [] };
    row.trials.push(t);
    rows.set(t.subject, row);
  }
  for (const row of rows.values()) row.trials.sort((a, b) => a.trial - b.trial);
  return [...rows.values()];
}

const outcome = (t: TrialRecord): "hit" | "miss" | "none" => (t.predicted_label == null ? "none" : t.predicted_label === t.observed_label ? "hit" : "miss");

/**
 * Every published trial at a glance: one row per subject, one cell per block, filled with the block's actual class; a
 * cross marks a block the model got wrong, a hatch one it gave no class. One tab stop: the arrow keys move the selection.
 */
export function TrialMatrix({ trials, scheme, sampleId, onTrial }: { trials: readonly TrialRecord[]; scheme: Scheme; sampleId: string; onTrial: (id: string) => void }) {
  const names = useNames();
  const rows = subjectRows(trials);
  const grid = useRef<HTMLDivElement>(null);
  const width = Math.max(...rows.map((r) => r.trials.length));
  const at = (() => {
    for (const [i, r] of rows.entries()) {
      const j = r.trials.findIndex((t) => t.sample_id === sampleId);
      if (j >= 0) return [i, j] as const;
    }
    return [0, 0] as const;
  })();
  const onKey = (e: React.KeyboardEvent) => {
    const moves: Record<string, [number, number]> = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };
    const m = moves[e.key];
    if (!m) return;
    e.preventDefault();
    const i = Math.min(rows.length - 1, Math.max(0, at[0] + m[0]));
    const row = rows[i]!;
    const j = Math.min(row.trials.length - 1, Math.max(0, at[1] + m[1]));
    onTrial(row.trials[j]!.sample_id);
    requestAnimationFrame(() => grid.current?.querySelector<HTMLElement>('[aria-selected="true"]')?.focus());
  };
  const firstTrain = rows.findIndex((r) => r.split === "train");
  return (
    <div className="trial-matrix-wrap">
      <div
        ref={grid}
        className="trial-matrix"
        role="grid"
        aria-label={tr("Todos los ensayos: un sujeto por fila, un bloque por columna", "All trials: one subject per row, one block per column")}
        onKeyDown={onKey}
        style={{ gridTemplateColumns: `5.25rem repeat(${width}, 1.15rem) 3rem` }}
        data-testid="trial-matrix"
      >
        <div role="row" className="tm-row tm-head">
          <span role="columnheader" className="tm-label">{tr("Sujeto", "Subject")}</span>
          {Array.from({ length: width }, (_, j) => (
            <span key={j} role="columnheader" className="tm-col">{(j + 1) % 3 === 1 ? j + 1 : ""}</span>
          ))}
          <span role="columnheader" className="tm-hits">{tr("Aciertos", "Correct")}</span>
        </div>
        {rows.map((r, i) => {
          const hits = r.trials.filter((t) => outcome(t) === "hit").length;
          return (
            <div key={r.subject} role="row" className={`tm-row${i === firstTrain ? " tm-row--first-train" : ""}`} data-subject={r.subject}>
              <span role="rowheader" className="tm-label">
                {r.subject}
                {r.split === "test" && <span className="tm-test">{tr("prueba", "test")}</span>}
              </span>
              {r.trials.map((t) => {
                const o = outcome(t);
                const selected = t.sample_id === sampleId;
                return (
                  <span
                    key={t.sample_id}
                    role="gridcell"
                    aria-selected={selected}
                    tabIndex={selected ? 0 : -1}
                    className={`tm-cell tm-cell--${o}${t.observed_label === scheme.classes[scheme.classes.length - 1]?.label ? " tm-cell--dark" : ""}`}
                    style={{ background: o === "none" ? undefined : classColor(scheme, t.observed_label) }}
                    data-sample={t.sample_id}
                    aria-label={tr(
                      `Sujeto ${t.subject}, bloque ${t.trial}: real ${names.cls(t.observed_label).toLowerCase()}, ${o === "none" ? "sin clase" : `predicha ${names.cls(t.predicted_label!).toLowerCase()}`}`,
                      `Subject ${t.subject}, block ${t.trial}: actual ${names.cls(t.observed_label).toLowerCase()}, ${o === "none" ? "no class" : `predicted ${names.cls(t.predicted_label!).toLowerCase()}`}`,
                    )}
                    title={tr(`Sujeto ${t.subject}, bloque ${t.trial}: ${names.cls(t.observed_label).toLowerCase()}${o === "miss" ? " (el modelo falló)" : ""}`, `Subject ${t.subject}, block ${t.trial}: ${names.cls(t.observed_label).toLowerCase()}${o === "miss" ? " (the model was wrong)" : ""}`)}
                    onClick={() => onTrial(t.sample_id)}
                  >
                    {o === "miss" ? "×" : ""}
                  </span>
                );
              })}
              <span className="tm-hits" data-raw={hits}>{hits}/{r.trials.length}</span>
            </div>
          );
        })}
      </div>
      <div className="tm-legend muted small">
        {scheme.classes.map((c) => <ClassChip key={c.label} label={c.label} color={c.color ?? "#999"} />)}
        <span><span className="tm-key tm-key--miss" aria-hidden="true">×</span> {tr("el modelo falló", "the model was wrong")}</span>
        <span><span className="tm-key tm-key--none" aria-hidden="true" /> {tr("sin clase", "no class")}</span>
        <span>{tr("El color es la carga real del bloque. En las filas de entrenamiento, las predicciones son dentro de la muestra.", "The colour is the block's actual load. Training rows are in-sample predictions.")}</span>
      </div>
    </div>
  );
}
