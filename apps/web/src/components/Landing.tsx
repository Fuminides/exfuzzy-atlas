import { tr } from "../i18n";
import { SiteCredits } from "./SiteCredits";
import { LandingArtifacts } from "./LandingArtifacts";
import { LanguageSwitch } from "./LanguageSwitch";
import airMap from "../assets/landing/air.svg";
import waterMap from "../assets/landing/water.svg";
import mobilityMap from "../assets/landing/mobility.svg";

/**
 * The three territories of the demo, one line each (what is predicted, from which public source) and a small map of
 * where its data are (static SVGs drawn from the published geometry by `npm run gen:landing-maps`).
 */
const territories = () => [
  {
    key: "air",
    map: airMap,
    alt: tr("Estaciones de medida en Alemania", "Measurement stations in Germany"),
    tag: tr("Calidad del aire", "Air quality"),
    title: tr("Alemania", "Germany"),
    text: tr("La categoría del índice europeo de calidad del aire (EAQI) para el NO₂ en las estaciones alemanas, prevista con horas de antelación a partir de las mediciones horarias que publica la Agencia Europea de Medio Ambiente (EEA).", "The European air quality index (EAQI) category for NO₂ at German stations, predicted hours ahead from the hourly measurements the European Environment Agency (EEA) publishes.",),
  },
  {
    key: "water",
    map: waterMap,
    alt: tr("Puntos de muestreo en los ríos de Northumberland y Tyne", "Sampling points on the Northumberland and Tyne rivers"),
    tag: tr("Calidad del agua", "Water quality"),
    title: tr("Ríos de Northumberland y Tyne (Inglaterra)", "Northumberland and Tyne rivers (England)"),
    text: tr("El oxígeno disuelto de las muestras de río de la Environment Agency, estimado con lo que mide esa misma muestra.", "Dissolved oxygen in the Environment Agency's river samples, estimated from what that same sample measures.",),
  },
  {
    key: "mobility",
    map: mobilityMap,
    alt: tr("Zonas de taxi de Nueva York", "Taxi zones of New York"),
    tag: tr("Movilidad urbana", "Urban mobility"),
    title: tr("Nueva York", "New York"),
    text: tr("El nivel de demanda de taxi amarillo en cada zona, respecto a lo habitual en esa zona a esa hora de la semana, con los viajes que publica la NYC TLC.", "The yellow-taxi demand level in each zone, relative to what is usual there at that hour of the week, from the trips the NYC TLC publishes.",),
  },
];

/**
 * Scroll to a section and give it the focus, without a hash in the URL (a hash route opens the app: lib/landing.ts).
 */
function jump(e: React.MouseEvent, id: string) {
  e.preventDefault();
  const target = document.getElementById(id);
  if (!target) return;
  const reduce = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  target.scrollIntoView?.({ behavior: reduce ? "auto" : "smooth", block: "start" });
  target.focus({ preventScroll: true });
}

/**
 * The landing page (DESIGN.md, Steep hero): what ExFuzzy Atlas is, how a model reads, the three territories, then
 * «Empezar la demo». Its floating artifacts are real components drawn from the API's data
 * (LandingArtifacts); without the API they are simply absent, and every sentence here still holds.
 */
export function Landing({ onStart }: { onStart: () => void }) {
  return (
    <div className="landing" data-testid="landing">
      <a className="skip-link" href="#landing-main" onClick={(e) => jump(e, "landing-main")}>
        {tr("Saltar al contenido", "Skip to content")}
      </a>
      <header className="lp-top">
        <p className="brand">ExFuzzy Atlas</p>
        <LanguageSwitch />
      </header>

      <main id="landing-main" tabIndex={-1}>
        <section className="lp-hero" aria-labelledby="landing-title">
          <div className="lp-wash" aria-hidden="true" />
          <div className="lp-hero-text">
            <p className="lp-kicker">{tr("Una demostración de ex_fuzzy con datos públicos reales", "An ex_fuzzy demo on real public data")}</p>
            <h1 id="landing-title" className="lp-title" tabIndex={-1}>
              {tr(<>Explicando mapas <em className="lp-accent">con reglas</em></>, <>Explaining maps <em className="lp-accent">with rules</em></>)}
            </h1>
            <p className="lp-sub">
              {tr("Un estudio de calidad del aire, calidad del agua y demanda de taxis.", "A study of air quality, water quality and taxi demand.")}
            </p>
            <div className="lp-actions">
              <button type="button" className="btn btn--primary btn--lg" onClick={onStart} data-testid="landing-start">
                {tr("Empezar la demo", "Start the demo")}
              </button>
              <a className="btn btn--lg lp-how" href="#como-funciona" onClick={(e) => jump(e, "lp-how-title")}>
                {tr("Ver cómo funciona", "How it works")}
              </a>
            </div>
          </div>
          <LandingArtifacts />
        </section>

        <section id="como-funciona" className="lp-section lp-how-section" aria-labelledby="lp-how-title">
          <div className="lp-col">
            <p className="lp-eyebrow">{tr("Cómo funciona", "How it works")}</p>
            <h2 id="lp-how-title" className="lp-h2" tabIndex={-1}>
              {tr("Un modelo hecho de frases", "A model made of sentences")}
            </h2>
            {tr(<p className="lp-text">Un modelo de <strong>ex_fuzzy</strong> es una lista corta de <strong>reglas difusas</strong>: frases del tipo «<em>Si el NO₂ hace 4 h es Buena y la hora es Mediodía → Buena</em>». Cada condición se cumple en un grado entre 0 y 1, y la regla que mejor encaja con las observaciones (en algunos modelos, ponderada por un peso) decide la predicción; en otros, cada regla tiene un peso para cada categoría y se predice la categoría que más apoyo suma. Ese grado mide cuánto encaja la regla con lo observado.</p>, <p className="lp-text">An <strong>ex_fuzzy</strong> model is a short list of <strong>fuzzy rules</strong>: sentences such as “<em>If NO₂ 4 h ago is Good and the hour is Midday → Good</em>”. Each condition holds to a degree between 0 and 1, and the rule that best matches the observations (in some models, multiplied by its weight) decides the prediction; in others, each rule has a weight for each category and the category with the most support added up is predicted. The degree measures how well the rule matches what was observed.</p>)}
          </div>
        </section>

        <section className="lp-section" aria-labelledby="lp-territories-title">
          <div className="lp-col lp-col--wide">
            <p className="lp-eyebrow">{tr("Tres territorios", "Three territories")}</p>
            <h2 id="lp-territories-title" className="lp-h2">
              {tr("Datos públicos de tres lugares", "Public data from three places")}
            </h2>
            <ul className="lp-cards">
              {territories().map((t) => (
                <li key={t.key} className="lp-card" data-territory={t.key}>
                  <img className="lp-card-map" src={t.map} alt={t.alt} width={400} height={300} loading="lazy" decoding="async" />
                  <p className="lp-card-tag">{t.tag}</p>
                  <h3 className="lp-card-title">{t.title}</h3>
                  <p className="lp-card-text">{t.text}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section className="lp-section lp-end" aria-labelledby="lp-end-title">
          <div className="lp-col">
            <h2 id="lp-end-title" className="lp-h2">
              {tr("Empieza por las reglas", "Start with the rules")}
            </h2>
            <p className="lp-text">
              {tr(<>La demo se abre en <em>Patrones</em>, con las reglas del primer territorio. Arriba puedes cambiar de territorio, de horizonte y de sección.</>, <>The demo opens on <em>Patterns</em>, with the rules of the first territory. At the top you can switch territory, horizon or section.</>)}
            </p>
            <div className="lp-actions">
              <button type="button" className="btn btn--primary btn--lg" onClick={onStart}>
                {tr("Empezar la demo", "Start the demo")}
              </button>
            </div>
          </div>
        </section>
      </main>

      <footer className="lp-foot">
        <SiteCredits />
      </footer>
    </div>
  );
}
