import { tr } from "../i18n";
import type { Outcome } from "../lib/labels";
import { strongestText } from "../lib/mixture";

/** Near-black or white, whichever has the higher contrast on a fill of this colour (text set inside a class pill). */
export function inkOn(hex: string): string {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex.trim());
  if (!m) return "#0b1220";
  const lin = (c: string) => {
    const v = parseInt(c, 16) / 255;
    return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  const L = 0.2126 * lin(m[1]!) + 0.7152 * lin(m[2]!) + 0.0722 * lin(m[3]!);
  // #0b1220 has a luminance of 0.0065: white wins only below the point where both give the same ratio
  return (1.05 / (L + 0.05)) > (L + 0.05) / 0.0565 ? "#ffffff" : "#0b1220";
}

/** What a rule predicts as a pill: the class in its official colour, or the value / term in the accent tint. */
export function OutcomePill({ outcome }: { outcome: Outcome }) {
  // v0.7 rule mixture: the class the rule supports most, said in words (a mixture rule has no conclusion of its own)
  if (outcome.kind === "mixture")
    return outcome.key === null ? (
      <span className="rmx-pill rmx-pill--value">{strongestText(null)}</span>
    ) : (
      <span className="rmx-pill-mixture" data-strongest={outcome.key}>
        <span className="rmx-pill-lead">{tr("apoya sobre todo", "supports most")}</span>{" "}
        <span className="rmx-pill" data-class={outcome.key} style={outcome.color ? { background: outcome.color, color: inkOn(outcome.color) } : undefined}>
          {outcome.label}
        </span>
      </span>
    );
  if (outcome.kind === "class")
    return (
      <span className="rmx-pill" data-class={outcome.key} style={outcome.color ? { background: outcome.color, color: inkOn(outcome.color) } : undefined}>
        {outcome.label}
      </span>
    );
  if (outcome.kind === "value") return <span className="rmx-pill rmx-pill--value">{outcome.text}</span>;
  return (
    <span className="rmx-pill rmx-pill--value">
      <em>{outcome.label}</em>
    </span>
  );
}
