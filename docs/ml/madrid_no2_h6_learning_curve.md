# Madrid NO2 at t+6 h: learning curve and full-data fitting (AT-041g)

**Status: finished (validation only; the test period was never read). The protocol (sections 0 and 0b) was committed
before the fits of its parts and is not edited; results are sections 2 to 4, deviations section 5.**

## Answer in short

* **Does more data help?** Not measurably, at this budget. Going from 30,000 to 120,000 tempered rows changes the mean
  validation macro-F1 by +0.006 (EvoX) and -0.008 (pymoo), against the pre-registered +0.011 and a standard error of
  about 0.013-0.015. Random forest on the same rows gains +0.007 (0.419 to 0.426), logistic regression loses 0.003.
  ExFuzzy stays 0.10-0.12 below the forest on identical rows at every size, so the limit is the model/search, not the rows.
* **Can we stop subsampling, and at what cost?** Yes, technically: all 918,601 rows were fitted (EvoX, scored on the CPU,
  58 min, 3.6 GB; and with the minibatch mode of ex-fuzzy PR 39, 4 to 8 min, 2.7 GB). The macro-F1 is the same (0.313, 0.320
  against 0.317 for the classic 30k fit on the same build). The classic exact fit costs about 0.65 microseconds per row and
  evaluation: 1.5 h at 918k rows, about 28 h at 17 million and 7 days at 100 million; memory is about 1.7 KB per row
  (27 GB at 17 million). The minibatch mode removes the per-generation cost (about 2 s for a 30,000-row batch whatever the
  pool) and leaves the final full scoring (about 0.1 ms per row) and the memory of the pool.
* **Is a minibatch-GA mode worth proposing upstream, in light of the curve?** It is already there (PR 39). The curve says it
  will not raise accuracy on this task; its value is cost and memory control for pools of millions of rows (the
  all-Europe case), where the classic fit does not run. Its best arm here, the 129,604-row tempered pool, is +0.011 over
  the classic control (0.328 against 0.317), which is at the threshold (0.0107, standard error 0.0085) and is not
  claimed as a gain.

Question from the author: "can we stop subsampling the data at some point? Is there no batch mode in ExFuzzy?"
Every ExFuzzy classifier of Atlas is fitted on a 30,000-row, class-tempered subsample of about 918,601 complete
training rows (`madrid_no2_h6_ica.md`, section 3). This document measures (a) whether more rows help at the
AT-041d budget, and (b) what fitting on many more rows costs, on the pinned PyPI ex_fuzzy 3.3.1.

**What this is not.** Same limits as AT-041c/d/e: firing, association degree and rule weight are degrees of rule
match, not probabilities, contributions or risk. No causal, clinical, sanitary or regulatory claim; no real-time
claim. A timing here is a measurement on one machine (the workstation), under load from other jobs, not a benchmark of the
library.

## 0. Protocol and decision rules (written and committed before any real-data fit)

History, for honesty. Before this section was written the author had (1) read the published AT-041d numbers
(validation macro-F1 of the three seeds 0.3481 / 0.3287 / 0.3310, mean 0.336, sd 0.011; Jaccard 0.151; baselines on the
same 30,000 rows: random forest 0.419, logistic regression 0.339) and the code of `atlas.ml`; (2) read the source of
`ex_fuzzy` 3.3.1 (`evolutionary_backends.py` `EvoXBackend`, `_torch_fitness.py`, `FitRuleBase._evaluate_gene_population`);
(3) run the upstream EvoX tests (checkout `origin/main` of 2026-10-31, extracted to a scratch directory, against the
pinned 3.3.1 in the main environment) and three fits on **synthetic uniform data** (2,000 and 30,000 rows, 3 to 5 generations)
to see whether the EvoX path runs. No fit on the Madrid rows and no validation number of any arm below had been
produced.

What the upstream test run showed (so the "device bug" hypothesis is settled before the experiments):

* With CUDA visible, 5 to 6 upstream tests fail; with `CUDA_VISIBLE_DEVICES=` all 176 pass. The failures are in the
  **tests**, not in the library: `tests/test_optional_pymoo.py::test_evox_fits_run_when_pymoo_cannot_be_imported`
  (line 46) builds a stand-in EvoX mutation with `torch.randint(-1, 2, population.shape)` and no `device=`, so it
  makes a CPU tensor and adds it to the CUDA population ("Expected all tensors to be on the same device, cuda:0 and
  cpu"); the others (`test_evox_population.py::test_evox_fit_search_is_identical_on_every_route`,
  `test_evolutionary_backends.py` three tests) assert `result['device'] == 'cpu'`, which only holds on a host
  without CUDA. A real EvoX fit (evox 1.3.0 operators, CUDA) with fixed partitions and `ds_mode=0` runs without error.
  So no ex-fuzzy worktree or fix is needed for this experiment; the pinned PyPI 3.3.1 is used as is.

### Part A. Feasibility and cost of the GPU route (pinned 3.3.1, `backend="evox"`, CUDA)

* **A1. Fit.** The AT-041d shape (`configs/ml/madrid_no2_h6_ica2_justified_experiment.json`: `justified` partitions,
  60 rules x 4 antecedents, 150 generations x 60 individuals, dominance score, seed 0) on the **published 30,000-row
  subsample** (`class_sample`, seed 20260101, power 0.5; the rows of `ica2-justified/subsample_keys.parquet`), twice:
  `backend="evox"` on CUDA and `backend="pymoo"` on the CPU (4 threads). Reported: validation macro-F1, rules kept,
  wall time, and from `optimization_result_` whether the run was `gpu_accelerated`. The two backends are different
  GAs (EvoX: tournament + SBX + polynomial mutation + elitist merge of parents and offspring; pymoo: its own GA), so equal
  rules are not expected. Expected as a harness check: the pymoo refit reproduces the published seed-0 value 0.3481.
* **A2. Exactness of the torch objective.** For a population of 60 chromosomes (the final population of the A1 EvoX fit, plus
  60 uniformly random chromosomes within the gene bounds) the fitness of `TorchObjective.score` on CUDA is compared with
  the CPU scores of `FitRuleBase._scalar_scores`: maximum absolute difference and number of exactly equal values.
  Criterion: maximum difference <= 1e-6 (the library documents bit-for-bit equality, so anything but 0 is reported).
  Also reported: `DeviceRoute.verified` and `rejected` after the A1 fit (does the fit really use the device?).
* **A3. Cost per row.** One generation's evaluation (60 candidates, 60 x 4 shape) on 30,000, 120,000 and 918,601 rows
  (the whole training period, natural prior; "1M" below), median of at least 3 repeats after a warm-up: CUDA
  (`TorchObjective.score`, synchronised), CPU batched route (`_score_fresh_on_cpu`, 4 threads) and, on 30,000 rows only,
  the CPU scalar route. The candidates are the evolved population of A1 (the same for every size). Where the device
  objective declines (the library builds it only if one candidate's scratch fits in 35 % of the free CUDA memory) the
  row says so and the largest row count that fits is computed from the library's own formula. Cost per row and per
  candidate is extrapolated to a full fit (150 x 60 + 60 evaluations) on 918,601, 17 million (Germany) and 100 million
  (Europe) rows, **assuming linear cost in rows and the 60-rule shape**; the linearity is checked against the three
  measured sizes and the extrapolation is labelled as such. Memory is extrapolated from the library's formula
  (CPU: about 2.3 KB per row, `exfuzzy_api_notes.md` section 7, to be re-measured).
* **Rule for the backend of Part B.** `evox` on CUDA is the main backend if A1 ran on the device (`gpu_accelerated`
  true), A2's criterion holds, and the device wall time of the A1 fit is below the CPU one. Otherwise the main
  backend is `pymoo` on the CPU with 4 threads and the sizes of Part B are shrunk as stated in B.

### Part B. Learning curve (validation 2024 only; the test period is never read)

Common to all arms: table, split (train 2019-2023, validation 2024, 24 h embargo), 4 ICA classes after the merge,
`justified` partitions built on the whole training period, 60 rules x 4 antecedents, 150 generations x 60 individuals, no
early stop, `rule_weighting = dominance_score`, seeds 0, 1, 2. The class-aware sampler is **new and nested**
(below); everything else is the `experiment_class` code path.

**Sampler.** `class_sample` draws each class independently with `rng.choice` inside entity x month blocks, so a
60,000-row draw does not contain the 30,000-row one. `nested_class_sample` (new, `atlas.ml.classification`) gives
every row of a class a key `(rank_in_block + u_block) / block_size` (rank from a seeded random permutation inside the
entity x month block, `u_block` a seeded uniform offset), sorts the class by key and takes the first `q_k` rows, where the
class quotas `q_k` are those of `class_sample` (square-root tempering with water-filling). Prefixes of one fixed ordering are nested
by construction, and each prefix holds in every block its proportional share to within one row. Seed 20260101 for all sizes.
Tests (`tests/ml/test_learning_curve.py`): the sizes are exact, the 30k set is inside the 60k set inside the 120k
set, class shares follow `count ** 0.5`, block shares are within one row of proportional.

**Arms (ExFuzzy, 3 seeds each, same backend):**

| arm | rows | prior | purpose |
|---|---|---|---|
| `n30k` | 30,000 | tempered, power 0.5 | the base, refitted on the main backend with the nested sampler |
| `n60k` | 60,000 | same | |
| `n120k` | 120,000 | same | the largest tempered size: with power 0.5 the rarest class (Desfavorable o peor, 7,350 training rows) is 5.67 % of the sample, so without replacement the maximum is 129,600 rows; 120,000 uses 6,806 of its 7,350 rows (93 %), the other classes about 65,600 / 36,100 / 11,400 of 683,216 / 207,285 / 20,750 |
| `n30k_pub` | 30,000 | same | **control**: the published AT-041d rows (non-nested draw) on the main backend. `n30k_pub` against `n30k` is the sampler effect; against the published pymoo values (0.3481 / 0.3287 / 0.3310) it is the backend effect |
| `full_natural` | 918,601 | **natural** (74.4 / 22.6 / 2.3 / 0.8 %) | informational. ex_fuzzy 3.3.1 has no sample weights, so using all rows also changes the class prior and the GA fitness (macro-F1 of the pruned base on the fitting rows) then sees the natural prior; this arm mixes volume and prior and is **not** used in the decision. Run only as budget allows (below) |
| `n120k_natural` | 120,000 | natural (power 1), nested | informational, optional: separates the prior effect from the volume effect of `full_natural` |

Baselines on **the same row sets** (one fit each, seed 0, not part of any decision): random forest (300 trees, leaf 20) and
multinomial logistic regression, plain and class-balanced, as in `class_baselines` (on `full_natural` the forests keep
`max_samples = 100,000`, as for the full-period baselines of AT-041d). Sanity check of the harness: the baselines on `n30k_pub`
must reproduce the published `*_subsample` values (random forest 0.4190, balanced 0.3703, logistic 0.3389 / 0.3127).

**Reported per arm** (mean +- sd with n-1 over the seeds, all complete validation rows, 191,459): macro-F1, balanced
accuracy, accuracy, recall and precision of every class, rules kept, mean pairwise Jaccard of the
`(antecedent set, class)` rule sets over the 3 seeds, fit seconds, peak CPU RSS (`PeakRss`) and, on CUDA, peak
allocated and reserved memory; for the baselines the same metrics.

**Decision rule (fixed here).** Data volume **helps** if the mean validation macro-F1 of `n120k` is at least **0.011** above
that of `n30k` (the seed sd of AT-041d) on the main backend. Otherwise the answer is "no measurable gain from more
rows at this budget". I note in advance that with three seeds per arm and sd about 0.011 the standard error of the
difference of means is about 0.009, so the threshold is only about 1.2 standard errors: a "helps" verdict from this
experiment alone would be weak evidence, and a "no gain" verdict rules out only effects clearly larger than about 0.02.
The report gives the difference with that standard error, the whole curve (30k, 60k, 120k) and the same difference for the
random forest and logistic regression, plus the ExFuzzy-minus-forest gap at each size, as context; none of these
changes the verdict. If the other backend is also run (below) and the two verdicts differ, the answer is "inconclusive".

**Budget and order** (at most about 3 h of compute in total, sequential fits; `nvidia-smi` and `free -g` checked before each
heavy step; GPU under about 6 GB, CPU 4 threads, RSS under 3 GB for a fit). Priority, last items dropped first if the
budget runs out: Part A; `n30k`, `n60k`, `n120k` (3 seeds); baselines of these arms; `n30k_pub` (3 seeds); the
other backend for `n30k` and `n120k` (3 seeds) as a robustness check, only if the main backend is `evox` and its seed-0
`n30k` validation macro-F1 differs from the pymoo seed-0 value of A1 by more than 0.03; `full_natural` seed 0 only, at the
full budget, only if the A3 cost projects to at most 60 minutes for the fit and RSS stays under the limit (otherwise
reported as not run, with the projected cost, which is itself the finding); `n120k_natural`. If the main backend falls back
to the CPU, the `n120k` arm is run only if the A3 cost projects to at most 25 minutes per fit, else the largest size that
does (and its name says so).

## 1. Provenance and reproduction

Commands are in section 4 once the runs exist. Library: PyPI `ex_fuzzy` 3.3.1 from the main environment with `torch` 2.9.1+cu128
and `evox` 1.3.0 (`exfuzzy_version()` prints plain `3.3.1`, no checkout), `ATLAS_DATA_DIR` and `ATLAS_ARTIFACTS_DIR` of
the main checkout. Run ids and experiment ids carry the prefix `lc-`; nothing existing is overwritten and
`artifacts/published` is not touched.

## 0b. Addendum: minibatch arms (written after Parts A and B had run, before any minibatch fit)

History, for honesty. This section was added at the request of A0 (ex-fuzzy PR 39 adds an opt-in minibatch fitness
mode) when Part A and Part B (both backends, the informational arms) were finished and their validation numbers known:
no gain from 30k to 120k rows on either backend (evox +0.006, pymoo -0.008 against a threshold of 0.011), a full-data
EvoX fit of 58 minutes. Nothing about the minibatch arms had been run. The protocol is fixed here and not edited.

**Build.** The local integration build `EXFUZZY_SRC=/path/to/ex-fuzzy`
(commit 13f7548 = ex-fuzzy main 73492ee + PR 39), through `PYTHONPATH`; `exfuzzy_version()` must print
`3.3.1+g13f7548` (checked in the log). `make test` / `make lint` stay on the pinned 3.3.1. Provenance caveat: that main
also contains PR 36 (rows where no rule fires get the training base rates), which changes predictions for unfired rows
relative to 3.3.1, so numbers from this build are not directly comparable with the 3.3.1 numbers of Part B; hence the
control below.

**Mode.** `BaseFuzzyRulesClassifier(batch_size=B)`: pymoo backend, `algorithm="ga"`, `patience=None`. Each generation
draws B rows stratified by class in proportion to the rows passed; parents are re-scored on the new batch; the final
population is scored on all rows passed and the best of that full scoring is returned.

**Arms** (CPU pymoo, 150 generations x 60 individuals, 60 x 4, seeds 0, 1, 2, same features, `justified` partitions, split
and selection metric as Part B; validation 2024 only):

| arm | pool of rows | batch | note |
|---|---|---|---|
| `n30k_ib` | the nested 30,000 tempered rows (as `n30k`) | none (classic fit) | **control on the integration build**: the classic fit of the `n30k` rows, so the minibatch arms are compared with the classic protocol on the same library |
| `mb30k_full_natural` | all 918,601 complete training rows, natural prior | 30,000 | tests the natural distribution; the GA fitness is macro-F1 on batches with the natural prior |
| `mb30k_tempered_max` | the largest class-tempered (power 0.5) pool without replacement: 129,604 rows (class quotas 70,868 / 39,035 / 12,351 / 7,350, i.e. every row of the rarest class), nested sampler, a superset of `n120k` | 30,000 | tests the tempered distribution; beyond about 130k rows "more data" under this protocol only means more majority rows |

**Comparison and rule.** Against the classic protocol `n30k_ib`: the minibatch arm **helps** if its mean validation
macro-F1 over the 3 seeds is at least 0.011 above that of `n30k_ib` (same rule as Part B). The reference of record is
`n30k_ib` (same library). The 3.3.1 value of Part B (`n30k` pymoo) and the published 0.336 are reported for context only.
The same caveats on power apply (standard error of a difference about 0.015 in Part B). Reported: seconds per generation
(from the start of the optimiser to the end of the last generation, divided by 150), seconds of the final full scoring, total
fit seconds, peak RSS of the process (`PeakRss`), validation macro-F1, balanced accuracy and per-class F1, recall and
precision, rules, rule-set Jaccard.

**Budget.** About 35 minutes of CPU; arms run sequentially, `free -g` checked before each (about 5 GB available;
at most two processes at once).

## 2. Part A results: the GPU route on the pinned 3.3.1

Machine: the workstation, RTX 5060 Ti (7.7 GB), 4 threads, other jobs running. `exfuzzy_version()` = `3.3.1` (PyPI, no checkout),
torch 2.9.1+cu128, evox 1.3.0. The published 30,000 rows were redrawn and match `ica2-justified/subsample_keys.parquet`.

**A1.** Seed 0, 60 x 4, 150 x 60, published rows.

| backend | val macro-F1 | rules | fit s | peak RSS MB | GPU MB (reserved) | device used |
|---|---|---|---|---|---|---|
| pymoo (CPU) | 0.3481 (reproduces the published seed 0 bit for bit) | 15 | 131 | 1962 | - | - |
| evox (CUDA) | 0.3184 | 11 | 8.5 | 1895 | 608 | yes (`gpu_accelerated` true) |

EvoX is 15 times faster for a worse model (-0.030, the pre-registered trigger was a difference above 0.03). The speed
does **not** come mainly from the GPU: a diagnostic (`costs`, section 5) shows that the EvoX GA scores only 1,115 distinct
(uncached) candidates in a 150 x 60 fit, against 9,060 offered; in 54 of the 151 generations every offspring was already in
its cache, because its polynomial mutation, rounded to integer genes, usually reproduces the parent. The two backends are
therefore not the same search at the same budget.

**A2.** The torch objective against the CPU scalar scores, 60 evolved plus 60 random chromosomes: maximum absolute
difference 0.0, 120 of 120 exactly equal, none declined (criterion 1e-6 met). The `_torch_fitness` self-check
(`DeviceRoute.verify`) accepted the device in the fits (`gpu_accelerated` true).

**A3.** One generation (60 candidates, 60 x 4, evolved population), median of 3, cold caches. CPU batched route: declined by
the library at every size (`chunk < 2` with 60 rules), so a CPU fit uses the scalar route.

| rows | CUDA s | CPU scalar s | CUDA us/row/cand | CPU scalar us/row/cand |
|---|---|---|---|---|
| 30,000 | 0.250 | 0.511 | 0.139 | 0.284 |
| 120,000 | 1.021 | 0.726 | 0.142 | 0.101 |
| 281,621 | 2.315 | not measured | 0.137 | not measured |
| 918,601 | **declined**: scratch of one candidate exceeds 35 % of the free GPU memory (limit 280,890 rows) | 9.46 | - | 0.172 |

Reading: the device cost is linear in rows (0.14 us); it needs 8 x 16 x rules = 7.7 KB per row and candidate, so with 60 rules
it cannot hold more than about 281k rows on this card (5.9 GB free), and an RTX consumer card has weak float64 throughput: the
GPU is no faster than one CPU thread at 120k rows or more (the CPU figures are noisy because the machine is shared:
0.10-0.28 us). Cold-generation costs are lower bounds for a fit: the in-fit cost of the pymoo fits was
0.39 us per row and evaluation at 30k, 0.63 at 60k and 0.66 at 120k rows (fit seconds / (rows x 9,060)), which is what
the extrapolation below uses.

**Extrapolation of a full classic fit (150 x 60, 9,060 evaluations, 60 x 4)**, linear in rows (checked only up to 120k for the
in-fit cost; 918k was measured only for the EvoX variant, which evaluates 1/8 of the candidates):

| rows | pymoo, 0.65 us/row/eval | CUDA, 0.14 us (all candidates fresh) | memory, CPU at 1.7 KB/row | GPU scratch per candidate |
|---|---|---|---|---|
| 918,601 | 1.5 h | does not fit (limit 281k) | 1.6 GB | 7 GB |
| 17 million (Germany) | 28 h | 6 h if it fitted | 29 GB | 131 GB |
| 100 million (Europe) | 164 h (6.8 days) | 35 h if it fitted | 170 GB | 770 GB |

A measured data point: EvoX with CPU scoring on all 918,601 rows took 3,507 s (58 min) and 3.55 GB of RSS (above the 3 GB limit of
the protocol) for 17 rules and a validation macro-F1 of 0.313.

## 3. Part B results: the learning curve (validation 2024, 191,459 rows, 3 seeds)

Rows of the arms: n30k [16,404 / 9,036 / 2,859 / 1,701], n60k [32,808 / 18,071 / 5,718 / 3,403], n120k
[65,617 / 36,142 / 11,435 / 6,806] (93 % of the rarest class), samples nested (tests check it). Mean +- sd (n-1). Recall
and precision are class means in the order Buena / Razonablemente buena / Regular / Desfavorable o peor.

**EvoX on CUDA (main backend by the rule of Part A)**

| arm | val macro-F1 | bal-acc | rules | Jaccard | fit s | RSS MB | GPU MB |
|---|---|---|---|---|---|---|---|
| n30k | 0.295 +- 0.016 | 0.349 | 17.3 | 0.010 | 6 | 2008 | 608 |
| n60k | 0.304 +- 0.010 | 0.357 | 18.0 | 0.022 | 11 | 2194 | 610 |
| n120k | 0.302 +- 0.015 | 0.355 | 22.7 | 0.000 | 20 | 2444 | 728 |
| n30k_pub (published rows) | 0.310 +- 0.018 | 0.341 | 13.0 | 0.012 | 6 | 2512 | 728 |

Decision: mean(n120k) - mean(n30k) = **+0.0062** (standard error 0.0126, threshold 0.011) -> **no measurable gain**.

**pymoo on the CPU (the AT-041d search; run on all three arms although the trigger of 0.03 was not exceeded, 0.0297, because the
EvoX search turned out to be much smaller, see A1)**

| arm | val macro-F1 | bal-acc | rules | Jaccard | fit s | RSS MB |
|---|---|---|---|---|---|---|
| n30k | 0.317 +- 0.016 (0.299, 0.330, 0.321) | 0.428 | 12.0 | 0.126 | 105 | 1327 |
| n60k | 0.326 +- 0.014 (0.341, 0.323, 0.313) | 0.392 | 17.0 | 0.021 | 343 | 1329 |
| n120k | 0.309 +- 0.020 (0.325, 0.286, 0.315) | 0.383 | 11.7 | 0.060 | 713 | 1468 |
| published AT-041d (n30k_pub, 3.3.1) | 0.336 +- 0.011 | | 13.7 | 0.151 | | |

Decision: mean(n120k) - mean(n30k) = **-0.0079** (standard error 0.0148) -> **no measurable gain**. Both backends agree, so
the verdict is "no measurable gain from more rows at this budget"; it is not "inconclusive".

Context. (i) The row draw matters as much as the data volume: the nested 30k rows give 0.317 on pymoo, the published rows 0.336
(and 0.295 against 0.310 on EvoX), a difference of 0.015-0.019, above the 0.011 threshold; it is one realisation of the
sampler. (ii) Baselines on the same rows (seed 0, one fit):

| rows | random forest | RF balanced | logistic | LR balanced |
|---|---|---|---|---|
| n30k | 0.4187 | 0.3675 | 0.3447 | 0.3135 |
| n60k | 0.4219 | 0.3724 | 0.3431 | 0.3133 |
| n120k | 0.4262 | 0.3753 | 0.3417 | 0.3127 |
| n30k_pub | 0.4190 | 0.3703 | 0.3389 | 0.3127 |
| full_natural (918,601) | 0.3473 | 0.3961 | 0.2792 | 0.3128 |
| n120k_natural | 0.3464 | 0.3903 | 0.2834 | 0.3136 |

The harness check passed: the `n30k_pub` baselines and the `full_natural` full-period ones reproduce the published AT-041d values
(RF 0.4190 / 0.3703, LR 0.3389 / 0.3127, full-period RF 0.3473 / 0.3961, LR 0.2792 / 0.3128). Random forest gains +0.0075 from
30k to 120k tempered rows (the same order as ExFuzzy's EvoX +0.006, noise-sized), and ExFuzzy is 0.10-0.12 below it at every
size (pymoo: 0.317 against 0.419, 0.326 against 0.422, 0.309 against 0.426).

**Informational arms (natural prior, not in the decision).** `full_natural` (918,601 rows, EvoX, CPU scoring, seed 0): 0.313,
recall 0.85 / 0.28 / 0.21 / 0.01, 3,507 s. `n120k_natural` (120,000 natural-prior rows, EvoX, 3 seeds): 0.304 +- 0.009,
recall 0.87 / 0.28 / 0.06 / 0.04, balanced accuracy 0.312. With the natural prior the rare classes collapse (the Desfavorable
recall is 0.01-0.04 against 0.10-0.26 with tempering) while accuracy rises (0.75-0.77): all rows change the prior as much as
the volume, as foreseen. `full_natural` pymoo was not run: the in-fit extrapolation is 1.5 h.

## 4. Part C results: minibatch fitness (ex-fuzzy PR 39) on the CPU

Build: `3.3.1+g13f7548` (ex-fuzzy main 73492ee + PR 39, local integration build, through `PYTHONPATH`; it also has PR 36, rows where
no rule fires get the training base rates, so these numbers are not comparable with the 3.3.1 ones of section 3, hence the
control `n30k_ib`). pymoo, 150 x 60, 60 x 4, 3 seeds, batch 30,000, two processes at once with 2 threads each (so times are
slightly pessimistic). Validation macro-F1 per seed in brackets.

| arm | pool | val macro-F1 | bal-acc | F1 Buena / R.buena / Regular / Desf. | rules | Jaccard | fit s | s/generation | final scoring s | peak RSS MB |
|---|---|---|---|---|---|---|---|---|---|---|
| `n30k_ib` classic (control) | 30,000 | 0.317 +- 0.015 (0.317, 0.303, 0.333) | 0.422 | 0.81 / 0.35 / 0.10 / 0.01 | 18.0 | 0.041 | 117 | about 0.8 (fit s / 150, not instrumented) | included | 1335 |
| `mb30k_tempered_max` | 129,604 tempered | 0.328 +- 0.001 (0.327, 0.329, 0.328) | 0.394 | 0.85 / 0.32 / 0.12 / 0.02 | 17.0 | 0.031 | 271 | 1.71 | 12.7 | 1238 |
| `mb30k_full_natural` | 918,601 natural | 0.320 +- 0.005 (0.318, 0.316, 0.326) | 0.322 | 0.87 / 0.29 / 0.11 / 0.02 | 25.3 | 0.008 | 404 | 2.01 | 90.1 | 2734 |

Decision (rule: at least +0.011 over `n30k_ib`): `mb30k_tempered_max` **+0.0107** (standard error 0.0085): just below the threshold,
**no measurable gain** by the rule, with the caveat that it is within 0.0003 of it and the sd of the three seeds (0.001) is much
smaller than that of the classic fit (0.015), so the minibatch fit is more stable across seeds, not clearly better;
`mb30k_full_natural` **+0.0026** (standard error 0.0091): no gain, and its recall of the rare classes is the natural-prior one
(Desfavorable recall 0.02). Against the 3.3.1 classic `n30k` (0.317) and the published 0.336 neither arm is above the published value.

Cost. A generation costs about 1.7-2.0 s with a 30,000-row batch, independent of the pool (it scores the parents on the new batch
and the offspring: two populations; the classic fit is about 0.8 s per generation on the same 30k rows); the final scoring of the
60 candidates on the whole pool costs 12.7 s for 129,604 rows and 90 s (63-126 s) for 918,601 rows, i.e. about 0.1 ms per row;
peak RSS 2.7 GB for the 918k-row pool (about 1.7 KB per row above the 1.1 GB of the process). Extrapolation, linear: a fit with a
17-million-row pool would take about 150 x 2 s + 17e6 x 0.1 ms = 5 + 28 min, with about 30 GB of memory; 100 million rows: about
5 min + 2.7 h, 170 GB. At those sizes the memory of the pool, not the compute, is the limit, and the library does not stream the
pool.

## 5. Deviations from the protocol, and what was added

* Added after A1-A3 (labelled): `costs` (CPU scalar route at 120k and 918k, the device at 281k rows, and the fresh-candidate
  count of an EvoX fit), because the first numbers showed that the EvoX speed was not the GPU; and the pymoo run of all three
  arms, run although the rule's trigger (a seed-0 difference above 0.03) was 0.0297.
* `full_natural` was started under the pre-registered 60-minute condition on a projection that was wrong (A4's 3 minutes
  assumed the EvoX candidate count of the 30k fit; the real fit took 58 minutes and 3.55 GB, above the 3 GB limit of the
  protocol). The total compute was about 2.5 h for sections 2 and 3 plus about 25 min for section 4, a little above the about
  3 h budget of the brief when the coordinator's addendum is counted.
* `n120k_natural` was run only on EvoX (3 seeds), `full_natural` only on EvoX (seed 0).
* The decision rule has little power (standard error of a difference 0.009-0.015 against a threshold of 0.011). "No measurable
  gain" means no gain larger than about 0.02-0.03; it does not prove that there is none.

## 6. Reproduction

```
export ATLAS_DATA_DIR=/path/to/exfuzzy-atlas/data ATLAS_ARTIFACTS_DIR=/path/to/exfuzzy-atlas/artifacts
make fit-lc LC_ARGS="feasibility"                                   # A1-A3
make fit-lc LC_ARGS="costs"                                         # section 5 additions
make fit-lc LC_ARGS="fit --arms n30k n60k n120k n30k_pub"           # EvoX arms (+ baselines)
make fit-lc LC_ARGS="fit --backend pymoo --arms n30k n60k n120k"    # pymoo arms
make fit-lc LC_ARGS="fit --arms full_natural n120k_natural"         # informational arms (about 1 h)
make fit-lc EXFUZZY_SRC=/path/to/ex-fuzzy \
  LC_ARGS="fit --backend pymoo --arms n30k_ib mb30k_tempered_max mb30k_full_natural"   # section 4
make fit-lc LC_ARGS="report"
```

Results are JSON files under `artifacts/madrid_no2_h6/experiments/lc-madrid-h6/` (`feasibility.json`, `costs.json`,
`fits/<backend>[@<build>]/<arm>_seed<k>.json`, `baselines/<arm>.json`, `rows_<arm>.parquet`). Tests:
`tests/ml/test_learning_curve.py` (sampler sizes and nesting, block stratification, timing helpers, config).
