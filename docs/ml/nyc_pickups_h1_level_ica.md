# NYC yellow-taxi demand level at t+1 h (baja / normal / alta / muy alta): winning-rule classifier, justified terms and baselines (AT-041e)

First NYC model of Atlas. Same task as `nyc_pickups_h1_level.md` (AT-031b): the class of the next hour's pickups
**relative to the zone's own April-December 2024 norm for that hour of the week**. The classifier is the winning-rule
`FuzzyClassifier` of AT-041c/d, fitted on a class-tempered subsample, with linguistic terms that have a documented
rationale. Every number below is printed by `python -m atlas.ml.report_nyc` from the run artifacts (commands at the end).

**What this is not.** The class is not demand, risk or a probability, and the task is a replay of historic data (no live
feed, no real-time claim). "alta" in February-March 2025 mixes unusual demand with season (the reference holds no winter),
vendor-reporting changes and congestion pricing (from 2025-01-05); the three cannot be separated with one winter and **no
causal statement is made**. A rule's firing, weight and association degree are degrees of rule match, not probabilities,
contributions or risk. A term named "alta" says where a percentile input was cut, not that the rule explains anything.

## 0. Protocol and decision rules

History, for honesty. The rules in this section were fixed before the second feature-set arm was fitted and before any
test row was read; the six validation fits of the first arm (all 12 inputs) had been seen when the feature-set rule was
written down.

| Element | Decision |
|---|---|
| Task, table | `nyc_pickups_h1_level` (AT-031b), 110 zones x hourly issue times, `target_level` = class of the next hour's pickups in the zone x week-hour train reference (cuts 25/75/95). Published as task `nyc_pickups_h1`, horizon 1 h, `observed` = the pickup count, `observed_label` = `target_level` |
| Split (AT-031) | train `[2024-04-01T04Z, 2025-01-01T05Z)`, validation `[2025-01-08T05Z, 2025-02-01T05Z)`, test `[2025-02-08T05Z, 2025-04-01T04Z)`, embargo 168 h |
| Rows | **complete** = `target_level` not null and the 12 inputs finite: train 596,400, validation 53,575, test 116,380. Rows with `level_status = low_volume` (and `insufficient_samples`, `target_missing`) have no label: they are **not fitted, not scored and never counted as "normal"**; they are "sin referencia" (section 6) |
| Fitting rows | class-tempered subsample of the training period: 30,000 rows with class sizes proportional to `count ** 0.5` (`class_sample`, entity x month blocks inside each class), partitions from the whole training period. Justification: the natural training mix is 25/50/20/5 %, with the test period far from it (21 % "muy alta"); the square root keeps the order of the classes but lifts "muy alta" from 5 % to 11.5 % of the fitted rows, and 30,000 rows is the Madrid budget (a fit takes 0.5-3 minutes; the GA cost is linear in rows). The class mix is therefore a fitting device: dominance scores and rule weights reflect it, not the natural frequencies (stated in the run manifest) |
| Budget | 150 generations x population 60, dominance-score weighting, `n_linguistic_variables = 3` for the data-driven inputs; same as Madrid |
| Shape selection | 6 shapes (30 or 60 rules x 2, 3 or 4 antecedents), **one fit each with seed 0**, per feature set; criterion: highest validation macro-F1 (ties: fewer rules) |
| Feature set (written before the second arm) | arm `all12`: the 7 AT-031 inputs and the 5 relative ones; arm `rel7`: the 5 relative inputs plus `local_hour` and `local_dow` (no raw counts). **Rule: `rel7` if its best validation macro-F1 is within 0.02 of the best of `all12`; otherwise `all12`.** Readability is the reason for the order: relative inputs share one justified partition and carry no zone scale. Both arms score the same rows (complete on the 12 inputs) |
| Seeds, test | 3 seeds (0, 1, 2) of the chosen arm and shape, validation and test scored in the same command; test is read once. Published seed = highest validation macro-F1 |
| Baselines | level persistence (the class of `rel_lag1` through the 25/75/95 cuts; also of `rel_lag24` and `rel_lag168`), majority class of train, logistic regression, random forest, histogram gradient boosting (plain and class-balanced) on the whole training period and the three plain ones also on the 30,000-row subsample. Baselines get **all 12 inputs** in every case (the stronger comparison) |
| Reported | macro-F1, balanced accuracy, accuracy, MAE of the class index and per-class recall and precision, overall, **per `volume_group`** (a column to slice by, never an input) and **per local month**, with the predicted and observed class share per month |

## 1. The linguistic terms and their justification

`configs/ml/nyc_partitions.json` is the single source (`atlas.ml.partitions.load_partition_file` refuses written
parameters that the cores and shoulders do not give). A term is a trapezoid whose core (membership 1) is the band, with a
linear shoulder at each boundary.

| input | terms (core) | shoulders | rationale |
|---|---|---|---|
| `rel_lag1`, `rel_lag2`, `rel_lag24`, `rel_lag168` (percentile of the lagged count in the zone x week-hour reference of its own hour) | baja 0-24.9, normal 25-74.9, alta 75-94.9, muy alta 95-100 | 7, 7 and 3.5 percentile points | cores are the classes of the target, so a rule reads in the language of the target ("IF rel_lag1 IS alta ... THEN nivel = muy alta"). The scheme is lower-inclusive over a continuous percentile, so each core ends 0.1 points below the next cut; the percentile of a cell with 30-40 reference values moves in steps of at least 1.25 points, so no value lies in the gap. **Shoulder = the binomial standard error of an empirical percentile estimated from n = 39 reference values** (the median cell size): sqrt(p(1-p)/n) = 6.9 points at p = 0.25 and 0.75 (written 7) and 3.5 at p = 0.95. A lagged value within a standard error of a cut is as likely to belong to either class given the noise of its own cell. It is a statistical rationale, not a physical one; the cuts 25/75/95 are the AT-031b decision |
| `local_hour` (hour of the target hour, America/New_York) | Madrugada 0-6, Mañana 7-10, Mediodía 11-14, Tarde-noche 15-23 | 1 h (crisp on whole hours) | day periods read from the **citywide pickup profile of the training period** (table below): night = workday level under 0.5 of the daily mean (hours 0-6: 0.47 ... 0.38); morning ramp 7-10 (0.78 to 1.09); plateau 11-14 (1.16 to 1.42, below the p75 of the 24 workday values, 1.45); evening 15-23: hours 15-19 and 21 are at or above p75 (hour 20 is 1.437, merged to keep one period), then the decline (1.37 at 22, 1.01 at 23). The cut between Mañana and Mediodía (10/11) is where the profile crosses about 1.1; it has no sharper break. Four terms because ex_fuzzy 3.3.1 bounds the term index of the k-th antecedent slot by the number of terms of the k-th feature (the four `rel_lag` inputs come first with four terms each). Midnight wrap: a trapezoid cannot wrap, so Tarde-noche ends at 23 and Madrugada starts at 0 (a crisp flip; Friday and Saturday 23 h and 0 h behave alike) |
| `local_dow` | Laborable 0-4, Sábado 5, Domingo 6 | 1 day (crisp) | calendar day types (0 = Monday); holidays are not encoded (they sit inside the reference cells) |
| `rel_mean24h` (ratio, 1 = the last 24 h were as busy as normal) | Low / Medium / High, **data-driven** | n/a | no defensible categorical scheme for the ratio; ex_fuzzy trapezoids anchored at the 20/40/60/80 % quantiles of the training rows. Labelled as such, no authority |
| raw counts `pickups_lag1/2/24/168`, `pickups_mean24h` (arm `all12` only) | Low / Medium / High, **data-driven** | n/a | same, pooled over zones whose scale differs by two orders of magnitude; hence the arm without them |

Citywide pickups per local hour of the target hour, training period, divided by the mean of the 24 hours (printed by
`python -m atlas.ml.experiment_nyc profile`; 725,890 rows with a known target; p25/p50/p75 of the 24 workday values
0.447 / 1.124 / 1.449):

| hour | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| workday | 0.469 | 0.223 | 0.119 | 0.077 | 0.084 | 0.155 | 0.382 | 0.779 | 1.058 | 1.080 | 1.092 | 1.157 |
| Saturday | 1.180 | 0.918 | 0.665 | 0.418 | 0.227 | 0.107 | 0.190 | 0.288 | 0.464 | 0.710 | 0.932 | 1.098 |
| Sunday | 1.448 | 1.132 | 0.833 | 0.544 | 0.328 | 0.153 | 0.226 | 0.326 | 0.484 | 0.770 | 1.051 | 1.243 |

| hour | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| workday | 1.246 | 1.298 | 1.424 | 1.485 | 1.503 | 1.691 | 1.803 | 1.551 | 1.437 | 1.502 | 1.373 | 1.010 |
| Saturday | 1.233 | 1.301 | 1.304 | 1.389 | 1.473 | 1.547 | 1.601 | 1.543 | 1.293 | 1.278 | 1.420 | 1.423 |
| Sunday | 1.425 | 1.489 | 1.541 | 1.478 | 1.518 | 1.519 | 1.466 | 1.284 | 1.153 | 1.084 | 0.877 | 0.630 |

The weekend profiles differ (the night is the busiest part of Saturday and Sunday); the weekday term only separates
Mon-Fri / Sat / Sun, so a rule can combine "Madrugada" with "Sábado". The profile describes the training period; it is
not a validated driver of demand.

## 2. Class distribution of the rows used

**Complete rows (label and the 12 inputs) and rows without a reference level**

| period | n complete | target known, no label | baja | normal | alta | muy alta |
|---|---|---|---|---|---|---|
| train | 596400 | 111293 | 25.5 % | 49.7 % | 20.2 % | 4.6 % |
| validation | 53575 | 9785 | 26.2 % | 46.4 % | 19.4 % | 8.0 % |
| test | 116380 | 20790 | 12.5 % | 38.3 % | 28.3 % | 20.9 % |

**Class shares (%) by volume group**

| period | volume group | n | baja | normal | alta | muy alta |
|---|---|---|---|---|---|---|
| train | 10_50 | 98138 | 25.1 | 50.1 | 20.1 | 4.7 |
| train | 3_10 | 90102 | 25.1 | 50.2 | 20.2 | 4.5 |
| train | ge_50 | 236559 | 25.2 | 49.8 | 20.1 | 4.8 |
| train | lt_3 | 171601 | 26.3 | 48.9 | 20.3 | 4.4 |
| validation | 10_50 | 8829 | 33.6 | 46.6 | 14.9 | 4.9 |
| validation | 3_10 | 8090 | 20.9 | 46.1 | 23.5 | 9.5 |
| validation | ge_50 | 21276 | 29.4 | 48.9 | 16.0 | 5.8 |
| validation | lt_3 | 15380 | 20.4 | 43.0 | 24.4 | 12.1 |
| test | 10_50 | 19129 | 16.7 | 42.2 | 27.1 | 14.0 |
| test | 3_10 | 17600 | 5.5 | 27.8 | 34.7 | 32.0 |
| test | ge_50 | 46059 | 17.3 | 48.8 | 23.9 | 10.0 |
| test | lt_3 | 33592 | 7.3 | 27.1 | 31.8 | 33.8 |

**Class shares (%) by local month**

| period | local month | n | baja | normal | alta | muy alta |
|---|---|---|---|---|---|---|
| train | 2024-04 | 51252 | 25.8 | 54.4 | 16.6 | 3.2 |
| train | 2024-05 | 69226 | 20.9 | 52.7 | 22.0 | 4.3 |
| train | 2024-06 | 67334 | 19.8 | 54.3 | 21.6 | 4.3 |
| train | 2024-07 | 69054 | 37.4 | 48.4 | 11.9 | 2.3 |
| train | 2024-08 | 69415 | 42.9 | 44.3 | 10.8 | 1.9 |
| train | 2024-09 | 67171 | 17.8 | 50.8 | 25.4 | 6.0 |
| train | 2024-10 | 69076 | 17.5 | 53.7 | 24.2 | 4.7 |
| train | 2024-11 | 64579 | 20.8 | 47.6 | 24.7 | 6.8 |
| train | 2024-12 | 69293 | 26.0 | 41.9 | 24.1 | 8.0 |
| validation | 2025-01 | 53575 | 26.2 | 46.4 | 19.4 | 8.0 |
| test | 2025-02 | 46953 | 15.4 | 38.7 | 27.7 | 18.2 |
| test | 2025-03 | 69427 | 10.6 | 38.0 | 28.7 | 22.7 |

The base rate moves: from 25/50/20/5 % in training to 26/46/19/8 % in January and 12.5/38/28/21 % in February-March.
In the small zones (`lt_3`, `3_10`) two thirds of the test rows are "alta" or "muy alta" (AT-031b section 3). A model that
learns "normal is the most likely class" is penalised on test for reasons that are not the model's.

## 3. Feature-set and shape selection (validation 2025-01 only, one fit per shape, seed 0)

**Arm `all12`** (the 5 relative inputs, `local_hour`, `local_dow` and the 5 raw counts)

| nRules | nAnts | rules kept | val macro-F1 | val bal-acc | val acc | val MAE idx | unknown | fit s |
|---|---|---|---|---|---|---|---|---|
| 30 | 2 | 8 | 0.399 | 0.388 | 0.463 | 0.643 | 0.000 | 49 |
| 30 | 4 | 8 | 0.390 | 0.394 | 0.459 | 0.663 | 0.004 | 46 |
| 60 | 4 | 19 | 0.384 | 0.386 | 0.414 | 0.733 | 0.015 | 180 |
| 60 | 3 | 18 | 0.382 | 0.386 | 0.426 | 0.712 | 0.007 | 108 |
| 60 | 2 | 13 | 0.341 | 0.342 | 0.405 | 0.720 | 0.001 | 110 |
| 30 | 3 | 10 | 0.323 | 0.327 | 0.393 | 0.759 | 0.015 | 41 |

**Arm `rel7`** (relative inputs, `local_hour`, `local_dow`)

| nRules | nAnts | rules kept | val macro-F1 | val bal-acc | val acc | val MAE idx | unknown | fit s |
|---|---|---|---|---|---|---|---|---|
| 30 | 2 | 10 | 0.398 | 0.406 | 0.443 | 0.693 | 0.004 | 33 |
| 60 | 4 | 13 | 0.380 | 0.394 | 0.401 | 0.766 | 0.003 | 170 |
| 30 | 3 | 10 | 0.372 | 0.375 | 0.419 | 0.732 | 0.002 | 51 |
| 60 | 3 | 15 | 0.372 | 0.398 | 0.396 | 0.778 | 0.001 | 125 |
| 30 | 4 | 11 | 0.335 | 0.345 | 0.398 | 0.767 | 0.012 | 51 |
| 60 | 2 | 8 | 0.319 | 0.332 | 0.419 | 0.703 | 0.000 | 84 |

Rule of section 0: best `all12` 0.399 (30 x 2), best `rel7` 0.398 (30 x 2), a difference of 0.001, inside the 0.02
tolerance, so **`rel7` is the final feature set** and 30 rules x 2 antecedents the shape. Reading, without
over-reading: one fit per shape is one GA seed; the three seeds of the final shape (section 4) have a validation
macro-F1 standard deviation of 0.019, so differences between shapes of 0.02-0.05 are within seed noise and the
shape ranking is not established. The raw counts bring nothing measurable on validation to the fuzzy model.

## 4. Results

The test period (2025-02-08 to 2025-03-31) was read once, in the `final` command, for the three seeds and all baselines.
The published seed is seed 0 (highest validation macro-F1). Rows: train 596,400, fitting
subsample 30,000, validation 53,575, test 116,380.

**Three seeds of the final shape (mean +- sd with n-1; published seed = the best validation macro-F1)**

| period | macro_f1 | balanced_accuracy | accuracy | macro_f1 by seed |
|---|---|---|---|---|
| validation | 0.382 +- 0.019 | 0.393 +- 0.026 | 0.426 +- 0.015 | 0.398, 0.387, 0.361 |
| test | 0.397 +- 0.013 | 0.418 +- 0.013 | 0.405 +- 0.017 | 0.412, 0.392, 0.387 |

**Validation overall (2025-01-08 to 2025-01-31)**

| estimator | macro_f1 | balanced_accuracy | accuracy | mae_class_index | off_by_2plus | unknown |
|---|---|---|---|---|---|---|
| persistence | 0.401 | 0.401 | 0.447 | 0.677 | 0.112 | 0.000 |
| persistence_rel_lag24 | 0.351 | 0.350 | 0.415 | 0.746 | 0.140 | 0.000 |
| persistence_rel_lag168 | 0.340 | 0.343 | 0.405 | 0.786 | 0.161 | 0.000 |
| majority_class | 0.158 | 0.250 | 0.464 | 0.617 | 0.080 | 0.000 |
| logistic_regression | 0.297 | 0.314 | 0.495 | 0.572 | 0.066 | 0.000 |
| logistic_regression_balanced | 0.339 | 0.429 | 0.362 | 0.899 | 0.223 | 0.000 |
| random_forest | 0.314 | 0.325 | 0.506 | 0.556 | 0.061 | 0.000 |
| random_forest_balanced | 0.409 | 0.433 | 0.428 | 0.715 | 0.130 | 0.000 |
| hist_gradient_boosting | 0.345 | 0.344 | 0.511 | 0.556 | 0.065 | 0.000 |
| hist_gradient_boosting_balanced | 0.381 | 0.431 | 0.407 | 0.802 | 0.178 | 0.000 |
| logistic_regression_subsample | 0.399 | 0.384 | 0.481 | 0.602 | 0.078 | 0.000 |
| random_forest_subsample | 0.401 | 0.384 | 0.496 | 0.580 | 0.073 | 0.000 |
| hist_gradient_boosting_subsample | 0.395 | 0.386 | 0.469 | 0.641 | 0.102 | 0.000 |
| exfuzzy_classifier | 0.398 | 0.406 | 0.443 | 0.693 | 0.123 | 0.004 |

**Test overall**

| estimator | macro_f1 | balanced_accuracy | accuracy | mae_class_index | off_by_2plus | unknown |
|---|---|---|---|---|---|---|
| persistence | 0.425 | 0.424 | 0.439 | 0.695 | 0.123 | 0.000 |
| persistence_rel_lag24 | 0.379 | 0.379 | 0.398 | 0.777 | 0.158 | 0.000 |
| persistence_rel_lag168 | 0.394 | 0.395 | 0.412 | 0.767 | 0.159 | 0.000 |
| majority_class | 0.138 | 0.250 | 0.383 | 0.826 | 0.209 | 0.000 |
| logistic_regression | 0.328 | 0.350 | 0.446 | 0.626 | 0.072 | 0.000 |
| logistic_regression_balanced | 0.336 | 0.416 | 0.355 | 0.921 | 0.243 | 0.000 |
| random_forest | 0.365 | 0.368 | 0.463 | 0.624 | 0.086 | 0.000 |
| random_forest_balanced | 0.420 | 0.441 | 0.424 | 0.727 | 0.137 | 0.000 |
| hist_gradient_boosting | 0.372 | 0.371 | 0.459 | 0.633 | 0.091 | 0.000 |
| hist_gradient_boosting_balanced | 0.386 | 0.419 | 0.389 | 0.825 | 0.189 | 0.000 |
| logistic_regression_subsample | 0.447 | 0.444 | 0.473 | 0.632 | 0.097 | 0.000 |
| random_forest_subsample | 0.434 | 0.422 | 0.469 | 0.629 | 0.094 | 0.000 |
| hist_gradient_boosting_subsample | 0.409 | 0.404 | 0.435 | 0.706 | 0.130 | 0.000 |
| exfuzzy_classifier | 0.412 | 0.430 | 0.424 | 0.736 | 0.144 | 0.002 |

**Test recall per class**

| estimator | baja | normal | alta | muy alta |
|---|---|---|---|---|
| persistence | 0.351 | 0.502 | 0.362 | 0.483 |
| persistence_rel_lag24 | 0.304 | 0.475 | 0.334 | 0.402 |
| persistence_rel_lag168 | 0.339 | 0.480 | 0.358 | 0.401 |
| majority_class | 0.000 | 1.000 | 0.000 | 0.000 |
| logistic_regression | 0.147 | 0.776 | 0.423 | 0.053 |
| logistic_regression_balanced | 0.422 | 0.195 | 0.127 | 0.917 |
| random_forest | 0.148 | 0.824 | 0.333 | 0.167 |
| random_forest_balanced | 0.338 | 0.309 | 0.400 | 0.718 |
| hist_gradient_boosting | 0.168 | 0.800 | 0.326 | 0.190 |
| hist_gradient_boosting_balanced | 0.375 | 0.277 | 0.288 | 0.737 |
| logistic_regression_subsample | 0.269 | 0.547 | 0.393 | 0.566 |
| random_forest_subsample | 0.230 | 0.622 | 0.372 | 0.463 |
| hist_gradient_boosting_subsample | 0.276 | 0.546 | 0.341 | 0.454 |
| exfuzzy_classifier | 0.370 | 0.429 | 0.284 | 0.637 |

**Test precision per class**

| estimator | baja | normal | alta | muy alta |
|---|---|---|---|---|
| persistence | 0.355 | 0.497 | 0.364 | 0.484 |
| persistence_rel_lag24 | 0.303 | 0.470 | 0.334 | 0.409 |
| persistence_rel_lag168 | 0.308 | 0.472 | 0.362 | 0.437 |
| majority_class | 0.000 | 0.383 | 0.000 | 0.000 |
| logistic_regression | 0.548 | 0.489 | 0.350 | 0.684 |
| logistic_regression_balanced | 0.394 | 0.581 | 0.283 | 0.314 |
| random_forest | 0.602 | 0.471 | 0.374 | 0.717 |
| random_forest_balanced | 0.452 | 0.586 | 0.334 | 0.411 |
| hist_gradient_boosting | 0.574 | 0.477 | 0.368 | 0.568 |
| hist_gradient_boosting_balanced | 0.434 | 0.596 | 0.323 | 0.334 |
| logistic_regression_subsample | 0.468 | 0.539 | 0.382 | 0.477 |
| random_forest_subsample | 0.518 | 0.499 | 0.374 | 0.520 |
| hist_gradient_boosting_subsample | 0.395 | 0.493 | 0.355 | 0.440 |
| exfuzzy_classifier | 0.349 | 0.518 | 0.342 | 0.426 |

### Per volume group (zone grouped by its mean pickups per hour in training: `lt_3`, `3_10`, `10_50`, `ge_50`)

**Test macro-F1**

| estimator | 10_50 (n=19129) | 3_10 (n=17600) | ge_50 (n=46059) | lt_3 (n=33592) |
|---|---|---|---|---|
| persistence | 0.409 | 0.361 | 0.443 | 0.355 |
| persistence_rel_lag24 | 0.358 | 0.328 | 0.365 | 0.334 |
| persistence_rel_lag168 | 0.368 | 0.339 | 0.380 | 0.361 |
| majority_class | 0.148 | 0.109 | 0.164 | 0.106 |
| logistic_regression | 0.288 | 0.244 | 0.283 | 0.308 |
| logistic_regression_balanced | 0.319 | 0.198 | 0.354 | 0.247 |
| random_forest | 0.343 | 0.318 | 0.375 | 0.292 |
| random_forest_balanced | 0.395 | 0.265 | 0.447 | 0.319 |
| hist_gradient_boosting | 0.357 | 0.309 | 0.392 | 0.311 |
| hist_gradient_boosting_balanced | 0.358 | 0.238 | 0.414 | 0.295 |
| logistic_regression_subsample | 0.412 | 0.338 | 0.423 | 0.359 |
| random_forest_subsample | 0.417 | 0.342 | 0.448 | 0.372 |
| hist_gradient_boosting_subsample | 0.395 | 0.332 | 0.433 | 0.337 |
| exfuzzy_classifier | 0.395 | 0.339 | 0.425 | 0.344 |

**Test balanced accuracy**

| estimator | 10_50 (n=19129) | 3_10 (n=17600) | ge_50 (n=46059) | lt_3 (n=33592) |
|---|---|---|---|---|
| persistence | 0.408 | 0.361 | 0.443 | 0.355 |
| persistence_rel_lag24 | 0.357 | 0.328 | 0.365 | 0.333 |
| persistence_rel_lag168 | 0.368 | 0.340 | 0.382 | 0.363 |
| majority_class | 0.250 | 0.250 | 0.250 | 0.250 |
| logistic_regression | 0.318 | 0.303 | 0.309 | 0.333 |
| logistic_regression_balanced | 0.417 | 0.281 | 0.445 | 0.324 |
| random_forest | 0.347 | 0.343 | 0.365 | 0.327 |
| random_forest_balanced | 0.422 | 0.312 | 0.468 | 0.353 |
| hist_gradient_boosting | 0.356 | 0.332 | 0.377 | 0.332 |
| hist_gradient_boosting_balanced | 0.410 | 0.286 | 0.457 | 0.328 |
| logistic_regression_subsample | 0.399 | 0.350 | 0.404 | 0.365 |
| random_forest_subsample | 0.407 | 0.352 | 0.433 | 0.365 |
| hist_gradient_boosting_subsample | 0.389 | 0.335 | 0.426 | 0.339 |
| exfuzzy_classifier | 0.414 | 0.354 | 0.447 | 0.356 |

**Test accuracy**

| estimator | 10_50 (n=19129) | 3_10 (n=17600) | ge_50 (n=46059) | lt_3 (n=33592) |
|---|---|---|---|---|
| persistence | 0.427 | 0.418 | 0.484 | 0.397 |
| persistence_rel_lag24 | 0.385 | 0.382 | 0.428 | 0.374 |
| persistence_rel_lag168 | 0.396 | 0.391 | 0.437 | 0.396 |
| majority_class | 0.422 | 0.278 | 0.488 | 0.271 |
| logistic_regression | 0.459 | 0.380 | 0.518 | 0.376 |
| logistic_regression_balanced | 0.316 | 0.350 | 0.360 | 0.373 |
| random_forest | 0.476 | 0.420 | 0.539 | 0.373 |
| random_forest_balanced | 0.389 | 0.397 | 0.464 | 0.403 |
| hist_gradient_boosting | 0.474 | 0.404 | 0.540 | 0.369 |
| hist_gradient_boosting_balanced | 0.351 | 0.357 | 0.430 | 0.371 |
| logistic_regression_subsample | 0.461 | 0.446 | 0.521 | 0.427 |
| random_forest_subsample | 0.460 | 0.442 | 0.520 | 0.417 |
| hist_gradient_boosting_subsample | 0.430 | 0.406 | 0.493 | 0.373 |
| exfuzzy_classifier | 0.402 | 0.408 | 0.456 | 0.401 |

**Validation macro-F1**

| estimator | 10_50 (n=8829) | 3_10 (n=8090) | ge_50 (n=21276) | lt_3 (n=15380) |
|---|---|---|---|---|
| persistence | 0.396 | 0.358 | 0.460 | 0.333 |
| persistence_rel_lag24 | 0.324 | 0.317 | 0.385 | 0.310 |
| persistence_rel_lag168 | 0.321 | 0.313 | 0.354 | 0.321 |
| majority_class | 0.159 | 0.158 | 0.164 | 0.150 |
| logistic_regression | 0.283 | 0.244 | 0.308 | 0.263 |
| logistic_regression_balanced | 0.327 | 0.299 | 0.378 | 0.274 |
| random_forest | 0.298 | 0.247 | 0.372 | 0.226 |
| random_forest_balanced | 0.401 | 0.352 | 0.470 | 0.324 |
| hist_gradient_boosting | 0.345 | 0.279 | 0.406 | 0.270 |
| hist_gradient_boosting_balanced | 0.374 | 0.318 | 0.443 | 0.303 |
| logistic_regression_subsample | 0.357 | 0.355 | 0.430 | 0.348 |
| random_forest_subsample | 0.396 | 0.330 | 0.460 | 0.326 |
| hist_gradient_boosting_subsample | 0.391 | 0.348 | 0.451 | 0.326 |
| exfuzzy_classifier | 0.389 | 0.358 | 0.454 | 0.329 |

### Per month

**Test macro-F1**

| estimator | 2025-02 (n=46953) | 2025-03 (n=69427) |
|---|---|---|
| persistence | 0.427 | 0.417 |
| persistence_rel_lag24 | 0.369 | 0.380 |
| persistence_rel_lag168 | 0.381 | 0.399 |
| majority_class | 0.140 | 0.138 |
| logistic_regression | 0.328 | 0.319 |
| logistic_regression_balanced | 0.343 | 0.325 |
| random_forest | 0.365 | 0.354 |
| random_forest_balanced | 0.425 | 0.407 |
| hist_gradient_boosting | 0.383 | 0.355 |
| hist_gradient_boosting_balanced | 0.394 | 0.374 |
| logistic_regression_subsample | 0.448 | 0.437 |
| random_forest_subsample | 0.439 | 0.420 |
| hist_gradient_boosting_subsample | 0.417 | 0.396 |
| exfuzzy_classifier | 0.416 | 0.404 |

**Test balanced accuracy**

| estimator | 2025-02 (n=46953) | 2025-03 (n=69427) |
|---|---|---|
| persistence | 0.426 | 0.417 |
| persistence_rel_lag24 | 0.369 | 0.380 |
| persistence_rel_lag168 | 0.381 | 0.400 |
| majority_class | 0.250 | 0.250 |
| logistic_regression | 0.349 | 0.345 |
| logistic_regression_balanced | 0.429 | 0.400 |
| random_forest | 0.368 | 0.362 |
| random_forest_balanced | 0.452 | 0.426 |
| hist_gradient_boosting | 0.378 | 0.361 |
| hist_gradient_boosting_balanced | 0.434 | 0.403 |
| logistic_regression_subsample | 0.441 | 0.437 |
| random_forest_subsample | 0.425 | 0.412 |
| hist_gradient_boosting_subsample | 0.411 | 0.393 |
| exfuzzy_classifier | 0.433 | 0.421 |

**Test accuracy**

| estimator | 2025-02 (n=46953) | 2025-03 (n=69427) |
|---|---|---|
| persistence | 0.435 | 0.443 |
| persistence_rel_lag24 | 0.385 | 0.407 |
| persistence_rel_lag168 | 0.397 | 0.422 |
| majority_class | 0.387 | 0.380 |
| logistic_regression | 0.446 | 0.446 |
| logistic_regression_balanced | 0.350 | 0.359 |
| random_forest | 0.461 | 0.464 |
| random_forest_balanced | 0.417 | 0.429 |
| hist_gradient_boosting | 0.463 | 0.457 |
| hist_gradient_boosting_balanced | 0.386 | 0.391 |
| logistic_regression_subsample | 0.463 | 0.479 |
| random_forest_subsample | 0.464 | 0.472 |
| hist_gradient_boosting_subsample | 0.434 | 0.435 |
| exfuzzy_classifier | 0.418 | 0.428 |

### Predicted against observed class share

**test 2025-02: share of rows (%) by class, observed and predicted**

|  | baja | normal | alta | muy alta | no_prediction |
|---|---|---|---|---|---|
| observed | 15.4 | 38.7 | 27.7 | 18.2 |  |
| exfuzzy_classifier | 16.3 | 33.1 | 22.9 | 27.5 | 0.3 |
| persistence | 15.2 | 39.2 | 27.5 | 18.1 | 0.0 |
| hist_gradient_boosting | 5.8 | 66.4 | 22.1 | 5.8 | 0.0 |
| random_forest | 5.0 | 69.2 | 22.6 | 3.2 | 0.0 |

**test 2025-03: share of rows (%) by class, observed and predicted**

|  | baja | normal | alta | muy alta | no_prediction |
|---|---|---|---|---|---|
| observed | 10.6 | 38.0 | 28.7 | 22.7 |  |
| exfuzzy_classifier | 11.3 | 30.7 | 24.0 | 33.8 | 0.2 |
| persistence | 10.5 | 38.2 | 28.6 | 22.7 | 0.0 |
| hist_gradient_boosting | 2.3 | 62.7 | 27.2 | 7.8 | 0.0 |
| random_forest | 1.8 | 65.3 | 26.9 | 6.0 | 0.0 |

**validation 2025-01: share of rows (%) by class, observed and predicted**

|  | baja | normal | alta | muy alta | no_prediction |
|---|---|---|---|---|---|
| observed | 26.2 | 46.4 | 19.4 | 8.0 |  |
| exfuzzy_classifier | 27.1 | 45.1 | 17.0 | 10.5 | 0.4 |
| persistence | 25.8 | 47.0 | 19.2 | 8.0 | 0.0 |
| hist_gradient_boosting | 11.0 | 81.4 | 6.0 | 1.6 | 0.0 |
| random_forest | 9.3 | 84.4 | 5.7 | 0.6 | 0.0 |

## 5. Reading the results

* **Against the baselines.** On test the published seed scores macro-F1 0.412 (balanced accuracy 0.430, accuracy 0.424);
  the three seeds give 0.397 +- 0.013. Level persistence (the class of `rel_lag1`) scores 0.425 / 0.424 / 0.439. So the
  fuzzy classifier **does not beat persistence**: it matches it in balanced accuracy (0.430 against 0.424), is lower in
  accuracy and macro-F1, and the seed mean is about 0.03 macro-F1 under it. Logistic regression and random forest fitted
  on the same 30,000-row subsample reach 0.447 and 0.434; the same models fitted on the whole training period reach only
  0.328 and 0.365 because they learn the training base rate (see the shares). The class-balanced random forest on the
  whole period (0.420) is the best baseline that does not use the subsample trick. In validation the gap is the same
  size (0.398 for the published seed against 0.401 for persistence). The task is hard on purpose (AT-031b: "la tarea
  relativa es más difícil que la de regresión"): the persistence of the last hour's level is already most of what the
  inputs say.
* **Per volume group.** Persistence, the subsample models and the fuzzy classifier do best on `ge_50` and `10_50` and worst on `3_10`
  and `lt_3` (Poisson noise on counts of 1-10 per hour); plain logistic regression is the exception. The fuzzy classifier is within 0.01-0.02 macro-F1 of persistence in
  all four groups (0.395 / 0.339 / 0.425 / 0.344 against 0.409 / 0.361 / 0.443 / 0.355) and equal to it in balanced
  accuracy. Nothing here says the model is better in the small zones, where the test shift is largest.
* **Per month.** February (0.416) and March (0.404) are close: the fuzzy classifier degrades by 0.012 from February to
  March, persistence by 0.010. Neither collapses.
* **Class shares.** This is where the estimators differ. In February-March the observed share of "muy alta" is 18 % and
  23 % (5 % in training). The models fitted on the natural training mix predict it for 3-8 % of the rows (random forest
  3.2 % and 6.0 %, boosting 5.8 % and 7.8 %) and "normal" for 63-69 %: good accuracy on the old base rate, blind to the
  shift. The fuzzy classifier, fitted on a subsample with 11.5 % "muy alta", predicts it for 27.5 % and 33.8 % of the
  rows: it follows the direction of the shift but overshoots it (observed 18 % and 23 %), and its "muy alta" precision is 0.43
  against a recall of 0.64. Persistence reproduces the observed shares by construction (it copies the last hour's level).
  The overshoot is mostly one rule, R10 "IF rel_mean24h IS High THEN nivel = muy alta", which decides 29 % of the test
  rows. No claim is made about why the demand level rose in February-March.
* **Seeds and shapes.** One GA seed moves the validation macro-F1 by 0.019 (sd), as much as most differences between
  shapes; `rel7` against `all12` (0.398 against 0.399) is not a measured difference.

### Readable rules of the published seed (`level-rel7-seed0`, 10 rules)

| rule | text | share of test rows it decides |
|---|---|---|
| R10 | IF rel_mean24h IS High THEN nivel = muy alta (peso 0.013) | 0.293 |
| R02 | IF rel_lag1 IS normal AND rel_lag24 IS normal THEN nivel = normal (peso 0.068) | 0.229 |
| R08 | IF rel_lag1 IS normal THEN nivel = alta (peso 0.031) | 0.148 |
| R01 | IF rel_lag1 IS baja THEN nivel = baja (peso 0.062) | 0.133 |
| R04 | IF rel_lag24 IS baja THEN nivel = normal (peso 0.036) | 0.086 |
| R07 | IF rel_lag1 IS alta AND rel_lag168 IS normal THEN nivel = alta (peso 0.018) | 0.085 |
| R09 | IF rel_lag1 IS muy alta THEN nivel = muy alta (peso 0.012) | 0.020 |
| R06 | IF rel_lag2 IS baja THEN nivel = alta (peso 0.0065) | 0.002 |
| R03 | IF rel_lag24 IS muy alta THEN nivel = normal (peso 0.0059) | 0.001 |
| R05 | IF rel_mean24h IS Low THEN nivel = alta (peso 0.0055) | 0.001 |

* 10 rules of mean length 1.2 antecedents, no duplicate antecedent sets, no conflicting ones, 7 rules decide at least 1 %
  of the test rows; 0.2 % of the rows fire no rule (they are published without a label). Seeds 1 and 2 have 12 and 7 rules
  (mean length 1.58 and 1.29; 10 and 6 rules decide at least 1 % of the test rows).
* **Neither `local_hour` nor `local_dow` is used by any rule of any seed**: the GA found the relative lags (above all
  `rel_lag1`) and `rel_mean24h` enough. So rules like "IF rel_lag1 IS alta AND local_hour IS Tarde-noche THEN muy alta"
  do not exist in this model; the justified time terms are available but unused.
* The rules are readable one at a time ("IF rel_lag1 IS baja THEN nivel = baja" is persistence), but the rule set has odd
  members that the GA kept for coverage: R08 "IF rel_lag1 IS normal THEN nivel = alta" and R03 "IF rel_lag24 IS muy alta
  THEN nivel = normal" have nothing to do with a causal story and decide few rows (R03: 0.1 %). Weights are dominance
  scores computed on the class-tempered subsample, so they are not comparable with natural frequencies.
* **Stability**: the pairwise Jaccard index of the rule sets across seeds is 0.06-0.13 (mean 0.096) and of the antecedent
  sets 0.06-0.21 (mean 0.143): different seeds give different rule sets with the same flavour (persistence-like rules on
  `rel_lag1`). Do not read a single rule as a finding.

## 6. Publication and the rows without a reference level

* `model_id` **exfuzzy-nyc_pickups_h1-level-rel7-seed0**, task `nyc_pickups_h1`, horizon 1 h, published period = the test
  period `[2025-02-08T05:00Z, 2025-04-01T04:00Z)`: 137,170 input rows, 110 zones, 1,371,700 activation records (10 rules
  x rows). The period is out of sample for the fit, but the validation month (January) is not in it.
* `--observed-label-column target_level` (new in `atlas.services.publish`): `observed` is the pickup count, `observed_label`
  is the precomputed class. The previous behaviour (scheme bounds applied to `observed`) would label a count of 3 as
  "baja" because 3 < 25; see `docs/api.md` section 4.
* **No reference level.** The 20,790 test rows (15.2 % of the published period) with an observed count but no label
  (`level_status = low_volume`) are published with `observed_label = null`, `prediction_label = null` and
  `missing_reason = prediction_unavailable`: *the model could compute a class from its inputs, but the target is a
  percentile of a zone x hour reference that does not exist for that cell, so a class would claim a reference that is not
  there*. The reason is `prediction_unavailable` (not `missing_input`, nothing is missing from the inputs; not
  `no_observation`, the count is there) and it is shared with the 286 rows where no rule fires (0.2 %); the two are
  distinguished by `observed_label`: it is null for the former and present for the latter. They are never "normal".
* `activations/` and the rule trace of those rows are the engine's: the firing of a rule is a degree of rule match even
  where the class is not published. So `/rule-trace` of a no-reference row returns the label the rules would give, while
  `/series` returns none. A client should draw the series/prediction (grey, "sin referencia") and not the trace label.

## 7. Limits

* One winter, no winter in the reference: "alta" in February-March mixes unusual demand with season, vendor reporting and
  congestion pricing. The model is evaluated on that shift, not corrected for it. No causal statement.
* The label of one zone-hour is noisy (about 39 reference values per cell; a percentile step of about 2.6 points).
* Test is one block of 7.5 weeks, read once; the fuzzy seed sd (0.013) and the one-fit-per-shape selection are the main
  sources of uncertainty. Selection used only validation (January 2025, after the toll).
* The comparison with LR/RF/HGB is on 12 inputs and default settings (300 trees, 20-row leaves, 200 boosting iterations,
  no tuning), a fixed budget and not a search.
* Compute (one core for the GA, up to 4 threads for the random forests): 12 selection fits 17.5 min in total
  (31-180 s each), final command 199 s wall (3 seeds of 31 s, 13 baselines), peak RSS 1.46 GB.

## Reproduce

```bash
export ATLAS_DATA_DIR=/path/to/exfuzzy-atlas/data ATLAS_ARTIFACTS_DIR=/path/to/exfuzzy-atlas/artifacts
export PYTHONPATH=src:apps/api
PY=python
for A in all12 rel7; do $PY -m atlas.ml.experiment_nyc select --config configs/ml/nyc_pickups_h1_level_${A}_experiment.json; done
$PY -m atlas.ml.experiment_nyc final --config configs/ml/nyc_pickups_h1_level_rel7_experiment.json   # seeds, baselines, test (once)
$PY -m atlas.ml.experiment_nyc runs  --config configs/ml/nyc_pickups_h1_level_rel7_experiment.json   # artifacts/nyc_pickups_h1/level-rel7-seed{0,1,2}
$PY -m atlas.ml.report_nyc --experiment artifacts/nyc_pickups_h1/experiments/level-rel7 --other artifacts/nyc_pickups_h1/experiments/level-all12
D=$ATLAS_DATA_DIR/processed/mobility
$PY -m atlas.services.publish --run-dir artifacts/nyc_pickups_h1/level-rel7-seed0 \
  --features $D/features/nyc_pickups_h1_level --entities $D/taxi_zones_simplified.geojson \
  --feature-spec configs/mobility/feature_spec.json --from 2025-02-08T05:00:00Z --to 2025-04-01T04:00:00Z \
  --task-id nyc_pickups_h1 --title "Yellow-taxi demand level (NYC)" --observed-label-column target_level
$PY -m pytest tests/ml/test_nyc_experiment.py tests/services/test_publish_observed_label.py -q
```

Seeds, split and the subsample keys (`subsample_keys.parquet`) are saved under `artifacts/nyc_pickups_h1/experiments/level-rel7/`.
