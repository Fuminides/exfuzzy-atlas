import { tr } from "../i18n";
import { articles } from "../lib/domainUi";

/** The selected entity is in the geometry file but the model has no data for it (`modelled: false`, "sin modelo"). */

export function UnmodelledNotice({ name, noun }: { name: string; noun: string }) {
  return (
    <section className="unmodelled-notice" aria-label={tr("Entidad sin modelo", "Entity not modelled")} data-testid="unmodelled-notice">
      <h2>{tr(`${name}: sin modelo`, `${name}: not modelled`)}</h2>
      <p className="muted">
        {tr(<>El modelo no tiene datos para {articles(noun).este} {noun} (<code>modelled: false</code>, <code>not_modelled</code>). Sin datos no hay predicción, activación, traza ni escenario.</>, <>The model has no data for this {noun} (<code>modelled: false</code>, <code>not_modelled</code>). Without data there&apos;s no prediction, activation, trace or scenario.</>)}
      </p>
    </section>
  );
}
