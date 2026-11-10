# Retraining with the fixed ex_fuzzy (FX): mixed term counts, unique antecedents, richer hour vocabularies

**Status: fitted on an unreleased build; Water `unique` is published (decision of the author, 2026-10-31).** The experiments
use a local ex_fuzzy build, not the 3.3.1 pinned for serving. The upstream PRs will take time to review, so until a release
exists Atlas uses the local build for fitting and may publish models fitted on it; the main Python environment, `make test`, `make lint`
and CI stay on the PyPI 3.3.1, and the build is used only through `PYTHONPATH` (`EXFUZZY_SRC` in the Makefile; how to rebuild it
is in `docs/reproduce.md`). Of the experiments below only Water `unique` was published (section 2); the Madrid and NYC
results are "no gain" and their models stay unpublished. Every manifest, `selection.json` and summary written with the build states

> `exfuzzy_source = "local atlas/local-integration @ 2ffcfb9 (3.3.1 + PRs #27 #29 #31 #32)"`

(`hyperparameters.exfuzzy_source`, a manifest warning, and the key `exfuzzy_source` of the summary files). Note that
`ex_fuzzy.__version__` of that build still says `3.3.1`, so the version string proves nothing; the code detects what the
library does (`atlas.ml.exfuzzy_features`). Since 2026-10-31 a model fitted on a git checkout of ex_fuzzy also records the
commit in `exfuzzy_version` (`3.3.1+g2ffcfb9`, `.dirty` if the checkout has local changes), see `exfuzzy_version()`.
The runs of the first FX session (before that change) carry plain `3.3.1`; the Water `unique` runs were refitted
(section 2, "Publication").

**Follow-up (2026-10-31).** The "proportional remap" test suggested in section 1 was run as FX2 on a build with ex_fuzzy PR 35
(`docs/ml/fx2_proportional_remap.md`): same arms and rules, no arm enters, the answer stays "no gain".

**What this is not.** Same limits as AT-041c/d/e/f: firing, association degree and rule weight are degrees of rule match,
never probabilities, contributions or risk; a term named after a source ("Punta de tarde") says how the input was split,
not that the rule explains anything; no causal, clinical, sanitary or regulatory claim; no real-time claim.

## Summary and recommendations

| # | Experiment | Result against the pre-registered rule | Recommendation |
|---|---|---|---|
| 1 | Madrid ICA, hour in 5 periods (PR 32) | the rules do use the fifth term (3.3.1: never), but validation macro-F1 is 0.319 (`h5_fix`) and 0.335 (`h5_sel`) against 0.336, Jaccard 0.015 / 0.090 against 0.151; the 3.3.1 control scores 0.322 | **no gain**; AT-041d stays |
| 2 | Water TSK, `unique_antecedents` (PR 30) | 0 duplicates, validation RMSE 0.942 against 0.916 (limit +0.03), test RMSE 0.938 against 0.922; `sufficient` 1.156 | `unique`: **publish** (readability only, about +0.015 mg/l RMSE); published 2026-10-31 on the local build; `sufficient`: no gain |
| 3 | NYC, hour in 5 or 6 periods (PR 32) | the added evening terms are used by no rule; macro-F1 0.366 / 0.399 (`h5`), 0.387 (`h6`) against 0.382 and persistence 0.401 | **no gain**; the published NYC model stays |
| 4 | `construct_breakpoint_partition` (PR 31) | identical trapezoids only for the whole-hour and weekday variables; 0.44-0.49 membership difference for the ICA, Beaufort, percentile and season terms (different family) | keep `atlas.ml.partitions`; no switch |

Common to all: the integration build reproduces the published fits bit-for-bit where the term counts are not mixed
(AT-041d 60 x 4 seed 0; the three NYC seeds and their rules; the whole Water shape selection and the three Water seeds,
duplicates included), so the differences above are due to the changed arms. Only one test period was read (Water `unique`). Everything fitted on the build carries its provenance until a release is pinned.

## 0. Protocol and decision rules (written and committed before any fit of the FX arms)

History, for honesty. Before this section was written the author knew the published numbers of the three existing
models (the docs `madrid_no2_h6_ica_v2.md`, `v3.md`, `nyc_pickups_h1_level_ica.md`, `water_uk_do_regression.md`) and
the upstream PR descriptions, and had run the test suite of `tests/ml` on the integration build (it passes, 171 tests).
No fit of an FX arm had been run, and no validation or test number of one had been seen.

**Build.** Experiments run with `PYTHONPATH=/path/to/ex-fuzzy:src`
(`python -c 'import ex_fuzzy; print(ex_fuzzy.__file__)'` is checked in the log); the main environment is untouched and
`make test` / `make lint` run on the pinned 3.3.1. Experiment configs name what they need (`requires_exfuzzy`:
`term_bound_fix`, `unique_antecedents`); on the pinned library they refuse to run with a clear
`ExFuzzyFeatureError`, and `FuzzyParams(unique_antecedents=True)` does the same. One control arm (Madrid 5-term hour on
the pinned 3.3.1, no requirement, no `exfuzzy_source`) isolates the effect of the library fix from that of the vocabulary.

**Common.** Splits, rows, class merge, fitting subsample, budget (150 generations x 60 individuals), dominance-score
weights and 3 seeds (0, 1, 2) are those of the existing docs. Decisions use **validation only**. A test period is read
only for an arm that satisfies the decision rule of its experiment, once, for its 3 seeds in one command; baselines are
those already published (same rows and splits, not refitted). If no arm qualifies, no test row is read for that
experiment and the answer is "no gain".

### Experiment 1: Madrid NO2 t+6 h, ICA, hour in 5 periods

* Arms (all `justified` partitions of AT-041d except where stated; NO2 inputs 4 terms, wind 4 Beaufort groups, weekday 3,
  temperature and humidity 3 quantile terms):
  * `base`: AT-041d as published (4-term hour). Its per-seed validation macro-F1 is 0.3481 / 0.3287 / 0.3310 (mean 0.336,
    sd 0.011), rule-set Jaccard 0.151. A **reproduction** of seed 0 on the integration build (`fx-m4-repro`, 60 x 4)
    must give 0.3481: for equal or capped term counts the fix is bit-for-bit upstream, and this is checked here.
  * `h5`: hour in five periods, `configs/ml/madrid_partitions_hour5.json`: Noche 0-6, Punta de mañana 7-9, Mediodía 10-16,
    Punta de tarde 17-19, Noche tardía 20-23. The cuts are those of the AT-041d rationale (evening rush 17-19, "after
    19 the profile declines"); none is tuned. Two protocols: `h5_fix` (shape 60 x 4 of AT-041d, seeds 0-2, run
    `fx-m5-fix`) and `h5_sel` (the AT-041d protocol: six shapes, one fit each with seed 0, best validation macro-F1,
    then seeds 0-2 of that shape, run `fx-m5-sel`).
  * `h5_ctrl`: `h5_fix` on the pinned 3.3.1 (run `fx-m5-ctrl`).
* First, a **term-index check**: for every fitted `h5` model, the number of antecedents that use each term of each
  variable (`atlas.ml.fx_checks.classifier_term_usage`), and the bound of the term genes on both builds
  (`exfuzzy_features.has_term_bound_fix`). Expected: on 3.3.1 the term "Noche tardía" (index 4) is never used; on the
  integration build it can be.
* Reported (validation 2024, all complete rows, mean +- sd with n-1 over the seeds): macro-F1, balanced accuracy,
  accuracy, Regular and Desfavorable recall and precision, rules kept, mean pairwise Jaccard of the
  `(antecedent set, class)` rules.
* Rule (that of `madrid_no2_h6_ica_v3.md`, section 0): an `h5` protocol **enters** if its mean validation macro-F1 is at
  least 0.011 above `base` (one seed sd of `base`), or its Jaccard is at least 0.05 above `base` while its macro-F1 is not
  more than 0.011 below. "Publish after release" requires **both** `h5_fix` and `h5_sel` to enter; otherwise "no gain".

### Experiment 2: Water dissolved oxygen, TSK, `unique_antecedents`

* Chronological split with water temperature, the published arm (`water_uk_do_regression.md`): 9 shapes (10/20/40 rules x
  2/3/4 antecedents), one fit each with seed 0, lowest validation RMSE, then 3 seeds. Arms: `base` (additive, as
  published, refitted on the integration build: `fx-w-base`; the published validation RMSE of the seeds is 0.907 / 0.914
  / 0.927, mean 0.916), `unique` (additive, `unique_antecedents=True`: `fx-w-unique`), `unique_sufficient`
  (`rule_mode="sufficient"`, `unique_antecedents=True`: `fx-w-unique-suf`).
* Reported (validation 2022-2023): MAE, RMSE, R2; readability of each fitted rule set: rules, distinct antecedent
  sets, duplicates (rules that repeat an earlier antecedent set), mean length, consequent range, and
  **implausible consequents**: for each rule, the rows of the training period where its raw firing is at least 0.5 and
  the 5 % and 95 % quantiles of the observed DO on them; a rule is `outside` if its consequent is not between them and
  `no_support` if fewer than 30 rows fire it (`atlas.ml.fx_checks.consequent_support`). In an additive TSK a
  consequent is not the mean of its rows, so this flags rules that are hard to read alone, not a wrong model. The
  single-antecedent season rules (the "Verano -> 1.2 mg/l" case of the published seed) are listed explicitly.
* Rule: an arm is **readable enough to publish after release** if its mean validation RMSE is within 0.03 mg/l of the
  `base` mean (about three seed sd), it has 0 duplicates in every seed, and it has no more `outside` rules than `base`
  on average. `sufficient` is judged by the same rule. Among arms that pass, the lowest validation RMSE; ties
  (within 0.01) go to the arm with fewer rules. If none passes: "no gain".

### Experiment 3: NYC demand level, larger hour vocabulary

* Task, rows, split, feature set `rel7`, budget as `nyc_pickups_h1_level_ica.md`. Arms: `h4` (the published vocabulary
  refitted on the integration build, `fx-n4-fix`, shape 30 x 2, seeds 0-2: the published validation macro-F1 of the seeds
  is 0.398 / 0.387 / 0.361), `h5` (`configs/ml/nyc_partitions_hour5.json`: Madrugada 0-6, Mañana 7-10, Mediodía 11-14,
  Tarde 15-21, Noche 22-23) and `h6` (`nyc_partitions_hour6.json`: Madrugada 0-6, Mañana 7-10, Mediodía 11-14, Tarde
  15-16, Punta de tarde 17-19, Noche 20-23). The cuts are fixed from the profile text of that doc, not tuned. For
  each vocabulary two protocols: `_fix` (shape 30 x 2 of the published model, runs `fx-n5-fix`, `fx-n6-fix`) and `_sel`
  (six shapes with seed 0, then 3 seeds, runs `fx-n5-sel`, `fx-n6-sel`).
* Reported (validation 2025-01): macro-F1, balanced accuracy, accuracy, rules; level persistence (0.401 macro-F1 on
  validation) and the published baselines; and whether any rule uses `local_hour` or `local_dow`
  (`classifier_term_usage`), and which terms.
* Rule: a vocabulary **enters** if (a) its mean validation macro-F1 is at least 0.019 above the `h4` mean on the same
  protocol (one seed sd of the published model) **and** above the persistence 0.401, and (b) at least two of three seeds
  have a rule using `local_hour` or `local_dow`. "Publish after release" requires both protocols to enter.

### Experiment 4 (optional): `construct_breakpoint_partition`

* For each fixed variable of `madrid_partitions.json`, `nyc_partitions.json` and `water_partitions.json`, the closest
  `utils.construct_breakpoint_partition` (breakpoint = midpoint between the core of a band and the next; ramp width =
  scale x (shoulder + gap), best scale on 0.05..4) and the maximum membership difference to the Atlas trapezoids
  (`atlas.ml.fx_checks.breakpoint_parity`). Parity means identical parameters. Code is **not** switched over.

### Budget

At most 2.5 h of CPU, at most 4 threads, RSS below 2 GB, fits run sequentially.

## 1. Experiment 1: Madrid NO2 t+6 h with the hour in five periods (validation 2024, 191,459 complete rows)

**Reproduction first.** `fx-m4-repro` (the AT-041d `justified` partitions, shape 60 x 4, seed 0) on the integration build
gives validation macro-F1 0.3480715 with the same confusion matrix and 15 rules as the AT-041d fit (0.3480715): bit-for-bit,
as the upstream PR 32 states for capped term counts. Everything below that differs from `base` therefore comes from the
vocabulary or from the changed bound, not from the other merged PRs.

**The bound, measured on the Madrid configuration** (the nine inputs with 4, 4, 4, 4, 4, 3, 3, **5**, 3 terms, 60 rules x
4 antecedents; upper bound of every term gene of `FitRuleBase`):

| ex_fuzzy | upper bound of the term genes | meaning |
|---|---|---|
| 3.3.1 (pinned) | 3 in every slot | the fifth term of the hour (index 4) cannot be drawn: the AT-041d limit |
| integration build | 4 in every slot | all five terms reachable; the 4-term variables now also receive index 4, which the decoder clips to their last term |

**Term usage** (antecedents per term over the three seeds, `classifier_term_usage`; only the hour is shown, the other
inputs have no unreachable terms):

| arm | Noche | Punta de mañana | Mediodía | Punta de tarde (or Tarde-noche) | Noche tardía | rules with an hour antecedent, per seed |
|---|---|---|---|---|---|---|
| `base` (AT-041d, 4 terms) | 5 | 3 | 4 | 1 (Tarde-noche) | - | 4 / 5 / 4 |
| `h5_ctrl` (5 terms on 3.3.1) | 3 | 4 | 5 | 2 | **0** | |
| `h5_fix` (5 terms, integration) | 6 | 6 | 5 | 4 | **3** (one per seed) | 12 / 4 / 8 |
| `h5_sel` (5 terms, integration) | 4 | 2 | 3 | 0 | **4** (2, 2, 0) | 4 / 5 / 4 |

So the answer to "do the rules now use terms beyond the first `nAnts` features' term counts" is **yes**: on 3.3.1 the
fifth hour term is used by no rule of any seed (it cannot be), on the integration build every seed of `h5_fix` and two of
three seeds of `h5_sel` use it.

**Validation, mean ± sd (n - 1) over seeds 0, 1, 2** (`python -m atlas.ml.report_fx madrid ...`):

| arm | shape | macro-F1 | bal-acc | acc | Regular recall / prec | Desf. recall / prec | rules | Jaccard | macro-F1 by seed |
|---|---|---|---|---|---|---|---|---|---|
| `base` (AT-041d, 4-term hour) | 60 x 4 | 0.336 ± 0.011 | 0.399 ± 0.045 | 0.731 ± 0.018 | 0.329 / 0.087 | 0.069 / 0.014 | 13.7 | 0.151 | 0.348, 0.329, 0.331 |
| `h5_ctrl` (5 terms, pinned 3.3.1) | 60 x 4 | 0.322 ± 0.022 | 0.418 ± 0.043 | 0.691 ± 0.068 | 0.436 / 0.077 | 0.097 / 0.012 | 14.7 | 0.086 | 0.335, 0.297, 0.336 |
| `h5_fix` (5 terms, integration) | 60 x 4 | 0.319 ± 0.004 | 0.407 ± 0.062 | 0.698 ± 0.042 | 0.322 / 0.051 | 0.139 / 0.017 | 19.7 | 0.015 | 0.323, 0.318, 0.315 |
| `h5_sel` (5 terms, integration, own shape) | 30 x 4 | 0.335 ± 0.004 | 0.400 ± 0.047 | 0.723 ± 0.040 | 0.191 / 0.105 | 0.243 / 0.023 | 10.3 | 0.090 | 0.333, 0.340, 0.333 |

Shape selection of `h5_sel` (seed 0, validation macro-F1): 30x2 0.310, 30x3 0.314, 30x4 **0.333**, 60x2 0.323, 60x3 0.326,
60x4 0.323 (AT-041d had picked 60 x 4 at 0.348; single-seed selection is noisy, so the two protocols land on different
shapes). Fit time 36-185 s per fit, RSS below 0.9 GB.

Reading, without over-reading:

* **No gain in macro-F1.** `h5_fix` is 0.017 below `base` (more than one seed sd), `h5_sel` equals it (-0.001), and the 3.3.1
  control with the same vocabulary scores 0.322, i.e. the library fix itself moves macro-F1 by -0.003 (inside the
  control's own sd of 0.022). The extra term is used, but using it does not make the model better on this task.
* **A different trade-off, not a better one.** `h5_sel` has Desfavorable recall 0.243 against 0.069 and Regular precision
  0.105 against 0.087, but Regular recall 0.191 against 0.329, and the same macro-F1; the Desfavorable precision stays at
  2 %. Its rule "IF valid_hour_local IS Noche tardía THEN ICA = Desfavorable o peor" is an association of the 20-23 h
  hours in the 2019-2023 sample with a rare class, not an explanation.
* **Less stable.** The rule-set Jaccard falls from 0.151 to 0.015 (`h5_fix`) and 0.090 (`h5_sel`): a larger rule space with
  the same budget and three seeds.
* **A confound the fix leaves in place.** The new bound makes every term gene range over 0..4 for all inputs, and the
  decoder clips an index above a variable's term count to its last term. Under a uniform draw the last NO2 band
  ("Desfavorable o peor") is therefore reached by two gene values (3 and 4) instead of one, i.e. it is twice as likely as
  any other band of that input, and the last term of a three-term input (temperature, humidity, weekday) by three values
  (2, 3, 4) instead of two. This is the "residual skew" that PR 32 describes. It may explain part of the drop of `h5_fix`
  (rare-class terms drawn more often); it cannot be separated from the vocabulary effect with these arms (a
  proportional remap upstream would be the clean test).

**Rules of `h5_sel`, seed 1 (best validation macro-F1 of its three seeds, 11 rules; not recommended for publication):**

* IF no2_lag3h IS Buena AND temperature IS Medium AND valid_hour_local IS Mediodía THEN ICA = Buena (peso 0.0619)
* IF no2_last IS Buena AND no2_lag3h IS Buena THEN ICA = Buena (peso 0.276)
* IF no2_last IS Buena AND valid_hour_local IS Noche THEN ICA = Buena (peso 0.1)
* IF no2_lag3h IS Desfavorable o peor AND relative_humidity IS Low THEN ICA = Razonablemente buena (peso 0.000525)
* IF wind_speed IS Brisa ligera AND relative_humidity IS Medium THEN ICA = Razonablemente buena (peso 0.00667)
* IF no2_lag1h IS Razonablemente buena AND temperature IS High THEN ICA = Razonablemente buena (peso 0.0042)
* IF relative_humidity IS High THEN ICA = Razonablemente buena (peso 0.0363)
* IF valid_hour_local IS Noche THEN ICA = Razonablemente buena (peso 0.0184)
* IF no2_lag24h IS Buena AND valid_hour_local IS Noche tardía THEN ICA = Regular (peso 0.00712)
* IF wind_speed IS Calma-ventolina AND temperature IS Low THEN ICA = Regular (peso 0.00299)
* IF valid_hour_local IS Noche tardía THEN ICA = Desfavorable o peor (peso 0.00653)

**Decision (rule of section 0).** Neither protocol enters: `h5_fix` is 0.017 below `base` and `h5_sel` 0.001 below, and
the Jaccard criterion (at least +0.05) fails for both (-0.136, -0.061). **Recommendation: no gain. The AT-041d model
stays.** No test row was read for Madrid. The AT-041d baselines (HGB 0.383, random forest 0.394 on the same 30,000 rows)
remain 0.05-0.06 above any of these.

## 2. Experiment 2: Water dissolved oxygen, `unique_antecedents` (chronological split, with temperature)

Rows: train 7,862, validation 1,726 (2022-2023). Same inputs, partitions, budget (150 x 60), 9 shapes (seed 0) and seeds
(0, 1, 2) as `water_uk_do_regression.md`. **Reproduction:** `fx-w-base` (additive, no `unique_antecedents`) on the
integration build selects the same shape (40 x 2) and gives the published per-seed validation RMSE 0.907 / 0.914 / 0.927,
the same 39 / 37 / 39 rules and the same 12 / 9 / 11 repeated antecedent sets as the published seeds (bit-for-bit).

**Validation, mean ± sd (n - 1) over seeds** (`python -m atlas.ml.report_fx water ...`). Readability columns are per seed
(0 / 1 / 2). "Outside" counts the rules whose consequent is not between the 5 % and 95 % quantiles of the observed DO of
the training rows that fire the rule at 0.5 or more (the check of section 0; additive consequents are not meant to be
the mean of their rows, so many rules fall outside even in a good model).

| arm | shape | val RMSE | val MAE | val R2 | rules | distinct antecedent sets | duplicates | consequent outside | no support |
|---|---|---|---|---|---|---|---|---|---|
| `base` (additive, as published) | 40 x 2 | 0.916 ± 0.010 | 0.611 ± 0.012 | 0.698 ± 0.007 | 39 / 37 / 39 | 27 / 28 / 28 | 12 / 9 / 11 | 27 / 23 / 29 | 0 / 2 / 0 |
| `unique` (additive, `unique_antecedents=True`) | 40 x 2 | 0.942 ± 0.020 | 0.627 ± 0.011 | 0.681 ± 0.014 | 39 / 35 / 29 | 39 / 35 / 29 | **0 / 0 / 0** | 24 / 20 / 15 | 0 / 0 / 0 |
| `unique_sufficient` (`rule_mode="sufficient"`) | 20 x 4 | 1.156 ± 0.136 | 0.822 ± 0.143 | 0.515 ± 0.117 | 19 / 17 / 17 | 19 / 17 / 17 | 0 / 0 / 0 | 3 / 7 / 4 | 4 / 0 / 0 |

Per-seed validation RMSE: `base` 0.907, 0.914, 0.927; `unique` 0.925, 0.938, 0.964; `unique_sufficient` 1.052, 1.310, 1.105.
Validation baselines (identical on both builds): ridge 0.992, random forest 0.799, histogram gradient boosting 0.800,
quadratic in temperature 1.011. Rule-set Jaccard across seeds: 0.268 (`base`), 0.321 (`unique`), 0.105 (`unique_sufficient`).
Shape selection of `unique` (validation RMSE): 40 x 2 0.925, 20 x 4 0.938, 40 x 3 0.959, 20 x 3 0.966, 10 x 2 and 20 x 2
0.970, 40 x 4 0.987, 10 x 4 1.028, 10 x 3 1.052. Fit time 34-41 s per seed, RSS below 0.4 GB.

Reading:

* **Duplicates are gone and the cost is small.** `unique` has 0 repeated antecedent sets in every seed (the library
  option works as described in PR 30) and loses 0.026 mg/l of validation RMSE (0.916 to 0.942, R2 0.698 to 0.681), within
  the 0.03 mg/l of the decision rule but by a narrow margin (the seed sd of `unique` is 0.020). The model keeps 29-39 rules
  that are all distinct, against 27-28 distinct antecedent sets hidden in 37-39 rules for `base`.
* **The "Verano -> 1.2 mg/l" rule is gone, but the compensating consequents are not.** The published seed 0 had two
  rules on exactly `days_from_midwinter IS Verano`, 1.198 and 18.62 mg/l. `unique` seed 0 has one rule per season term
  (Invierno 10.80, Primavera-otoño 6.35), none for Verano, and none is as extreme. But extremes remain where several rules
  overlap: in the listing below `water_temperature IS Low -> 18.62` and `water_temperature IS High -> 2.80` are read
  against an observed DO of 7-14 mg/l for the rows they cover (`outside`). That is the additive TSK, `Σ f c / Σ f`: the
  consequents are offsets that cancel each other. `unique_antecedents` removes the literal repeats; it does not make a
  rule a local mean.
* **`rule_mode="sufficient"` is readable but not usable.** Only the best-matching rule speaks, so the consequents
  stay in the range of the rows they cover (3-7 of 17-19 rules outside, against 15-29 of 29-39) and the model is half
  the size, but validation RMSE rises to 1.156 ± 0.136 (+0.24, worse than the quadratic in temperature, 1.011, and
  than ridge, 0.992) and the seeds disagree (1.05 to 1.31; Jaccard 0.105). It fails the 0.03 mg/l rule by a wide margin.

**All 39 rules of `unique`, seed 0** (lowest validation RMSE, 0.925; consequent in mg/l; n = training rows with firing
at least 0.5, [5 %, 95 %] quantiles of the observed DO on them):

| rule | text | n | covered range | status |
|---|---|---|---|---|
| R01 | IF ammoniacal_nitrogen IS Medio>L AND ph IS Low THEN DO = 5.998 | 287 | 6.3 - 13.6 | outside |
| R02 | IF water_temperature IS Medium AND days_from_midwinter IS Primavera-otoño THEN DO = 12.22 | 2236 | 9.2 - 12.9 | within |
| R03 | IF ph IS Medium THEN DO = 14.36 | 3310 | 8.6 - 13.8 | outside |
| R04 | IF orthophosphate_reactive IS <=L AND local_hour IS Low THEN DO = 9.910 | 900 | 9.2 - 13.9 | within |
| R05 | IF water_temperature IS Low AND ph IS Low THEN DO = 14.53 | 830 | 11.1 - 14.3 | outside |
| R06 | IF ammoniacal_nitrogen IS Medio>L AND water_temperature IS High THEN DO = 2.620 | 371 | 6.7 - 10.9 | outside |
| R07 | IF ammoniacal_nitrogen IS Alto>L THEN DO = 9.910 | 695 | 4.6 - 13.3 | within |
| R08 | IF ammoniacal_nitrogen IS Medio>L AND orthophosphate_reactive IS <=L THEN DO = 16.49 | 87 | 9.2 - 13.9 | outside |
| R09 | IF ammoniacal_nitrogen IS Bajo>L THEN DO = 11.33 | 805 | 8.2 - 13.7 | within |
| R10 | IF orthophosphate_reactive IS <=L AND water_temperature IS High THEN DO = 3.865 | 848 | 8.6 - 11.6 | outside |
| R11 | IF water_temperature IS High AND local_hour IS Low THEN DO = 5.821 | 626 | 7.2 - 11.0 | outside |
| R12 | IF orthophosphate_reactive IS <=L THEN DO = 14.89 | 2797 | 9.3 - 14.0 | outside |
| R13 | IF orthophosphate_reactive IS Alto>L AND ph IS High THEN DO = 13.82 | 335 | 8.8 - 13.9 | within |
| R14 | IF ammoniacal_nitrogen IS Medio>L AND local_hour IS High THEN DO = 12.58 | 386 | 7.9 - 13.4 | within |
| R15 | IF days_from_midwinter IS Invierno THEN DO = 10.80 | 2534 | 10.3 - 14.1 | within |
| R16 | IF water_temperature IS Medium AND ph IS High THEN DO = 12.76 | 856 | 10.3 - 13.4 | within |
| R17 | IF ammoniacal_nitrogen IS <=L AND orthophosphate_reactive IS <=L THEN DO = 14.18 | 2570 | 9.4 - 14.0 | outside |
| R18 | IF days_from_midwinter IS Primavera-otoño THEN DO = 6.354 | 4892 | 8.5 - 13.9 | outside |
| R19 | IF ammoniacal_nitrogen IS Bajo>L AND orthophosphate_reactive IS <=L THEN DO = 11.51 | 109 | 8.6 - 13.7 | within |
| R20 | IF ammoniacal_nitrogen IS Medio>L THEN DO = 15.78 | 1161 | 7.4 - 13.7 | outside |
| R21 | IF days_from_midwinter IS Primavera-otoño AND ph IS High THEN DO = 15.96 | 1417 | 9.4 - 13.9 | outside |
| R22 | IF ammoniacal_nitrogen IS <=L AND water_temperature IS Low THEN DO = 11.33 | 1596 | 11.9 - 14.5 | outside |
| R23 | IF days_from_midwinter IS Invierno AND ph IS Low THEN DO = 10.44 | 884 | 9.0 - 14.1 | within |
| R24 | IF ph IS High THEN DO = 12.76 | 2286 | 9.3 - 13.8 | within |
| R25 | IF ammoniacal_nitrogen IS Medio>L AND ph IS Medium THEN DO = 8.843 | 513 | 7.7 - 13.7 | within |
| R26 | IF water_temperature IS High AND ph IS Medium THEN DO = 6.710 | 901 | 7.8 - 11.0 | outside |
| R27 | IF ammoniacal_nitrogen IS <=L THEN DO = 14.53 | 5201 | 9.3 - 13.9 | outside |
| R28 | IF ammoniacal_nitrogen IS <=L AND days_from_midwinter IS Verano THEN DO = 7.776 | 1388 | 8.7 - 12.6 | outside |
| R29 | IF ammoniacal_nitrogen IS Bajo>L AND days_from_midwinter IS Invierno THEN DO = 15.24 | 296 | 10.9 - 13.9 | outside |
| R30 | IF orthophosphate_reactive IS <=L AND water_temperature IS Low THEN DO = 14.18 | 853 | 12.1 - 14.6 | within |
| R31 | IF ammoniacal_nitrogen IS <=L AND ph IS Low THEN DO = 12.22 | 1418 | 9.2 - 14.0 | within |
| R32 | IF ammoniacal_nitrogen IS Alto>L AND ph IS Medium THEN DO = 14.36 | 249 | 8.2 - 13.3 | outside |
| R33 | IF water_temperature IS Medium AND days_from_midwinter IS Invierno THEN DO = 8.488 | 937 | 9.2 - 12.8 | outside |
| R34 | IF water_temperature IS Low THEN DO = 18.62 | 2404 | 11.7 - 14.3 | outside |
| R35 | IF water_temperature IS Medium THEN DO = 7.065 | 3095 | 9.3 - 12.9 | outside |
| R36 | IF water_temperature IS High THEN DO = 2.798 | 2409 | 7.2 - 11.5 | outside |
| R37 | IF water_temperature IS Low AND days_from_midwinter IS Invierno THEN DO = 10.98 | 1553 | 11.7 - 14.4 | outside |
| R38 | IF orthophosphate_reactive IS Bajo>L THEN DO = 14.36 | 1599 | 9.3 - 13.9 | outside |
| R39 | IF orthophosphate_reactive IS Medio>L THEN DO = 13.11 | 2100 | 8.5 - 13.7 | within |

The terms `<=L`, `Bajo>L`, ... are those of `water_partitions.json`; `<=L` means "not above the detection limit", never
"zero". Read the set, not a rule: the prediction is the firing-weighted mean of the 39 consequents.

**Decision (rule of section 0).** `unique` passes: validation RMSE +0.026 mg/l (limit 0.03), 0 duplicates in every seed, and on
average 19.7 `outside` rules per seed against 26.3 for `base`. `unique_sufficient` fails (+0.24 mg/l). Among the arms that pass,
only `unique` remains, so **its test period was read, once** (command `experiment_water final --config
configs/ml/fx_water_do_chrono_temp_unique_experiment.json`, run directories `uk_water_do/fx-w-unique-seed{0,1,2}`;
the three fits are those of the validation run, deterministic):

**Test 2024-2025 (3,264 rows), published seed of each arm = seed 0**

| estimator | MAE (mg/l) | RMSE (mg/l) | R2 | 3 seeds, RMSE |
|---|---|---|---|---|
| ExFuzzy TSK, published model (`water-do-chrono-temp`, duplicates allowed) | 0.630 | 0.920 | 0.673 | 0.922 ± 0.003 |
| ExFuzzy TSK, `unique_antecedents` (`fx-w-unique`) | 0.635 | 0.932 | 0.665 | 0.938 ± 0.011 |
| random forest | 0.548 | 0.864 | 0.712 | |
| histogram gradient boosting | 0.562 | 0.881 | 0.700 | |
| ridge | 0.659 | 1.016 | 0.602 | |
| quadratic in temperature | 0.651 | 1.025 | 0.595 | |

Test RMSE by season (published seed): spring-autumn 1.011 (published model 0.999), summer 1.019 (0.958), winter 0.662
(0.715); observed DO below 8 mg/l (97 rows) 2.987 (2.868); points not seen in training 1.088 (1.063). The test cost of
`unique_antecedents` is +0.012 mg/l RMSE for the published seed and +0.016 for the 3-seed mean, the same order as on
validation, and the low-DO tail stays badly estimated.

**Recommendation: publish, as a readability option, not an accuracy gain** (originally "after release"; the author decided on
2026-10-31 to publish on the local build, see the status line and "Publication" below). A model with no repeated
antecedent sets (so no `duplicate_of` chains and no "Verano -> 1.2 mg/l" pair) at a cost of about 0.015 mg/l RMSE; the
compensating consequents of the additive TSK remain (R34 and R36 above), so the "implausible consequent" problem is
reduced (fewer rules outside the range of their rows) but not solved. `rule_mode="sufficient"`: no gain.

## 3. Experiment 3: NYC demand level, hour in 5 or 6 periods (validation 2025-01-08 to 2025-01-31, 53,575 rows)

Same task, rows, split (train to 2024-12-31, 168 h embargo), `rel7` inputs, class-tempered 30,000-row subsample and
budget as `nyc_pickups_h1_level_ica.md`. The relative inputs keep their four terms; the hour has 5 (`h5`: Madrugada 0-6,
Mañana 7-10, Mediodía 11-14, Tarde 15-21, Noche 22-23) or 6 (`h6`: ..., Tarde 15-16, Punta de tarde 17-19, Noche 20-23).

**Reproduction.** `fx-n4-fix` (published vocabulary, shape 30 x 2, integration build) gives the published per-seed
validation macro-F1 0.398 / 0.387 / 0.361 exactly, with the same rules. (The NYC rel7 model never suffered from the bound:
its first two features have four terms and so does the hour.) Level persistence scores 0.401 on validation.

| arm | shape | macro-F1 | bal-acc | acc | rules | Jaccard | macro-F1 by seed | rules with a `local_hour` / `local_dow` antecedent, per seed |
|---|---|---|---|---|---|---|---|---|
| level persistence (published baseline) | - | 0.401 | 0.401 | 0.447 | - | - | - | - |
| `h4` published (= `fx-n4-fix`, reproduced) | 30 x 2 | 0.382 ± 0.019 | 0.393 ± 0.026 | 0.426 ± 0.015 | 9.7 | 0.096 | 0.398, 0.387, 0.361 | 0 / 0 / 0 |
| `h4` at the `h5_sel` shape (post-hoc control, `fx-n4-shape`) | 60 x 3 | 0.375 ± 0.025 | 0.382 ± 0.025 | 0.421 ± 0.037 | 10.3 | 0.103 | 0.372, 0.352, 0.401 | 3 / 2 / 0 |
| `h5_fix` | 30 x 2 | 0.366 ± 0.026 | 0.367 ± 0.020 | 0.418 ± 0.038 | 7.3 | 0.275 | 0.352, 0.350, 0.396 | 3 / 3 / 1 |
| `h5_sel` | 60 x 3 | 0.399 ± 0.007 | 0.407 ± 0.007 | 0.437 ± 0.005 | 13.7 | 0.123 | 0.406, 0.393, 0.398 | 2 / 2 / 3 |
| `h6_fix` = `h6_sel` (the six-shape selection chose 30 x 2) | 30 x 2 | 0.387 ± 0.025 | 0.382 ± 0.023 | 0.447 ± 0.023 | 10.0 | 0.080 | 0.401, 0.400, 0.358 | 0 / 1 / 4 |

Shape selection (seed 0, validation macro-F1): `h5`: 30x2 0.352, 30x3 0.366, 30x4 0.384, 60x2 0.386, **60x3 0.406**, 60x4
0.381. `h6`: **30x2 0.401**, 30x3 0.347, 30x4 0.388, 60x2 0.370, 60x3 0.381, 60x4 0.394. Fit time 27-143 s, RSS below 0.8 GB.

Term usage of `local_hour` and `local_dow` (antecedents per term, seeds 0 / 1 / 2): `h5_fix`: hour none, dow Laborable 1/1/0,
Sábado 1/1/0, Domingo 1/1/1. `h5_sel`: hour Madrugada 0/1/1, Mañana 0/0/1; dow Laborable 1/0/1, Domingo 1/1/0. `h6`: hour
Mañana 0/0/1; dow Laborable 0/0/1, Sábado 0/0/1, Domingo 0/1/1. `h4` at 60 x 3: hour Madrugada 1/1/0, Mañana 1/0/0,
Tarde-noche 0/1/0; dow Laborable 1/0/0. The fifth and sixth hour terms (Tarde, Noche, Punta de tarde) are **never** used by
any rule of any seed.

Reading:

* **The rules do not start using the evening.** The two terms the new vocabulary adds (the split of the old
  Tarde-noche) appear in no rule of any seed of `h5` or `h6`; the hour appears only through Madrugada and Mañana, and only in
  larger rule bases (`h5_sel` seeds 1 and 2, `h6` seed 2). The old 4-term vocabulary does the same at 60 x 3 (hour used by
  seeds 0 and 1), so what let the published model ignore the hour was its small shape (30 rules x 2 antecedents), not the
  vocabulary or the bound.
* **Macro-F1 does not clear the rule.** `h5_sel` (0.399 ± 0.007) is +0.017 above the published `h4` (0.382), under the 0.019 of the rule
  and 0.002 below persistence (0.401); `h5_fix` is -0.016; `h6` is +0.005. Against the `h4` fit at the same 60 x 3 shape
  `h5_sel` is +0.024, but that control is post-hoc and its sd (0.025) is larger than the gain, and at 30 x 2 the same
  vocabulary is worse (`h5_fix`), so the sign depends on the shape. Nothing here is resolved by three seeds.
* `h6`'s best seed is persistence: 4 rules, "IF rel_lag1 IS baja THEN nivel = baja", ..., "IF rel_lag1 IS muy alta THEN nivel =
  muy alta"; it scores 0.401, the persistence figure.

**Rules of `h5_sel`, seed 0** (best validation macro-F1 of the most promising arm, 13 rules, mean length 1.8; not recommended for
publication):

* IF rel_lag1 IS baja THEN nivel = baja (peso 0.0621)
* IF rel_lag1 IS normal AND rel_lag24 IS baja THEN nivel = normal (peso 0.026)
* IF rel_lag2 IS baja AND local_dow IS Domingo THEN nivel = normal (peso 0.00516)
* IF rel_lag1 IS normal AND rel_lag24 IS normal THEN nivel = normal (peso 0.0684)
* IF rel_lag1 IS alta AND rel_lag2 IS normal THEN nivel = alta (peso 0.0157)
* IF rel_lag1 IS alta AND rel_lag168 IS baja THEN nivel = alta (peso 0.00667)
* IF rel_lag1 IS normal AND local_dow IS Laborable THEN nivel = alta (peso 0.0219)
* IF rel_lag1 IS normal AND rel_lag24 IS alta THEN nivel = alta (peso 0.0117)
* IF rel_lag1 IS alta AND rel_lag2 IS alta AND rel_lag24 IS alta THEN nivel = alta (peso 0.00781)
* IF rel_lag1 IS alta AND rel_lag168 IS normal THEN nivel = alta (peso 0.0179)
* IF rel_lag1 IS normal AND rel_lag2 IS normal THEN nivel = alta (peso 0.0189)
* IF rel_lag168 IS alta THEN nivel = muy alta (peso 0.00633)
* IF rel_lag1 IS muy alta THEN nivel = muy alta (peso 0.012)

Two of these rules mention the calendar ("normal level an hour ago on a workday -> alta"; "low two hours ago on a Sunday ->
normal"); they are associations of one winter's reference, not findings.

**Decision (rule of section 0).** No vocabulary enters on both protocols: `h5_fix` -0.016 and `h6` +0.005 on macro-F1, `h5_sel` +0.017
with 0.399 < 0.401 (persistence). **Recommendation: no gain** (the published NYC model stays). No test row was read for NYC; the
published test figure remains 0.412 (published seed) against persistence 0.425.

## 4. Experiment 4: `construct_breakpoint_partition` against `atlas.ml.partitions` (parity check, nothing switched over)

Each fixed variable of the committed partition files was rebuilt with `utils.construct_breakpoint_partition`
(breakpoint = midpoint between a core and the next, ramp width = scale x (shoulder + gap), best scale on 0.05-4) and
compared with the Atlas trapezoids on a 4,001-point grid of the domain (`atlas.ml.fx_checks.breakpoint_parity`;
`tests/ml/test_fx_checks.py`):

| variable | shoulder / gap | identical parameters | max membership difference at the best scale |
|---|---|---|---|
| hour (Madrid 4 and 5 terms, NYC 4 and 6 terms), weekday, `local_dow` | 1 / 1 | **yes** (scale 0.5: ramp [u, u + 1]) | 0.000 |
| NO2, four inputs (ICA bands, 15 % shoulders 6, 13.5, 18) | 6-18 / 1 | no | 0.472 (scale 0.95) |
| wind speed (Beaufort groups, 0.5, 0.5, 0.79 m/s) | 0.5-0.8 / 0.1 | no | 0.438 (scale 0.90) |
| NYC `rel_lag*` (7, 7, 3.5 percentile points) | 3.5-7 / 0.1 | no | 0.493 (scale 1.00) |
| water `days_from_midwinter` (15 days) | 15 / 1 | no | 0.467 (scale 0.95) |

The two families coincide only where the shoulder equals the gap between cores (the whole-hour partitions): there a
neighbour's falling ramp and the next term's rising ramp are the same segment, i.e. a Ruspini partition. Atlas's terms
keep membership 1 on the whole official band and let the neighbours overlap over a shoulder on each side of the
boundary (memberships do not add to 1), which is what makes `no2_last IS Regular` mean "inside the 91-120 band, with a
measurement-uncertainty margin". `construct_breakpoint_partition` cannot express that without giving up either the
full-membership core or the margin; if Atlas ever wants Ruspini bands, it would be a different partition family (and
new models), not a refactor. **Recommendation: keep `atlas.ml.partitions`**; the library function is useful for the
hour and weekday variables only, where it gives identical trapezoids.

## 5. Code added (all reusable pieces have tests; none is needed by serving)

* `atlas.ml.exfuzzy_features`: `has_term_bound_fix`, `has_unique_antecedents`, `has_breakpoint_partition` (behavioural probes,
  because the integration build still reports 3.3.1), `require`, `ensure_config`, `provenance_warnings`,
  `provenance_hyperparameters`; experiment configs (`ExperimentConfig`, `WaterConfig`) gain `exfuzzy_source` and
  `requires_exfuzzy`, checked at the start of `run_selection` / `run_final` (clear `ExFuzzyFeatureError` on the pinned
  library) and echoed in `selection.json`, the summaries and every manifest (`hyperparameters.exfuzzy_source`,
  `exfuzzy_module_path`, a manifest warning).
* `FuzzyParams.unique_antecedents` (default False, absent from `as_dict()` when False, so manifests of the pinned release are
  unchanged); `WaterConfig.rule_mode` and `.unique_antecedents`; `experiment_water final --validation-only` (no test row,
  no run directory).
* `atlas.ml.fx_checks`: `classifier_term_usage`, `consequent_support`, `breakpoint_parity`. `atlas.ml.report_fx`: the tables above.
* Configs: `configs/ml/fx_*_experiment.json` (one per arm), `madrid_partitions_hour5.json`, `nyc_partitions_hour5.json`,
  `nyc_partitions_hour6.json`.
* Tests: `tests/ml/test_exfuzzy_features.py`, `test_fx_checks.py`, `test_report_fx.py` and three cases in
  `test_water_experiment.py`. `tests/ml` on the pinned 3.3.1: 188 passed, 4 skipped (the ones that need a fix; the refusal
  tests run); on the integration build: 191 passed, 1 skipped (the test that documents the 3.3.1 behaviour).

**Publication (2026-10-31).** Seed 0 of `unique` is the served Water model, `exfuzzy-uk_water_do-fx-w-unique-seed0`:
39 rules, 39 distinct antecedent sets (0 duplicates), validation RMSE 0.925, test RMSE 0.932 (MAE 0.635, R2 0.665),
`exfuzzy_version` `3.3.1+g2ffcfb9` in the manifest, the card and the `inference` block of `rules.json`. The run directories
written before the provenance change recorded `3.3.1`, so the three seeds were **refitted on the same build with the same
configuration** (`make fit-water-unique`, the shape selection of `selection.json` reused) and compared with the earlier runs:
`rules.json` identical except `inference.exfuzzy_version` and `schema_version` (0.3.0 to 0.4.0, the contract moved on), the
`predictions.parquet` of all three seeds identical (`DataFrame.equals`), and every metric row of the ex_fuzzy model identical
except fit time and RSS; the random-forest baseline rows differ in the 16th digit (thread-dependent summation, 4 threads
now), nothing else. The previous Water model `exfuzzy-uk_water_do-water-do-chrono-temp-seed0` stays in `artifacts/published`
but is no longer registered; the registry's `uk_water_do` points to the new id.

## 6. Reproduce

```bash
export ATLAS_DATA_DIR=/path/to/exfuzzy-atlas/data ATLAS_ARTIFACTS_DIR=/path/to/exfuzzy-atlas/artifacts
LOCAL=/path/to/ex-fuzzy   # branch atlas/local-integration @ 2ffcfb9
PY=python; A=$ATLAS_ARTIFACTS_DIR
export PYTHONPATH=$LOCAL:src; $PY -c 'import ex_fuzzy; print(ex_fuzzy.__file__)'    # must print the LOCAL path
# 1 Madrid (validation only; --no-baselines because the baselines are those of AT-041d)
$PY -m atlas.ml.experiment_class select --config configs/ml/fx_madrid_no2_h6_repro_experiment.json            # reproduction
$PY -m atlas.ml.experiment_class select --config configs/ml/fx_madrid_no2_h6_hour5_experiment.json
$PY -m atlas.ml.experiment_class final --validation-only --no-baselines --config configs/ml/fx_madrid_no2_h6_hour5_experiment.json
$PY -m atlas.ml.experiment_class final --validation-only --no-baselines --config configs/ml/fx_madrid_no2_h6_hour5_fixed_experiment.json \
    --selection $A/madrid_no2_h6/experiments/ica2-justified/selection.json
PYTHONPATH=src $PY -m atlas.ml.experiment_class final --validation-only --no-baselines \
    --config configs/ml/fx_madrid_no2_h6_hour5_pinned_control_experiment.json --selection $A/madrid_no2_h6/experiments/ica2-justified/selection.json  # PINNED 3.3.1
# 2 Water
for a in base unique unique_sufficient; do
  $PY -m atlas.ml.experiment_water select --config configs/ml/fx_water_do_chrono_temp_${a}_experiment.json
  $PY -m atlas.ml.experiment_water final --validation-only --config configs/ml/fx_water_do_chrono_temp_${a}_experiment.json; done
$PY -m atlas.ml.experiment_water final --config configs/ml/fx_water_do_chrono_temp_unique_experiment.json   # test, once
# 3 NYC
S=$A/nyc_pickups_h1/experiments/level-rel7/selection.json
for c in hour4_repro hour5_fixed hour6_fixed; do $PY -m atlas.ml.experiment_nyc final --validation-only --no-baselines \
    --config configs/ml/fx_nyc_pickups_h1_${c}_experiment.json --selection $S; done
for k in 5 6; do $PY -m atlas.ml.experiment_nyc select --config configs/ml/fx_nyc_pickups_h1_hour${k}_experiment.json
  $PY -m atlas.ml.experiment_nyc final --validation-only --no-baselines --config configs/ml/fx_nyc_pickups_h1_hour${k}_experiment.json; done
$PY -m atlas.ml.experiment_nyc final --validation-only --no-baselines --config configs/ml/fx_nyc_pickups_h1_hour4_shape_control_experiment.json \
    --selection $A/nyc_pickups_h1/experiments/fx-n5-sel/selection.json                                      # post-hoc control
# tables
PYTHONPATH=src:apps/api $PY -m atlas.ml.report_fx madrid --arm base=ica2-justified --arm h5_fix=fx-m5-fix --arm h5_sel=fx-m5-sel --arm h5_ctrl=fx-m5-ctrl --usage valid_hour_local
PYTHONPATH=src:apps/api $PY -m atlas.ml.report_fx nyc --arm h4=level-rel7 --arm h5_sel=fx-n5-sel --usage local_hour local_dow --rules
PYTHONPATH=src:apps/api $PY -m atlas.ml.report_fx water --arm base=configs/ml/fx_water_do_chrono_temp_base_experiment.json --arm unique=configs/ml/fx_water_do_chrono_temp_unique_experiment.json
# publish the served Water model (seed 0 of `unique`), then the suite on the PINNED library (make test / make lint)
make publish-water-unique EXFUZZY_SRC=$LOCAL ATLAS_DATA_DIR=$ATLAS_DATA_DIR ATLAS_ARTIFACTS_DIR=$ATLAS_ARTIFACTS_DIR
```

Compute: 80 minutes of single-core GA fits in total (Madrid 31, NYC 32, Water 17), sequential, one process at a time, peak RSS
1.0 GB; plus the test suites (`make test` takes about 5 minutes wall and 37 minutes of CPU on this machine because the service
tests use many threads).

## 7. Limits

* Three seeds and one validation block per task: a seed sd of 0.011 (Madrid), 0.019-0.026 (NYC) and 0.010-0.020 (Water) means that
  differences below about 0.02 macro-F1 or 0.03 mg/l are not resolved. The decisions are "does not clear a rule fixed beforehand",
  not "is worse".
* Single-seed shape selection is noisy (AT-041d picked 60 x 4 for Madrid, the `h5` selection 30 x 4; NYC `h5` 60 x 3, `h6` 30 x 2).
  Both a fixed-shape and a selected-shape protocol are therefore reported; the NYC `h4` at 60 x 3 control is post-hoc.
* The residual skew of PR 32 (an index above a variable's term count clips to its last term) is not removed, and cannot be separated
  from the vocabulary effect here.
* The hour cuts are read from the traffic / pickup profiles of the training period and fixed before the fits; other cuts were
  not tried (that would be tuning on validation).
* The "implausible consequent" check is descriptive: in an additive TSK a consequent need not be the mean of its rows.
* The test period was read for Water `unique` only. The Madrid and NYC test figures quoted are those already published.
* The models are fitted on an unreleased ex_fuzzy; `ex_fuzzy.__version__` is 3.3.1 on both builds, so the manifests record the commit (`3.3.1+g2ffcfb9`) and carry a warning that a release pin will replace the build.

## 8. Deviations from section 0 (all of them, in the order they happened)

1. The `h5_sel` protocol of Madrid selected 30 x 4, not the AT-041d shape 60 x 4, so `h5_fix` and `h5_sel` are two different
   models (as section 0 allowed); no run was skipped.
2. NYC `h4` at the shape chosen for `h5_sel` (`fx-n4-shape`, 60 x 3) was **not in section 0**. It was added after seeing `h5_sel` to
   separate the shape from the vocabulary; it is post-hoc, is excluded from the decision, and is labelled so above.
3. A queue script waited on the wrong path and idled for a few minutes (no fit was affected). `make test` was run once in full
   (5 minutes wall, 37 CPU minutes, many threads) and tests/ml several times on each library; the GA fits were never run in parallel.
4. No test row was read for Madrid or NYC (no arm entered); for Water only `unique` was read, once, as the rule says.
5. The pinned control of Madrid (`fx-m5-ctrl`) has no `exfuzzy_source` by design: it ran on the pinned release.
