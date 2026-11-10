# Arquitectura y decisiones ratificadas

**Fecha:** 2026-10-30 · **Contrato:** schema v0.1.0 · Cada decisión puede revisarse con un PR que la cite.

## D1 — Licencia

Atlas es **AGPL-3.0-or-later**, igual que `ex_fuzzy`. Ojo: la metadata upstream es inconsistente (`LICENSE` y PyPI dicen AGPL-3.0-or-later; `setup.py` dice GPL-3.0). Tomamos la más restrictiva. Antes de un despliegue público, revisar la obligación de ofrecer el código fuente a los usuarios del servicio (AGPL §13).

## D2 — Stack

| Capa | Elección |
|---|---|
| Python | ≥ 3.10 (CI en 3.12) |
| Motor de reglas | `ex-fuzzy==3.5.0` de PyPI (condiciones ordinales «al menos / como mucho» y términos compuestos, PR 45; contrato v0.8; la 3.4.0 fue la primera con la mezcla de reglas y su poda, PR 44; contrato v0.7); antes `ex_fuzzy==3.3.1` de PyPI. Ver `docs/reproduce.md` |
| Datos | Parquet + DuckDB (+ pyarrow, pandas). Particionado hive `year=/month=` |
| Contratos | Pydantic v2 → JSON Schema exportado (`make schemas`) |
| API | FastAPI, solo GET por ahora; servicio de artefactos precalculados |
| Web | React + TypeScript (strict) + Vite + **MapLibre GL JS**. deck.gl fuera del MVP |

## D3 — Entorno

- **Entorno de Python:** el Makefile usa `PYTHON` (por defecto `python`); en una máquina compartida, mejor un entorno común que un venv por proyecto. Los paquetes que falten se instalan ahí y se declaran en `pyproject.toml`.
- **Sin instalación editable:** `PYTHONPATH=src:apps/api` (lo fijan el Makefile y pytest), así cada git worktree importa su propio código.
- **CI:** usa un entorno limpio con `pip install -e .[dev]`.

## D4 — Estructura

Es la de `MASTER_PLAN.md` §6, con dos añadidos:

- `fixtures/synthetic/`: payloads sintéticos que comparten tests, API mock y web. Los genera `scripts/make_fixtures.py` con el motor real de ex_fuzzy.
- `LLM_help/`: dónde van los datos (raíz de datasets, enlaces `data/raw/`).

## D5 — Datos

- **Raw:** en la raíz de datasets de la máquina, un directorio por fuente (`LLM_help/DATASETS_PATHS.md`). Junto a los ficheros va un `source_manifest.json` (`SourceManifest`: URL, licencia, fecha y sha256). Lo raw no se modifica.
- **En el repo:** `data/raw/<source>` es un symlink a ese directorio. `data/processed/` y `artifacts/` son regenerables y están ignorados por git.
- **Contrato:** las observaciones canónicas publicadas deben pasar `atlas.contracts.validate_observations` (DuckDB, memoria acotada).

## D6 — Contratos

- **Forma normativa:** `src/atlas/contracts/models.py` y `observations.py`. Si `CONTRACTS.md` y el código discrepan, manda el código y se corrige el documento en el mismo PR. Las enmiendas v0.1 están en `CONTRACTS.md` §7.
- **Cambios:** se sube `SCHEMA_VERSION`, se ejecuta `make schemas fixtures` y se añade un test de compatibilidad, en un PR propio.

## D7 — API

- **Ahora (modo mock):** sirve `fixtures/synthetic/` y todo lleva `synthetic: true`.
- **Después (modo artifacts):** leerá vistas precalculadas por `model_id + data_version` (Parquet/DuckDB).
- **Límites:** nunca entrena ni optimiza durante una petición. Las agregaciones se hacen en el backend y el frontend no recalcula firing.

## D8 — Mapa base

- **Desarrollo:** estilo **OpenFreeMap Positron** (`https://tiles.openfreemap.org/styles/positron`), sin clave. Los datos son de OpenStreetMap (ODbL) y la atribución es obligatoria.
- **Configuración:** la URL se cambia con `VITE_BASEMAP_STYLE_URL`, y la UI tiene que seguir funcionando sin mapa base (fondo liso).
- **Antes de un despliegue público:** revisar los términos o servir PMTiles propios (Protomaps).

## D9 — Cómputo

- **Estación de trabajo** (*the workstation* en los informes en inglés): 12 núcleos y 15 GB de RAM compartida con otros jobs; suele haber unos 4 GB libres. Tiene una GPU de 8 GB.
- **Máquina grande** (*the large machine*): una máquina remota aarch64 de 20 CPU y 121 GB de RAM para los ajustes que no caben en la estación de trabajo; los directorios de run se copian de vuelta.
- **ETL:** en streaming con DuckDB y `memory_limit` explícito (≤ 3 GB); no se cargan históricos completos en pandas.
- **GA de ex_fuzzy:** en CPU (`backend="pymoo"`), salvo que un benchmark justifique `evox`/GPU.
- **Clúster:** un clúster HPC (SGE) está disponible, pero no está planificado. Los jobs pesados se coordinan para no coincidir en la misma máquina.

## D10 — Flujo de trabajo

- **Ramas:** una por issue o tarea, en un worktree propio (`git worktree add`).
- **PRs:** a `main`; el mantenedor revisa y fusiona con la CI en verde.
- **Contenido del PR:** el que pide `AGENTS.md` (contexto, archivos, comandos, evidencia, limitaciones y siguiente paso).
