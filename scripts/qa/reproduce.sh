#!/usr/bin/env bash
# The whole chain, raw data -> ingest -> features -> train -> publish, for the three MVP tasks (AT-060).
#
#   scripts/qa/reproduce.sh              list the stages with their commands, times and peak RSS (touches nothing)
#   scripts/qa/reproduce.sh --check      dry run: every module, config and input exists or is produced by an earlier stage
#   scripts/qa/reproduce.sh --smoke      --check, then publish the existing Water run into a temp dir and verify it
#   scripts/qa/reproduce.sh --run --yes  execute every stage in order (hours of CPU, ~5 GB of downloads; see the list)
#   scripts/qa/reproduce.sh --run --yes --only water    only the stages of one task: madrid | germany | nyc | water
#
# Locations: ATLAS_DATA_DIR (default <repo>/data) and ATLAS_ARTIFACTS_DIR (default <repo>/artifacts), as in atlas.paths.
# EXFUZZY_SRC: an ex_fuzzy checkout to use instead of the installed one (docs/reproduce.md), first on PYTHONPATH. Empty =
# the installed ex_fuzzy, which must be the pinned 3.4.0 (pyproject.toml; it has the mixture of rules).
# Times and RSS are the ones measured in docs/ (a 12-core workstation with ~15 GB RAM, one process); they are not re-measured here.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="${PYTHON:-python}"
D="${ATLAS_DATA_DIR:-$REPO/data}"
A="${ATLAS_ARTIFACTS_DIR:-$REPO/artifacts}"
export PYTHONPATH="${EXFUZZY_SRC:+$EXFUZZY_SRC:}$REPO/src:$REPO/apps/api" ATLAS_DATA_DIR="$D" ATLAS_ARTIFACTS_DIR="$A"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}" OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-4}"

MODE=list; YES=0; ONLY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --check) MODE=check ;; --smoke) MODE=smoke ;; --run) MODE=run ;; --yes) YES=1 ;;
    --only) ONLY="${2:-}"; shift ;;
    -h|--help) sed -n 2,12p "$0"; exit 0 ;;
    *) echo "unknown option $1 (see --help)" >&2; exit 2 ;;
  esac
  shift
done

# --- stage table -------------------------------------------------------------------------------------------------
# Each stage: task | title | python module | arguments | configs in the repo | inputs | outputs | time | peak RSS | doc
IDS=(); declare -A S
stage() { local id="$1"; IDS+=("$id"); S["$id"]="$2"; }
# fields separated by '|' ; lists separated by spaces
stage madrid-1 "madrid|ingest air hourly + stations|atlas.domains.air.ingest|--years 2019-2025|configs/air/madrid_air.json||$D/processed/air/stations.geojson $D/processed/air/observations|35 s|n/a|docs/air/README.md"
stage madrid-2 "madrid|ingest meteo hourly|atlas.domains.air.meteo|--years 2019-2025|configs/air/madrid_meteo.json||$D/processed/air/meteo|24 s (first download ~10 min, portal rate limit)|n/a|docs/air/madrid_meteo.md"
stage madrid-3 "madrid|feature table madrid_no2_h6|atlas.domains.air.features||configs/air/madrid_no2_h6.json|$D/processed/air/observations $D/processed/air/meteo|$D/processed/air/features/madrid_no2_h6/table|4 s|1.8 GB|docs/air/madrid_no2_h6.md"
stage madrid-4 "madrid|train ica4: served models on the common rows|atlas.ml.experiment_ica4|base --config configs/ml/madrid_no2_h6_ica4_experiment.json|configs/ml/madrid_no2_h6_ica4_experiment.json configs/ml/ica_no2_scheme.json configs/ml/madrid_partitions_diurnal.json|$D/processed/air/features/madrid_no2_h6/table|$A/madrid_no2_h6/experiments/ica4/val/base_published.json|10 s|n/a|docs/ml/madrid_no2_h6_ica_v4.md section 8"
stage madrid-5 "madrid|train ica4: round 1, one new input per arm (pre-registered)|atlas.ml.experiment_ica4|arms --config configs/ml/madrid_no2_h6_ica4_experiment.json --workers 10 --only base_refit,no2_clim_valid,no2_expected_valid,no2_expected_valid_ratio,no2_expected_valid_damped,no2_yday_valid,no2_week_valid,no2_mean_24h,no2_max_24h|configs/ml/madrid_no2_h6_ica4_experiment.json|$D/processed/air/features/madrid_no2_h6/table $A/madrid_no2_h6/experiments/ica4/val/base_published.json|$A/madrid_no2_h6/experiments/ica4/val/no2_yday_valid.json|~10 min on a 20-CPU, 121 GB machine (27 fits)|~1 GB per fit|docs/ml/madrid_no2_h6_ica_v4.md section 8"
stage madrid-6 "madrid|train ica4: stage 2 (compact input sets)|atlas.ml.experiment_ica4|stage2 --config configs/ml/madrid_no2_h6_ica4_experiment.json --workers 10|configs/ml/madrid_no2_h6_ica4_experiment.json|$A/madrid_no2_h6/experiments/ica4/val/no2_yday_valid.json|$A/madrid_no2_h6/experiments/ica4/stage2_arms.json|minutes (3 fits)|~1 GB per fit|docs/ml/madrid_no2_h6_ica_v4.md section 8"
stage madrid-7 "madrid|train ica4: rule-base shape|atlas.ml.experiment_ica4|shape --config configs/ml/madrid_no2_h6_ica4_experiment.json --workers 15|configs/ml/madrid_no2_h6_ica4_experiment.json|$A/madrid_no2_h6/experiments/ica4/stage2_arms.json|$A/madrid_no2_h6/experiments/ica4/shape_arms.json|minutes (15 fits)|~1 GB per fit|docs/ml/madrid_no2_h6_ica_v4.md section 8"
stage madrid-8 "madrid|train ica4: rounds 2-3 (post-hoc addenda, committed before their fits)|atlas.ml.experiment_ica4|arms --config configs/ml/madrid_no2_h6_ica4_experiment.json --workers 15 --only r2_power075,r2_power100,r2_minimal,r2_minimal_power100,r3_base_unweighted,r3_yday_unweighted,r3_compact_unweighted,r3_compact_r60a4_unweighted,r3_minimal_unweighted|configs/ml/madrid_no2_h6_ica4_experiment.json|$A/madrid_no2_h6/experiments/ica4/shape_arms.json|$A/madrid_no2_h6/experiments/ica4/val/r3_minimal_unweighted.json|minutes|~1 GB per fit|docs/ml/madrid_no2_h6_ica_v4.md section 8"
stage madrid-9 "madrid|train ica4: decision under the pre-registered rule|atlas.ml.experiment_ica4|decide --config configs/ml/madrid_no2_h6_ica4_experiment.json|configs/ml/madrid_no2_h6_ica4_experiment.json|$A/madrid_no2_h6/experiments/ica4/val/r3_minimal_unweighted.json|$A/madrid_no2_h6/experiments/ica4/decision.json|seconds|n/a|docs/ml/madrid_no2_h6_ica_v4.md section 8"
stage madrid-10 "madrid|train ica4: robustness (5 seeds)|atlas.ml.experiment_ica4|robust --config configs/ml/madrid_no2_h6_ica4_experiment.json --workers 4|configs/ml/madrid_no2_h6_ica4_experiment.json|$A/madrid_no2_h6/experiments/ica4/decision.json|$A/madrid_no2_h6/experiments/ica4/fits|minutes|~1 GB per fit|docs/ml/madrid_no2_h6_ica_v4.md section 8"
stage madrid-11 "madrid|train ica4: test 2025, read once (a TEST_READ marker refuses a second read)|atlas.ml.experiment_ica4|final --test --config configs/ml/madrid_no2_h6_ica4_experiment.json|configs/ml/madrid_no2_h6_ica4_experiment.json|$A/madrid_no2_h6/experiments/ica4/decision.json|$A/madrid_no2_h6/experiments/ica4/final_test.json|minutes|n/a|docs/ml/madrid_no2_h6_ica_v4.md section 8"
stage madrid-12 "madrid|run directory of the published seed (pruned, scored on the task rows)|atlas.ml.experiment_ica4|publish-runs --config configs/ml/madrid_no2_h6_ica4_experiment.json --publish-config configs/ml/madrid_no2_h6_ica4_publish_experiment.json|configs/ml/madrid_no2_h6_ica4_experiment.json configs/ml/madrid_no2_h6_ica4_publish_experiment.json|$A/madrid_no2_h6/experiments/ica4/final_test.json|$A/madrid_no2_h6/ica4-yday-seed1/SHA256SUMS|seconds|n/a|docs/ml/madrid_no2_h6_ica_v4.md section 9.6"
stage madrid-13 "madrid|publish 2025|atlas.services.publish|--run-dir $A/madrid_no2_h6/ica4-yday-seed1 --features $D/processed/air/features/madrid_no2_h6/table --entities $D/processed/air/stations.geojson --feature-spec configs/ml/madrid_no2_h6_feature_spec.json --from 2025-01-01T00:00:00Z --to 2026-01-01T00:00:00Z --task-id madrid_no2_h6 --title \"Madrid air quality\" --metadata configs/air/attribution.json --territory madrid --territory-title Madrid --published-dir $A/published|configs/ml/madrid_no2_h6_feature_spec.json configs/air/attribution.json|$A/madrid_no2_h6/ica4-yday-seed1/SHA256SUMS $D/processed/air/stations.geojson|$A/published/exfuzzy-madrid_no2_h6-ica4-yday-seed1/SHA256SUMS|seconds|n/a|docs/ml/madrid_no2_h6_ica_v4.md section 9.6"
stage madrid-14 "madrid|parity of every published row with native ex_fuzzy (labels and winning rule)|atlas.ml.publish_parity|$A/published/exfuzzy-madrid_no2_h6-ica4-yday-seed1||$A/published/exfuzzy-madrid_no2_h6-ica4-yday-seed1/SHA256SUMS||seconds|n/a|docs/ml/madrid_no2_h6_ica_v4.md section 9"
stage germany-1 "germany|ingest EEA NO2 hourly (E1a/E2a) + stations (download 0.9 GB, resumable)|atlas.domains.air.eea_ingest|--years 2019-2025|configs/air/de_eea.json||$D/processed/air-de/stations.geojson $D/processed/air-de/observations|~15 min download + 40 s|2.3 GB|docs/air/germany.md"
stage germany-2 "germany|ingest DWD meteo hourly (download 1.5 GB, resumable)|atlas.domains.air.dwd_ingest||configs/air/de_dwd.json||$D/processed/air-de/meteo|~12 min download + 17 min|2.9 GB|docs/air/germany.md"
stage germany-3 "germany|feature table de_no2_h6 (+ spec, splits, quality)|atlas.domains.air.de_features||configs/air/de_no2_h6.json|$D/processed/air-de/observations $D/processed/air-de/meteo|$D/processed/air-de/features/de_no2_h6/table|47 s|1.5 GB|docs/air/germany.md"
stage germany-4 "germany|train ica4: served model on the common rows|atlas.ml.experiment_ica4|base --config configs/ml/de_no2_h6_ica4_experiment.json --workers 9|configs/ml/de_no2_h6_ica4_experiment.json configs/air/eaqi_no2_scheme.json|$D/processed/air-de/features/de_no2_h6/table|$A/de_no2_h6/experiments/ica4/val/base_published.json|seconds|n/a|docs/ml/madrid_no2_h6_ica_v4.md section 8"
stage germany-5 "germany|train ica4: the Madrid arms on Germany|atlas.ml.experiment_ica4|arms --config configs/ml/de_no2_h6_ica4_experiment.json --workers 9|configs/ml/de_no2_h6_ica4_experiment.json|$D/processed/air-de/features/de_no2_h6/table $A/de_no2_h6/experiments/ica4/val/base_published.json|$A/de_no2_h6/experiments/ica4/val/base_refit.json|minutes on a 20-CPU, 121 GB machine|9.5 GB per fit (27 M-row table)|docs/ml/madrid_no2_h6_ica_v4.md section 8"
stage germany-6 "germany|train ica4: decision under the pre-registered rule|atlas.ml.experiment_ica4|decide --config configs/ml/de_no2_h6_ica4_experiment.json|configs/ml/de_no2_h6_ica4_experiment.json|$A/de_no2_h6/experiments/ica4/val/base_refit.json|$A/de_no2_h6/experiments/ica4/decision.json|seconds|n/a|docs/ml/madrid_no2_h6_ica_v4.md section 8"
stage germany-7 "germany|train ica4: test 2025, read once|atlas.ml.experiment_ica4|final --test --config configs/ml/de_no2_h6_ica4_experiment.json|configs/ml/de_no2_h6_ica4_experiment.json|$A/de_no2_h6/experiments/ica4/decision.json|$A/de_no2_h6/experiments/ica4/final_test.json|minutes|n/a|docs/ml/madrid_no2_h6_ica_v4.md section 8"
stage germany-8 "germany|run directory of the published seed|atlas.ml.experiment_ica4|publish-runs --config configs/ml/de_no2_h6_ica4_experiment.json --publish-config configs/ml/de_no2_h6_ica4_publish_experiment.json|configs/ml/de_no2_h6_ica4_experiment.json configs/ml/de_no2_h6_ica4_publish_experiment.json|$A/de_no2_h6/experiments/ica4/final_test.json|$A/de_no2_h6/ica4-yday-seed2/SHA256SUMS|seconds|n/a|docs/ml/madrid_no2_h6_ica_v4.md section 9.6"
stage germany-9 "germany|publish 2025 (437 stations; 3 without official coordinates are left out)|atlas.services.publish|--run-dir $A/de_no2_h6/ica4-yday-seed2 --features $D/processed/air-de/features/de_no2_h6/table --entities $D/processed/air-de/stations.geojson --feature-spec configs/air/de_no2_h6_feature_spec.json --from 2025-01-01T00:00:00Z --to 2026-01-01T00:00:00Z --task-id de_no2_h6 --title \"Germany air quality (EEA)\" --metadata configs/air/attribution_de.json --territory germany --territory-title Alemania --published-dir $A/published|configs/air/de_no2_h6_feature_spec.json configs/air/attribution_de.json|$A/de_no2_h6/ica4-yday-seed2/SHA256SUMS $D/processed/air-de/stations.geojson|$A/published/exfuzzy-de_no2_h6-ica4-yday-seed2/SHA256SUMS|37 s|1.4 GB|docs/ml/madrid_no2_h6_ica_v4.md section 9.6"
stage germany-10 "germany|parity of every published row with native ex_fuzzy|atlas.ml.publish_parity|$A/published/exfuzzy-de_no2_h6-ica4-yday-seed2||$A/published/exfuzzy-de_no2_h6-ica4-yday-seed2/SHA256SUMS||seconds|n/a|docs/ml/madrid_no2_h6_ica_v4.md section 9"
stage germany-11 "germany|mixture of rules (AT-041j, served since contract v0.7): served reference + W>=0 and free arms, 3 seeds|atlas.ml.experiment_mixture|arms --workers 8 --config configs/ml/de_no2_h6_mixture_serve_experiment.json|configs/ml/de_no2_h6_mixture_serve_experiment.json|$A/de_no2_h6/ica4-yday-seed2/SHA256SUMS|$A/de_no2_h6/experiments/mixture-serve/val/mix_search_nonneg.json|~6 min on a 20-CPU, 121 GB machine (6 searches, 126-371 s each)|~2 GB per fit|docs/ml/rule_mixture_serve.md"
stage germany-12 "germany|mixture: choice on validation (highest mean, ties to W>=0)|atlas.ml.experiment_mixture|decide --config configs/ml/de_no2_h6_mixture_serve_experiment.json|configs/ml/de_no2_h6_mixture_serve_experiment.json|$A/de_no2_h6/experiments/mixture-serve/val/mix_search_nonneg.json|$A/de_no2_h6/experiments/mixture-serve/decision.json|seconds|n/a|docs/ml/rule_mixture_serve.md"
stage germany-13 "germany|mixture: test 2025, read once|atlas.ml.experiment_mixture|final --test --config configs/ml/de_no2_h6_mixture_serve_experiment.json|configs/ml/de_no2_h6_mixture_serve_experiment.json|$A/de_no2_h6/experiments/mixture-serve/decision.json|$A/de_no2_h6/experiments/mixture-serve/final_test.json|minutes|n/a|docs/ml/rule_mixture_serve.md"
stage germany-14 "germany|mixture: run directory of the chosen fit|atlas.ml.experiment_mixture|runs --config configs/ml/de_no2_h6_mixture_serve_experiment.json|configs/ml/de_no2_h6_mixture_serve_experiment.json|$A/de_no2_h6/experiments/mixture-serve/final_test.json|$A/de_no2_h6/mixture-nonneg-seed0/SHA256SUMS|about a minute|n/a|docs/ml/rule_mixture_serve.md"
stage germany-15 "germany|mixture: publish 2025 (replaces the registry entry)|atlas.services.publish|--run-dir $A/de_no2_h6/mixture-nonneg-seed0 --features $D/processed/air-de/features/de_no2_h6/table --entities $D/processed/air-de/stations.geojson --feature-spec configs/air/de_no2_h6_feature_spec.json --from 2025-01-01T00:00:00Z --to 2026-01-01T00:00:00Z --task-id de_no2_h6 --title \"Germany air quality (EEA)\" --metadata configs/air/attribution_de.json --territory germany --territory-title Alemania --territory-title-en Germany --published-dir $A/published|configs/air/de_no2_h6_feature_spec.json configs/air/attribution_de.json|$A/de_no2_h6/mixture-nonneg-seed0/SHA256SUMS $D/processed/air-de/stations.geojson|$A/published/exfuzzy-de_no2_h6-mixture-nonneg-seed0/SHA256SUMS|78 s|2 GB|docs/ml/rule_mixture_serve.md"
stage germany-16 "germany|mixture: parity of every published row with native ex_fuzzy|atlas.ml.publish_parity|$A/published/exfuzzy-de_no2_h6-mixture-nonneg-seed0||$A/published/exfuzzy-de_no2_h6-mixture-nonneg-seed0/SHA256SUMS||minutes|n/a|docs/ml/rule_mixture_serve.md"
stage nyc-1 "nyc|ingest yellow-taxi trips + zones (12 months)|atlas.domains.mobility.ingest|--months 2024-04..2025-03|configs/mobility/nyc_tlc.json||$D/processed/mobility/observations $D/processed/mobility/taxi_zones_simplified.geojson|13 s (+ download)|1.2 GB|docs/mobility/README.md"
stage nyc-2 "nyc|feature table nyc_pickups_h1 (AT-031)|atlas.domains.mobility.features|--write-spec|configs/mobility/nyc_pickups_h1.json|$D/processed/mobility/observations|$D/processed/mobility/features/nyc_pickups_h1|3 s|n/a|docs/mobility/nyc_pickups_h1_feature_card.md"
stage nyc-3 "nyc|relative-level table nyc_pickups_h1_level (AT-031b)|atlas.domains.mobility.levels|--write-spec|configs/mobility/nyc_pickups_h1_level.json configs/mobility/nyc_level_scheme.json|$D/processed/mobility/features/nyc_pickups_h1|$D/processed/mobility/features/nyc_pickups_h1_level|minutes (not timed in docs)|n/a|docs/mobility/nyc_pickups_h1_level.md"
stage nyc-4 "nyc|train: select (rel7 arm)|atlas.ml.experiment_nyc|select --config configs/ml/nyc_pickups_h1_level_rel7_experiment.json|configs/ml/nyc_pickups_h1_level_rel7_experiment.json configs/mobility/nyc_level_scheme.json configs/ml/nyc_partitions.json|$D/processed/mobility/features/nyc_pickups_h1_level|$A/nyc_pickups_h1/experiments/level-rel7/selection.json|~9 min (6 fits, 31-180 s each)|<=1.5 GB|docs/ml/nyc_pickups_h1_level_ica.md Reproduce"
stage nyc-5 "nyc|train: final, 3 seeds + 13 baselines + test (read once)|atlas.ml.experiment_nyc|final --config configs/ml/nyc_pickups_h1_level_rel7_experiment.json|configs/ml/nyc_pickups_h1_level_rel7_experiment.json|$D/processed/mobility/features/nyc_pickups_h1_level $A/nyc_pickups_h1/experiments/level-rel7/selection.json|$A/nyc_pickups_h1/experiments/level-rel7/summary.json|199 s|1.46 GB|docs/ml/nyc_pickups_h1_level_ica.md Reproduce"
stage nyc-6 "nyc|train: run directories|atlas.ml.experiment_nyc|runs --config configs/ml/nyc_pickups_h1_level_rel7_experiment.json|configs/ml/nyc_pickups_h1_level_rel7_experiment.json|$A/nyc_pickups_h1/experiments/level-rel7/summary.json|$A/nyc_pickups_h1/level-rel7-seed0/SHA256SUMS|seconds|n/a|docs/ml/nyc_pickups_h1_level_ica.md Reproduce"
stage nyc-7 "nyc|publish the test period|atlas.services.publish|--run-dir $A/nyc_pickups_h1/level-rel7-seed0 --features $D/processed/mobility/features/nyc_pickups_h1_level --entities $D/processed/mobility/taxi_zones_simplified.geojson --feature-spec configs/mobility/feature_spec.json --from 2025-02-08T05:00:00Z --to 2025-04-01T04:00:00Z --task-id nyc_pickups_h1 --title \"Yellow-taxi demand level (NYC)\" --observed-label-column target_level --metadata configs/mobility/attribution.json --include-unmodelled-entities --published-dir $A/published --replace|configs/mobility/feature_spec.json|$A/nyc_pickups_h1/level-rel7-seed0/SHA256SUMS $D/processed/mobility/taxi_zones_simplified.geojson|$A/published/exfuzzy-nyc_pickups_h1-level-rel7-seed0/SHA256SUMS|2 s (measured by A6)|0.5 GB (measured by A6)|docs/ml/nyc_pickups_h1_level_ica.md Reproduce"
stage nyc-8 "nyc|mixture of rules (AT-041j, served since contract v0.7): served reference + W>=0 and free arms, 3 seeds|atlas.ml.experiment_mixture|arms --workers 8 --config configs/ml/nyc_pickups_h1_mixture_serve_experiment.json|configs/ml/nyc_pickups_h1_mixture_serve_experiment.json|$A/nyc_pickups_h1/level-rel7-seed0/SHA256SUMS|$A/nyc_pickups_h1/experiments/mixture-serve/val/mix_search_nonneg.json|~8 min on a 20-CPU, 121 GB machine (6 searches, 218-496 s each)|<1 GB per fit|docs/ml/rule_mixture_serve.md"
stage nyc-9 "nyc|mixture: choice, test (read once) and run directory|atlas.ml.experiment_mixture|decide --config configs/ml/nyc_pickups_h1_mixture_serve_experiment.json|configs/ml/nyc_pickups_h1_mixture_serve_experiment.json|$A/nyc_pickups_h1/experiments/mixture-serve/val/mix_search_nonneg.json|$A/nyc_pickups_h1/experiments/mixture-serve/decision.json|seconds|n/a|docs/ml/rule_mixture_serve.md"
stage nyc-10 "nyc|mixture: test, read once|atlas.ml.experiment_mixture|final --test --config configs/ml/nyc_pickups_h1_mixture_serve_experiment.json|configs/ml/nyc_pickups_h1_mixture_serve_experiment.json|$A/nyc_pickups_h1/experiments/mixture-serve/decision.json|$A/nyc_pickups_h1/experiments/mixture-serve/final_test.json|seconds|n/a|docs/ml/rule_mixture_serve.md"
stage nyc-11 "nyc|mixture: run directory of the chosen fit|atlas.ml.experiment_mixture|runs --config configs/ml/nyc_pickups_h1_mixture_serve_experiment.json|configs/ml/nyc_pickups_h1_mixture_serve_experiment.json|$A/nyc_pickups_h1/experiments/mixture-serve/final_test.json|$A/nyc_pickups_h1/mixture-nonneg-seed1/SHA256SUMS|seconds|n/a|docs/ml/rule_mixture_serve.md"
stage nyc-12 "nyc|mixture: publish the test period (replaces the registry entry)|atlas.services.publish|--run-dir $A/nyc_pickups_h1/mixture-nonneg-seed1 --features $D/processed/mobility/features/nyc_pickups_h1_level --entities $D/processed/mobility/taxi_zones_simplified.geojson --feature-spec configs/mobility/feature_spec.json --from 2025-02-08T05:00:00Z --to 2025-04-01T04:00:00Z --task-id nyc_pickups_h1 --title \"Yellow-taxi demand level (NYC)\" --observed-label-column target_level --metadata configs/mobility/attribution.json --include-unmodelled-entities --territory nyc --territory-title \"Nueva York\" --territory-title-en \"New York\" --published-dir $A/published|configs/mobility/feature_spec.json configs/mobility/attribution.json|$A/nyc_pickups_h1/mixture-nonneg-seed1/SHA256SUMS $D/processed/mobility/taxi_zones_simplified.geojson|$A/published/exfuzzy-nyc_pickups_h1-mixture-nonneg-seed1/SHA256SUMS|3 s|0.5 GB|docs/ml/rule_mixture_serve.md"
stage nyc-13 "nyc|mixture: parity of every published row with native ex_fuzzy|atlas.ml.publish_parity|$A/published/exfuzzy-nyc_pickups_h1-mixture-nonneg-seed1||$A/published/exfuzzy-nyc_pickups_h1-mixture-nonneg-seed1/SHA256SUMS||seconds|n/a|docs/ml/rule_mixture_serve.md"
stage water-1 "water|ingest EA water quality (paged API, 5 determinands)|atlas.domains.water.ingest|--counts|configs/water/uk_water_quality.json||$D/processed/water/observations $D/processed/water/entities.geojson|~1 min (125 requests)|n/a|docs/water/README.md"
stage water-2 "water|feature table uk_water_do (+ splits)|atlas.domains.water.features|--write-spec|configs/water/uk_water_do.json|$D/processed/water/observations|$D/processed/water/features/uk_water_do|2 s|n/a|docs/water/README.md"
stage water-3 "water|train: select (chrono, with temperature, unique_antecedents; needs EXFUZZY_SRC)|atlas.ml.experiment_water|select --config configs/ml/fx_water_do_chrono_temp_unique_experiment.json|configs/ml/fx_water_do_chrono_temp_unique_experiment.json configs/ml/water_partitions.json|$D/processed/water/features/uk_water_do|$A/uk_water_do/experiments/fx-w-unique/selection.json|~3 min (9 fits)|0.35 GB|docs/ml/fx_retrain_with_fixed_exfuzzy.md Experiment 2"
stage water-4 "water|train: final, seeds + baselines + test (read once) + run directories (needs EXFUZZY_SRC)|atlas.ml.experiment_water|final --config configs/ml/fx_water_do_chrono_temp_unique_experiment.json|configs/ml/fx_water_do_chrono_temp_unique_experiment.json|$D/processed/water/features/uk_water_do $A/uk_water_do/experiments/fx-w-unique/selection.json|$A/uk_water_do/fx-w-unique-seed0/SHA256SUMS|~70 s|0.35 GB|docs/ml/fx_retrain_with_fixed_exfuzzy.md Experiment 2"
stage water-5 "water|publish 2024-2025 (irregular sample times)|atlas.services.publish|--run-dir $A/uk_water_do/fx-w-unique-seed0 --features $D/processed/water/features/uk_water_do --entities $D/processed/water/entities.geojson --feature-spec configs/water/feature_spec.json --from 2024-01-01T00:00:00Z --to 2026-01-01T00:00:00Z --task-id uk_water_do --title \"River dissolved oxygen (UK)\" --irregular-times --metadata configs/water/attribution.json --published-dir $A/published --replace|configs/water/feature_spec.json|$A/uk_water_do/fx-w-unique-seed0/SHA256SUMS $D/processed/water/entities.geojson|$A/published/exfuzzy-uk_water_do-fx-w-unique-seed0/SHA256SUMS|seconds|n/a|docs/ml/fx_retrain_with_fixed_exfuzzy.md Experiment 2"

field() { echo "${S[$1]}" | cut -d'|' -f"$2"; }
selected() { [ -z "$ONLY" ] || [ "$(field "$1" 1)" = "$ONLY" ]; }
command_of() { echo "$PY -m $(field "$1" 3) $(field "$1" 4)"; }

list() {
  echo "ExFuzzy Atlas: raw data -> published models.   data=$D   artifacts=$A"
  echo "Peak RSS and times are the ones measured in docs/ (the 12-core, ~15 GB workstation); '5 GB' of downloads are the TLC parquet, the traffic"
  echo "files are not needed for the published models."
  for id in "${IDS[@]}"; do
    selected "$id" || continue
    printf '\n[%s] %s\n  time %s, peak RSS %s, doc %s\n  $ %s\n' "$id" "$(field "$id" 2)" "$(field "$id" 8)" \
      "$(field "$id" 9)" "$(field "$id" 10)" "$(command_of "$id")"
  done
  echo
  echo "Then: make demo   (serves the published models) ;  make qa   (integration tests over them)"
}

declare -A HELP
check() {
  local fail=0 produced=" " id
  for id in "${IDS[@]}"; do
    selected "$id" || continue
    local out="" ; local mod; mod="$(field "$id" 3)"
    if ! (cd "$REPO" && "$PY" -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('$mod') else 1)" 2>/dev/null); then
      echo "FAIL [$id] module $mod not importable"; fail=1; continue
    fi
    local args sub="" key help_text; args="$(field "$id" 4)"
    case "$args" in -*|"") ;; *) sub="${args%% *}" ;; esac
    key="$mod $sub"
    if [ -z "${HELP[$key]+x}" ]; then HELP[$key]="$(cd "$REPO" && "$PY" -m $mod $sub --help 2>&1)"; fi
    help_text="${HELP[$key]}"
    for flag in $(grep -o -e '--[a-z][a-z0-9-]*' <<<"$args" | sort -u); do
      grep -q -e "$flag" <<<"$help_text" || { echo "FAIL [$id] $mod $sub has no option $flag"; fail=1; }
    done
    for f in $(field "$id" 5); do
      [ -e "$REPO/$f" ] || { echo "FAIL [$id] config missing: $f"; fail=1; }
    done
    for f in $(field "$id" 6); do
      if [ -e "$f" ]; then :; elif [[ "$produced" == *" $f "* ]]; then :; else
        echo "FAIL [$id] input missing and no earlier stage produces it: $f"; fail=1; fi
    done
    for f in $(field "$id" 7); do produced+="$f "; [ -e "$f" ] && out+=" present" || out+=" absent"; done
    echo "ok   [$id] module+configs+inputs;  outputs:${out}"
  done
  return $fail
}

smoke() {
  # Publish the existing Water run into a temp dir (about 10 s) and compare it with the published copy.
  local id=water-5 tmp; tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  for f in $(field "$id" 6); do [ -e "$f" ] || { echo "smoke needs $f (not present: nothing to publish)"; return 1; }; done
  local args; args="$(field "$id" 4)"
  args="${args//--published-dir $A\/published/--published-dir $tmp}"
  eval "$PY -m $(field "$id" 3) $args" || return 1
  "$PY" - "$tmp" "$A/published" <<'PYEOF'
import json, sys
from pathlib import Path
import pandas as pd
new, old = Path(sys.argv[1]), Path(sys.argv[2])
reg = json.loads((new / "registry.json").read_text())["tasks"]["uk_water_do"]
mid = reg["model_id"]
a = pd.read_parquet(new / mid / "predictions.parquet")
print(f"smoke: published {mid}: {len(a)} prediction rows, {a.entity_id.nunique()} entities")
if (old / mid / "predictions.parquet").exists():
    b = pd.read_parquet(old / mid / "predictions.parquet")
    same = a.reset_index(drop=True).equals(b.reset_index(drop=True))
    rules = json.loads((new / mid / "rules.json").read_text()) == json.loads((old / mid / "rules.json").read_text())
    print(f"smoke: predictions identical to the published copy: {same}; rules.json identical: {rules}")
    sys.exit(0 if same and rules else 1)
PYEOF
}

run() {
  [ "$YES" = 1 ] || { echo "--run executes every stage (hours of CPU, GB of downloads, writes under $D and $A). Add --yes." >&2; exit 2; }
  check || { echo "dry run failed; fix before running" >&2; exit 1; }
  for id in "${IDS[@]}"; do
    selected "$id" || continue
    echo "=== [$id] $(field "$id" 2)"; echo "\$ $(command_of "$id")"
    (cd "$REPO" && eval "$(command_of "$id")") || { echo "stage $id failed" >&2; exit 1; }
  done
}

case "$MODE" in
  list) list ;;
  check) check; rc=$?; [ $rc = 0 ] && echo "dry run OK" || echo "dry run FAILED"; exit $rc ;;
  smoke) check || exit 1; smoke; rc=$?; [ $rc = 0 ] && echo "smoke OK" || echo "smoke FAILED"; exit $rc ;;
  run) run ;;
esac
