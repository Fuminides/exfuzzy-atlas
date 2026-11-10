# Atribuciones y licencias

Estado a **2026-10-31** (AT-060, A6). Cada afirmación se contrastó con el manifiesto de la fuente en `configs/` (lo que
escribió el agente de datos) y, cuando se indica, con la página pública de la fuente ese mismo día. Lo que no se pudo
comprobar está marcado **[sin verificar]**. Una tabla corta de «qué mostrar» está al final; la web ya muestra la
atribución de cada dominio (`apps/web/src/lib/domainUi.ts`).

## Datos

| Fuente | Uso en Atlas | Licencia | Texto de atribución | Comprobado |
|---|---|---|---|---|
| Calidad del aire horaria, Madrid (`madrid-air`) | NO₂ y lags de la tarea `madrid_no2_h6` | CC BY 4.0 | Ayuntamiento de Madrid, Servicio de Calidad del Aire. Datos abiertos: <https://datos.madrid.es/dataset/201200-0-calidad-aire-horario> | manifiesto `configs/air/madrid_air.json`; página del portal (2026-10-31): «Creative Commons Attribution 4.0 International (CC BY 4.0)» |
| Estaciones de calidad del aire, Madrid (`madrid-air-stations`) | geometría oficial de las 24 estaciones | CC BY 4.0 | Ayuntamiento de Madrid, Servicio de Calidad del Aire (Geoportal <https://geoportal.madrid.es> y <https://datos.madrid.es/dataset/212629-0-estaciones-control-aire>) | manifiesto; portal (2026-10-31) |
| Meteorología horaria y estaciones, Madrid (`madrid-meteo`, `madrid-meteo-stations`) | viento, temperatura, humedad | CC BY 4.0 | Ayuntamiento de Madrid, Servicio de Calidad del Aire. Datos abiertos: <https://datos.madrid.es/dataset/300352-0-meteorologicos-horarios> y <https://datos.madrid.es/dataset/300360-0-meteorologicos-estaciones> | manifiesto; portal (2026-10-31) |
| Tráfico, puntos de medida (`madrid-traffic`, `madrid-traffic-points`) | solo en los experimentos de A4 (con y sin tráfico); **no** está en el modelo publicado | CC BY 4.0 | Ayuntamiento de Madrid, Área de Medio Ambiente y Movilidad. Datos abiertos: <https://datos.madrid.es/dataset/208627-0-transporte-ptomedida-historico> y <https://datos.madrid.es/dataset/202468-0-intensidad-trafico> | manifiesto; portal (2026-10-31) |
| Calidad del agua, Environment Agency (`uk-water-quality`) | oxígeno disuelto y determinandos de la tarea `uk_water_do` (Northumberland & Tyne, ríos, 2015-2025) | Open Government Licence v3.0 | *Contains public sector information licensed under the Open Government Licence v3.0. © Environment Agency copyright and/or database right 2025. All rights reserved.* | manifiesto `configs/water/uk_water_quality.json`; ficha de data.gov.uk (2026-10-31): «Open Government Licence v3.0» |
| NYC TLC Trip Record Data y Taxi Zones (`nyc-tlc`) | demanda de taxi amarillo por zona y hora (`nyc_pickups_h1`), polígonos de zona | **Sin licencia abierta explícita.** Rigen la NYC Open Data Legal Policy y los NYC.gov Terms of Use; TLC no garantiza la exactitud | NYC Taxi & Limousine Commission (TLC) Trip Record Data and Taxi Zones, <https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page>. Los datos de viaje fueron recogidos por los proveedores TPEP/LPEP y no los creó la TLC | manifiesto `configs/mobility/nyc_tlc.json` y `DATA_SOURCES.md` (A3, 2026-10-30); la página de TLC no declara licencia (2026-10-31). Decisión del usuario (2026-11-06): **no bloquea el uso como demo** (la web, capturas, charlas, un despliegue de demostración); revisar los términos solo antes de **publicar para descarga** los artefactos derivados (ver abajo). Sí van en la release privada de CI `qa-artifacts` |
| Mapa base: OpenFreeMap, datos de OpenStreetMap | fondo del mapa en la web (estilo `positron`, `https://tiles.openfreemap.org/styles/positron`); necesita internet, sin él se dibuja un fondo liso | Datos: **ODbL 1.0** (OpenStreetMap). Esquema de teselas: OpenMapTiles | La fuente de teselas declara: «OpenFreeMap © OpenMapTiles Data from OpenStreetMap» (TileJSON `https://tiles.openfreemap.org/planet`, 2026-10-31). La web muestra «OpenFreeMap © OpenMapTiles · datos © OpenStreetMap contributors» (hallazgo QA-2, resuelto). Estilo, glifos y licencia de OpenFreeMap **[sin verificar]** más allá de la atribución anterior | TileJSON consultado; licencias de OpenFreeMap y de OpenMapTiles no leídas en sus sitios |
| Índice Nacional de Calidad del Aire (ICA), MITECO | límites, nombres, colores y mensajes de las categorías de NO₂ (`configs/ml/ica_no2_scheme.json`) | El PDF no lleva texto de licencia ni de reutilización. Es una resolución oficial (en España las disposiciones legales y reglamentarias no son objeto de propiedad intelectual, art. 13 de la Ley de Propiedad Intelectual) y de ella solo se toman límites, nombres, colores y mensajes: **no bloquea** (decisión del usuario, 2026-11-06; lectura práctica, no un dictamen jurídico) | Ministerio para la Transición Ecológica y el Reto Demográfico, Resolución de la Dirección General de Calidad y Evaluación Ambiental por la que se modifica el anexo de la Orden TEC/351/2019, de 18 de marzo, por la que se aprueba el Índice Nacional de Calidad del Aire: <https://www.miteco.gob.es/content/dam/miteco/images/es/resoluciondgactualizacionica_tcm30-509833.pdf> | Los límites de NO₂ se releyeron en el PDF (2026-10-31): 0-40, 41-90, 91-120, 121-230, 231-340, 341-1000. La fecha y el BOE de la resolución (2020-09-02, BOE 242) **no** salen del PDF: vienen de una página secundaria, como ya advierte el esquema. Los colores están muestreados de la tabla del PDF, no escritos en él |
| NO₂ horario de Alemania, EEA (`eea-air-de`) | NO₂ y lags de las tareas `de_no2_h1` … `de_no2_h24`; geometría de las estaciones | CC BY 4.0; titular: European Environment Agency (EEA) | European Environment Agency (EEA), Air Quality Download Service, datos E1a (verificados) y E2a (actualizados) notificados por Alemania (Umweltbundesamt y los Länder) según la Decisión de Ejecución 2011/850/UE: <https://www.eea.europa.eu/en/datahub/datahubitem-view/778ef9f5-6293-4846-badd-56a29c70880d> | `configs/air/de_eea.json` (`license_evidence`: registro de metadatos del catálogo SDI de la EEA y su aviso legal); copiado de la configuración, no releído hoy |
| Meteorología horaria de Alemania, DWD (`dwd-meteo-de`) | temperatura, humedad, viento y presión de las tareas de Alemania | CC BY 4.0 con atribución de la fuente | Deutscher Wetterdienst (DWD), Climate Data Center (CDC): observaciones horarias de estaciones: <https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/> | `configs/air/de_dwd.json` (Terms_of_use.pdf del CDC, versión de mayo de 2024, y descripciones de los conjuntos); copiado de la configuración, no releído hoy |
| European Air Quality Index (EAQI), EEA | límites, nombres y colores de las bandas de NO₂ de Alemania (`configs/air/eaqi_no2_scheme.json`) | **[sin verificar]** para esta página en concreto; el aviso legal de la EEA dice que sus materiales se publican con CC BY | European Environment Agency, European Air Quality Index: <https://airindex.eea.europa.eu/AQI/index.html> | Bandas y colores leídos de la página y de su hoja de estilos el 2026-11-02 (copia en `data/raw/eea-air-de/docs/`). Las bandas del EAQI no son las del ICA: los resultados por clase de Madrid y Alemania no son comparables |
| Esquema de nivel de demanda NYC | construcción propia (percentiles de la referencia de entrenamiento por zona y hora de la semana) | n/a (propio, AGPL-3.0-or-later como el resto del repositorio) | `docs/mobility/nyc_pickups_h1_level.md` | `configs/mobility/nyc_level_scheme.json` |

El modelo de Madrid agrupa las clases ICA «Desfavorable», «Muy desfavorable» y «Extremadamente desfavorable» en
«Desfavorable o peor» (121-1000 µg/m³; `docs/ml/madrid_no2_h6_ica_v2.md`). Una clase fusionada no es una categoría del
ICA oficial: la web lo avisa. La salida del modelo es una «categoría ICA prevista», nunca un riesgo sanitario ni una
probabilidad.

## Software

| Componente | Licencia | Comprobado |
|---|---|---|
| ExFuzzy Atlas (este repositorio) | **AGPL-3.0-or-later** (`LICENSE` es el texto de la AGPL v3; `pyproject.toml` y `README.md` declaran «or later») | `LICENSE`, `pyproject.toml` |
| [ex_fuzzy](https://github.com/Fuminides/ex-fuzzy) 3.4.0 (motor de inferencia, fijado `ex-fuzzy==3.4.0`) | **AGPL-3.0-or-later** | metadatos del paquete instalado (`License-Expression`, 3.4.0) |
| numpy, pandas, scikit-learn (esta última llega vía ex_fuzzy y se usa en los baselines) | BSD | metadatos instalados |
| pyarrow | Apache-2.0 | metadatos instalados |
| duckdb, pydantic, fastapi, pytz, pyproj, pyshp | MIT | metadatos instalados |
| uvicorn, shapely | BSD-3-Clause | metadatos instalados |
| MapLibre GL JS 6.16.0 | BSD-3-Clause | `node_modules/maplibre-gl/package.json` |
| React / React DOM 19.3.1 | MIT | `node_modules/*/package.json` |
| Source Serif 4 (paquete `@fontsource-variable/source-serif-4` 5.3.1; el LICENSE del paquete es el de Google Fonts), tipografía de títulos de la web, servida desde el propio sitio | **SIL OFL 1.1** | `node_modules/@fontsource-variable/source-serif-4/{package.json,LICENSE}` (2026-11-09) |
| Inter (The Inter Project Authors; paquete `@fontsource-variable/inter` 5.3.0), tipografía de texto de la web, servida desde el propio sitio | **SIL OFL 1.1** | `node_modules/@fontsource-variable/inter/{package.json,LICENSE}` (2026-11-09) |

El árbol completo de dependencias (las transitivas de ex_fuzzy, como pymoo y matplotlib, y las de npm) **no** se auditó aquí **[sin verificar]**.

Obligación AGPL (MASTER_PLAN §11): si Atlas se ofrece como servicio de red, quien lo use tiene derecho al código
fuente de la versión servida, incluidas las modificaciones. Este repositorio es AGPL-3.0-or-later y ex_fuzzy se consume
como paquete sin modificar; el despliegue público debe enlazar el código fuente.

## Qué debe mostrar o acompañar una redistribución

1. En la web, junto al mapa: la atribución del dominio (ya está en el pie) y la del mapa base, con «© OpenMapTiles»
   (ya están en el pie y en el mapa).
2. Si se redistribuyen **artefactos publicados** (`artifacts/published/`: entradas, activaciones, predicciones) o la
   tabla de rasgos:
   - Madrid y agua llevan su texto de atribución.
   - Los de NYC contienen recogidas por zona y hora derivadas de TLC: **no publicarlos para descarga sin revisar antes los términos** (la demo y la release privada de CI no lo son)
     (`DATA_SOURCES.md`). Los artefactos no se versionan en Git (`/artifacts/` está ignorado).
   - La licencia del agua exige el aviso «Contains public sector information…» y, si procede, el enlace a la OGL.
3. Las cifras de la web no son predicciones sanitarias ni causales; `DATA_SOURCES.md` y `AGENTS.md` recogen las
   salvedades de uso.
