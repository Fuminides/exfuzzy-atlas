/**
 * Helpers of the rule hovercards (components/RuleRef.tsx): finding rule ids inside a text, and placing a floating card
 * next to its trigger without leaving the viewport.
 */

/** A rule id as the models publish them: R and two or more digits (R02, R10, R113). */
export const RULE_ID = /\bR\d{2,}\b/g;

export type TextPart = string | { ruleId: string };

/**
 * Splits a text on the rule ids it mentions. Only the ids `isKnown` accepts become parts of their own; any other "R12"
 * (a rule of another model, a road name) stays in the text. Adjacent text is merged, so a text with no known id comes
 * back as one string.
 */
export function splitRuleIds(text: string, isKnown: (id: string) => boolean): TextPart[] {
  const out: TextPart[] = [];
  let last = 0;
  for (const m of text.matchAll(RULE_ID)) {
    const id = m[0];
    if (!isKnown(id)) continue;
    if (m.index > last) out.push(text.slice(last, m.index));
    out.push({ ruleId: id });
    last = m.index + id.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out.length ? out : [text];
}

export interface Box {
  top: number;
  left: number;
  bottom: number;
  right: number;
}

/**
 * Where a card of `card` size goes for a trigger at `anchor` in a viewport of `view` size: below it when it fits (or when
 * below has at least as much room as above), else above; left-aligned with the trigger, then pushed back inside the
 * viewport (`margin` from every edge). A card taller than either side is clamped to the viewport (it scrolls inside).
 */
export function placeCard(
  anchor: Box,
  card: { width: number; height: number },
  view: { width: number; height: number },
  gap = 8,
  margin = 8,
): { top: number; left: number; side: "below" | "above" } {
  const roomBelow = view.height - anchor.bottom - gap - margin;
  const roomAbove = anchor.top - gap - margin;
  const side = card.height <= roomBelow || (card.height > roomAbove && roomBelow >= roomAbove) ? "below" : "above";
  const rawTop = side === "below" ? anchor.bottom + gap : anchor.top - gap - card.height;
  const top = Math.max(margin, Math.min(rawTop, view.height - margin - card.height));
  const left = Math.max(margin, Math.min(anchor.left, view.width - margin - card.width));
  return { top, left, side };
}
