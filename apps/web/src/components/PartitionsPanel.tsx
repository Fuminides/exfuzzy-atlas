import type { LinguisticTerm, LinguisticVariable, RuleTrace } from "../api/types";
import { tr } from "../i18n";
import { boundedSumPoints, condKey, isExtra, termsOf, type CondSpec } from "../lib/conditions";
import { fmt, fmtNum, unitLabel } from "../lib/format";
import { useFeatureLabel, useNames } from "../lib/labels";

interface Props {
  variable: LinguisticVariable;
  /** Term the selected rule uses for this variable, drawn thicker. */
  ruleTerm: string | null;
  /** v0.8: the ordinal and compound conditions some rule of the model uses on this variable (drawn as the bounded sum of their terms). */
  conditions?: readonly CondSpec[];
  /** v0.8: the selected rule's condition on this variable when it is one of those, drawn thicker. */
  ruleCondition?: CondSpec | null;
  ruleId: string | null;
  /** Variables of the selected rule, to switch between them. */
  siblings: readonly string[];
  onVariable: (feature: string) => void;
  onClose: () => void;
  /** Trace of the selected station at the selected issue time, if any. */
  trace: RuleTrace | null;
  stationName: string | null;
}

const W = 380;
const H = 180;
const M = { l: 30, r: 12, t: 14, b: 26 };
/** Categorical colours for terms; each term is also labelled on the plot and in the table. */
export const COLORS = ["#1d4ed8", "#c2410c", "#047857", "#7e22ce", "#a16207", "#be123c"];

/** The four params of a trapezoidal/triangular term are its vertices: (a,0) (b,1) (c,1) (d,0). */
export const vertices = (p: readonly number[]): [number, number][] => [
  [p[0]!, 0],
  [p[1]!, 1],
  [p[2]!, 1],
  [p[3]!, 0],
];
export const isDrawn = (t: LinguisticTerm) => t.membership_type !== "gaussian" && t.params.length === 4;

/**
 * Linguistic terms of one variable. Trapezoidal/triangular terms are drawn as the polyline of their params (placed on
 * the axis, nothing else); gaussian terms are listed. The input value of the selected station and every μ come from
 * the rule trace (the engine's numbers); the client computes no membership. The only shape computed here is the dashed line
 * of an ordinal or compound condition (v0.8): the sum of the memberships of the terms it covers, capped at 1, drawn from
 * the terms' published parameters.
 */
export function PartitionsPanel({ variable, ruleTerm, conditions = [], ruleCondition = null, ruleId, siblings, onVariable, onClose, trace, stationName }: Props) {
  const label = useFeatureLabel();
  const names = useNames();
  const drawn = variable.terms.filter(isDrawn);
  const dom = variable.domain as [number, number] | null | undefined;
  const allX = drawn.flatMap((t) => t.params);
  const lo = dom ? dom[0] : allX.length ? Math.min(...allX) : 0;
  const hi = dom ? dom[1] : allX.length ? Math.max(...allX) : lo + 1;
  const X = (v: number) => M.l + ((Math.min(hi, Math.max(lo, v)) - lo) / (hi - lo || 1)) * (W - M.l - M.r);
  const Y = (m: number) => H - M.b - m * (H - M.t - M.b);

  const input = trace?.feature_values.find((f) => f.feature === variable.feature) ?? null;
  const value = input?.value ?? null;
  // Memberships of this variable's terms that the trace carries (those some rule uses); never computed here.
  const mu = new Map<string, number>();
  const muCond = new Map<string, number>();
  for (const r of trace?.rules ?? []) for (const a of r.antecedents) if (a.feature === variable.feature) (isExtra(a) ? muCond : mu).set(condKey(a), a.membership);
  const shapes = conditions.map((c, i) => {
    const pts = boundedSumPoints(variable.terms.filter((t) => termsOf(c).includes(t.name)), lo, hi);
    const top = pts.filter(([, m]) => m >= 1).map(([x]) => x);
    return { c, key: condKey(c), pts, at: top.length ? (Math.min(...top) + Math.max(...top)) / 2 : (lo + hi) / 2, row: i };
  });
  const ruleKey = ruleCondition && isExtra(ruleCondition) ? condKey(ruleCondition) : null;
  const outside = value !== null && (value < lo || value > hi);
  const unit = variable.unit ? unitLabel(variable.unit) : "";
  const colorOf = (i: number) => COLORS[i % COLORS.length]!;

  return (
    <section className="partitions" aria-label={tr("Particiones lingüísticas", "Linguistic partitions")}>
      <div className="partitions-head">
        <h2>
          {tr("Particiones: ", "Partitions: ")}
          {label(variable.feature)}
          {unit && <span className="muted"> ({unit})</span>}
        </h2>
        <button type="button" onClick={onClose} aria-label={tr("Cerrar particiones lingüísticas", "Close linguistic partitions")}>
          {tr("Cerrar", "Close")}
        </button>
      </div>
      {siblings.length > 1 && (
        <div className="partitions-vars" role="group" aria-label={tr(`Variables de la regla ${ruleId}`, `Variables of rule ${ruleId}`)}>
          {siblings.map((f) => (
            <button key={f} type="button" aria-pressed={f === variable.feature} onClick={() => onVariable(f)}>
              {label(f)}
            </button>
          ))}
        </div>
      )}
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={tr(`Términos de ${label(variable.feature)} sobre su dominio [${fmtNum(lo)}, ${fmtNum(hi)}]`, `Terms of ${label(variable.feature)} over its domain [${fmtNum(lo)}, ${fmtNum(hi)}]`)}>
        <line x1={M.l} x2={W - M.r} y1={Y(0)} y2={Y(0)} className="axis-line" />
        <line x1={M.l} x2={M.l} y1={Y(1)} y2={Y(0)} className="axis-line" />
        <text x={M.l - 4} y={Y(1) + 4} textAnchor="end" className="axis">1</text>
        <text x={M.l - 4} y={Y(0)} textAnchor="end" className="axis">0</text>
        <text x={M.l} y={H - 4} textAnchor="start" className="axis">{fmtNum(lo)}</text>
        <text x={W - M.r} y={H - 4} textAnchor="end" className="axis">{fmtNum(hi)}</text>
        {variable.terms.map((t, i) => {
          if (!isDrawn(t)) return null;
          const vs = vertices(t.params);
          return (
            <g key={t.name}>
              <polyline
                className={t.name === ruleTerm ? "term term--rule" : "term"}
                style={{ stroke: colorOf(i) }}
                points={vs.map(([x, m]) => `${X(x)},${Y(m)}`).join(" ")}
                data-term={t.name}
                data-vertices={JSON.stringify(vs)}
              />
              <text x={X((t.params[1]! + t.params[2]!) / 2)} y={Y(1) - 3} textAnchor="middle" className="axis" style={{ fill: colorOf(i), fontStyle: "italic" }}>
                {names.term(variable.feature, t.name)}
              </text>
            </g>
          );
        })}
        {shapes.map(({ c, key, pts, at, row }) => (
          <g key={key} data-condition={key}>
            <polyline className={key === ruleKey ? "term term--sum term--rule" : "term term--sum"} points={pts.map(([x, m]) => `${X(x)},${Y(m)}`).join(" ")} />
            <text x={X(at)} y={Y(1) + 11 + row * 10} textAnchor="middle" className="axis sum-label">{names.label(variable.feature, c)}</text>
          </g>
        ))}
        {value !== null && (
          <g data-testid="input-marker" data-value={String(value)}>
            <line x1={X(value)} x2={X(value)} y1={Y(1)} y2={Y(0)} className="input-line" />
            <text x={X(value)} y={H - M.b + 13} textAnchor="middle" className="axis input-text">{fmtNum(value)}</text>
            {variable.terms.map((t, i) => {
              const m = mu.get(t.name);
              return m === undefined || !isDrawn(t) ? null : (
                <circle key={t.name} cx={X(value)} cy={Y(m)} r={4} data-mu={String(m)} data-term={t.name} style={{ fill: colorOf(i) }} />
              );
            })}
            {shapes.map(({ key }) => {
              const m = muCond.get(key);
              return m === undefined ? null : <circle key={key} cx={X(value)} cy={Y(m)} r={4} data-mu={String(m)} data-condition={key} style={{ fill: "var(--ink)" }} />;
            })}
          </g>
        )}
      </svg>
      {shapes.length > 0 && (
        <p className="muted" data-testid="partition-conditions">
          {tr("La línea discontinua suma las pertenencias de los términos que cubre cada condición, con tope en 1.", "The dashed line adds up the memberships of the terms each condition covers, capped at 1.")}
        </p>
      )}
      <p className="muted">
        {value === null
          ? trace
            ? tr("A la traza le falta la entrada de esta estación, así que no se marca ningún valor.", "This station's input is missing from the trace, so no value is marked.")
            : tr("Elige una estación para marcar su valor de entrada y las μ de la traza.", "Choose a station to mark its input value and the trace's μ.")
          : tr(
              `Entrada de ${stationName ?? trace?.entity_id}: ${fmtNum(value)}${unit ? ` ${unit}` : ""}. Las μ marcadas vienen de la traza del motor.`,
              `Input of ${stationName ?? trace?.entity_id}: ${fmtNum(value)}${unit ? ` ${unit}` : ""}. The marked μ come from the engine's trace.`,
            )}
        {outside && tr(" El valor queda fuera del dominio. ex_fuzzy lo recorta al extremo más cercano, y ahí se marca.", " The value is outside the domain. ex_fuzzy clips it to the nearest end, which is where it's marked.")}
      </p>
      <table className="plain">
        <caption>{tr(`Términos y parámetros (dominio [${fmtNum(lo)}, ${fmtNum(hi)}])`, `Terms and parameters (domain [${fmtNum(lo)}, ${fmtNum(hi)}])`)}</caption>
        <thead>
          <tr>
            <th scope="col">{tr("Término", "Term")}</th>
            <th scope="col">{tr("Tipo", "Type")}</th>
            <th scope="col">{tr("Parámetros", "Parameters")}</th>
            <th scope="col">{tr("μ (traza)", "μ (trace)")}</th>
          </tr>
        </thead>
        <tbody>
          {variable.terms.map((t, i) => (
            <tr key={t.name} data-term={t.name} aria-current={t.name === ruleTerm ? "true" : undefined}>
              <th scope="row">
                <span className="swatch" style={{ background: isDrawn(t) ? colorOf(i) : "transparent", borderColor: colorOf(i) }} aria-hidden="true" />{" "}
                <em className="term-phrase">{names.phrase(variable.feature, t.name)}</em>
                {t.name === ruleTerm && <span className="muted">{tr(` · usado por ${ruleId}`, ` · used by ${ruleId}`)}</span>}
              </th>
              <td>{t.membership_type}</td>
              <td>
                <code title={`[${t.params.join(", ")}]`}>[{t.params.map(fmtNum).join(", ")}]</code>
                {t.membership_type === "gaussian" && <span className="muted">{tr(" [media, desv.]; no se dibuja", " [mean, sd]; not drawn")}</span>}
              </td>
              <td>
                {mu.has(t.name) && value !== null ? (
                  <span data-raw={String(mu.get(t.name))}>{fmt(mu.get(t.name)!)}</span>
                ) : (
                  <span className="muted">
                    {!trace ? "—" : value === null ? tr("sin entrada", "no input") : tr("ninguna regla usa este término", "no rule uses this term")}
                  </span>
                )}
              </td>
            </tr>
          ))}
          {shapes.map(({ c, key }) => (
            <tr key={key} data-condition={key} aria-current={key === ruleKey ? "true" : undefined}>
              <th scope="row">
                <span className="swatch" style={{ background: "transparent", borderColor: "var(--ink)", borderStyle: "dashed" }} aria-hidden="true" />{" "}
                <em className="term-phrase">{names.label(variable.feature, c)}</em>
                {key === ruleKey && <span className="muted">{tr(` · usado por ${ruleId}`, ` · used by ${ruleId}`)}</span>}
              </th>
              <td>{tr("suma acotada", "bounded sum")}</td>
              <td>{names.detail(variable.feature, c) ?? termsOf(c).map((n) => names.term(variable.feature, n)).join(", ")}</td>
              <td>
                {muCond.has(key) && value !== null ? (
                  <span data-raw={String(muCond.get(key))}>{fmt(muCond.get(key)!)}</span>
                ) : (
                  <span className="muted">{!trace ? "—" : value === null ? tr("sin entrada", "no input") : tr("ninguna regla usa este término", "no rule uses this term")}</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
