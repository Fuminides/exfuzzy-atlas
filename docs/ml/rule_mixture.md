# Mixture of rules: every rule votes, with learned per-class weights (AT-041i)

> **Follow-up (AT-041j, contract v0.7):** by decision of the user the mixture is now published for every demo
> classifier; the retrain, results and publication are in `docs/ml/rule_mixture_serve.md`.

The served classifiers are ex_fuzzy winning-rule classifiers: one rule decides each prediction (firing x dominance
score, or firing alone for the unweighted ica4 models). On 14 tasks they tie persistence and "same hour yesterday" but
lose to a multinomial logistic regression on the same 30,000 fitting rows in 12 of them, by 0.01-0.06 test macro-F1
(Madrid +6 h 0.411 against 0.419, Germany +6 h 0.518 against 0.551, NYC +3 h 0.335 against 0.394). Larger rule bases
(60 x 4) did not help. Reading: one winning rule cannot add up evidence from several rules; a linear model adds up
every input.

This experiment measures an opt-in inference added to ex_fuzzy for it (Fuminides/ex-fuzzy PR 44, branch
`feat/rule-mixture`, commit `20c1095`): the score of class c is

    score_c(x) = b_c + sum_r W[r, c] * mu_r(x),   prediction = argmax_c score_c(x)

with `mu_r` the firing strength of rule r and `W`, `b` fitted by L2-regularised multinomial logistic regression on
the matrix of rule firings of the fitting rows. **Nothing is published.** Run directories are experiment directories
(`artifacts/<task>/experiments/rule-mixture/`).

**What this is not.** A mixture weight is a coefficient of a fitted linear model on firing strengths. It is not a
probability, a contribution in the causal sense, or a risk; `softmax(score)` is that model's class probability on
data like its fitting sample (class-tempered, power 0.5), not a calibrated probability. Firing is still a degree of
rule match.

## 0. Pre-registration (written and committed before any validation number of a mixture arm was produced)

### 0.1 What was known when this section was written

* The served models' published numbers (their `metrics.json`; the rows of this experiment are those rows):

  | task | served model | val macro-F1 (served seed) | test | persistence val / test | same hour yesterday val / test | LR (fitting sample) val / test |
  |---|---|---|---|---|---|---|
  | Madrid +6 h | `exfuzzy-madrid_no2_h6-ica4-yday-seed1` | 0.480 | 0.411 | 0.294 / 0.293 | `persistence_24h` 0.475 / 0.407 | 0.453 / 0.419 |
  | NYC +3 h | `exfuzzy-nyc_pickups_h3-level-rel7-seed0` | 0.328 | 0.335 | 0.327 / 0.355 | `persistence_rel_lag24` 0.310 / 0.345 | 0.326 / 0.394 |

  The served arms' three seeds: Madrid `r3_minimal_unweighted` validation 0.479 / 0.481 / 0.434 on the ica4 rows
  (`madrid_no2_h6_ica_v4.md`); NYC `level-rel7` 0.328 / 0.306 / 0.299.
* **The NYC LR of `metrics.json` does not have the model's inputs**: the NYC baselines use `baseline_features`, the 7
  fuzzy inputs plus 5 raw pickup counts (`pickups_lag1/2/24/168`, `pickups_mean24h`). The comparison "same rows and
  inputs" therefore needs a refit (section 0.6). In Madrid the LR of `metrics.json` has the model's 4 inputs.
* A smoke run of the experiment code (`arms --smoke`: 2 generations x 8 individuals, seed 0, every score on the
  30,000 fitting rows, no validation or test row read) checked that the pipeline runs. Its in-sample macro-F1 on the
  fitting rows: Madrid served 0.536, mixture on its rules 0.542 (>= 0) / 0.543 (free); NYC served 0.354, mixture on
  its rules 0.317 / 0.317. Logistic regression maximises likelihood, not macro-F1, so on the fitting rows a mixture of
  the same rules can score below the winning rule (NYC). Nothing was changed after it.
* Cost (measured on the fitting rows, single-threaded BLAS): a mixture fit on the served rules takes 0.06-0.15 s; one
  candidate of the search under the mixture 0.08 s (Madrid, 30 x 2) to 0.27 s (NYC, 60 x 2).

### 0.2 Library and environment

`EXFUZZY_SRC` = a worktree of ex-fuzzy `feat/rule-mixture` (PR 44, on top of ex-fuzzy main `fac6c0e`), first on
`PYTHONPATH`; the main environment keeps the pinned PyPI 3.3.1 and nothing is installed. The fits record
`exfuzzy_version` = `3.3.1+g20c1095`. Default inference in that build is bit-for-bit the one of ex-fuzzy main (PR
44, 15 seeded fits compared). Main differs from 3.3.1 by later PRs, among them PR 32 and 35 (term genes of variables
with fewer terms): they change the decoding where inputs have different numbers of terms, i.e. in NYC (`local_dow`
and `rel_mean24h` have 3 terms, the others 4), not in Madrid (four 4-term inputs). The control arm `search_winning`
measures what the newer build alone does to the search.

### 0.3 Tasks, rows, split, sample

* **Madrid +6 h**: rows, split (train 2019-2023 / validation 2024 / test 2025, 24 h embargo), class merge and
  partitions of the served run directory (`configs/ml/madrid_no2_h6_ica4_publish_experiment.json`: the complete rows
  with `no2_yday_valid` finite, 189,413 validation and 178,122 test rows); inputs `no2_yday_valid`, `no2_last`,
  `valid_hour_local`, `wind_speed`; served arm = the three publication fits of `r3_minimal_unweighted`
  (`experiments/ica4-yday/models/seed{0,1,2}.pkl`, never-deciding rules pruned as published; seed 1 is the served
  model).
* **NYC +3 h**: `configs/ml/nyc_pickups_h3_level_rel7_experiment.json` (train 2024-04 to 2024-12 / validation
  2025-01-08 to 2025-02-01 / test 2025-02-08 to 2025-04-01, 168 h embargo); 7 inputs; served arm =
  `experiments/level-rel7/models/seed{0,1,2}.pkl` (seed 0 is the served model). For NYC "validation" in this report
  means that January 2025 window, not 2024.
* **Germany +6 h** only if time and memory allow (its fits need about 9.5 GB each, the large machine), with the same arms and rule
  (`configs/ml/de_no2_h6_mixture_experiment.json`); if it is not run, this report says so.
* **Fitting sample**: every fit and every mixture weight uses the served model's own class-aware 30,000-row sample
  (`subsample_keys.parquet` of the served experiment, power 0.5), which is also the sample of the `*_subsample`
  baselines. The terms of every re-searched fit are checked to be those of the served model.
* Seeds 0, 1, 2 for every arm. A mixture on the served rules has no seed of its own: its seed is the served seed whose
  rules it uses.

### 0.4 Arms

| arm | rules | inference | weights |
|---|---|---|---|
| `served` | the served seed's | winning rule (as served) | - |
| `mix_served_nonneg` | the served seed's, unchanged | mixture | `W >= 0` |
| `mix_served_free` | the served seed's, unchanged | mixture | unconstrained |
| `mix_search_nonneg` | re-searched: the GA scores each candidate as its own fitted mixture (`mixture_search`) | mixture | `W >= 0` |
| `mix_search_free` | re-searched, as above | mixture | unconstrained |
| `search_winning` (control, never selected) | re-searched with the winning-rule objective on the new build | winning rule | - |

Common to all: `mixture_C = 1.0` (L2 penalty `||W||^2 / 2`, scikit-learn's convention, the same `C` as the LR
baselines), no tuning of `C`, weights fitted on the fitting sample only. Re-searched arms use the served shape and
budget (Madrid 30 rules x 2 antecedents, NYC 60 x 2; 150 generations x 60 individuals, no early stop), the served
weighting for the search's pruning (Madrid unweighted, NYC dominance score) and the served terms. The pruning of a
re-searched candidate is the library's winning-rule pruning (dominance score and winning-rule accuracy), as in a
fitted model.

The ex_fuzzy "search under the mixture" was affordable (0.08-0.27 s per candidate), so it is the re-searched arm
instead of a winning-rule search followed by a mixture.

### 0.5 Decision rule (each task on its own; validation only; `python -m atlas.ml.experiment_mixture decide`)

* Reference = mean validation macro-F1 of `served` over its three seeds.
* A mixture arm **wins** if (1) its mean gain over the reference is at least
  `max(0.02, 2 * sqrt((sd_arm^2 + sd_served^2) / 3))`, two standard errors of the difference of two 3-seed means and
  never less than the 0.02 of ica4; (2) its worst seed is above the reference mean; (3) its mean number of rules with
  **non-negligible weight** is at most 22 (the readability bound of ica4). A rule has non-negligible weight when its
  weight spread `max_c W[r, c] - min_c W[r, c]` is at least 0.25 (a fully firing rule moves the odds of one class
  against another by a factor of at least e^0.25 = 1.28); the spread does not change when a constant is added to all
  of a rule's weights, so it is comparable between `>= 0` and unconstrained weights.
* Among winners the highest mean is taken; arms within 0.005 of it are tied, and the tie goes to non-negative weights
  (easier to read), then to fewer rules with non-negligible weight, then to the served rules over re-searched ones.
  The proposed seed is the chosen arm's seed with the highest validation macro-F1.
* If nothing wins, the served model stays. The test is then still read once, for information only, for the mixture arm
  with the highest validation mean.
* `search_winning` is a control: it is reported, never selected.

### 0.6 Test (read once, `final --test`; a `TEST_READ` marker refuses a second read)

For the selected (or information-only) arm and for `served`, three seeds each, on the task's test rows; next to:
persistence and same hour yesterday (Madrid `persistence_24h`, NYC `persistence_rel_lag24`) and the LR of the served
`metrics.json`, quoted; a logistic regression refitted on the same fitting sample with **the model's inputs** (in
Madrid it must reproduce the `metrics.json` LR, in NYC it is the "same inputs" comparison) and, in NYC, with the
baselines' 12 inputs (it must reproduce the `metrics.json` LR). The served seed's test macro-F1 must reproduce its
`metrics.json`.

### 0.7 Interpretability (reported for every mixture arm, from the fitting sample only)

Rules kept; rules with non-negligible weight (section 0.5); **decisive** rules (setting the rule's weights to 0 changes at
least 0.1 % of the fitting-sample predictions); the weights and biases of every fit (`fits/*.json`). For the chosen
(or information-only) arm and seed, 3-5 rules as text with their weight for every class, their strongest class and the
biases (`print_mixture`).

### 0.8 Reproduce

```bash
X=<ex-fuzzy worktree at feat/rule-mixture>; export PYTHONPATH=$X:src:apps/api OMP_NUM_THREADS=1
for t in madrid_no2_h6 nyc_pickups_h3; do C=configs/ml/${t}_mixture_experiment.json
  python -u -m atlas.ml.experiment_mixture arms --config $C --workers 4   # 18 fits, [k/N] progress
  python -m atlas.ml.experiment_mixture decide --config $C
  python -m atlas.ml.experiment_mixture final --test --config $C          # once
  python -m atlas.ml.experiment_mixture report --config $C; done
```

Tests: `tests/ml/test_mixture_decision.py` (the decision rule, the opt-in options); the library's own tests are in
ex-fuzzy PR 44.

## 1. What was run, and every deviation from section 0

* **Machine: the large machine, not the workstation** (the workstation was short of memory). Code: Atlas `c1fefbc` (the pre-registration commit),
  ex-fuzzy `20c1095` (a clone of PR 44; every fit records `3.3.1+g20c1095`). Python: an existing
  venv on the large machine, used read-only (numpy 2.5.3, pandas 3.0.6, scikit-learn 1.9.1, scipy 1.18.1, pymoo
  0.6.2), plus a stub `duckdb` module (`atlas.contracts` imports it at import time for the observation validator,
  which this experiment never calls; any use raises). Nothing was installed. This is a different numpy / pandas than
  the main environment; the checks below say it did not change any number that can be compared.
* **Platform checks** (all exact, `final_test.json` `checks`): the served seed of each task reproduces its
  `metrics.json` validation and test macro-F1 bit for bit (Madrid 0.48027 / 0.41067, NYC 0.32822 / 0.33500, Germany
  0.47664 / 0.51812); the LR refitted on the model's inputs reproduces the `metrics.json` LR in Madrid and Germany
  (0.45280 / 0.41941, 0.50608 / 0.55148) and, with the 12 baseline inputs, in NYC (0.32610 / 0.39394). The smoke run
  (section 0.1) gave the same fitting-sample numbers on the workstation and the large machine.
* **Germany +6 h was run** (section 0.3 allowed it): time and memory allowed it, with peak RSS 1.9 GB per fit.
* Otherwise as registered: the six arms, three seeds, the rule of section 0.5 applied by `decide`, the test read once
  per task (`TEST_READ`), for `served` and the chosen or information-only arm.

## 2. Validation (mean ± sd over seeds 0-2; rules = rules kept; "weighted" = rules with weight spread >= 0.25)

| task | arm | val macro-F1 | seeds | rules | weighted | fit s |
|---|---|---|---|---|---|---|
| Madrid +6 h | `served` | 0.464 ± 0.026 | 0.478 / 0.480 / 0.434 | 6.7 | - | - |
| | `mix_served_nonneg` | 0.458 ± 0.011 | 0.470 / 0.448 / 0.455 | 6.7 | 6.7 | < 1 |
| | `mix_served_free` | 0.459 ± 0.012 | 0.472 / 0.449 / 0.456 | 6.7 | 6.7 | < 1 |
| | `mix_search_nonneg` | 0.478 ± 0.003 | 0.474 / 0.480 / 0.481 | 12.7 | 12.7 | 125 |
| | `mix_search_free` | **0.479 ± 0.000** | 0.478 / 0.478 / 0.479 | 12.0 | 12.0 | 108 |
| | `search_winning` (control) | 0.476 ± 0.001 | 0.476 / 0.477 / 0.475 | 5.0 | - | 14 |
| NYC +3 h | `served` | 0.311 ± 0.015 | 0.328 / 0.306 / 0.299 | 9.7 | - | - |
| | `mix_served_nonneg` | 0.301 ± 0.012 | 0.293 / 0.296 / 0.315 | 9.7 | 6.3 | < 1 |
| | `mix_served_free` | 0.301 ± 0.012 | 0.293 / 0.296 / 0.315 | 9.7 | 6.3 | < 1 |
| | `mix_search_nonneg` | 0.322 ± 0.003 | 0.319 / 0.322 / 0.325 | 15.7 | 10.3 | 763 |
| | `mix_search_free` | **0.325 ± 0.006** | 0.321 / 0.323 / 0.332 | 17.0 | 10.7 | 385 |
| | `search_winning` (control) | 0.315 ± 0.005 | 0.321 / 0.312 / 0.313 | 8.3 | - | 86 |
| Germany +6 h | `served` | 0.473 ± 0.005 | 0.468 / 0.475 / 0.477 | 7.7 | - | - |
| | `mix_served_nonneg` | 0.487 ± 0.003 | 0.487 / 0.485 / 0.490 | 7.7 | 7.7 | < 1 |
| | `mix_served_free` | 0.487 ± 0.002 | 0.487 / 0.485 / 0.490 | 7.7 | 7.7 | < 1 |
| | `mix_search_nonneg` | 0.507 ± 0.002 | 0.509 / 0.507 / 0.504 | 12.0 | 11.7 | 220 |
| | `mix_search_free` | **0.511 ± 0.003** | 0.510 / 0.508 / 0.514 | 11.0 | 10.3 | 166 |
| | `search_winning` (control) | 0.473 ± 0.007 | 0.467 / 0.480 / 0.472 | 8.7 | - | 25 |

Reference values for the same rows (from `metrics.json`, not fitted here): Madrid persistence 0.294, `persistence_24h`
0.475, LR 0.453; NYC persistence 0.327, `persistence_rel_lag24` 0.310, LR 0.326; Germany persistence 0.438,
`persistence_24h` 0.484, LR 0.506.

What the table says:

* **A mixture on the served rules does not help** where the served rules are few and mostly "IF yesterday IS c": -0.006
  in Madrid, -0.010 in NYC; +0.014 in Germany. Logistic regression maximises likelihood, not macro-F1, and these rule
  bases were selected for winning-rule macro-F1. With the same rules, `>= 0` and unconstrained weights give the same
  prediction on 99.4-99.99 % of the validation rows (they are the same family of models; only the penalty differs).
* **Re-searching the rules under the mixture helps in every task** (+0.014 Madrid, +0.014 NYC, +0.034 / +0.038
  Germany) and makes the seeds far more stable (sd 0.000-0.006 against 0.005-0.026). It needs about twice as many
  rules (11-17 against 5-12), all short (mean length 1.0-1.4).
* **The control matters in Madrid.** The winning-rule GA re-run on this build and machine scores 0.476, close to the
  mixture search (0.479) and well above the served arm (0.464, whose third seed is 0.434); none of its seeds
  reproduces a served rule set (Jaccard 0.33-0.62). So in Madrid the validation gain cannot be credited to the mixture.
  In NYC the mixture search is +0.010 over the control, in Germany +0.038.

## 3. Decision (section 0.5, `decide`; `decision.json` of each task)

| task | reference (served mean, sd) | best mixture arm: gain / margin | worst seed > ref | weighted rules <= 22 | decision |
|---|---|---|---|---|---|
| Madrid +6 h | 0.464, 0.026 | `mix_search_free` +0.015 / 0.030 | yes | yes | **nothing wins**: the served model stays |
| NYC +3 h | 0.311, 0.015 | `mix_search_free` +0.014 / 0.020 | yes | yes | **nothing wins**: the served model stays |
| Germany +6 h | 0.473, 0.005 | `mix_search_free` +0.038 / 0.020; `mix_search_nonneg` +0.034 / 0.020 | yes | yes | **`mix_search_nonneg`, seed 0** (the two are within 0.005; the tie goes to `>= 0` weights) |

In Madrid the served arm's seed noise (sd 0.026) sets a margin of 0.030; in NYC the gain falls short of the 0.02 floor.
The test was then read once for `mix_search_free` in Madrid and NYC, for information only.

## 4. Test (read once per task; `final_test.json`)

| task | model | val macro-F1 | test macro-F1 | test bal-acc | test acc |
|---|---|---|---|---|---|
| Madrid +6 h (2025, 178,122 rows) | ExFuzzy served arm, 3 seeds | 0.464 ± 0.026 | 0.403 ± 0.008 | 0.400 ± 0.008 | 0.816 ± 0.001 |
| | served model (seed 1) | 0.480 | 0.411 | | |
| | `mix_search_free` (information only), 3 seeds | 0.479 ± 0.000 | **0.421 ± 0.002** (0.421 / 0.423 / 0.419) | 0.444 ± 0.001 | 0.820 ± 0.004 |
| | persistence / `persistence_24h` | 0.294 / 0.475 | 0.293 / 0.407 | | |
| | LR, fitting sample, the model's 4 inputs | 0.453 | 0.419 | 0.435 | 0.829 |
| NYC +3 h (Feb-Mar 2025, 116,319 rows) | ExFuzzy served arm, 3 seeds | 0.311 ± 0.015 | 0.313 ± 0.028 | 0.324 ± 0.006 | 0.363 ± 0.013 |
| | served model (seed 0) | 0.328 | 0.335 | | |
| | `mix_search_free` (information only), 3 seeds | 0.325 ± 0.006 | **0.373 ± 0.006** (0.372 / 0.368 / 0.379) | 0.366 ± 0.006 | 0.420 ± 0.004 |
| | persistence / `persistence_rel_lag24` | 0.327 / 0.310 | 0.355 / 0.345 | | |
| | LR, fitting sample, the model's 7 inputs (refit) | 0.326 | 0.398 | 0.392 | 0.439 |
| | LR, fitting sample, the 12 baseline inputs (`metrics.json`) | 0.326 | 0.394 | 0.388 | 0.439 |
| Germany +6 h (2025, 2,911,495 rows) | ExFuzzy served arm, 3 seeds | 0.473 ± 0.005 | 0.517 ± 0.007 | 0.518 ± 0.010 | 0.640 ± 0.007 |
| | served model (seed 2) | 0.477 | 0.518 | | |
| | **`mix_search_nonneg` (chosen)**, 3 seeds | 0.507 ± 0.002 | **0.551 ± 0.003** (0.554 / 0.550 / 0.549) | 0.552 ± 0.002 | 0.660 ± 0.001 |
| | proposed seed 0 | 0.509 | 0.554 | | |
| | persistence / `persistence_24h` | 0.438 / 0.484 | 0.455 / 0.536 | | |
| | LR, fitting sample, the model's 4 inputs | 0.506 | 0.551 | 0.537 | 0.666 |

Reading:

* **Germany (selected):** 0.518 -> 0.554 for the proposed seed (arm 0.517 ± 0.007 -> 0.551 ± 0.003). It ties the LR
  of the same rows and inputs (0.551) and is above "same hour yesterday" (0.536), which the served model was below.
  Recall of the worst class goes from 0.24-0.30 to 0.31-0.33 with precision 0.30-0.31 (served seed 2: 0.27 / 0.26).
* **Madrid (information only):** 0.421 ± 0.002 against the served model's 0.411 and the arm's 0.403 ± 0.008; equal to
  LR (0.419) and above `persistence_24h` (0.407). Recall of Regular 0.28 (served 0.17-0.22) and of Desfavorable o peor
  0.16 (0.07-0.10). Not selected: on validation it did not clear the served arm's seed noise, and the winning-rule
  control came as close on validation; its test was not read.
* **NYC (information only):** 0.373 ± 0.006 against 0.335 for the served model and 0.355 for persistence; still below
  the LR (0.398 with the same 7 inputs, 0.394 with 12). Validation (January) barely separates anything in NYC: the
  served model, persistence and LR are all 0.326-0.328 there and 0.335-0.398 on February-March.
* In all three tasks the mixture search on test is at or near the LR of the same rows and inputs, which is what the
  winning-rule classifiers missed by 0.008 (Madrid), 0.033 (Germany) and 0.059 (NYC).

## 5. Interpretability

Rule counts (fitting sample; "weighted": spread >= 0.25; "decisive": zeroing it changes >= 0.1 % of the fitting-sample
predictions):

| task | arm | rules per seed | weighted | decisive | mean antecedents |
|---|---|---|---|---|---|
| Madrid | served | 5 / 7 / 8 | - | - | 1.0-1.2 |
| Madrid | `mix_search_free` | 11 / 12 / 13 | 11 / 12 / 13 | 11 / 12 / 13 | 1.0-1.15 |
| NYC | served | 7 / 10 / 12 | - | - | 1.0-1.17 |
| NYC | `mix_search_free` | 18 / 16 / 17 | 11 / 10 / 11 | 18 / 16 / 17 | 1.06-1.38 |
| Germany | served | 6 / 7 / 10 | - | - | 1.0-1.43 |
| Germany | `mix_search_nonneg` (chosen) | 14 / 10 / 12 | 14 / 10 / 11 | 14 / 10 / 12 | 1.1-1.25 |

Every mixture keeps 10-18 short rules and nearly all of them change some predictions; in NYC a third of the rules have
weights under 0.25 that still flip near-tied rows (the NYC classes are close: accuracy 0.42).

**Germany, chosen seed 0** (`print_mixture`; weights `>= 0`, so each reads "votes for these classes"; the five rules
whose removal changes the most fitting-sample predictions, out of 14):

    Bias: Good -1.42 | Fair +0.22 | Moderate +0.96 | Poor or worse +0.24
    IF no2_last IS Good;              strongest class: Good;          weights: Good +5.53 | Fair +2.62 | Moderate +0.68 | Poor or worse +0.00   (removal changes 34.7 %)
    IF no2_last IS Fair;              strongest class: Good;          weights: Good +2.48 | Fair +1.79 | Moderate +0.47 | Poor or worse +0.00   (17.7 %)
    IF no2_yday_valid IS Fair;        strongest class: Fair;          weights: Good +1.05 | Fair +2.06 | Moderate +1.11 | Poor or worse +0.00   (12.4 %)
    IF no2_yday_valid IS Moderate;    strongest class: Moderate;      weights: Good +0.00 | Fair +1.68 | Moderate +2.35 | Poor or worse +1.74   (11.1 %)
    IF no2_yday_valid IS Good;        strongest class: Good;          weights: Good +3.78 | Fair +2.58 | Moderate +0.93 | Poor or worse +0.00   (8.8 %)

The other nine: `no2_yday_valid IS Poor or worse` (weights 0 / 0.94 / 2.60 / 4.16, 3.3 %), `no2_last IS Poor or
worse`, hour terms (Night, Morning rush, Evening),
`wind_speed IS Gentle to moderate breeze`, and three two-antecedent rules (`no2_yday_valid IS Good AND hour IS
Night`, `no2_last IS Moderate / Fair AND hour IS Midday`).

**Madrid, `mix_search_free` seed 2** (information only; unconstrained weights, relative over the classes):

    Bias: Buena +0.72 | Razonablemente buena +0.67 | Regular -0.51 | Desfavorable o peor -0.87
    IF no2_yday_valid IS Razonablemente buena; strongest class: Regular; weights: Buena -1.38 | Razonablemente buena +0.31 | Regular +0.73 | Desfavorable o peor +0.34   (23.4 %)
    IF no2_yday_valid IS Desfavorable o peor;  strongest class: Desfavorable o peor; weights: Buena -2.60 | Razonablemente buena -0.99 | Regular +1.03 | Desfavorable o peor +2.56   (4.2 %)
    IF valid_hour_local IS Mediodía;           strongest class: Buena; weights: Buena +1.70 | Razonablemente buena +0.97 | Regular -0.76 | Desfavorable o peor -1.91   (1.9 %)

**NYC, `mix_search_free` seed 2** (information only):

    Bias: baja -0.18 | normal +0.63 | alta +0.27 | muy alta -0.72
    IF rel_mean24h IS Low;  strongest class: baja;     weights: baja +0.71 | normal -0.09 | alta -0.34 | muy alta -0.28   (18.3 %)
    IF rel_mean24h IS High; strongest class: muy alta; weights: baja -0.48 | normal -0.27 | alta +0.25 | muy alta +0.51   (15.1 %)
    IF rel_lag1 IS normal;  strongest class: normal;   weights: baja +0.05 | normal +0.17 | alta -0.02 | muy alta -0.19   (10.3 %)

How to read it, honestly:

* The searched mixtures are **additive models over fuzzy terms**: almost every rule has one antecedent, so the model
  reads "each term of each input pushes the class scores up or down". That is readable, but it is not "a rule
  decides", and the map's "the rule that decided" disappears.
* **A rule's weights are conditional on the other rules firing with it.** "IF no2_last IS Fair -> strongest Good"
  (Germany) and "IF yesterday IS Razonablemente buena -> strongest Regular" (Madrid) look wrong in isolation; they
  correct the rules of the neighbouring terms that fire on the same rows (the terms overlap at the shoulders). Showing
  one rule with its weights alone would mislead; the per-prediction contributions (`mixture_contributions`) are the
  honest unit.
* **`>= 0` weights read better but are not "evidence for" in an absolute sense**: they equal the unconstrained ones
  shifted so that each rule's weakest class is 0, and only differences between classes matter. "+2.62 for Fair" on
  `no2_last IS Good` means "Fair is 2.91 below Good on this rule", not support for Fair.
* Negative unconstrained weights mean "less support than this rule gives the average class"; they are not evidence
  against the class.

## 6. What the Atlas contract would need to serve a mixture (not changed here; for A0)

1. `InferenceFamily.RULE_MIXTURE_CLASSIFIER = "rule_mixture_classifier"`: "class with the largest
   `b_c + sum_r W[r, c] * firing_r`".
2. `InferenceSpec` for that family: `allow_unknown` required, `rule_weighting` absent; new `mixture_weights:
   Literal["non_negative", "unconstrained"]`, `mixture_C: float`; `fallback` needs a value for "no rule fires and
   `allow_unknown` is false" (`"largest_bias"`).
3. `ModelRules.class_bias: dict[str, float]` (one per class of `target_scheme`).
4. `RuleDefinition.class_weights: dict[str, float]` (keys = the classes of `target_scheme`; `>= 0` when
   `non_negative`; may be negative otherwise, so the existing `weight` (ge=0, "multiplies the firing") cannot carry
   it), and `strongest_class: str`. The GA consequent is not the rule's meaning in a mixture: either `consequent`
   carries `strongest_class` and a new `search_consequent` keeps the GA's, or the UI must ignore `consequent` for this
   family. `duplicate_of` rules carry all-zero weights (validator).
5. `RuleTraceEntry` for that family: `weight` and `association_degree` null; new `class_contributions: dict[str,
   float]` = `class_weights[c] * firing_strength` (validator, parity tolerance).
6. `TracePrediction`: `winning_rule_id` null for this family (no rule decides; relax "label and winning_rule_id go
   together"); new `class_scores: dict[str, float]` = bias + summed contributions (validator: label = first argmax in
   class order; with `allow_unknown`, no firing rule -> no label and `fallback_used`); optionally
   `top_rule_ids: list[str]` (rules ordered by contribution to the predicted class) for the UI.
7. No probability field. If the softmax is ever exposed, name it `model_softmax` with the description "softmax of the
   scores of a fitted model, not a calibrated probability".
8. Importance: `RuleImportance.decided_share` / `n_decided` do not exist for a mixture. Proposal: `decisive_share`
   (share of predictions that change when the rule's weights are set to 0) and `top_contributor_share` (share where
   it adds the most to the predicted class), both measured, never probabilities; `VariableImportance` the same per
   input.
9. Rule map: `firing_strength`, `mean_activation`, `activation_frequency` stay valid. A class-contribution metric
   (`class_contribution` with a `class_label` parameter) would be signed for unconstrained weights; the map's scale
   would need to be diverging.
10. `SCHEMA_VERSION` 0.7.0 (new family and optional fields), schemas and fixtures regenerated, a compatibility test;
    `rules_export`, `atlas.explain.classifier` and `publish_parity` need a mixture path (parity = ex_fuzzy `predict`
    and `mixture_scores` row by row).

## 7. Conclusions, risks and open questions

1. **The two-stage design as first suggested (weights on the served rules) is not enough.** The served rule bases
   were selected for winning-rule macro-F1 and are 5-12 rules of mostly "yesterday's class"; a likelihood-fitted mixture
   on them is -0.010 to +0.014 on validation.
2. **Searching the rules under the mixture works**: it lifts validation in all three tasks, passes the pre-registered
   rule in Germany only, and on test it reaches the LR of the same rows and inputs (Madrid 0.421 vs 0.419, Germany
   0.551 vs 0.551) or gets closer to it (NYC 0.373 vs 0.398). It is also much more stable across seeds.
3. **Cost** is modest: 98-821 s per search fit on the large machine (one core each) against 13-107 s for the winning-rule search.
4. **Madrid is confounded by the build**: the winning-rule GA re-run on ex-fuzzy main / this machine nearly matches the
   mixture on validation. A test read of that control was not registered and was not made.
5. **Readability risks** (section 5): weights are conditional, not marginal; `>= 0` weights hide that only class
   differences matter; "the rule that decided" disappears, and the map needs per-class contributions instead. Rules go
   from 5-12 to 10-18. Whether this is worth it for the demo is a product decision (A0/A5).
6. **Selection noise**: NYC's 3.5-week validation window separates nothing (every model 0.31-0.33); Madrid's served
   arm has one weak seed that sets a wide margin. Both mixture search arms were very stable, so the margin was driven
   by the served arm.
7. **Nothing published.** To publish Germany's `mix_search_nonneg` seed 0 the contract needs section 6, the ex-fuzzy
   PR merged (or a local build, as for Water), and publication code for the new family.

## 8. Reproduce and compute

Section 0.8, with `configs/ml/de_no2_h6_mixture_experiment.json` for Germany. Wall time on the large machine (9 worker processes
per task, one thread each, Madrid and NYC concurrently, then Germany): Madrid 128 s (18 fits), NYC 828 s, Germany 255 s;
`final` 1-12 s. Per fit: search under the mixture Madrid 98-127 s, NYC 351-821 s (the `>= 0` searches about twice as
slow), Germany 146-251 s; winning-rule control 13-107 s; weights on the served rules < 1 s. Peak RSS per fit 0.6 GB
(Madrid, NYC), 1.9 GB (Germany). Directories: `artifacts/{madrid_no2_h6,nyc_pickups_h3,de_no2_h6}/experiments/
rule-mixture/` (`fits/`, `models/`, `val/`, `decision.json`, `final_test.json`, `TEST_READ`, `logs/`), copied back to
the workstation. Nothing was written under `artifacts/published`.
