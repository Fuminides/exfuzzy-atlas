# ExFuzzy Atlas

An atlas of fuzzy rules over open environmental and urban data. It uses the Python library [`ex_fuzzy`](https://github.com/Fuminides/ex-fuzzy) to learn rules, and shows **where and when each rule fires**, on official geometries and with traces you can check. It is not a generic map with a table beside it. It is a separate project from ExFuzzy Lab.

**Demo:** <https://fuminides.github.io/exfuzzy-atlas/> (coming soon).

Domains: **Air** (NO₂ in Germany, EEA data), **Water** (river water quality in England) and **Mobility** (yellow taxi demand in New York City). Madrid, the first domain, was taken out of the demo on 2026-11-09: its models did not clearly beat repeating yesterday's category at the same hour (`docs/ml/madrid_no2_h6_ica_v4.md`, `docs/ml/rule_mixture.md`). Its data, code and models are still in the repository.

Most of the project documents are in Spanish; the ML reports in `docs/ml/` are in English. The web app is in Spanish and English.

## Status

Data and API contract v0.7 (`CONTRACTS.md`), with ex-fuzzy 3.4.0 from PyPI. The published models are fitted on real data. They are not in git: the chain in `docs/reproduce.md` builds them. Without them, the API serves the synthetic fixtures in `fixtures/synthetic/`, which carry `synthetic: true`.

## Quick start

Python 3.10 or later (CI uses 3.12) and Node 24:

```bash
pip install -e ".[dev]"
make test    # PYTHON=/path/to/python to use another interpreter (default: python)
make api     # mock API over the synthetic fixtures at http://127.0.0.1:8000/docs
cd apps/web && npm ci && npm run dev   # the web app, with `make api` running
```

Every `make` target runs with `$(PYTHON)`, so `PYTHON` can point to any interpreter where the project is installed. With published models in `artifacts/published`, `make demo` serves them through the API together with the built web app. `docs/reproduce.md` has more commands, the data downloads and the model fits; `LLM_help/DATASETS_PATHS.md` says where the data go.

## Documents

| File | Contents |
|---|---|
| `AGENTS.md` | Contributor guide: invariants, languages, protocol, memory limits |
| `MASTER_PLAN.md` | Product, goals, phases and risks |
| `MAP_EXPERIENCE.md` | Specification of the rule atlas: Rule Spotlight, timeline and semantics |
| `CONTRACTS.md` | Data and API contract (§7 onwards: amendments) |
| `docs/architecture.md` | Decisions: stack, environment, data, basemap, compute and workflow |
| `DATA_SOURCES.md`, `ATTRIBUTION.md`, `LLM_help/DATASETS_PATHS.md` | Sources, licences, attribution and where the data are stored |

## Data and credits

- **Air, Germany:** European Environment Agency (EEA), Air Quality Download Service, data reported by Germany (CC BY 4.0); meteorology from Deutscher Wetterdienst (DWD), Climate Data Center (CC BY 4.0).
- **Water, England:** contains public sector information licensed under the Open Government Licence v3.0, © Environment Agency.
- **Mobility, New York City:** derived from NYC Taxi & Limousine Commission (TLC) Trip Record Data. The pickup counts by zone and hour and the predictions are the author's own work, not produced or endorsed by NYC or the TLC.
- **Air, Madrid** (in the code, not in the demo): Ayuntamiento de Madrid open data (CC BY 4.0).
- **Basemap:** OpenFreeMap © OpenMapTiles · © OpenStreetMap contributors (ODbL).

`ATTRIBUTION.md` and `DATA_SOURCES.md` give the licences, the attribution texts and the dates they were checked.

## Licence and citation

AGPL-3.0-or-later (see `LICENSE`). Each data source keeps its own licence and attribution. To cite Atlas, use `CITATION.cff`. Atlas builds on [ex-fuzzy](https://github.com/Fuminides/ex-fuzzy) (Fumanal-Idocin and Andreu-Perez, *Neurocomputing*, 2024, doi:10.1016/j.neucom.2024.128048).
