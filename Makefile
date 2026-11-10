# PYTHON: the interpreter of the environment where the project is installed (make test PYTHON=/path/to/python).
PYTHON ?= python

# Contract v0.7: the dependency is ex-fuzzy 3.4.0 from PyPI (pyproject.toml; the first release with the mixture of
# rules), installed in CI and in the dev env. EXFUZZY_SRC = an ex-fuzzy checkout to use instead (docs/reproduce.md): it
# goes first on PYTHONPATH of every target and its commit is recorded in every manifest. Empty = the installed ex_fuzzy.
EXFUZZY_SRC ?=
export EXFUZZY_SRC
export PYTHONPATH := $(if $(EXFUZZY_SRC),$(EXFUZZY_SRC):)src:apps/api
FIT_PYTHONPATH := $(PYTHONPATH)
# Where the Water model of the FX retrain is fitted and published (see docs/ml/fx_retrain_with_fixed_exfuzzy.md).
ATLAS_ARTIFACTS_DIR ?= $(CURDIR)/artifacts
ATLAS_DATA_DIR ?= $(CURDIR)/data
WATER_FEATURES = $(ATLAS_DATA_DIR)/processed/water

.PHONY: test lint schemas fixtures api api-artifacts publish-demo publish-demo-class demo reproduce qa qa-web qa-volume explain \
	exfuzzy-info export-static fit-water-unique publish-water-unique fx2-checks fit-fx2-madrid fit-fx2-nyc fit-lc

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check .

# Regenerate the committed JSON Schemas from the Pydantic contracts.
schemas:
	$(PYTHON) scripts/export_schemas.py

# Regenerate the synthetic contract fixtures (computed with the real ex_fuzzy engine).
fixtures:
	$(PYTHON) scripts/make_fixtures.py

# Mock API over the synthetic fixtures: http://127.0.0.1:8000/docs
api:
	$(PYTHON) -m uvicorn atlas_api.main:app --reload --port 8000

# Same API over published models (artifacts/published by default; see docs/api.md).
api-artifacts:
	ATLAS_API_MODE=artifacts $(PYTHON) -m uvicorn atlas_api.main:app --reload --port 8000

# A synthetic published model, to try artifacts mode before a real one exists:
#   make publish-demo && ATLAS_PUBLISHED_DIR=artifacts/published-demo/published make api-artifacts
publish-demo:
	$(PYTHON) -m atlas.services.synthetic --out artifacts/published-demo

# Same, with a synthetic winning-rule classifier (contract v0.3):
#   make publish-demo-class && ATLAS_PUBLISHED_DIR=artifacts/published-demo-class/published make api-artifacts
publish-demo-class:
	$(PYTHON) -m atlas.services.synthetic --out artifacts/published-demo-class --task classification

# One command, no credentials: the API in artifacts mode over the published models + the built web (AT-060).
#   API http://127.0.0.1:8000 (docs at /docs), web http://127.0.0.1:4173; Ctrl-C stops both.
#   ATLAS_PUBLISHED_DIR picks another published directory (default artifacts/published); WEB_PORT=<n> moves the web.
#   ATLAS_API_WORKERS=<n> sets the uvicorn workers (default 2; each has its own caches). No --reload (that is `make api`).
demo:
	PYTHON=$(PYTHON) scripts/qa/demo.sh

# The raw-data -> published chain for the three tasks. `make reproduce` lists it;
#   make reproduce ARGS=--check   dry run (modules, options, configs, inputs)      make reproduce ARGS=--smoke
#   make reproduce ARGS="--run --yes"   run everything (hours); add --only madrid|nyc|water
reproduce:
	PYTHON=$(PYTHON) EXFUZZY_SRC=$(EXFUZZY_SRC) scripts/qa/reproduce.sh $(ARGS)

# Contract v0.6.2: Claude writes the explanation of a published model's rule base (configs/explanations/<id>.json)
# from configs/explanations/TEMPLATE.md and the model's published files; needs the `claude` CLI, logged in.
#   make explain MODEL_ID=exfuzzy-madrid_no2_h6-ica4-yday-seed1      add EXPLAIN_ARGS=--dry-run to see the prompt
explain:
	$(PYTHON) scripts/explain_model.py --model-id $(MODEL_ID) $(EXPLAIN_ARGS)

# AT-062: QA over the real published models (skips with a reason when there are none).
qa:
	$(PYTHON) -m pytest tests/integration -q -rs

# AT-061: volume budget (1M input rows, 21M activation records; builds a model in a temp dir, ~40 s; needs psutil).
#   ATLAS_VOLUME_DIR=<scratch>/published reuses a model built by scripts/qa/volume.py; the full measurement is
#   `scripts/qa/volume.py all --out <scratch>` (docs/qa/volume.md).
qa-volume:
	ATLAS_QA_VOLUME=1 $(PYTHON) -m pytest tests/integration/test_volume_budget.py -q -rs

# Same plus the browser smoke (needs the built web, Chrome and the published models); see docs/qa/README.md.
qa-web:
	ATLAS_QA_WEB=1 $(PYTHON) -m pytest tests/integration/test_web_smoke.py -q -rs

# Static export of the demo (docs/static_export.md): gzip JSON files for a fully static site, built from the published models.
#   make export-static OUT=<dir> [PUBLISHED=<published dir>] [ARGS="--tasks nyc_pickups_h1,uk_water_do --groups static,days"]
PUBLISHED ?= $(ATLAS_ARTIFACTS_DIR)/published
OUT ?= $(ATLAS_ARTIFACTS_DIR)/static-export
export-static:
	$(PYTHON) -u -m atlas.services.static.export --published-dir $(PUBLISHED) --out $(OUT) $(ARGS)

# Which ex_fuzzy these targets import and the version string Atlas records for it:
#   make exfuzzy-info                                  the pinned PyPI library: 3.4.0
#   make exfuzzy-info EXFUZZY_SRC=<ex-fuzzy checkout>  e.g. 3.4.0+g10d811b (".dirty" if the checkout has local changes)
exfuzzy-info:
	PYTHONPATH=$(FIT_PYTHONPATH) $(PYTHON) -c "import ex_fuzzy; from atlas.ml.exfuzzy_features import exfuzzy_version; print(ex_fuzzy.__file__, exfuzzy_version())"

# Water TSK with unique_antecedents (FX Experiment 2, arm `unique`): needs EXFUZZY_SRC (upstream PR 30 and later).
# Writes artifacts/uk_water_do/fx-w-unique-seed{0,1,2}; `select` is resumable, `final` reads the test period.
fit-water-unique:
	PYTHONPATH=$(FIT_PYTHONPATH) ATLAS_DATA_DIR=$(ATLAS_DATA_DIR) ATLAS_ARTIFACTS_DIR=$(ATLAS_ARTIFACTS_DIR) \
	$(PYTHON) -m atlas.ml.experiment_water select --config configs/ml/fx_water_do_chrono_temp_unique_experiment.json
	PYTHONPATH=$(FIT_PYTHONPATH) ATLAS_DATA_DIR=$(ATLAS_DATA_DIR) ATLAS_ARTIFACTS_DIR=$(ATLAS_ARTIFACTS_DIR) \
	$(PYTHON) -m atlas.ml.experiment_water final --config configs/ml/fx_water_do_chrono_temp_unique_experiment.json

# Publishes seed 0 of that arm as the served uk_water_do model; the previously published model directories stay.
publish-water-unique:
	PYTHONPATH=$(FIT_PYTHONPATH) ATLAS_DATA_DIR=$(ATLAS_DATA_DIR) ATLAS_ARTIFACTS_DIR=$(ATLAS_ARTIFACTS_DIR) \
	$(PYTHON) -m atlas.services.publish --run-dir $(ATLAS_ARTIFACTS_DIR)/uk_water_do/fx-w-unique-seed0 \
	  --features $(WATER_FEATURES)/features/uk_water_do --entities $(WATER_FEATURES)/entities.geojson \
	  --feature-spec configs/water/feature_spec.json --from 2024-01-01T00:00:00Z --to 2026-01-01T00:00:00Z \
	  --task-id uk_water_do --title "River dissolved oxygen (UK)" --irregular-times \
	  --metadata configs/water/attribution.json --published-dir $(ATLAS_ARTIFACTS_DIR)/published --replace

# FX2 (docs/ml/fx2_proportional_remap.md): hour vocabularies with the proportional term remap. All three targets need
# EXFUZZY_SRC (the local build at 915b836 or later: PR 35). Validation only; the test period is read by hand for an arm that enters.
FX2 = PYTHONPATH=$(FIT_PYTHONPATH) ATLAS_DATA_DIR=$(ATLAS_DATA_DIR) ATLAS_ARTIFACTS_DIR=$(ATLAS_ARTIFACTS_DIR) OMP_NUM_THREADS=4 $(PYTHON)
FX2_MADRID_SEL = $(ATLAS_ARTIFACTS_DIR)/madrid_no2_h6/experiments/ica2-justified/selection.json
FX2_NYC_SEL = $(ATLAS_ARTIFACTS_DIR)/nyc_pickups_h1/experiments/level-rel7/selection.json

# Reproduction checks A (equal-count digest; compare with the same command on 2ffcfb9), B (remap undone) and D (Water).
fx2-checks:
	$(FX2) -m atlas.ml.fx2_clip_check digest
	$(FX2) -m atlas.ml.fx2_clip_check select --config configs/ml/fx2_madrid_no2_h6_hour4_clip_check_experiment.json
	$(FX2) -m atlas.ml.experiment_water select --config configs/ml/fx2_water_do_chrono_temp_repro_experiment.json
	$(FX2) -m atlas.ml.experiment_water final --validation-only --config configs/ml/fx2_water_do_chrono_temp_repro_experiment.json

fit-fx2-madrid:
	$(FX2) -m atlas.ml.experiment_class select --config configs/ml/fx2_madrid_no2_h6_hour4_control_experiment.json
	$(FX2) -m atlas.ml.experiment_class final --validation-only --no-baselines --config configs/ml/fx2_madrid_no2_h6_hour4_control_experiment.json
	$(FX2) -m atlas.ml.experiment_class final --validation-only --no-baselines --config configs/ml/fx2_madrid_no2_h6_hour5_fixed_experiment.json \
	  --selection $(FX2_MADRID_SEL)
	$(FX2) -m atlas.ml.experiment_class select --config configs/ml/fx2_madrid_no2_h6_hour5_experiment.json
	$(FX2) -m atlas.ml.experiment_class final --validation-only --no-baselines --config configs/ml/fx2_madrid_no2_h6_hour5_experiment.json

fit-fx2-nyc:
	$(FX2) -m atlas.ml.experiment_nyc final --validation-only --no-baselines --config configs/ml/fx2_nyc_pickups_h1_hour4_control_experiment.json \
	  --selection $(FX2_NYC_SEL)
	for k in 5 6; do \
	  $(FX2) -m atlas.ml.experiment_nyc final --validation-only --no-baselines \
	    --config configs/ml/fx2_nyc_pickups_h1_hour$${k}_fixed_experiment.json --selection $(FX2_NYC_SEL); done
	for k in 5 6; do \
	  $(FX2) -m atlas.ml.experiment_nyc select --config configs/ml/fx2_nyc_pickups_h1_hour$${k}_experiment.json; \
	  $(FX2) -m atlas.ml.experiment_nyc final --validation-only --no-baselines --config configs/ml/fx2_nyc_pickups_h1_hour$${k}_experiment.json; done

# AT-041g learning curve (docs/ml/madrid_no2_h6_learning_curve.md): validation only, pinned ex_fuzzy, 4 threads.
#   make fit-lc LC_ARGS="feasibility"      make fit-lc LC_ARGS="fit --arms n30k n60k n120k"      (add --backend pymoo)
LC_CONFIG ?= configs/ml/madrid_no2_h6_learning_curve.json
fit-lc:
	OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MKL_NUM_THREADS=4 PYTHONPATH=$(FIT_PYTHONPATH) \
	  ATLAS_ARTIFACTS_DIR=$(ATLAS_ARTIFACTS_DIR) ATLAS_DATA_DIR=$(ATLAS_DATA_DIR) \
	  $(PYTHON) -m atlas.ml.learning_curve $(LC_ARGS) --config $(LC_CONFIG)
