# Atlas Air: ingesta de la calidad del aire de Madrid (AT-010)

Pipeline reproducible `datos.madrid.es` (hora local, un registro por estación x magnitud x día con 24 huecos) a observaciones
canónicas en Parquet (una fila por estación x hora x magnitud), más las estaciones con geometría oficial y un informe de
calidad. Resultados de la última ingesta real: [`madrid_air_quality.md`](madrid_air_quality.md) (generado, no se edita).

## Reproducir

```bash
# desde la raíz del checkout (o worktree); python = el del entorno del proyecto
PYTHONPATH=src python -m atlas.domains.air.ingest --years 2019-2025
```

Hace, en este orden (todo idempotente):

1. **Descarga** a `$ATLAS_DATASETS_ROOT/madrid-air/` (por defecto `~/Datasets`) y `.../madrid-air-stations/` (el directorio se toma de
   `--datasets-root` o `ATLAS_DATASETS_ROOT`) y crea los enlaces `data/raw/madrid-air*`. Cada directorio lleva su
   `source_manifest.json` (`SourceManifest`: URL, sha256, bytes, licencia, atribución, fecha por fichero). Un fichero cuyo
   sha256 ya coincide con el manifiesto no se vuelve a bajar; los ficheros raw quedan en solo lectura. `--refresh` fuerza la
   descarga (necesario para recoger meses nuevos del CSV «desde 2025», que el portal amplía cada mes).
2. **Conversión** en streaming (un mes cada vez; pico medido 1,4 GB de RSS con DuckDB limitado a 1 GB) a
   `data/processed/air/observations/year=YYYY/month=M/*.parquet`. **El particionado es por año/mes UTC** de
   `timestamp_utc`, así que `year=2018/month=12` contiene la primera hora de 2019 local (23:00Z).
3. **Validación** con `atlas.contracts.validate_observations` (falla la ingesta si hay violaciones).
4. **Estaciones**: `data/processed/air/stations.geojson` (`EntityCollection`, `geometry_support=observed_point`).
5. **Informe**: `data/processed/air/quality_report.json` (`QualityReport`), `ingest_details.json` (cobertura por estación
   y año de todas las magnitudes, evidencia de horario de verano, inventario de ficheros) y `docs/air/madrid_air_quality.md`.

Otras opciones: `--download-only`, `--skip-download` (usa `data/raw` tal cual), `--out-dir`, `--doc`/`--no-doc`.
Tests (sin red ni datos reales): `make test` o `PYTHONPATH=src python -m pytest tests/air`.

## Fuentes (todas CC BY 4.0, Ayuntamiento de Madrid)

| Qué | URL |
|---|---|
| Dataset horario | https://datos.madrid.es/dataset/201200-0-calidad-aire-horario |
| Intérprete de ficheros | https://datos.madrid.es/dataset/201200-0-calidad-aire-horario/resource/201200-17-calidad-aire-horario/download/201200-17-calidad-aire-horario.pdf |
| Estaciones: capa Geoportal (geometría) | https://sigma.madrid.es/hosted/rest/services/GEOPORTAL/ZONAS_DE_CALIDAD_DEL_AIRE_Y_ESTACIONES_DE_MEDICION/MapServer/5 (`query?where=1=1&outFields=*&outSR=4326&f=geojson`) |
| Estaciones: dataset datos.madrid.es (contraste, altitud, alta) | https://datos.madrid.es/dataset/212629-0-estaciones-control-aire |

Las URLs de descarga de cada ZIP/CSV están en `configs/air/madrid_air.json`. 2019-2024 son ZIP anuales; 2025 en adelante
es un único CSV acumulado («desde 2025»), que a 2026-10-30 llegaba hasta el 30-09-2026. 2025 está completo; 2026 no se
ingiere por defecto.

## Esquema canónico

Una fila por estación x hora x magnitud. Claves y semántica (contrato en `src/atlas/contracts/observations.py`):

| Columna | Valor |
|---|---|
| `domain`, `source_id` | `air`, `madrid-air` |
| `entity_id` | código nacional de 8 dígitos, `PROVINCIA`+`MUNICIPIO`+`ESTACION` (p. ej. `28079004`); igual que `stations.geojson` |
| `timestamp_utc` | **inicio** de la hora de medida, en UTC |
| `source_timestamp_local` | texto original: `AAAA-MM-DD Hnn` |
| `timezone` | `Europe/Madrid` |
| `feature_name`, `unit` | `no2`, `pm10`, `pm25`, `o3`, `co`, `so2`, `no`, `nox`, `tol`, `ben`, `ebe`, `tch`, `ch4`, `nmhc` (ver abajo); `ug/m3` salvo `co`, `tch`, `ch4`, `nmhc` en `mg/m3` |
| `value` | número, o `null` con `missing_reason` (nunca 0 por falta de dato) |
| `validity_flag` | código original (`V`, `N`, `M`) |
| `missing_reason` | `invalid_observation` (código distinto de `V`) o `no_observation` (hueco vacío) |
| `data_version` | `madrid-air-2019-2025-v1` |

Códigos de magnitud (anexo II del intérprete): 1 SO2, 6 CO, 7 NO, 8 **NO2**, 9 PM2.5, 10 PM10, 12 NOx, 14 O3, 20 TOL,
30 BEN, 35 EBE, 37 MXY, 38 PXY, 39 OXY, 42 TCH, 43 CH4, 44 NMHC, 431 MPX. Las magnitudes 81-89 (sensores meteorológicos que
aparecen en los TXT de 2019) se excluyen y se cuentan (AT-011 se ocupa de meteorología).

## Convención horaria

- Los datos están en **hora local de Madrid** (intérprete, apartado 7). `Hnn` es la hora que **termina** a las `nn:00`:
  el intérprete define `H24` como la media de los seis valores diezminutales de las 23 h a las 24 h. Prueba empírica:
  en los 7 días de cambio de marzo de 2019-2025 el hueco `H03` es inválido en el 100 % de las filas (la hora local
  02:00-03:00 no existe); con `Hnn = [nn:00, nn+1:00)` sería `H02`.
- `timestamp_utc = (fecha local + (nn-1) h)` interpretado en `Europe/Madrid` y pasado a UTC.
- **Hora inexistente** (marzo, 23 h): el hueco `H03` no tiene instante UTC; no se escribe fila y se cuenta en el informe.
- **Hora ambigua** (octubre, 25 h): la fuente solo trae 24 huecos y «se elimina el dato de la hora en la que se produce el
  retraso». Se asigna `H03` a la **primera** ocurrencia (horario de verano, UTC+2); la segunda (01:00Z) no existe como fila.
  Es una asunción basada en el intérprete; los datos no permiten comprobarla.
- Consecuencia: ningún estación-magnitud llega al 100 % del año; el máximo es horas del año − 1.
- **2025-10-26 es anómalo** (`H02` y `H24` inválidos en todas las estaciones): excluirlo de features/targets.

## Validez

Solo `V` genera `value`. `N` (no validado/anulado; el fichero conserva un número que puede ser 0 o no) y `M` (código no
documentado) → `value=null`, `invalid_observation`. Un hueco vacío → `no_observation`. Fechas imposibles (30 de febrero…)
no se pueden convertir a UTC, así que no producen fila y se cuentan en el informe (`rows_impossible_date`; 0 en los datos
reales). Valores negativos con código `V` (66) se conservan y se cuentan como `outliers_flagged`.

## Formatos y diferencias entre años

CSV `;` con cabecera (sin comillas en los ZIP, entrecomillado con BOM en el CSV de 2025) y TXT `,` sin cabecera. El lector
falla con `SchemaError` si cambia el esquema. En los ZIP 2019-2021 el CSV **no contiene todo lo del TXT** (PM2.5/PM10 de las
estaciones 56 y 57) y en 2019-2022 el ozono del TXT está redondeado; la ingesta une ambos formatos con precedencia del CSV.
Detalles y cifras en `madrid_air_quality.md`.

## Estaciones

`stations.geojson`: una `Feature` Point por estación de la capa oficial (24), con `geometry_source` = la capa del Geoportal.
Una estación presente en los datos pero ausente de la capa tendría `geometry: null`; no se inventan coordenadas (hoy
no hay ninguna). El contraste con el CSV de datos.madrid.es detecta una discrepancia de ~790 m en la estación 28079059
(Juan Carlos I); se usa la capa del Geoportal y el otro valor queda en `attributes`. La estación 28079055 (Urb. Embajada)
no aparece en el fichero de 2025.

## Dependencias

Solo `pandas`, `numpy`, `pyarrow`, `duckdb`, `pydantic` (ya en `pyproject.toml`); la descarga usa `urllib` de la biblioteca
estándar. La meteorología y las features están en AT-011 y el tráfico en AT-012 (abajo).

## AT-011: meteorología y tabla `madrid_no2_h6`

```bash
export ATLAS_DATA_DIR=/path/to/exfuzzy-atlas/data   # opcional; por defecto <repo>/data
PYTHONPATH=src python -m atlas.domains.air.meteo --years 2019-2025   # descarga idempotente + observaciones meteo
PYTHONPATH=src python -m atlas.domains.air.features                  # asociación + tabla de features/target
```

Requiere la salida de AT-010. Ver [`madrid_meteo.md`](madrid_meteo.md) (fuente, convención horaria, coordenadas oficiales,
asociación espacial), [`madrid_meteo_quality.md`](madrid_meteo_quality.md) (generado), [`madrid_no2_h6.md`](madrid_no2_h6.md)
(features, convención anti-fuga, split recomendado) y [`madrid_no2_h6_coverage.md`](madrid_no2_h6_coverage.md) (generado).
Código: `meteo.py`, `meteo_report.py`, `association.py`, `features.py`; configuración en `configs/air/madrid_meteo.json` y
`configs/air/madrid_no2_h6.json`; tests en `tests/air/test_meteo.py` y `tests/air/test_features.py`.

## AT-012: tráfico y su correspondencia con las estaciones

```bash
export ATLAS_DATA_DIR=/path/to/exfuzzy-atlas/data
PYTHONPATH=src python -m atlas.domains.air.traffic --months 2023-01:2025-12   # descarga (3,1 GB) + estudio + observaciones horarias
PYTHONPATH=src python -m atlas.domains.air.traffic_features --write-spec      # tabla madrid_no2_h6_traffic + feature_spec_traffic.json
```

Requiere la salida de AT-010 y de AT-011 (la tabla base, solo para comprobar la unión 1:1). Un mes cada vez, DuckDB a 1 GB y 2 hilos (pico medido 1,04 GB de RSS en la
ingesta y 0,95 GB en las features; unos 4 minutos). Ver [`madrid_traffic.md`](madrid_traffic.md) (fuente, esquema y unidades
verificados, horario, estudio de correspondencia espacial con distancias, calidad, limitaciones; generado) y
[`madrid_no2_h6_traffic.md`](madrid_no2_h6_traffic.md) (cobertura de la tabla de features; generado). La tabla es **aparte** de `madrid_no2_h6`
(mismas claves `entity_id`, `issued_at_utc`; unión 1:1) para medir con y sin tráfico sobre filas idénticas. Un punto de medida es un tramo de calle y la
asociación (≤ 500 m, fichero de ubicación del mismo mes) es una aproximación; correlación no es causalidad.
Código: `traffic.py`, `traffic_points.py`, `traffic_features.py`, `traffic_report.py`; configuración en `configs/air/madrid_traffic.json`
y `configs/air/feature_spec_traffic.json`; tests en `tests/air/test_traffic*.py`.

## AT-070: Alemania como segundo territorio (EEA + DWD)

```bash
export ATLAS_DATA_DIR=/path/to/exfuzzy-atlas/data
PYTHONPATH=src python -m atlas.domains.air.eea_ingest --years 2019-2025   # NO2 horario de la EEA (E1a/E2a)
PYTHONPATH=src python -m atlas.domains.air.dwd_ingest                      # meteorología horaria del DWD
PYTHONPATH=src python -m atlas.domains.air.de_features                     # tabla de_no2_h6 (mismas columnas que madrid_no2_h6)
```

Fuentes, licencias, convención horaria, tope de distancia meteorológica, splits y bandas EAQI: [`germany.md`](germany.md). Informes
generados: [`de_eea_air_quality.md`](de_eea_air_quality.md), [`de_dwd_meteo_quality.md`](de_dwd_meteo_quality.md),
[`de_no2_h6_quality.md`](de_no2_h6_quality.md). Código: `eea_download.py`, `eea_ingest.py`, `dwd_download.py`, `dwd_ingest.py`,
`de_features.py`, `de_report.py` (y `features.py`, ahora gobernado por la configuración de la tarea); configuración en
`configs/air/de_eea.json`, `de_dwd.json`, `de_no2_h6.json`, `eaqi_no2_scheme.json`, `attribution_de.json`; tests en `tests/air/test_de_*.py`.
