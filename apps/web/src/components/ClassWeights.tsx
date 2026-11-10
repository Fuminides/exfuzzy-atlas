import type { TargetScheme } from "../api/types";
import { tr } from "../i18n";
import { classColor } from "../lib/classifier";
import { useNames } from "../lib/labels";
import { centredNote, polarity, polarityWord, signed } from "../lib/mixture";
import { ClassChip } from "./ClassChip";

/**
 * Support (+) and suppression (−) of one rule of a mixture (contract v0.7), per class: a bar that grows right of a
 * neutral zero line in the support colour or left of it in the suppression colour (DESIGN.md, the diverging pair), with
 * the signed value written beside it. Colour is never the only cue: the side, the sign and the text say the same. The
 * values are the API's (`class_weights_centred`, or a trace's `class_contributions_centred`); `scale` (the largest |value|
 * the view shows) only sets the bar lengths so that bars are comparable within a view.
 */
export function WeightBar({ value, scale }: { value: number; scale: number }) {
  const half = scale > 0 ? Math.min(1, Math.abs(value) / scale) * 50 : 0;
  const p = polarity(value);
  return (
    <span className="cw-bar" aria-hidden="true">
      <span className="cw-zero" />
      {p !== "none" && <span className={`cw-fill cw-fill--${p === "support" ? "pos" : "neg"}`} style={p === "support" ? { left: "50%", width: `${half}%` } : { right: "50%", width: `${half}%` }} />}
    </span>
  );
}

/** The signed figure of a bar, with its polarity for screen readers. */
export function WeightValue({ value, strong = false }: { value: number; strong?: boolean }) {
  const p = polarity(value);
  const text = signed(value);
  return (
    <span className={`cw-value cw-value--${p}${strong ? " cw-value--strong" : ""}`} data-raw={String(value)}>
      {text}
      <span className="sr-only"> ({polarityWord(p)})</span>
    </span>
  );
}

interface Props {
  /** class → centred value, as published. */
  values: Readonly<Record<string, number>>;
  scheme: TargetScheme;
  scale: number;
  /** The class the rule supports most (`strongest_class`): its row is marked. */
  strongest?: string | null;
  /** Accessible name of the list. */
  label: string;
  testId?: string;
}

/** One row per class of the scheme, in its order: the class, the bar, the signed value. */
export function ClassWeights({ values, scheme, scale, strongest = null, label, testId = "class-weights" }: Props) {
  const names = useNames();
  return (
    <ul className="cw" aria-label={label} data-testid={testId}>
      {scheme.classes
        .filter((c) => typeof values[c.label] === "number")
        .map((c) => {
          const v = values[c.label]!;
          return (
            <li key={c.label} data-class={c.label} data-sign={polarity(v)} className={c.label === strongest ? "cw-row cw-row--strongest" : "cw-row"}>
              <span className="cw-class">
                <ClassChip label={c.label} color={classColor(scheme, c.label)} text={names.cls(c.label)} />
              </span>
              <WeightBar value={v} scale={scale} />
              <WeightValue value={v} strong={c.label === strongest} />
            </li>
          );
        })}
    </ul>
  );
}

/** The key of the weight bars: what each side and colour means. */
export function WeightKey({ note = true }: { note?: boolean }) {
  return (
    <div className="cw-key" data-testid="class-weights-key">
      <span className="cw-key-item">
        <span className="cw-key-swatch cw-fill--pos" aria-hidden="true" /> {tr("+ apoyo: sube esa categoría frente a las demás", "+ support: raises that category against the others")}
      </span>
      <span className="cw-key-item">
        <span className="cw-key-swatch cw-fill--neg" aria-hidden="true" /> {tr("− supresión: la baja frente a las demás", "− suppression: lowers it against the others")}
      </span>
      {note && <p className="muted small">{centredNote()}</p>}
    </div>
  );
}
