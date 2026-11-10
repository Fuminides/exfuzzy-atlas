import { useMemo, useState } from "react";
import { locale, tr } from "../i18n";
import type { RuleDefinition, TargetScheme } from "../api/types";
import { classColor, NO_COLOR, weightLabel, weightTitle } from "../lib/classifier";
import { fmtNum, unitLabel } from "../lib/format";
import { ruleMetrics } from "../lib/ruleMetrics";
import { ClassChip } from "./ClassChip";
import { strongestText } from "../lib/mixture";
import { condText, humanizeFeature, ruleSentence, sentenceText, useFeatureLabel, useNames } from "../lib/labels";

interface Props {
  rules: readonly RuleDefinition[];
  selectedId: string | null;
  onSelect: (ruleId: string) => void;
  /** Classifier: colours of the class consequents, and how the rule weight is called (`inference.rule_weighting`). */
  scheme?: TargetScheme | null;
  weighting?: Parameters<typeof weightTitle>[0];
}

const ALL = "";

/** Does the rule mention `query` in its id, text, a feature or a term (case-insensitive)? */
export function matchesRule(rule: RuleDefinition, query: string, label: (feature: string) => string = humanizeFeature): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return (
    rule.rule_id.toLowerCase().includes(q) ||
    rule.text.toLowerCase().includes(q) ||
    rule.antecedents.some((a) => a.feature.toLowerCase().includes(q) || label(a.feature).toLowerCase().includes(q) || a.term.toLowerCase().includes(q))
  );
}

/** Compact, searchable list of the model's rules (15–30 at real scale). Rules are never merged or reordered. */
export function RuleRail({ rules, selectedId, onSelect, scheme, weighting }: Props) {
  const label = useFeatureLabel();
  const names = useNames();
  const [query, setQuery] = useState("");
  const [feature, setFeature] = useState(ALL);
  const features = useMemo(() => [...new Set(rules.flatMap((r) => r.antecedents.map((a) => a.feature)))].sort((a, b) => label(a).localeCompare(label(b), locale())), [rules, label]);
  const shown = rules.filter((r) => matchesRule(r, query, label) && (feature === ALL || r.antecedents.some((a) => a.feature === feature)));

  return (
    <section aria-label={tr("Reglas del modelo", "The model's rules")} className="rule-rail">
      <h2>{tr("Reglas del modelo", "The model's rules")}</h2>
      <div className="rule-filters">
        <label>
          {tr("Buscar por variable o término", "Search by variable or term")}
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={tr("p. ej. viento o alta", "e.g. wind or high")} />
        </label>
        <label>
          Variable
          <select value={feature} onChange={(e) => setFeature(e.target.value)}>
            <option value={ALL}>{tr("todas", "all")}</option>
            {features.map((f) => (
              <option key={f} value={f}>
                {label(f)}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="muted" role="status">
        {tr(`${shown.length} de ${rules.length} reglas`, `${shown.length} of ${rules.length} rules`)}
      </p>
      <ul className="rule-list">
        {shown.map((r) => {
          const metrics = ruleMetrics(r).filter((m) => m.activation);
          return (
            <li key={r.rule_id}>
              <button
                type="button"
                className="rule-btn"
                aria-pressed={r.rule_id === selectedId}
                aria-label={tr(`Regla ${r.rule_id}: ${sentenceText(ruleSentence(r, label, scheme, names))}${r.duplicate_of ? ` (mismas condiciones que ${r.duplicate_of})` : ""}`, `Rule ${r.rule_id}: ${sentenceText(ruleSentence(r, label, scheme, names))}${r.duplicate_of ? ` (same conditions as ${r.duplicate_of})` : ""}`)}
                onClick={() => onSelect(r.rule_id)}
              >
                <span className="rule-id">{r.rule_id}</span>
                <span className="rule-body">
                  <span className="rule-ants">
                    {r.antecedents.map((a) => condText(a, label, names)).join(tr(" y ", " and "))}
                  </span>
                  {r.consequent.value != null && (
                    <span className="rule-then">
                      → {fmtNum(r.consequent.value)}
                      {r.consequent.unit ? ` ${unitLabel(r.consequent.unit)}` : ""}
                    </span>
                  )}
                  {r.class_weights_centred && (
                    <span className="rule-then rule-class" data-testid="rule-strongest">
                      {r.strongest_class ? (
                        <>
                          {tr("apoya sobre todo", "supports most")} <ClassChip label={r.strongest_class} color={scheme ? classColor(scheme, r.strongest_class) : NO_COLOR} />
                        </>
                      ) : (
                        strongestText(null)
                      )}
                    </span>
                  )}
                  {!r.class_weights_centred && r.consequent.type === "class" && r.consequent.term != null && (
                    <span className="rule-then rule-class">
                      →{" "}
                      <ClassChip label={r.consequent.term} color={scheme ? classColor(scheme, r.consequent.term) : NO_COLOR} />
                      {r.weight != null && weighting !== "none" && (
                        <span data-raw={String(r.weight)} title={weightTitle(weighting)}>
                          {" "}
                          · {weightLabel()} {fmtNum(r.weight)}
                        </span>
                      )}
                    </span>
                  )}
                  {r.duplicate_of && (
                    <span className="badge-dup">{tr(`mismas condiciones que ${r.duplicate_of} (dispara igual)`, `same conditions as ${r.duplicate_of} (fires the same)`)}</span>
                  )}
                  {metrics.length > 0 && (
                    <span className="rule-metrics">
                      {metrics.map((m) => `${m.label} ${m.text}`).join(" · ")}
                    </span>
                  )}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      {shown.length === 0 && <p className="muted">{tr("Ninguna regla coincide con el filtro.", "No rule matches the filter.")}</p>}
    </section>
  );
}
