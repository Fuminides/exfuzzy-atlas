import type { ReactNode } from "react";

interface HeroProps {
  /** Accessible name of the band (a region). */
  label: string;
  /** Small line above the headline: where, which horizon, which period. */
  eyebrow?: ReactNode;
  /** The one sentence that matters on the page, as an h2; mark its key figure with <HeroAccent>. Without one the hero is its eyebrow, the chips and the aside. */
  headline?: ReactNode;
  headlineTestId?: string;
  /** One plain sentence under the headline. */
  verdict?: ReactNode;
  /** Under the verdict: chips, a line of facts, a disclosure. */
  children?: ReactNode;
  /** The right column: KPI tiles or a light panel. */
  aside?: ReactNode;
  /** A shorter band for the tabs whose map comes right after it. */
  compact?: boolean;
  testId?: string;
}

/** The figure a headline turns on, set in the italic serif (DESIGN.md: one italicized phrase). */
export function HeroAccent({ children }: { children: ReactNode }) {
  return <span className="hero-accent">{children}</span>;
}

/**
 * The editorial hero at the top of a tab (DESIGN.md): on the white canvas, an eyebrow, a serif headline with one italic
 * figure, a one-sentence verdict in Slate, quiet chips and, on the right, KPI tiles floating as product artifacts. It only
 * lays out what it is given: every figure comes from the page's own data.
 */
export function Hero({ label, eyebrow, headline, headlineTestId, verdict, children, aside, compact = false, testId }: HeroProps) {
  return (
    <section className={`hero${compact ? " hero--compact" : ""}${aside ? "" : " hero--single"}`} aria-label={label} data-testid={testId}>
      <div className="hero-text">
        {eyebrow && <p className="hero-eyebrow">{eyebrow}</p>}
        {headline && (
          <h2 className="hero-headline" data-testid={headlineTestId}>
            {headline}
          </h2>
        )}
        {verdict && <p className="hero-verdict">{verdict}</p>}
        {children}
      </div>
      {aside && <div className="hero-aside">{aside}</div>}
    </section>
  );
}
