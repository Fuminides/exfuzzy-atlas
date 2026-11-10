# FX2: hour vocabularies with the proportional term remap (ex_fuzzy PR 35)

**Status: protocol written and committed before any fit of an FX2 arm. Results below the line "Results" are added after the runs.**
Same limits as `docs/ml/fx_retrain_with_fixed_exfuzzy.md` (FX): firing, association degree and rule weight are degrees of rule
match, never probabilities, contributions or risk; a term named after a source ("Punta de tarde") says how the input was split,
not that a rule explains anything; no causal, clinical, sanitary or regulatory claim; no real-time claim. The models of this
experiment are fitted on the unreleased local ex_fuzzy build (`docs/reproduce.md`); nothing here is published by this task.

## 0. Protocol and decision rules (written and committed before any fit of the FX2 arms)

**History, for honesty.** The author of this protocol had read the whole FX document before writing it, so it knows the FX
outcomes: Madrid `h5_fix` 0.319, `h5_sel` 0.335 against `base` 0.336; NYC `h5` 0.366 / 0.399, `h6` 0.387 against `h4` 0.382 and
persistence 0.401; and that "no gain" was the FX answer for both. It had also printed, from the FX artifacts, the term usage of
the three FX Madrid arms (clip decoding) for all nine inputs. No FX2 arm had been fitted and no number of an FX2 arm had been
seen. Check A of section 0.3 (a 25-generation fit on synthetic data, no Atlas data) was run while the tooling was being
written, before this document: the hash was identical on 2ffcfb9 and 915b836 (`b780553bc84885ad`, 8 rules, train accuracy 0.468333),
and the table below fixes it as the expected value. Checks B and D, the controls and all arms were run **after** this document was
committed.

### 0.1 What changes, and why this is a cleaner test (not a perfect one)

FX (PR 32) bounds every term gene by the largest partition `M` and decodes an index above a variable's last term by clipping it
to that last term. FX Section 1 named the consequence: the last term of every smaller variable is reached by several gene values
and is over-represented under uniform sampling; for Madrid that term is the rarest NO2 band, "Desfavorable o peor".
`Fuminides/ex-fuzzy` PR 35 (stacked on 32) decodes a gene `g` as term `(g * n) // M` of a variable with `n` terms:

* identity when `n == M` (so a variable with the largest partition, and any problem whose variables all have the same count,
  decode as before);
* order preserving, every term reachable, each term gets `floor(M / n)` or `ceil(M / n)` gene values, and the **extra gene value
  goes to the first terms** instead of the last.

Gene values per term, as decoded by the build (`atlas.ml.fx_checks.decoded_term_table`, checked in `tests/ml/test_fx_checks.py`):

| M | n | clip (FX, PR 32) | remap (FX2, PR 35) | where it matters |
|---|---|---|---|---|
| 5 (Madrid hour 5) | 4 | 1, 1, 1, **2** | **2**, 1, 1, 1 | the four NO2 bands (`Buena` now 2, `Desfavorable o peor` 1), wind (4 Beaufort groups) |
| 5 | 3 | 1, 1, **3** | **2**, **2**, 1 | temperature, humidity (Low, Medium, High), weekday (Laborable, Sábado, Domingo) |
| 5 | 5 | 1, 1, 1, 1, 1 | same | the hour |
| 6 (NYC hour 6) | 4 | 1, 1, 1, **3** | **2**, 1, **2**, 1 | the four `rel_lag*` (baja, normal, alta, muy alta) |
| 6 | 3 | 1, 1, **4** | 2, 2, 2 | `local_dow`, `rel_mean24h` |
| 5 (NYC hour 5) | 4 / 3 | as the Madrid rows | as the Madrid rows | |

So the remap is **not uniform** either: for a 4-term variable under `M = 5`, term 0 gets two gene values (40 % of the term draws)
instead of 20-25 %. For Madrid that term is now `Buena`, the commonest NO2 band, and for the 3-term inputs the last term (High,
Domingo) gets one value of five. The skew moves from the last term to the first ones; this experiment tests whether the FX result
depended on the first kind of skew, not whether a perfectly neutral prior would change it. The unselected prior is shown by
`decoded_term_table`; after selection, what the rules use is shown by the term usage below.

**Expected consequence for equal-count fits, and a premise that does not hold.** For `n == M` the map is the identity, so such a
fit is bit-for-bit that of the clip decoder. The Madrid and NYC problems are **not** equal-count even with the 4-term hour: three
Madrid inputs (temperature, humidity, weekday) and two NYC inputs (`local_dow`, `rel_mean24h`) have 3 terms under `M = 4`, where the clip
gave `0, 1, 2, 2` and the remap gives `0, 0, 1, 2`. A fit that draws one of them decodes differently, so its search path diverges.
We therefore **expect** that `fx-m4-repro` re-run on 915b836 does **not** reproduce 0.3480715, and the same for the NYC `h4` fits;
that would be the remap working as specified, not a defect. What must hold bit-for-bit are the checks of 0.3, which isolate the
remap from the other merged work (PR 34).

### 0.2 Build

915b836 = `atlas/local-integration` of a local ex-fuzzy worktree = 2ffcfb9 + PR 35 (contains PR 32) + PR 34 (rule-set stability
diagnostics). `PYTHONPATH=/path/to/ex-fuzzy:src:apps/api`; `exfuzzy_version()` records `3.3.1+g915b836`.
Nothing is pip-installed; `make test` and `make lint` stay on the pinned 3.3.1. The FX2 configs (`configs/ml/fx2_*.json`) require
`term_bound_fix` and the new probe `proportional_term_remap` (`atlas.ml.exfuzzy_features.has_proportional_term_remap`: gene 2 of a 3-term
variable under a 5-term maximum decodes to term 1) and refuse to run on a library without it. Their `exfuzzy_source` is
`local atlas/local-integration @ 915b836 (3.3.1 + PRs #30 #27 #29 #31 #32 #35 #34)`.

### 0.3 Reproduction checks

| check | what | expected | if not |
|---|---|---|---|
| A | `python -m atlas.ml.fx2_clip_check digest` on 2ffcfb9 and 915b836: one small fit (600 rows, 6 inputs, all with 4 terms, 12 rules x 3 antecedents, 25 generations) printed as a hash of the rules and weights | identical on both builds (seen: `b780553bc84885ad`) | **stop and report**: PR 35 or 34 changed an equal-count fit |
| B | `fx2-m4-clip`: Madrid AT-041d (`fx-m4-repro` config, 60 x 4, seed 0) on 915b836 with the PR 35 remap replaced by the clip (`python -m atlas.ml.fx2_clip_check select ...`) | validation macro-F1 **0.3480715** (0.3480714999186046) and the same selection record as `fx-m4-repro` | **stop and report**: something other than the remap differs from 2ffcfb9 |
| C | `fx2-m4`: the same fit with the remap (the build as is), seeds 0-2 | seed 0 differs from 0.3480715 (the 3-term inputs, 0.1); reported as an informational control, **not** in any decision rule | reported as found |
| D | `fx2-w-repro`: Water TSK regression, 40 x 2, seed 0 (`fx-w-base` config), on 915b836 | validation RMSE 0.9067318 and 39 rules (regression decoder is unchanged by PR 35) | **stop and report** |

Check B is the answer to "does 915b836 reproduce the FX fit". It reproduces it exactly when the only difference between the two builds that
the fit can see is undone, which is the strongest statement available for a problem with 3- and 4-term inputs.

### 0.4 Arms

All arms: splits, rows, class merge, subsample, budget (150 generations x 60 individuals), dominance-score weights, candidate
shapes and seeds (0, 1, 2) **as FX Experiments 1 and 3**. Only the build differs (and with it the term decoding). Run names do not
overwrite FX runs. Validation only for decisions.

| id | task | vocabulary and protocol | config |
|---|---|---|---|
| `fx2-m5-fix` | Madrid | `h5_fix`: hour in 5 periods (`madrid_partitions_hour5.json`), shape 60 x 4, seeds 0-2 (`--selection` of `ica2-justified`) | `fx2_madrid_no2_h6_hour5_fixed_experiment.json` |
| `fx2-m5-sel` | Madrid | `h5_sel`: six shapes with seed 0, best validation macro-F1, then seeds 0-2 | `fx2_madrid_no2_h6_hour5_experiment.json` |
| `fx2-n5-fix`, `fx2-n5-sel` | NYC | `h5` (Madrugada 0-6, Mañana 7-10, Mediodía 11-14, Tarde 15-21, Noche 22-23), `_fix` = 30 x 2 (`--selection` of `level-rel7`) and `_sel` = six shapes | `fx2_nyc_pickups_h1_hour5_{fixed_,}experiment.json` |
| `fx2-n6-fix`, `fx2-n6-sel` | NYC | `h6` (..., Tarde 15-16, Punta de tarde 17-19, Noche 20-23), same two protocols | `fx2_nyc_pickups_h1_hour6_{fixed_,}experiment.json` |
| `fx2-m4` | Madrid | informational: AT-041d vocabulary (4-term hour), 60 x 4, seeds 0-2, with the remap | `fx2_madrid_no2_h6_hour4_control_experiment.json` |
| `fx2-n4` | NYC | informational: `h4` published vocabulary, 30 x 2, seeds 0-2, with the remap | `fx2_nyc_pickups_h1_hour4_control_experiment.json` |
| `fx2-m4-clip`, `fx2-w-repro` | Madrid, Water | checks B and D | `fx2_madrid_no2_h6_hour4_clip_check_experiment.json`, `fx2_water_do_chrono_temp_repro_experiment.json` |

The two informational controls are an addition to FX, made because the **comparison bases are the published figures fitted with the
clip decoder** (they stay the bases, as in FX); `fx2-m4` and `fx2-n4` show how much the remap alone moves the base arms. They enter no rule.
Comparison bases: Madrid `base` = AT-041d, validation macro-F1 per seed 0.3481 / 0.3287 / 0.3310 (mean 0.3359, sd 0.0106), Jaccard 0.1515;
NYC `h4` = 0.3981 / 0.3868 / 0.3612 (mean 0.3820, sd 0.0189), level persistence 0.4013 on the same validation block.

### 0.5 Measurements

* As FX (validation 2024 for Madrid, 2025-01 for NYC; mean ± sd with n - 1 over the seeds): macro-F1, balanced accuracy,
  accuracy, Regular and Desfavorable recall / precision for Madrid, rules kept, mean pairwise Jaccard of the rules, macro-F1 by
  seed. For NYC also the rules that use `local_hour` or `local_dow`.
* **Term usage** (`atlas.ml.fx_checks.classifier_term_usage`, `python -m atlas.ml.report_fx ... --usage ... --compare-usage`): number of
  antecedents on each term of each input, summed over the three seeds, for FX (clip) and FX2 (remap) side by side. In particular:
  the four NO2 inputs by band (and the share of NO2 antecedents on `Desfavorable o peor`), the hour terms, and for NYC the hour and
  `local_dow` terms. The comparison is between runs with the **same vocabulary** (`fx-m5-fix` against `fx2-m5-fix`, ...).
* Reading rule for term usage (fixed now): the counts are tens of antecedents per arm and the search selects, so a change in usage
  is a description of the fitted models, not a measurement of the prior and not evidence that the skew caused a change in
  macro-F1. The prior is given by the gene table of 0.1.

### 0.6 Decision rules (those of FX, unchanged)

* **Madrid** (FX Experiment 1). A protocol **enters** if its mean validation macro-F1 is at least 0.011 above `base` (>= 0.347), or
  its Jaccard is at least 0.05 above `base` (>= 0.201) while its macro-F1 is not more than 0.011 below (>= 0.325).
* **NYC** (FX Experiment 3). A vocabulary **enters** on a protocol if (a) its mean validation macro-F1 is at least 0.019 above the `h4`
  mean (>= 0.401) and above persistence (> 0.4013), and (b) at least two of three seeds have a rule that uses `local_hour` or `local_dow`.
* **Recommendation.** If an arm enters on **both** protocols (`_fix` and `_sel`) of its task and vocabulary: "candidate for publication on
  the local build", and stop there (A0 decides about publishing). Otherwise: "no gain, the published models stay".
* **Test period.** Read only for an arm that enters, once, its three seeds in one command, baselines as already published (same rows and
  splits). If no arm enters, no test row is read.

### 0.7 Budget and order

At most 2.5 h of CPU, `OMP_NUM_THREADS=4`, RSS below 2 GB, fits run one at a time, `free -g` checked before. Order: checks A, B, D, then
Madrid (`fx2-m4`, `fx2-m5-fix`, `fx2-m5-sel`), then NYC (`fx2-n4`, `fx2-n5-fix`, `fx2-n6-fix`, `fx2-n5-sel`, `fx2-n6-sel`). If the budget runs out the
run stops at a coherent point (an experiment's two protocols complete) and the report says so.

## Results

Fits ran on 915b836 (`exfuzzy_version` `3.3.1+g915b836`, `python -c 'import ex_fuzzy; print(ex_fuzzy.__file__)'` printed the
local ex-fuzzy worktree path), sequentially, `OMP_NUM_THREADS=4`; every manifest and summary carries the FX2 `exfuzzy_source`. Total about 55 min of
CPU (checks 3 min, Madrid 26 min, NYC 26 min), peak RSS 1.05 GB. Tables are generated by `python -m atlas.ml.report_fx`
(means ± sd with n - 1 over seeds 0-2). FX figures are the FX document's (clip decoding); they were re-read from the FX artifacts, not refitted.

### R.1 Reproduction checks

| check | result |
|---|---|
| A, equal-count digest | identical on 2ffcfb9 and 915b836: `b780553bc84885ad`, 8 rules, train accuracy 0.468333 |
| B, `fx2-m4-clip` (Madrid AT-041d, 60 x 4, seed 0, remap replaced by the clip) | validation macro-F1 **0.3480714999186046**, equal to `fx-m4-repro` to the last digit, and the same confusion matrix. Fit 129 s |
| C, `fx2-m4` (the same fit with the remap) | seed 0: **0.299**, not 0.348, as expected in 0.1; seeds 0-2: 0.299, 0.323, 0.321 (mean 0.314 ± 0.014) |
| D, `fx2-w-repro` (Water TSK, 40 x 2, seed 0) | validation RMSE **0.9067317609233859** (equal to `fx-w-base` seed 0), 39 rules |

Checks A, B and D, the ones that had to be bit-for-bit, are. So PR 34 and the rest of the 2ffcfb9-to-915b836 difference change nothing in
these fits, the regression decoder is untouched, and the whole difference between FX and FX2 fits comes from the remap. The expectation
that the Madrid `fx-m4-repro` would reproduce 0.3480715 on 915b836 holds only with the remap undone (check B): with the remap, the
three 3-term inputs decode differently under `M = 4` (0.1), the search diverges and seed 0 gives 0.299. That is the remap
doing what it specifies; it is the reason the AT-041d and NYC `h4` bases remain the **published** figures (fitted with the clip), and the
reason the informational controls exist. No run was stopped.

### R.2 Madrid NO2 t+6 h, validation 2024 (191,459 complete rows)

| arm | shape | macro-F1 | bal-acc | acc | Regular recall / prec | Desf. recall / prec | rules | Jaccard | macro-F1 by seed |
|---|---|---|---|---|---|---|---|---|---|
| `base` (AT-041d, 4-term hour, clip) | 60 x 4 | 0.336 ± 0.011 | 0.399 ± 0.045 | 0.731 ± 0.018 | 0.329 / 0.087 | 0.069 / 0.014 | 13.7 | 0.151 | 0.348, 0.329, 0.331 |
| `h5_fix` FX (clip) | 60 x 4 | 0.319 ± 0.004 | 0.407 ± 0.062 | 0.698 ± 0.042 | 0.322 / 0.051 | 0.139 / 0.017 | 19.7 | 0.015 | 0.323, 0.318, 0.315 |
| **`h5_fix` FX2 (remap)** | 60 x 4 | **0.320 ± 0.031** | 0.431 ± 0.056 | 0.684 ± 0.090 | 0.400 / 0.075 | 0.183 / 0.015 | 19.3 | **0.026** | 0.284, 0.333, 0.342 |
| `h5_sel` FX (clip) | 30 x 4 | 0.335 ± 0.004 | 0.400 ± 0.047 | 0.723 ± 0.040 | 0.191 / 0.105 | 0.243 / 0.023 | 10.3 | 0.090 | 0.333, 0.340, 0.333 |
| **`h5_sel` FX2 (remap)** | 60 x 2 | **0.316 ± 0.014** | 0.341 ± 0.034 | 0.758 ± 0.022 | 0.128 / 0.057 | 0.076 / 0.013 | 12.7 | **0.117** | 0.328, 0.301, 0.321 |
| `h5_ctrl` FX (3.3.1, 5 terms) | 60 x 4 | 0.322 ± 0.022 | 0.418 ± 0.043 | 0.691 ± 0.068 | 0.436 / 0.077 | 0.097 / 0.012 | 14.7 | 0.086 | 0.335, 0.297, 0.336 |
| *`m4` FX2 control (AT-041d vocabulary, remap; informational)* | 60 x 4 | 0.314 ± 0.014 | 0.415 ± 0.060 | 0.673 ± 0.073 | 0.366 / 0.062 | 0.141 / 0.010 | 13.7 | 0.027 | 0.299, 0.323, 0.321 |

Shape selection of `h5_sel` FX2 (seed 0, validation macro-F1): 30x2 0.300, 30x3 0.309, 30x4 0.314, **60x2 0.328**, 60x3 0.301, 60x4 0.284
(FX picked 30 x 4 at 0.333). The seeds of `h5_fix` FX2 range over 0.058 (0.284 to 0.342; sd 0.031 against 0.004 for the same arm in FX).

**Decision (rule of 0.6).** `h5_fix`: 0.320 against the 0.347 needed, Jaccard 0.026 against the 0.201 needed: does not enter. `h5_sel`: 0.316,
Jaccard 0.117: does not enter. **Neither protocol enters.** No test row was read for Madrid.

**Term usage, antecedents summed over seeds 0-2** (the rows of `classifier_term_usage`; counts are small, see the reading rule of 0.5):

| NO2 bands (4 inputs together) | Buena | Razonablemente buena | Regular | **Desfavorable o peor** | antecedents |
|---|---|---|---|---|---|
| `base` AT-041d (clip, M = 4) | 19 (58 %) | 9 | 4 | 1 (3 %) | 33 |
| `m4` control (remap, M = 4) | 14 (50 %) | 9 | 2 | 3 (11 %) | 28 |
| `h5_ctrl` (3.3.1) | 18 (62 %) | 8 | 2 | 1 (3 %) | 29 |
| `h5_fix` FX (clip, M = 5) | 27 (44 %) | 18 | 10 | **7 (11 %)** | 62 |
| `h5_fix` FX2 (remap, M = 5) | 36 (67 %) | 13 | 5 | **0 (0 %)** | 54 |
| `h5_sel` FX (clip) | 13 (54 %) | 7 | 2 | 2 (8 %) | 24 |
| `h5_sel` FX2 (remap) | 15 (75 %) | 5 | 0 | **0 (0 %)** | 20 |

| hour terms (Noche, Punta de mañana, Mediodía, Punta de tarde, **Noche tardía**) | antecedents | `Noche tardía` per seed |
|---|---|---|
| `h5_fix` FX (clip) | 6, 6, 5, 4, **3** = 24 | 1 / 1 / 1 |
| `h5_fix` FX2 (remap) | 10, 5, 10, 4, **2** = 31 | 1 / 0 / 1 |
| `h5_sel` FX (clip) | 4, 2, 3, 0, **4** = 13 | 2 / 2 / 0 |
| `h5_sel` FX2 (remap) | 2, 2, 4, 1, **2** = 11 | 1 / 1 / 0 |

| last term of the three 3-term inputs (temperature High, humidity High, weekday Domingo) | share of the antecedents on those inputs |
|---|---|
| `h5_fix` FX (clip) | 16 / 35 = 46 % |
| `h5_fix` FX2 (remap) | 8 / 34 = 24 % |
| `h5_sel` FX (clip) / FX2 (remap) | 6 / 15 = 40 % / 4 / 14 = 29 % |

Unselected prior (`decoded_term_table`, one gene value in `M` per row entry): NO2 band (n = 4, M = 5) clip 20/20/20/**40** %, remap **40**/20/20/20 %;
3-term inputs clip 20/20/**60** %, remap **40/40**/20 %; the hour 20 % per term on both.

Reading:

* **The confound is real in the prior and in what the rules use.** The last NO2 band went from 11 % of the NO2 antecedents (`h5_fix` clip) to 0 %
  (remap) and from 8 % to 0 % in `h5_sel`; the first band went from 44 % to 67 % and from 54 % to 75 %; the last term of the 3-term inputs from 46 % to 24 %. The
  rules follow the prior (the rare band is no longer favoured; the commonest one now is), as they should if the skew had an effect.
* **Removing it does not recover the metric.** `h5_fix` is 0.319 (clip) and 0.320 (remap); `h5_sel` 0.335 and 0.316. Against `base` neither is
  near the rule (-0.016 and -0.020). FX's "no gain" was therefore **not** produced by the over-representation of the rarest NO2 band alone;
  with only three seeds and sd 0.004-0.031, a smaller share of it cannot be excluded.
* **The remap alone moves the base arm.** With the AT-041d vocabulary the remap scores 0.314 ± 0.014 against 0.336 published (-0.022, about two sd),
  and the Jaccard falls from 0.151 to 0.027. Like for like (remap against remap), `h5_fix` is +0.006 and `h5_sel` +0.002 over the 4-term control, i.e.
  no difference at this seed count. This reading is post hoc (the control was added to the protocol, not part of any rule).
* The fifth hour term (Noche tardía) is used in both FX2 arms, as in FX. The best seed of `h5_sel` FX2 (seed 0, 13 rules) has two rules on it:
  "IF relative_humidity IS Low AND valid_hour_local IS Noche tardía THEN ICA = Desfavorable o peor" (peso 0.00622) and, with two NO2 terms, a
  Regular one; FX's best seed had the one-condition version for the rare class. Associations of the 2019-2023 sample with a rare class, not explanations.
* Desfavorable recall rises for `h5_fix` (0.183, FX 0.139, base 0.069) with a precision of 1.5 %: the usual trade of a rare class, not a gain.

### R.3 NYC demand level, validation 2025-01 (53,575 rows)

| arm | shape | macro-F1 | bal-acc | acc | rules | Jaccard | macro-F1 by seed | rules with `local_hour` / `local_dow`, per seed |
|---|---|---|---|---|---|---|---|---|
| level persistence | - | 0.401 | 0.401 | 0.447 | - | - | - | - |
| `h4` published (clip) | 30 x 2 | 0.382 ± 0.019 | 0.393 ± 0.026 | 0.426 ± 0.015 | 9.7 | 0.096 | 0.398, 0.387, 0.361 | 0 / 0 / 0 |
| *`h4` FX2 control (remap; informational)* | 30 x 2 | 0.372 ± 0.011 | 0.387 ± 0.006 | 0.402 ± 0.019 | 10.0 | 0.162 | 0.385, 0.366, 0.366 | 1 / 1 / 3 |
| `h5_fix` FX (clip) | 30 x 2 | 0.366 ± 0.026 | 0.367 ± 0.020 | 0.418 ± 0.038 | 7.3 | 0.275 | 0.352, 0.350, 0.396 | 3 / 3 / 1 |
| **`h5_fix` FX2 (remap)** | 30 x 2 | **0.374 ± 0.012** | 0.385 ± 0.013 | 0.420 ± 0.039 | 9.0 | 0.103 | 0.380, 0.360, 0.382 | 3 / 2 / 1 |
| `h5_sel` FX (clip) | 60 x 3 | 0.399 ± 0.007 | 0.407 ± 0.007 | 0.437 ± 0.005 | 13.7 | 0.123 | 0.406, 0.393, 0.398 | 2 / 2 / 3 |
| **`h5_sel` FX2 (remap)** | 60 x 4 | **0.370 ± 0.027** | 0.373 ± 0.034 | 0.421 ± 0.016 | 14.7 | 0.072 | 0.401, 0.357, 0.353 | 4 / 3 / 2 |
| `h6_fix` = `h6_sel` FX (clip) | 30 x 2 | 0.387 ± 0.025 | 0.382 ± 0.023 | 0.447 ± 0.023 | 10.0 | 0.080 | 0.401, 0.400, 0.358 | 0 / 1 / 4 |
| **`h6_fix` FX2 (remap)** | 30 x 2 | **0.365 ± 0.017** | 0.366 ± 0.006 | 0.411 ± 0.020 | 7.0 | 0.081 | 0.364, 0.382, 0.348 | 0 / 1 / 4 |
| **`h6_sel` FX2 (remap)** | 60 x 4 | **0.376 ± 0.026** | 0.374 ± 0.025 | 0.433 ± 0.030 | 13.7 | 0.048 | 0.391, 0.391, 0.345 | 9 / 3 / 2 |

Shape selection (seed 0, validation macro-F1), FX2: `h5`: 30x2 0.380, 30x3 0.347, 30x4 0.385, 60x2 0.376, 60x3 0.398, **60x4 0.401**. `h6`:
30x2 0.364, 30x3 0.362, 30x4 0.370, 60x2 0.361, 60x3 0.362, **60x4 0.391**. (FX: `h5` 60x3 0.406, `h6` 30x2 0.401.)

**Decision (rule of 0.6).** Condition (a), mean macro-F1 of at least 0.401 and above persistence (0.4013), fails for all four FX2 arms (0.374, 0.370, 0.365, 0.376);
condition (b) (at least two of three seeds with a rule on `local_hour` or `local_dow`) holds for all four but is not enough. **No vocabulary
enters on either protocol.** No test row was read for NYC.

**Term usage** (antecedents summed over the seeds). `local_hour`: `h5_fix` FX2 one antecedent on Mañana (FX none); `h5_sel` FX2 Madrugada 2 and **Tarde 2**
(FX: Madrugada 2, Mañana 1); `h6_fix` FX2 none; `h6_sel` FX2 Madrugada 1, Mañana 1, **Punta de tarde 1**, **Noche 1** (FX none of the last two). So for the first time
a rule of some seed uses one of the evening terms the new vocabulary adds (four antecedents in all: Tarde 2 in `h5_sel`, Punta de tarde 1 and Noche 1 in
`h6_sel`), but that is not a result and does not lift macro-F1.
The `rel_lag*` bands (4 inputs together; baja / normal / alta / muy alta): `h5_fix` FX 3 / 7 / 1 / 2 against FX2 7 / 9 / 3 / 1; `h5_sel` FX 13 / 20 / 13 / 6
against 13 / 15 / 13 / 6; the 4-term control FX 9 / 16 / 4 / 3 against remap 9 / 12 / 5 / 2. There is no pattern comparable to Madrid's: here the last
band is not a rare class that the rules abandon.

### R.4 Recommendation

* Madrid: **no gain, AT-041d stays** (neither protocol enters; 0.320 and 0.316 against 0.347 required).
* NYC: **no gain, the published NYC model stays** (no vocabulary enters on any protocol; 0.365-0.376 against 0.401 required and 0.4013 persistence).
* Nothing is a candidate for publication on the local build. Nothing was published or registered by this task; no test period was read.

What the experiment adds to FX: the over-representation of the rarest NO2 band by the clip is real (7 of 62 NO2 antecedents in `h5_fix` against 0 of 54
with the remap), and removing it neither helps nor hurts at this resolution on `h5`; but the remap changes the AT-041d and `h4` bases themselves (-0.022 on
Madrid, -0.010 on NYC against the published figures, the Madrid one about two sd), so any future comparison of a remap arm with a clip-fitted base
mixes two effects. If the library goes to a release with the remap, the Madrid and NYC bases should be refitted on it before a new vocabulary is judged.

### R.5 Limits

* Three seeds, one validation block per task. The sd of the FX2 arms (0.011-0.031) is as large as most differences; single-seed shape selection is noisy (Madrid chose 60 x 2 here,
  30 x 4 in FX; NYC `h5` 60 x 4, `h6` 60 x 4).
* The remap is not uniform (it favours the first terms, 0.1), so this tests the removal of the last-term skew, not neutrality. After selection the term usage describes the
  fitted models; it does not measure the prior and is not evidence of cause.
* The informational controls were added to the protocol before any fit but are not in FX; the like-for-like readings that use them are post hoc.
* The bases are the published clip-fitted figures; the like-for-like base (remap) is a control with three seeds and is below the published one.
* Same honesty limits as FX: degrees of match, not probabilities; no causal, sanitary or regulatory claim.

## Reproduce

```bash
export ATLAS_DATA_DIR=/path/to/exfuzzy-atlas/data ATLAS_ARTIFACTS_DIR=/path/to/exfuzzy-atlas/artifacts
LOCAL=/path/to/ex-fuzzy     # atlas/local-integration @ 915b836 (docs/reproduce.md)
make exfuzzy-info EXFUZZY_SRC=$LOCAL                                   # <path> 3.3.1+g915b836
make fx2-checks   EXFUZZY_SRC=$LOCAL OMP_NUM_THREADS=4                 # A (digest; run it also with the 2ffcfb9 tree), B, D
make fit-fx2-madrid EXFUZZY_SRC=$LOCAL                                 # fx2-m4, fx2-m5-fix, fx2-m5-sel (validation only)
make fit-fx2-nyc    EXFUZZY_SRC=$LOCAL                                 # fx2-n4, fx2-n5-fix, fx2-n6-fix, fx2-n5-sel, fx2-n6-sel
export PYTHONPATH=src:apps/api
F="no2_last no2_lag1h no2_lag3h no2_lag24h wind_speed valid_hour_local temperature relative_humidity valid_weekday"
python -m atlas.ml.report_fx madrid --arm base=ica2-justified --arm h5_fix_clip=fx-m5-fix --arm h5_fix_remap=fx2-m5-fix \
  --arm h5_sel_clip=fx-m5-sel --arm h5_sel_remap=fx2-m5-sel --arm m4_remap=fx2-m4 --usage $F --compare-usage
python -m atlas.ml.report_fx nyc --arm h4=level-rel7 --arm h4_remap=fx2-n4 --arm h5_fix_remap=fx2-n5-fix --arm h5_sel_remap=fx2-n5-sel \
  --arm h6_fix_remap=fx2-n6-fix --arm h6_sel_remap=fx2-n6-sel --usage local_hour local_dow --compare-usage
```

The `make` targets run the fits with the validation-only commands of FX Section 6, with the new configs; `OMP_NUM_THREADS=4` is set by the targets.
(The `make fx2-checks` target runs B with the same wrapper `atlas.ml.fx2_clip_check`.) Run directories: `madrid_no2_h6/experiments/fx2-*`,
`nyc_pickups_h1/experiments/fx2-*`, `uk_water_do/experiments/fx2-w-repro`.

Tests (2026-10-31): `make lint` clean; `make test` on the pinned 3.3.1: 757 passed, 156 skipped; `tests/ml` on 915b836
(`PYTHONPATH=<local>:src:apps/api`): 203 passed, 2 skipped (the two that document the pinned behaviour).
