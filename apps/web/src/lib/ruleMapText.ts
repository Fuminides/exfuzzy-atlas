import type { RuleMapMetric } from "../api/types";
import { tr } from "../i18n";
import { dec } from "./format";

/** Labels of the three map metrics; getters, so each read follows the current language. */
export const VIEW_LABEL: Record<RuleMapMetric, string> = {
  get firing_strength() { return tr("Instante de emisión", "Issue instant"); },
  get mean_activation() { return tr("Media en la ventana", "Mean over the window"); },
  get activation_frequency() { return tr("Frecuencia ≥ τ en la ventana", "Frequency ≥ τ over the window"); },
};

export function metricTitle(view: RuleMapMetric, tau: number): string {
  if (view === "firing_strength") return tr("activación de regla (0–1) en el instante de emisión", "rule activation (0–1) at the issue instant");
  if (view === "mean_activation") return tr("activación media de la regla (0–1) en la ventana", "mean rule activation (0–1) over the window");
  return tr(`frecuencia de activación de la regla (0–1), con τ = ${dec(tau, 2)}`, `rule activation frequency (0–1), with τ = ${dec(tau, 2)}`);
}

export function legendTitle(view: RuleMapMetric, tau: number): string {
  if (view === "firing_strength") return tr("activación de regla (0–1)", "rule activation (0–1)");
  if (view === "mean_activation") return tr("activación media de regla (0–1)", "mean rule activation (0–1)");
  return tr(`frecuencia de activación de regla ≥ τ=${dec(tau, 2)} (fracción 0–1)`, `rule activation frequency ≥ τ=${dec(tau, 2)} (fraction 0–1)`);
}
