# CLAUDE.md — ExFuzzy Atlas

`AGENTS.md` es la guía principal: invariantes, idiomas, protocolo, límites de memoria e informe final. Léelo antes de nada, y también `CONTRACTS.md` (§7) y `docs/architecture.md`.

## Comandos

- `make test` / `make lint`: pytest y ruff, con `$(PYTHON)` (por defecto `python`) y `PYTHONPATH=src:apps/api`.
- `make schemas` / `make fixtures`: regeneran los JSON Schema y `fixtures/synthetic/`. Hay un test que falla si los ficheros commiteados están desfasados.
- `make api`: API mock (FastAPI) sobre las fixtures sintéticas.

## Mapa del código

- `src/atlas/contracts/`: contrato normativo (Pydantic + esquema Arrow de observaciones + validador DuckDB). Cualquier cambio exige subir `SCHEMA_VERSION`.
- `apps/api/atlas_api/`: API v1. `mock_store.py` agrega rule-map en el backend a partir de las trazas.
- `scripts/make_fixtures.py`: genera fixtures dorados con el motor real de ex_fuzzy (`RuleBaseT1Regression`).
- `src/atlas/domains/{air,water,mobility}`: ingesta y features por dominio; `src/atlas/ml`, `src/atlas/explain`: ajuste y explicación; `src/atlas/services`: publicación; `apps/web`: la web.
- La web sigue `DESIGN.md` (Steep: serif sobre papel blanco; al final, «Atlas additions» con lo propio de Atlas). Los tokens están en `apps/web/src/styles.css`.

## Lo que más se rompe

- **Firing ≠ probabilidad / contribución / riesgo.** La t-norma la decide el modelo (producto por defecto en ex_fuzzy 3.3.1).
- **`0` ≠ `null`.** Un null siempre lleva `missing_reason`.
- **Nada de superficies estimadas** ni de coordenadas fabricadas.
- **Sin fugas temporales:** solo se usan entradas observadas hasta `issued_at`, y el split se hace con embargo ≥ horizonte.
- **RAM:** en una máquina de ~15 GB compartida suele haber unos 4 GB libres. ETL en streaming con DuckDB y `memory_limit`; tests de fichero en fichero; los ajustes grandes, en una máquina remota con más memoria (ver `AGENTS.md`).
