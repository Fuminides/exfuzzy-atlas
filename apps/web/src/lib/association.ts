import { tr } from "../i18n";
import { fmt, fmtFine } from "./format";

/** The three numbers of a classifier rule in a trace; nothing here is recomputed, only compared and written out. */
export interface AssociationEntry {
  rule_id: string;
  firing_strength: number;
  weight?: number | null;
  association_degree?: number | null;
}

export interface AssociationStory {
  winnerId: string;
  /** Why the winner decided: its activation, weight and association, as in the trace. */
  winner: string;
  /** The rule that fires most among the others (firing > 0) and what its weight did to its association; null if none fires. */
  loserId: string | null;
  loser: string | null;
}

const cmp = (x: number, y: number): "more" | "less" | "same" => (x > y ? "more" : x < y ? "less" : "same");

/** Rules with all three numbers; a rule the trace gives no weight for cannot be explained. */
const complete = (r: AssociationEntry): r is AssociationEntry & { weight: number; association_degree: number } =>
  r.weight != null && r.association_degree != null;

/**
 * Plain-language reading of why a rule that fires strongly can still lose: the activation (0-1) is "how much it fires",
 * the weight (dominance score) is "how much it weighs", and their product, the association, decides. The numbers are the
 * trace's own; the words (more/less, above/below) come from comparing them.
 */
export function associationStory(rules: readonly AssociationEntry[], winningId: string | null, unweighted = false): AssociationStory | null {
  const winner = rules.find((r) => r.rule_id === winningId);
  if (!winner) return null;
  if (unweighted) return unweightedStory(rules, winner);
  if (!complete(winner)) return null;
  const W = winner.rule_id;
  const beaten = rules.filter((r) => r.rule_id !== W);
  const isMax = beaten.every((r) => (r.association_degree ?? 0) < winner.association_degree);
  const wf = fmt(winner.firing_strength);
  const ww = fmtFine(winner.weight);
  const wa = fmtFine(winner.association_degree);
  const winnerText = tr(`${W} decide la categoría. Se activa con grado ${wf} y su peso es ${ww}, así que su asociación (activación × peso) es ${wa}` + (isMax ? ", la mayor de todas las reglas." : "."),
    `${W} decides the category. Its activation degree is ${wf} and its weight ${ww}, so its association (activation × weight) is ${wa}` + (isMax ? ", the highest of all the rules." : "."),
  );

  const strongest = beaten
    .filter((r) => r.firing_strength > 0 && complete(r))
    .sort((a, b) => b.firing_strength - a.firing_strength || b.association_degree! - a.association_degree! || a.rule_id.localeCompare(b.rule_id))[0];
  if (!strongest || !complete(strongest)) return { winnerId: W, winner: winnerText, loserId: null, loser: null };

  const L = strongest.rule_id;
  const full = strongest.firing_strength >= 0.9995;
  const lf = fmt(strongest.firing_strength);
  const lw = fmtFine(strongest.weight);
  const la = fmtFine(strongest.association_degree);
  const vsFiring = cmp(strongest.firing_strength, winner.firing_strength);
  const lighter = strongest.weight < winner.weight;
  const heavier = strongest.weight > winner.weight;
  const contrast = (strongest.firing_strength >= winner.firing_strength && lighter) || (strongest.firing_strength < winner.firing_strength && heavier);
  const vsWeight = cmp(strongest.weight, winner.weight);
  const vsAssoc = cmp(strongest.association_degree, winner.association_degree);
  // Each language writes its whole sentence; only the comparisons (more/less/same) are shared.
  const loser = tr(`${L} se activa ${full ? "por completo" : "con grado"} (${lf})` + (vsFiring === "same" ? `, igual que ${W} (${wf})` : `, ${vsFiring === "more" ? "más" : "menos"} que ${W} (${wf})`) + `${contrast ? ", pero" : " y"} su peso (${lw}) es ${{ more: "mayor", less: "menor", same: "igual" }[vsWeight]} que el de ${W} (${ww})` + `, así que su asociación (${la}) ${{ more: `queda por encima de la de ${W}`, less: `queda por debajo de la de ${W}`, same: `es igual a la de ${W}` }[vsAssoc]} (${wa}).`,
    `${L} fires ${full ? "fully" : "with degree"} (${lf})` +
      (vsFiring === "same" ? `, the same as ${W} (${wf})` : `, ${vsFiring === "more" ? "more" : "less"} than ${W} (${wf})`) +
      `${contrast ? ", but" : " and"} its weight (${lw}) is ${{ more: "higher than", less: "lower than", same: "the same as" }[vsWeight]} that of ${W} (${ww})` +
      `, so its association (${la}) ${{ more: `stays above that of ${W}`, less: `stays below that of ${W}`, same: `is equal to that of ${W}` }[vsAssoc]} (${wa}).`,
  );
  return { winnerId: W, winner: winnerText, loserId: L, loser };
}

/**
 * An unweighted model (`rule_weighting: "none"`): every weight is 1, so the association is the activation and the rule
 * that fires most decides. Several rules often fire fully at once; ex_fuzzy then takes the first in the model's order.
 * The rules are listed in the trace in that order.
 */
function unweightedStory(rules: readonly AssociationEntry[], winner: AssociationEntry): AssociationStory {
  const W = winner.rule_id;
  const wf = fmt(winner.firing_strength);
  const tied = rules.filter((r) => r.rule_id !== W && r.firing_strength === winner.firing_strength).map((r) => r.rule_id);
  const list = (ids: string[], and: string) => (ids.length === 1 ? ids[0]! : `${ids.slice(0, -1).join(", ")} ${and} ${ids[ids.length - 1]}`);
  const text =
    tied.length === 0
      ? tr(`${W} decide la categoría. Se activa con grado ${wf}, más que ninguna otra regla.`, `${W} decides the category. It fires with degree ${wf}, more than any other rule.`)
      : tr(`${W} decide la categoría. Se activa con grado ${wf}, igual que ${list(tied, "y")}. En este modelo las reglas no llevan peso y, ante un empate, decide la primera en el orden del modelo.`,
          `${W} decides the category. It fires with degree ${wf}, the same as ${list(tied, "and")}. This model's rules carry no weight, and on a tie, the first in the model's order decides.`,
        );
  return { winnerId: W, winner: text, loserId: null, loser: null };
}

