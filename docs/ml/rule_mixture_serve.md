# The mixture of rules in every demo classifier (AT-041j, contract v0.7)

**Decision (the user, 2026-11-09):** take the mixture-of-rules inference of ex_fuzzy (PR 44, `docs/ml/rule_mixture.md`)
to every classifier of the demo: Germany NO₂ +1/+3/+6/+12/+24 h and New York taxi level +1/+3/+6/+24 h. Water
(`uk_water_do`) is a regression and stays; Madrid left the demo and is not retrained. The selected mixture arm is
published for every task **even where it does not beat the served winning-rule model**; the comparison below is reported,
not used to decide. **Follow-up decision (the user, same day):** New York +6 h, where the mixture lost, was diagnosed and
retried with a pre-registered gate (section 7); the gate was not met, so that task stays winning-rule and the demo serves
eight mixtures and one winning-rule classifier. **Second follow-up (the user, same day):** the pruning of the search
under the mixture was fixed in ex-fuzzy (PR 44, `5409bb8`: rules are pruned by their role in the mixture) and the nine
classifiers retrained against a pre-registered gate per task (section 8); no task met it, so nothing changed in the demo
and the pin moved to `5409bb8`, under which every served model reproduces bit for bit. **Release:** PR 44 was merged and
released as **ex-fuzzy 3.4.0** (PyPI; tag `v3.4.0` = `10d811b`, the code of `5409bb8` plus the version bump), which is
now the pin (`ex-fuzzy==3.4.0`); every check of section 8 made with `5409bb8` holds for it.

The score of class c is `b_c + Σ_r W[r, c] · firing_r` and the prediction is the first class of largest score. A weight
is a coefficient of a fitted multinomial logistic regression on the rule firings of the fitting sample: not a
probability, a confidence or a risk; the softmax of the scores is not served anywhere. In the centred form
`W[r, c] − mean_c W[r, c]` (same predictions) a rule **supports** some classes (+) and **suppresses** others (−), relative
to the rest; suppression is not "evidence against" a class.

## 0. Protocol (fixed in the brief before any fit; nothing was changed after seeing a number)

* **Arm:** "rules re-searched under the mixture" of `rule_mixture.md` (`mix_search_*`): the genetic search scores each
  candidate rule base as the mixture fitted on it (`mixture_search=True`); `mixture_C = 1.0`, no tuning.
* **Two weight arms:** `W ≥ 0` (`mix_search_nonneg`) and free weights (`mix_search_free`), seeds 0, 1, 2 each.
* **Same as the served model of each task:** rows, split, embargo, class-aware 30,000-row fitting sample
  (`subsample_keys.parquet` of the served experiment), terms (checked to be identical, partition by partition), inputs
  and rule-base shape and budget (nRules × nAnts, 150 generations × 60 individuals, no early stop, the served weighting
  for the search's pruning). Inputs: the ica4 4-input setting of the served Germany +6 h model; the 9 inputs of the
  `eaqi-justified` models for Germany +1/+3/+12/+24 h; the 7 relative-level inputs of `level-rel7` for New York.

  | task | served model | shape | inputs |
  |---|---|---|---|
  | `de_no2_h1` | `eaqi-justified-seed0` | 60 × 2 | no2_last, no2_lag1h, no2_lag3h, no2_lag24h, wind_speed, temperature, relative_humidity, valid_hour_local, valid_weekday |
  | `de_no2_h3` | `eaqi-justified-seed0` | 30 × 3 | the same 9 |
  | `de_no2_h6` | `ica4-yday-seed2` | 30 × 2, unweighted | no2_yday_valid, no2_last, valid_hour_local, wind_speed |
  | `de_no2_h12` | `eaqi-justified-seed1` | 60 × 4 | the same 9 as +1 h |
  | `de_no2_h24` | `eaqi-justified-seed0` | 60 × 4 | the same 9 as +1 h |
  | `nyc_pickups_h1` | `level-rel7-seed0` | 30 × 2 | rel_lag1, rel_lag2, rel_lag24, rel_lag168, local_hour, local_dow, rel_mean24h |
  | `nyc_pickups_h3` | `level-rel7-seed0` | 60 × 2 | the same 7 |
  | `nyc_pickups_h6` | `level-rel7-seed0` | 30 × 3 | the same 7 |
  | `nyc_pickups_h24` | `level-rel7-seed0` | 60 × 2 | the same 7 |

* **Choice (validation only):** the arm of highest mean validation macro-F1; arms within 0.005 of it are tied and the tie
  goes to `W ≥ 0`; the published seed is the chosen arm's best validation seed. No margin over the served model.
* **Test, read once per task** (`TEST_READ` marker) for the served arm and the chosen arm (3 seeds each), next to
  persistence, "same hour yesterday" where the task has it (Germany +6 h `persistence_24h`, New York
  `persistence_rel_lag24`), and a logistic regression and a random forest **refitted on the same fitting sample with the
  model's inputs** (in Germany they must reproduce the `*_subsample` rows of the served `metrics.json`; in New York
  those used the 12 baseline inputs, so they are quoted as well).
* Config: `configs/ml/<task>_mixture_serve_experiment.json` (block `serve`); code: `atlas.ml.experiment_mixture`
  (stages `arms`, `decide`, `final --test`, `runs`, `summary`).

## 1. What was run

* **Machine: the large machine** (DGX Spark, aarch64, 20 CPUs, 121 GB). Code: this PR. Library: a clean checkout of ex-fuzzy
  `20c1095` (PR 44; every fit records `3.3.1+g20c1095`). Python: an existing venv on that machine, used read-only
  (numpy 2.5.3, pandas 3.0.6, scikit-learn 1.9.1, scipy 1.18.1, pymoo 0.6.2); the fits ran with a `duckdb` stub
  (`atlas.contracts` imports it for the observation validator, never called), the later stages and the test runs with
  aarch64 wheels of duckdb, fastapi, uvicorn, shapely, pyproj and pyshp unpacked into a separate directory on
  `PYTHONPATH`. Nothing was installed.
* **Parallelism:** one process for the five Germany tasks and one for the four New York tasks, 8 workers each, one BLAS
  thread per fit; Germany +24 h was moved to its own process (6 workers) once the 60 × 4 searches proved slow, and the
  Germany process was guarded to stop before +24 h (it never had to: +24 h was on disk first). Every fit is a
  `[k/N]` line of the logs (`logs/arms-*.log`, copied back).
* **Fit times (one core each):** Germany +1 h 592-861 s, +3 h 357-927 s, +6 h 126-371 s, +12 h 1067-1623 s,
  +24 h 670-1882 s; New York +1 h 218-496 s, +3 h 334-825 s, +6 h 195-685 s, +24 h 313-1161 s. Wall time: about
  63 min (3,808 s) for all 54 searches. Peak RSS per fit: 1.9-2.4 GB in Germany (the forked table), 0.62-0.65 GB in New York. Every mixture fit converged (L-BFGS-B).
* **Same rows as served:** for every task the served seed of the `served` arm reproduces the validation macro-F1 of its
  `metrics.json` (`final_test.json` `checks`), and the logistic regression refitted on the fitting sample with the model's
  inputs reproduces the `logistic_regression_subsample` row of the served `metrics.json` in Germany.
* **Reproducibility:** the 12 searches that AT-041i had already run (Germany +6 h and New York +3 h, both weight arms,
  seeds 0-2) came out bit for bit identical (rules, weights, biases, validation metrics).
* **Deviation, none in the protocol.** One operational note: Germany loads its 27 M-row tables compactly, with every
  input but the persistence one in float32 (`atlas.ml.compact_load`, relative error < 6e-8), as the served models did;
  publication scores the float64 table. The two disagree on a handful of rows where a firing is ~1e-7 at a term shoulder:
  0 of 2,964,241 test rows in Germany +1 h, 85 of 2,960,236 in +3 h, 0 in +6 h, 74 of 2,976,594 in +24 h, 101 of 2,954,472 in
  +12 h; never in New York (no compact load). The run directory's `metrics.json` is the float32 one, the served
  predictions the float64 one.

## 2. Validation and test

Macro-F1. "3 seeds" = mean ± sd over seeds 0-2; the published seed is the chosen arm's best validation seed. Validation
is 2024 for Germany and 2025-01-08 to 02-01 for New York; test is 2025 for Germany and 2025-02-08 to 04-01 for New York.
The test of the arm that was not chosen was not read.

| task | model | val macro-F1 | test macro-F1 |
|---|---|---|---|
| de_no2_h1 | winning rule, served (seed 0) | 0.628 | 0.652 |
|  | winning rule, served arm (3 seeds) | 0.623 ± 0.004 | 0.653 ± 0.001 |
|  | **mixture `mix_search_nonneg`, published (seed 1)** | **0.637** | **0.664** |
|  | mixture `mix_search_nonneg` (3 seeds) | 0.636 ± 0.001 | 0.662 ± 0.002 |
|  | mixture `mix_search_free` (3 seeds, not tested) | 0.635 ± 0.001 | - |
|  | persistence | 0.632 | 0.658 |
|  | LR, fitting sample (served metrics.json) | 0.629 | 0.660 |
|  | RF, fitting sample (served metrics.json) | 0.649 | 0.677 |
|  | LR refit, fitting sample, model inputs | 0.629 | 0.660 |
|  | RF refit, fitting sample, model inputs | 0.649 | 0.677 |
| de_no2_h3 | winning rule, served (seed 0) | 0.502 | 0.528 |
|  | winning rule, served arm (3 seeds) | 0.497 ± 0.005 | 0.522 ± 0.006 |
|  | **mixture `mix_search_nonneg`, published (seed 2)** | **0.518** | **0.542** |
|  | mixture `mix_search_nonneg` (3 seeds) | 0.516 ± 0.002 | 0.541 ± 0.002 |
|  | mixture `mix_search_free` (3 seeds, not tested) | 0.517 ± 0.003 | - |
|  | persistence | 0.504 | 0.527 |
|  | LR, fitting sample (served metrics.json) | 0.501 | 0.539 |
|  | RF, fitting sample (served metrics.json) | 0.540 | 0.572 |
|  | LR refit, fitting sample, model inputs | 0.501 | 0.539 |
|  | RF refit, fitting sample, model inputs | 0.540 | 0.572 |
| de_no2_h6 | winning rule, served (seed 2) | 0.477 | 0.518 |
|  | winning rule, served arm (3 seeds) | 0.473 ± 0.005 | 0.517 ± 0.007 |
|  | **mixture `mix_search_nonneg`, published (seed 0)** | **0.509** | **0.554** |
|  | mixture `mix_search_nonneg` (3 seeds) | 0.507 ± 0.002 | 0.551 ± 0.003 |
|  | mixture `mix_search_free` (3 seeds, not tested) | 0.511 ± 0.003 | - |
|  | persistence | 0.438 | 0.455 |
|  | same hour yesterday (`persistence_24h`) | 0.484 | 0.536 |
|  | LR, fitting sample (served metrics.json) | 0.506 | 0.551 |
|  | RF, fitting sample (served metrics.json) | 0.525 | 0.569 |
|  | LR refit, fitting sample, model inputs | 0.506 | 0.551 |
|  | RF refit, fitting sample, model inputs | 0.525 | 0.569 |
| de_no2_h12 | winning rule, served (seed 1) | 0.417 | 0.436 |
|  | winning rule, served arm (3 seeds) | 0.412 ± 0.005 | 0.432 ± 0.007 |
|  | **mixture `mix_search_nonneg`, published (seed 0)** | **0.430** | **0.455** |
|  | mixture `mix_search_nonneg` (3 seeds) | 0.430 ± 0.001 | 0.455 ± 0.001 |
|  | mixture `mix_search_free` (3 seeds, not tested) | 0.431 ± 0.002 | - |
|  | persistence | 0.416 | 0.438 |
|  | LR, fitting sample (served metrics.json) | 0.419 | 0.456 |
|  | RF, fitting sample (served metrics.json) | 0.449 | 0.482 |
|  | LR refit, fitting sample, model inputs | 0.419 | 0.456 |
|  | RF refit, fitting sample, model inputs | 0.449 | 0.482 |
| de_no2_h24 | winning rule, served (seed 0) | 0.467 | 0.512 |
|  | winning rule, served arm (3 seeds) | 0.466 ± 0.001 | 0.512 ± 0.002 |
|  | **mixture `mix_search_nonneg`, published (seed 0)** | **0.478** | **0.525** |
|  | mixture `mix_search_nonneg` (3 seeds) | 0.477 ± 0.002 | 0.524 ± 0.001 |
|  | mixture `mix_search_free` (3 seeds, not tested) | 0.475 ± 0.001 | - |
|  | persistence | 0.470 | 0.519 |
|  | LR, fitting sample (served metrics.json) | 0.472 | 0.525 |
|  | RF, fitting sample (served metrics.json) | 0.490 | 0.539 |
|  | LR refit, fitting sample, model inputs | 0.472 | 0.525 |
|  | RF refit, fitting sample, model inputs | 0.490 | 0.539 |
| nyc_pickups_h1 | winning rule, served (seed 0) | 0.398 | 0.412 |
|  | winning rule, served arm (3 seeds) | 0.382 ± 0.019 | 0.397 ± 0.013 |
|  | **mixture `mix_search_nonneg`, published (seed 1)** | **0.409** | **0.430** |
|  | mixture `mix_search_nonneg` (3 seeds) | 0.405 ± 0.003 | 0.431 ± 0.001 |
|  | mixture `mix_search_free` (3 seeds, not tested) | 0.407 ± 0.006 | - |
|  | persistence | 0.401 | 0.425 |
|  | same hour yesterday (`persistence_rel_lag24`) | 0.351 | 0.379 |
|  | LR, fitting sample (served metrics.json), 12 baseline inputs | 0.399 | 0.447 |
|  | RF, fitting sample (served metrics.json), 12 baseline inputs | 0.401 | 0.434 |
|  | LR refit, fitting sample, model inputs | 0.397 | 0.451 |
|  | RF refit, fitting sample, model inputs | 0.411 | 0.438 |
| nyc_pickups_h3 | winning rule, served (seed 0) | 0.328 | 0.335 |
|  | winning rule, served arm (3 seeds) | 0.311 ± 0.015 | 0.313 ± 0.028 |
|  | **mixture `mix_search_nonneg`, published (seed 2)** | **0.325** | **0.371** |
|  | mixture `mix_search_nonneg` (3 seeds) | 0.322 ± 0.003 | 0.369 ± 0.003 |
|  | mixture `mix_search_free` (3 seeds, not tested) | 0.325 ± 0.006 | - |
|  | persistence | 0.327 | 0.355 |
|  | same hour yesterday (`persistence_rel_lag24`) | 0.310 | 0.345 |
|  | LR, fitting sample (served metrics.json), 12 baseline inputs | 0.326 | 0.394 |
|  | RF, fitting sample (served metrics.json), 12 baseline inputs | 0.328 | 0.385 |
|  | LR refit, fitting sample, model inputs | 0.326 | 0.398 |
|  | RF refit, fitting sample, model inputs | 0.329 | 0.384 |
| nyc_pickups_h6 | winning rule, served (seed 0) | 0.314 | 0.353 |
|  | winning rule, served arm (3 seeds) | 0.306 ± 0.008 | 0.327 ± 0.022 |
|  | **mixture `mix_search_nonneg`, published (seed 1)** | **0.290** | **0.281** |
|  | mixture `mix_search_nonneg` (3 seeds) | 0.290 ± 0.000 | 0.282 ± 0.000 |
|  | mixture `mix_search_free` (3 seeds, not tested) | 0.289 ± 0.001 | - |
|  | persistence | 0.278 | 0.312 |
|  | same hour yesterday (`persistence_rel_lag24`) | 0.277 | 0.305 |
|  | LR, fitting sample (served metrics.json), 12 baseline inputs | 0.286 | 0.351 |
|  | RF, fitting sample (served metrics.json), 12 baseline inputs | 0.287 | 0.310 |
|  | LR refit, fitting sample, model inputs | 0.288 | 0.357 |
|  | RF refit, fitting sample, model inputs | 0.290 | 0.342 |
| nyc_pickups_h24 | winning rule, served (seed 0) | 0.343 | 0.373 |
|  | winning rule, served arm (3 seeds) | 0.329 ± 0.017 | 0.358 ± 0.016 |
|  | **mixture `mix_search_nonneg`, published (seed 0)** | **0.341** | **0.387** |
|  | mixture `mix_search_nonneg` (3 seeds) | 0.336 ± 0.005 | 0.384 ± 0.003 |
|  | mixture `mix_search_free` (3 seeds, not tested) | 0.335 ± 0.003 | - |
|  | persistence | 0.351 | 0.380 |
|  | same hour yesterday (`persistence_rel_lag24`) | 0.290 | 0.330 |
|  | LR, fitting sample (served metrics.json), 12 baseline inputs | 0.317 | 0.380 |
|  | RF, fitting sample (served metrics.json), 12 baseline inputs | 0.312 | 0.364 |
|  | LR refit, fitting sample, model inputs | 0.314 | 0.388 |
|  | RF refit, fitting sample, model inputs | 0.328 | 0.388 |

**Choice.** `W ≥ 0` in all nine tasks: it had the higher validation mean in Germany +1 and +24 h and New York +6 and
+24 h, and was within 0.005 of the free arm (so tied, and the tie goes to `W ≥ 0`) in Germany +3 h (0.516 vs 0.517),
+6 h (0.507 vs 0.511), +12 h (0.430 vs 0.431), New York +1 h (0.405 vs 0.407) and +3 h (0.322 vs 0.325).

**Reading, task by task (honest comparison; nothing here changed what is published).**

* **Germany, every horizon: the mixture beats the served winning-rule model** on validation and on test, by +0.009 to
  +0.032 on validation (published seed against the served seed) and +0.012 to +0.036 on test, with seed sd of 0.001-0.003
  against 0.001-0.007 for the served arms. On test it ties or slightly beats the logistic regression of the same rows and
  inputs (+1 h 0.664 vs 0.660, +3 h 0.542 vs 0.539, +6 h 0.554 vs 0.551, +12 h 0.455 vs 0.456, +24 h 0.525 vs 0.525) and
  is still 0.013-0.030 below the random forest. +1, +12 and +24 h are close to persistence on validation (+0.005,
  +0.014, +0.008) and above it on test; +6 h is well above both persistence and same hour yesterday (0.554 vs 0.536).
* **New York +1, +3 and +24 h: better on test**, 0.430 vs 0.412, 0.371 vs 0.335, 0.387 vs 0.373; on validation the
  served seed (the best of its arm's three) is level or slightly above (+1 h 0.409 vs 0.398 above; +3 h 0.325 vs 0.328;
  +24 h 0.341 vs 0.343), while the mixture's own seeds are much more stable (sd 0.003-0.005 against 0.015-0.019). The
  three-week January validation window barely separates anything in New York (persistence and the LR are within 0.01
  of every model there). On test the mixture is above persistence (+1 h 0.430 vs 0.425, +3 h 0.371 vs 0.355, +24 h 0.387
  vs 0.380) and below the LR of the same inputs (0.451, 0.398, 0.388).
* **New York +6 h: the mixture is clearly worse** (validation 0.290 vs 0.314, test 0.281 vs 0.353; below persistence,
  0.312, and same hour yesterday, 0.305, on test). The search converged to 6 rules of which only 2 have a weight spread
  ≥ 0.25 (one rule, `rel_mean24h IS High`, is the top rule of 64 % of the predictions); both weight arms and all six
  seeds landed there (validation 0.289-0.290). Why the search under the mixture collapses to so few rules here was not
  investigated here (section 7 does). It was published first, as decided; after the pre-registered retry of section 7
  (60 × 2, five seeds per arm) **the served model of `nyc_pickups_h6` is the winning-rule one again**.


## 3. Rules, weights and suppression

Rule counts of the published fits (fitting sample). "Weight spread": `max_c W − min_c W ≥ 0.25`; "decisive": zeroing the
rule's weights changes at least 0.1 % of the fitting-sample predictions; **"suppressing": at least one centred weight
≤ −0.25** (a fully firing rule lowers that class's score by at least 0.25 in log-odds relative to the rule's average class);
"mostly suppressing": a suppressing rule whose largest centred effect is negative (`|min| > max`).

| task | published run | rules | weight spread >= 0.25 | decisive (fit sample) | suppressing (centred <= -0.25) | mostly suppressing | served model rules |
|---|---|---|---|---|---|---|---|
| de_no2_h1 | `mixture-nonneg-seed1` | 14 | 13 | 14 | 13 of 14 (93%) | 6 | 10 |
| de_no2_h3 | `mixture-nonneg-seed2` | 15 | 15 | 15 | 13 of 15 (87%) | 7 | 7 |
| de_no2_h6 | `mixture-nonneg-seed0` | 14 | 14 | 14 | 13 of 14 (93%) | 8 | 10 |
| de_no2_h12 | `mixture-nonneg-seed0` | 19 | 19 | 19 | 18 of 19 (95%) | 10 | 21 |
| de_no2_h24 | `mixture-nonneg-seed0` | 19 | 18 | 17 | 16 of 19 (84%) | 8 | 15 |
| nyc_pickups_h1 | `mixture-nonneg-seed1` | 13 | 10 | 13 | 6 of 13 (46%) | 2 | 10 |
| nyc_pickups_h3 | `mixture-nonneg-seed2` | 15 | 8 | 15 | 4 of 15 (27%) | 1 | 7 |
| nyc_pickups_h6 | `mixture-nonneg-seed1` | 6 | 2 | 6 | 2 of 6 (33%) | 1 | 8 |
| nyc_pickups_h24 | `mixture-nonneg-seed0` | 16 | 9 | 16 | 5 of 16 (31%) | 0 | 11 |

* The rule bases are 6-19 rules, nearly all single-antecedent (an additive model over fuzzy terms, as in AT-041i).
* **Suppression is the rule, not the exception, in Germany** (84-95 % of the rules suppress some class by ≥ 0.25):
  a term of NO₂ supports its own and neighbouring classes and pushes the far classes down. In New York it is a minority
  (27-46 %): most relative-level rules nudge one or two classes up and the rest down by less than 0.25.
* In a `W ≥ 0` fit the suppressed class is the one with weight 0 (and the classes just above it): the fitted weights
  never show it, the centred ones do. Example, Germany +1 h `R05`: fitted `Good +0.00 | Fair +2.49 | Moderate +3.70 |
  Poor or worse +2.77`, centred `Good −2.24 | Fair +0.25 | Moderate +1.46 | Poor or worse +0.53`: it mostly suppresses Good.

**Example: Germany +6 h, `exfuzzy-de_no2_h6-mixture-nonneg-seed0`** (14 rules; the three that are the top rule most often;
"top" = share of the published 2025 predictions where the rule supports the predicted class the most, "decisive" =
share whose class would change without the rule):

    Bias: Good −1.42 | Fair +0.22 | Moderate +0.96 | Poor or worse +0.24
    R02 IF no2_last IS Good        strongest Good      fitted  Good +5.53 | Fair +2.62 | Moderate +0.68 | Poor or worse +0.00
                                                        centred Good +3.32 | Fair +0.41 | Moderate −1.53 | Poor or worse −2.21   top 40.2 %, decisive 45.5 %
    R01 IF no2_yday_valid IS Fair  strongest Fair      fitted  Good +1.05 | Fair +2.06 | Moderate +1.11 | Poor or worse +0.00
                                                        centred Good −0.00 | Fair +1.00 | Moderate +0.05 | Poor or worse −1.05   top 27.0 %, decisive 12.8 %
    R03 IF no2_yday_valid IS Moderate  strongest Moderate  fitted  Good +0.00 | Fair +1.68 | Moderate +2.35 | Poor or worse +1.74
                                                        centred Good −1.44 | Fair +0.23 | Moderate +0.91 | Poor or worse +0.30   top 15.2 %, decisive 9.5 %

They are the AT-041i rules of the same seed (the fits are identical). R03 is also the strongest "mostly suppressing"
rule of the task: what it does most is lower Good. New York +3 h `R02 IF rel_mean24h IS High` (centred `baja −0.51 |
normal −0.28 | alta +0.26 | muy alta +0.52`, top 32 %, decisive 42 %) is the New York analogue.


## 4. Publication and parity

* **Run directories** (written on the large machine by `runs`, copied back): `artifacts/<task>/mixture-nonneg-seed<k>` (model, rules
  of contract v0.7, `metrics.json` with the served run's baseline rows, which are the same rows, split and fitting
  sample, and the mixture's own rows and readability rows, test-period predictions, manifest). Before publishing, each
  pickle was loaded on the workstation and re-predicted its own `predictions.parquet` (numpy 2.5.3 → 2.3.5): see the float32
  note of section 1 for the only differences.
* **Published into `artifacts/published-v07/`**, not into `artifacts/published/`: the two demos that run now (:8000 and
  the `atlas-preview` unit on :8001) read `artifacts/published/registry.json` with contract v0.6.1 code and PyPI ex_fuzzy
  3.3.1, which can open neither a v0.7 `rules.json` (unknown fields are refused) nor a mixture pickle
  (`ex_fuzzy.rule_mixture`). `published-v07` holds hard-linked copies of the ten previously served model directories
  (kept, unchanged), the nine new ones and a registry (schema 0.7.0) whose nine classifier tasks point at the mixtures and
  `uk_water_do` at the same Water model. Promotion once this PR is merged and the demos run v0.7 code with the pinned
  commit (`EXFUZZY_SRC`): `cp -al artifacts/published-v07/exfuzzy-*-mixture-* artifacts/published/ && cp
  artifacts/published-v07/registry.json artifacts/published/registry.json`.
* **Parity of every published row** (`python -m atlas.ml.publish_parity`, mixture path), all nine `ok`: 15,669,243
  rows with inputs (Germany 3.0-3.1 M each, New York 137,170 each); label, firing, centred contribution to the predicted
  class, decisive flag and top rule (and its share) equal to ex_fuzzy's, exactly; 28,800 API rule traces (400 per
  month) whose `class_scores` and `class_contributions` equal ex_fuzzy `mixture_scores` and `mixture_contributions` on
  the same rows bit for bit; `rules.json` weights and biases equal `coef_` / `intercept_`. No published row has two class
  scores within 1e-12. New York withholds the label of 19,993-20,757 rows without a reference level, as before.
  `atlas.services.verify` passes for the whole directory. Records: `artifacts/mixture-serve-logs/parity-*.json`.
* **The previously served models under the pinned commit:** recomputing their firing tables and predictions with ex_fuzzy
  `20c1095` (`publish_parity --tables`) gives the published files bit for bit, 245.9 M activation records and 19.7 M predictions, none different
  (`artifacts/mixture-serve-logs/tables_served_20c1095.json`); 3,000 API traces of them (300 per model) are identical
  under v0.6.1 code with PyPI 3.3.1 and under this code with `20c1095`, apart from the new null fields.
* **Publication cost (the workstation):** 78-102 s and about 2 GB peak RSS for a Germany task (3.8 M input rows, 54-73 M
  activation records), 2-4 s for New York.
* **Integration tests** (`tests/integration`, what CI runs on the QA bundle) pass on the bundle built from
  `published-v07` (New York +1 h, Water, Germany +6 h): 123 passed, 129 skipped (opt-in, Madrid not served, data not on
  that machine).


## 5. Reading, risks and open questions

1. **Germany gains everywhere, New York mostly, New York +6 h loses.** The mixture reaches the logistic regression of the
   same rows and inputs in Germany and gets closer to it in New York; the random forest stays above it everywhere. At New
   York +6 h the mixture loses (−0.07 test macro-F1); its cause and the retry are in section 7, and that task stays
   winning-rule: the demo serves eight mixtures and one winning-rule classifier side by side.
2. **Validation in New York is weak evidence** (three January weeks; see AT-041i §7.6), so the New York gains are mostly
   test gains, read once.
3. **Weights are conditional and relative.** A rule's centred weights say how it moves the class scores given the other
   rules firing with it; neighbouring terms overlap at the shoulders, so one rule alone can look odd (Germany +3 h
   `no2_last IS Fair` supports Good most). The per-prediction view (centred contributions of the firing rules, the bias
   and the scores) is the honest unit; the top rule is the one that supports the predicted class the most, and it did not
   decide alone.
4. **Top rule under `W ≥ 0` vs free weights:** defined on centred contributions, so it is the same function of the model
   for both; on raw `W ≥ 0` contributions it would favour rules that suppress the winner less than the others.
5. **Float32 inputs in the Germany experiments** (section 1): the run's `metrics.json` and the served predictions differ on
   0-101 rows of about 3 M per task.
6. **Dependency on an unreleased commit** until ex_fuzzy releases the mixture (`docs/reproduce.md`); the workstation needs
   `EXFUZZY_SRC` for anything that opens these models.


## 7. New York +6 h: why the search collapsed, and a pre-registered retry

### 7.1 Cause (fitting sample and configs only; no validation number was used)

* **Class balance is not the cause.** The target is a level relative to each zone's own norm, so its shares are the same
  at every horizon: training 0.255 / 0.497 / 0.202 / 0.046 (baja / normal / alta / muy alta) at +1, +3, +6 and +24 h,
  validation about 0.26 / 0.46 / 0.20 / 0.08, test about 0.125 / 0.383 / 0.283 / 0.208; the fitting samples have the same
  class counts within 12 rows (8,076 / 11,285 / 7,187 / 3,452 at +6 h).
* **The one setting that differs at +6 h is the shape:** 30 rules × **3** antecedents, chosen by the per-horizon shape
  selection of AT-080; +1 h is 30 × 2, +3 h and +24 h 60 × 2. Terms (3 per input), budget (150 × 60, no early stop),
  dominance-score weighting, pruning tolerance 0 and sampling power 0.5 are the same at every horizon.
* **The pruning keeps only about ten rules at +6 h, whatever the shape.** In the search under the mixture every
  candidate rule base is first pruned as a winning-rule model is finalised: a rule that never wins a fitting row
  correctly under winning-rule arbitration is deleted (ex_fuzzy `prune_bad_rules`, accuracy 0), and only then the mixture
  is fitted on the survivors. Counted over every candidate evaluated in one full search (fitting sample, seed 0, `W ≥ 0`;
  `artifacts/mixture-serve-logs/diag_pruning.json`, script `diag_pruning.py` next to it):

  | task, shape | candidate rules before pruning | kept (mean) | final rules | fit-sample macro-F1 |
  |---|---|---|---|---|
  | +3 h, 60 × 2 (reference) | 42.2 | 16.7 | 17 | 0.345 |
  | +6 h, 30 × 3 (served shape) | 24.9 | 10.9 | 10 | 0.315 |
  | +6 h, 30 × 2 | 18.6 | 8.3 | 4 | 0.315 |
  | +6 h, 60 × 2 | 46.8 | 10.6 | 10 | 0.313 |
  | +6 h, 60 × 3 | 44.6 | 9.6 | 9 | 0.314 |

  Every removal was a zero-accuracy removal (none fell under the dominance-score tolerance).
* **Fitness.** The +6 h mixtures reach 0.313-0.315 macro-F1 on their own fitting sample, below the served winning-rule
  model's 0.349 on the same rows; at +3 h and +24 h the mixtures are closer (0.345-0.350 against 0.354; 0.323-0.327
  against 0.350) and keep 15-18 rules.
* **Reading.** At +6 h only about ten rules of any candidate win anything under winning-rule arbitration, so the mixture
  is fitted on about ten mostly single-term rules (two to six with weight spread ≥ 0.25) and stays below the winning-rule
  search, which optimises that arbitration directly. More rule slots or fewer antecedents do not change it (the
  table). The pruning is ex_fuzzy's (`MixtureObjective` prunes "as a fitted model is finalised"); changing it is an
  ex-fuzzy change and was not done here (section 8 does it, after the user approved it).

### 7.2 Pre-registration (written and committed before any fit of these arms)

* **Arms:** `mix_search_nonneg` and `mix_search_free` with **60 rules × 2 antecedents**, the shape of New York +3 h and
  +24 h (+1 h uses 30 × 2; every other New York horizon uses 2 antecedents, +6 h alone 3). Everything else is the served
  +6 h model's: its 30,000-row fitting sample, terms, inputs, budget (150 generations × 60, no early stop), dominance-score
  pruning with tolerance 0, `mixture_C = 1.0`. **Seeds 0-4** (five per arm). Config
  `configs/ml/nyc_pickups_h6_mixture_retry_experiment.json`, experiment `mixture-retry-r60a2`.
* **Choice between the two arms:** as for the nine tasks (highest mean validation macro-F1; within 0.005 the tie goes to
  `W ≥ 0`); the published seed is the chosen arm's best validation seed.
* **Gate:** the chosen arm is served only if its **5-seed mean validation macro-F1 is at least 0.324**, that is the served
  winning-rule model's 0.314 plus a margin of 0.010. The margin is the served arm's seed sd on this validation window
  (0.008, seeds 0.314 / 0.306 / 0.299) rounded up, and twice the 0.005 tie tolerance: a smaller gain is within the seed
  noise of the served model itself. The comparison is with the served seed, the best of its arm's three.
* **Otherwise** `nyc_pickups_h6` stays the winning-rule model `exfuzzy-nyc_pickups_h6-level-rel7-seed0` in
  `published-v07/registry.json`, next to the eight mixtures.
* **Test**, read once at the end whatever the gate says: the served arm's three seeds and the chosen arm's five, with
  persistence, same hour yesterday and the LR / RF refitted on the fitting sample with the model's inputs.
* The 30 × 3 arms of section 2 stay recorded as they are (`mixture-serve`); the model published from them,
  `exfuzzy-nyc_pickups_h6-mixture-nonneg-seed1`, stays on disk whatever the outcome.

### 7.3 Result

Validation (`decide`, `artifacts/nyc_pickups_h6/experiments/mixture-retry-r60a2/decision.json`):

| arm (60 × 2) | seeds 0-4 | mean ± sd | rules (mean) | weight spread ≥ 0.25 (mean) |
|---|---|---|---|---|
| `mix_search_nonneg` (chosen: tied with free, so `W ≥ 0`) | 0.289 / 0.289 / 0.288 / 0.290 / 0.290 | **0.289 ± 0.001** | 8.2 | 4.0 |
| `mix_search_free` | 0.289 / 0.288 / 0.290 / 0.290 / 0.289 | 0.289 ± 0.001 | 7.8 | 4.0 |
| served winning rule `level-rel7` (seeds 0-2) | 0.314 / 0.306 / 0.299 | 0.306 ± 0.008 | 7.0 | - |

**Gate not met** (0.289 < 0.324): **`nyc_pickups_h6` stays the winning-rule model `exfuzzy-nyc_pickups_h6-level-rel7-seed0`**
in `published-v07/registry.json`, next to the eight mixtures. No run directory was written for the retry; the 30 × 3
mixture published earlier (`exfuzzy-nyc_pickups_h6-mixture-nonneg-seed1`) stays on disk, unregistered.

Test, read once afterwards (`final_test.json`; the served seed reproduces its `metrics.json`, 0.314 / 0.353):

| model | validation | test |
|---|---|---|
| winning rule, served (seed 0) | 0.314 | 0.353 |
| winning rule, served arm (3 seeds) | 0.306 ± 0.008 | 0.327 ± 0.022 |
| mixture `mix_search_nonneg` 60 × 2 (5 seeds) | 0.289 ± 0.001 | 0.282 ± 0.001 |
| persistence / same hour yesterday (`persistence_rel_lag24`) | 0.278 / 0.277 | 0.312 / 0.305 |
| LR refit, fitting sample, model inputs | 0.288 | 0.357 |
| RF refit, fitting sample, model inputs | 0.290 | 0.342 |
| LR / RF, served `metrics.json` (12 baseline inputs) | 0.286 / 0.287 | 0.351 / 0.310 |

On this validation window every model with these inputs except the winning-rule one sits at 0.28-0.29; the mixture is
the LR's level there but far below it on test (0.282 against 0.357), consistent with its handful of effective rules.

**Both families side by side.** The API serves each task by its own `rules.json` family (`/predictions`:
`decided_by_rule_id` for +6 h, `top_rule_id` for the others; `/rule-territories?measure=winner_share` 200 for +6 h, 422
for a mixture; traces and importance per family), checked on `published-v07` and in
`tests/api/test_v07_mixture.py::test_a_winning_rule_and_a_mixture_classifier_are_served_side_by_side`. The parity tool
dispatches by family; its winning-rule path compared published labels on rows the publication withholds (no reference
level) and so could never pass on New York (0.853 on +6 h, the same with main's code and PyPI 3.3.1). It now leaves those
rows out, as the mixture path does, and the +6 h winning-rule model passes: 137,170 rows, 20,186 withheld, labels, winners
and association degree equal to ex_fuzzy.

## 8. Pruning by the rules' role in the mixture (ex-fuzzy PR 44 follow-up)

**Decision (the user, 2026-11-09):** fix the pruning of the search under the mixture in ex-fuzzy PR 44 (section 7.1 found
that it deletes every rule that never wins a fitting row correctly, before the mixture is fitted) and retrain the nine
classifiers; #107 waits for the new models.

### 8.1 The change in ex-fuzzy (`5409bb8` on `feat/rule-mixture`, PR 44)

* With `mixture_search=True` every candidate, and the final model, are now pruned by the rules' role in the mixture
  (`mixture_pruning='mixture'`, the new default with `mixture_search`): the weights are fitted on every rule; a rule is
  deleted when its **effect**, `max_n firing[n, r] · max_c |W[r, c] − mean_c W[r, c]|` (the largest centred contribution
  over the fitting rows, in log-odds), is at most `mixture_prune_threshold`; the weights are fitted again, from scratch,
  on the survivors, which is the mixture the final model gets. A rule that never wins a row but lowers a class
  (a suppressor) stays. `mixture_pruning='winning_rule'` is the previous pruning.
* **Threshold 0.02** (ex-fuzzy default, used here unchanged). It removes the rules that never fire, the repeats (a rule
  with the antecedents of an earlier one shares its weight row) and rules practically without effect: removing such a
  rule moves no class-score difference by more than 0.04. Chosen before any fit of section 8.2 from a diagnostic on the
  fitting samples only (`diag_effects.py`: short searches, `W ≥ 0`, seed 0, 8 generations, every candidate's effects
  recorded with the threshold at 0; `artifacts/mixture-serve-logs/diag_effects.json`):

  | task, shape | candidates | rules per candidate | kept by the winning-rule pruning | effect of those, 1st / 5th percentile | kept at 0.02 | of them deleted by the winning-rule pruning (clear suppressors, centred ≤ −0.25) | kept by winning-rule pruning but under 0.02 |
  |---|---|---|---|---|---|---|---|
  | `de_no2_h6`, 30 × 2 | 181 | 23.1 | 13.4 | 0.094 / 0.156 | 20.1 | 6.7 (5.0) | 0.00 |
  | `de_no2_h24`, 60 × 4 | 203 | 47.6 | 24.3 | 0.120 / 0.195 | 46.8 | 22.5 (17.4) | 0.05 |
  | `nyc_pickups_h6`, 30 × 3 | 208 | 24.6 | 15.8 | 0.022 / 0.053 | 23.9 | 8.2 (2.3) | 0.13 |
  | `nyc_pickups_h3`, 60 × 2 | 206 | 45.0 | 12.8 | 0.030 / 0.057 | 39.8 | 28.0 (5.3) | 1.00 |

  Between 0 and 0.02 almost nothing changes: the threshold sits below the effects of practically every rule the
  winning-rule pruning keeps. Most of the last column are repeats, which the winning-rule pruning can keep (a repeat
  wins rows for its own class) and the mixture gives no weights, so they go at any threshold: 0.95 of the 1.00 at New
  York +3 h, 0.06 of 0.13 at +6 h, all 0.05 at Germany +24 h. A larger one (0.25 or 0.5) would start deleting those rules. The cost is size: the
  candidates keep about twice as many rules, so the served models may be larger than today's.
* **Default path unchanged.** The 15 seeded winning-rule fits of PR 44 (iris, wine, synthetic; `ds_mode` 0/1/2, T1/T2,
  fixed and optimised partitions) are bit for bit those of ex-fuzzy main (`fac6c0e`) and of `20c1095`; 9 seeded
  `mixture_search` fits with `mixture_pruning='winning_rule'` are bit for bit those of `20c1095`; full ex-fuzzy suite
  1652 passed, 43 skipped (the large machine).
* **Old Atlas fits reproduce.** Atlas passes `mixture_pruning` explicitly (`FuzzyClassifierParams`, default
  `"winning_rule"`, the pruning of every mixture fitted so far), so the `mixture-serve` and `mixture-retry-r60a2` configs
  refit the same models: three of them refitted under `5409bb8` (`de_no2_h6` free seed 1, `nyc_pickups_h1` free seed 1,
  `nyc_pickups_h6` retry free seed 2) give the same rules, weights, biases, fitness and fitting-sample predictions and
  scores as the pickles written under `20c1095`, bit for bit (`artifacts/mixture-serve-logs/old_pruning_repro.json`).

### 8.2 Pre-registration (written and committed before any fit of these arms)

* **Arms** (experiment `mixture-prune`, configs `configs/ml/<task>_mixture_prune_experiment.json`):
  `mix_search_nonneg_mp` (`W ≥ 0`) and `mix_search_free_mp` (free weights), the arms `mix_search_nonneg` /
  `mix_search_free` of sections 0 and 7.2 with **only the pruning changed** (`mixture_pruning="mixture"`, threshold
  0.02): same rows, split, fitting sample, terms, inputs, shape and budget, `mixture_C = 1.0`. **Seeds 0, 1, 2**; New
  York +6 h **seeds 0-4 at 60 × 2**, the shape and seeds of its retry (section 7.2), so that both prunings are compared
  on the same shape. ex_fuzzy `5409bb8`, the new pin.
* **Old-pruning arms are not refitted**: their fits are on disk (`mixture-serve`; New York +6 h `mixture-retry-r60a2`)
  and reproduce under the new pin (8.1). Their validation and test numbers are quoted from there; their test rows were
  read once already.
* **Choice between the two new arms:** as before: highest mean validation macro-F1, within 0.005 the tie goes to
  `W ≥ 0`; the published seed is the chosen arm's best validation seed.
* **Gate, per task:** the task moves to the new-pruning mixture only if the chosen arm's **mean validation macro-F1 is at
  least the currently served model's validation macro-F1 plus 0.010**; otherwise the served model stays. The margin is
  that of section 7.2: twice the tie tolerance, and above the seed sd of every served arm (at most 0.0046 for the
  old-pruning mixtures, 0.008 for the New York +6 h winning-rule arm). The comparison is a new arm's mean against the
  served seed, which was the best of its arm, so it errs towards keeping the served model.

  | task | served model (stays if the gate is not met) | its validation macro-F1 | gate |
  |---|---|---|---|
  | `de_no2_h1` | `exfuzzy-de_no2_h1-mixture-nonneg-seed1` | 0.6371 | 0.6471 |
  | `de_no2_h3` | `exfuzzy-de_no2_h3-mixture-nonneg-seed2` | 0.5179 | 0.5279 |
  | `de_no2_h6` | `exfuzzy-de_no2_h6-mixture-nonneg-seed0` | 0.5089 | 0.5189 |
  | `de_no2_h12` | `exfuzzy-de_no2_h12-mixture-nonneg-seed0` | 0.4302 | 0.4402 |
  | `de_no2_h24` | `exfuzzy-de_no2_h24-mixture-nonneg-seed0` | 0.4779 | 0.4879 |
  | `nyc_pickups_h1` | `exfuzzy-nyc_pickups_h1-mixture-nonneg-seed1` | 0.4087 | 0.4187 |
  | `nyc_pickups_h3` | `exfuzzy-nyc_pickups_h3-mixture-nonneg-seed2` | 0.3246 | 0.3346 |
  | `nyc_pickups_h6` | `exfuzzy-nyc_pickups_h6-level-rel7-seed0` (winning rule) | 0.314 | 0.324 |
  | `nyc_pickups_h24` | `exfuzzy-nyc_pickups_h24-mixture-nonneg-seed0` | 0.3411 | 0.3511 |

* **Test**, read once per task at the end, whatever the gate says (`TEST_READ` of `mixture-prune`): the chosen new arm's
  seeds and the served winning-rule arm, persistence, same hour yesterday and the LR / RF refitted on the fitting sample
  with the model's inputs (these must equal the `mixture-serve` refits).
* **Reported per task:** old-pruning mixture, new-pruning mixture and winning rule, validation and test, the baselines,
  rule counts and the suppression share (rules with a centred weight ≤ −0.25, as in section 3).
* **Publication:** a task that passes gets the run directory `<task>/mixture-mp-<nonneg|free>-seed<k>`, published into
  `published-v07` with a new model id, the registry pointing to it; the current directories stay on disk.

### 8.3 Result

**What ran.** 85 fits on the large machine (58 searches: two arms × three seeds for eight tasks, × five for New York +6 h; and the
27 served winning-rule seeds scored again), 12 workers, ex_fuzzy `3.3.1+g5409bb8`, from 15:29:44 UTC to 20:10 UTC. The
pre-registration commit `7cfd148` is dated 15:28:38 UTC and was pushed at 17:03 UTC; the first new fit finished at
17:05 UTC. The fits were packed across tasks in one pool (`artifacts/mixture-serve-logs/arms_all.py`: the jobs of
`experiment_mixture arms` for each config, slowest first), then `decide`, `final --test` and, where the gate is met,
`runs` per task (`post_prune.sh`). Each new search took 2.8-5.7 times as long as its old-pruning twin (mean 585 s
against 210 s at Germany +6 h, 7,496 s against 1,316 s at +12 h): two logistic fits per candidate when something is
pruned, and candidates keep about twice as many rules.

**No task meets its gate.** The new pruning's chosen arm (`W ≥ 0` everywhere, by the tie rule) has a mean validation
macro-F1 between 0.003 below and 0.007 above the old-pruning arm's mean, and 0.004-0.033 below the gate. **Nothing is published and
`published-v07/registry.json` is unchanged**: eight old-pruning mixtures and the New York +6 h winning-rule model. The
test rows were read once per task afterwards (`TEST_READ` of `mixture-prune`); the served arm reproduces its
`metrics.json` and the LR / RF refits equal those of `mixture-serve` (same rows, inputs and fitting sample), bit for bit.

Rules, suppressing share (rules with a centred weight ≤ −0.25) and the seed in brackets are those of the served or
best validation seed; the new arm's test mean is over its three seeds (five at New York +6 h):

| task | winning rule (served seed) val / test, rules | mixture, old pruning (seed) val / test, rules, suppressing | mixture, new pruning (seed) val / test, rules, suppressing | new arm mean val ± sd · gate | old arm mean val / test | new arm mean test | persistence / same hour yesterday, test | LR / RF refit, test |
|---|---|---|---|---|---|---|---|---|
| DE +1 h | 0.628 / 0.652, 10 | 0.637 / 0.664 (1), 14, 93% | 0.635 / 0.662 (0), 24, 92% | 0.635 ± 0.000 · 0.6471 not met | 0.636 / 0.662 | 0.662 ± 0.001 | 0.658 | 0.660 / 0.677 |
| DE +3 h | 0.502 / 0.528, 7 | 0.518 / 0.542 (2), 15, 87% | 0.522 / 0.549 (2), 21, 100% | 0.520 ± 0.003 · 0.5279 not met | 0.516 / 0.541 | 0.545 ± 0.003 | 0.527 | 0.539 / 0.572 |
| DE +6 h | 0.477 / 0.518, 10 | 0.509 / 0.554 (0), 14, 93% | 0.509 / 0.550 (2), 17, 88% | 0.508 ± 0.001 · 0.5189 not met | 0.507 / 0.551 | 0.552 ± 0.002 | 0.455 / 0.536 | 0.551 / 0.569 |
| DE +12 h | 0.417 / 0.436, 21 | 0.430 / 0.455 (0), 19, 95% | 0.438 / 0.467 (1), 44, 82% | 0.436 ± 0.002 · 0.4402 not met | 0.430 / 0.455 | 0.466 ± 0.002 | 0.438 | 0.456 / 0.482 |
| DE +24 h | 0.467 / 0.512, 15 | 0.478 / 0.525 (0), 19, 84% | 0.477 / 0.525 (1), 46, 85% | 0.476 ± 0.001 · 0.4879 not met | 0.477 / 0.524 | 0.525 ± 0.002 | 0.519 | 0.525 / 0.539 |
| NYC +1 h | 0.398 / 0.412, 10 | 0.409 / 0.430 (1), 13, 46% | 0.407 / 0.438 (2), 13, 62% | 0.405 ± 0.002 · 0.4187 not met | 0.405 / 0.431 | 0.434 ± 0.004 | 0.425 / 0.379 | 0.451 / 0.438 |
| NYC +3 h | 0.328 / 0.335, 7 | 0.325 / 0.371 (2), 15, 27% | 0.332 / 0.377 (1), 29, 31% | 0.329 ± 0.004 · 0.3346 not met | 0.322 / 0.369 | 0.375 ± 0.002 | 0.355 / 0.345 | 0.398 / 0.384 |
| NYC +6 h | **0.314 / 0.353**, 8 (served) | 0.290 / 0.282 (4), 6, 33% (retry, 60 × 2, not served) | 0.295 / 0.316 (3), 25, 12% | 0.291 ± 0.003 · 0.324 not met | 0.289 / 0.282 | 0.309 ± 0.007 | 0.312 / 0.305 | 0.357 / 0.342 |
| NYC +24 h | 0.343 / 0.373, 11 | 0.341 / 0.387 (0), 16, 31% | 0.336 / 0.387 (1), 29, 21% | 0.333 ± 0.005 · 0.3511 not met | 0.336 / 0.384 | 0.386 ± 0.003 | 0.380 / 0.330 | 0.388 / 0.388 |

Validation means of the two new arms (`W ≥ 0` / free): DE +1 h 0.635 / 0.634, +3 h 0.520 / 0.518, +6 h 0.508 / 0.509,
+12 h 0.436 / 0.433, +24 h 0.476 / 0.478; NYC +1 h 0.405 / 0.407, +3 h 0.329 / 0.329, +6 h 0.291 / 0.291, +24 h 0.333 /
0.334 (`artifacts/<task>/experiments/mixture-prune/decision.json`; full table with both arms' seeds and every baseline:
`artifacts/mixture-serve-logs/prune_report.md`).

**What the new pruning keeps.** In the chosen fits, the rules the winning-rule pruning would have deleted (no fitting
row won correctly, `wr_deleted_share.json`): DE +1 h 12 of 24 (12 of them suppress a class), +3 h 5 of 21 (5), +6 h 7 of
17 (6), +12 h 28 of 44 (22), +24 h 20 of 46 (16); NYC +1 h 3 of 13 (1), +3 h 18 of 29 (7), +6 h 10 of 25 (0), +24 h 17
of 29 (2). In Germany most of them are suppressors, as section 3 suggested; in New York most have no centred weight
≤ −0.25: they shift the class scores without winning a row correctly or clearly suppressing a class.

**Reading.**
* On validation, where the choice is made, pruning by the role in the mixture changes little: −0.003 to +0.007 on
  the arm means, the largest gains at DE +12 h (+0.006) and NYC +3 h (+0.007), short of the 0.010 margin over the
  served seeds. On test the new arm means are higher in eight tasks (+0.001 to +0.011; NYC +6 h +0.027) and 0.0004
  lower at DE +1 h; the test rows were read after the decision and do not change it.
* **New York +6 h does not recover.** The section 7 diagnosis was right about the mechanism (10 of the 25 rules of the
  new model would have been deleted), but keeping them lifts validation only from 0.289 to 0.291, far from the gate
  (0.324) and the winning-rule model (0.314); on test the new mixture reaches 0.309 ± 0.007 against the winning rule's
  0.353 and the old mixture's 0.282. The validation window itself, on which every model with these inputs except the
  winning-rule one sits at 0.28-0.29 (section 7.3), remains the open question.
* **The price is size**: about twice as many rules (DE +12 h 44, +24 h 46, against 19), which would make the rule views
  harder to read; with no accuracy gain on validation, there is no case for it under the pre-registered rule.

**Old models under the new pin.** The 18 served models reproduce their tables bit for bit under `5409bb8` (section 8.1,
`docs/reproduce.md`), and the nine served classifiers pass the row-by-row parity again with it (`publish_parity`, now in
two-day windows): 15,669,243 rows, 26,469 traces, every label, firing record, contribution, decisive flag, top rule and
trace equal to ex_fuzzy (`artifacts/mixture-serve-logs/parity-served/`; the large machine, peak RSS 0.31-0.56 GB per model).

## 6. Reproduce

```bash
X=<ex-fuzzy checkout of 20c1095, or leave empty for the pinned 3.4.0>   # 3.4.0 (= 5409bb8) refits these bit for bit (8.1)
export PYTHONPATH=$X:src:apps/api OMP_NUM_THREADS=1 ATLAS_DATA_DIR=<data> ATLAS_ARTIFACTS_DIR=<artifacts>
C=configs/ml
python -u -m atlas.ml.experiment_mixture arms --workers 8 --config $C/de_no2_h{1,3,6,12,24}_mixture_serve_experiment.json
python -u -m atlas.ml.experiment_mixture arms --workers 8 --config $C/nyc_pickups_h{1,3,6,24}_mixture_serve_experiment.json
for t in de_no2_h1 de_no2_h3 de_no2_h6 de_no2_h12 de_no2_h24 nyc_pickups_h1 nyc_pickups_h3 nyc_pickups_h6 nyc_pickups_h24; do
  c=$C/${t}_mixture_serve_experiment.json
  python -m atlas.ml.experiment_mixture decide --config $c
  python -m atlas.ml.experiment_mixture final --test --config $c      # once: TEST_READ refuses a second read
  python -m atlas.ml.experiment_mixture runs --config $c              # artifacts/<task>/mixture-<nonneg|free>-seed<k>
done
python -m atlas.ml.experiment_mixture summary --config $C/*_mixture_serve_experiment.json
```

Section 8 (pruning by the role in the mixture; the pinned ex-fuzzy 3.4.0, or a checkout of `5409bb8`):

```bash
for t in de_no2_h1 de_no2_h3 de_no2_h6 de_no2_h12 de_no2_h24 nyc_pickups_h1 nyc_pickups_h3 nyc_pickups_h6 nyc_pickups_h24; do
  c=$C/${t}_mixture_prune_experiment.json
  python -u -m atlas.ml.experiment_mixture arms --workers 8 --config $c    # 6 searches (NYC +6 h: 10), 0.5-2.6 h each
  python -m atlas.ml.experiment_mixture decide --config $c                 # the gate of section 8.2
  python -m atlas.ml.experiment_mixture final --test --config $c           # once
  # runs --config $c only where decision.json says "serve": true (no task, 2026-11-09)
done
```

Publication (the workstation, one task at a time; `R` = the main checkout, `P` = the published directory):

```bash
# Germany (h = 1, 3, 6, 12, 24; <run> from the table of section 4)
python -m atlas.services.publish --run-dir $R/artifacts/de_no2_h$h/<run> --features $R/data/processed/air-de/features/de_no2_h$h/table \
  --entities $R/data/processed/air-de/stations.geojson --feature-spec configs/air/de_no2_h${h}_feature_spec.json \
  --from 2025-01-01T00:00:00Z --to 2026-01-01T00:00:00Z --task-id de_no2_h$h --title "Germany air quality (EEA)" \
  --metadata configs/air/attribution_de.json --territory germany --territory-title Alemania --territory-title-en Germany \
  --skip-labels-not-in-spec --published-dir $P   # attribution_de.json also labels no2_yday_valid, a +6 h input only
# New York (h = 1, 3, 6, 24)
python -m atlas.services.publish --run-dir $R/artifacts/nyc_pickups_h$h/<run> --features $R/data/processed/mobility/features/nyc_pickups_h${h}_level \
  --entities $R/data/processed/mobility/taxi_zones_simplified.geojson --feature-spec configs/mobility/feature_spec.json \
  --from 2025-02-08T05:00:00Z --to 2025-04-01T04:00:00Z --task-id nyc_pickups_h$h --title "Yellow-taxi demand level (NYC)" \
  --observed-label-column target_level --metadata configs/mobility/attribution.json --include-unmodelled-entities \
  --territory nyc --territory-title "Nueva York" --territory-title-en "New York" --published-dir $P
python -m atlas.ml.publish_parity $P/exfuzzy-<task>-<run>          # every published row against ex_fuzzy
python -m atlas.services.verify $P/exfuzzy-<task>-<run>
```
