import { useRef } from "react";
import type { RuleDefinition } from "../api/types";
import { tr } from "../i18n";
import { fmt, missingText } from "../lib/format";
import type { ColorStop } from "../lib/colorScale";
import { DIFF_DOMAIN, DIVERGING, fmtDiff, type DuelEntry } from "../lib/duel";
import { StationMarker } from "./StationMarker";

interface Props {
  entries: readonly DuelEntry[];
  selectedId: string | null;
  onSelect: (entityId: string) => void;
  ruleA: RuleDefinition;
  ruleB: RuleDefinition;
  noun: { one: string; many: string };
  stops: readonly ColorStop[];
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

function Cell({ value, reason, stops }: { value: number | null; reason: DuelEntry["missingA"]; stops: readonly ColorStop[] }) {
  if (value === null) {
    return (
      <span className="missing-text">
        <span className="marker marker--missing" aria-hidden="true" /> {tr("sin dato", "no data")}
        {reason ? ` · ${missingText(reason)}` : ""}
      </span>
    );
  }
  return (
    <>
      <StationMarker value={value} domain={[0, 1]} stops={stops} /> <span data-raw={String(value)}>{fmt(value)}</span>
    </>
  );
}

const sideMissing = (e: DuelEntry): string =>
  e.a === null && e.b === null ? tr("faltan A y B", "A and B are missing") : e.a === null ? tr("falta A", "A is missing") : tr("falta B", "B is missing");

/**
 * Accessible alternative to the two maps: A, B and A − B per entity, with the same selection as the maps. Up/Down move
 * between the entity buttons; Enter or Space selects. A missing side is "sin dato", never 0, and the difference is then
 * "sin diferencia".
 */
export function DuelTable({ entries, selectedId, onSelect, ruleA, ruleB, noun, stops }: Props) {
  const table = useRef<HTMLTableElement>(null);
  const move = (e: React.KeyboardEvent, delta: number) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const buttons = [...(table.current?.querySelectorAll<HTMLButtonElement>("tbody th button") ?? [])];
    const next = buttons[buttons.indexOf(e.currentTarget as HTMLButtonElement) + delta];
    if (next) {
      e.preventDefault();
      next.focus();
    }
  };
  return (
    <table className="stations duel-table" ref={table} aria-label={tr(`Duelo ${ruleA.rule_id} frente a ${ruleB.rule_id}`, `Duel ${ruleA.rule_id} versus ${ruleB.rule_id}`)}>
      <caption>
        {tr(`${cap(noun.many)}: ${ruleA.rule_id} frente a ${ruleB.rule_id} (alternativa textual a los mapas). A − B es la diferencia de activación. Flechas arriba/abajo para moverse; Intro para seleccionar.`,
          `${cap(noun.many)}: ${ruleA.rule_id} versus ${ruleB.rule_id} (text alternative to the maps). A − B is the activation difference. Up/down arrows to move; Enter to select.`)}
      </caption>
      <thead>
        <tr>
          <th scope="col">{cap(noun.one)}</th>
          <th scope="col">A · {ruleA.rule_id} (0–1)</th>
          <th scope="col">B · {ruleB.rule_id} (0–1)</th>
          <th scope="col">A − B</th>
          <th scope="col">n_valid (A / B)</th>
        </tr>
      </thead>
      <tbody>
        {entries.map((e) => (
          <tr key={e.entityId} aria-selected={e.entityId === selectedId} data-entity={e.entityId}>
            <th scope="row">
              <button
                type="button"
                onClick={() => onSelect(e.entityId)}
                aria-pressed={e.entityId === selectedId}
                onKeyDown={(ev) => move(ev, ev.key === "ArrowDown" ? 1 : -1)}
              >
                {e.name}
              </button>
            </th>
            <td data-side="a" data-missing={e.a === null}>
              <Cell value={e.a} reason={e.missingA} stops={stops} />
            </td>
            <td data-side="b" data-missing={e.b === null}>
              <Cell value={e.b} reason={e.missingB} stops={stops} />
            </td>
            <td data-side="diff" data-missing={e.diff === null}>
              {e.diff === null ? (
                <span className="missing-text">{tr(`sin diferencia (${sideMissing(e)})`, `no difference (${sideMissing(e)})`)}</span>
              ) : (
                <>
                  <StationMarker value={e.diff} domain={DIFF_DOMAIN} stops={DIVERGING} />{" "}
                  <span data-raw={String(e.diff)}>{fmtDiff(e.diff)}</span>
                </>
              )}
            </td>
            <td>
              {e.nValidA ?? "—"} / {e.nValidB ?? "—"}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
