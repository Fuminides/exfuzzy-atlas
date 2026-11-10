# Atlas Air: Alemania como segundo territorio (AT-070)

NO₂ horario de las estaciones alemanas de la EEA y meteorología del DWD, con la tabla `de_no2_h6` que tiene **las mismas
columnas, convenciones y semántica temporal que `madrid_no2_h6`** ([`madrid_no2_h6.md`](madrid_no2_h6.md)), para que A4 repita el
protocolo de Madrid sin cambios. Cifras y tablas (generadas, no se editan): [`de_eea_air_quality.md`](de_eea_air_quality.md),
[`de_dwd_meteo_quality.md`](de_dwd_meteo_quality.md), [`de_no2_h6_quality.md`](de_no2_h6_quality.md). No se ha entrenado ningún modelo.

El esquema de la fuente es **independiente** del de Madrid: ingesta, configuración y fuentes propias (`eea_*`, `dwd_*`,
`configs/air/de_*.json`). Lo que se comparte es el contrato de observaciones, `atlas.ingest.sources` (descarga con manifiesto) y
`features.py`, que se generalizó (no se copió) para que lo gobierne un fichero de configuración; la salida de Madrid regenerada con
ese código es idéntica fila a fila.

## Reproducir

```bash
export ATLAS_DATA_DIR=/path/to/exfuzzy-atlas/data      # opcional; por defecto <repo>/data
PYTHONPATH=src python -m atlas.domains.air.eea_ingest --years 2019-2025   # descarga (0,9 GB) + NO2 canónico + estaciones + informe
PYTHONPATH=src python -m atlas.domains.air.dwd_ingest                      # descarga (1,5 GB) + meteo canónica + estaciones + informe
PYTHONPATH=src python -m atlas.domains.air.de_features                     # tabla de_no2_h6 + feature spec + splits + calidad
```

Cada paso es idempotente. La descarga es secuencial (0,4 s entre ficheros, reintentos con espera creciente) y reanudable: el
manifiesto `source_manifest.json` se reescribe cada 50 ficheros y un fichero cuyo sha256 coincide no se vuelve a bajar. Los
ficheros raw van a `$ATLAS_DATASETS_ROOT/eea-air-de` y `.../dwd-meteo-de` (enlaces `data/raw/<nombre>` en el checkout
principal) y quedan en solo lectura. Memoria: DuckDB con `memory_limit` de 2 GB y 4 hilos; la tabla se escribe mes a mes.
Opciones: `--download-only`, `--skip-download`, `--refresh`, `--out-dir`, `--no-doc`.

Salida en `data/processed/air-de/` (misma disposición que `data/processed/air/` de Madrid):

| ruta | contenido |
|---|---|
| `observations/year=Y/month=M/` | NO₂ canónico (EEA), hive por año y mes UTC; pasa `validate_observations_partitioned` |
| `stations.geojson` | `EntityCollection` de puntos de las estaciones con NO₂ (coordenadas EEA, tipo, zona, altitud, red) |
| `meteo/observations/…`, `meteo/stations.geojson` | meteorología canónica y estaciones DWD |
| `quality_report.json`, `ingest_details.json` (+ `meteo/`) | informes de calidad y de ingesta |
| `features/de_no2_h6/table/year=Y/month=M/` | tabla de features y target |
| `features/de_no2_h6/{feature_card,coverage,association,quality,splits,feature_spec}.json` | tarjeta, cobertura, asociación meteo, calidad, splits, feature spec |

Copia versionada de la feature spec: `configs/air/de_no2_h6_feature_spec.json`; atribución: `configs/air/attribution_de.json`;
esquema EAQI: `configs/air/eaqi_no2_scheme.json`.

## Fuentes y licencias

| Qué | Dónde | Licencia |
|---|---|---|
| NO₂ horario, E1a (verificado) y E2a (al día) | EEA Air Quality Download Service: API `https://eeadmz1-downloads-api-appservice.azurewebsites.net` (`POST /ParquetFile/urls`, dataset 2 = E1a, dataset 1 = E2a); ficha: https://www.eea.europa.eu/en/datahub/datahubitem-view/778ef9f5-6293-4846-badd-56a29c70880d | CC BY 4.0 (registro de metadatos del dataset, `otherConstraints`: «License CC-BY 4.0 … Copyright holder: European Environment Agency (EEA)»; https://www.eea.europa.eu/en/legal-notice: «EEA materials are published under the CC-BY license»; política de datos art. 4) |
| Estaciones: coordenadas, tipo, zona | `https://discomap.eea.europa.eu/map/fme/metadata/PanEuropean_metadata.csv` (lista oficial de estaciones y puntos de muestreo, 27 MB) | ídem |
| Estaciones: nombres y coordenadas de reserva | capa ESRI `…/AirQualityDownloadServiceEUMonitoringStations/MapServer/0` | ídem |
| Meteorología horaria | DWD CDC `https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/` (`air_temperature`, `wind`, `pressure`; `historical/` y `recent/`) | CC BY 4.0 con cita de la fuente: `CDC/Terms_of_use.pdf` («The Creative Commons BY 4.0 - Licence "CC BY 4.0" apply», estado mayo 2024) y los `DESCRIPTION_…pdf` de cada producto; https://www.dwd.de/DE/service/rechtliche_hinweise/rechtliche_hinweise_node.html |
| Bandas EAQI | https://airindex.eea.europa.eu/AQI/index.html (copia en `data/raw/eea-air-de/docs/eaqi_airindex.html`) | contenido web de la EEA, CC BY (legal notice); la tabla no declara licencia propia |

Sin claves ni cuentas. Los vocabularios de la EEA (validez, verificación, zona horaria) y los documentos de referencia se guardan en
el directorio raw y en su manifiesto.

## Convención horaria (con prueba)

**EEA.** `Start`/`End` de cada valor están en el desfase **fijo UTC+01 todo el año** y el valor cubre `[Start, End)` con
`End = Start + 1 h`: la columna `Timezone` de los 7.077 registros alemanes del fichero de metadatos es la entrada `UTC+01` del
vocabulario de la EEA y el Parquet trae marcas sin zona. Por tanto `timestamp_utc = Start − 1 h` es el **inicio** de la hora, como en
todo Atlas. No hay horario de verano: ni horas inexistentes ni ambiguas, 24 filas por día. Dos comprobaciones: (1) el lector
exige `AggType = hour`, `End − Start = 1 h` y minutos 0 (falla si no); (2) el ciclo diario del NO₂ de las 140 estaciones de tráfico urbanas
en laborables llega en verano **una hora UTC antes** que en invierno (desplazamiento óptimo +1 h, error 0,22 frente a 0,47 sin
desplazar), que es lo que implica un reloj fijo UTC+1 frente a un reloj local que pasa a UTC+2. Test:
`tests/air/test_de_eea.py::test_start_is_utc_plus_one_all_year_…` y `…::test_diurnal_check_…`.

**DWD.** `MESS_DATUM` está en **UTC** casi siempre: cada zip trae `Metadaten_Parameter` con el reloj de cada variable y periodo («Stundenwerte in
UTC»). Excepción: la velocidad del viento de **17 estaciones de registro analógico** dice «Stundenwerte in MEZ» durante todo el periodo. Se
convirtieron (MEZ = UTC+1 fijo) y se compararon con sus vecinas UTC más cercanas (≤ 60 km, 2021-2022): tras la conversión sus valores horarios
encajan mejor con desfases de −1 h (14 de 17) y −2 o −3 h (3), mientras que entre estaciones digitales UTC vecinas el desfase es 0. Como el reloj de
esas series no se puede verificar, **se excluyen** (`accepted_time_references: ["UTC"]` en `configs/air/de_dwd.json`); el código sabe convertir
MEZ y un test lo cubre, pero no se usa. Una referencia que no sea UTC ni MEZ (p. ej. hora legal) detiene la ingesta y las filas sin referencia
declarada se descartan y se cuentan.

Los ficheros no dicen si la etiqueta es el inicio o el final de la ventana (T, HR y presión salen de mensajes SYNOP a la hora en punto; el
viento, de medias de 10 minutos; la comparación anterior sugiere que en las series digitales la etiqueta es el final de la ventana). Decisión:
**la etiqueta se toma como inicio de la hora** (`timestamp_utc = MESS_DATUM`, usable desde `MESS_DATUM + 1 h`). Si la etiqueta es el final de la
ventana esto solo retrasa la meteorología una hora respecto a lo legítimo; no puede filtrar futuro. Coste: la feature con clave t − 1 h es, en la
práctica, la observada como mucho en t − 1 h.

## Datos y semántica de valores

- **Una fila canónica por (estación, hora)**: E1a si existe y si no E2a, con `source_id` `eea-air-de-e1a` / `eea-air-de-e2a`. En 2019-2025
  **E1a cubre todo el periodo** (los ficheros E2a empiezan el 2026-01-01), así que E2a aporta 0 filas aquí; el código, los tests y el informe
  lo tratan igualmente y lo muestran.
- `validity_flag = "<Validity>:<Verification>"` con los códigos de la EEA (Validity 1 válido, 2 válido bajo el límite de detección con el valor
  medido, 3 sustituido por 0,5 × límite, −1 no válido, −99 mantenimiento o calibración; Verification 1 verificado, 2 preliminar, 3 no verificado).
  Todos los valores 2019-2025 son *verificados* (E1a). `missing_reason`: `invalid_observation` (validez −1/−99, o unidad no soportada) o
  `no_observation` (válido sin número). El centinela −999 que traen los inválidos **nunca** se escribe como valor.
- Unidades: todos los ficheros traen `ug.m-3`. Se convierten `mg.m-3` y `ng.m-3`; cualquier otra (p. ej. ppb) deja el valor nulo y
  `invalid_observation` en lugar de mezclar unidades (hay un test).
- Valores negativos: 26.205 valores válidos (bandera 2, ruido bajo el límite de detección, mínimo −9,9) y uno de 1.015 µg/m³ se conservan tal
  cual y se cuentan en `outliers_flagged`; A4 decide si recorta.
- Todas las estaciones entran (tráfico, fondo, industrial; urbana, suburbana, rural…): el tipo y la zona son atributos de la entidad, no
  columnas de la tabla (misma tabla que Madrid).
- Estaciones: 440 con algún valor en el periodo. Coordenadas del fichero de metadatos; 8 estaciones nuevas faltan en él: 5 se cogen de la capa de
  estaciones de la EEA (4 decimales, anotado en la entidad) y 3 se quedan sin geometría (`geometry: null`, nada se inventa) y por tanto sin
  meteorología. Todas las que tienen punto caen dentro de la caja de Alemania; hay un par a 31 m (DEBE063 – DEBE127), ambos se mantienen.

## Meteorología: asignación y tope de distancia

Igual que Madrid (`association.py`): por (estación de aire, variable), las estaciones DWD que miden la variable dentro del tope, ordenadas
por distancia (círculo máximo), hasta 3; la primera es la principal y las demás suplentes hora a hora. Sin interpolar ni promediar. La
distancia queda en `association.parquet/json`. **Tope: 25 km** (Madrid: 5 km). Con la red DWD (separación media de unos 25 km) 5 km dejaría
casi todas las estaciones sin meteorología; 25 km es una decisión de este informe, con la sensibilidad (5/10/15/25/50 km) en
[`de_no2_h6_quality.md`](de_no2_h6_quality.md). Más allá del tope el input es NULL (`missing_reason = no_observation`; `association.json` lo lista
como `null` y `quality.json` cuenta las filas nulas por motivo). Presión: P0 (a nivel de estación, hPa), columna `pressure` no recomendada
como en Madrid. Rangos de plausibilidad propios del DWD en `configs/air/de_no2_h6.json` (`plausible_range`).

## Diferencias deliberadas con Madrid

| | Madrid | Alemania |
|---|---|---|
| fuente NO₂ / meteo | `madrid-air` / `madrid-meteo` | `eea-air-de` (E1a/E2a) / `dwd-meteo-de` |
| reloj de la fuente | hora local con horario de verano (huecos `H03` anómalos) | EEA: UTC+01 fijo; DWD: UTC; sin días excluidos |
| calendario local | Europe/Madrid | Europe/Berlin |
| tope meteo | 5 km | 25 km |
| etiqueta meteo | `[t−1 h, t)` | etiqueta DWD tomada como inicio de hora (+1 h conservadora) |
| escritura de la tabla | una pasada | mes a mes (`chunk_by_month`), mismas filas |
| esquema de clases | ICA (MITECO) | EAQI (EEA), ver abajo |

## Splits y clases

Misma partición que Madrid (`splits.json`): train 2019-01-01T00:00Z – 2023-12-31T00:00Z, validación 2024-01-01T00:00Z – 2024-12-31T00:00Z, test
2025-01-01T00:00Z – 2026-01-01T00:00Z, embargo de 24 h entre periodos (ventanas de hora de emisión semiabiertas). Cronológico, sin mezclar.

**EAQI (NO₂, concentración horaria, µg/m³)**: Good 0-10, Fair 11-25, Moderate 26-60, Poor 61-100, Very poor 101-150, Extremely poor >150.
Fuente: https://airindex.eea.europa.eu/AQI/index.html (consultada 2026-11-02, §2 «Bands of concentrations and index levels»). **No coinciden con las
bandas del ICA español de Madrid** (0-40, 41-90, 91-120, 121-230, 231-340, 341-1000): los cinco umbrales son más bajos, así que los resultados por
clase de Madrid y Alemania no son comparables. El redondeo al entero antes de clasificar es una convención de Atlas (la EEA no la declara). El
porcentaje de horas de cada banda por split está en `de_no2_h6_quality.md` y `features/de_no2_h6/quality.json`. Decidir si se agrupan clases (como
«Desfavorable o peor» en el ICA) es cosa de A4; `attribution_de.json` deja `classes` vacío.

## Cifras de la última ejecución (2026-11-02)

| | |
|---|---|
| NO₂ EEA | 24.915.384 filas canónicas (440 estaciones, 2018-12-31T23:00Z – 2025-12-31T22:00Z), 24.285.506 con valor (97,5 %); todo E1a, todo *verificado*; 629.878 inválidas (−1: 602.879, −99: 26.999) |
| cobertura NO₂ | 97,0 – 97,8 % de las horas por estación y año (411 estaciones con filas en 2019, 400 en 2025) |
| meteo DWD | 89.879.191 filas canónicas, 593 estaciones (TU 516, FF 301, P0 217 zips; 17 series de viento MEZ excluidas), 99,6 % con valor |
| tabla `de_no2_h6` | 26.998.840 filas = 440 estaciones × 61.361 horas; 21.228.357 completas (78,6 %): train 15.213.722, validación 3.039.891, test 2.957.829 |
| NO₂ del target (filas completas) | media 17,9 (train), 14,6 (validación), 15,5 µg/m³ (test) |
| EAQI (filas completas), train / val / test | Good 40,8 / 48,6 / 45,8 %; Fair 34,8 / 34,7 / 35,2 %; Moderate 22,4 / 16,2 / 18,2 %; Poor 1,84 / 0,56 / 0,82 %; Very poor 11.664 / 206 / 764 filas; Extremely poor 268 / 13 / 5 filas |
| meteo a ≤ 25 km | temperatura y humedad 437 de 440 estaciones, viento 407, presión 372; distancia mediana a la principal 7,6 km (T), 9,9 km (viento) |
| tiempos | EEA: descarga ≈ 15 min (899 ficheros, 0,9 GB), ingesta 40 s; DWD: descarga ≈ 12 min (1.063 ficheros, 1,5 GB), ingesta 17 min; tabla 47 s |
| memoria (RSS máx. medido) | EEA 2,27 GB; DWD 2,94 GB; tabla 1,51 GB (DuckDB con 2 GB, 4 hilos) |

Para A4: con el EAQI las clases altas son raras (Very poor: 0,08 % del train y 0,03 % del test; Extremely poor: 5 filas en el test), así que
conviene agrupar «Poor o peor» como se agrupó «Desfavorable o peor» en el ICA. Con las bandas del ICA de Madrid el 91-95 % de las horas alemanas
caerían en «Buena» (ver `de_no2_h6_quality.md`), por eso el esquema de clases es el EAQI.

## Pruebas

`tests/air/test_de_eea.py`, `test_de_dwd.py`, `test_de_features.py` (sin red ni datos reales): convención temporal del EEA y del DWD, banderas,
unidades, precedencia E1a/E2a, estaciones (caja, colocalizadas, reserva), descarga reanudable, asignación meteo con el tope de 25 km,
igualdad de la escritura mes a mes con la de una pasada, no-fuga (claves ≤ t−1 h, target a t+6 h, nulos no ceros), calendario Europe/Berlin,
feature spec con las columnas, unidades y retardos de Madrid, y que la salida de Madrid no cambia.
