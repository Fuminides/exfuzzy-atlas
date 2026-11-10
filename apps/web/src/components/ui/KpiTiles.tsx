import type { ReactNode } from "react";

export interface Kpi {
  key: string;
  label: ReactNode;
  value: ReactNode;
  /** Small text beside the value ("reglas", "µg/m³"). */
  unit?: ReactNode;
  /** One short line under the value. */
  note?: ReactNode;
  /** The headline figure: the same tile with a larger value. */
  accent?: boolean;
  testId?: string;
}

/** Key figures as tiles (a definition list): label, big value, optional unit and note; white Floating Product Artifacts (DESIGN.md). */
export function KpiTiles({ items, row = false }: { items: readonly Kpi[]; /** Side by side instead of stacked. */ row?: boolean }) {
  return (
    <dl className={`kpis${row ? " kpis--row" : ""}`}>
      {items.map((k) => (
        <div key={k.key} className={`kpi${k.accent ? " kpi--accent" : ""}`} data-testid={k.testId}>
          <dt>{k.label}</dt>
          <dd>
            {k.value}
            {k.unit != null && (
              <>
                {" "}
                <span className="kpi-unit">{k.unit}</span>
              </>
            )}
          </dd>
          {k.note != null && <dd className="kpi-note">{k.note}</dd>}
        </div>
      ))}
    </dl>
  );
}
