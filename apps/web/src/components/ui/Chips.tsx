import type { ReactNode } from "react";

export interface Chip {
  key: string;
  content: ReactNode;
  /** above / par / below: a standing against a reference; neutral otherwise. */
  tone?: "above" | "par" | "below" | "neutral";
  /** data-* attributes for the item (tests, styling). */
  data?: Record<`data-${string}`, string>;
}

/** A row of quiet pill chips (a list): Mist, no border; a standing gets a neutral glyph, never a colour. */
export function Chips({ items, label, testId }: { items: readonly Chip[]; label: string; testId?: string }) {
  return (
    <ul className="chips" aria-label={label} data-testid={testId}>
      {items.map((c) => (
        <li key={c.key} className={`chip chip--${c.tone ?? "neutral"}`} {...c.data}>
          {c.content}
        </li>
      ))}
    </ul>
  );
}
