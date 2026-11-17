import { useId } from "react";
import type { ModelRules, MontageChannel, MontageResponse } from "../api/types";
import { localized, tr } from "../i18n";
import { dec, fmt } from "../lib/format";
import { convexHull, proximityGroups, wedgePath, type Point } from "./geometry";

/** What a channel shows: a signal value (data view) or the membership of a rule's condition (rule view). */
export interface ChannelMark {
  /** Diverging bin -4..4 (data view) or sequential bin 0..4 (rule view); null: the channel is not part of the view. */
  bin: number | null;
  /** The line under the channel name in the tooltip: the value, or the condition and its membership. */
  detail: string;
  /** Rule view: the signal(s) the condition reads at this channel ("HbR"), drawn next to the channel. */
  tag?: string;
  /** A fill that overrides the bin's (data view: the blood scale; rule tiles: the signal's colour). */
  fill?: string;
}

/**
 * The data view's colour (blood): red towards oxygenated, blue towards deoxygenated. An increase of HbO is red and its
 * decrease blue; an increase of HbR is blue and its decrease red. `bin` is the signed diverging bin of the change.
 */
export function bloodFill(bin: number, signal: string): string {
  if (bin === 0) return "var(--div-mid)";
  const oxygenated = signal === "HbO" ? bin > 0 : bin < 0;
  return `var(--${oxygenated ? "oxy" : "deoxy"}-${Math.min(4, Math.abs(bin))})`;
}

/** The identity colour of a signal: HbO red, HbR blue. */
export const signalColor = (signal: string): string => (signal === "HbO" ? "var(--hbo)" : signal === "HbR" ? "var(--hbr)" : "var(--sienna)");

/** Fill of a bin: the diverging pair of DESIGN.md (Sienna arm = increase, slate-blue arm = decrease, grey midpoint). */
export const binFill = (bin: number): string =>
  bin === 0 ? "var(--div-mid)" : bin > 0 ? `var(--div-pos-${Math.min(4, bin)})` : `var(--div-neg-${Math.min(4, -bin)})`;

/** A value in [-bound, bound] as a diverging bin: 0 within an eighth of the bound, then 1..4 by quarters. */
export function divergingBin(value: number, bound: number): number {
  if (!(bound > 0)) return 0;
  const t = Math.min(1, Math.abs(value) / bound);
  const step = t < 0.125 ? 0 : t < 0.375 ? 1 : t < 0.625 ? 2 : t < 0.875 ? 3 : 4;
  return step === 0 ? 0 : Math.sign(value) * step;
}

/** A membership in [0, 1] as a sequential bin on the Sienna arm: 0 for 0, then 1..4 by quarters. */
export const membershipBin = (mu: number): number => (mu <= 0 ? 0 : Math.min(4, Math.ceil(mu * 4)));

const R = 0.07; // channel radius, in head units (the ear plane is the unit circle)

/** One rule at a channel of the rule-base overview: a wedge in the colour of the class it supports most. */
export interface Wedge {
  ruleId: string;
  color: string;
  text: string;
}

/**
 * The rule-base overview: at each channel a rule reads, one wedge per rule (Reglas › Dónde miran las reglas, and the
 * landing's scalp card). `color` and `text` say how each rule is shown at a channel.
 */
export function ruleWedges(
  rules: ModelRules,
  montage: MontageResponse,
  color: (rule: ModelRules["rules"][number]) => string,
  text: (rule: ModelRules["rules"][number], condition: ModelRules["rules"][number]["antecedents"][number]) => string,
): Map<string, Wedge[]> {
  const where = new Map(montage.channels.flatMap((c) => c.inputs.map((i) => [i.feature, c.channel_id] as const)));
  const wedges = new Map<string, Wedge[]>();
  for (const r of rules.rules) {
    for (const a of r.antecedents) {
      const channel = where.get(a.feature);
      if (!channel) continue;
      const list = wedges.get(channel) ?? [];
      if (!list.some((x) => x.ruleId === r.rule_id)) list.push({ ruleId: r.rule_id, color: color(r), text: text(r, a) });
      wedges.set(channel, list);
    }
  }
  return wedges;
}

interface Props {
  channels: readonly MontageChannel[];
  label: string;
  /** Canales: what each channel shows (value or membership). */
  marks?: ReadonlyMap<string, ChannelMark>;
  /** Reglas: the rules that read each channel, one wedge each. */
  wedges?: ReadonlyMap<string, readonly Wedge[]>;
  /** Channels any rule uses: outlined, so the reader sees where the model looks. */
  usedByRules?: ReadonlySet<string>;
  /** A small multiple (rule cards): no names, no orientation labels. */
  mini?: boolean;
  testId?: string;
}

/** The head: soft fill, outline, nose, ears and the two guide lines (front-back and ear to ear). */
function Head({ id, mini }: { id: string; mini: boolean }) {
  return (
    <g className="scalp-head" aria-hidden="true">
      <defs>
        <radialGradient id={id} cx="50%" cy="42%" r="58%">
          <stop offset="0%" stopColor="#ffffff" />
          <stop offset="100%" stopColor="#f1ece6" />
        </radialGradient>
      </defs>
      <path className="scalp-ear" d="M -1.09 -0.18 C -1.22 -0.14 -1.22 0.14 -1.09 0.18" />
      <path className="scalp-ear" d="M 1.09 -0.18 C 1.22 -0.14 1.22 0.14 1.09 0.18" />
      <path className="scalp-nose" d="M -0.13 -1.075 L 0 -1.23 L 0.13 -1.075" />
      <circle className="scalp-skull" r={1.09} fill={`url(#${id})`} />
      {!mini && (
        <>
          <line className="scalp-guide" x1={0} y1={-1.09} x2={0} y2={1.09} />
          <line className="scalp-guide" x1={-1.09} y1={0} x2={1.09} y2={0} />
        </>
      )}
    </g>
  );
}

/**
 * The NIRS channels where the source places them (contract v0.9: `xy` is the azimuthal projection of the published
 * `xyz`; nose up, right ear to the right). The patches behind them group channels by proximity (the six areas of the
 * montage) and carry no value: nothing is drawn as a surface between channels.
 */
export function ScalpMap({ channels, label, marks, wedges, usedByRules, mini = false, testId = "scalp" }: Props) {
  const gradient = useId().replace(/:/g, "");
  const groups = proximityGroups(channels.map((c) => ({ ...c, xy: c.xy as unknown as Point })));
  const named = channels.filter((c) => marks?.get(c.channel_id)?.tag || (wedges?.get(c.channel_id)?.length ?? 0) > 0);
  return (
    <svg className={`scalp${mini ? " scalp--mini" : ""}`} viewBox={mini ? "-1.32 -1.3 2.64 2.62" : "-2.2 -1.3 4.4 2.62"} role="img" aria-label={label} data-testid={testId}>
      <Head id={`head${gradient}`} mini={mini} />
      <g className="scalp-areas" aria-hidden="true">
        {groups.map((g) => {
          const hull = convexHull(g.map((c) => [c.xy[0], -c.xy[1]] as Point));
          return <path key={g[0]!.channel_id} d={`M ${hull.map(([x, y]) => `${x.toFixed(4)} ${y.toFixed(4)}`).join(" L ")} Z`} />;
        })}
      </g>
      {!mini && (
        <g className="scalp-orient" aria-hidden="true">
          <text x={-1.25} y={0.33}>{tr("Izq.", "L")}</text>
          <text x={1.25} y={0.33}>{tr("Der.", "R")}</text>
        </g>
      )}
      {channels.map((c) => {
        const [x, y] = c.xy as unknown as [number, number];
        const mark = marks?.get(c.channel_id);
        const pie = wedges?.get(c.channel_id) ?? [];
        const active = (mark && mark.bin !== null) || pie.length > 0;
        const region = localized(c.region ?? null, c.region_en ?? null);
        const title = [
          c.channel_id,
          region ? tr(`${region} (región aproximada${c.brodmann ? `, ${c.brodmann}` : ""})`, `${region} (approximate region${c.brodmann ? `, ${c.brodmann}` : ""})`) : null,
          mark?.detail ?? null,
          ...pie.map((w) => w.text),
        ].filter(Boolean).join("\n");
        return (
          <g
            key={c.channel_id}
            className={`scalp-ch${active ? " scalp-ch--on" : ""}${usedByRules?.has(c.channel_id) ? " scalp-ch--used" : ""}`}
            data-channel={c.channel_id}
            data-bin={mark && mark.bin !== null ? mark.bin : undefined}
            data-rules={pie.length ? pie.map((w) => w.ruleId).join(" ") : undefined}
            transform={`translate(${x} ${-y})`}
          >
            <title>{title}</title>
            {pie.length > 0 ? (
              <>
                {pie.map((w, i) => <path key={w.ruleId} d={wedgePath(i, pie.length, R * 1.25)} style={{ fill: w.color }} />)}
                <circle className="scalp-pie-ring" r={R * 1.25} />
              </>
            ) : (
              /* in `style`: a `fill` attribute would lose to the stylesheet's default */
              <circle r={active ? R : R * 0.6} style={mark && mark.bin !== null ? { fill: mark.fill ?? binFill(mark.bin) } : undefined} />
            )}
          </g>
        );
      })}
      {/* names last and outside the head, with a leader line each, so no channel or name covers another */}
      {!mini && <Callouts items={named.map((c) => {
        const [x, y] = c.xy as unknown as [number, number];
        const pie = wedges?.get(c.channel_id) ?? [];
        return { id: c.channel_id, x, y: -y, text: pie.length ? `${c.channel_id} · ${pie.map((w) => w.ruleId).join(" ")}` : `${c.channel_id} · `, signals: pie.length ? "" : marks!.get(c.channel_id)!.tag ?? "" };
      })} />}
    </svg>
  );
}

const GAP = 0.12; // vertical room per callout, in head units
const TOP = -1.2;
const BOTTOM = 1.25;

/** Labels in two columns beside the head (left channels to the left), spread so none overlaps, each tied to its channel. */
function Callouts({ items }: { items: readonly { id: string; x: number; y: number; text: string; signals?: string }[] }) {
  const placed: { id: string; x: number; y: number; text: string; signals?: string; side: 1 | -1; ly: number }[] = [];
  for (const side of [-1, 1] as const) {
    const col = items.filter((it) => (side === -1 ? it.x < -0.02 : it.x >= -0.02)).sort((a, b) => a.y - b.y);
    const ys = col.map((it) => it.y);
    for (let k = 0; k < ys.length; k++) ys[k] = Math.max(ys[k]!, k ? ys[k - 1]! + GAP : TOP);
    for (let k = ys.length - 1; k >= 0; k--) ys[k] = Math.min(ys[k]!, k < ys.length - 1 ? ys[k + 1]! - GAP : BOTTOM);
    col.forEach((it, k) => placed.push({ ...it, side, ly: ys[k]! }));
  }
  return (
    <g className="scalp-callouts" aria-hidden="true">
      {placed.map((p) => (
        <g key={p.id}>
          <polyline points={`${p.x},${p.y} ${p.side * 1.2},${p.ly} ${p.side * 1.36},${p.ly}`} />
          <text x={p.side * 1.4} y={p.ly + 0.025} textAnchor={p.side === -1 ? "end" : "start"}>
            {p.text}
            {(p.signals ?? "").split("+").filter(Boolean).map((sig, i) => (
              <tspan key={sig} className={`sig-${sig}`}>{i > 0 ? "+" : ""}{sig}</tspan>
            ))}
          </text>
        </g>
      ))}
    </g>
  );
}

/** The bins of the data view (inputs are in mmol/L; shown in µmol/L), on the blood scale of the signal shown. */
export function DivergingLegend({ bound, signal }: { bound: number; signal: string }) {
  const bins = [-4, -3, -2, -1, 0, 1, 2, 3, 4];
  const top = dec(bound * 1000, 2);
  return (
    <div className="scalp-legend" data-testid="scalp-legend">
      <div className="scalp-legend-bins" aria-hidden="true">
        {bins.map((b) => (
          <span key={b} style={{ background: bloodFill(b, signal) }} />
        ))}
      </div>
      <div className="scalp-legend-axis muted small">
        <span>−{top}</span>
        <span>0</span>
        <span>+{top} µmol/L</span>
      </div>
      <p className="muted small">
        {signal === "HbO"
          ? tr(`Cambio de oxihemoglobina respecto a la línea base del bloque: rojo si sube (más sangre oxigenada), azul si baja. La escala llega hasta ${top} µmol/L, el mayor cambio de este ensayo en valor absoluto, y cada tono abarca una cuarta parte.`, `Change of oxyhaemoglobin from the block's baseline: red where it rises (more oxygenated blood), blue where it falls. The scale goes up to ${top} µmol/L, this trial's largest change in absolute value, and each shade spans a quarter of it.`)
          : tr(`Cambio de desoxihemoglobina respecto a la línea base del bloque: azul si sube (más sangre desoxigenada), rojo si baja. La escala llega hasta ${top} µmol/L, el mayor cambio de este ensayo en valor absoluto, y cada tono abarca una cuarta parte.`, `Change of deoxyhaemoglobin from the block's baseline: blue where it rises (more deoxygenated blood), red where it falls. The scale goes up to ${top} µmol/L, this trial's largest change in absolute value, and each shade spans a quarter of it.`)}
      </p>
    </div>
  );
}

/** The bins of the rule view: how much each condition of the rule holds in this trial. */
export function MembershipLegend() {
  return (
    <div className="scalp-legend" data-testid="scalp-legend">
      <div className="scalp-legend-bins scalp-legend-bins--seq" aria-hidden="true">
        {[0, 1, 2, 3, 4].map((b) => (
          <span key={b} style={{ background: binFill(b) }} />
        ))}
      </div>
      <div className="scalp-legend-axis muted small">
        <span>0</span>
        <span>{fmt(0.5)}</span>
        <span>1</span>
      </div>
      <p className="muted small">
        {tr("Grado en que se cumple cada condición de la regla en este ensayo (pertenencia, de 0 a 1). Los canales con borde los usa alguna otra regla.",
          "How much each condition of the rule holds in this trial (membership, 0 to 1). Outlined channels are used by some other rule.",
        )}
      </p>
    </div>
  );
}
