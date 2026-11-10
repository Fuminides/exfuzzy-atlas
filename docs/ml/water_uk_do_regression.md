# Dissolved oxygen of UK rivers from the same sample: ExFuzzy TSK regressor with detection-limit terms, with and without temperature (AT-041f)

First Water model of Atlas. It estimates the dissolved oxygen (DO, mg/l) of a river sample from the ammonia, orthophosphate,
temperature, pH, season and time of day measured **in that same sample** (`uk_water_do`, AT-021): a **descriptive
same-sample inference**, horizon 0 (`valid_at = issued_at`), not a forecast. The user chose regression and dropped the
ecological banding. Every number below is printed by `python -m atlas.ml.report_water` from the run artifacts (commands at
the end).

**Served model since 2026-10-31: `exfuzzy-uk_water_do-fx-w-unique-seed0`.** The model of this document
(`water-do-chrono-temp-seed0`, 39 rules of which 12 repeat an antecedent set) was replaced as the served `uk_water_do` model by
seed 0 of the same configuration refitted with `unique_antecedents=True` (FX Experiment 2 of
`docs/ml/fx_retrain_with_fixed_exfuzzy.md`, on the local ex_fuzzy build, decision of the author on 2026-10-31):

| | `water-do-chrono-temp-seed0` (this document) | `fx-w-unique-seed0` (served) |
|---|---|---|
| rules / distinct antecedent sets / duplicates | 39 / 27 / 12 | 39 / 39 / 0 |
| validation RMSE | 0.907 | 0.925 |
| test RMSE, MAE, R2 (3,264 rows) | 0.920, 0.630, 0.673 | 0.932, 0.635, 0.665 |
| recorded `exfuzzy_version` | `3.3.1` | `3.3.1+g2ffcfb9` (+ manifest warning: unreleased build) |

The cost of readability is about +0.012 mg/l of test RMSE for this seed (+0.016 for the three-seed mean). The old model's
directory stays in `artifacts/published` (unregistered), so the rest of this document still describes a published artifact;
only section 5 says which id the registry serves. The 39 rules of the served model are listed in section 2 of the FX document.

**What this is not.** A rule such as "ammonia ≤ L ∧ summer → DO = 10 mg/l" describes an association in the Environment
Agency archive: it is not a cause, a probability, a forecast, an official assessment of a water body, or valid between
sampling points (points are not river reaches). Firing is a degree of rule match, never a probability or a contribution.
No real-time or alert capability is claimed (laboratory results arrive days or months later; the table is a historic
reconstruction).

## 0. Protocol

| Element | Decision |
|---|---|
| Table | `data/processed/water/features/uk_water_do` (14,025 samples, 426 points, 2015-2025); target `target` = DO, mg/l. **Complete rows** = target and the 6 recommended inputs finite (13,045): every arm scores the same rows |
| Inputs | the 6 recommended of `configs/water/feature_spec.json`: `ammoniacal_nitrogen`, `orthophosphate_reactive`, `water_temperature`, `days_from_midwinter`, `ph`, `local_hour`. The variant **without temperature** drops `water_temperature` (5 inputs). `point_median_phosphate_train` and `local_day_of_year` are not used |
| Splits | **chronological**: train `[2015-01-01, 2021-12-01)` 7,862 complete rows, validation `[2022-01-01, 2023-12-01)` 1,726, test `[2024-01-01, 2026-01-01)` 3,264, embargo 30 days (`SplitSpec`, `configs/water/uk_water_do.json`). **Spatial**: whole points held out by the `entity_id` mask of `uk_water_do_spatial_split.json` (seed 20261030, 70/10/20 % of the points, every date): train 8,665, validation 1,074, test 3,306 rows. Four arms: {chronological, spatial} x {with, without temperature} |
| Fitting rows | every complete training row (7-9 thousand: no subsample is needed) |
| Model | `FuzzyRegressor` family: zero-order TSK, crisp consequents, additive rule mode (`Σ f c / Σ f`), 3 seeds. Linguistic variables in section 1, built from the training rows of the split in use |
| Shape selection | 9 shapes (10, 20, 40 rules x 2, 3, 4 antecedents), one fit each with seed 0, 150 generations x population 60, per arm; criterion lowest validation RMSE (ties: fewer rules). Then 3 seeds (0, 1, 2) of the chosen shape; validation and test scored in the same command, test read once; published seed = lowest validation RMSE |
| Baselines | global training mean; mean of the point (chronological split only, global mean for points not seen); season-only (mean by 12 equal bins of `days_from_midwinter`); Ridge (median imputation, standardised, alpha 1); random forest (300 trees, 5-row leaves); histogram gradient boosting (200 iterations); a quadratic in water temperature where the temperature is an input. All on the same inputs as the fuzzy model. **No persistence feature** (no previous value of the target is used anywhere) |
| Reported | MAE, RMSE, R2 overall, by season term, by observed DO below / at or above 8 mg/l (a descriptive slice of 3-5 % of the rows, not a standard) and, chronologically, by "point seen in training" |
| Published model | the **chronological split with temperature**: the arm with the lowest validation RMSE (0.907 against 1.295 without temperature), because it is the only split that has a publishable period (the test years) and the task is "estimate the DO of a sample". The variant without temperature has run directories as well and can be published instead (section 6) |

## 1. Linguistic terms

`configs/ml/water_partitions.json` documents every variable: `variables` follow the format of `madrid_partitions.json`
(`load_partition_file`), `censored` are read by `atlas.ml.water_fuzzy`. Everything data-driven is built from the training
rows of the split in use.

| input | terms | rationale |
|---|---|---|
| `ammoniacal_nitrogen` (limit L = 0.03 mg/l) | `<=L`, `Bajo>L`, `Medio>L`, `Alto>L` | The table harmonises every ammonia result known to be at or below the dominant detection limit to L (70.6 % of the non-missing values are exactly L; below L the table knows nothing). **Term `<=L` is exactly the set of values equal to L**: membership 1 at L, 0 from the smallest measured value above it (0.0304 mg/l, the reporting resolution), i.e. a crisp step on the data. A rule that says `ammoniacal_nitrogen IS <=L` means "not above the detection limit", never "zero". The three terms above are the ex_fuzzy quantile terms (20/40/60/80 %) of the training values strictly above L; the first one starts at the smallest of them so that it is 0 at L (no overlap with `<=L`) |
| `orthophosphate_reactive` (L = 0.01 mg/l) | `<=L`, `Bajo>L`, `Medio>L`, `Alto>L` | same (39.3 % of the values are exactly L; smallest value above L 0.0101 mg/l) |
| `days_from_midwinter` | `Invierno` 0-45, `Primavera-otoño` 46-137, `Verano` 138-183 days; shoulders 15 days | the feature is the distance in days to the nearest 21 December, so spring and autumn share a value and cannot be told apart. Three terms centred on the solstices and the equinoxes (0, 91.5, 183 days), cut at the midpoints (45.5, 137.5): Invierno is about 6 Nov-4 Feb, Verano about 6 May-7 Aug, Primavera-otoño the rest. Not the meteorological or astronomical seasons. The 15-day shoulder (about half a month) is a convention for a gradual change, not a measured quantity, and its sensitivity was not studied |
| `water_temperature`, `ph`, `local_hour` | Low / Medium / High, **data-driven** | ex_fuzzy trapezoids at the 20/40/60/80 % quantiles of the training rows. No citable categorical scheme for a river sample was verified (the Water Framework Directive standards are percentile standards by water-body type and were not checked), and the sampling hour clusters in working hours (median 10.25 h, interquartile range 9.15-11.5 h); nothing was invented, the terms carry no authority |

The two 4-term variables come first in the input order because ex_fuzzy 3.3.1 bounds the term index of the k-th antecedent
slot by the number of terms of the k-th feature. The terms of the published seed (the quantile terms and the shapes above
L depend on the training rows):

| variable | term | trapezoid [a, b, c, d] |
|---|---|---|
| ammoniacal_nitrogen | <=L | [0.03, 0.03, 0.03, 0.0304] |
| ammoniacal_nitrogen | Bajo>L | [0.0304, 0.0304, 0.039, 0.0525] |
| ammoniacal_nitrogen | Medio>L | [0.039, 0.0525, 0.082, 0.17] |
| ammoniacal_nitrogen | Alto>L | [0.082, 0.17, 263, 263] |
| orthophosphate_reactive | <=L | [0.01, 0.01, 0.01, 0.0101] |
| orthophosphate_reactive | Bajo>L | [0.0101, 0.0101, 0.01748, 0.029] |
| orthophosphate_reactive | Medio>L | [0.01748, 0.029, 0.055, 0.118] |
| orthophosphate_reactive | Alto>L | [0.055, 0.118, 5.17, 5.17] |
| water_temperature | Low | [-0.0001, -0.0001, 4.7, 7] |
| water_temperature | Medium | [4.7, 7, 10.1, 13.1] |
| water_temperature | High | [10.1, 13.1, 22.5, 22.5] |
| days_from_midwinter | Invierno | [0, 0, 45, 60] |
| days_from_midwinter | Primavera-otoño | [31, 46, 137, 152] |
| days_from_midwinter | Verano | [123, 138, 183, 183] |
| ph | Low | [3.83, 3.83, 7.75, 7.94] |
| ph | Medium | [7.75, 7.94, 8.09, 8.26] |
| ph | High | [8.09, 8.26, 9.51, 9.51] |
| local_hour | Low | [5.417, 5.417, 8.983, 9.867] |
| local_hour | Medium | [8.983, 9.867, 10.7, 11.77] |
| local_hour | High | [10.7, 11.77, 15.63, 15.63] |
## 2. Results

### Test RMSE (mg/l) and R2 of every estimator in the four arms

Published seed for ExFuzzy (lowest validation RMSE among the 3 seeds), one fit per baseline; the test rows were read once, in the `final` command of each arm.

| test RMSE / R2 | chrono, with temperature | chrono, without temperature | spatial, with temperature | spatial, without temperature |
|---|---|---|---|---|
| global_mean | 1.626 / -0.02 | 1.626 / -0.02 | 1.888 / -0.02 | 1.888 / -0.02 |
| point_mean | 1.581 / 0.04 | 1.581 / 0.04 |  |  |
| season_only | 1.409 / 0.23 | 1.409 / 0.23 | 1.623 / 0.24 | 1.623 / 0.24 |
| temperature_only_quadratic | 1.025 / 0.59 |  | 1.267 / 0.54 |  |
| ridge | 1.016 / 0.60 | 1.343 / 0.30 | 1.266 / 0.54 | 1.614 / 0.25 |
| random_forest | 0.864 / 0.71 | 1.289 / 0.36 | 0.970 / 0.73 | 1.356 / 0.47 |
| hist_gradient_boosting | 0.881 / 0.70 | 1.290 / 0.36 | 0.926 / 0.75 | 1.336 / 0.49 |
| exfuzzy_tsk | 0.920 / 0.67 | 1.240 / 0.41 | 1.096 / 0.66 | 1.426 / 0.42 |

### Chronological split, with water temperature

Rows: train 7,862, validation 1,726, test 3,264. Chosen shape 40 rules x 2 antecedents; published seed 0.

**Shape selection (seed 0, validation RMSE)**

| nRules | nAnts | val MAE | val RMSE | val R2 | distinct rules | mean length | fit s |
|---|---|---|---|---|---|---|---|
| 40 | 2 | 0.606 | 0.907 | 0.704 | 27 | 1.36 | 55 |
| 20 | 3 | 0.610 | 0.927 | 0.691 | 17 | 1.70 | 21 |
| 40 | 3 | 0.640 | 0.937 | 0.684 | 35 | 1.65 | 53 |
| 20 | 2 | 0.617 | 0.938 | 0.683 | 18 | 1.50 | 23 |
| 10 | 2 | 0.649 | 0.947 | 0.677 | 8 | 1.50 | 7 |
| 10 | 4 | 0.636 | 0.958 | 0.670 | 9 | 1.80 | 8 |
| 40 | 4 | 0.675 | 0.992 | 0.646 | 35 | 2.42 | 56 |
| 20 | 4 | 0.655 | 1.022 | 0.624 | 18 | 2.40 | 25 |
| 10 | 3 | 0.757 | 1.082 | 0.579 | 10 | 1.80 | 7 |

**Three seeds of the chosen shape (mean +- sd with n-1)**

| period | MAE | RMSE | R2 | RMSE by seed |
|---|---|---|---|---|
| validation | 0.611 +- 0.012 | 0.916 +- 0.010 | 0.698 +- 0.007 | 0.907, 0.914, 0.927 |
| test | 0.627 +- 0.003 | 0.922 +- 0.003 | 0.672 +- 0.002 | 0.920, 0.920, 0.926 |

**Validation**

| estimator | MAE (mg/l) | RMSE (mg/l) | R2 |
|---|---|---|---|
| global_mean | 1.342 | 1.669 | -0.002 |
| point_mean | 1.330 | 1.663 | 0.005 |
| season_only | 1.032 | 1.398 | 0.298 |
| temperature_only_quadratic | 0.611 | 1.011 | 0.632 |
| ridge | 0.616 | 0.992 | 0.646 |
| random_forest | 0.506 | 0.799 | 0.770 |
| hist_gradient_boosting | 0.519 | 0.800 | 0.770 |
| exfuzzy_tsk | 0.606 | 0.907 | 0.704 |

**Test**

| estimator | MAE (mg/l) | RMSE (mg/l) | R2 |
|---|---|---|---|
| global_mean | 1.282 | 1.626 | -0.020 |
| point_mean | 1.265 | 1.581 | 0.036 |
| season_only | 1.045 | 1.409 | 0.234 |
| temperature_only_quadratic | 0.651 | 1.025 | 0.595 |
| ridge | 0.659 | 1.016 | 0.602 |
| random_forest | 0.548 | 0.864 | 0.712 |
| hist_gradient_boosting | 0.562 | 0.881 | 0.700 |
| exfuzzy_tsk | 0.630 | 0.920 | 0.673 |

**Test RMSE by season (`days_from_midwinter` cut at 45.5 and 137.5)**

| estimator | spring_autumn (n=1586) RMSE | summer (n=794) RMSE | winter (n=884) RMSE |
|---|---|---|---|
| global_mean | 1.625 | 1.855 | 1.390 |
| point_mean | 1.552 | 1.803 | 1.410 |
| season_only | 1.653 | 1.212 | 1.053 |
| temperature_only_quadratic | 1.142 | 1.129 | 0.628 |
| ridge | 1.080 | 1.100 | 0.793 |
| random_forest | 0.921 | 0.989 | 0.597 |
| hist_gradient_boosting | 0.931 | 1.011 | 0.629 |
| exfuzzy_tsk | 0.999 | 0.958 | 0.715 |

**Test RMSE by observed DO below / at or above 8 mg/l (descriptive slice, not a standard)**

| estimator | ge_8 (n=3167) RMSE | lt_8 (n=97) RMSE |
|---|---|---|
| global_mean | 1.404 | 4.958 |
| point_mean | 1.403 | 4.452 |
| season_only | 1.197 | 4.474 |
| temperature_only_quadratic | 0.805 | 3.767 |
| ridge | 0.840 | 3.414 |
| random_forest | 0.707 | 2.964 |
| hist_gradient_boosting | 0.727 | 2.982 |
| exfuzzy_tsk | 0.788 | 2.868 |

**Test RMSE by sampling point seen in the training period**

| estimator | no (n=990) RMSE | yes (n=2274) RMSE |
|---|---|---|
| global_mean | 1.689 | 1.598 |
| point_mean | 1.689 | 1.532 |
| season_only | 1.569 | 1.333 |
| temperature_only_quadratic | 1.207 | 0.934 |
| ridge | 1.223 | 0.911 |
| random_forest | 1.029 | 0.781 |
| hist_gradient_boosting | 1.053 | 0.795 |
| exfuzzy_tsk | 1.063 | 0.851 |

**Readability of the fitted rule sets**

| seed | rules | distinct antecedent sets | duplicates | mean length | consequent range | negative consequents |
|---|---|---|---|---|---|---|
| 0 | 39 | 27 | 12 | 1.36 | 1.20 .. 18.62 | 0 |
| 1 | 37 | 28 | 9 | 1.46 | 1.02 .. 17.73 | 0 |
| 2 | 39 | 28 | 11 | 1.41 | 1.02 .. 18.62 | 0 |

### Chronological split, without water temperature

Rows: train 7,862, validation 1,726, test 3,264. Chosen shape 40 rules x 3 antecedents; published seed 0.

**Shape selection (seed 0, validation RMSE)**

| nRules | nAnts | val MAE | val RMSE | val R2 | distinct rules | mean length | fit s |
|---|---|---|---|---|---|---|---|
| 40 | 3 | 0.965 | 1.295 | 0.397 | 32 | 1.52 | 50 |
| 40 | 4 | 0.969 | 1.307 | 0.386 | 34 | 2.02 | 51 |
| 20 | 2 | 0.977 | 1.316 | 0.377 | 15 | 1.40 | 19 |
| 40 | 2 | 0.978 | 1.316 | 0.377 | 32 | 1.49 | 50 |
| 20 | 3 | 0.994 | 1.351 | 0.343 | 17 | 2.00 | 20 |
| 10 | 2 | 0.990 | 1.352 | 0.343 | 9 | 1.30 | 7 |
| 20 | 4 | 1.027 | 1.414 | 0.281 | 18 | 2.15 | 21 |
| 10 | 4 | 1.097 | 1.420 | 0.275 | 10 | 2.20 | 8 |
| 10 | 3 | 1.072 | 1.437 | 0.257 | 7 | 1.70 | 7 |

**Three seeds of the chosen shape (mean +- sd with n-1)**

| period | MAE | RMSE | R2 | RMSE by seed |
|---|---|---|---|---|
| validation | 0.985 +- 0.017 | 1.314 +- 0.017 | 0.379 +- 0.016 | 1.295, 1.319, 1.329 |
| test | 0.938 +- 0.013 | 1.256 +- 0.015 | 0.391 +- 0.014 | 1.240, 1.269, 1.260 |

**Validation**

| estimator | MAE (mg/l) | RMSE (mg/l) | R2 |
|---|---|---|---|
| global_mean | 1.342 | 1.669 | -0.002 |
| point_mean | 1.330 | 1.663 | 0.005 |
| season_only | 1.032 | 1.398 | 0.298 |
| ridge | 1.019 | 1.371 | 0.324 |
| random_forest | 0.967 | 1.291 | 0.401 |
| hist_gradient_boosting | 0.963 | 1.281 | 0.410 |
| exfuzzy_tsk | 0.965 | 1.295 | 0.397 |

**Test**

| estimator | MAE (mg/l) | RMSE (mg/l) | R2 |
|---|---|---|---|
| global_mean | 1.282 | 1.626 | -0.020 |
| point_mean | 1.265 | 1.581 | 0.036 |
| season_only | 1.045 | 1.409 | 0.234 |
| ridge | 0.995 | 1.343 | 0.304 |
| random_forest | 0.949 | 1.289 | 0.359 |
| hist_gradient_boosting | 0.944 | 1.290 | 0.358 |
| exfuzzy_tsk | 0.925 | 1.240 | 0.407 |

**Test RMSE by season (`days_from_midwinter` cut at 45.5 and 137.5)**

| estimator | spring_autumn (n=1586) RMSE | summer (n=794) RMSE | winter (n=884) RMSE |
|---|---|---|---|
| global_mean | 1.625 | 1.855 | 1.390 |
| point_mean | 1.552 | 1.803 | 1.410 |
| season_only | 1.653 | 1.212 | 1.053 |
| ridge | 1.541 | 1.203 | 1.050 |
| random_forest | 1.507 | 1.105 | 0.981 |
| hist_gradient_boosting | 1.500 | 1.132 | 0.978 |
| exfuzzy_tsk | 1.462 | 1.018 | 0.956 |

**Test RMSE by observed DO below / at or above 8 mg/l (descriptive slice, not a standard)**

| estimator | ge_8 (n=3167) RMSE | lt_8 (n=97) RMSE |
|---|---|---|
| global_mean | 1.404 | 4.958 |
| point_mean | 1.403 | 4.452 |
| season_only | 1.197 | 4.474 |
| ridge | 1.161 | 4.087 |
| random_forest | 1.142 | 3.654 |
| hist_gradient_boosting | 1.140 | 3.683 |
| exfuzzy_tsk | 1.088 | 3.625 |

**Test RMSE by sampling point seen in the training period**

| estimator | no (n=990) RMSE | yes (n=2274) RMSE |
|---|---|---|
| global_mean | 1.689 | 1.598 |
| point_mean | 1.689 | 1.532 |
| season_only | 1.569 | 1.333 |
| ridge | 1.498 | 1.270 |
| random_forest | 1.447 | 1.214 |
| hist_gradient_boosting | 1.462 | 1.208 |
| exfuzzy_tsk | 1.363 | 1.183 |

**Readability of the fitted rule sets**

| seed | rules | distinct antecedent sets | duplicates | mean length | consequent range | negative consequents |
|---|---|---|---|---|---|---|
| 0 | 40 | 32 | 8 | 1.52 | 1.55 .. 18.62 | 0 |
| 1 | 40 | 37 | 3 | 2.00 | 2.62 .. 16.67 | 0 |
| 2 | 40 | 33 | 7 | 1.98 | 1.73 .. 18.09 | 0 |

### Spatial hold-out of points, with water temperature

Rows: train 8,665, validation 1,074, test 3,306. Chosen shape 20 rules x 2 antecedents; published seed 0.

**Shape selection (seed 0, validation RMSE)**

| nRules | nAnts | val MAE | val RMSE | val R2 | distinct rules | mean length | fit s |
|---|---|---|---|---|---|---|---|
| 20 | 2 | 0.712 | 1.222 | 0.582 | 14 | 1.10 | 33 |
| 40 | 2 | 0.744 | 1.249 | 0.563 | 29 | 1.56 | 43 |
| 40 | 3 | 0.731 | 1.251 | 0.562 | 34 | 1.68 | 42 |
| 10 | 2 | 0.759 | 1.261 | 0.555 | 10 | 1.40 | 9 |
| 20 | 3 | 0.754 | 1.292 | 0.532 | 19 | 1.95 | 27 |
| 40 | 4 | 0.779 | 1.301 | 0.526 | 36 | 2.42 | 42 |
| 10 | 3 | 0.859 | 1.393 | 0.457 | 10 | 2.00 | 8 |
| 20 | 4 | 0.844 | 1.410 | 0.443 | 17 | 2.45 | 17 |
| 10 | 4 | 0.878 | 1.533 | 0.342 | 9 | 2.40 | 9 |

**Three seeds of the chosen shape (mean +- sd with n-1)**

| period | MAE | RMSE | R2 | RMSE by seed |
|---|---|---|---|---|
| validation | 0.740 +- 0.024 | 1.253 +- 0.027 | 0.560 +- 0.019 | 1.222, 1.264, 1.272 |
| test | 0.737 +- 0.012 | 1.122 +- 0.027 | 0.639 +- 0.017 | 1.096, 1.119, 1.150 |

**Validation**

| estimator | MAE (mg/l) | RMSE (mg/l) | R2 |
|---|---|---|---|
| global_mean | 1.396 | 1.896 | -0.007 |
| season_only | 1.166 | 1.709 | 0.182 |
| temperature_only_quadratic | 0.776 | 1.400 | 0.451 |
| ridge | 0.754 | 1.345 | 0.493 |
| random_forest | 0.637 | 1.190 | 0.603 |
| hist_gradient_boosting | 0.640 | 1.187 | 0.605 |
| exfuzzy_tsk | 0.712 | 1.222 | 0.582 |

**Test**

| estimator | MAE (mg/l) | RMSE (mg/l) | R2 |
|---|---|---|---|
| global_mean | 1.456 | 1.888 | -0.022 |
| season_only | 1.157 | 1.623 | 0.244 |
| temperature_only_quadratic | 0.752 | 1.267 | 0.540 |
| ridge | 0.729 | 1.266 | 0.540 |
| random_forest | 0.611 | 0.970 | 0.730 |
| hist_gradient_boosting | 0.597 | 0.926 | 0.754 |
| exfuzzy_tsk | 0.727 | 1.096 | 0.655 |

**Test RMSE by season (`days_from_midwinter` cut at 45.5 and 137.5)**

| estimator | spring_autumn (n=1667) RMSE | summer (n=780) RMSE | winter (n=859) RMSE |
|---|---|---|---|
| global_mean | 1.843 | 2.233 | 1.611 |
| season_only | 1.767 | 1.581 | 1.345 |
| temperature_only_quadratic | 1.315 | 1.408 | 1.010 |
| ridge | 1.372 | 1.313 | 0.973 |
| random_forest | 1.008 | 1.009 | 0.850 |
| hist_gradient_boosting | 0.960 | 0.993 | 0.787 |
| exfuzzy_tsk | 1.131 | 1.164 | 0.957 |

**Test RMSE by observed DO below / at or above 8 mg/l (descriptive slice, not a standard)**

| estimator | ge_8 (n=3129) RMSE | lt_8 (n=177) RMSE |
|---|---|---|
| global_mean | 1.490 | 5.227 |
| season_only | 1.213 | 4.818 |
| temperature_only_quadratic | 0.841 | 4.178 |
| ridge | 0.945 | 3.764 |
| random_forest | 0.709 | 2.944 |
| hist_gradient_boosting | 0.706 | 2.687 |
| exfuzzy_tsk | 0.811 | 3.289 |

**Readability of the fitted rule sets**

| seed | rules | distinct antecedent sets | duplicates | mean length | consequent range | negative consequents |
|---|---|---|---|---|---|---|
| 0 | 20 | 14 | 6 | 1.10 | n/a | n/a |
| 1 | 20 | 18 | 2 | 1.40 | n/a | n/a |
| 2 | 19 | 17 | 2 | 1.42 | n/a | n/a |

### Spatial hold-out of points, without water temperature

Rows: train 8,665, validation 1,074, test 3,306. Chosen shape 20 rules x 2 antecedents; published seed 1.

**Shape selection (seed 0, validation RMSE)**

| nRules | nAnts | val MAE | val RMSE | val R2 | distinct rules | mean length | fit s |
|---|---|---|---|---|---|---|---|
| 20 | 2 | 1.049 | 1.521 | 0.352 | 16 | 1.35 | 12 |
| 40 | 3 | 1.040 | 1.525 | 0.349 | 33 | 1.52 | 33 |
| 10 | 2 | 1.071 | 1.530 | 0.344 | 10 | 1.60 | 6 |
| 40 | 2 | 1.040 | 1.531 | 0.344 | 26 | 1.40 | 38 |
| 20 | 3 | 1.079 | 1.549 | 0.328 | 16 | 1.65 | 12 |
| 40 | 4 | 1.091 | 1.574 | 0.306 | 35 | 2.42 | 34 |
| 20 | 4 | 1.125 | 1.622 | 0.263 | 16 | 2.20 | 13 |
| 10 | 4 | 1.129 | 1.625 | 0.260 | 10 | 2.30 | 6 |
| 10 | 3 | 1.143 | 1.626 | 0.260 | 10 | 1.80 | 7 |

**Three seeds of the chosen shape (mean +- sd with n-1)**

| period | MAE | RMSE | R2 | RMSE by seed |
|---|---|---|---|---|
| validation | 1.046 +- 0.009 | 1.513 +- 0.007 | 0.359 +- 0.006 | 1.521, 1.508, 1.509 |
| test | 1.064 +- 0.008 | 1.438 +- 0.011 | 0.407 +- 0.009 | 1.440, 1.426, 1.447 |

**Validation**

| estimator | MAE (mg/l) | RMSE (mg/l) | R2 |
|---|---|---|---|
| global_mean | 1.396 | 1.896 | -0.007 |
| season_only | 1.166 | 1.709 | 0.182 |
| ridge | 1.145 | 1.656 | 0.231 |
| random_forest | 0.978 | 1.475 | 0.390 |
| hist_gradient_boosting | 0.984 | 1.487 | 0.381 |
| exfuzzy_tsk | 1.037 | 1.508 | 0.363 |

**Test**

| estimator | MAE (mg/l) | RMSE (mg/l) | R2 |
|---|---|---|---|
| global_mean | 1.456 | 1.888 | -0.022 |
| season_only | 1.157 | 1.623 | 0.244 |
| ridge | 1.149 | 1.614 | 0.253 |
| random_forest | 0.978 | 1.356 | 0.473 |
| hist_gradient_boosting | 0.979 | 1.336 | 0.488 |
| exfuzzy_tsk | 1.055 | 1.426 | 0.416 |

**Test RMSE by season (`days_from_midwinter` cut at 45.5 and 137.5)**

| estimator | spring_autumn (n=1667) RMSE | summer (n=780) RMSE | winter (n=859) RMSE |
|---|---|---|---|
| global_mean | 1.843 | 2.233 | 1.611 |
| season_only | 1.767 | 1.581 | 1.345 |
| ridge | 1.775 | 1.558 | 1.307 |
| random_forest | 1.494 | 1.262 | 1.141 |
| hist_gradient_boosting | 1.470 | 1.249 | 1.121 |
| exfuzzy_tsk | 1.587 | 1.264 | 1.220 |

**Test RMSE by observed DO below / at or above 8 mg/l (descriptive slice, not a standard)**

| estimator | ge_8 (n=3129) RMSE | lt_8 (n=177) RMSE |
|---|---|---|
| global_mean | 1.490 | 5.227 |
| season_only | 1.213 | 4.818 |
| ridge | 1.283 | 4.423 |
| random_forest | 1.125 | 3.459 |
| hist_gradient_boosting | 1.130 | 3.276 |
| exfuzzy_tsk | 1.184 | 3.637 |

**Readability of the fitted rule sets**

| seed | rules | distinct antecedent sets | duplicates | mean length | consequent range | negative consequents |
|---|---|---|---|---|---|---|
| 0 | 20 | 16 | 4 | 1.35 | n/a | n/a |
| 1 | 19 | 15 | 4 | 1.37 | n/a | n/a |
| 2 | 20 | 14 | 6 | 1.20 | n/a | n/a |

## 3. Reading the results

* **Against the baselines (chronological split, test 2024-2025, with temperature).** The fuzzy regressor scores RMSE 0.920
  mg/l, R2 0.67 (three seeds 0.922 +- 0.003), against 0.864 for the random forest and 0.881 for boosting, 1.016 for
  Ridge, 1.025 for a quadratic in temperature alone, 1.409 for the season-only mean, 1.581 for the point mean and
  1.626 for the global mean. It beats Ridge and the temperature-only curve clearly and loses to the two tree ensembles
  by 0.04-0.06 mg/l RMSE (4-6 %). The point mean is hardly better than the global mean (R2 0.04): knowing the point is
  almost worthless, the season and the temperature are what matter.
* **With and without temperature.** Temperature dominates (AT-021: Pearson2 0.59). Taking it out raises the fuzzy
  regressor's test RMSE from 0.920 to 1.240 mg/l (R2 0.67 to 0.41) and the random forest's from 0.864 to 1.289 (R2 0.71 to 0.36).
  Without temperature the other inputs (ammonia, orthophosphate, pH, hour, season) still explain more than the season
  alone: RMSE 1.240 against 1.409 and R2 0.41 against 0.23; that is the part of the story the nutrients can tell on
  this table. Without temperature the fuzzy regressor is the best estimator of the chronological arm (1.240 against 1.289
  for the forest and 1.290 for boosting, Ridge 1.343), a margin of 0.05 mg/l with one fit per baseline, no tuning and a seed sd of 0.015 for the
  fuzzy model: suggestive, not established. With temperature the nutrients add 0.1 mg/l of RMSE on top of the temperature curve (0.920 against
  1.025).
* **Spatial hold-out (points never seen).** Everything degrades and the order is the same: with temperature the fuzzy
  regressor scores 1.096 (seeds 1.122 +- 0.027) against 0.970 for the forest and 0.926 for boosting; Ridge and the
  temperature curve score 1.266; without temperature 1.426 (1.438 +- 0.011) against 1.356, 1.336 and 1.614 for Ridge.
  The gap to the tree ensembles is larger than chronologically (0.13-0.17 mg/l with temperature), so the
  rules generalise to new points worse than boosting does. The chronological test also contains 30 % of rows (990 of 3,264) from points
  without complete training rows (RMSE 1.063 against 0.851 for seen points with temperature, same pattern for all estimators).
  The two splits score different rows and are not strictly comparable.
* **Where it fails.** For the 97 test samples with DO below 8 mg/l (3 %) the RMSE of every estimator is 2.9-5.0 mg/l (the
  fuzzy regressor 2.87, the forest 2.96, boosting 2.98, the global mean 4.96): low oxygen, the case that would matter, is
  estimated as a much higher value. By season the fuzzy regressor is worst in spring and autumn (0.999) and best in winter (0.715).
* **Seeds and shapes.** Three seeds differ by 0.003 mg/l (chronological, with temperature) to 0.027 (spatial). The
  selection used one seed per shape; the best shape lies on the edge of the grid (40 rules) for the chronological arms, so a larger rule base might do slightly better. Not explored.

## 4. Readability of the rules

The additive TSK rules are **hard to read as rules**, which is the point of this section.

* The prediction is the firing-weighted mean of the consequents (`Σ f c / Σ f`). A consequent is therefore not "the DO of
  the samples this rule covers": the published seed has consequents from 1.2 to 18.6 mg/l (observed DO: 0.3 to 18.9, mean 11.3).
  Rules with **identical antecedents and compensating consequents** are normal: R01 and R06 both say "IF days_from_midwinter
  IS Verano", with 1.198 and 18.62 mg/l; together they act as one rule of about 9.9 mg/l (the mean of a duplicate
  group). R05, R21 and R26 ("water_temperature IS Low") say 17.91, 14 and 16.49. Of the 39 rules of the published seed 12
  repeat the antecedent set of an earlier rule (27 distinct antecedent sets); the other seeds have 9 and 11 duplicates.
  Without temperature the numbers are 40 rules, 32 distinct sets, 8 duplicates.
* Mean rule length is 1.36 antecedents: most rules have one or two conditions, so each can be read, but the model is the sum
  of 39 of them. The detection-limit terms are used (R10, R27, R31 "IF ... IS <=L", R28 and R30 combine ammonia `<=L`
  with temperature High or pH Medium): the terms do what they were built for, but the rules that carry the
  fit are the temperature and season ones.
* The rule sets of different seeds share 24-31 % of their antecedent sets (Jaccard), a little more than for the NYC and Madrid classifiers.
* **`unique_antecedents`** (one rule per antecedent set) is not an option of `BaseFuzzyRulesRegressor` in ex_fuzzy 3.3.1
  (checked in the source), so it was not used here; it is in the FX retrain and the served model uses it (top of this document). The Atlas contract keeps duplicates flagged (`duplicate_of`); a "canonical
  rule view" that averages a duplicate group would be a presentation of the same prediction, not a different model.

### All rules of the published seed (`water-do-chrono-temp-seed0`)

| rule | text | duplicate antecedents |
|---|---|---|
| R01 | IF days_from_midwinter IS Verano THEN dissolved_oxygen(t+0h) = 1.198 mg/l |  |
| R02 | IF local_hour IS Low THEN dissolved_oxygen(t+0h) = 5.465 mg/l |  |
| R03 | IF water_temperature IS High AND ph IS Low THEN dissolved_oxygen(t+0h) = 5.109 mg/l |  |
| R04 | IF orthophosphate_reactive IS Bajo>L THEN dissolved_oxygen(t+0h) = 8.31 mg/l |  |
| R05 | IF water_temperature IS Low THEN dissolved_oxygen(t+0h) = 17.91 mg/l |  |
| R06 | IF days_from_midwinter IS Verano THEN dissolved_oxygen(t+0h) = 18.62 mg/l  [same antecedents as R01] | yes |
| R07 | IF ph IS High THEN dissolved_oxygen(t+0h) = 14.89 mg/l |  |
| R08 | IF ammoniacal_nitrogen IS Medio>L AND water_temperature IS Low THEN dissolved_oxygen(t+0h) = 12.4 mg/l |  |
| R09 | IF ph IS Low THEN dissolved_oxygen(t+0h) = 5.109 mg/l |  |
| R10 | IF orthophosphate_reactive IS <=L THEN dissolved_oxygen(t+0h) = 8.488 mg/l |  |
| R11 | IF orthophosphate_reactive IS Bajo>L AND water_temperature IS Medium THEN dissolved_oxygen(t+0h) = 7.421 mg/l |  |
| R12 | IF orthophosphate_reactive IS Bajo>L THEN dissolved_oxygen(t+0h) = 13.47 mg/l  [same antecedents as R04] | yes |
| R13 | IF water_temperature IS Low AND days_from_midwinter IS Invierno THEN dissolved_oxygen(t+0h) = 10.09 mg/l |  |
| R14 | IF ammoniacal_nitrogen IS Bajo>L THEN dissolved_oxygen(t+0h) = 15.42 mg/l |  |
| R15 | IF ammoniacal_nitrogen IS Medio>L AND local_hour IS High THEN dissolved_oxygen(t+0h) = 14.36 mg/l |  |
| R16 | IF water_temperature IS Medium AND days_from_midwinter IS Invierno THEN dissolved_oxygen(t+0h) = 8.488 mg/l |  |
| R17 | IF water_temperature IS Medium THEN dissolved_oxygen(t+0h) = 9.732 mg/l |  |
| R18 | IF orthophosphate_reactive IS Alto>L THEN dissolved_oxygen(t+0h) = 9.91 mg/l |  |
| R19 | IF ammoniacal_nitrogen IS Medio>L AND local_hour IS Medium THEN dissolved_oxygen(t+0h) = 12.04 mg/l |  |
| R20 | IF ph IS High THEN dissolved_oxygen(t+0h) = 10.09 mg/l  [same antecedents as R07] | yes |
| R21 | IF water_temperature IS Low THEN dissolved_oxygen(t+0h) = 14 mg/l  [same antecedents as R05] | yes |
| R22 | IF orthophosphate_reactive IS Bajo>L THEN dissolved_oxygen(t+0h) = 18.09 mg/l  [same antecedents as R04] | yes |
| R23 | IF water_temperature IS High THEN dissolved_oxygen(t+0h) = 10.62 mg/l |  |
| R24 | IF orthophosphate_reactive IS Medio>L AND ph IS Low THEN dissolved_oxygen(t+0h) = 8.132 mg/l |  |
| R25 | IF ammoniacal_nitrogen IS Bajo>L THEN dissolved_oxygen(t+0h) = 10.44 mg/l  [same antecedents as R14] | yes |
| R26 | IF water_temperature IS Low THEN dissolved_oxygen(t+0h) = 16.49 mg/l  [same antecedents as R05] | yes |
| R27 | IF ammoniacal_nitrogen IS <=L THEN dissolved_oxygen(t+0h) = 16.67 mg/l |  |
| R28 | IF ammoniacal_nitrogen IS <=L AND water_temperature IS High THEN dissolved_oxygen(t+0h) = 10.44 mg/l |  |
| R29 | IF water_temperature IS Medium THEN dissolved_oxygen(t+0h) = 13.47 mg/l  [same antecedents as R17] | yes |
| R30 | IF ammoniacal_nitrogen IS <=L AND ph IS Medium THEN dissolved_oxygen(t+0h) = 9.021 mg/l |  |
| R31 | IF orthophosphate_reactive IS <=L THEN dissolved_oxygen(t+0h) = 17.2 mg/l  [same antecedents as R10] | yes |
| R32 | IF ammoniacal_nitrogen IS Alto>L AND ph IS Medium THEN dissolved_oxygen(t+0h) = 13.82 mg/l |  |
| R33 | IF water_temperature IS High AND local_hour IS Low THEN dissolved_oxygen(t+0h) = 5.109 mg/l |  |
| R34 | IF ph IS High THEN dissolved_oxygen(t+0h) = 8.31 mg/l  [same antecedents as R07] | yes |
| R35 | IF orthophosphate_reactive IS Bajo>L AND water_temperature IS High THEN dissolved_oxygen(t+0h) = 5.109 mg/l |  |
| R36 | IF days_from_midwinter IS Invierno AND local_hour IS Low THEN dissolved_oxygen(t+0h) = 18.44 mg/l |  |
| R37 | IF ph IS Medium THEN dissolved_oxygen(t+0h) = 8.132 mg/l |  |
| R38 | IF water_temperature IS High THEN dissolved_oxygen(t+0h) = 1.376 mg/l  [same antecedents as R23] | yes |
| R39 | IF local_hour IS Low THEN dissolved_oxygen(t+0h) = 14.71 mg/l  [same antecedents as R02] | yes |
## 5. Publication and horizon 0

* **Served since 2026-10-31: `exfuzzy-uk_water_do-fx-w-unique-seed0`** (same task, inputs, period, coverage and publish command, with
  `--run-dir artifacts/uk_water_do/fx-w-unique-seed0` and `--metadata configs/water/attribution.json`; `make publish-water-unique`).
  The description below is that of the earlier model `exfuzzy-uk_water_do-water-do-chrono-temp-seed0`, which is still on disk; the
  counts are the same (3,316 input rows, 195 points, 129,324 activation records: 39 rules in both).
* `model_id` **exfuzzy-uk_water_do-water-do-chrono-temp-seed0**, task `uk_water_do`, horizon 0 h, published period =
  the test period `[2024-01-01, 2026-01-01)`: 3,316 input rows, 195 points, 129,324 activation records. 52 rows have a missing input and are
  published with `prediction = null`, `missing_reason = missing_input`. The model without temperature is `water-do-chrono-notemp-seed0`
  (publish it with the same command and `--run-dir artifacts/uk_water_do/water-do-chrono-notemp-seed0`).
* `valid_at = issued_at` is handled end to end: the run manifest and the registry carry `horizon_hours = 0`
  (contract v0.3), the predictions file has `valid_at_utc == issued_at_utc` in every row, `/series` returns
  `horizon_hours = 0` and points with equal times, and the rule trace value equals `model.predict` (smoke test below).
* **Irregular sample times.** `publish` refused the table: `issued_at_utc` is the sampling instant (minute resolution), so the
  gcd of the gaps is 60 s and `coverage.step_hours` is not a whole number of hours. New option `--irregular-times`
  (`irregular_times=True`): `step_hours = 1` (the finest step the contract expresses) and a warning in the card. **The timeline
  of this task is not a grid.** `/rule-map` with `metric=firing_strength` needs an exact issue instant, and each sample has its own:
  at one instant 1 of 195 points has a value (194 `no_observation`). A map of this task has to use `mean_activation` or
  `activation_frequency` over a window: for the summer 2024 window (`[2024-06-01, 2024-09-01)`) 126 of 195 points have a value.
  The web timeline must not step through hours.

## 6. Limits

* Descriptive inference, not forecast, not an alert; sparse campaign sampling (median 23 samples per point; 30 % of the complete test rows are from points without training rows).
* One fit per shape for selection and one baseline fit each (seed of the forest and of boosting 0), no tuning of any model; the grid edge (40 rules) was the best for the chronological arms.
* The ammonia and orthophosphate columns are "≤ L" for 71 % and 39 % of the rows: the fuzzy model can say "not above the limit", nothing finer; the
  harmonisation also removes the difference between 0.002 and 0.03 mg/l ammonia (AT-021 section 3).
* Season terms are a convention (shoulder 15 days, not studied); `local_hour` is a sampling hour, clustered in working hours, and carries little.
* The low-DO tail is badly estimated by every model (section 3); a map of "low oxygen" would be wrong where it matters.
* Compute: 36 selection fits (about 15 min of one core in total, 6-56 s each), 4 `final` commands (112, 101, 51 and 44 s wall; peak RSS 0.35 GB).

## Reproduce

```bash
export ATLAS_DATA_DIR=/path/to/exfuzzy-atlas/data ATLAS_ARTIFACTS_DIR=/path/to/exfuzzy-atlas/artifacts
export PYTHONPATH=src:apps/api
PY=python
for A in chrono_temp chrono_notemp spatial_temp spatial_notemp; do
  $PY -m atlas.ml.experiment_water select --config configs/ml/water_do_${A}_experiment.json   # validation only
  $PY -m atlas.ml.experiment_water final  --config configs/ml/water_do_${A}_experiment.json   # seeds, baselines, test (once); run dirs for the chronological arms
done
$PY -m atlas.ml.report_water --artifacts-dir $ATLAS_ARTIFACTS_DIR
D=$ATLAS_DATA_DIR/processed/water
$PY -m atlas.services.publish --run-dir artifacts/uk_water_do/water-do-chrono-temp-seed0 \
  --features $D/features/uk_water_do --entities $D/entities.geojson --feature-spec configs/water/feature_spec.json \
  --from 2024-01-01T00:00:00Z --to 2026-01-01T00:00:00Z --task-id uk_water_do --title "River dissolved oxygen (UK)" --irregular-times
$PY -m pytest tests/ml/test_water_experiment.py tests/services -q
```

Seeds, splits and shapes are in `artifacts/uk_water_do/experiments/<arm>/{selection,summary}.json`.
