# Atlas Water: ingesta de la API Water Quality Explorer (AT-020)

Qué hay y cómo reproducirlo. Hechos de la API: [`api_notes.md`](api_notes.md). Perfil de datos y problemas candidatos:
[`profile.md`](profile.md) (generado).

## Rebanada

Environment Agency, región North East, área `X` (Northumberland, Durham and Tees), sub-área `H` (Northumberland & Tyne), puntos de tipo `F6`
(ríos de agua dulce), 2015-2025, determinandos `9924` oxígeno disuelto, `0111` nitrógeno amoniacal, `0180` ortofosfato reactivo y,
desde AT-021, `0061` pH y `0076` temperatura del agua (configuración en `configs/water/uk_water_quality.json`). La razón de la elección
está en el perfil (§1).

## Tarea de ML (AT-021)

`uk_water_do`: oxígeno disuelto inferido de lo que se mide en la misma muestra (inferencia descriptiva, **no un pronóstico**). Tarjeta de datos y
viabilidad: [`water_feasibility.md`](water_feasibility.md). Configuración: `configs/water/uk_water_do.json`; especificación de features:
`configs/water/feature_spec.json`; código: `src/atlas/domains/water/features.py`.

```bash
PYTHONPATH=src python -m atlas.domains.water.features --write-spec   # data/processed/water/features/uk_water_do/
```

## Reproducción

```bash
export ATLAS_DATA_DIR=/path/to/exfuzzy-atlas/data      # datos compartidos entre worktrees (opcional)
ln -s "${ATLAS_DATASETS_ROOT:-$HOME/Datasets}/uk-water-quality" data/raw/uk-water-quality   # una vez; el CLI lo crea si falta

PYTHONPATH=src python -m atlas.domains.water.ingest --counts   # descarga (≈ 125 peticiones, ≈ 1 min) y normaliza
PYTHONPATH=src python -m atlas.domains.water.profile           # escribe docs/water/profile.md
PYTHONPATH=src python -m atlas.domains.water.ingest --skip-download   # solo normaliza desde la caché: 0 peticiones
```

Opciones: `--years 2019-2020`, `--download-only`, `--refresh` (vuelve a bajar todo: instantánea nueva del archivo), `--out-dir`.

## Salidas

| Ruta | Contenido |
|---|---|
| `$ATLAS_DATASETS_ROOT/uk-water-quality/` | Páginas crudas inmutables (solo lectura), `request.json` por consulta y `source_manifest.json` con sha256 (≈ 23 MB) |
| `data/processed/water/observations/year=/month=/` | Observaciones canónicas (Parquet, hive, año/mes UTC). Pasan `validate_observations` |
| `data/processed/water/entities.geojson` | `EntityCollection`: puntos de muestreo, `observed_point`, WGS84 |
| `data/processed/water/quality_report.json` | `QualityReport` |
| `data/processed/water/ingest_details.json` | Contadores, conciliación por año, DST, duplicados |
| `data/processed/water/features/uk_water_do/` | Tabla de features y target de AT-021 (Parquet hive `year=/month=`), con `uk_water_do_feature_report.json` y `uk_water_do_spatial_split.json` |

Columnas añadidas a las del contrato (el validador las tolera): `sample_id` (`{punto}/{n}`), `observation_id`, `determinand_code`,
`result_raw` (texto original, p. ej. `<0.03`), `unit_label`, `sampling_purpose`, `sample_material`.

## Decisiones

- **Una fila por muestra x determinando.** `sample_id` y `observation_id` se conservan; la clave única del contrato
  (`entity_id`, `timestamp_utc`, `feature_name`) no se repite en esta rebanada. Si se repitiera (réplicas en el mismo instante), se
  conserva la de menor `observation_id` y se cuenta en `duplicate_rows`.
- **Censura:** `<x` da `value = x`, `censoring = left`; `>x`, `right`. Un valor ausente o ilegible es `null` con `missing_reason`.
- **Hora:** la API da hora local de Europe/London sin desfase; hora repetida de otoño = primera aparición (BST), hora inexistente de
  primavera = desfase previo (GMT). Ambas se cuentan.
- **Sin bandera de validez:** `validity_flag` es nulo en todas las filas; la API no la publica.
- **Fixtures de pruebas** (`tests/water/fixtures/`): extractos reales de la API (OGL v3.0), unas pocas filas.
