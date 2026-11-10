# ex_fuzzy 3.3.1: verified API facts, wrapper decisions and scaling (AT-040, AT-042, AT-044)

All facts below were checked against the installed package (`<env>/lib/python3.12/site-packages/ex_fuzzy`,
version 3.3.1) by reading its source and running it; the tests in `tests/ml/` pin the ones the code depends on.
**Everything labelled "synthetic" uses invented data: no number here says anything about Madrid.**

## 1. Verified API facts

| Topic | Fact |
|---|---|
| Entry point | `ex_fuzzy.evolutionary_fit_regression.BaseFuzzyRulesRegressor(nRules, nAnts, n_linguistic_variables, linguistic_variables, consequent_type, rule_mode, tolerance, backend)`; `fit(X, y, n_gen, pop_size, random_state)`; `get_rulebase()` returns a `RuleBaseT1Regression` |
| Fitness | The GA maximises the **R² of the rule-base prediction on the training rows**. `performance_` equals `r2_score(y, predict(X))` to 1e-12 (checked in additive and sufficient mode) |
| Partitions | Fixed before the GA (quantile trapezoids, `utils.construct_partitions`); the GA only chooses rules and consequents. They come from the training rows only |
| Feature names | A DataFrame keeps its column names (`feature_names_in_`, `fuzzyVariable.name`) *if the library builds the partitions*; `predict` raises if the DataFrame columns differ in name or order. A numpy `X` gives names `"0"`, `"1"`, ... |
| Rule base | `.antecedents` (list of `fuzzyVariable`, each with `.name`, `.units`, `.linguistic_variables`, `.domain()`), `.rules` (`RuleSimple.antecedents` = term index per feature, `-1` unused; optional `.modifiers`), `.scalar_consequents`, `.tnorm` (`np.prod`), `.rule_mode`, `.tolerance`, `.y_mean` |
| Inference | Zero-order TSK: `Σ f c / Σ f`, clipped into `[min c, max c]`. If `Σ f ≤ 1e-10` the output is `y_mean` (the training-target mean) |
| Public hooks used | `compute_antecedents_memberships(X)`, `compute_rule_antecedent_memberships(X, cached)` (raw firing, the t-norm output), `inference(X, cached)` |
| Semi-private hook used | `evolutionary_fit_regression._apply_rule_mode(firing, rule_mode, tolerance)` gives the *effective* firing (what the inference sums). It is the only way to get it: `sufficient` keeps the row's argmax rule if its firing exceeds `tolerance` and zeroes the rest. Guarded by an import check and by tests that rebuild the prediction from the effective firing (≤ 1e-9) |
| Modifiers | `rule.modifiers[f]` outside `{-1, 1}` raises the membership to that power before the t-norm. The GA never produces them; the trace supports them (tested with a hand-built rule base) |
| Domain clipping | `fuzzyVariable.compute_memberships` clips `x` to the variable domain (training min/max) first, so any input beyond the training range has the membership of the nearest edge. `rules.json` terms do not carry the domain (see §6) |
| Non-finite input | `X` must be finite; NaN or inf raises `ValueError`. The wrapper never sends such rows to the library |
| Membership classes | `FS` (trapezoid, 4 params), `triangularFS` (a subclass that keeps the **4-parameter trapezoid** form), `gaussianFS` (`[mean, std]`, `exp(-((x-mean)/std)**2)`, no 1/2 factor), `categoricalFS` (no parameters) |
| Categorical detection | `construct_partitions` runs `detect_categorical_mask` by default: any whole-number column with ≤ 5 distinct values (e.g. a 0/1 holiday flag) silently becomes `categoricalFS` |
| Backends | `pymoo` (CPU NumPy) is used; `evox` (GPU) not evaluated |
| Determinism | Same `random_state` and data give identical rules and consequents (tested) |

## 2. Wrapper decisions (`src/atlas/ml/fuzzy.py`)

* **Partitions are built by the wrapper** with `detect_categorical=False` and passed as `linguistic_variables`.
  Reason: `categoricalFS` has no parameters, so `rules.json` could not describe it. Consequence: a binary flag is
  quantile-partitioned into degenerate trapezoids (`Low` = {0}, `Medium` = [0, 1] everywhere, `High` = {1}); it works
  but yields a vacuous `Medium` term. Prefer to feed continuous or ≥ 6-level features, or ask A0 for a
  `categorical` term type (§6). Constant training columns raise.
* **Calendar features** (`hour`, `weekday`) are treated as plain numbers: `hour` 23 and 0 are far apart in the
  partition. Cyclic encodings (sin/cos) are the feature owner's decision (A1); not done here.
* **Mamdani (`consequent_type="fuzzy"`) is not exposed.** The contract has no description of the evolved output sets,
  so `rules.json` would be incomplete, and per-rule contribution is undefined for it. It would need a contract change.
* **`optimization_result_` is deleted after fit.** It holds the pymoo problem, i.e. the training data: about 200 bytes
  per training row (6.3 MB pickled for 30k rows; 4.2 KB without it). `performance_`, generations run and backend are
  kept in `fit_info` and in the manifest.
* **Missing inputs:** `predict` returns NaN for rows with a non-finite feature; training and evaluation use complete
  rows only, and the dropped counts go to `run_manifest.json` `warnings`.

## 3. Duplicate rules: decision

The GA can return several rules with identical antecedents. In an ad hoc sweep of 24 fitted synthetic models
(6 seeds × 4 rule-mode/tolerance settings) the models carried 39 such groups in total; the demo model has R06 and R16.
They fire with identical strength and differ only in their consequent.

Decision: **keep every rule as its own entry with a positional id (R01, R02, ...) and flag duplicates; never merge or
drop.**

* Positions are the stable key: column `r` of every firing array, `rule_id`, `RuleDefinition.position` and the
  library's rule list stay aligned, so traces, the firing table and rule maps need no mapping layer.
* `rules.json`: `metrics["duplicate_antecedents_of_position"]` holds the position of the first rule of the group and
  `text` ends with `[same antecedents as R06]`. `atlas.explain.duplicate_groups(rulebase)` returns the groups.
* Behaviour to remember: in `additive` mode a duplicate group acts as one rule whose consequent is the mean of the
  members' consequents; in `sufficient` mode `argmax` picks the first member, so later duplicates have effective
  firing 0 and never speak. A rule-map UI should offer the group, not draw the same layer twice.
* Not done: removing duplicates before export would change `predict` unless the consequents were averaged, and the
  averaged rule would no longer be a rule the GA produced. Proposal for later: a dedicated "canonical rule view".

## 4. Serialization

* `model.pkl` is the pickled `FuzzyRegressor` wrapper (estimator, feature names, units, `fit_info`). A first-party
  pickle round-trip gave bit-identical predictions in A0's smoke test and in ours (`np.array_equal`).
* `write_run_dir` reloads the pickle in the temporary directory and compares predictions on up to 500 test rows
  before renaming; a mismatch aborts the run and leaves nothing under the final name (tested).
* `SHA256SUMS` is checked by `load_model` before unpickling. Pickle executes code: only load runs you produced.
* The pickle references `atlas.ml.fuzzy.FuzzyRegressor` and ex_fuzzy classes by import path, so a reload needs the
  same ex_fuzzy version (recorded in the manifest). No cross-version guarantee was tested.
* `ex_fuzzy.persistence` (text save/load) is for classifier rule bases; it was not used.
* Atomicity: `os.rename` of a sibling temp directory on the same filesystem; an existing run is never overwritten.

## 5. Reproduce

All from the worktree root, CPU only. `export OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4` on the shared machine.

```bash
make test lint                                           # whole suite, ~2 s for tests/ml
PYTHONPATH=src python -m atlas.ml demo     # synthetic series -> artifacts/synthetic_y_h6/<run_id>/
PYTHONPATH=src python -m atlas.ml evaluate --run <run_dir> --table table.parquet
PYTHONPATH=src python -m atlas.ml predict  --run <run_dir> --table table.parquet --out pred.parquet
PYTHONPATH=src python -m atlas.ml explain  --run <run_dir> --table table.parquet --entity E0 --at 2024-02-20T06:00:00Z
PYTHONPATH=src python -m atlas.ml train    --table table.parquet --config run_config.json
```

**Feature table** (what A1/A2/A3 must hand over): one row per `(entity_id, issued_at_utc)`; `issued_at_utc` UTC and
timezone-aware; the feature columns of `RunConfig.features`; `RunConfig.target_column` holding `y(issued_at_utc +
horizon)`. Producing only features observable at `issued_at_utc` is the producer's responsibility; the pipeline
guarantees the chronological split, the embargo check and train-only fitting. `RunConfig` (JSON) is
`atlas.ml.pipeline.RunConfig`; `python -m atlas.ml demo` shows a full example (`atlas.ml.__main__.demo_config`).

**Run directory** `artifacts/<task_id>/<run_id>/`: `model.pkl`, `run_manifest.json` (`RunManifest`), `metrics.json`
(`MetricsReport`), `rules.json` (`ModelRules`), `predictions.parquet` (test period, fuzzy model:
`entity_id, issued_at_utc, valid_at_utc, observed, prediction, model_id, missing_reason`) and `SHA256SUMS`.
`predictions.parquet` goes beyond the four files asked for; it is the CONTRACTS §4 artifact and is cheap.

**Protocol** (`atlas.ml.pipeline.train_run`): chronological train / validation / test by issue time with
`embargo_hours ≥ horizon` (`chronological_split_spec`), hard leakage check (`assert_no_temporal_leakage`), fuzzy model
and baselines (persistence, per-entity hour × weekday climatology of the valid time, Ridge with median imputation and
scaling, `HistGradientBoostingRegressor` without internal early stopping) fitted on complete **training** rows, all
scored on the same complete **test** rows. The validation period is reserved and not used yet. MAE, RMSE, R² overall
and per entity; plus `fit_seconds`, `predict_seconds`, `n_rules`, `mean_rule_length`, `fraction_fallback`.

Synthetic demo result (invented data, 3 entities × 60 days, 843 test rows, `nRules=20, nAnts=3, n_gen=30,
pop_size=30`, seed 0; one run, no error bars):

| estimator | MAE | RMSE | R² |
|---|---|---|---|
| persistence | 6.84 | 8.29 | 0.767 |
| climatology | 13.51 | 15.07 | 0.231 |
| ridge | 5.27 | 6.53 | 0.856 |
| hist_gradient_boosting | 4.45 | 5.58 | 0.895 |
| exfuzzy (TSK) | 6.29 | 7.70 | 0.800 |

This only shows that the harness works; it is not evidence about the fuzzy model's quality.

## 6. Gaps and proposals (nothing here was changed in `contracts`)

1. **`LinguisticVariable` has no `domain`.** ex_fuzzy clips inputs to the training domain, so a membership
   reconstructed from `params` alone differs outside it. Proposal: `domain: [min, max] | null`.
2. **No `categorical` term type.** Needed for flags (holiday, weekend) without the degenerate partition of §2.
3. **Gaussian/triangular parameter semantics** are ex_fuzzy-specific (see §1). `LinguisticTerm` should say so or
   carry a formula tag.
4. **`scripts/make_fixtures.py` computes `fallback_used` from the raw firing sum**, while the library uses the
   effective firing. Equal in additive mode, different in sufficient mode with a tolerance. `atlas.explain` uses the
   effective firing.
5. **`RuleDefinition.metrics` carries the duplicate marker as a float** (position of the first member). A boolean
   plus `duplicate_group` field would be cleaner.

## 7. Scaling benchmark (synthetic, CPU, sequential)

Command (each size in a fresh subprocess; peak RSS = `ru_maxrss` of that process, including the data it generates):

```bash
export OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MKL_NUM_THREADS=4
PYTHONPATH=src python -m atlas.ml.benchmark --sizes 10000 50000 200000 --n-gen 20 --pop-size 30 --out bench1.json
PYTHONPATH=src python -m atlas.ml.benchmark --sizes 50000 --n-gen 50 --pop-size 50 --out bench2.json
```

Setup: 10 features (gamma / normal), `nRules=20`, `nAnts=3`, `n_linguistic_variables=3`, `backend="pymoo"`, single run
per cell on a machine shared with other jobs (timings are indicative, ±2× is plausible; the 10k point benefits from
cache effects). The tiny budgets mean the fitted models are poor (train R² 0.05 to 0.5); only the cost matters.

| n_rows | n_gen × pop_size | evaluations | fit time (s) | s / generation | µs / row / evaluation | peak RSS (MB) | RSS before fit (MB) |
|---|---|---|---|---|---|---|---|
| 10,000 | 20 × 30 | 600 | 1.2 | 0.061 | 0.20 | 238 | 212 |
| 50,000 | 20 × 30 | 600 | 20.2 | 1.01 | 0.67 | 331 | 217 |
| 200,000 | 20 × 30 | 600 | 110.5 | 5.52 | 0.92 | 680 | 241 |
| 50,000 | 50 × 50 | 2,500 | 56.2 | 1.13 | 0.45 | 332 | 218 |

Inference: 200k rows predict in 0.12 s. Pickle: 8.5 KB, independent of n.

**Reading.** Fit time is `≈ n_rows × evaluations × 0.45 to 0.9 µs` (linear in rows and in the GA budget). Memory grows
≈ 2.2 to 2.3 KB per training row (the library precomputes memberships and rule terms for every row), on top of ≈ 0.24 GB.

**Madrid (≈ 24 stations × 6 to 7 years × 8,760 h ≈ 1.3 to 1.5 M rows), extrapolated, not measured:**

| training rows | peak RSS | per evaluation | 2,500 evals (50 × 50) | 10,000 evals (100 × 100) |
|---|---|---|---|---|
| 1.4 M (all) | ≈ 3.3 to 3.5 GB (**over the 2.5 GB cap**) | 0.6 to 1.3 s | 0.4 to 0.9 h | 1.8 to 3.6 h |
| 400 k | ≈ 1.1 GB | 0.18 to 0.37 s | 8 to 15 min | 30 to 60 min |
| 200 k | ≈ 0.7 GB | 0.09 to 0.18 s | 4 to 8 min | 15 to 30 min (measured per-eval: 0.18 s) |

**Recommendation (partly superseded by AT-041, `docs/ml/madrid_no2_h6_results.md` §2: on Madrid the number of GA
evaluations mattered more than the number of rows, and the final fit used 30 k rows).** Do not fit on the full Madrid history.

1. Split chronologically first, then subsample **the training period only**: the test period is evaluated in full
   (inference is cheap: ~0.6 µs/row).
2. Subsample to ≈ 200 to 400 k rows, uniformly within blocks of (entity × month) so that every station and season
   keeps its share; optionally oversample high-concentration hours but then keep the objective in mind (the GA
   maximises *unweighted* R², and extremes are rare). Rows are independent once lags are materialised, so random
   thinning does not break the time structure; the split already did.
3. Fit partitions on the same subsample; check stability across 3 seeds (A4's later task) rather than spending the
   budget on one huge fit.
4. If a full-data fit is ever needed, the cost is a process of ≥ 3.5 GB: that needs A0's agreement on a memory slot,
   or a chunked evaluation upstream (not available in 3.3.1).
5. Peak memory of `train_run` adds the feature table and a few copies of the train/test frames: budget ≈ 1 GB more
   at 1.4 M rows × 15 columns. Run one training job at a time.
