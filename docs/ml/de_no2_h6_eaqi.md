# Germany NO2 at t+6 h as an EAQI band: the Madrid protocol on 440 stations (AT-070, A4)

Task `de_no2_h6`: the same pipeline, rows definition, split, fitting subsample, budget and baselines as the Madrid
`justified` classifier of `madrid_no2_h6_ica_v2.md` (AT-041d), on the Germany feature table of AT-070
([`../air/germany.md`](../air/germany.md): EEA hourly NO2 of 440 stations, DWD meteorology within 25 km). The target is the
**predicted EAQI NO2 band** at t+6 h (EAQI = the European Air Quality Index of the EEA). Every table below is printed by
`python -m atlas.ml.report_class` from the run artifacts, except the ones marked as measured by hand.

**What this is not.** The output is the EAQI **band of the NO2 concentration** the model expects, not a health risk, not
an exposure and not an air-quality forecast for people. Firing, association degree and rule weight are degrees of rule
match, not probabilities, contributions or risk. The NO2 concentration of one station is not an area value and nothing
is interpolated between stations. No causal claim: "wind_speed IS Light breeze" in a rule says how an input was split,
not that wind causes the band. The EAQI bands are **not** the Spanish ICA bands of Madrid (EAQI thresholds are 10/25/60
against 40/90/120), so class-level results of Madrid and Germany are not comparable (section 8).

**Result in one paragraph.** Selection on validation 2024 (6 shapes, one fit each) picked 30 rules x 3 antecedents
(validation macro-F1 0.451). Three seeds of that shape on test 2025 (2,957,829 complete rows, read once): macro-F1
**0.470 for the published seed 0** (seeds 0.448 to 0.470, mean 0.462 +- 0.012), balanced accuracy 0.479 (0.484 +- 0.005).
That is not a clear gain over the two trivial baselines on macro-F1: persistence of the current band 0.455 and station x hour
x weekday climatology 0.442 on test (on validation climatology, 0.470, is above the fuzzy classifier, 0.451). It is below
gradient boosting (0.518 on a 2,000,000-row training sample, 0.527 on the 30,000 fitting rows) and random forest (0.489 to
0.535) by 0.05 to 0.07, the same order of gap as in Madrid. The upper band "Poor or worse" (61 ug/m3 and above, 0.85 % of the
test hours) is found with recall 0.23 and precision 0.14 (F1 0.175); the class-balanced baselines recall it better (0.49 to
0.74) at precision 0.08 to 0.18. The model is 15 readable rules (mean length 1.87 antecedents); the rule sets of the three
seeds hardly overlap (Jaccard 0.045), so a single rule is not a stable finding. Costs: a 9.6 min `final` stage and a
38 s, 1.4 GB, 190 MB publication of a full year for 440 stations (section 9, 10).

## 1. Task, data and split

* Table `data/processed/air-de/features/de_no2_h6/table` (hive, 26,998,840 rows = 440 stations x 61,361 issue hours,
  21,228,357 complete rows); card, splits and quality in the same folder. Source: EEA Air Quality Download Service
  (E1a verified), CC BY 4.0, and DWD Climate Data Center, CC BY 4.0 (`../air/germany.md`).
* Features, as in Madrid: `no2_last`, `no2_lag1h`, `no2_lag3h`, `no2_lag24h`, `wind_speed`, `temperature`,
  `relative_humidity`, `valid_hour_local` (Europe/Berlin), `valid_weekday`. Feature spec
  `configs/air/de_no2_h6_feature_spec.json`.
* Split (`splits.json`): train 2019-01-01 to 2023-12-31 (15,213,722 complete rows, 400 stations), validation 2024
  (3,039,891; 380 stations), test 2025 (2,957,829; 371 stations); 24 h embargo; chronological, no shuffling.
* Complete row = the table's `complete` flag and a finite target and finite features. Rows with a missing input are not
  scored by anything (the 21.2 M of 27.0 M). Rows with a missing input in a published model get no prediction.
* Negative NO2 values (detection-limit noise, minimum -9.9 ug/m3) are kept as in the table and classified **Good**, the
  boundary convention of `configs/air/eaqi_no2_scheme.json` (`below_first_as_first`).

## 2. Classes

EAQI NO2, hourly, ug/m3 (`configs/air/eaqi_no2_scheme.json`, EEA page read 2026-11-02): Good 0-10, Fair 11-25,
Moderate 26-60, Poor 61-100, Very poor 101-150, Extremely poor above 150. Rare upper classes are merged **from the top**
when they have fewer than 1 % of the complete training rows (`merge_min_train_share: 0.01`, new, exclusive with the
Madrid `merge_min_train_rows`): Extremely poor (0.0018 %) and Very poor (0.077 %) are merged into Poor (1.84 %, kept),
giving four classes, **Good, Fair, Moderate, Poor or worse** (the last is 61 ug/m3 and above; `merged_from` = Poor,
Very poor, Extremely poor). Thresholds are never changed. With Madrid's 500-row rule only Extremely poor (268 rows) would
have been merged ("Very poor or worse", 12 k rows), because the German counts are large: a share was needed.

**Official classes** (complete rows, target at t+6 h)

| period | n | Good | Fair | Moderate | Poor | Very poor | Extremely poor |
|---|---|---|---|---|---|---|---|
| train | 15213722 | 6211047 (40.825 %) | 5299313 (34.832 %) | 3410860 (22.420 %) | 280570 (1.844 %) | 11664 (0.077 %) | 268 (0.002 %) |
| validation | 3039891 | 1477175 (48.593 %) | 1053966 (34.671 %) | 491643 (16.173 %) | 16888 (0.556 %) | 206 (0.007 %) | 13 (0.000 %) |
| test | 2957829 | 1353888 (45.773 %) | 1040698 (35.185 %) | 538109 (18.193 %) | 24365 (0.824 %) | 764 (0.026 %) | 5 (0.000 %) |

**Classes used by the model** (complete rows, target at t+6 h)

| period | n | Good | Fair | Moderate | Poor or worse |
|---|---|---|---|---|---|
| train | 15213722 | 6211047 (40.825 %) | 5299313 (34.832 %) | 3410860 (22.420 %) | 292502 (1.923 %) |
| validation | 3039891 | 1477175 (48.593 %) | 1053966 (34.671 %) | 491643 (16.173 %) | 17107 (0.563 %) |
| test | 2957829 | 1353888 (45.773 %) | 1040698 (35.185 %) | 538109 (18.193 %) | 25134 (0.850 %) |

The class mix drifts: "Poor or worse" is 1.92 % of the training hours, 0.56 % of validation and 0.85 % of test, and "Good"
is 40.8 %, 48.6 % and 45.8 %. A model fitted on 2019-2023 therefore meets fewer high-NO2 hours in 2024 and 2025.

**EAQI colours (A0, at integration).** The EEA page snapshot carries no colour values as text (only `#6f6f6f`),
but the stylesheet of the same EEA viewer does: `https://airindex.eea.europa.eu/AQI/css/style.css`, lines 17-22,
`--band-color-good` rgb(80, 240, 230) `#50F0E6`, `-fair` `#50CCAA`, `-moderate` `#F0E641`, `-poor` `#FF5050`,
`-veryPoor` `#960032`, `-extremelyPoor` `#7D2181` (snapshot `data/raw/eea-air-de/docs/eaqi_airindex_style.css`,
accessed 2026-11-02). They are in `configs/air/eaqi_no2_scheme.json`; "Poor or worse" takes the colour of Poor, as
Madrid's merged class takes that of its best member. The runs were regenerated with `experiment_class runs` (35 s):
`model.pkl` and `metrics.json` are byte-identical, only `rules.json` (colours), the run manifest and `SHA256SUMS` differ;
the colourless run directories are kept in `artifacts/de_no2_h6/superseded-no-colours/`.

## 3. Linguistic terms and their justification

`configs/ml/de_partitions.json` (loaded by `atlas.ml.partitions.load_partition_file`, which refuses a file whose written
trapezoids are not those its cores and shoulders give). Term names are English. Every variable has a rationale and, where a
source was read, the source and what was read.

| input | terms | basis |
|---|---|---|
| `no2_last`, `no2_lag1h`, `no2_lag3h`, `no2_lag24h` | Good [-10, 10], Fair [11, 25], Moderate [26, 60], Poor or worse [61, 1100] | the merged target classes (`follows_target_scheme`, checked at run time); shoulders 15 % of each boundary (1.5, 3.75, 9 ug/m3), as in Madrid |
| `wind_speed` | Calm to light air [0, 1.5], Light breeze [1.6, 3.3], Gentle to moderate breeze [3.4, 7.9], Fresh breeze or stronger [8, 40] m/s | Beaufort groups as in Madrid; shoulders 0.5, 0.5, 0.79 m/s (WMO CIMO guide) |
| `valid_hour_local` | Night [0, 4], Morning rush [5, 9], Midday [10, 16], Evening [17, 23] | the German NO2 profile of the TRAIN period (below); one-hour shoulders (crisp on whole hours) |
| `valid_weekday` | Weekday [0, 4], Saturday [5], Sunday [6] | calendar; holidays are not encoded |
| `temperature`, `relative_humidity` | Low / Medium / High, data-driven quantile trapezoids (20/40/60/80 %) of 1,000,000 uniformly drawn training rows | no defensible source found (as in Madrid) |

Two NO2 domain choices are not EAQI facts: the Good core starts at -10 (so detection-limit noise, 0.28 % of the training
rows have a negative NO2 input, belongs to a term instead of to none) and the top core ends at 1100 (the EAQI top band is
open; the largest value in the table is 1015.1 ug/m3). The 15 % shoulder is the data quality objective for fixed NO2
measurements of Directive 2008/50/EC (read for the Madrid file, not re-read), applied at 10 to 60 ug/m3 instead of near the
hourly limit value: an extrapolation, larger than in Madrid, with the caveats written in the file.

**DWD wind: unit and height.** `DESCRIPTION_wind.pdf` (v24.03) gives the unit m/s and "hourly mean"; the station metadata
say the hourly value is generated from 10-minute means. The description does not state the sensor height. The per-station
`Geberhoehe ueber Grund` of the 300 stations with wind data in 2019-2025 (maximum over the period, from the
`Metadaten_Geraete_Windgeschwindigkeit` file in each zip) is exactly 10 m at 155 stations, 10.1 to 15 m at 114 (79 of them
at 12 m) and above 15 m at 29 (up to 42.6 m); the median is 10 m. So "about 10 m" holds for half the stations, and the
Beaufort groups are approximate, worse at the tall-mast ones.

**Hour periods from the German NO2 profile (train rows only).** Mean of `target` divided by the station's own mean, by local
hour of the valid time, Monday to Friday, 15,213,722 complete training rows, 400 stations (computed 2026-11-02 with DuckDB
from the table; the raw workday means in ug/m3 are in the last row):

| hour | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| relative level | 0.93 | 0.86 | 0.83 | 0.82 | 0.87 | 1.05 | 1.29 | 1.45 | 1.37 | 1.21 | 1.08 | 0.98 |
| raw mean, ug/m3 | 15.7 | 14.3 | 13.7 | 13.5 | 14.7 | 18.5 | 23.4 | 26.4 | 25.1 | 22.2 | 20.0 | 18.2 |

| hour | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| relative level | 0.92 | 0.90 | 0.92 | 0.99 | 1.07 | 1.13 | 1.18 | 1.19 | 1.20 | 1.19 | 1.15 | 1.05 |
| raw mean, ug/m3 | 17.1 | 17.0 | 17.4 | 18.7 | 20.1 | 21.0 | 21.6 | 21.5 | 21.4 | 21.0 | 20.1 | 18.2 |

Night = hours 0-4 (the trough, all below 0.95 of the station mean); Morning rush = 5-9 (hour 5 is the first above the mean,
6-9 the peak, 1.45 at 7); Midday = 10-16 (decline, trough 0.90 at 13, back to 1.07 at 16); Evening = 17-23. Madrid's periods
(night 0-6, rush 7-9) were **not** reused: the German morning ramp starts two hours earlier (hour 6 is already 1.29). On
Saturday and Sunday the morning peak is absent (Saturday 0.96 at hour 7, Sunday 0.76); the periods follow the workday
profile and the model combines them with `valid_weekday`. By day type the mean level is 1.02 to 1.10 Monday to Friday, 0.90
on Saturday and 0.78 on Sunday. The profile describes the training period; it is not a validated cause (traffic, heating,
boundary-layer height and photochemistry all vary with the hour). Four terms and not five for the same ex_fuzzy 3.3.1 reason
as in Madrid (the term index of the k-th antecedent slot is bounded by the number of terms of the k-th feature, and the four
NO2 inputs come first with four terms).

## 4. Protocol

Identical to the Madrid `justified` arm except for what section 1 to 3 list. Config: `configs/ml/de_no2_h6_eaqi_experiment.json`.

* Fitting subsample: 30,000 complete training rows, class-tempered (class sizes proportional to count^0.5), uniform
  within station x month blocks, seed 20260101; class counts [10,410, 9,616, 7,715, 2,259]. Partitions of the free inputs
  from 1,000,000 uniformly drawn training rows (`partition_rows`; Madrid used all 918 k).
* Selection (`select`, validation 2024 only, test never read): 30/60 rules x 2/3/4 antecedents, 3 terms per quantile
  variable, dominance-score weighting, power 0.5, 150 generations x population 60, seed 0; ranked by validation macro-F1
  (ties: fewer rules). Final (`final`): the chosen shape with seeds 0, 1, 2; published seed = highest validation macro-F1.
* Baselines, same set as Madrid (persistence of the EAQI class of `no2_last`, station x local hour x weekday climatology,
  HGB classifier plain and balanced, HGB regression binned with the scheme, logistic regression and random forest plain
  and balanced, and the five subsample variants on the 30,000 fitting rows). The "full training period" ones are fitted on
  **a bounded sample of 2,000,000 complete training rows** (`baseline_train_rows`, uniform within station x month blocks,
  natural class proportions, seed 20260101), 13 % of the 15.2 M, because pandas / sklearn on 15 M rows does not fit the memory
  budget; climatology counts are exact over the whole training period (chunked). The random forests keep 300 trees, leaf 20
  and a 100,000-row bootstrap per tree. These baselines are therefore not "all rows" as in Madrid; the comparison with their
  Madrid counterparts is of the same kind but not identical.
* ex_fuzzy: the pinned PyPI 3.3.1 (`atlas.ml.exfuzzy_features.exfuzzy_version()` is recorded in each run manifest), no local
  build, as in the published Madrid model.
* Not done: the Madrid AT-041d partition comparison (quantile terms versus justified terms). Germany uses the `justified`
  scheme directly, so this document says nothing about whether the justified terms help here.

## 5. Selection (validation 2024)

| power | weighting | nRules | nAnts | terms | rules kept | GA fitness (train) | val macro-F1 | val bal-acc | val acc | val MAE idx | unknown | fit s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.5 | dominance_score | 30 | 3 | 3 | 15 | 0.544 | 0.451 | 0.456 | 0.614 | 0.427 | 0.005 | 76 |
| 0.5 | dominance_score | 30 | 2 | 3 | 8 | 0.533 | 0.437 | 0.431 | 0.613 | 0.431 | 0.000 | 36 |
| 0.5 | dominance_score | 30 | 4 | 3 | 14 | 0.532 | 0.436 | 0.441 | 0.593 | 0.438 | 0.013 | 57 |
| 0.5 | dominance_score | 60 | 4 | 3 | 14 | 0.519 | 0.433 | 0.435 | 0.596 | 0.446 | 0.003 | 71 |
| 0.5 | dominance_score | 60 | 3 | 3 | 13 | 0.528 | 0.431 | 0.439 | 0.608 | 0.441 | 0.000 | 107 |
| 0.5 | dominance_score | 60 | 2 | 3 | 6 | 0.506 | 0.426 | 0.424 | 0.602 | 0.446 | 0.000 | 102 |

The six shapes lie within 0.025 of each other (0.426 to 0.451) on one fit each; with seed standard deviations of about 0.012
(section 6.1) the ranking is weak evidence. 60-rule shapes did not beat 30-rule ones (the genetic algorithm keeps 6 to 15
rules after pruning in every case). Chosen: 30 rules x 3 antecedents, 3 terms, dominance score, power 0.5.

## 6. Test results (2025, read once, 2,957,829 complete rows)

Seed 0 is the published model (highest validation macro-F1 of the three seeds).

**Test overall**

| estimator | macro_f1 | balanced_accuracy | accuracy | mae_class_index | share_off_by_2plus | share_unknown |
|---|---|---|---|---|---|---|
| persistence | 0.455 | 0.455 | 0.600 | 0.446 | 0.045 | 0.000 |
| climatology_majority_class | 0.442 | 0.439 | 0.597 | 0.443 | 0.040 | 0.000 |
| hist_gradient_boosting | 0.518 | 0.504 | 0.675 | 0.344 | 0.018 | 0.000 |
| hist_gradient_boosting_balanced | 0.501 | 0.629 | 0.632 | 0.412 | 0.040 | 0.000 |
| hist_gradient_boosting_regression_binned | 0.510 | 0.499 | 0.655 | 0.357 | 0.012 | 0.000 |
| logistic_regression | 0.434 | 0.427 | 0.620 | 0.419 | 0.038 | 0.000 |
| logistic_regression_balanced | 0.436 | 0.565 | 0.577 | 0.499 | 0.070 | 0.000 |
| random_forest | 0.489 | 0.482 | 0.668 | 0.352 | 0.021 | 0.000 |
| random_forest_balanced | 0.535 | 0.593 | 0.647 | 0.384 | 0.031 | 0.000 |
| hist_gradient_boosting_subsample | 0.527 | 0.538 | 0.647 | 0.381 | 0.028 | 0.000 |
| logistic_regression_subsample | 0.482 | 0.472 | 0.616 | 0.423 | 0.039 | 0.000 |
| logistic_regression_balanced_subsample | 0.450 | 0.547 | 0.587 | 0.472 | 0.056 | 0.000 |
| random_forest_subsample | 0.514 | 0.504 | 0.643 | 0.387 | 0.029 | 0.000 |
| random_forest_balanced_subsample | 0.502 | 0.576 | 0.625 | 0.415 | 0.038 | 0.000 |
| exfuzzy_classifier | 0.470 | 0.479 | 0.607 | 0.437 | 0.046 | 0.006 |

**Validation overall** (same rows as the selection)

| estimator | macro_f1 | balanced_accuracy | accuracy | mae_class_index | share_off_by_2plus | share_unknown |
|---|---|---|---|---|---|---|
| persistence | 0.437 | 0.438 | 0.603 | 0.442 | 0.044 | 0.000 |
| climatology_majority_class | 0.470 | 0.467 | 0.620 | 0.411 | 0.031 | 0.000 |
| hist_gradient_boosting | 0.494 | 0.483 | 0.677 | 0.342 | 0.019 | 0.000 |
| hist_gradient_boosting_balanced | 0.487 | 0.594 | 0.643 | 0.395 | 0.035 | 0.000 |
| hist_gradient_boosting_regression_binned | 0.490 | 0.483 | 0.661 | 0.351 | 0.012 | 0.000 |
| logistic_regression | 0.415 | 0.408 | 0.622 | 0.417 | 0.039 | 0.000 |
| logistic_regression_balanced | 0.420 | 0.520 | 0.588 | 0.480 | 0.064 | 0.000 |
| random_forest | 0.476 | 0.468 | 0.672 | 0.348 | 0.020 | 0.000 |
| random_forest_balanced | 0.515 | 0.549 | 0.655 | 0.373 | 0.027 | 0.000 |
| hist_gradient_boosting_subsample | 0.499 | 0.500 | 0.651 | 0.376 | 0.027 | 0.000 |
| logistic_regression_subsample | 0.447 | 0.435 | 0.619 | 0.420 | 0.038 | 0.000 |
| logistic_regression_balanced_subsample | 0.431 | 0.503 | 0.596 | 0.459 | 0.052 | 0.000 |
| random_forest_subsample | 0.492 | 0.479 | 0.646 | 0.382 | 0.027 | 0.000 |
| random_forest_balanced_subsample | 0.483 | 0.537 | 0.631 | 0.404 | 0.034 | 0.000 |
| exfuzzy_classifier | 0.451 | 0.456 | 0.614 | 0.427 | 0.043 | 0.005 |

**Test recall per class**

| estimator | Good (n=1353888) | Fair (n=1040698) | Moderate (n=538109) | Poor or worse (n=25134) |
|---|---|---|---|---|
| persistence | 0.736 | 0.502 | 0.469 | 0.114 |
| climatology_majority_class | 0.722 | 0.495 | 0.510 | 0.030 |
| hist_gradient_boosting | 0.792 | 0.601 | 0.550 | 0.073 |
| hist_gradient_boosting_balanced | 0.765 | 0.534 | 0.479 | 0.737 |
| hist_gradient_boosting_regression_binned | 0.667 | 0.695 | 0.575 | 0.060 |
| logistic_regression | 0.840 | 0.466 | 0.391 | 0.012 |
| logistic_regression_balanced | 0.810 | 0.370 | 0.384 | 0.695 |
| random_forest | 0.792 | 0.603 | 0.514 | 0.018 |
| random_forest_balanced | 0.762 | 0.534 | 0.586 | 0.489 |
| hist_gradient_boosting_subsample | 0.779 | 0.549 | 0.524 | 0.301 |
| logistic_regression_subsample | 0.802 | 0.469 | 0.454 | 0.162 |
| logistic_regression_balanced_subsample | 0.791 | 0.431 | 0.379 | 0.588 |
| random_forest_subsample | 0.773 | 0.553 | 0.511 | 0.177 |
| random_forest_balanced_subsample | 0.762 | 0.523 | 0.483 | 0.536 |
| exfuzzy_classifier | 0.792 | 0.467 | 0.431 | 0.227 |

**Test precision per class**

| estimator | Good | Fair | Moderate | Poor or worse |
|---|---|---|---|---|
| persistence | 0.737 | 0.503 | 0.466 | 0.113 |
| climatology_majority_class | 0.728 | 0.491 | 0.489 | 0.158 |
| hist_gradient_boosting | 0.788 | 0.568 | 0.602 | 0.389 |
| hist_gradient_boosting_balanced | 0.805 | 0.569 | 0.508 | 0.099 |
| hist_gradient_boosting_regression_binned | 0.856 | 0.527 | 0.585 | 0.534 |
| logistic_regression | 0.686 | 0.522 | 0.572 | 0.375 |
| logistic_regression_balanced | 0.708 | 0.534 | 0.449 | 0.077 |
| random_forest | 0.780 | 0.560 | 0.600 | 0.482 |
| random_forest_balanced | 0.799 | 0.563 | 0.516 | 0.182 |
| hist_gradient_boosting_subsample | 0.769 | 0.551 | 0.547 | 0.215 |
| logistic_regression_subsample | 0.707 | 0.518 | 0.526 | 0.246 |
| logistic_regression_balanced_subsample | 0.715 | 0.519 | 0.467 | 0.092 |
| random_forest_subsample | 0.759 | 0.541 | 0.551 | 0.268 |
| random_forest_balanced_subsample | 0.766 | 0.543 | 0.510 | 0.133 |
| exfuzzy_classifier | 0.708 | 0.522 | 0.507 | 0.142 |

**Test F1 per class**

| estimator | Good | Fair | Moderate | Poor or worse |
|---|---|---|---|---|
| persistence | 0.736 | 0.503 | 0.467 | 0.113 |
| climatology_majority_class | 0.725 | 0.493 | 0.499 | 0.051 |
| hist_gradient_boosting | 0.790 | 0.584 | 0.575 | 0.123 |
| hist_gradient_boosting_balanced | 0.785 | 0.551 | 0.493 | 0.175 |
| hist_gradient_boosting_regression_binned | 0.750 | 0.600 | 0.580 | 0.109 |
| logistic_regression | 0.755 | 0.493 | 0.464 | 0.023 |
| logistic_regression_balanced | 0.756 | 0.437 | 0.414 | 0.139 |
| random_forest | 0.786 | 0.581 | 0.554 | 0.035 |
| random_forest_balanced | 0.780 | 0.548 | 0.549 | 0.265 |
| hist_gradient_boosting_subsample | 0.774 | 0.550 | 0.535 | 0.251 |
| logistic_regression_subsample | 0.752 | 0.492 | 0.487 | 0.195 |
| logistic_regression_balanced_subsample | 0.751 | 0.471 | 0.418 | 0.160 |
| random_forest_subsample | 0.766 | 0.547 | 0.531 | 0.213 |
| random_forest_balanced_subsample | 0.764 | 0.533 | 0.496 | 0.214 |
| exfuzzy_classifier | 0.748 | 0.493 | 0.466 | 0.175 |

**Confusion matrix of the ExFuzzy classifier on test (published seed)**

| observed \ predicted | Good | Fair | Moderate | Poor or worse | no_prediction |
|---|---|---|---|---|---|
| **Good** | 1,071,998 | 239,080 | 38,923 | 2,228 | 1,659 |
| **Fair** | 362,405 | 485,623 | 176,083 | 10,337 | 6,250 |
| **Moderate** | 76,737 | 199,110 | 231,750 | 22,003 | 8,509 |
| **Poor or worse** | 2,032 | 6,055 | 10,630 | 5,716 | 701 |

### 6.1 Seeds

| seed | rules | val macro-F1 | test macro-F1 | test bal-acc | test acc | test MAE idx | test unknown | fit s |
|---|---|---|---|---|---|---|---|---|
| 0 | 15 | 0.451 | 0.470 | 0.479 | 0.607 | 0.437 | 0.006 | 44 |
| 1 | 12 | 0.428 | 0.448 | 0.484 | 0.590 | 0.461 | 0.000 | 45 |
| 2 | 11 | 0.441 | 0.467 | 0.488 | 0.600 | 0.442 | 0.001 | 44 |
| mean ± sd |  | 0.440 ± 0.012 | 0.462 ± 0.012 | 0.484 ± 0.005 | 0.599 ± 0.009 | 0.447 ± 0.013 | 0.002 ± 0.003 |  |

**Per-class F1 of the three seeds, test**

| seed | Good | Fair | Moderate | Poor or worse |
|---|---|---|---|---|
| 0 | 0.748 | 0.493 | 0.466 | 0.175 |
| 1 | 0.735 | 0.527 | 0.384 | 0.144 |
| 2 | 0.734 | 0.531 | 0.424 | 0.178 |

**Per-class F1 of the three seeds, validation**

| seed | Good | Fair | Moderate | Poor or worse |
|---|---|---|---|---|
| 0 | 0.753 | 0.491 | 0.439 | 0.123 |
| 1 | 0.739 | 0.520 | 0.359 | 0.095 |
| 2 | 0.738 | 0.524 | 0.403 | 0.101 |

The seed with the highest validation macro-F1 (0) is also the best on test. The macro-F1 of the "Moderate" class swings
between 0.384 and 0.466 and that of "Poor or worse" between 0.144 and 0.178 across seeds: per-class differences below about
0.05 are not distinguishable from seed variation.

### 6.2 Reading of the comparison

* Persistence and climatology are strong here (macro-F1 0.455 / 0.442 on test, 0.437 / 0.470 on validation). The fuzzy
  classifier beats persistence by 0.015 for the published seed but loses to it for seed 1 (0.448); on validation climatology
  is above it. The honest summary is "about at the level of the trivial baselines on macro-F1", with a higher balanced
  accuracy (0.479 to 0.488 against 0.455 / 0.439) because it recalls "Poor or worse" more often than they do (0.23 against
  0.11 / 0.03) and finds the lower classes less well.
* On the identical 30,000 rows the fuzzy classifier (0.470) is below HGB (0.527), random forest (0.514) and logistic
  regression (0.482). With 2,000,000 rows HGB reaches 0.518 and the balanced random forest 0.535 (the highest macro-F1).
  More rows do not clearly help the tree models here (HGB 0.527 on 30 k against 0.518 on 2 M rows; seed noise is not
  measured for the baselines, they are single fits).
* The class-balanced variants recall "Poor or worse" at 0.49 to 0.74 with precision 0.08 to 0.18; as in Madrid, higher
  balanced accuracy is not a better forecaster of the top band, the precision is low for every model.
* The same raw-hour limitation of the logistic regression as in Madrid applies (hour and weekday enter as linear numbers).
* Unknown: 0.58 % of the test rows get no prediction from the fuzzy classifier (no rule fires), every baseline predicts all.

**Macro-F1 per station on test** (371 stations with test rows; the figure for a station averages the classes observed at
that station only, so it is not comparable to the pooled value): persistence 0.394 (min 0.253, max 0.690), climatology
0.292, HGB 0.455, fuzzy 0.404 (min 0.278, max 0.677). HGB is best at 328 of the 371 stations, persistence at 31, the fuzzy
classifier at 6.

## 7. The rules of the published model (seed 0)

| readability metric (published seed) | value |
|---|---|
| rules | 15 |
| rules for Good | 2 |
| rules for Fair | 4 |
| rules for Moderate | 6 |
| rules for Poor or worse | 3 |
| mean rule length (antecedents) | 1.87 |
| duplicate rules (same antecedents) | 0 |
| antecedent sets used with more than one class | 0 |
| rules that win at least one validation row | 15 |
| rules that win at least 1 % of validation rows | 10 |
| share of validation rows with no prediction | 0.0048 |
| share of test rows with no prediction | 0.0058 |
| Jaccard of rules across seeds (mean over pairs) | 0.045 |
| Jaccard of antecedent sets across seeds | 0.072 |

| rule | text | validation rows decided | of those, observed class equal |
|---|---|---|---|
| R01 | IF no2_last IS Good THEN EAQI NO2 = **Good** (peso 0.19) | 49.9 % | 0.73 |
| R02 | IF no2_lag3h IS Good ∧ no2_lag24h IS Good THEN EAQI NO2 = **Good** (peso 0.17) | 4.4 % | 0.51 |
| R03 | IF no2_lag3h IS Good THEN EAQI NO2 = **Fair** (peso 0.018) | 2.7 % | 0.51 |
| R04 | IF no2_last IS Fair ∧ no2_lag3h IS Fair THEN EAQI NO2 = **Fair** (peso 0.068) | 23.1 % | 0.52 |
| R05 | IF no2_lag24h IS Good ∧ wind_speed IS Light breeze THEN EAQI NO2 = **Fair** (peso 0.011) | 0.6 % | 0.44 |
| R06 | IF valid_hour_local IS Night THEN EAQI NO2 = **Fair** (peso 0.026) | 4.9 % | 0.52 |
| R07 | IF temperature IS High ∧ relative_humidity IS Medium THEN EAQI NO2 = **Moderate** (peso 0.0033) | 0.9 % | 0.51 |
| R08 | IF temperature IS Medium ∧ relative_humidity IS High THEN EAQI NO2 = **Moderate** (peso 0.0072) | 1.1 % | 0.44 |
| R09 | IF no2_last IS Moderate ∧ temperature IS Low THEN EAQI NO2 = **Moderate** (peso 0.04) | 6.0 % | 0.54 |
| R10 | IF no2_lag3h IS Moderate ∧ wind_speed IS Gentle to moderate breeze ∧ temperature IS Medium THEN EAQI NO2 = **Moderate** (peso 0.0094) | 1.2 % | 0.52 |
| R11 | IF no2_lag3h IS Fair THEN EAQI NO2 = **Moderate** (peso 0.026) | 2.7 % | 0.44 |
| R12 | IF no2_lag1h IS Fair ∧ no2_lag3h IS Moderate ∧ no2_lag24h IS Fair THEN EAQI NO2 = **Moderate** (peso 0.0068) | 1.2 % | 0.39 |
| R13 | IF no2_last IS Poor or worse ∧ relative_humidity IS Medium THEN EAQI NO2 = **Poor or worse** (peso 0.0036) | 0.0 % | 0.06 |
| R14 | IF no2_lag1h IS Poor or worse ∧ valid_weekday IS Weekday THEN EAQI NO2 = **Poor or worse** (peso 0.01) | 0.3 % | 0.14 |
| R15 | IF wind_speed IS Light breeze ∧ relative_humidity IS Low THEN EAQI NO2 = **Poor or worse** (peso 0.0029) | 0.6 % | 0.08 |

Linguistic terms of the published model: `rules.json` of the run (`artifacts/de_no2_h6/eaqi-justified-seed0/`). The
percentages are shares of validation rows decided by the rule, not probabilities. Rules R13 to R15 (the "Poor or worse"
rules) decide 0.0 %, 0.3 % and 0.6 % of validation rows with an observed-class agreement of 0.06, 0.14 and 0.08: the
top-band rules are weak. R05, R07 and R15 use temperature, humidity or wind with weights of 0.003 to 0.011; they win few
rows and say nothing causal.

## 8. Comparison with Madrid (careful)

EAQI and ICA are different schemes: thresholds 10/25/60 against 40/90/120, four classes with different meanings, different
class mixes (Madrid test: Buena 83.8 %; Germany test: Good 45.8 %, Fair 35.2 %, Moderate 18.2 %, Poor or worse 0.85 %).
Absolute macro-F1, recall and F1 **by class are not comparable between the two tasks** and no table here puts them side by
side. What can be compared are structural things, with the Madrid values from `madrid_no2_h6_ica_v2.md`:

| | Madrid (ICA, `justified`, 60 x 4) | Germany (EAQI, `justified`, 30 x 3) |
|---|---|---|
| test stations / complete rows | 24 / 180,326 | 371 / 2,957,829 |
| seed standard deviation of test macro-F1 | 0.010 | 0.012 |
| rules of the published seed | 15 | 15 |
| rule-set Jaccard across seeds | 0.15 | 0.045 |
| fuzzy test macro-F1 minus persistence | +0.035 | +0.015 |
| fuzzy test macro-F1 minus HGB (30 k rows) | -0.054 | -0.057 |
| fuzzy test macro-F1 minus RF (30 k rows) | -0.065 | -0.044 |
| fit time of one seed (30,000 rows) | 98 to 133 s | 44 s |

The qualitative picture is the same: the fuzzy classifier is a readable model of 11 to 15 rules at the level of the trivial
baselines, a few hundredths of macro-F1 below tree ensembles on the same 30,000 rows, and its rule sets are unstable across
seeds (more so in Germany). It is not evidence that the model "works better in Germany": the Germany task has an even class
mix, which lifts every macro-F1, and 16 times more test rows, which only reduces sampling noise.

## 9. Costs (measured on the workstation, 12 cores, RAM shared with other jobs; one run each)

| stage | wall | peak RSS | notes |
|---|---|---|---|
| load (compact, 21.2 M complete rows of 27.0 M) | 4 to 10 s | 1.9 GB while reading, 1.2 GB table kept | `compact_load`; the old pandas path was not run, estimated above 6 GB (27 M rows x 10 float64 columns plus the finite check) |
| `select` (6 fits of 150 x 60, validation scoring of 3.0 M rows each) | 8 min 42 s | 2.85 GB | fits 36 to 107 s each |
| `final` (14 baselines + 3 seeds, validation and test scoring) | 9 min 37 s | 5.32 GB | baselines 6 min 17 s including scoring 6 M rows each (RF fits 37 and 41 s, HGB 18 s on the 2 M rows); seed fits 44 s each; the peak is in the baseline phase |
| `runs` (3 run directories, 3.0 M-row test prediction tables) | 35 s | 3.9 GB | 32 MB per run directory |
| publish 2025 (trial, `published-de-trial`) | 38.5 s | 1.43 GB | section 10 |

The peak RSS exceeded the 3.5 GB target in `final` (5.3 GB): the first attempt peaked at 5.4 GB in the baseline phase
and was stopped and restarted after freeing each baseline once scored and chunking baseline prediction (500,000 rows); the
figure above is the second attempt. glibc keeps freed memory, so RSS did not fall after the baselines. Rerun with
`baseline_train_rows: 1000000` to stay near 4 GB. `select` alone stays under 3 GB.

**Per station** (440 stations; linear extrapolation is the reader's, the fixed costs are marked):

| | per station | note |
|---|---|---|
| feature table on disk | 1.3 MB | 577 MB hive / 440 |
| compact in-memory table | 2.7 MB | 1.19 GB / 440; the whole `ClassData` is about 2.4 GB (5.5 MB per station) |
| rows | 61.4 k issue hours, 48.2 k complete | |
| fuzzy fit | fixed 44 s | the fit sees 30,000 rows whatever the number of stations (68 rows per station here; 7.5 per station with 4,000 stations) |
| scoring validation + test | 6 M rows in about 20 s per seed, 3.3 microseconds per row | |
| publish one year | 0.09 s, 3.3 MB RSS (month-bounded), 0.43 MB on disk | 38.5 s, 1.43 GB, 190 MB for 440 |
| activation records published | 131 k (15 rules x 8,760 h) | 57.8 M records |
| API | 0.9 MB for the territories of all stations | section 10 |

For a possible all-Europe run on an HPC cluster: the scaling that bites is memory of the table (2.7 MB per station for the compact
frame, 5.5 MB with labels: 4,000 stations would be 11 to 22 GB, more than one 15 GB node; the stations count is an
assumption, not looked up), so the loader should keep per-country or per-station-chunk tables, or fit from a two-pass
sample (class counts first, then the class-tempered draw) without ever holding all rows. The fit (44 s) and the model
(15 rules) do not grow. Publication grows linearly (4,000 stations x 0.43 MB = 1.7 GB of files for one year, with the
`card.json` per-station metrics at 7.5 KB per station = 30 MB, see section 10); evaluating on every station is the
expensive part (about 3.3 microseconds per row).

## 10. Trial publication and API (scratch directory, never `artifacts/published/`)

```bash
PYTHONPATH=src python -m atlas.services.publish \
  --run-dir artifacts/de_no2_h6/eaqi-justified-seed0 \
  --features data/processed/air-de/features/de_no2_h6/table --entities data/processed/air-de/stations.geojson \
  --feature-spec configs/air/de_no2_h6_feature_spec.json --from 2025-01-01T00:00:00Z --to 2026-01-01T00:00:00Z \
  --task-id de_no2_h6 --title "Germany air quality (EEA)" --metadata configs/air/attribution_de.json \
  --published-dir artifacts/published-de-trial --replace
```

**Fixed by A0 at integration** (it failed before): `atlas.services.publish.classify_observed` builds `np.array([c.upper for c in classes])`, and
the merged EAQI scheme has an open top class (`upper = null`, "Poor or worse" is 61 and above), so numpy compares `None`
with a float (`TypeError`). The trial used a local wrapper outside the repo that replaces `classify_observed` by the same
function with `np.inf` for a null upper bound. The fix for A0 (`src/atlas/services/publish.py`, not in A4's zone):

```python
uppers = np.array([np.inf if c.upper is None else c.upper for c in scheme.classes])
```

(and a test with a scheme whose last class is open). Nothing else in publish, the API or the contract needed a change.

Measured (published model of seed 0, 440 stations x 8,760 h of 2025):

| | value |
|---|---|
| publish time | 38.5 s wall (37.4 s reported by the tool) |
| peak RSS | 1.43 GB |
| input rows / activation records | 3,851,320 / 57,769,800 |
| on disk, total | 190 MB in 23 files |
| `inputs.parquet` | 96.0 MB |
| `activations/` (12 monthly files) | 63 MB (4.8 to 5.6 MB each) |
| `predictions.parquet` | 23.8 MB |
| `model.pkl` | 4.6 MB |
| `card.json` | 4.6 MB (3.3 MB of it is `metrics`: per-station slices of 440 stations) |
| `metrics.json` | 4.3 MB |
| `entities.geojson` | 0.66 MB |
| `rules.json`, `run_manifest.json`, `publish.json`, `feature_spec.json`, `SHA256SUMS` | 20, 8, 7, 1, 2 KB |

For comparison the Madrid model (24 stations) is 9.0 MB, of which `inputs.parquet` 1.3 MB, `activations/` 2.0 MB and
`card.json` 0.5 MB. `atlas.services.verify` is ok on the trial directory.

The API in artifacts mode (`ATLAS_API_MODE=artifacts ATLAS_PUBLISHED_DIR=artifacts/published-de-trial`, the Madrid model
copied next to the German one, the registry with both air tasks; `/domains` lists `de_no2_h6` and `madrid_no2_h6` under
`air`), uvicorn on localhost, one process, cold = first request, warm = best of the next two. Payload sizes are uncompressed
(the API does not compress; the gzip size is what a reverse proxy would send):

| request (`de_no2_h6`) | cold | warm | payload | gzip |
|---|---|---|---|---|
| `/entities?domain=air&task_id=de_no2_h6` (440 stations) | 91 ms | 3 ms | 0.45 MB | 0.03 MB |
| `/predictions?time=2025-07-01T12:00Z` (one hour, all stations) | 53 ms | 22 ms | 0.22 MB | 0.01 MB |
| `/observations?time=...` (one hour, all stations, with inputs) | 52 ms | 48 ms | 0.82 MB | 0.03 MB |
| `/rule-map` firing strength, one rule, one hour | 16 ms | 3 ms | 0.25 MB | 0.01 MB |
| `/rule-map` mean activation, one rule, 1 / 31 / 365 days | 13 / 22 / 154 ms | 2 to 4 ms | 0.24 MB | 0.02 MB |
| `/rule-territories` mean activation, 1 day | 345 ms | 5 ms | 0.75 MB | 0.05 MB |
| `/rule-territories`, 7 / 31 / 92 days | 307 / 510 / 537 ms | 6 to 7 ms | 0.82 to 0.88 MB | 0.08 to 0.15 MB |
| `/rule-territories`, 365 days | 1,283 ms | 6 ms | 0.92 MB | 0.18 MB |
| `/rule-territories` winner share, 31 days | 484 ms | 7 ms | 0.84 MB | 0.11 MB |
| `/rule-stories`, 31 days | 176 ms | 1 ms | 0.02 MB | 0.00 MB |
| `/entities/DEBE010/rule-trace`, one hour | 26 ms | 12 ms | 0.01 MB | 0.00 MB |
| `/series`, one station, 7 / 31 days | 8 / 20 ms | 7 / 20 ms | 0.04 / 0.17 MB | 0.01 MB |
| `/series`, one station, the whole year | 5 pages of 2,000 points, 0.22 s | | 2.0 MB in total | |
| `/models/exfuzzy-de_no2_h6-eaqi-justified-seed0` (card) | 13 ms | 11 ms | 3.08 MB | 0.38 MB |

The API process was at 0.4 GB RSS at the end. Observations: (1) every request is below 1 s except the first
`rule-territories` over a whole year (1.3 s cold, 6 ms after, cached); (2) the largest payload is the model card, 3.1 MB,
because `metrics` carries per-station slices; it is fetched once per model; (3) nothing exceeds the 1 GB, 1 s or 5 MB
guides, so **the full 2025 year is fine for a local demo and no shorter window is needed**. Had one been needed, the last
quarter of 2025 would be a quarter of the files (about 48 MB) and cut the year-long territory request to 0.5 s cold. The
caveat below was resolved by A0 at integration (colours in section 2; the merged-class block is now in
`configs/air/attribution_de.json`). It read: the null colours (section 2) and the missing `merged_from` / description for "Poor or worse"
(`configs/air/attribution_de.json` has `classes: {}`; the trial `card.json` therefore has `merged_from: []`) make the web
show the merged class without the usual note on its three official members. A0 can add, in the style of
`configs/air/attribution.json`:

```json
"classes": {"Poor or worse": {"merged_from": ["Poor", "Very poor", "Extremely poor"],
  "description": "Groups three EAQI bands for NO2 that the model does not distinguish: Poor (61-100 ug/m3), Very poor (101-150 ug/m3) and Extremely poor (above 150 ug/m3)."}}
```

This description repeats only the band limits of the EEA table and no health message.

## 11. Contract artifacts

`artifacts/de_no2_h6/eaqi-justified-seed{0,1,2}/` (manifest, metrics, rules with the target scheme, test predictions,
`model.pkl`, `SHA256SUMS`) and `artifacts/de_no2_h6/experiments/eaqi-justified/` (`class_distribution.json`,
`selection.json`, `summary.json`, `subsample_keys.parquet`, `models/`). All git-ignored. The rule text uses
`target_label: "EAQI NO2"` ("IF ... THEN EAQI NO2 = Moderate"). Seeds, subsample seed, split and the full config are in each
run manifest. Provenance of ex_fuzzy: the run manifests record the PyPI release.

## 12. Reproduce

```bash
export ATLAS_DATA_DIR=/path/to/exfuzzy-atlas/data ATLAS_ARTIFACTS_DIR=/path/to/exfuzzy-atlas/artifacts
export PYTHONPATH=src
C=configs/ml/de_no2_h6_eaqi_experiment.json
python -m atlas.ml.experiment_class select --config $C      #  8.7 min, 2.9 GB
python -m atlas.ml.experiment_class final  --config $C      #  9.6 min, 5.3 GB (test read once)
python -m atlas.ml.experiment_class runs   --config $C      #  35 s
python -m atlas.ml.report_class --experiment $ATLAS_ARTIFACTS_DIR/de_no2_h6/experiments/eaqi-justified \
    --run-dir $ATLAS_ARTIFACTS_DIR/de_no2_h6/eaqi-justified-seed0
```

Needs the Germany table (`../air/germany.md`). Check available RAM first (`free -g`): `final` needs about 5.5 GB.
`ex_fuzzy` is the PyPI 3.3.1 (no `EXFUZZY_SRC`). The diurnal profile of section 3 is a DuckDB aggregate over the train
rows of the table (the query is in the section; no script is committed).

## 13. Shared-code changes of this task (all backward compatible; Madrid results and configs unchanged)

* `atlas.ml.classification.ClassScheme`: `merged_label_suffix` (default `" o peor"`; EAQI `" or worse"`),
  `below_first_as_first` (default false), open top class (`ClassBand.upper` null, `color` / `description` optional),
  `merge_rare_upper_tail(counts, min_count=None, *, min_share=None)`, chunked `classify`.
* `ClassExperimentConfig`: `merge_min_train_share` (exclusive with `merge_min_train_rows`, which stays 500 by default),
  `target_label` (default "ICA"), `baseline_train_rows` (default none), `compact_load` (default false, in
  `ExperimentConfig`); follows-target-scheme check for an open top class.
* `atlas.ml.compact_load` (new): batch-wise reading of the complete rows, float32 features except the target and the
  persistence feature. The complete rows, class counts, merges, row order and subsample equal those of the old loader
  restricted to complete rows (test). Float32 features differ from the table by a relative error below 6e-8; the published
  model is scored on the float64 table.
* Memory: block coding of `stratified_subsample` without one string per row (same draws, test against the old code),
  column-wise finite check and key-sort duplicate check in `Data`, chunked `FuzzyClassifier.predict`,
  `classifier_readability_rows`, climatology fit and baseline prediction.
* `atlas.ml.partitions.scheme_partition(domain_upper=, domain_lower=)`; `report_class` prints per-class F1 and takes the rule
  label from the run manifest.
* Madrid check on the real data (2026-11-02): `ClassData` of `madrid_no2_h6_ica2_justified_experiment.json` with the new code
  gives a 30,000-row subsample equal key by key to the published `subsample_keys.parquet` of `ica2-justified`, and a
  `class_distribution.json` equal to the committed one.
* Tests: `tests/ml/test_de_eaqi.py` (15 tests); full suite 824 passed, 156 skipped, `ruff` clean, with the PyPI ex_fuzzy 3.3.1
  and `PYTHONPATH=src` (without it `tests/services/test_verify.py::test_cli_as_a_module...` fails in its subprocess, also on main).

## 14. Risks and limits

* Not a health or exposure statement; one station is a point, not an area. Not causal.
* Temporal drift: the NO2 level fell from 17.9 (train) to 14.6 (validation) and 15.5 ug/m3 (test); "Poor or worse" went
  from 1.9 % to 0.6 % and 0.85 %. A model fitted to 2019-2023 is evaluated on cleaner years.
* The baselines "of the full training period" use a 2 M-row sample; the fuzzy classifier a 30 k-row one; baselines are single
  fits; the fuzzy comparison rests on three seeds. Differences below about 0.02 macro-F1 should not be read.
* Stations differ in type and region (traffic, background, rural) and the model has no station feature; per-station macro-F1
  ranges from 0.28 to 0.68. Meteorology is from the nearest DWD station within 25 km (median 7.6 km temperature, 9.9 km wind),
  not co-located; 33 stations (7.5 %) lack wind within 25 km and are never scored (incomplete rows).
* 0.58 % of the test rows have no prediction (no rule fires), counted as wrong.
* Top-band rules are weak (observed-class agreement 0.06 to 0.14); the model should not be used to flag high-NO2 hours.
* EAQI colours and the merged-class metadata were added by A0 at integration (sections 2 and 10).
