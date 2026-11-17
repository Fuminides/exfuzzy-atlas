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
/**
 * The page title (H1) and its lead. `accent` is the phrase of the title that names what the page is about: set in the
 * terracotta italic of the hero's figure (DESIGN.md, Colour in titles); the heading's text is unchanged.
 */
export function PageHead({ title, accent, children }: { title: string; accent?: string; children: React.ReactNode }) {
  const at = accent ? title.indexOf(accent) : -1;
  return (
    <header className="page-head">
      <h1>{at < 0 ? title : <>{title.slice(0, at)}<span className="title-accent">{accent}</span>{title.slice(at + accent!.length)}</>}</h1>
      <p className="lead" data-testid="page-lead">
        {children}
      </p>
    </header>
  );
}

/** A payload the backend has not published yet (404): said plainly, never an error and never an empty chart. */
/** The task in one sentence, first thing on the first tab of a problem: what the rules below are solving. */
export function TaskLine({ children }: { children: React.ReactNode }) {
  return (
    <p className="task-line" data-testid="task-line">
      <span className="task-line-label">{tr("Tarea", "Task")}</span>
      <span className="task-line-text">{children}</span>
    </p>
  );
}

export function NotYet({ what, children }: { what: string; children?: React.ReactNode }) {
  return (
    <div className="not-yet" role="status" data-testid="not-yet">
      <strong>{tr(`${what}: no disponible todavía.`, `${what}: not available yet.`)}</strong>
      {children && <p>{children}</p>}
    </div>
  );
}
