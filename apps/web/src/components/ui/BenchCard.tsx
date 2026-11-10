import { useId, type ReactNode } from "react";

interface BenchCardProps {
  title: ReactNode;
  /** One short sentence under the title. */
  subtitle?: ReactNode;
  /** Right side of the header: a control that belongs to this card. */
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  /** Heading level: 2 for a card of a tab, 3 for a side card. */
  level?: 2 | 3;
  /** Accessible name of the section when it is not the title. */
  label?: string;
}

/**
 * A "bench" card: DESIGN.md's Neutral Card (Mist, 24 px radius, no border or shadow), with a header row (title, a
 * sentence, a control on the right) and generous spacing. Every tab's cards are drawn with it.
 */
export function BenchCard({ title, subtitle, actions, children, className, level = 2, label }: BenchCardProps) {
  const id = useId();
  const Heading = level === 2 ? "h2" : "h3";
  return (
    <section className={`bench bench--h${level}${className ? ` ${className}` : ""}`} aria-label={label} aria-labelledby={label ? undefined : id}>
      <header className="bench-head">
        <div className="bench-titles">
          <Heading id={id} className="bench-title">
            {title}
          </Heading>
          {subtitle && <p className="bench-sub">{subtitle}</p>}
        </div>
        {actions && <div className="bench-actions">{actions}</div>}
      </header>
      <div className="bench-body">{children}</div>
    </section>
  );
}
