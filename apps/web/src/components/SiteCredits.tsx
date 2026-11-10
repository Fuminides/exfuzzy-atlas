import { tr } from "../i18n";
import agplLogo from "../assets/agplv3-155x51.png";

const AUTHOR_LINKS: { href: string; label: () => string }[] = [
  { href: "https://fuminides.github.io/", label: () => tr("Web", "Website") },
  { href: "https://scholar.google.com/citations?user=llsfX8sAAAAJ", label: () => "Google Scholar" },
  { href: "https://orcid.org/0000-0002-0644-1355", label: () => "ORCID" },
  { href: "https://github.com/Fuminides/ex-fuzzy", label: () => tr("ex-fuzzy en GitHub", "ex-fuzzy on GitHub") },
  { href: "https://pypi.org/project/ex-fuzzy/", label: () => tr("ex-fuzzy en PyPI", "ex-fuzzy on PyPI") },
  { href: "https://github.com/Fuminides/exfuzzy-atlas", label: () => tr("Código de esta demo", "Source of this demo") },
];

const DATA_CREDITS: { href: string; name: string; licence: string }[] = [
  { href: "https://www.eea.europa.eu/en/datahub/datahubitem-view/778ef9f5-6293-4846-badd-56a29c70880d", name: "European Environment Agency", licence: "CC BY 4.0" },
  { href: "https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/", name: "Deutscher Wetterdienst", licence: "CC BY 4.0" },
  { href: "https://environment.data.gov.uk/water-quality", name: "Environment Agency", licence: "OGL v3.0" },
  { href: "https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page", name: "NYC Taxi & Limousine Commission", licence: "NYC.gov Terms of Use" },
];

const ext = { target: "_blank", rel: "noopener noreferrer" } as const;

/** Who made the demo, where the data come from and the code's licence. The same block closes the landing and the app. */
export function SiteCredits() {
  return (
    <div className="site-credits" data-testid="site-credits">
      <p className="site-credits-author">
        {tr("Hecha por", "Made by")} <strong>Javier Fumanal Idocin</strong>
        {AUTHOR_LINKS.map((l) => (
          <span key={l.href}>
            {" · "}
            <a href={l.href} {...ext}>
              {l.label()}
            </a>
          </span>
        ))}
      </p>
      <p className="site-credits-data">
        {tr("Datos", "Data")}:{" "}
        {DATA_CREDITS.map((d, i) => (
          <span key={d.href}>
            {i > 0 && " · "}
            <a href={d.href} {...ext}>
              {d.name}
            </a>{" "}
            <span className="muted">({d.licence})</span>
          </span>
        ))}
        {" · "}
        {tr("Mapa", "Map")}:{" "}
        <a href="https://openfreemap.org/" {...ext}>
          OpenFreeMap
        </a>
        , © OpenMapTiles,{" "}
        <a href="https://www.openstreetmap.org/copyright" {...ext}>
          © OpenStreetMap contributors
        </a>
      </p>
      <p className="site-credits-note">
        {tr("Derivado de NYC Taxi & Limousine Commission (TLC) Trip Record Data. Los recuentos por zona y hora y las predicciones son trabajo propio, no producidos ni respaldados por NYC ni por la TLC.", "Derived from NYC Taxi & Limousine Commission (TLC) Trip Record Data. The pickup counts by zone and hour and the predictions are the author's own work, not produced or endorsed by NYC or the TLC.")}
      </p>
      <p className="site-credits-licence">
        <a href="https://www.gnu.org/licenses/agpl-3.0.html" {...ext}>
          <img src={agplLogo} width={93} height={31} alt="GNU AGPL v3" />
        </a>
        <span>
          {tr("El código es software libre bajo la licencia AGPL-3.0-or-later. Cada fuente de datos conserva su propia licencia.", "The code is free software under the AGPL-3.0-or-later licence. Each data source keeps its own licence.")}
        </span>
      </p>
    </div>
  );
}
