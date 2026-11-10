import { tr } from "../i18n";
import type { ColorStop } from "../lib/colorScale";
import { NO_COLOR } from "../lib/classifier";
import { fmt, missingText, neverPredictedText } from "../lib/format";
import type { StationRow } from "../map/stations";
import { ClassChip } from "./ClassChip";
import { StationMarker } from "./StationMarker";

interface Props {
  rows: readonly StationRow[];
  selectedId: string | null;
  onSelect: (entityId: string) => void;
  stops: readonly ColorStop[];
  domain: readonly [number, number];
  /** Omit for views without a value column (Data placeholder). */
  valueHeader?: string;
  /** Formats a present value (null never reaches it). */
  formatValue?: (v: number) => string;
  /** "sqrt": the colour scale is on the square root of the value (Data mode, counts); the swatch follows it. */
  scale?: "linear" | "sqrt";
  /** What a row without a label is called ("sin predicción" by default; "sin regla dominante" in Rule Territories). */
  missingWord?: string;
  showNValid: boolean;
  /** Classifier prediction: colour of each class label. The value column then shows the label chip. */
  classColors?: ReadonlyMap<string, string>;
  /** What the rows are called ("estación", "zona de taxi"...); the default is the Madrid wording. */
  noun?: { one: string; many: string };
  /** One more column after the value (e.g. the sample date of a Water point). */
  extra?: { header: string; cell: (row: StationRow) => React.ReactNode };
  /** Prediction mode: the rule that decided each prediction (its own column, after the value). */
  decided?: (row: StationRow) => React.ReactNode;
  /** Header of that column ("Regla que decidió" by default; a mixture names the rule that adds the most). */
  decidedHeader?: string;
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** Keyboard-navigable alternative to the map: same stations, same selection. */
export function StationTable({
  rows,
  selectedId,
  onSelect,
  stops,
  domain,
  valueHeader,
  formatValue = fmt,
  scale = "linear",
  missingWord: missingWordProp,
  showNValid,
  classColors,
  noun: nounProp,
  extra,
  decided,
  decidedHeader,
}: Props) {
  const missingWord = missingWordProp ?? tr("sin predicción", "no prediction");
  const noun = nounProp ?? { one: tr("estación", "station"), many: tr("estaciones", "stations") };
  return (
    <table className="stations">
      <caption>{tr(`${cap(noun.many)} (alternativa textual al mapa)`, `${cap(noun.many)} (text alternative to the map)`)}</caption>
      <thead>
        <tr>
          <th scope="col">{cap(noun.one)}</th>
          {valueHeader && <th scope="col">{valueHeader}</th>}
          {decided && <th scope="col">{decidedHeader ?? tr("Regla que decidió", "Rule that decided")}</th>}
          {showNValid && <th scope="col" title="n_valid">{tr("Registros válidos", "Valid records")}</th>}
          {extra && <th scope="col">{extra.header}</th>}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.entityId} aria-selected={r.entityId === selectedId} data-entity={r.entityId}>
            <th scope="row">
              <button type="button" onClick={() => onSelect(r.entityId)} aria-pressed={r.entityId === selectedId}>
                {r.name}
              </button>
              {r.geometry === null && <span className="muted no-geom">{tr(" · sin geometría (no se dibuja en el mapa)", " · no geometry (not drawn on the map)")}</span>}
            </th>
            {valueHeader && classColors && (
              <td data-missing={!r.label} data-class={r.label ?? undefined}>
                {r.label ? (
                  <ClassChip label={r.label} color={classColors.get(r.label) ?? NO_COLOR} />
                ) : (
                  <>
                    <span className={`marker ${r.noReference ? "marker--noref" : r.noPredictions ? "marker--unmodelled" : "marker--missing"}`} aria-hidden="true" />{" "}
                    <span className="missing-text" data-no-reference={r.noReference ? "true" : undefined} data-no-predictions={r.noPredictions ? "true" : undefined}>
                      {r.noPredictions ? neverPredictedText() : r.missingReason === "not_modelled" ? tr("sin modelo", "not modelled") : r.noReference ? tr("sin referencia", "no reference") : missingWord}
                      {r.missingReason && r.missingReason !== "not_modelled" && !r.noReference && !r.noPredictions ? ` · ${missingText(r.missingReason)}` : ""}
                    </span>
                  </>
                )}
              </td>
            )}
            {valueHeader && !classColors && (
              <td data-missing={r.value === null}>
                <StationMarker value={r.value} domain={domain} stops={stops} scale={scale} />{" "}
                {r.value === null ? (
                  <span className="missing-text">
                    {r.missingReason === "not_modelled" ? tr("sin modelo", "not modelled") : `${tr("sin dato", "no data")}${r.missingReason ? ` · ${missingText(r.missingReason)}` : ""}`}
                  </span>
                ) : (
                  <span data-raw={String(r.value)}>{formatValue(r.value)}</span>
                )}
              </td>
            )}
            {decided && <td>{r.decidedBy ? decided(r) : <span className="muted">—</span>}</td>}
            {showNValid && <td>{r.nValid ?? "—"}</td>}
            {extra && <td>{extra.cell(r)}</td>}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
