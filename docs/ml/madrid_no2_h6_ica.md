# Madrid NO2 at t+6 h as an ICA category: ExFuzzy winning-rule classifier versus baselines (AT-041c)

> Follow-up AT-041d (justified terms per input, logistic regression and random forest baselines, traffic with versus
> without): `madrid_no2_h6_ica_v2.md`.

Task: for each station and issue time, predict **which official ICA band the hourly NO2 concentration will fall in six
hours later**. The output is labelled **"categoría ICA prevista de NO₂ (índice oficial)"**. It replaces the regression
of AT-041 (test R2 0.13, rules such as "... → 1 µg/m³" that could not be read one by one). Real data: the
`madrid_no2_h6` table of AT-011 (`docs/air/madrid_no2_h6.md`), same split, rows and features as AT-041. Model:
ex_fuzzy 3.3.1 `BaseFuzzyRulesClassifier` (type-1, winning-rule inference, CPU `pymoo`). Every number below comes from
the run artifacts (`class_distribution.json`, `selection.json`, `summary.json`, `metrics.json`, `rules.json`); the
tables are printed by `python -m atlas.ml.report_class`.

**What this is not.** The bands come from the official index; the model only predicts which band the concentration
will fall into. Firing, association degree and rule weight are degrees of rule match, **not probabilities**, not
contributions and not a measure of risk. Nothing here is a causal, clinical, sanitary or regulatory statement. The
health messages of the index (section 1) are the source's messages for *observed* concentrations; the model does not
make claims about health.

## 1. The scheme and its source

`configs/ml/ica_no2_scheme.json` (read from the official document on 2026-10-30):

* Source: Resolución del Director General de Calidad y Evaluación Ambiental por la que se modifica el anexo de la Orden
  TEC/351/2019 (Índice Nacional de Calidad del Aire), MITECO,
  <https://www.miteco.gob.es/content/dam/miteco/images/es/resoluciondgactualizacionica_tcm30-509833.pdf>, annex section A,
  table "Bandas de concentraciones y categorías de índice" (p. 3), column NO2; messages from the table "Recomendaciones
  para la salud" (p. 5). The PDF carries no date or BOE number: "resolución de 2 de septiembre de 2020, BOE núm. 242
  de 10-09-2020" was given by the coordinator and agrees with a secondary page (Ayuntamiento de Granada consolidated
  text); the BOE text itself was **not** checked.
* NO2 uses the mean concentration of the last hour. Values above the last upper bound (1000) are considered erroneous
  by the source.

| Category | NO2 band (µg/m³, whole numbers, both ends inclusive) | Colour (sampled from the official table) |
|---|---|---|
| Buena | 0 - 40 | #00FFFF |
| Razonablemente buena | 41 - 90 | #00B050 |
| Regular | 91 - 120 | #FFCC00 |
| Desfavorable | 121 - 230 | #FF3300 |
| Muy desfavorable | 231 - 340 | #990000 |
| Extremadamente desfavorable | 341 - 1000 | #9900FF |

Boundary convention: the official table lists whole numbers with both ends inclusive; the Madrid target is
integer-valued (checked: 100 % of the complete rows in all three periods), so the class of a value is the closed
integer range that contains it. For non-integers `ClassScheme.classify` rounds half up first. In the contract
(`TargetScheme`) the same scheme is `(−, 40], (40, 90], (90, 120], ...` with `boundary = upper_inclusive` and the first
class unbounded below; for integer data this is identical. The colours are not written as text in the PDF: they were
sampled from the filled cells of the rendered table (cyan, green, yellow, orange-red, dark red, violet).

Official health messages (column "Mensajes para la salud", used as class descriptions): Buena "Calidad del aire
satisfactoria"; Razonablemente buena "Calidad del aire aceptable, la contaminación no supone un riesgo para la salud";
Regular "La calidad del aire probablemente no afecte a la población general pero puede presentar un riesgo moderado
para los grupos de riesgo"; Desfavorable "Toda la población puede experimentar efectos negativos sobre la salud ...";
Muy desfavorable and Extremadamente desfavorable "Condiciones de emergencia para la salud pública ...". Quoted from
the source; they describe the band of an observed concentration.

## 2. Class distribution and the merge decision

**Official ICA classes** (complete rows, target at t+6 h)

| period | n | Buena | Razonablemente buena | Regular | Desfavorable | Muy desfavorable | Extremadamente desfavorable |
|---|---|---|---|---|---|---|---|
| train | 918601 | 683216 (74.376 %) | 207285 (22.565 %) | 20750 (2.259 %) | 7323 (0.797 %) | 27 (0.003 %) | 0 (0.000 %) |
| validation | 191459 | 157798 (82.419 %) | 31681 (16.547 %) | 1836 (0.959 %) | 144 (0.075 %) | 0 (0.000 %) | 0 (0.000 %) |
| test | 180326 | 151101 (83.793 %) | 27776 (15.403 %) | 1368 (0.759 %) | 81 (0.045 %) | 0 (0.000 %) | 0 (0.000 %) |

**Classes used by the model** (complete rows, target at t+6 h)

| period | n | Buena | Razonablemente buena | Regular | Desfavorable o peor |
|---|---|---|---|---|---|
| train | 918601 | 683216 (74.376 %) | 207285 (22.565 %) | 20750 (2.259 %) | 7350 (0.800 %) |
| validation | 191459 | 157798 (82.419 %) | 31681 (16.547 %) | 1836 (0.959 %) | 144 (0.075 %) |
| test | 180326 | 151101 (83.793 %) | 27776 (15.403 %) | 1368 (0.759 %) | 81 (0.045 %) |

Training has almost no hours above Desfavorable (27 in Muy desfavorable, none in Extremadamente) and validation and
test have none at all; the test year is also much cleaner than the training years (the downward trend noted in
AT-011), so the upper classes are far rarer in test (Regular 0.76 %, Desfavorable 0.045 %, 81 rows) than in training
(2.26 %, 0.80 %).

**Rule, fixed before any fit** (`merge_min_train_rows = 500`, in the experiment config): starting from the worst class,
a class with fewer than 500 complete *training* rows is merged with the next better class; the walk stops at the first
class with at least 500 rows. Only training counts are used. Applied here: Extremadamente (0) and Muy desfavorable (27)
are merged into **"Desfavorable o peor"** (121 - 1000 µg/m³; `merged_from` lists the three official labels in
`rules.json`'s `target_scheme` and in the run manifest). No threshold is changed or relabelled; the UI must show the
merged class as such and must not invent a split of it. The validation and test sets have only the 4 classes in use.

## 3. Protocol (decided before looking at the test period; `configs/ml/madrid_no2_h6_ica_experiment.json`)

| Item | Value |
|---|---|
| Table, features, split, embargo, complete rows | As AT-041: 9 features, train [2019-01-01, 2023-12-31), validation 2024, test 2025, embargo 24 h; train 918,601, validation 191,459, test 180,326 complete rows (22 stations in test) |
| Target | class of the observed NO2 at t+6 h in the scheme above (4 classes after the merge) |
| Model | `BaseFuzzyRulesClassifier`, type-1, `allow_unknown=True`, `ds_mode` dominance score (contract `rule_weighting = dominance_score`), product t-norm, 3 linguistic terms (Low / Medium / High) as quantile trapezoids built **on the whole training period** (`utils.construct_partitions`, `detect_categorical=False`) |
| GA fitness | macro-F1 of the pruned rule base on the fitting rows minus ex_fuzzy's small compactness (0.03) and class-coverage (0.05) penalties: already class-balance aware, so no custom loss was needed |
| Fitting rows | class-aware stratified subsample of the **training period only**, 30,000 rows, class sizes proportional to `count ** power` (power 0.5 chosen, below), uniform over station x month blocks inside each class; seed 20260101; keys in `subsample_keys.parquet`. Subsample classes: {16,404, 9,036, 2,859, 1,701} against the natural {74.4 %, 22.6 %, 2.3 %, 0.8 %} |
| Budget | `n_gen` 150 x `pop_size` 60 = 9,000 evaluations per fit (no early stop), CPU, `OMP_NUM_THREADS=4`, RSS about 1.0 GB, 16 to 136 s per fit |
| Selection (validation only) | 23 candidates fitted once with seed 0, criterion **highest validation macro-F1** (ties: fewer rules). Stage A: class-sampling power {1, 0.5, 0} x weighting {dominance score, GA-optimised weight} at 30 rules x 3 antecedents x 3 terms. Stage B (list fixed after stage A, with its winner power 0.5 / dominance score): nRules {15, 30, 60} x nAnts {2, 3, 4} x terms {3, 5} |
| Final | the chosen shape, seeds {0, 1, 2}, same subsample and budget; the published seed is the one with the highest **validation** macro-F1 |
| Baselines (identical rows) | persistence class (class of `no2_last`); majority class of the training rows per station x local hour x weekday of the valid time (fallback station, then global); HGB classifier (200 iterations, defaults) on the full training period; the same with `class_weight="balanced"`; HGB regression on the raw value (200 iterations) whose output is binned with the scheme; HGB classifier on the same 30,000-row subsample as ExFuzzy |
| Test | read once, in `final`, after the shape and budget were fixed |

Unknown predictions (no rule fires, or a missing input) count as wrong answers and never as a class. Macro-F1 and
balanced accuracy average over the classes present in the evaluated rows. MAE on the class index and the share off by
two or more categories use the rows that have a prediction. Per-class rows in `metrics.json` are named
`recall[Regular]`, `precision[...]`, `f1[...]` and `confusion[Buena>Regular]` (last predicted column `no_prediction`).

## 4. Selection on validation

| power | weighting | nRules | nAnts | terms | rules kept | GA fitness (train) | val macro-F1 | val bal-acc | val acc | val MAE idx | unknown | fit s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.5 | dominance_score | 60 | 3 | 3 | 16 | 0.471 | 0.354 | 0.457 | 0.733 | 0.300 | 0.000 | 86 |
| 0.5 | dominance_score | 30 | 2 | 3 | 12 | 0.454 | 0.342 | 0.460 | 0.714 | 0.329 | 0.003 | 36 |
| 0.5 | dominance_score | 60 | 3 | 5 | 21 | 0.450 | 0.340 | 0.386 | 0.743 | 0.279 | 0.002 | 136 |
| 0.5 | dominance_score | 60 | 4 | 3 | 16 | 0.474 | 0.339 | 0.456 | 0.678 | 0.352 | 0.000 | 90 |
| 0.5 | dominance_score | 30 | 4 | 3 | 13 | 0.468 | 0.334 | 0.428 | 0.712 | 0.319 | 0.003 | 40 |
| 0.5 | dominance_score | 60 | 2 | 3 | 14 | 0.461 | 0.334 | 0.454 | 0.729 | 0.315 | 0.000 | 80 |
| 0.5 | dominance_score | 30 | 3 | 3 | 9 | 0.461 | 0.333 | 0.437 | 0.677 | 0.345 | 0.006 | 33 |
| 0.5 | dominance_score | 60 | 2 | 5 | 14 | 0.440 | 0.331 | 0.411 | 0.729 | 0.322 | 0.001 | 70 |
| 1.0 | dominance_score | 30 | 3 | 3 | 13 | 0.410 | 0.330 | 0.329 | 0.786 | 0.227 | 0.000 | 39 |
| 0.5 | dominance_score | 15 | 2 | 5 | 11 | 0.428 | 0.329 | 0.423 | 0.677 | 0.338 | 0.040 | 27 |
| 0.5 | dominance_score | 60 | 4 | 5 | 27 | 0.439 | 0.329 | 0.405 | 0.722 | 0.314 | 0.027 | 124 |
| 0.5 | weight | 30 | 3 | 3 | 12 | 0.465 | 0.327 | 0.452 | 0.688 | 0.350 | 0.000 | 51 |
| 0.5 | dominance_score | 15 | 3 | 3 | 9 | 0.448 | 0.322 | 0.455 | 0.672 | 0.375 | 0.001 | 19 |
| 0.5 | dominance_score | 30 | 4 | 5 | 15 | 0.427 | 0.321 | 0.411 | 0.685 | 0.334 | 0.049 | 53 |
| 0.5 | dominance_score | 15 | 3 | 5 | 10 | 0.395 | 0.314 | 0.371 | 0.721 | 0.331 | 0.006 | 31 |
| 0.5 | dominance_score | 30 | 2 | 5 | 16 | 0.411 | 0.314 | 0.385 | 0.731 | 0.310 | 0.001 | 46 |
| 0.5 | dominance_score | 15 | 2 | 3 | 9 | 0.403 | 0.313 | 0.391 | 0.680 | 0.375 | 0.000 | 16 |
| 1.0 | weight | 30 | 3 | 3 | 11 | 0.384 | 0.311 | 0.312 | 0.779 | 0.229 | 0.006 | 48 |
| 0.5 | dominance_score | 15 | 4 | 5 | 10 | 0.365 | 0.310 | 0.319 | 0.615 | 0.342 | 0.162 | 28 |
| 0.5 | dominance_score | 30 | 3 | 5 | 16 | 0.443 | 0.309 | 0.456 | 0.623 | 0.458 | 0.003 | 43 |
| 0.5 | dominance_score | 15 | 4 | 3 | 9 | 0.443 | 0.302 | 0.444 | 0.559 | 0.427 | 0.115 | 21 |
| 0.0 | dominance_score | 30 | 3 | 3 | 13 | 0.477 | 0.287 | 0.455 | 0.591 | 0.580 | 0.000 | 43 |
| 0.0 | weight | 30 | 3 | 3 | 14 | 0.479 | 0.274 | 0.510 | 0.530 | 0.647 | 0.000 | 62 |

Reading: the validation macro-F1 of the 23 candidates spans 0.27 to 0.35, but most of the spread is within what a
single-seed GA fit can produce (the 3 final seeds of the chosen shape give 0.340 to 0.354). What is clear: fully
balanced sampling (power 0) lowers accuracy and macro-F1 strongly (many false alarms in the upper classes); natural
sampling (power 1) is accurate but recalls the rare classes poorly (balanced accuracy 0.33); the square-root
compromise is better on macro-F1 and balanced accuracy. The GA-optimised weights did not beat the dominance score at this
budget (0.327 against 0.333, one seed). Five terms did not help. 60 rules (of which 14 to 18 survive the library's
pruning) were slightly better than 30 or 15. The chosen shape is the maximum of a noisy ranking, not a proven optimum.

## 5. Test results (2025, 180,326 complete rows, seed 0 = published model)

| estimator | macro_f1 | balanced_accuracy | accuracy | mae_class_index | share_off_by_2plus | share_unknown |
|---|---|---|---|---|---|---|
| persistence | 0.294 | 0.294 | 0.769 | 0.244 | 0.012 | 0.000 |
| climatology_majority_class | 0.291 | 0.286 | 0.827 | 0.181 | 0.007 | 0.000 |
| hist_gradient_boosting | 0.373 | 0.396 | 0.845 | 0.163 | 0.006 | 0.000 |
| hist_gradient_boosting_balanced | 0.350 | 0.626 | 0.725 | 0.343 | 0.058 | 0.000 |
| hist_gradient_boosting_regression_binned | 0.414 | 0.406 | 0.836 | 0.166 | 0.002 | 0.000 |
| hist_gradient_boosting_subsample | 0.383 | 0.493 | 0.798 | 0.223 | 0.018 | 0.000 |
| exfuzzy_classifier | 0.336 | 0.459 | 0.736 | 0.302 | 0.028 | 0.000 |

Validation (2024, 191,459 rows):

| estimator | macro_f1 | balanced_accuracy | accuracy | mae_class_index | share_off_by_2plus | share_unknown |
|---|---|---|---|---|---|---|
| persistence | 0.294 | 0.294 | 0.758 | 0.258 | 0.015 | 0.000 |
| climatology_majority_class | 0.286 | 0.283 | 0.813 | 0.197 | 0.010 | 0.000 |
| hist_gradient_boosting | 0.376 | 0.372 | 0.849 | 0.158 | 0.006 | 0.000 |
| hist_gradient_boosting_balanced | 0.375 | 0.603 | 0.740 | 0.320 | 0.050 | 0.000 |
| hist_gradient_boosting_regression_binned | 0.396 | 0.386 | 0.839 | 0.164 | 0.003 | 0.000 |
| hist_gradient_boosting_subsample | 0.405 | 0.490 | 0.806 | 0.213 | 0.016 | 0.000 |
| exfuzzy_classifier | 0.354 | 0.457 | 0.733 | 0.300 | 0.024 | 0.000 |

Per class on test (recall with the number of rows of the class; precision is the share of rows predicted in that class
that really belong to it):

| estimator | Buena (n=151101) | Razonablemente buena (n=27776) | Regular (n=1368) | Desfavorable o peor (n=81) |
|---|---|---|---|---|
| persistence | 0.864 | 0.291 | 0.020 | 0.000 |
| climatology_majority_class | 0.952 | 0.192 | 0.000 | 0.000 |
| hist_gradient_boosting | 0.922 | 0.471 | 0.029 | 0.160 |
| hist_gradient_boosting_balanced | 0.761 | 0.539 | 0.514 | 0.691 |
| hist_gradient_boosting_regression_binned | 0.895 | 0.554 | 0.102 | 0.074 |
| hist_gradient_boosting_subsample | 0.852 | 0.530 | 0.308 | 0.284 |
| exfuzzy_classifier | 0.798 | 0.422 | 0.271 | 0.346 |

| estimator | Buena | Razonablemente buena | Regular | Desfavorable o peor |
|---|---|---|---|---|
| persistence | 0.866 | 0.288 | 0.019 | 0.000 |
| climatology_majority_class | 0.858 | 0.417 | 0.000 | 0.000 |
| hist_gradient_boosting | 0.903 | 0.518 | 0.149 | 0.022 |
| hist_gradient_boosting_balanced | 0.950 | 0.355 | 0.053 | 0.015 |
| hist_gradient_boosting_regression_binned | 0.917 | 0.477 | 0.289 | 0.105 |
| hist_gradient_boosting_subsample | 0.925 | 0.417 | 0.098 | 0.015 |
| exfuzzy_classifier | 0.900 | 0.302 | 0.085 | 0.009 |

Confusion matrix of the ExFuzzy classifier on test (rows: observed class; the persistence and HGB matrices follow):

| observed \ predicted | Buena | Razonablemente buena | Regular | Desfavorable o peor | no_prediction |
|---|---|---|---|---|---|
| **Buena** | 120,605 | 26,930 | 1,775 | 1,791 | 0 |
| **Razonablemente buena** | 12,877 | 11,727 | 2,220 | 951 | 1 |
| **Regular** | 495 | 220 | 371 | 282 | 0 |
| **Desfavorable o peor** | 33 | 10 | 10 | 28 | 0 |

| observed \ predicted | Buena | Razonablemente buena | Regular | Desfavorable o peor | no_prediction |
|---|---|---|---|---|---|
| **Buena** | 130,519 | 19,619 | 904 | 59 | 0 |
| **Razonablemente buena** | 19,141 | 8,077 | 531 | 27 | 0 |
| **Regular** | 1,043 | 296 | 28 | 1 | 0 |
| **Desfavorable o peor** | 59 | 21 | 1 | 0 | 0 |

| observed \ predicted | Buena | Razonablemente buena | Regular | Desfavorable o peor | no_prediction |
|---|---|---|---|---|---|
| **Buena** | 139,325 | 11,431 | 96 | 249 | 0 |
| **Razonablemente buena** | 14,338 | 13,081 | 129 | 228 | 0 |
| **Regular** | 520 | 703 | 40 | 105 | 0 |
| **Desfavorable o peor** | 35 | 29 | 4 | 13 | 0 |

| estimator | mean over stations | min | max | stations where best |
|---|---|---|---|---|
| persistence | 0.345 | 0.271 | 0.445 | 0 |
| climatology_majority_class | 0.328 | 0.266 | 0.410 | 0 |
| hist_gradient_boosting | 0.434 | 0.347 | 0.540 | 21 |
| exfuzzy_classifier | 0.384 | 0.273 | 0.464 | 1 |

22 stations; macro-F1 per station averages only the classes observed at that station.

### 5.1 Seeds (same subsample, budget and shape; only the GA seed changes)

| seed | rules | val macro-F1 | test macro-F1 | test bal-acc | test acc | test MAE idx | test unknown | fit s |
|---|---|---|---|---|---|---|---|---|
| 0 | 16 | 0.354 | 0.336 | 0.459 | 0.736 | 0.302 | 0.000 | 84 |
| 1 | 18 | 0.340 | 0.329 | 0.420 | 0.764 | 0.277 | 0.001 | 107 |
| 2 | 14 | 0.344 | 0.330 | 0.424 | 0.733 | 0.297 | 0.000 | 115 |
| mean ± sd |  | 0.346 ± 0.007 | 0.332 ± 0.004 | 0.434 ± 0.021 | 0.744 ± 0.017 | 0.292 ± 0.013 | 0.000 ± 0.001 |  |

Seed 0 is the published model (highest validation macro-F1). On test it is also the best of the three, so it is a
slightly optimistic draw of the model family; the mean row is the fairer summary. The class most sensitive to the
seed is the rarest: recall of "Desfavorable o peor" is 0.35, 0.11 and 0.15 for seeds 0, 1 and 2 (81 test rows).

### 5.2 Honest comparison with the baselines

* ExFuzzy is clearly better than the two naive baselines on class-balanced measures: macro-F1 0.336 (3 seeds
  0.332 ± 0.004) against 0.294 (persistence) and 0.291 (climatology); balanced accuracy 0.459 against 0.294 and 0.286.
  It is worse on plain accuracy (0.736 against 0.769 and 0.827) because it deliberately predicts the upper classes
  more often, at the price of many false alarms; accuracy is dominated by "Buena" (83.8 % of test rows) and the
  majority-class baseline wins it.
* ExFuzzy is **worse than the HGB models on macro-F1**: 0.336 against 0.373 (HGB classifier), 0.383 (HGB on the same
  30,000 rows) and 0.414 (HGB regression, binned). It wins at 1 of the 22 stations, HGB at 21. Its ordinal errors are
  larger: mean error of 0.30 classes against 0.16, and 2.8 % of rows are off by two or more categories against 0.6 %
  (HGB) and 1.2 % (persistence).
* The HGB classifier with balanced class weights detects the rare classes better than ExFuzzy (recall Regular 0.51
  against 0.27, Desfavorable o peor 0.69 against 0.35) with similarly poor precision (0.05 and 0.015 against 0.085 and
  0.009), at the price of lower accuracy (0.725). If the goal were only to flag the upper classes, ExFuzzy is not the
  best tool here.
* Precision in the upper classes is low for every model: of the 3,052 test rows ExFuzzy puts in "Desfavorable o peor",
  28 belong to it (0.9 %). The test year has 81 such hours; recall and precision there are very noisy.
* The level shift hurts every model in the same way: training years are dirtier (Regular 2.3 % of rows) than 2024 and
  2025 (1.0 % and 0.8 %), so a model fitted on training class frequencies (or on a tempered version of them) raises
  more false alarms in the test year.
* The comparison is on one table, one split, three seeds for ExFuzzy and one fit per baseline; differences of a
  few hundredths of macro-F1 between models should not be over-read, the gap to HGB (0.04 to 0.08) is several seed
  standard deviations.

## 6. Readability (AT-043)

| readability metric (published seed) | value |
|---|---|
| rules | 16 |
| rules for Buena | 5 |
| rules for Razonablemente buena | 4 |
| rules for Regular | 5 |
| rules for Desfavorable o peor | 2 |
| mean rule length (antecedents) | 1.62 |
| duplicate rules (same antecedents) | 0 |
| antecedent sets used with more than one class | 0 |
| rules that win at least one validation row | 16 |
| rules that win at least 1 % of validation rows | 10 |
| share of validation rows with no prediction | 0.0000 |
| share of test rows with no prediction | 0.0000 |
| Jaccard of rules across seeds (mean over pairs) | 0.118 |
| Jaccard of antecedent sets across seeds | 0.143 |

Reading: the rule base is small enough to read in a minute (16 rules, 1.6 antecedents on average, no duplicates and
no antecedent set with two classes, every rule wins at least one validation row). Two caveats. First, it is not stable
across seeds: only about one rule in eight is shared by two seeds (Jaccard 0.12). Second, the terms are quantile
terms (see the table at the end), not health thresholds: for NO2 "High" starts at 28 to 47 µg/m³ and covers every
concentration above, including all of the "Desfavorable" band, so "no2_last IS High" cannot be read as "NO2 is in
the unhealthy range".

## 7. The published rules (seed 0)

Weights are the dominance scores computed by ex_fuzzy on the 30,000 fitting rows (confidence x support): they depend on
the class-tempered sample, only their relative size decides between rules, and they are not probabilities or
importances. "Validation rows decided" is the share of validation rows whose winning rule is that rule (a share of
rows, not a contribution).

| rule | text | validation rows decided | of those, observed class equal |
|---|---|---|---|
| R01 | IF no2_lag3h IS Low THEN ICA = **Buena** (peso 0.17) | 45.5 % | 0.93 |
| R02 | IF no2_last IS Medium ∧ valid_hour_local IS Low THEN ICA = **Buena** (peso 0.052) | 4.3 % | 0.83 |
| R03 | IF no2_lag3h IS Medium ∧ valid_hour_local IS Medium THEN ICA = **Buena** (peso 0.058) | 11.3 % | 0.80 |
| R04 | IF no2_lag3h IS Medium ∧ wind_speed IS High THEN ICA = **Buena** (peso 0.056) | 5.1 % | 0.86 |
| R05 | IF no2_last IS Low ∧ no2_lag24h IS Low THEN ICA = **Buena** (peso 0.093) | 7.6 % | 0.87 |
| R06 | IF no2_lag3h IS Medium ∧ no2_lag24h IS Low THEN ICA = **Razonablemente buena** (peso 0.0081) | 0.5 % | 0.43 |
| R07 | IF valid_hour_local IS Low THEN ICA = **Razonablemente buena** (peso 0.022) | 3.3 % | 0.32 |
| R08 | IF relative_humidity IS High THEN ICA = **Razonablemente buena** (peso 0.036) | 11.6 % | 0.31 |
| R09 | IF no2_lag3h IS High ∧ valid_hour_local IS Medium THEN ICA = **Razonablemente buena** (peso 0.038) | 6.6 % | 0.33 |
| R10 | IF temperature IS Medium THEN ICA = **Regular** (peso 0.0037) | 0.4 % | 0.10 |
| R11 | IF no2_lag24h IS Medium ∧ valid_hour_local IS High THEN ICA = **Regular** (peso 0.0053) | 1.7 % | 0.11 |
| R12 | IF no2_lag1h IS High ∧ wind_speed IS Medium THEN ICA = **Regular** (peso 0.0046) | 0.2 % | 0.14 |
| R13 | IF no2_last IS Medium ∧ wind_speed IS Medium THEN ICA = **Regular** (peso 0.003) | 0.0 % | 0.13 |
| R14 | IF valid_weekday IS Medium THEN ICA = **Regular** (peso 0.0043) | 0.7 % | 0.16 |
| R15 | IF no2_last IS High THEN ICA = **Desfavorable o peor** (peso 0.0035) | 0.1 % | 0.01 |
| R16 | IF relative_humidity IS Low ∧ valid_hour_local IS High THEN ICA = **Desfavorable o peor** (peso 0.0062) | 1.2 % | 0.01 |

What the rules say, without over-reading: "Buena" is decided mostly by low NO2 three hours before (R01 alone decides
45 % of validation rows with 93 % agreement). The "Razonablemente buena" rules agree with the observed class in 31 to 43 %
of the rows they decide. The rules of "Regular" and "Desfavorable o peor" have an observed-class agreement of 10 to
16 % and 1 %, and some use antecedents with no physical reason to matter for the category (`valid_weekday IS Medium`,
`temperature IS Medium`): the GA found weak rules for classes with 0.8 to 2 % of the rows; they should not be
presented as explanations.

### Linguistic terms

| feature | unit | term | type | parameters |
|---|---|---|---|---|
| no2_last | ug/m3 | Low | trapezoidal | 1, 1, 10, 17 |
| no2_last | ug/m3 | Medium | trapezoidal | 10, 17, 28, 47 |
| no2_last | ug/m3 | High | trapezoidal | 28, 47, 328, 328 |
| no2_lag1h | ug/m3 | Low | trapezoidal | 1, 1, 10, 17 |
| no2_lag1h | ug/m3 | Medium | trapezoidal | 10, 17, 28, 47 |
| no2_lag1h | ug/m3 | High | trapezoidal | 28, 47, 328, 328 |
| no2_lag3h | ug/m3 | Low | trapezoidal | 1, 1, 10, 17 |
| no2_lag3h | ug/m3 | Medium | trapezoidal | 10, 17, 28, 47 |
| no2_lag3h | ug/m3 | High | trapezoidal | 28, 47, 328, 328 |
| no2_lag24h | ug/m3 | Low | trapezoidal | 1, 1, 10, 17 |
| no2_lag24h | ug/m3 | Medium | trapezoidal | 10, 17, 28, 47 |
| no2_lag24h | ug/m3 | High | trapezoidal | 28, 47, 328, 328 |
| wind_speed | m/s | Low | trapezoidal | -0.0001, -0.0001, 0.57, 0.92 |
| wind_speed | m/s | Medium | trapezoidal | 0.57, 0.92, 1.37, 2.08 |
| wind_speed | m/s | High | trapezoidal | 1.37, 2.08, 10.6, 10.6 |
| temperature | degC | Low | trapezoidal | -14, -14, 8.3, 12.5 |
| temperature | degC | Medium | trapezoidal | 8.3, 12.5, 17.7, 24.2 |
| temperature | degC | High | trapezoidal | 17.7, 24.2, 47.9, 47.9 |
| relative_humidity | % | Low | trapezoidal | -0.0001, -0.0001, 34, 47 |
| relative_humidity | % | Medium | trapezoidal | 34, 47, 62, 78 |
| relative_humidity | % | High | trapezoidal | 62, 78, 100, 100 |
| valid_hour_local | h | Low | trapezoidal | -0.0001, -0.0001, 4, 9 |
| valid_hour_local | h | Medium | trapezoidal | 4, 9, 14, 19 |
| valid_hour_local | h | High | trapezoidal | 14, 19, 23, 23 |
| valid_weekday | day | Low | trapezoidal | -0.0001, -0.0001, 1, 2 |
| valid_weekday | day | Medium | trapezoidal | 1, 2, 4, 5 |
| valid_weekday | day | High | trapezoidal | 4, 5, 6, 6 |

## 8. Contract v0.3 artifacts and parity tests

* `atlas.explain.classifier`: `compute_classifier_activations` (library memberships, firing, association degree,
  winning rule and class), `build_classifier_traces` (`RuleTrace` with `weight`, `association_degree`,
  `TracePrediction.label` / `winning_rule_id`), `iter_classifier_firing_tables` (columns `firing_strength`, `weight`,
  `association_degree`, `is_winner`, `missing_reason`), `inference_spec`.
* `atlas.ml.rules_export.export_classifier_rules`: `ModelRules` with `target_scheme`, `Consequent(type="class")`, rule
  `weight`, text `IF ... THEN ICA = Regular (peso 0.71)`.
* Golden tests (`tests/ml/test_classifier_traces.py`): trace firing and association equal ex_fuzzy's own arrays; winning
  rule and label equal `predict` and `explainable_predict`; the three `ds_mode`s; a missing-input row has no rules and
  `missing_input`; a hand-built rule base where nothing fires gives `label = None`, `prediction_unavailable`; an
  `allow_unknown=False` model is refused because ex_fuzzy would answer the class of rule 0 with association 0.
* Run directories `artifacts/madrid_no2_h6/ica-v1-seed{0,1,2}/` (model id `exfuzzy-madrid_no2_h6-ica-v1-seed<k>`):
  `model.pkl`, `run_manifest.json`, `metrics.json`, `rules.json`, `predictions.parquet` (test year: `observed`,
  `observed_label`, null `prediction`, `prediction_label`, `missing_reason`), `SHA256SUMS`.

## 9. Reproduce

```bash
export ATLAS_DATA_DIR=.../data ATLAS_ARTIFACTS_DIR=.../artifacts PYTHONPATH=src OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4
CFG=configs/ml/madrid_no2_h6_ica_experiment.json
PY=python
$PY -m atlas.ml.experiment_class select --config $CFG    # class_distribution.json, selection.json (validation only), about 20 min
$PY -m atlas.ml.experiment_class final  --config $CFG    # 3 seeds, baselines, test; summary.json, models/, about 6 min
$PY -m atlas.ml.experiment_class runs   --config $CFG    # run directories (contract v0.3 rules.json)
$PY -m atlas.ml.report_class --experiment $ATLAS_ARTIFACTS_DIR/madrid_no2_h6/experiments/ica-v1 \
    --run-dir $ATLAS_ARTIFACTS_DIR/madrid_no2_h6/ica-v1-seed0 > tables.md
```

Compute: selection 20 min of fits, final 5 min of fits plus about 1 min of HGB baselines, one process, 4 threads,
peak RSS 1.03 GB.

## 10. Observations for the ex_fuzzy author (3.3.1)

All checked on the installed package.

1. `MasterRuleBase.explainable_predict(...).association_degree` is `np.max(firing_strengths, axis=1)` (see
   `_winning_rules`): the largest **firing**, not the association degree of the winning rule (firing x weight). With a
   hand-built two-rule base (scores 0.5 and 0.25) a row with firing 1 returns 1.0 while the winner's association is
   0.5. The docstring says "association degree". Atlas takes the association from `compute_association_degrees`.
2. With `allow_unknown=False`, a row on which no rule fires gets the class of **rule 0** (`argmax` of an all-zero row),
   silently, with association 0. Atlas always uses `allow_unknown=True` and refuses to export the other setting.
3. The dominance score (confidence x support) is computed once on the fitting rows, so rule weights carry the class
   priors of the fitting sample (here a tempered one). A class-balanced fit and a natural fit give weights that are not
   comparable. The weights are in the 0.003 to 0.17 range here, which is a problem only if someone reads them as
   anything other than a relative ordering.
4. `nRules` is only an upper bound: with `nRules=60` the final rule base has 14 to 18 rules (rules with zero accuracy
   or a score below the tolerance are purged). The pruning tolerance is not stored on the `MasterRuleBase`, so a
   serialised model cannot say which tolerance produced it.
5. The rule list is class-major (all rules of class 0, then class 1, ...) and ties go to the first rule, i.e. to the
   better class in an ordinal task. Worth documenting.
6. The default fitness (macro-F1 with penalties) worked for imbalance without a custom loss. Not tried: an ordinal-aware
   custom loss (MAE on the class index); a `customized_loss` disables the fit-local caches, so it would be much slower.
7. `ds_mode='optimized'` (one weight per rule found by the GA) was 20 to 50 % slower per fit and not better on validation
   at this budget (one seed per setting; no conclusion beyond that).
8. `BaseFuzzyRulesClassifier.performance` is an array (`1 - result['F']`), and `optimization_result_` keeps the fitting
   data inside the estimator; Atlas deletes it before pickling.
9. Partitions from `construct_partitions` are quantile trapezoids whose terms carry no domain meaning. A way to give
   cut points (for NO2 the ICA breakpoints 40, 90, 120) would let rules read in the vocabulary of the index. Not done
   here (next step, below).

## 11. Limitations and next steps

* Limitations: one city, one pollutant, one horizon; very few hours in the upper classes in 2024 and 2025 (144 and 81),
  so their metrics are noisy; the model is weaker than HGB and its rules are not stable across seeds; the merged class
  is "Desfavorable o peor" because the data cannot support a finer split; the selection ranking is within seed noise;
  the 30,000-row class-tempered sample changes the class priors seen by the GA, which `class_weight` or a different
  `power` would change again; no calibration, no uncertainty, no cross-validation by year.
* Next step suggested: partitions of the NO2 features aligned with the ICA bands (cuts at 40, 90, 120 µg/m³) so that the
  rules read as "NO2 three hours before was in the Razonablemente buena band"; and an ordinal-aware loss.
* Publishing needs a services change (see the PR description).
