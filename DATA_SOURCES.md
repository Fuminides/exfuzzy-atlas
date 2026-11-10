# Catálogo de fuentes y condiciones de uso

Consultado el 2026-10-30. Quien ingiera una fuente debe comprobar en ejecución descarga, esquema y restricciones actualizadas; **no se han descargado datasets en este paquete**.

## Atlas Air (Madrid)

- Contaminación atmosférica horaria, 2001–presente; publicación mensual de datos validados: https://datos.madrid.es/dataset/201200-0-calidad-aire-horario
- Meteorología horaria, desde 2019: https://datos.madrid.es/dataset/300352-0-meteorologicos-horarios
- Tráfico histórico por puntos de medida, desde 2013; descargas mensuales: https://datos.madrid.es/dataset/208627-0-transporte-ptomedida-historico
- Uso previsto: primera intersección temporal 2019–2025. Comprobar relación espacial, distintas frecuencias (tráfico vs aire), flags de validez, valores perdidos, horas y códigos de magnitud.
- Licencias de los portales municipales: CC BY 4.0; incluir atribución y fecha/URL por dataset.
- Extensión europea: https://www.eea.europa.eu/en/about/contact-us/faqs/where-can-i-access-the-latest-air-quality-data-in-europe/

## Atlas Air (Alemania)

Es el dominio Air que sirve la demo (tareas `de_no2_*`). Detalle en `docs/air/germany.md`; atribución en `ATTRIBUTION.md`.

- **NO₂ horario, EEA Air Quality Download Service** (`eea-air-de`): datos E1a (verificados) y E2a (actualizados)
  notificados por Alemania (Umweltbundesamt y los Länder) según la Decisión de Ejecución 2011/850/UE. Ficha:
  https://www.eea.europa.eu/en/datahub/datahubitem-view/778ef9f5-6293-4846-badd-56a29c70880d; API de descarga:
  https://eeadmz1-downloads-api-appservice.azurewebsites.net; metadatos de estaciones y puntos de muestreo:
  https://discomap.eea.europa.eu/map/fme/metadata/PanEuropean_metadata.csv. URLs exactas en `configs/air/de_eea.json`.
- Licencia **CC BY 4.0**, titular la European Environment Agency (EEA), según el registro de metadatos
  (https://sdi.eea.europa.eu/catalogue/srv/api/records/fe809728-9cec-41c0-a9be-3a8f04600974/formatters/xml) y el aviso
  legal de la EEA (https://www.eea.europa.eu/en/legal-notice). Atribución e indicación de cambios obligatorias.
- **Meteorología horaria, DWD Climate Data Center** (`dwd-meteo-de`): observaciones horarias de estaciones (temperatura y
  humedad, viento, presión): https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/.
  Licencia **CC BY 4.0** con atribución de la fuente (Deutscher Wetterdienst), según
  https://opendata.dwd.de/climate_environment/CDC/Terms_of_use.pdf (estado de mayo de 2024). URLs en `configs/air/de_dwd.json`.
- Bandas y colores del European Air Quality Index (EEA, https://airindex.eea.europa.eu/AQI/index.html): licencia de esa
  página **sin verificar** (el aviso legal de la EEA dice CC BY); ver `ATTRIBUTION.md`.

## Atlas Water (Inglaterra)

- Registro oficial: https://www.data.gov.uk/dataset/583e771f-1af6-4934-b8f0-28f1d1ddd48c/water-quality-explorer
- Más de 72 M observaciones de más de 5 M muestras, según ficha publicada en 2026; **observación de analito no equivale a muestra/ejemplo supervisado**.
- Nuevo acceso: seguir los enlaces a Water Quality Explorer/API desde la ficha; la **API histórica antigua fue retirada el 11/12/2025**, con nuevas respuestas paginadas. Documento: https://dsp.environment.data.gov.uk/support/faqs/275879249/1156874241
- Verificar cuotas, paginación, unidad, analito/determinand, matriz (agua dulce/costera/etc.), límite de detección, flags y disponibilidad del dato.
- Registrar atribución de Environment Agency y Open Government Licence según metadatos.
- **Muestra en uso (AT-020/021):** ríos de Northumberland & Tyne (subárea `X-H`), 2015-2025, 5 determinandos: oxígeno disuelto 9924, amonio 0111, ortofosfato 0180, pH 0061 y temperatura 0076. Son 93.930 observaciones. Licencia OGL v3.0, sin clave.

## Atlas Mobility (NYC)

- TLC mensual, Parquet, diccionarios y shapefile/taxi zone lookup: https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page
- Taxi amarillo como primer subtipo. Para predicción de demanda usar `pickup_datetime` y `PULocationID`; la hora de `dropoff_datetime` y el fare **no** son features válidas de demanda futura.
- Para duración de viaje, se requiere una tarea distinta con su propio corte temporal y validación.
- Registro NYC recoge viajes completados: no mide demanda no atendida. Ni viajes ni cobros equivalen automáticamente a emisiones/congestión.
- Consultar licencia, condiciones de uso y cambios de esquema al descargar cada año (p.ej. nuevos campos en 2025).
- **Comprobado por A3 (2026-10-30):** ni la página de TLC ni los metadatos de NYC Open Data (`irx2-vgm4`) declaran una licencia abierta explícita. Rigen la NYC Open Data Legal Policy y los NYC.gov Terms of Use, y TLC no garantiza la exactitud de los datos. **Hay que revisar los términos antes de redistribuir datos derivados públicamente.**
- **Decisión tomada:** se publican **recuentos derivados por zona y hora** y las predicciones del modelo, no los registros
  de viaje, con este crédito en el sitio (`apps/web/src/components/SiteCredits.tsx`): «Derivado de NYC Taxi &
  Limousine Commission (TLC) Trip Record Data. Los recuentos por zona y hora y las predicciones son trabajo propio, no
  producidos ni respaldados por NYC ni por la TLC.»

## Auditoría obligatoria en cada fuente

Tabla esperada en `quality_report.json`: `source_url`, `downloaded_at`, `source_period`, `license`, `sha256`, `raw_rows`, `valid_rows`, `uniqueness_key`, `missing_by_column`, `date_range`, `geographic_coverage`, `sampling_frequency`, `value_units`, `known_limitations`.
