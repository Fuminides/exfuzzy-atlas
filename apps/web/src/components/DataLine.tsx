import type { SummaryResponse } from "../api/types";
import { count, distributionText, isClassified, lcFirst, quantileText, stationsWithData, totalRow, yearsText } from "../lib/summary";
import { unitLabel } from "../lib/format";
import { localized, tr } from "../i18n";

/**
 * One slim line of data context above the rules: what is observed, where, when, and how it is spread, with a link to
 * Resumen. Small on purpose: the rules are the focus of Patrones. Omitted by the caller when the summary is not published (404).
 */
export function DataLine({ summary, noun, onOpenSummary }: { summary: SummaryResponse; noun: { one: string; many: string }; onOpenSummary?: () => void }) {
  const all = totalRow(summary);
  const n = stationsWithData(summary).length;
  const spread = !all ? "" : isClassified(summary) && all.shares ? distributionText(summary.classes!, all.shares) : quantileText(all.quantiles, unitLabel(summary.unit));
  return (
    <p className="data-line muted small" data-testid="data-line">
      <span>
        {tr("Datos: ", "Data: ")}
        {lcFirst(localized(summary.label, summary.label_en))}, {count(n)} {n === 1 ? noun.one : noun.many}, {yearsText(summary)}
        {spread ? ` · ${spread}` : ""}
      </span>
      {onOpenSummary && (
        <>
          {" "}
          <button type="button" className="link link--go" onClick={onOpenSummary}>
            {tr(<>Ver el <em>resumen de los datos</em></>, <>See the <em>data summary</em></>)}
          </button>
        </>
      )}
    </p>
  );
}
