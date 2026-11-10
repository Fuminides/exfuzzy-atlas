# Rutas de datos

Actualizar este fichero cada vez que se descargue o mueva un dataset.

## Raíz de datasets

Los datos raw se descargan **fuera del repo**, en una raíz de datasets por máquina, un directorio por fuente
(`<raíz>/<source_id>`). La raíz es `ATLAS_DATASETS_ROOT` (o `--datasets-root` en cada CLI de ingesta) y, si no se da,
`~/Datasets` (`atlas.paths.DEFAULT_DATASETS_ROOT`).

```bash
export ATLAS_DATASETS_ROOT=/ruta/a/Datasets   # opcional; por defecto ~/Datasets
```

## Cómo encuentra los datos este repo

El código lee `data/raw/<source>/`, que es un symlink a `<raíz>/<source>`. Las CLI de ingesta lo crean si falta; a mano,
en cada checkout o worktree:

```bash
mkdir -p data/raw
ln -s "${ATLAS_DATASETS_ROOT:-$HOME/Datasets}/madrid-air" data/raw/madrid-air
```

`data/processed/` y `artifacts/` se generan en cada checkout y git los ignora. `ATLAS_DATA_DIR` y `ATLAS_ARTIFACTS_DIR` permiten moverlos
(por ejemplo, para compartir el `data/` del checkout principal entre worktrees).

## Fuentes

| source_id | Dominio | Directorio | Estado |
|---|---|---|---|
| `madrid-air` | air | `<raíz>/madrid-air` | descargado 2026-10-30: ZIP anuales 2019-2024 + CSV «desde 2025» + intérprete PDF (~54 MB, `source_manifest.json`); ver `docs/air/README.md` |
| `madrid-meteo` | air | `<raíz>/madrid-meteo` | descargado 2026-10-30: 146 ficheros (~89 MB). CSV y TXT mensuales de 2019-2024, un CSV «desde 2025», el PDF intérprete y `source_manifest.json`. CC BY 4.0. El portal bloquea (403) tras unas 22 peticiones rápidas; `http_fetch` espacia las peticiones y reintenta. Ver `docs/air/madrid_meteo.md` |
| `madrid-meteo-stations` | air | `<raíz>/madrid-meteo-stations` | descargado 2026-10-30: CSV oficial con las 26 ubicaciones de sensores, más el PDF de estructura |
| `madrid-traffic` | air | `<raíz>/madrid-traffic` | descargado 2026-10-30: 36 zips mensuales 2023-01..2025-12 con registros de 15 min (3,1 GB, un CSV de ~750 MB por zip), PDF de estructura y `source_manifest.json`; solo lectura. CC BY 4.0. Ver `docs/air/madrid_traffic.md` |
| `madrid-traffic-points` | air | `<raíz>/madrid-traffic-points` | descargado 2026-10-30: 36 CSV mensuales con la ubicación de los puntos de medida (24,7 MB), PDF y `source_manifest.json`. El conjunto de puntos cambia cada mes |
| `madrid-air-stations` | air | `<raíz>/madrid-air-stations` | descargado 2026-10-30: capa Geoportal (GeoJSON, 24 estaciones) + CSV datos.madrid.es (~0,3 MB, `source_manifest.json`) |
| `uk-water-quality` | water | `<raíz>/uk-water-quality` | descargado 2026-10-30: páginas crudas de la API Water Quality Explorer (ríos de Northumberland & Tyne, 2015-2025; CSV de observaciones, JSON-LD de puntos, codelist de unidades; unos 23 MB, `source_manifest.json`, solo lectura). OGL v3.0. Ver `docs/water/README.md` |
| `nyc-tlc` | mobility | `<raíz>/nyc-tlc` | descargado 2026-10-30: yellow 2024-04..2025-03 (Parquet, 42,8 M viajes) + taxi_zone_lookup.csv + taxi_zones.zip (shapefile EPSG:2263) + diccionario PDF (~690 MB, `source_manifest.json`; el PDF de nyc.gov va en `manual/` porque el servidor responde 403 a clientes automáticos); ver `docs/mobility/README.md` |
| `eea-air-de` | air | `<raíz>/eea-air-de` | NO₂ horario de Alemania, EEA Air Quality Download Service (E1a verificados + E2a actualizados), 2019-2025, más metadatos de estaciones y vocabularios (≈ 0,9 GB, `source_manifest.json`, solo lectura). CC BY 4.0. Ver `docs/air/germany.md` |
| `dwd-meteo-de` | air | `<raíz>/dwd-meteo-de` | Observaciones horarias del DWD Climate Data Center (temperatura y humedad, viento, presión) de las estaciones alemanas (≈ 1,5 GB, `source_manifest.json`, solo lectura). CC BY 4.0. Ver `docs/air/germany.md` |

URLs, licencias y advertencias en `DATA_SOURCES.md`.

## Reglas

1. Descargar en la raíz de datasets de la máquina, nunca dentro del repo ni en `artifacts/`.
2. Cada directorio de fuente contiene `source_manifest.json` (`atlas.contracts.SourceManifest`) con el sha256 de cada fichero.
3. Lo raw es inmutable. Las correcciones van en la capa normalizada (`data/processed`).
4. Comprobar `free -g` antes de un ETL largo si la RAM se comparte con otros jobs; el ETL va en streaming (DuckDB con `memory_limit`).
