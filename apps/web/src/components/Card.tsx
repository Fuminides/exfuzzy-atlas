import { tr } from "../i18n";
import { BenchCard } from "./ui/BenchCard";

interface CardProps {
  title: string;
  /** Right side of the header: a control that belongs to this card. */
  actions?: React.ReactNode;
  /** One short sentence under the title. */
  subtitle?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  /** Heading level: 2 for a card of a tab. */
  level?: 2 | 3;
}

/** A titled block of a tab: the same bench header everywhere (title, optional sentence, optional controls). */
export function Card({ title, actions, subtitle, children, className, level = 2 }: CardProps) {
  return (
    <BenchCard title={title} subtitle={subtitle} actions={actions} level={level} className={`card${className ? ` ${className}` : ""}`}>
      {children}
    </BenchCard>
  );
}

/** Method notes live behind a disclosure so a tab reads as a page and not as a wall of text. */
export function MoreInfo({ summary = tr("Más información", "More information"), children }: { summary?: string; children: React.ReactNode }) {
  return (
    <details className="more-info">
      <summary>{summary}</summary>
      <div className="more-info-body">{children}</div>
    </details>
  );
}

/** The title of a tab and, under it, one plain sentence: what is being looked at and over which period. */
export function PageHead({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <header className="page-head">
      <h1>{title}</h1>
      <p className="lead" data-testid="page-lead">
        {children}
      </p>
    </header>
  );
}

/** A payload the backend has not published yet (404): said plainly, never an error and never an empty chart. */
export function NotYet({ what, children }: { what: string; children?: React.ReactNode }) {
  return (
    <div className="not-yet" role="status" data-testid="not-yet">
      <strong>{tr(`${what}: no disponible todavía.`, `${what}: not available yet.`)}</strong>
      {children && <p>{children}</p>}
    </div>
  );
}
