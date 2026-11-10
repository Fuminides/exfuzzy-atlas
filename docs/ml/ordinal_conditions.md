# Ordinal conditions ("x IS at least Fair" / "at most Fair") in the published models (AT-041k)

ex-fuzzy PR 45 (`Fuminides/ex-fuzzy`, branch `feature/ordinal-conditions`, commit `08cb406`, open and unmerged) adds an
opt-in `ordinal_conditions=True` to `BaseFuzzyRulesClassifier` (winning rule, `inference='mixture'`, `mixture_search`)
and `BaseFuzzyRulesRegressor`. A rule may then say `x IS at least t` or `x IS at most t` over the ordered terms of a
variable, besides a single term: `3n - 4` conditions for a variable with `n` terms (8 for 4 terms), membership the
bounded sum `min(1, sum of the covered terms)`. With the option off the library is bit-identical to 3.4.0 (the PR's
golden replay).

**Question (the user, 2026-11-10): does the option produce better published models?** Better is defined below, per task,
on validation only. This document is written, and committed, before any fit of any arm of this experiment. Nothing is
published, the contract is not bumped (an `Antecedent` has no operator in v0.7; a model with ordinal conditions cannot
be exported until a v0.8 adds one) and ex-fuzzy is not modified.

**What this is not.** Same limits as the earlier experiments: a firing is a degree of rule match, not a probability, a
contribution or a risk; a mixture weight is a coefficient of a fitted linear model; "at least Fair" is a statement
about the order of the terms of an input, not a clinical, sanitary or regulatory claim.

## Amendment 1 (2026-11-10, written before any result existed): arm B changes; quantity inputs get ordinal conditions, clock inputs get named compound terms

**Status: final, committed before any fit of the new arm B** (the first draft is commit `074138e`, revised in `817d153`;
the commit that fills in the library hash below is the last one before the first fit). Written 2026-11-10 from about 11:35 UTC
on the decision of the user, with no result of any arm in existence.

**The change.** In section 0 arm B switched `ordinal_conditions` on for every variable with 3 or more terms. That is
replaced. Arm B is now:

* **Quantity inputs** (pollutants and their lags, temperature, humidity, wind, pH, nutrients, demand levels, counts and
  lags of those, and the water season `days_from_midwinter`, which is an ordered distance and not a cycle: 0 at midwinter,
  the maximum at midsummer): `x IS at least t` / `x IS at most t` as in PR 45, `3n - 4` conditions for `n` terms, membership the
  bounded sum. These are the only inputs with `at least` / `at most`.
* **Clock and calendar inputs** (hour of day: `valid_hour_local`, `local_hour`; weekday: `valid_weekday`, `local_dow`) get
  **no** `at least` / `at most`. They get named **compound terms**, each the union of contiguous terms, membership the
  bounded sum `min(1, sum of the terms)`:
  * **hour:** every adjacent pair of its terms. **A union wraps (last term with the first) only if the variable's domain
    spans the whole cycle** (hour 0 to 23, weekday 0 to 6). Germany and NYC hours do (4 terms, 4 unions, e.g. Germany Evening
    and Night, 17 h to 5 h). Water's sampling hour does not: its domain in the published `rules.json` is 5.4 to 15.6 h
    (daytime sampling), so only "Low or Medium" and "Medium or High" exist and the wrap pair "High or Low" is dropped;
  * **weekday:** only the weekend, Saturday and Sunday (no other union was specified);
  The single terms of these inputs stay available, so a rule can still say `hour IS Midday`.
* Names of the compound terms are provisional, in Spanish and English, in `configs/ml/ordinal_conditions_experiment.json`;
  they do not enter the fit and the user will polish them.

**Why.** Hour, weekday and season are cyclic and ordered by time, not by quantity. "Hour IS at least Midday" reads as a
threshold on a quantity, but the hour 23 is next to hour 0: the order is a clock order with a seam, and the useful
statement is a stretch of the day (including one that wraps midnight or the week). Section 0.1 already named this as a
known weakness and left it in arm B because B was "the same configuration with the option on"; the user decided, before any
result existed, to fix the design instead of reporting the weakness afterwards.

**Why the original run is void.** The first launch of `arms` (arm B with the option on for all variables) started at
11:21:37 UTC and was stopped by PID at about 11:28 UTC, on the same decision. **It produced no result:** no `[k/90]` line
was printed, no fit, model or record file was written (`find` over the output directory: 0 files), and no validation figure
was computed, read or written (validation is scored after a fit, and none had finished). The only fits of the old design that
exist are the smoke fits (2 generations x 8 individuals, seed 0, three tasks), scored on the fitting sample, not on any
validation or test row; they say nothing about the question and were not used for any design choice here.

**What stays exactly as in section 0.** Arm A (the published configuration, the option off); the ten tasks and their
published procedures (including the shape selection of NYC +6 h and Water, run in both arms); seeds 0, 1, 2; the budget
(150 generations x 60 individuals); the fitting samples, partitions and base terms; the selection of the fit of an arm
(highest validation macro-F1, Water lowest RMSE); the decision rule of section 0.4 with the same tolerances (macro-F1
0.01, Water 1 % of A's MAE), the strict "more than" and the robustness check on the medians; and the test protocol of
section 0.5 (not read before all ten decisions are recorded, then once).

**Consequences for the definitions of section 0**, each superseding the sentence it names:

* Section 0.3 "arm B is the identical configuration with `ordinal_conditions=True`": arm B is the identical configuration
  with the per-variable option and the compound terms above. B differs from A in **the option and the compound terms
  together**; this experiment cannot separate their effects, and the report says so.
* Section 0.4 total conditions `C`: a compound term, like a single term or an `at least` condition, counts as **one**
  condition of its rule.
* Section 0.6 "identical terms": the base terms of A and B must be identical variable by variable; B adds only the
  compound terms of the clock inputs, listed in the config.
* Section 0.7 interpretability: instead of the share of ordinal conditions on cyclic inputs, the report gives per
  variable the use of `at least` / `at most` (quantity inputs; any use on a clock input is a bug) and the use of compound
  terms (clock inputs); the example rules show both kinds.
* Library: arm B needs the extension of PR 45 with per-variable selection and named compound terms, which is being
  written; the commit is **ex-fuzzy `7a0844a`** (`feature/ordinal-conditions`, PR 45, on top of `08cb406`; 118 ordinal and
  compound tests pass and the recorded 3.4.0 fixture of nine fits replays exactly with the defaults, as reported by the
  library's author). The API, as reported with that commit: `ordinal_conditions` takes True, False or a collection of
  features (names or indices); `compound_terms` maps a feature to a list of `(name, [member term names or indices])`; a
  name is a free string that must not collide with a base term or another compound of the same variable; in
  `rule.conditions()` a compound term has operator `'any_of'` with `terms` (the members) and `name`, and compound use is
  counted by that operator. Quantity variables keep their `3n - 4` conditions. Names must be unique within a variable,
  differ from every term and ordinal condition, and not contain `;`, line breaks, parentheses or the words AND / IS / WITH /
  THEN or start with "at least" / "at most": the names of the config pass. Sets are stored sorted, so a wrapping union is
  allowed; compound codes come after the single and ordinal codes. Arm A runs on that same build with
  the new options off (they default to the 3.4.0 behaviour), and the check against the `mixture-serve` fits of section
  0.6 is repeated on it, plus a second check: for one task A's genes and rules on the new build equal those of the
  smoke fits made on the PR 45 build `08cb406` (option off).
* Environment: as section 0.2, with that ex-fuzzy commit in place of `08cb406`.

## 0. Pre-registration (fixed before any fit of an ordinal arm; arm B superseded by Amendment 1)

### 0.1 What was known when this section was written

* The validation numbers of arm A for 8 of the 10 tasks come from the earlier experiments (`rule_mixture_serve.md`
  section 2, `artifacts/<task>/experiments/mixture-serve/val/mix_search_nonneg.json`; NYC +6 h
  `experiments/level-rel7`; Water `experiments/fx-w-unique`). They are the expected result of re-running A (section
  0.6) and are listed in the table of 0.3. Their test numbers had been read before, once per experiment (information
  only, as stated there); the test periods are therefore not virgin for A, and are read for B here for the first time.
* No ordinal-arm fit has been run, not even a smoke fit. Of PR 45 I read its description, its code layout and the
  signatures of `Condition`, `rule_conditions` and `fuzzyVariable.condition*`; the PR's own benchmark (iris, wine,
  breast cancer, diabetes; wine and diabetes gain, iris is within noise) is the only evidence about the option, and says
  nothing about these tasks.
* The inputs are the ones of the served models. Several are not ordinal scales: hour of day, weekday (and the water
  season, `days_from_midwinter`) have terms listed in clock or calendar order. The library flags every variable with
  at least 3 terms when the option is on, and arm B is "the same configuration with the option on", so these inputs
  get ordinal conditions too. "Night" to "Evening" is an order of the clock, not of a quantity. This is reported (section
  0.7), not excluded.

### 0.2 Library and environment

* **ex-fuzzy:** a clone of PR 45 at `08cb406` (on top of 3.4.0 = `10d811b`), first on `PYTHONPATH`; nothing is
  installed. Arm A runs on the **same build with the option off** (bit-identical to 3.4.0), so A and B differ in the
  option only. Every fit records `exfuzzy_version` = `3.4.0+g08cb406`.
* **Machine:** the large machine (DGX Spark, aarch64, 20 CPUs, 121 GB). Python: an existing venv, read-only
  (numpy 2.5.3, pandas 3.0.6, scikit-learn 1.9.1, scipy 1.18.1, pymoo 0.6.2), plus a stub `duckdb` module on
  `PYTHONPATH` (`atlas.contracts` imports it for the observation validator, never called by the fits). Atlas: a clone
  of this branch at the commit named in section 1. One BLAS thread per fit, one process per fit.
* **Outputs:** outside git, on the large machine, in a work directory, and copied back to
  `artifacts/experiments/ordinal_conditions/`. Nothing is written under `artifacts/published`.

### 0.3 Tasks and arms

Arm A is each task's currently published configuration (`artifacts/published/registry.json`, v0.7) with the option off;
arm B is the identical configuration with `ordinal_conditions=True` **[superseded by Amendment 1: per-variable option plus compound terms]**: same rows, split, embargo, class merge, fitting
sample, partitions, inputs, shape, budget (150 generations x 60 individuals, no early stop), pruning, weights penalty,
selection procedure and the same **seeds 0, 1, 2** in both arms. Fitting samples are the served models' own
(`subsample_keys.parquet` of the served experiment; Water: every complete training row). Each arm runs the published
selection procedure of its task, so that A is re-run "like for like" and not compared against a cherry-picked fit:

| task | published model | family | shape | the published procedure, run in both arms | A on disk, validation (seeds 0 / 1 / 2) |
|---|---|---|---|---|---|
| `de_no2_h1` | `mixture-nonneg-seed1` | mixture, `W >= 0` | 60 x 2, 9 inputs | 3 seeds, best seed by validation macro-F1 | 0.6347 / 0.6371 / 0.6365 |
| `de_no2_h3` | `mixture-nonneg-seed2` | mixture, `W >= 0` | 30 x 3, 9 inputs | same | 0.5161 / 0.5147 / 0.5179 |
| `de_no2_h6` | `mixture-nonneg-seed0` | mixture, `W >= 0` | 30 x 2, 4 inputs, unweighted | same | 0.5089 / 0.5073 / 0.5041 |
| `de_no2_h12` | `mixture-nonneg-seed0` | mixture, `W >= 0` | 60 x 4, 9 inputs | same | 0.4302 / 0.4290 / 0.4295 |
| `de_no2_h24` | `mixture-nonneg-seed0` | mixture, `W >= 0` | 60 x 4, 9 inputs | same | 0.4779 / 0.4770 / 0.4748 |
| `nyc_pickups_h1` | `mixture-nonneg-seed1` | mixture, `W >= 0` | 30 x 2, 7 inputs | same | 0.4032 / 0.4087 / 0.4033 |
| `nyc_pickups_h3` | `mixture-nonneg-seed2` | mixture, `W >= 0` | 60 x 2, 7 inputs | same | 0.3189 / 0.3223 / 0.3246 |
| `nyc_pickups_h24` | `mixture-nonneg-seed0` | mixture, `W >= 0` | 60 x 2, 7 inputs | same | 0.3411 / 0.3340 / 0.3324 |
| `nyc_pickups_h6` | `level-rel7-seed0` | winning rule, dominance score | 30 x 3 (selected), 7 inputs | shape selection: the six shapes of `nyc_pickups_h6_level_rel7_experiment.json` with seed 0, highest validation macro-F1 (ties: fewer rules); then seeds 0-2 at that shape, best seed by validation macro-F1 | 0.3141 / 0.3059 / 0.2988 (30 x 3) |
| `uk_water_do` | `fx-w-unique-seed0` | TSK regressor, additive, `unique_antecedents` | 40 x 2 (selected), 6 inputs | shape selection: the 9 shapes (10 / 20 / 40 rules x 2 / 3 / 4 antecedents) with seed 0, lowest validation RMSE (ties: fewer rules, then fewer antecedents); then seeds 0-2 at that shape, published seed = lowest validation RMSE | RMSE 0.9252 / 0.9376 / 0.9643, MAE 0.6233 / 0.6188 / 0.6399 |

The mixtures are `mix_search_nonneg` of `rule_mixture_serve.md` (pruning `winning_rule`, `mixture_C = 1`). The weights
arm (`W >= 0` against free) is not re-decided: all eight published mixtures are `W >= 0`, which is the configuration
under test. Shapes of the mixtures are those of the published models (they came from the winning-rule shape selection
of AT-080 and were not re-selected for the mixture); only NYC +6 h and Water have a shape selection in their published
procedure, and only there is it re-run. Water's selection criterion (RMSE) and seed rule (RMSE) are the published
ones; its decision metric is MAE (section 0.4), as set by the user.

### 0.4 Decision rule (per task; validation only; `python -m atlas.ml.experiment_ordinal decide`)

Per arm and task, the **selected fit** is the fit of the arm's published procedure: the seed with the highest validation
macro-F1 (Water: the lowest validation RMSE), ties to the lowest seed. Its **metric** `M` is the validation macro-F1
(Water: the validation MAE) and its **total conditions** `C` is the sum, over all rules of the fitted rule base, of the
number of conditions of the rule (the antecedents that are not "don't care"; an `at least` or `at most` condition counts
as one), which is what the web shows as rules x conditions. Rules are counted as kept by the fit (none is removed).

* Gain `D`: classifiers `D = M_B - M_A` (macro-F1, higher is better); Water `D = (MAE_A - MAE_B)`, positive when B has
  the lower error. Tie tolerance `tau`: classifiers 0.01; Water `0.01 x MAE_A` (the 1 % of the tolerance the web uses).
* **B wins the task** if (a) `D > tau`, or (b) `|D| <= tau` and `C_B < C_A` (strictly fewer).
* **Otherwise A stays** (`D < -tau`, or a tie with no fewer conditions: equal or more).
* Robustness check, reported next to every decision and not changing it: the same rule on the medians over the 3 seeds
  (median `M`, median `C`) of each arm. A decision is called **robust** if the median rule gives the same outcome.
* Also reported (no role in the decision): the mean and sd of `M` over the seeds, rules, mean conditions per rule, the
  share of conditions that are `at least` / `at most`, the variables they are on (section 0.7), fit seconds.
* No multiplicity correction: ten separate decisions on ten validation periods. A "win" is a statement about that
  task's validation period under this rule, not evidence that the option helps in general; the New York windows (3.5
  weeks of January) separate models very poorly (`rule_mixture.md` section 7 point 6), and best-of-3 selection favours
  the arm with the larger seed spread, which is why the median check exists.

### 0.5 Test (read once, `test` stage; a `TEST_READ` marker refuses a second read)

The test periods are **not read before every task's decision is recorded**: the `test` stage refuses to run unless
`decisions.json` holds all 10 tasks, and that file (the validation table and the decisions) is committed to this
document before the stage is launched. It then scores all 3 seeds of both arms on each task's test rows (Water
2024-2025, Germany 2025, NYC 2025-02-08 to 2025-04-01), macro-F1 (Water: MAE and RMSE), for information only. The test
figures do not change any decision.

### 0.6 Checks that A is the published configuration

* For the eight mixtures, A re-run on this build (option off) must reproduce the fits of `mixture-serve` on disk
  (rules, weights, validation macro-F1), as the earlier pins did ("old Atlas fits reproduce", `rule_mixture_serve.md`
  8.1). It is a check of the environment, not part of the decision: **A is always the re-run**, and any difference is
  reported.
* For NYC +6 h and Water the re-run A may select a different shape than the published one (different ex-fuzzy
  build, different machine). It is reported; the decision uses the re-run.
* Both arms must use identical base terms (partitions), compared variable by variable; a mismatch aborts the fit (Amendment 1: B adds only the compound terms).
* A fit that crashes or a B fit that is not ordinal-flagged (no variable with `ordinal`) stops the experiment: it is
  a library or code bug, reported, not worked around.

### 0.7 Interpretability (reported for every B fit)

Rules, total conditions, mean conditions per rule, the number of rules that use `at least` / `at most`, the share of
all conditions that are ordinal, and which inputs carry them. Inputs whose terms are cyclic or nominal (hour, weekday,
season) are listed separately from the quantity inputs. For the winning task with the largest `D` (any task with the
largest `D` if none wins, said so), three rules that use an ordinal condition are printed as text: the three with
the largest effect in the selected B fit (mixture: weight spread `max_c W - min_c W`; winning rule: rule weight;
Water: absolute consequent), through `rule.conditions()`.

### 0.8 Reproduce

```bash
X=<ex-fuzzy clone at 08cb406>; export PYTHONPATH=$X:src:apps/api OMP_NUM_THREADS=1 ATLAS_DATA_DIR=<data> ATLAS_ARTIFACTS_DIR=<artifacts>
python -u -m atlas.ml.experiment_ordinal arms --workers 16     # every (task, arm, seed) fit, one [k/N] line each
python -m atlas.ml.experiment_ordinal decide                   # decisions.json, validation only
python -m atlas.ml.experiment_ordinal test                     # once; refuses without decisions.json for all 10 tasks
python -m atlas.ml.experiment_ordinal report                   # markdown tables
```

## 1. What was run

* **Commits.** Gate `eacb222` (2026-11-10 11:03 UTC); Amendment 1 final `88bc869`, the code that ran; Atlas on the large machine is a clone of
  this branch at `88bc869`. ex-fuzzy `7a0844a` (`3.4.0+g7a0844a` in every fit record), arm A on the same build with the new
  options off.
* **Launches.** The first launch (arm B with the option on for every input) was stopped by PID after about 6 minutes, with no
  fit finished and no validation figure produced (Amendment 1); its log is kept as `arms-void-first-launch.log`. The run
  reported here started at 11:46:29 UTC and finished at 12:47:37 UTC: **61 minutes of wall time**, 90 fits (10 tasks x 2 arms x 3
  seeds, plus the shape selections: 6 shapes x 2 arms for NYC +6 h and 9 x 2 for Water), 18 worker processes, one core each, on the large machine.
  The three `de_no2_h6` A fits had been run alone just before it, as the arm-A check below, and are the same records.
* **Arm A checks (section 0.6).** (1) For the eight mixture tasks, A re-run on `7a0844a` with the options off reproduces
  the fits of `mixture-serve` on disk **exactly**: same rules, same mixture weights, same validation macro-F1, for every
  seed of every task (24 of 24; `decisions.json`, `checks`). (2) A's smoke fits (2 generations) on `7a0844a` equal those made on
  `08cb406`: antecedent codes, rules, weights, consequents, partitions and fitting-sample scores identical for `de_no2_h6`, NYC
  +6 h and Water. (3) Base terms of A and B are identical in every task (checked by `decide`); every B fit asserted that exactly
  the quantity inputs are ordinal, that no clock input is, and that its config compound terms are on its inputs.
* **A is not always the published model.** The shape selection of NYC +6 h, re-run on this build, picks **60 x 3** in A (validation macro-F1 per
  shape 30x2 0.2889, 30x3 0.3095, 30x4 0.2985, 60x2 0.2750, 60x3 0.3182, 60x4 0.3144), not the published 30 x 3 (whose
  published seed-0 value was 0.3141; the published model was fitted on an older build). B picks 60 x 4 (0.3165, 0.3138, 0.2974,
  0.2831, 0.2869, 0.3185). Water's A picks 40 x 2, the published shape (RMSE per shape 0.9697, 1.0518, 1.0285, 0.9703,
  0.9660, 0.9378, 0.9252, 0.9586, 0.9873 for 10x2 ... 40x4); B picks 40 x 3 (0.9769, 0.9577, 0.9730, 0.9330, 0.9449, 0.9334,
  0.9199, 0.9101, 0.9300). The decisions use the re-run A, as registered.
* **Cost.** Mean fit seconds per seed, A / B: `de_no2_h24` 1581 / 2354, `de_no2_h12` 1575 / 2412, `nyc_pickups_h24` 916 / 1624,
  `de_no2_h3` 1123 / 1316, `de_no2_h1` 990 / 1269, `nyc_pickups_h3` 921 / 982, `nyc_pickups_h1` 590 / 727, `de_no2_h6` 213 / 531,
  `nyc_pickups_h6` (final fits) 96 / 153, `uk_water_do` 78 / 65. Arm B is 1.0x to 2.5x slower for the classifiers (a larger
  search space). Peak RSS 4.1 GB per Germany fit (the forked table), about 1 GB for NYC, 0.6 GB for Water.
* **Nothing else deviates** from section 0 and Amendment 1. Outputs: `artifacts/experiments/ordinal_conditions/` (fits, models,
  `decisions.json`, `report.md`, logs); nothing under `artifacts/published`.

## 2. Validation and decisions

Recorded **before any test row was read** (the `test` stage had not been run when this section was committed). `M` = validation
macro-F1 of the selected fit (Water: MAE); seeds 0 / 1 / 2; "selected" = the arm's published seed rule; conditions = total
conditions `C` of the selected fit; cond/rule = `C` / rules; ordinal / compound = conditions of the selected fit that are `at least`
or `at most` / named compound terms. Shapes are `nRules x nAnts`.

| task | arm | seeds (val) | selected seed, shape | M | rules | C | cond/rule | ordinal | compound |
|---|---|---|---|---|---|---|---|---|---|
| de_no2_h1 | A | 0.6347 / 0.6371 / 0.6365 | 1, 60x2 | 0.6371 | 14 | 15 | 1.07 | 0 | 0 |
| | B | 0.6327 / 0.6364 / 0.6286 | 1, 60x2 | 0.6364 | 11 | 17 | 1.55 | 10 | 1 |
| de_no2_h3 | A | 0.5161 / 0.5147 / 0.5179 | 2, 30x3 | 0.5179 | 15 | 23 | 1.53 | 0 | 0 |
| | B | 0.5194 / 0.5137 / 0.5188 | 0, 30x3 | 0.5194 | 12 | 20 | 1.67 | 8 | 2 |
| de_no2_h6 | A | 0.5089 / 0.5073 / 0.5041 | 0, 30x2 | 0.5089 | 14 | 17 | 1.21 | 0 | 0 |
| | B | 0.5102 / 0.5063 / 0.5081 | 0, 30x2 | 0.5102 | 14 | 18 | 1.29 | 2 | 2 |
| de_no2_h12 | A | 0.4302 / 0.4290 / 0.4295 | 0, 60x4 | 0.4302 | 19 | 40 | 2.11 | 0 | 0 |
| | B | 0.4286 / 0.4322 / 0.4273 | 1, 60x4 | 0.4322 | 29 | 75 | 2.59 | 28 | 7 |
| de_no2_h24 | A | 0.4779 / 0.4770 / 0.4748 | 0, 60x4 | 0.4779 | 19 | 36 | 1.89 | 0 | 0 |
| | B | 0.4739 / 0.4740 / 0.4739 | 1, 60x4 | 0.4740 | 19 | 40 | 2.11 | 21 | 3 |
| nyc_pickups_h1 | A | 0.4032 / 0.4087 / 0.4033 | 1, 30x2 | 0.4087 | 13 | 14 | 1.08 | 0 | 0 |
| | B | 0.3941 / 0.4043 / 0.4000 | 1, 30x2 | 0.4043 | 11 | 16 | 1.45 | 7 | 0 |
| nyc_pickups_h3 | A | 0.3189 / 0.3223 / 0.3246 | 2, 60x2 | 0.3246 | 15 | 16 | 1.07 | 0 | 0 |
| | B | 0.3346 / 0.3331 / 0.3342 | 0, 60x2 | 0.3346 | 9 | 12 | 1.33 | 8 | 2 |
| nyc_pickups_h6 | A | 0.3182 / 0.3093 / 0.3060 | 0, 60x3 (re-selected) | 0.3182 | 9 | 11 | 1.22 | 0 | 0 |
| | B | 0.3185 / 0.3159 / 0.3166 | 0, 60x4 (re-selected) | 0.3185 | 5 | 10 | 2.00 | 5 | 0 |
| nyc_pickups_h24 | A | 0.3411 / 0.3340 / 0.3324 | 0, 60x2 | 0.3411 | 16 | 20 | 1.25 | 0 | 0 |
| | B | 0.3381 / 0.3355 / 0.3377 | 0, 60x2 | 0.3381 | 17 | 27 | 1.59 | 15 | 3 |
| uk_water_do | A | MAE 0.6233 / 0.6188 / 0.6399 | 0, 40x2 | 0.6233 | 39 | 64 | 1.64 | 0 | 0 |
| | B | MAE 0.6030 / 0.6162 / 0.6162 | 0, 40x3 | 0.6030 | 38 | 81 | 2.13 | 24 | 2 |

Total conditions and rules by seed (A / B): `de_no2_h1` C 17, 15, 19 / 25, 17, 12; `de_no2_h3` 17, 15, 23 / 20, 25, 17; `de_no2_h6`
17, 11, 15 / 18, 20, 16; `de_no2_h12` 40, 38, 43 / 51, 75, 56; `de_no2_h24` 36, 35, 44 / 68, 40, 59; `nyc_pickups_h1` 14, 14, 11 /
15, 16, 13; `nyc_pickups_h3` 21, 20, 16 / 12, 8, 5; `nyc_pickups_h6` 11, 12, 5 / 10, 14, 16; `nyc_pickups_h24` 20, 20, 17 / 27, 12,
21; `uk_water_do` 64, 54, 49 / 81, 76, 78.

**Decisions** (section 0.4; `D` = gain of B, positive is better for B, `tau` the tolerance; `decisions.json`):

| task | D (selected fits) | tau | C_A | C_B | **decision** | median D | median check | robust |
|---|---|---|---|---|---|---|---|---|
| de_no2_h1 | -0.0008 | 0.0100 | 15 | 17 | A | -0.0038 | A | yes |
| de_no2_h3 | +0.0015 | 0.0100 | 23 | 20 | **B** (tie, fewer conditions) | +0.0027 | A | **no** |
| de_no2_h6 | +0.0013 | 0.0100 | 17 | 18 | A | +0.0008 | A | yes |
| de_no2_h12 | +0.0021 | 0.0100 | 40 | 75 | A | -0.0009 | A | yes |
| de_no2_h24 | -0.0039 | 0.0100 | 36 | 40 | A | -0.0031 | A | yes |
| nyc_pickups_h1 | -0.0044 | 0.0100 | 14 | 16 | A | -0.0032 | A | yes |
| nyc_pickups_h3 | +0.0101 | 0.0100 | 16 | 12 | **B** (gain beyond the tolerance) | +0.0119 | B | yes |
| nyc_pickups_h6 | +0.0003 | 0.0100 | 11 | 10 | **B** (tie, fewer conditions) | +0.0073 | A | **no** |
| nyc_pickups_h24 | -0.0030 | 0.0100 | 20 | 27 | A | +0.0037 | A | yes |
| uk_water_do | +0.0203 (MAE 0.6233 to 0.6030, -3.3 %) | 0.0062 | 64 | 81 | **B** (error reduced by more than 1 %) | +0.0071 | B | yes |

**Reading, honestly.**

* **B wins 4 of 10 tasks under the registered rule; 2 of them robustly** (`nyc_pickups_h3`, `uk_water_do`). `de_no2_h3` and
  `nyc_pickups_h6` win only by the tie clause (fewer conditions by 3 and 1) and lose on the median check.
* **`nyc_pickups_h3` clears the strict tolerance by 0.0001** (0.0101 against 0.0100). It would also have won under the tie clause (12
  conditions against 16), so the verdict does not depend on that margin; and all three B seeds (0.3331 to 0.3346) are above
  every A seed (0.3189 to 0.3246), with a seed spread of 0.0008 against A's 0.0029. The New York validation window is 3.5 weeks
  of January, which separates models poorly (`rule_mixture.md`, section 7).
* **Water is the clearest case**: MAE 0.6030 against 0.6233 (-3.3 %), RMSE 0.9101 against 0.9252 at the shapes the selection picks, B at a
  larger shape (40 x 3, 81 conditions against 64). The median seed gain is 1.1 % (0.0071 against 0.0062), still beyond the tolerance.
  B fits are the cheapest here (65 s against 78 s).
* **In the other six tasks A stays**: B is within the tolerance but not smaller (`de_no2_h1`, `de_no2_h6`, `de_no2_h12`,
  `de_no2_h24`, `nyc_pickups_h1`, `nyc_pickups_h24`), with more conditions in all six (+2, +1, +35, +4, +2, +7).
  On the Germany +12 h and +24 h tasks B is clearly bigger (75 conditions against 40; 40 against 36) for a validation change of
  +0.0021 and -0.0039.
* **Size.** B has more total conditions than A in 7 of 10 tasks (and the same selected shape in 8). `at least` / `at most`
  conditions are 11 to 67 % of the conditions of the selected B fit (for example 28 of 75 in `de_no2_h12`, 24 of 81 in
  Water, 2 of 18 in `de_no2_h6`): the search uses them, which does not by itself mean they help. Compound terms are rare (0 to 7 per selected fit).
* **B differs from A in two things at once** (the option and the compound terms, Amendment 1): the experiment does not say
  which produced a gain.
* This is a decision on validation periods only; the test periods are read next, for information, and change nothing.

## 3. Test (information only)

Read once, after section 2 was committed (`b280ad8`, 2026-11-10 12:49 UTC; the `test` stage ran at 12:49:55 UTC, 23 s, all
3 seeds of both arms; `TEST_READ` written). Macro-F1, Water MAE (lower is better). "Selected" = the fit the validation rule
selects in each arm. Test figures change no decision.

| task | decision (validation) | A, 3 seeds | B, 3 seeds | A selected | B selected | B - A selected | B - A seed means |
|---|---|---|---|---|---|---|---|
| de_no2_h1 | A | 0.6620 ± 0.0017 | 0.6586 ± 0.0019 | 0.6638 | 0.6603 | -0.0035 | -0.0035 |
| de_no2_h3 | B (tie, not robust) | 0.5408 ± 0.0015 | 0.5416 ± 0.0061 | 0.5422 | 0.5477 | +0.0055 | +0.0009 |
| de_no2_h6 | A | 0.5510 ± 0.0026 | 0.5529 ± 0.0029 | 0.5539 | 0.5561 | +0.0022 | +0.0019 |
| de_no2_h12 | A | 0.4550 ± 0.0005 | 0.4558 ± 0.0015 | 0.4550 | 0.4572 | +0.0022 | +0.0008 |
| de_no2_h24 | A | 0.5240 ± 0.0011 | 0.5228 ± 0.0004 | 0.5252 | 0.5233 | -0.0020 | -0.0012 |
| nyc_pickups_h1 | A | 0.4311 ± 0.0013 | 0.4197 ± 0.0107 | 0.4305 | 0.4278 | -0.0027 | -0.0114 |
| nyc_pickups_h3 | **B** | 0.3688 ± 0.0032 | 0.3685 ± 0.0082 | 0.3714 | 0.3772 | +0.0058 | -0.0003 |
| nyc_pickups_h6 | B (tie, not robust) | 0.3326 ± 0.0043 | 0.3442 ± 0.0071 | 0.3359 | 0.3370 | +0.0011 | +0.0116 |
| nyc_pickups_h24 | A | 0.3843 ± 0.0028 | 0.3847 ± 0.0105 | 0.3875 | 0.3922 | +0.0047 | +0.0004 |
| uk_water_do (MAE) | **B** | 0.6360 ± 0.0034 | 0.6371 ± 0.0107 | 0.6351 | 0.6251 | -0.0100 (B lower, -1.6 %) | +0.0011 (B higher) |

(Water RMSE of the selected fits: A 0.9315, B 0.9277.) Reading:

* **The test does not confirm a general gain.** On the three seeds' mean, B is within 0.002 of A in 7 of 10 tasks; the exceptions
  are Germany +1 h (B lower by 0.0035), NYC +1 h (B lower by 0.0114, one weak B seed, 0.4076) and NYC +6 h (B higher by 0.0116,
  the task where the shape selection picked other shapes than the published one in both arms). In the two robust validation winners, the seed means are level (`nyc_pickups_h3` -0.0003, Water
  +0.0011 MAE, B slightly worse); only the selected fit is better (+0.0058 macro-F1; MAE -1.6 %), which is what selecting the
  best of three seeds on validation rewards.
* B's seed spread is larger than A's in 9 of 10 tasks on test (for example NYC +1 h 0.0107 against 0.0013; Water 0.0107 against
  0.0034), the same pattern as the best-of-3 selection effect that section 0.4 warns about.
* The test periods of A were read before in earlier experiments (section 0.1); B's are read here for the first time.

## 4. Example rules

Selected B fits of winning tasks, with `at least` / `at most` (quantity inputs) and compound terms (clock inputs), printed through
`rule.conditions()`. For a mixture a rule is not a conclusion: the centred weights say which classes it supports (+) or
suppresses (-) relative to the others, and a rule's weights are conditional on the other rules that fire with it
(`rule_mixture.md`, section 5). For Water the number is the additive consequent of a TSK rule, not the oxygen of the samples it
covers.

**`uk_water_do`, B seed 0** (the largest gain; the three rules with the largest effect among those with an ordinal condition):

    IF water_temperature IS Low AND ph IS at most Medium: THEN dissolved oxygen += +18.8
    IF ammoniacal_nitrogen IS <=L AND water_temperature IS at most Medium: THEN dissolved oxygen += +17.2
    IF ammoniacal_nitrogen IS at most Medio>L: THEN dissolved oxygen += +16.8

**`nyc_pickups_h3`, B seed 0** (a mixture; the second robust winner):

    IF rel_lag1 IS at most alta: centred weights baja +0.44 | normal +0.39 | alta -0.03 | muy alta -0.80
    IF rel_mean24h IS at most Medium: centred weights baja +0.58 | normal +0.28 | alta -0.27 | muy alta -0.58
    IF rel_lag1 IS at least normal AND rel_mean24h IS at least Medium: centred weights baja -0.67 | normal -0.00 | alta +0.28 | muy alta +0.39

In the same fit the compound terms are used by two rules: `IF local_hour IS Primeras horas` (Madrugada or Mañana) and
`IF local_dow IS Fin de semana`. Others: `de_no2_h3` (B seed 0) `IF no2_lag24h IS at least Fair AND relative_humidity IS at least
Medium` (centred: Good -1.69, Fair -0.18, Moderate +0.61, Poor or worse +1.26) and `IF no2_lag3h IS at most Fair AND
valid_hour_local IS Afternoon`; Water `IF ammoniacal_nitrogen IS Bajo>L AND local_hour IS Low or Medium`.

## 5. Atlas code changes, risks and what is left

* **Atlas code.** `rule_conditions` / `condition_labels` / the capability probes (`ordinal_conditions`, `compound_terms`) in
  `atlas.ml.exfuzzy_features`; `rule_signatures`, `classifier_rule_sets`, `classifier_term_usage` and `build_consensus_model` read
  conditions through them (they give the same result on ex-fuzzy 3.4.0 and with the options off); `ordinal_conditions` (True or the inputs) and
  `compound_terms` in `FuzzyClassifierParams` / `FuzzyParams`, left out of `as_dict` when off; `rules_export` refuses an
  `at least` / `at most` / compound condition (`UnsupportedModelError`) because contract v0.7 has no operator; the driver
  `atlas.ml.experiment_ordinal`. Tests: `tests/ml/test_ordinal_conditions.py`.
* **Not done on purpose.** No contract bump, no web change, nothing published. `atlas.explain.{classifier,mixture,traces}` and
  `report_fx` still index `linguistic_variable_names()[term]`: they serve contract objects, so they need the v0.8 operator first.
* **Summary of the answer.** Under the registered rule B beats A in 4 of 10 tasks, but only two (`nyc_pickups_h3`, `uk_water_do`)
  survive the median check, one of them by 0.0001, and the test period shows no gain in the seed means (section 3). The
  option gave the clearest validation gains in Water and NYC +3 h. In NYC +3 h the B fit is also smaller (9 rules and 12
  conditions against 15 and 16); in Water it is larger (81 conditions against 64). In the larger searches (Germany +12 h,
  +24 h) B is bigger without better validation. A v0.8 with an operator on `Antecedent` is justified, if at all, by
  readability in the two robust tasks, not by accuracy.
* **Confounds and risks.** B changes the option and the compound terms together; the search space of B is larger at equal
  budget (150 x 60), so a gain or loss may partly be about the budget; 10 decisions without correction; the New York
  validation window is short; A re-selected a different shape in NYC +6 h than the published one; B's selected fits have more
  conditions in 7 of 10 tasks.
* **Reproduce** (the large machine, section 0.8): `arms --workers 18` (61 min), `decide`, `test`, `report`; the outputs are in
  `artifacts/experiments/ordinal_conditions/` of the workstation (git-ignored).
