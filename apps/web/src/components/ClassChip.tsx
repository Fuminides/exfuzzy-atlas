import { useNames } from "../lib/labels";

/**
 * A class of the model's target scheme: official colour swatch plus its name (the colour is never the only cue).
 * `label` is the class key; the text is its translated name when the model publishes one (or `text`, when the caller has it).
 */
export function ClassChip({ label, color, text }: { label: string; color: string; text?: string }) {
  const names = useNames();
  return (
    <span className="class-chip" data-class={label}>
      <span className="class-swatch" style={{ background: color }} aria-hidden="true" />
      {text ?? names.cls(label)}
    </span>
  );
}
