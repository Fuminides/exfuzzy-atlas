# Madrid NO2 at t+6 h as an ICA category, v3: calibration, natural-prior weights, consensus rules, ordinal decomposition, extra inputs (AT-041e)

Follow-up of `madrid_no2_h6_ica_v2.md` (AT-041d). Same task, rows, split (train 2019-2023 / validation 2024 / test 2025,
24 h embargo), class merge, justified partitions (`configs/ml/madrid_partitions.json`), fitting protocol (class-aware
30,000-row subsample, power 0.5, 60 rules x 4 antecedents, 150 generations x 60 individuals) and baselines. Prototype in
Atlas on the pinned ex_fuzzy 3.3.1 public API; whatever proves useful may later go upstream (section 8).

**What this is not.** Same limits as AT-041c/d: firing, association degree and rule weight are degrees of rule match,
not probabilities, contributions or risk. A per-class factor is a decision threshold, not a probability correction.
A selection frequency is a count of fits, not the probability that a rule is true. No causal, clinical, sanitary or
regulatory claim.

## 0. Decision rules (written and committed before any validation number of the new arms was produced)

History, for honesty. When this section was written, the only AT-041d numbers known to the author were the published
ones (validation and test macro-F1 of the three seeds, the baseline table and the rule-set Jaccard 0.15). A timing
test of two single GA fits on training rows (20,000 rows, 60 and 100 generations: 19 s and 33 s) was run to size the
consensus budget; it computed no validation or test score.

**Arms** (every one is scored on all complete validation rows, 3 seeds; a "seed" is the unit that is repeated):

| id | idea | what is repeated 3 times |
|---|---|---|
| `base` | AT-041d `justified` as published | its seeds 0, 1, 2 (pickles of `ica2-justified`, reproduction checked) |
| `calib` | 1: per-class factor on the association | the 3 `base` models, factors tuned on validation |
| `natw` | 2: dominance scores recomputed by ex_fuzzy on all 918,601 training rows | the 3 `base` models |
| `natw_calib` | 2 then 1 | the 3 `base` models |
| `cons_p30`, `cons_p50` (+ `_calib`) | 3: consensus rules, pi = 0.3 / 0.5; weights recomputed on all training rows | 3 disjoint seed sets A, B, C of N = 15 fits each; each set gives one consensus rule base |
| `restart_k5`, `restart_k15` | 6: best of k fits by validation macro-F1, k = 5 (first 5 of each set) / 15 (the whole set); same fits as the consensus pool | sets A, B, C |
| `feat_trend`, `feat_anomaly`, `feat_type`, `feat_all` | 5: one extra input / all three; same protocol as `base` | GA seeds 0, 1, 2 (same fitting sample as `base`) |
| `ordinal` (raw / calibrated, `highest` / `count`) | 4: three binary winning-rule classifiers, NO2 > 40, > 90, > 120 | GA seeds 0, 1, 2 |

Each consensus fit uses a fresh class-aware draw of 20,000 training rows (power 0.5, a different draw per fit seed) and
100 generations x 60 individuals (fewer than the 150 x 60 of `base` to fit the CPU budget; this makes single fits of the
pool a little weaker than a `base` fit, which is the price of N = 15 fits per set). Partitions are the same for every fit.

**Calibration.** One factor per class (Buena fixed to 1), coordinate ascent over a log grid 0.01-1000 (41 values, 3
sweeps) maximising validation macro-F1. The factor is folded into the rule weights (`weight = dominance score x
factor`), so `association = firing x weight` holds; the unscaled score is exported as `dominance_score_raw`. Because the
factors are tuned on the rows that score them, a calibrated arm is **selected on its cross-fitted macro-F1**: validation
rows are split into two halves by ISO-week parity, each half is predicted with the factors tuned on the other half, and
the macro-F1 of the pooled predictions is used. The in-sample figure is reported next to it.

**Stability** is the mean pairwise Jaccard index of the sets of `(antecedent set, class)` rules of the 3 repeated units
(for the consensus arms this is the stability of the whole procedure: rule bases built from disjoint seed sets).
Reference: AT-041d, 0.151.

**Entry to the combination.** An isolated idea enters the combination if its mean (cross-fitted) validation macro-F1 is at
least 0.011 above `base` (one seed sd of `base`), or if its Jaccard is at least 0.05 above `base` while its macro-F1 is
not more than 0.011 below. Entered ideas are combined in the order extra inputs, consensus, natural weights,
calibration; the combination is evaluated like any other arm. If the CPU budget does not allow the combination (a
consensus pool on new inputs is 45 more fits), that is stated and the combination is restricted to the ideas that can be
stacked on stored fits.

**Final choice.** Among arms that are plain winning-rule classifiers (not `ordinal`) with Jaccard >= 0.151, take the one
with the highest mean validation macro-F1 (cross-fitted for calibrated arms); if the best is less than 0.011 above `base`,
`base` is kept and nothing new is proposed for publication. Ties within 0.005 go to the arm with fewer rules. The
published seed (or set) of the chosen arm is the one with the highest validation macro-F1. An arm that uses the extra
inputs is eligible but flagged: publishing it needs the columns in the feature table (A1). The `ordinal` arm is never
published (new inference family); if it wins on validation macro-F1 by the same margin, a contract proposal is written.

**Test.** Read once, in one command, for the chosen arm and `base`; the baselines are those of AT-041d (same rows, same
fits, `ica2-justified/summary.json`), not refitted.


## 1. Deviations from section 0 (all of them, in the order they happened)

1. **Consensus at pi = 0.3 and 0.5 collapsed** (section 3). pi = 0.5 left two of the three seed sets without any rule, so
   `cons_p50` could not be built; pi = 0.3 left 1-2 rules per set. Only then, and seeing those numbers, two lower
   thresholds were added as **post-hoc** arms (`posthoc_cons_p10`, `posthoc_cons_p20`). They are reported, are excluded
   from `decide` (a test in `tests/ml/test_ica3_report.py` pins the exclusion by name) and cannot be chosen by the rule.
2. The empty-rule-base case crashed the first consensus run (`BaseFuzzyRulesClassifier.load_master_rule_base` indexes
   rule 0); the stage now records an empty consensus and skips it. No number was affected.
3. **Test.** The chosen arm is `base` itself, so the single test read scored `base`, and, **for information only**, the
   post-hoc `posthoc_cons_p20` (the only arm that moves stability). It was not used to choose anything. No other arm was
   scored on test.
4. A control that was not in section 0 (HistGradientBoosting with and without the extra inputs, validation) was added to
   interpret idea 5; it is not part of any selection.

## 2. Ideas 1 and 2: class factors and dominance scores from all training rows

Reproduction first: re-scoring the three AT-041d pickles gives their published validation macro-F1 to 1e-9 (0.3481,
0.3287, 0.3310). All numbers below are validation 2024 (191,459 complete rows), mean ± sd (n-1) over the 3 units.

| arm | macro-F1 | macro-F1 cross-fit | bal-acc | acc | Regular recall | Regular prec | Desf. recall | Desf. prec | rules | Jaccard |
|---|---|---|---|---|---|---|---|---|---|---|
| base (AT-041d) | 0.336 ± 0.011 | - | 0.399 ± 0.045 | 0.731 ± 0.018 | 0.329 ± 0.177 | 0.087 ± 0.027 | 0.069 ± 0.049 | 0.014 ± 0.003 | 13.7 | 0.151 |
| calib (idea 1) | 0.338 ± 0.011 | 0.335 ± 0.008 | 0.398 ± 0.036 | 0.733 ± 0.018 | 0.329 ± 0.199 | 0.096 ± 0.030 | 0.062 ± 0.049 | 0.015 ± 0.006 | 13.7 | 0.151 |
| natw (idea 2) | 0.336 ± 0.012 | - | 0.391 ± 0.047 | 0.740 ± 0.020 | 0.330 ± 0.190 | 0.087 ± 0.026 | 0.039 ± 0.039 | 0.013 ± 0.004 | 13.7 | 0.151 |
| natw_calib (2 then 1) | 0.339 ± 0.011 | 0.335 ± 0.008 | 0.396 ± 0.037 | 0.737 ± 0.017 | 0.322 ± 0.207 | 0.098 ± 0.032 | 0.062 ± 0.049 | 0.015 ± 0.007 | 13.7 | 0.151 |

* **Calibration does not help.** In-sample tuning gains +0.002 and the cross-fitted figure is 0.335, i.e. 0.001 below
  `base`. The tuner is not the limit: an exhaustive 16 x 16 x 16 log-grid over the three factors reaches +0.003, +0.002
  and +0.003 on seeds 0-2 against the identity, the same as the coordinate ascent. The factors it finds are scattered
  (seed 0: 0.75 / 0.75 / 0.13; seed 1: 1 / 0.56 / 0.32; seed 2: 2.4 / 0.24 / 1) with no consistent direction: the fitted
  winners are already close to the macro-F1 optimum of their rule set, and what limits macro-F1 is the rules (Regular
  precision 0.09, Desfavorable precision 0.014), not the way they are weighed.
* **Natural-prior weights do not help either, and they shrink the rare-class weights by one order of magnitude**
  (seed 0, its last six rules, one Razonablemente buena, three Regular and two Desfavorable: 0.007 / 0.002 / 0.001 /
  0.003 / 0.004 / 0.001 with the tempered sample against 0.0035 / 0.0001 / 0.0000 / 0.0002 / 0.0001 / 0.0000 with all
  training rows). Macro-F1 is unchanged (0.336); Desfavorable recall
  falls from 0.069 to 0.039. The ranking problem seen in the UI (a "Regular" rule with firing 1.0 losing to a weaker
  "Razonablemente buena" rule on weight 0.004 against 0.038) is therefore **not a performance problem**: a factor that
  would let the Regular rule win costs more precision than it gains recall. It is a readability problem of the
  inference (association = firing x class-prior-laden weight), which no re-weighting fixes; see section 8.
* The exported weights keep trace parity: `weight = score_raw x class_factor`, `association = firing x weight`
  (`tests/ml/test_calibration.py`), with `dominance_score_raw`, `class_factor` and `selection_frequency` as rule
  `metrics` (no contract change; `export_classifier_rules(rule_metrics=...)`).

## 3. Idea 3 (consensus rules) and idea 6 (restarts)

Pool: 3 disjoint seed sets (A 100-114, B 200-214, C 300-314), 15 fits each, a fresh class-aware 20,000-row draw per fit, 100
generations x 60 individuals, 60 rules x 4 antecedents, justified partitions (checked identical across fits). A pooled
fit has 17-19 rules and a single-fit validation macro-F1 of 0.307 / 0.313 / 0.314 (sd 0.009-0.015 within a set), below
the 0.336 of `base` because of the smaller budget.

| arm | macro-F1 | bal-acc | acc | Regular recall | Regular prec | Desf. recall | Desf. prec | rules | Jaccard of the procedure |
|---|---|---|---|---|---|---|---|---|---|
| base | 0.336 ± 0.011 | 0.399 ± 0.045 | 0.731 ± 0.018 | 0.329 ± 0.177 | 0.087 ± 0.027 | 0.069 ± 0.049 | 0.014 ± 0.003 | 13.7 | 0.151 |
| cons pi = 0.3 | 0.064 ± 0.004 | 0.149 ± 0.091 | 0.061 ± 0.039 | 0.241 ± 0.418 | 0.003 ± 0.005 | 0.000 | 0.000 | 1.7 | 0.167 |
| cons pi = 0.5 | no rule in sets A and B; not built | | | | | | | 0 / 0 / 1 | - |
| restart k = 5 (idea 6) | 0.328 ± 0.014 | 0.396 ± 0.027 | 0.727 ± 0.026 | 0.133 ± 0.035 | 0.080 ± 0.052 | 0.248 ± 0.080 | 0.014 ± 0.008 | 17.0 | 0.011 |
| restart k = 15 (idea 6) | 0.329 ± 0.013 | 0.418 ± 0.024 | 0.702 ± 0.025 | 0.282 ± 0.224 | 0.083 ± 0.049 | 0.199 ± 0.124 | 0.014 ± 0.008 | 15.7 | 0.023 |
| post-hoc: cons pi = 0.2 | 0.319 ± 0.005 | 0.336 ± 0.010 | 0.753 ± 0.004 | 0.161 ± 0.048 | 0.057 ± 0.011 | 0.014 ± 0.024 | 0.004 ± 0.007 | 11.7 | **0.409** |
| post-hoc: cons pi = 0.2 + factors | 0.319 ± 0.006 (cross-fit 0.318) | 0.337 ± 0.010 | 0.753 ± 0.006 | 0.162 ± 0.047 | 0.057 ± 0.011 | 0.016 ± 0.028 | 0.004 ± 0.008 | 11.7 | 0.409 |
| post-hoc: cons pi = 0.1 | 0.317 ± 0.007 | 0.337 ± 0.005 | 0.806 ± 0.009 | 0.132 ± 0.080 | 0.070 ± 0.014 | 0.088 ± 0.071 | 0.093 ± 0.136 | 35.0 | 0.281 |
| post-hoc: cons pi = 0.1 + factors | 0.324 ± 0.005 (cross-fit 0.322) | 0.343 ± 0.001 | 0.793 ± 0.018 | 0.161 ± 0.056 | 0.073 ± 0.011 | 0.069 ± 0.054 | 0.093 ± 0.136 | 35.0 | 0.281 |

| set | distinct rules in the pool | rules per fit | max selection frequency | rules kept at 0.5 / 0.3 / 0.2 / 0.1 |
|---|---|---|---|---|
| A | 208 | 17.2 | 0.47 | 0 / 2 / 11 / 31 |
| B | 215 | 17.7 | 0.40 | 0 / 1 / 10 / 36 |
| C | 222 | 19.0 | 0.53 | 1 / 2 / 14 / 38 |

* **The rule space is too large for exact-rule consensus.** Of ~260 rule slots per pool (15 fits x 17-19 rules), 208-222
  are distinct (antecedent set, class) pairs; the most frequent one appears in 40-53 % of the fits and almost none in 30 %
  or more. Stability selection as specified (pi 0.3 / 0.5) therefore returns almost nothing, and what it returns
  (`no2_last IS Buena THEN Buena`-type rules) predicts Buena only: macro-F1 0.064.
* With a lower, post-hoc threshold the consensus becomes usable and **much more stable as a procedure** (pairwise
  Jaccard between rule bases built from disjoint seed sets: 0.50 / 0.32 / 0.41 at pi = 0.2, against 0.03 / 0.18 / 0.24
  for single AT-041d fits), at a cost of 0.017 macro-F1 against `base` (0.319 against 0.336; but 0.008 above the mean
  of the single fits in its own pool, 0.311). It does not recover rare classes (Desfavorable recall 0.014).
  **Stable is not the same as meaningful**: the rules kept at pi = 0.2 include `no2_lag24h IS Buena THEN Regular` and
  `temperature IS High THEN Regular` (weights 0.0003 and 0.0002), which are GA artefacts that happen to recur, not
  explanations. The frequency says the search finds them repeatedly, not that they are right.
* **Restarts (idea 6) lower stability** (Jaccard 0.01-0.02 against 0.15) and do not raise macro-F1 (0.328-0.329): picking
  the best of 5 or 15 fits on validation selects a different rule base in each set (picked fits 100 / 203 / 304 for k = 5)
  and the winner's advantage on validation does not carry over to the mean of the sets.

## 4. Idea 5: extra inputs

`no2_trend_3h`, `no2_anomaly` and `station_type`; terms and rationale in `configs/ml/madrid_partitions_extra.json`
(6 ug/m3 half-width = the measurement-uncertainty scale already used for the NO2 terms, a threshold of scale and not of
significance); station types are the official `station_type_code` of `stations.geojson` (9 Tráfico, 12 Fondo urbano, 3
Suburbana; a station without a code raises). Anomaly reference: 576 station x local-hour cells (24 x 24) from the 1,051,200
training-period rows (the training split only, tested in `tests/ml/test_extra_features.py`). The complete-row set and the
training positions are identical to AT-041d (checked), so the arms are comparable row by row. Same fitting sample, shape,
budget and seeds as `base`.

| arm | macro-F1 | bal-acc | acc | Regular recall | Regular prec | Desf. recall | Desf. prec | rules | Jaccard |
|---|---|---|---|---|---|---|---|---|---|
| base | 0.336 ± 0.011 | 0.399 ± 0.045 | 0.731 ± 0.018 | 0.329 ± 0.177 | 0.087 ± 0.027 | 0.069 ± 0.049 | 0.014 ± 0.003 | 13.7 | 0.151 |
| + trend | 0.324 ± 0.003 | 0.395 ± 0.041 | 0.707 ± 0.036 | 0.356 ± 0.115 | 0.075 ± 0.014 | 0.065 ± 0.066 | 0.010 ± 0.011 | 17.7 | 0.008 |
| + anomaly | 0.328 ± 0.008 | 0.426 ± 0.016 | 0.684 ± 0.042 | 0.385 ± 0.100 | 0.069 ± 0.019 | 0.106 ± 0.038 | 0.011 ± 0.002 | 21.0 | 0.081 |
| + station type | 0.315 ± 0.018 | 0.409 ± 0.021 | 0.692 ± 0.061 | 0.353 ± 0.120 | 0.055 ± 0.024 | 0.157 ± 0.116 | 0.008 ± 0.001 | 15.3 | 0.022 |
| + all three | 0.335 ± 0.004 | 0.426 ± 0.024 | 0.697 ± 0.001 | 0.363 ± 0.053 | 0.084 ± 0.002 | 0.132 ± 0.049 | 0.013 ± 0.006 | 21.7 | 0.025 |

The GA does use the new inputs (anomaly appears in 29 % of the rules of the `+ all three` fits, trend and type in 14 % each)
but macro-F1 does not move (-0.001 with all three) and rule agreement across seeds drops from 0.15 to 0.03-0.08, because
the rule space grew. Control: HistGradientBoosting on the full training period scores 0.376 validation macro-F1 with the
nine AT-041d inputs and 0.379 with the three extra ones (+0.003): at hourly resolution and a 6 h horizon these inputs carry
almost no information beyond `no2_last`, `no2_lag*` and the hour. The inputs are readable and their leakage tests pass, so
they remain candidates for the table if a clinician or a map needs the vocabulary, not as a performance measure.
Publishing a model with them needs the three columns in the feature table (A1) and the anomaly reference as a data file.

## 5. Idea 4: ordinal decomposition (Frank and Hall)

Three binary winning-rule classifiers (NO2 > 40, > 90, > 120 ug/m3), each fitted like `base` (30,000 rows, class-aware
power 0.5, 60 x 4, 150 x 60, seeds 0-2). Single binary validation macro-F1: 0.60-0.63 (> 40), 0.53-0.57 (> 90), 0.50-0.51
(> 120); 8-16 rules each (38 in total on average). `highest` is the primary combiner, `count` the variant; calibrated
variants tune one factor per threshold on the "exceeded" side.

| variant | macro-F1 | macro-F1 cross-fit | bal-acc | acc | Regular recall | Regular prec | Desf. recall | Desf. prec | MAE class | off by 2+ | inconsistent patterns |
|---|---|---|---|---|---|---|---|---|---|---|---|
| base (4-class, for reference) | 0.336 ± 0.011 | - | 0.399 ± 0.045 | 0.731 ± 0.018 | 0.329 ± 0.177 | 0.087 ± 0.027 | 0.069 ± 0.049 | 0.014 ± 0.003 | 0.304 ± 0.044 | 0.033 ± 0.026 | - |
| raw, highest | 0.313 ± 0.008 | - | 0.412 ± 0.040 | 0.715 ± 0.011 | 0.190 ± 0.130 | 0.046 ± 0.007 | 0.310 ± 0.080 | 0.010 ± 0.002 | 0.347 ± 0.043 | 0.052 ± 0.027 | 0.027 ± 0.040 |
| raw, count | 0.320 ± 0.009 | - | 0.402 ± 0.026 | 0.721 ± 0.004 | 0.146 ± 0.054 | 0.060 ± 0.017 | 0.275 ± 0.071 | 0.012 ± 0.003 | 0.321 ± 0.006 | 0.033 ± 0.002 | 0.027 ± 0.040 |
| factors, highest | 0.319 ± 0.012 | 0.318 ± 0.011 | 0.396 ± 0.035 | 0.744 ± 0.022 | 0.171 ± 0.057 | 0.053 ± 0.018 | 0.259 ± 0.100 | 0.010 ± 0.002 | 0.309 ± 0.050 | 0.043 ± 0.023 | 0.028 ± 0.032 |
| factors, count | 0.328 ± 0.008 | 0.326 ± 0.008 | 0.387 ± 0.023 | 0.754 ± 0.007 | 0.162 ± 0.047 | 0.074 ± 0.010 | 0.208 ± 0.042 | 0.013 ± 0.003 | 0.276 ± 0.010 | 0.025 ± 0.003 | 0.034 ± 0.040 |

The inconsistency rate is low on average (2.7-3.4 % of rows) but very uneven: 7.3 %, 0.7 % and 0.2 % of the rows for seeds 0, 1, 2 (raw), i.e. one seed's binary classifiers contradict each other far more than the others and the share of rows
with at least one threshold deciding nothing is 1.0 %. The decomposition **does not win** (best 0.326 cross-fitted against
0.336): it raises Desfavorable recall (0.21-0.31 against 0.07) and lowers Regular recall, at a Desfavorable precision of 1 %.
It is therefore not proposed for publication and no contract change is requested. If a later experiment makes it win,
what the contract would need is in section 8.

## 6. Decision (rule of section 0, applied by `python -m atlas.ml.experiment_ica3 decide`)

No isolated idea entered the combination (`enters: []`): calibration and natural weights are -0.001 cross-fitted, the
consensus at pi 0.3 is -0.27, restarts and every extra-input arm are below `base` or less stable than it. The best
eligible arm is `base` and its margin criterion holds trivially, so **the final choice is `base`: the AT-041d model stays
and nothing new is proposed for publication.** The combination was therefore empty by rule, not skipped for budget. No
`ica3-*` run directory is proposed.

For completeness (not selected, post-hoc): the three run directories of `posthoc_cons_p20` exist for inspection at
`artifacts/madrid_no2_h6/ica3-posthoc_cons_p20-set{A,B,C}` (valid `rules.json` with `selection_frequency`,
`dominance_score_raw` and `class_factor` as rule metrics, `metrics.json`, `predictions.parquet`, `model.pkl`).
They are **not recommended for publication**: see the caveat on meaningless recurrent rules in section 3.

## 7. Test 2025 (read once; 180,326 complete rows)

`base` rescored reproduces AT-041d (0.3291 / 0.3133 / 0.3296). Baselines are copied from AT-041d (`summary.json`).

| model | macro-F1 | bal-acc | acc | Regular recall | Regular prec | Desf. recall | Desf. prec |
|---|---|---|---|---|---|---|---|
| ExFuzzy `base` (AT-041d), 3 seeds | 0.324 ± 0.009 | 0.403 ± 0.041 | 0.736 ± 0.034 | 0.253 ± 0.212 | 0.052 ± 0.011 | 0.156 ± 0.019 | 0.014 ± 0.004 |
| ExFuzzy consensus pi = 0.2 (post-hoc, information only), 3 sets | 0.321 ± 0.006 | 0.348 ± 0.018 | 0.771 ± 0.005 | 0.162 ± 0.026 | 0.045 ± 0.009 | 0.045 ± 0.078 | 0.006 ± 0.010 |
| persistence | 0.294 | 0.294 | 0.769 | 0.020 | 0.019 | 0.000 | 0.000 |
| logistic regression (full / 30k rows) | 0.303 / 0.348 | 0.295 / 0.384 | 0.839 / 0.809 | 0.024 / 0.115 | 0.254 / 0.116 | 0.037 / 0.198 | 0.036 / 0.019 |
| random forest (full / 30k rows) | 0.374 / 0.394 | 0.361 / 0.464 | 0.853 / 0.820 | 0.012 / 0.232 | 0.444 / 0.134 | 0.086 / 0.259 | 0.101 / 0.025 |
| random forest balanced (full / 30k rows) | 0.371 / 0.347 | 0.614 / 0.624 | 0.752 / 0.725 | 0.583 / 0.515 | 0.075 / 0.058 | 0.531 / 0.704 | 0.025 / 0.011 |
| HGB (full / 30k rows) | 0.373 / 0.383 | 0.396 / 0.493 | 0.845 / 0.798 | 0.029 / 0.308 | 0.149 / 0.098 | 0.160 / 0.284 | 0.022 / 0.015 |
| HGB regression then binned | 0.414 | 0.406 | 0.836 | 0.102 | 0.289 | 0.074 | 0.105 |

**ExFuzzy still trails the tree ensembles.** Against the models trained on the same 30,000 rows it is 0.07 below random forest
(0.324 against 0.394) and 0.06 below HGB (0.383); against the full-period ones, 0.05 below RF and HGB (0.374 / 0.373) and
0.09 below HGB regression-then-binned (0.414). It is above persistence (+0.03) and above logistic regression on all rows
(+0.02), and 0.02 below logistic regression on the 30k subsample. None of the ideas of this report changes that ordering.
The class-balanced forests detect rare classes far better (Regular recall 0.52-0.58, Desfavorable 0.53-0.70, balanced accuracy
0.61-0.62 against 0.40) but with precision of 6-8 % and 1-3 %; with F1 per class that does not pay.

## 8. Upstream candidates (ex-fuzzy PR, later; none is needed by Atlas today)

| candidate | generic? | evidence here | verdict |
|---|---|---|---|
| `stability` / consensus module: selection frequency per (antecedent set, class), `MasterRuleBase` from the kept rules, procedure-level Jaccard | yes, only the public rule classes are used (`atlas.ml.consensus`) | it measures and raises the stability of the procedure (0.15 -> 0.41 at pi 0.2) but needs a threshold far below the textbook 0.3-0.5 and keeps recurrent meaningless rules | worth upstreaming as a **diagnostic** (frequency table, procedure Jaccard), not as a recipe that improves accuracy. ex-fuzzy already has `pattern_stability` (multi-run pattern counts); a PR should extend it rather than add a second module |
| per-class factor calibration folded into the rule weights (`atlas.ml.calibration`) | yes | +0.002 in-sample, -0.001 cross-fitted on this task | **do not upstream as an improvement.** A `rescore(X, y)` helper on a fitted `MasterRuleBase` (a wrapper over `evalRuleBase.add_rule_weights`) is the only generic part and is a convenience |
| ordinal wrapper (Frank and Hall with winning-rule classifiers, `atlas.ml.ordinal`) | yes | does not win here (best 0.326 against 0.336); inconsistency 2.7-3.4 % | not now. A generic wrapper is a few lines; the value is the combiner and the inconsistency report |
| `association = firing x weight` with class-prior-laden weights (the cause of the UI ranking surprise) | library design | natural-prior weights are 10x smaller for rare classes; macro-F1 unchanged | the useful upstream discussion: a prior-free score for **display** (for example a rule's firing and its confidence, shown separately, never the product) while inference keeps the dominance score; no accuracy claim |

Contract note for ordinal decomposition, **only if it ever wins and A0 wants it** (not requested now): it needs a new
`InferenceFamily` (for example `ordinal_winning_rule_classifier`) whose `RuleTrace` holds K-1 sub-decisions, each with its
own `winning_rule_id`, its `exceeds: bool | None` (None: no rule fired), the threshold and its unit, and the combiner name
(`highest`) with an `inconsistent: bool` flag; rules would carry `Consequent(type="threshold", threshold=90, unit="ug/m3",
exceeds=true)` and read "IF ... THEN supera 90 ug/m3"; `rule_id` would need the threshold as a prefix (`T90-R03`) to stay
unique; the class label would be derived, not predicted.

## 9. Reproduce

Environment: `export ATLAS_DATA_DIR=.../exfuzzy-atlas/data ATLAS_ARTIFACTS_DIR=.../exfuzzy-atlas/artifacts PYTHONPATH=src`.
The stages are resumable and write to `artifacts/madrid_no2_h6/experiments/ica3/`.

```
python -m atlas.ml.experiment_ica3 base|calib|natw  --config configs/ml/madrid_no2_h6_ica3_experiment.json   # seconds
python -m atlas.ml.experiment_ica3 pool             --config ...    # 45 fits, ~34 min, RSS 1.2 GB
python -m atlas.ml.experiment_ica3 consensus|restarts --config ...  # ~2 min
python -m atlas.ml.experiment_ica3 features         --config ...    # 12 fits, ~30 min, RSS 1.6 GB
python -m atlas.ml.experiment_ica3 ordinal          --config ...    # 9 fits, ~14 min
python -m atlas.ml.experiment_ica3 control|report|decide --config ...
python -m atlas.ml.experiment_ica3 final --test --config ...        # once; refuses a second run
```

Budget used: about 85 minutes of single-process CPU (the node was shared with A4b), peak RSS 1.6 GB. Tests:
`tests/ml/test_calibration.py`, `test_consensus.py`, `test_ordinal.py`, `test_extra_features.py`, `test_ica3_report.py`.

## 10. Limits

* One time split and one year of validation; seed sd is 0.011 for `base`, so differences below ~0.02 are not resolved.
* Consensus fits use a smaller budget (20,000 rows, 100 generations) than `base`; a pool at the full budget might shift the
  absolute macro-F1 of the consensus (not the frequency problem).
* The post-hoc thresholds were chosen after seeing pi 0.3 / 0.5 fail; the pi = 0.2 / 0.1 results are exploratory.
* The 6 ug/m3 half-width of the trend and anomaly terms is a scale, not a validated threshold; other widths were not tried.
* The cross-fitted score splits validation by ISO-week parity; neighbouring weeks are correlated, so it is optimistic for
  the calibrated arms, which only strengthens the "no gain" conclusion.
* Firing, association and weights are degrees of rule match; no probability, causal or clinical claim is made.
