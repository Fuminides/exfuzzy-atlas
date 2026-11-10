import { useRef } from "react";
import type { RuleDefinition, TargetScheme } from "../api/types";
import { tr } from "../i18n";
import { VIRIDIS } from "../lib/colorScale";
import { DIFF_DOMAIN, DIVERGING, fmtDiff, type DuelEntry } from "../lib/duel";
import { fmt, missingText } from "../lib/format";
import type { LayerOptions } from "../map/mapLayers";
import { createMapLink, StationMap } from "../map/StationMap";
import type { StationRow } from "../map/stations";
import type { DuelView } from "./DuelControls";
import { Legend } from "./Legend";
import { RuleSentenceView } from "./RuleSentenceView";
import { ruleSentence, useFeatureLabel, useNames } from "../lib/labels";

interface Props {
  view: DuelView;
  ruleA: RuleDefinition;
  ruleB: RuleDefinition;
  entries: readonly DuelEntry[];
  rowsA: readonly StationRow[];
  rowsB: readonly StationRow[];
  rowsDiff: readonly StationRow[];
  /** Activation layer shared by A and B: one scale, one palette, one emphasis threshold. */
  layerOptions: LayerOptions;
  onSelect: (entityId: string) => void;
  basemapUrl?: string;
  noun: { one: string; many: string };
  /** Name of the measure in the legend ("activación de regla (0–1)", with τ or the window when it applies). */
  measureTitle: string;
  /** Both rule maps have arrived for the same parameters; until then the maps stay neutral and the legend is hidden. */
  ready: boolean;
  /** Window / split-period / geometry notes, the same lines as the single-rule legend. */
  detail: React.ReactNode;
  /** Classifier: colours of the class chips in the rule sentences. */
  scheme?: TargetScheme | null;
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/**
 * Rule Duel (E4): rules A and B of one model on two maps with the same scale, legend, entities, instant or window and
 * tau, or one map with value(A) - value(B) on a diverging scale centred at 0. The selection is shared with the table.
 */
export function RuleDuel({ view, ruleA, ruleB, entries, rowsA, rowsB, rowsDiff, layerOptions, onSelect, basemapUrl, noun, measureTitle, detail, ready, scheme = null }: Props) {
  const label = useFeatureLabel();
  const names = useNames();
  const link = useRef(createMapLink());
  const byId = new Map(entries.map((e) => [e.entityId, e]));
  const Nouns = cap(noun.many);
  const both = entries.filter((e) => e.diff !== null).length;
  const withA = entries.filter((e) => e.a !== null).length;
  const withB = entries.filter((e) => e.b !== null).length;

  const missing = (r: StationRow) => `${tr("sin dato", "no data")}${r.missingReason ? ` · ${missingText(r.missingReason)}` : ""}`;
  const tipSide = (side: "A" | "B") => (r: StationRow) =>
    `${r.name}: ${side} = ${r.value !== null ? fmt(r.value) : missing(r)}`;
  const tipDiff = (r: StationRow) => {
    const e = byId.get(r.entityId);
    if (!e) return r.name;
    const a = e.a === null ? tr("sin dato", "no data") : fmt(e.a);
    const b = e.b === null ? tr("sin dato", "no data") : fmt(e.b);
    return `${r.name}: A − B = ${e.diff === null ? tr("sin diferencia", "no difference") : fmtDiff(e.diff)} (A = ${a}, B = ${b})`;
  };

  const diffLayer: LayerOptions = { kind: ready ? "values" : "neutral", stops: DIVERGING, domain: DIFF_DOMAIN, emphasis: null, selectedId: layerOptions.selectedId };

  // The difference map takes the place (and the map instance, so the camera stays) of pane A; B is dropped.
  const pane = (side: "A" | "B", rule: RuleDefinition, rows: readonly StationRow[]) => (
    <div className="duel-pane" data-side={side} key={side}>
      <h3>
        {side} · {tr("Regla", "Rule")} {rule.rule_id}
      </h3>
      <div className="duel-rule-text"><RuleSentenceView sentence={ruleSentence(rule, label, scheme, names)} /></div>
      <StationMap
        rows={rows}
        layerOptions={layerOptions}
        onSelect={onSelect}
        basemapUrl={basemapUrl}
        tipText={tipSide(side)}
        plural={noun.many}
        name={tr(`${side}, regla ${rule.rule_id}`, `${side}, rule ${rule.rule_id}`)}
        link={link.current}
      />
    </div>
  );

  return (
    <div className="duel" data-testid="rule-duel" data-view={view}>
      {view === "side" ? (
        <div className="duel-maps">
          {pane("A", ruleA, rowsA)}
          {pane("B", ruleB, rowsB)}
        </div>
      ) : (
        <div className="duel-maps duel-maps--single">
          <div className="duel-pane" data-side="diff" key="A">
            <h3>
              {tr(`A − B · ${ruleA.rule_id} menos ${ruleB.rule_id}`, `A − B · ${ruleA.rule_id} minus ${ruleB.rule_id}`)}
            </h3>
            <p className="muted duel-rule-text">
              {tr("Diferencia de activación (A − B).", "Activation difference (A − B).")}
            </p>
            <StationMap
              rows={rowsDiff}
              layerOptions={diffLayer}
              onSelect={onSelect}
              basemapUrl={basemapUrl}
              tipText={tipDiff}
              plural={noun.many}
              name={tr(`diferencia ${ruleA.rule_id} menos ${ruleB.rule_id}`, `difference ${ruleA.rule_id} minus ${ruleB.rule_id}`)}
            />
          </div>
        </div>
      )}
      {ready && <div className="map-legend">
        {view === "side" ? (
          <Legend
            title={tr(`${measureTitle}: A (${ruleA.rule_id}) y B (${ruleB.rule_id})`, `${measureTitle}: A (${ruleA.rule_id}) and B (${ruleB.rule_id})`)}
            note={tr("A y B comparten la escala 0–1 y la leyenda. Es el grado de activación que calcula el motor del modelo.", "A and B share the 0–1 scale and the legend. This is the activation degree computed by the model's engine.")}
            stops={VIRIDIS}
            domain={[0, 1]}
            ticks={["0", "0.25", "0.5", "0.75", "1"]}
            nValid={both}
            total={entries.length}
            missingLabel={tr("sin dato en ese lado (el motivo se indica en la tabla)", "no data on that side (the reason is in the table)")}
            countLabel={tr(<>{Nouns} con valor en A y en B</>, <>{Nouns} with a value in A and in B</>)}
            detail={
              <>
                <p className="legend-count" data-testid="duel-counts">
                  {tr(<>Con valor en A: <strong>{withA}</strong> de {entries.length} · con valor en B: <strong>{withB}</strong> de {entries.length}.</>,
                    <>With a value in A: <strong>{withA}</strong> of {entries.length} · with a value in B: <strong>{withB}</strong> of {entries.length}.</>,
                  )}
                </p>
                {detail}
              </>
            }
          />
        ) : (
          <Legend
            title={tr("diferencia de activación (A − B)", "activation difference (A − B)")}
            note={tr(`El valor de la regla A (${ruleA.rule_id}) menos el de la regla B (${ruleB.rule_id}) en cada ${noun.one}. Se restan los dos valores publicados para la misma medida, instante o ventana y τ. Naranja: A se activa más; morado: B se activa más; cerca de 0: igual. Si falta A o B, el resultado es «sin dato».`, `Rule A's value (${ruleA.rule_id}) minus rule B's (${ruleB.rule_id}) at each ${noun.one}, subtracting the two published values for the same measure, instant or window and τ. Orange: A fires more; purple: B fires more; near 0: about the same. If A or B is missing, the result is “no data”.`)}
            stops={DIVERGING}
            domain={DIFF_DOMAIN}
            ticks={["−1", "−0.5", "0", "0.5", "1"]}
            nValid={both}
            total={entries.length}
            missingLabel={tr("sin diferencia (falta A o B; el motivo se indica en la tabla)", "no difference (A or B is missing; the reason is in the table)")}
            countLabel={tr(<>{Nouns} con valor en A y en B</>, <>{Nouns} with a value in A and in B</>)}
            detail={detail}
          />
        )}
      </div>}
    </div>
  );
}
