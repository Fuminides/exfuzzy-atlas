# Madrid NO2 at t+6 h as an ICA category, v4: diurnal inputs for the winning-rule classifier (AT-041h)

Follow-up of `madrid_no2_h6_ica_v2.md` (AT-041d, the served model `exfuzzy-madrid_no2_h6-ica2-justified-seed0`) and
`madrid_no2_h6_ica_v3.md` (AT-041e, six ideas, none beat AT-041d). Same task, table, split (train 2019-2023 / validation
2024 / test 2025, 24 h embargo), class merge, justified partitions, fitting protocol (class-aware 30,000-row subsample,
power 0.5, 60 rules x 4 antecedents, 150 generations x 60 individuals, seeds 0-2) on the pinned PyPI ex_fuzzy 3.3.1
winning-rule classifier. What changes is **the inputs**: quantities, in ug/m3, that tell the rules what the station
usually reads at the hour being forecast, and what it read at that hour yesterday or last week. No TSK, no
regression-then-bin with ExFuzzy, no change to the library, no black-box output as an input.

**What this is not.** Firing, association and rule weight are degrees of rule match, not probabilities, contributions or
risk. A climatology is a description of the training years, not a cause. No causal, clinical, sanitary or regulatory
claim.

## 0. Pre-registration (written and committed before any validation number of a new arm was produced)

### 0.1 What was known when this section was written

* The published AT-041d / AT-041e numbers (validation 0.336 ± 0.011, test 0.324 ± 0.009 over seeds, served seed
  0.329; persistence 0.294; HGB regression-then-binned 0.414; RF 0.374; HGB validation 0.376 with the nine inputs and
  0.379 with the AT-041e trend / anomaly / type inputs).
* **Training-only diagnostics** (rows of 2019-2023 only; no validation or test row was scored): the ICA band of each
  candidate quantity used directly as the prediction, in-sample macro-F1 on the complete training rows. They shaped the
  list of arms and the ratio offset, and are reported here for that reason:

  | quantity (its ICA band = the prediction) | train macro-F1 |
  |---|---|
  | `no2_last` (persistence) | 0.322 |
  | station x hour x day-type median at the valid hour (`no2_clim_valid`) | 0.290 |
  | `no2_expected_valid` (additive, hour x day-type climatology) | 0.376 |
  | same, hour-only climatology | 0.366 |
  | `no2_expected_valid_damped` (rho = 0.48) | 0.341 |
  | ratio variant, offset 0 / 5 / 10 / 20 ug/m3 | 0.364 / 0.373 / 0.373 / 0.364 |
  | NO2 yesterday at the valid hour (`no2_yday_valid`) | 0.504 |
  | yesterday at the valid hour + today's change since yesterday | 0.457 |
  | mean of `no2_expected_valid` and `no2_yday_valid` | 0.448 |
  | max of the last 3 h | 0.321 |
  | mean / max of the last 24 h | 0.372 / 0.257 |

  Correlation with the target on the training-period table: 0.63 for NO2 yesterday at the valid hour against 0.35 for
  `no2_last`. Alignment of the table was checked (target of row t = `no2_last` of row t+7 h in 100 % of the rows).
  These are in-sample, single-quantity numbers with no model; they say which quantities are worth giving the GA, not
  what the classifier will score.
* Missing values (share of AT-041d complete rows without the quantity, all periods): `no2_yday_valid` 0.8 %,
  `no2_week_valid` 1.5 %, 24-h window statistics 0.14 %; the climatology-based inputs are never missing.
* A timing check of the experiment code was not run on real rows before this section was committed.

### 0.2 Inputs (definitions in `src/atlas/ml/diurnal_features.py`, terms in `configs/ml/madrid_partitions_diurnal.json`)

All in ug/m3, all read only finished hours (keys <= t - 1 h), all partitioned with the **ICA bands and shoulders of
`no2_last`** (Buena / Razonablemente buena / Regular / Desfavorable o peor; 6 / 13.5 / 18 ug/m3), so that a rule reads
"IF no2_expected_valid IS Regular ...". Fitted quantities come from the training split only.

| input | definition | one-line domain reason |
|---|---|---|
| `no2_clim_valid` | training median NO2 of the station at the local hour and day type (Laborable / Sábado / Domingo) of the target hour | what this station usually reads at that hour on that kind of day (H2) |
| `no2_expected_valid` | `no2_clim_valid + (no2_last - usual value at the hour of no2_last)`, clipped to [0, 1000] | today's departure from normal carried forward to the target hour (H1) |
| `no2_expected_valid_ratio` | `no2_clim_valid x (no2_last + 6) / (usual value at the hour of no2_last + 6)`, clipped | the same with the departure as a ratio (emissions and mixing scale the level); 6 ug/m3 = the measurement-uncertainty scale of the NO2 terms |
| `no2_expected_valid_damped` | `no2_clim_valid + rho x departure`, rho = least-squares slope on the complete training rows | linear persistence-plus-diurnal expectation: only a share rho of today's departure survives 7 h |
| `no2_yday_valid` | NO2 at key t+6 h-24 h = the hour [t-18 h, t-17 h) | what happened yesterday at the hour being forecast: diurnal cycle and multi-day episode persistence, nothing fitted |
| `no2_week_valid` | NO2 at key t+6 h-168 h | same hour and weekday last week: the weekly pattern of traffic |
| `no2_mean_24h` | mean of the 24 finished hours, >= 18 valid (75 % data capture, 2008/50/EC Annex VII) | level of the last day, a marker of accumulation episodes |
| `no2_max_24h` | max of the same 24 hours, >= 18 valid | worst hour of the last day (did yesterday's rush peak reach Regular?) |

Not tried, and why: max / mean of the last 3 h (training diagnostic at persistence level, 0.321; the 3-h trend was
already AT-041e); a multi-coefficient linear forecast (a fitted forecast shrinks towards the mean and rarely reaches the
fixed upper bands: the one-coefficient damped version already loses 0.035 against the undamped one in the training
diagnostic; it would also read as a model inside the input); specialised rule bases per daypart or station type (only
if nothing here wins: they multiply the rule count).

### 0.3 Rows

Every arm, `base_refit` and the re-scored published base use **the same rows**: the AT-041d complete rows on which all
eight candidate inputs are finite (about 2 % fewer than AT-041d; counts are printed by the experiment and reported in
section 1). Every fit uses the same class-aware 30,000-row draw (seed 20260101, power 0.5) of those training rows, the
same quantile terms for temperature and humidity (computed on those training rows), and seeds 0, 1, 2. The published
model's own-row validation and test numbers are reported next to the common-row ones.

### 0.4 Arms

Stage 1 (27 fits): `base_refit` (the nine AT-041d inputs, refitted on the common rows, on the same machine as the arms)
and one arm per input above, **the nine AT-041d inputs plus that one input** (appended last; the first four inputs are
the four-term NO2 inputs, so the ex_fuzzy 3.3.1 slot bound of v2 observation 10 does not bite; the code refuses an input
order where it would).

Reference = the larger of the means of `base_refit` and of the published base re-scored on the common rows.

Stage 2, defined by stage 1 through this rule (no other choice is made by hand):

* an input **enters** if its arm's mean validation macro-F1 is at least **0.011** above the reference (one seed sd of
  AT-041d);
* `combo` = AT-041d inputs + the best entered input of the expectation family (`no2_clim_valid`, `no2_expected_valid*`,
  at most one of them, they say the same thing) + at most the two best other entered inputs; built only if at least two
  inputs entered;
* `compact` = the entered inputs of `combo` (or the single entered input) **replacing** `no2_lag1h`, `no2_lag3h`,
  `no2_lag24h`: inputs `no2_last`, the entered inputs, wind, hour, temperature, humidity, weekday (four-term inputs
  first). Built if at least one input entered. It tests whether a smaller rule space helps.

Shape (up to 15 fits): the best arm by mean among the entered single arms, `combo` and `compact` is refitted with
nRules x nAnts in {30, 60} x {2, 3, 4} (3 seeds each; its 60 x 4 fits are reused).

Robustness (information only, never selects): seeds 3 and 4 of the chosen arm and of `base_refit`.

### 0.5 Decision rule (validation 2024 only)

* Eligible: every stage-1 single arm, `combo`, `compact` and the shape arms, with a mean rule count <= 22 (rules stay
  ≲ 20 with at most 4 antecedents).
* An eligible arm **wins** if its mean validation macro-F1 is at least **0.02** above the reference (about two standard
  errors of a difference of two 3-seed means with sd 0.011, and twice the entry margin to absorb the selection among
  ~20 arms) **and** its worst seed is above the reference mean.
* Among winners take the highest mean; arms within 0.005 of it are tied and the tie goes to the arm with fewer inputs,
  then fewer rules. If nothing wins, the AT-041d model stays and nothing is proposed.
* The proposed seed of the chosen arm is its seed with the highest validation macro-F1.
* `python -m atlas.ml.experiment_ica4 decide` applies this rule mechanically and writes `decision.json`.

### 0.6 Test 2025 (once)

`final --test` reads the test rows once (a marker file refuses a second read), for the chosen arm (3 seeds), the
published base (3 seeds, common rows), `base_refit`, persistence, climatology, and, as a control and not for selection,
HGB, HGB regression-then-binned and RF on the full training period and HGB, RF and LR on the 30,000-row subsample,
**with the AT-041d inputs and with the chosen arm's inputs**, all on the common rows. The AT-041d baseline numbers
(own rows) are quoted from its `summary.json` for reference.

### 0.7 Other tasks

Only if an arm wins on Madrid +6 h: the same winning input(s), same protocol and same kind of decision (gain >= 0.02 over
that task's base refitted on common rows, worst seed above it), on Madrid +1 / +3 / +12 / +24 h and Germany +6 h
(per-station training climatology). For +24 h "yesterday at the valid hour" is the key t, which is not finished at t,
so that input does not exist there; the climatology-based inputs do. NYC is left out unless it clearly makes sense
(its target is already relative to an hour-of-week reference).

### 0.8 Addendum: round 2 (post-hoc; written after the round-1 validation results, before any test row was read)

Round 1 ran as registered (sections 1-3). The rule chose `compact_r30a2` (validation 0.431 ± 0.031 against the
reference 0.336). Its rules lean almost entirely on `no2_yday_valid`, so the obvious seasonal-naive forecast "the ICA
class of NO2 at the same hour yesterday" was then scored on validation: **0.476**, above every round-1 arm. It was not in
section 0, so it is added to the reported baselines (validation and test) as `persistence_24h`; it did not take part in
the round-1 decision, which is kept as it was.

Round 2 asks one question: can the winning-rule classifier at least match that forecast if the rule space is smaller or
the fitting sample keeps the natural class mix? (The class-tempered sample, power 0.5, makes rare-class rules cheap to
the GA; in round 1 such rules on temperature or humidity alone appear in every seed.) Arms, 3 seeds each, same rows,
budget and partitions:

| arm | inputs | shape | sampling power |
|---|---|---|---|
| `r2_power075` | as `compact` | 30 x 2 | 0.75 |
| `r2_power100` | as `compact` | 30 x 2 | 1.0 (natural class proportions) |
| `r2_minimal` | `no2_yday_valid`, `no2_last`, `valid_hour_local`, `wind_speed` | 30 x 2 | 0.5 |
| `r2_minimal_power100` | as `r2_minimal` | 30 x 2 | 1.0 |

Rule: a round-2 arm replaces `compact_r30a2` only if its mean validation macro-F1 is at least 0.02 above that of
`compact_r30a2` and its worst seed is above it (mean rules <= 22); the best such arm is taken. Because round 2 was
designed after seeing round-1 validation numbers on the same year, its validation figures are optimistic and are
labelled post-hoc; the test year decides nothing but is the only unbiased number. `final --test` then reads the test rows
once for the round-1 choice, the round-2 choice (if any), the base, `persistence_24h` and the controls.

### 0.9 Addendum: round 3 (post-hoc; written after round 2 and one diagnostic, before any test row was read)

Round 2 changed nothing (every arm 0.416-0.431, none above `compact_r30a2` by the margin). Diagnostic, validation only:
the 4-rule rule base "IF no2_yday_valid IS c THEN ICA = c" built inside ex_fuzzy 3.3.1 scores **0.447** with dominance
weights computed on the fitting sample (it is exactly what the GA found for `r2_minimal` seed 2; the GA fits with a higher
fitting-sample score do worse on validation), against **0.476** for the crisp class of `no2_yday_valid`. The same four
rules with **unweighted** inference (ex_fuzzy `ds_mode = 1`: association = firing) give **0.4760**. So the loss sits in the
class-prior-laden dominance weights at the band shoulders (a value of 92 ug/m3 fires Regular at 1.0 and Razonablemente
buena at 0.85, and the 6x larger weight of the latter wins), not in the search. Unweighted inference is also the more
readable one (no hidden weight decides between two rules; see v3 section 8).

Round 3 arms (3 seeds, same rows, sample power 0.5, budget and partitions; `rule_weighting = "none"`):

| arm | inputs | shape |
|---|---|---|
| `r3_base_unweighted` | the nine AT-041d inputs (control: weighting alone) | 60 x 4 |
| `r3_yday_unweighted` | AT-041d inputs + `no2_yday_valid` | 60 x 4 |
| `r3_compact_unweighted` | as `compact` | 30 x 2 |
| `r3_compact_r60a4_unweighted` | as `compact` | 60 x 4 |
| `r3_minimal_unweighted` | as `r2_minimal` | 30 x 2 |

Same rule as round 2: an arm replaces `compact_r30a2` only if its mean is at least 0.02 above it and its worst seed above
it; the best such arm (by mean, round 2 and 3 pooled) is taken. Post-hoc, optimistic on validation; the test is read once
after this round.

## 1. What was run, and every deviation from section 0

Machine: the large machine (aarch64, 20 CPUs), a fresh venv with the PyPI wheels of ex_fuzzy **3.3.1** and the same numpy 2.3.5 /
pandas 2.3.3 / scikit-learn 1.9.0 / pymoo 0.6.2 as the main environment on the workstation. Platform check before anything else: refitting
AT-041d seed 0 there with its own rows and sample gives **identical predictions** to the published pickle (validation
0.3481). Fits ran in parallel worker processes (one GA per process, one thread each).

Rows (identical for every arm): train 898,468, validation 187,014, test 174,671 (AT-041d: 918,601 / 191,459 / 180,326;
2.3 % of the validation rows lack one of the eight candidate inputs). The published base re-scored on these rows gives
0.348 / 0.328 / 0.331 (own rows 0.348 / 0.329 / 0.331). Fitted quantities: a climatology of 1,728 cells (24 stations x 24
local hours x 3 day types) from the 1,051,200 training-period rows (cell medians 3-58 ug/m3); rho = 0.482 on the 918,601
complete training rows; the additive projection is negative, and clipped to 0, on 7.0 % of the rows.

Deviations, in the order they happened:

1. **`persistence_24h` added after round 1** (section 0.8): the ICA class of `no2_yday_valid` used as the forecast. It was
   not in section 0; it took no part in any decision of round 1.
2. **Rounds 2 and 3 are post-hoc** (sections 0.8 and 0.9), designed after round-1 validation numbers on the same year.
   Their addenda were committed before their fits, and before any test row was read.
3. **Two diagnostics on validation only**, not arms: the 4-rule identity rule base (section 0.9) and the share of rows
   whose winner ties with a rule of another class (section 3).
4. The control baselines "with the chosen inputs" were fitted with the inputs of the **round-1** choice (`compact`, 7
   inputs), a superset of the 4 inputs of the final choice; the code took `decision.chosen` (round 1) for them.
5. Other tasks (section 6): the arms run there are the round-1 and the final Madrid +6 h structures, fixed in
   `configs/ml/*_ica4_experiment.json` before those fits. Those configs were committed after the runs, not before.

## 2. Validation 2024 (mean ± sd over seeds 0-2; rules = rules kept; Jaccard = mean pairwise Jaccard of the rule sets)

| arm | macro-F1 | bal-acc | acc | Regular recall | Regular prec | Desf. recall | Desf. prec | rules | mean length | Jaccard |
|---|---|---|---|---|---|---|---|---|---|---|
| base_published (AT-041d pickles) | 0.336 ± 0.011 | 0.399 ± 0.044 | 0.731 ± 0.018 | 0.331 ± 0.178 | 0.088 ± 0.027 | 0.069 ± 0.049 | 0.014 ± 0.003 | 13.7 | 1.69 | 0.151 |
| base_refit | 0.326 ± 0.005 | 0.412 ± 0.047 | 0.713 ± 0.047 | 0.353 ± 0.138 | 0.081 ± 0.031 | 0.148 ± 0.084 | 0.010 ± 0.006 | 17.7 | 1.90 | 0.062 |
| *stage 1: AT-041d inputs + one input* | | | | | | | | | | |
| + no2_clim_valid | 0.322 ± 0.005 | 0.396 ± 0.043 | 0.727 ± 0.033 | 0.281 ± 0.228 | 0.066 ± 0.024 | 0.144 ± 0.063 | 0.008 ± 0.002 | 15.0 | 1.94 | 0.037 |
| + no2_expected_valid | 0.344 ± 0.007 | 0.410 ± 0.039 | 0.752 ± 0.058 | 0.309 ± 0.108 | 0.095 ± 0.019 | 0.130 ± 0.063 | 0.017 ± 0.013 | 13.3 | 1.85 | 0.053 |
| + no2_expected_valid_ratio | 0.329 ± 0.020 | 0.419 ± 0.033 | 0.729 ± 0.039 | 0.287 ± 0.142 | 0.062 ± 0.019 | 0.213 ± 0.079 | 0.015 ± 0.004 | 15.0 | 1.90 | 0.035 |
| + no2_expected_valid_damped | 0.324 ± 0.003 | 0.415 ± 0.068 | 0.725 ± 0.047 | 0.387 ± 0.225 | 0.060 ± 0.021 | 0.132 ± 0.094 | 0.016 ± 0.011 | 14.7 | 1.90 | 0.022 |
| + no2_yday_valid | **0.377 ± 0.010** | 0.490 ± 0.029 | 0.797 ± 0.008 | 0.476 ± 0.181 | 0.093 ± 0.013 | 0.273 ± 0.112 | 0.069 ± 0.051 | 18.0 | 2.14 | 0.027 |
| + no2_week_valid | 0.326 ± 0.007 | 0.408 ± 0.039 | 0.707 ± 0.031 | 0.355 ± 0.087 | 0.067 ± 0.017 | 0.104 ± 0.098 | 0.010 ± 0.004 | 18.3 | 1.94 | 0.019 |
| + no2_mean_24h | 0.341 ± 0.015 | 0.409 ± 0.036 | 0.742 ± 0.031 | 0.342 ± 0.191 | 0.080 ± 0.039 | 0.134 ± 0.024 | 0.038 ± 0.012 | 17.3 | 1.99 | 0.042 |
| + no2_max_24h | 0.339 ± 0.007 | 0.419 ± 0.033 | 0.740 ± 0.030 | 0.301 ± 0.057 | 0.089 ± 0.027 | 0.208 ± 0.126 | 0.031 ± 0.007 | 16.0 | 1.83 | 0.023 |
| *stage 2 (only no2_yday_valid entered: no combo)* | | | | | | | | | | |
| compact (lags replaced by no2_yday_valid), 60 x 4 | 0.432 ± 0.030 | 0.473 ± 0.060 | 0.810 ± 0.032 | 0.303 ± 0.212 | 0.246 ± 0.114 | 0.275 ± 0.092 | 0.159 ± 0.076 | 11.0 | 1.59 | 0.022 |
| *shape of compact* | | | | | | | | | | |
| 30 x 2 (**round-1 choice**) | 0.431 ± 0.031 | 0.466 ± 0.017 | 0.824 ± 0.006 | 0.361 ± 0.089 | 0.172 ± 0.064 | 0.234 ± 0.020 | 0.179 ± 0.080 | 9.3 | 1.23 | 0.148 |
| 30 x 3 | 0.418 ± 0.025 | 0.497 ± 0.030 | 0.820 ± 0.009 | 0.463 ± 0.111 | 0.136 ± 0.027 | 0.299 ± 0.067 | 0.153 ± 0.067 | 8.7 | 1.19 | 0.302 |
| 30 x 4 | 0.400 ± 0.019 | 0.485 ± 0.045 | 0.818 ± 0.011 | 0.357 ± 0.251 | 0.178 ± 0.105 | 0.345 ± 0.058 | 0.104 ± 0.022 | 9.3 | 1.52 | 0.078 |
| 60 x 2 | 0.392 ± 0.025 | 0.513 ± 0.036 | 0.743 ± 0.090 | 0.534 ± 0.059 | 0.118 ± 0.024 | 0.306 ± 0.153 | 0.170 ± 0.123 | 12.0 | 1.32 | 0.179 |
| 60 x 3 | 0.409 ± 0.003 | 0.532 ± 0.012 | 0.784 ± 0.031 | 0.579 ± 0.060 | 0.130 ± 0.012 | 0.331 ± 0.008 | 0.123 ± 0.014 | 16.0 | 1.59 | 0.176 |
| *round 2 (post-hoc)* | | | | | | | | | | |
| r2_power075 (compact 30 x 2, power 0.75) | 0.416 ± 0.014 | 0.483 ± 0.063 | 0.822 ± 0.008 | 0.381 ± 0.255 | 0.213 ± 0.118 | 0.299 ± 0.090 | 0.128 ± 0.035 | 9.0 | 1.37 | 0.081 |
| r2_power100 (compact 30 x 2, power 1) | 0.423 ± 0.011 | 0.414 ± 0.026 | 0.831 ± 0.002 | 0.136 ± 0.014 | 0.278 ± 0.137 | 0.197 ± 0.112 | 0.195 ± 0.069 | 6.7 | 1.14 | 0.378 |
| r2_minimal (4 inputs, 30 x 2) | 0.429 ± 0.021 | 0.456 ± 0.040 | 0.804 ± 0.030 | 0.292 ± 0.263 | 0.278 ± 0.136 | 0.234 ± 0.020 | 0.215 ± 0.013 | 5.7 | 1.11 | 0.261 |
| r2_minimal_power100 | 0.431 ± 0.005 | 0.406 ± 0.017 | 0.835 ± 0.004 | 0.118 ± 0.008 | 0.377 ± 0.011 | 0.174 ± 0.072 | 0.227 ± 0.029 | 6.3 | 1.19 | 0.307 |
| *round 3 (post-hoc): unweighted inference* | | | | | | | | | | |
| r3_base_unweighted (AT-041d inputs, 60 x 4) | 0.314 ± 0.012 | 0.375 ± 0.038 | 0.719 ± 0.026 | 0.266 ± 0.129 | 0.059 ± 0.013 | 0.104 ± 0.025 | 0.012 ± 0.006 | 20.7 | 1.96 | 0.025 |
| r3_yday_unweighted (+ no2_yday_valid, 60 x 4) | 0.377 ± 0.019 | 0.487 ± 0.041 | 0.779 ± 0.039 | 0.474 ± 0.180 | 0.093 ± 0.025 | 0.255 ± 0.142 | 0.071 ± 0.026 | 16.7 | 1.93 | 0.079 |
| r3_compact_unweighted (30 x 2) | 0.447 ± 0.051 | 0.486 ± 0.022 | 0.815 ± 0.016 | 0.400 ± 0.157 | 0.244 ± 0.111 | 0.227 ± 0.032 | 0.177 ± 0.092 | 9.7 | 1.29 | 0.079 |
| r3_compact_r60a4_unweighted | 0.424 ± 0.021 | 0.485 ± 0.032 | 0.801 ± 0.021 | 0.363 ± 0.057 | 0.149 ± 0.021 | 0.252 ± 0.080 | 0.109 ± 0.061 | 23.7 | 2.31 | 0.021 |
| **r3_minimal_unweighted (final choice)** | **0.465 ± 0.026** | 0.461 ± 0.022 | 0.823 ± 0.002 | 0.267 ± 0.070 | 0.296 ± 0.025 | 0.199 ± 0.022 | 0.215 ± 0.084 | 7.3 | 1.07 | 0.235 |
| *reference forecasts (no model)* | | | | | | | | | | |
| persistence (class of no2_last) | 0.294 | | | | | | | | | |
| persistence_24h (class of no2_yday_valid) | **0.476** | | | | | | | | | |

Seeds 3 and 4 (information only): `base_refit` 5 seeds 0.319 ± 0.017; `compact_r30a2` 0.431 ± 0.025;
`r3_minimal_unweighted` 0.458 ± 0.032 (seeds 0.479, 0.481, 0.434, 0.482, 0.412).

What the table says:

* **H1 and H2 are not supported.** The usual value at the valid hour (`no2_clim_valid`, -0.014) and today's departure
  carried forward (`no2_expected_valid`, +0.008, below the entry margin) do not help the GA. The ratio and damped variants
  are worse, and so are last week at the valid hour and the 24-h mean and maximum. In the training-only diagnostic,
  `no2_expected_valid` was a better direct predictor than persistence (0.376 against 0.322). On validation it is not
  (0.331 against 0.294, both as direct band forecasts), and the GA does not turn it into rules that beat AT-041d.
* **What helps is the station's own value 24 h before the target hour**, a quantity HGB/RF never had either. Added to the
  nine inputs it gives +0.041 (it enters). Replacing the three raw lags with it (`compact`) gives another +0.055, and this
  is the largest single effect in the report. A smaller rule space makes the GA find the yesterday rules.
* **Shape** does not matter beyond noise (0.39-0.43); 30 x 2 ties 60 x 4 and has fewer rules, so the tie rule takes it.
* **Round 2 changes nothing.** The diagnostic of section 0.9 explains why: the GA does find the identity rule base, but
  dominance weights computed on the class-tempered sample cost it 0.03 at the band shoulders.
* **Round 3: unweighted inference matters only together with the new input.** On the AT-041d inputs it is -0.012
  (`r3_base_unweighted`), on `compact` +0.016 and on the 4 minimal inputs +0.034 against the round-1 choice.
  `r3_minimal_unweighted` passes the round-2/3 rule (gain +0.034 >= 0.02, worst seed 0.434 > 0.431) and is the final
  choice; the published seed by the rule is seed 1 (validation 0.481).
* **No arm beats `persistence_24h` on validation** (0.476). The best seeds (0.479-0.482) match it; the mean (0.465) and
  two of five seeds (0.434, 0.412) are below it.

## 3. The chosen rule base (r3_minimal_unweighted)

Inputs: `no2_yday_valid` (NO2 of the hour 24 h before the target hour, ug/m3), `no2_last` (ug/m3), `valid_hour_local`
(day periods), `wind_speed` (Beaufort groups); all terms as in AT-041d. 30 rules x 2 antecedents searched; 5-9 rules
kept; mean length 1.0-1.2. **Inference is unweighted**: a row goes to the rule that fires most (product t-norm), with no
weight. When several rules fire equally (the ICA cores are crisp, so firing 1.0 is common), ex_fuzzy takes the first in
its rule order, which is class-major: **a tie goes to the better ICA class**. This happens a lot: on validation the winner
ties at firing 1.0 with a rule of another class in 23 % (seed 0), 73 % (seed 1) and 91 % (seed 2) of the rows. So a
rule's place in the list is part of its meaning, and a rule that fires can still never decide.

Seed 1 (chosen by the rule: highest validation macro-F1, 0.481; test 0.411). Share of validation rows decided, and of
those the share whose observed class is the rule's class:

| rule | decides | observed = class |
|---|---|---|
| IF wind_speed IS Brisa fresca o más THEN Buena | 0.0 % | 0.67 |
| IF wind_speed IS Brisa gentil-moderada THEN Buena | 4.4 % | 0.97 |
| IF no2_yday_valid IS Buena THEN Buena | 78.4 % | 0.89 |
| IF no2_yday_valid IS Razonablemente buena THEN Razonablemente buena | 16.1 % | 0.48 |
| IF valid_hour_local IS Punta de mañana THEN Razonablemente buena | 0.0 % | 0.69 |
| IF no2_yday_valid IS Regular THEN Regular | 0.9 % | 0.32 |
| IF no2_last IS Razonablemente buena THEN Desfavorable o peor | 0.0 % | 0.39 |
| IF wind_speed IS Calma-ventolina THEN Desfavorable o peor | 0.0 % | 0.17 |

Seed 0 (validation 0.479, test 0.403) is the cleanest reading: `IF no2_yday_valid IS c THEN c` for the four classes (82.5 /
16.5 / 0.8 / 0.1 % of rows decided; observed = class 0.90 / 0.48 / 0.34 / 0.27) plus `IF no2_last IS Buena AND wind_speed
IS Brisa ligera THEN Regular` (0.2 %, 0.13). Seed 2 adds hour and `no2_last` rules for Regular / Desfavorable that decide
under 1 % of the rows.

How to read it, honestly: **the model is "the ICA class at the same hour yesterday", with a few rules at the edges.**
Four of the eight rules of seed 1 never decide a validation row. "IF no2_last IS Razonablemente buena THEN Desfavorable o
peor" is in the model and fires on many rows, but it always loses the tie to a better class. Showing it as a rule
without that context would mislead.

## 4. Decision (rules of sections 0.5, 0.8 and 0.9, applied by `experiment_ica4 decide`)

* Round 1: `no2_yday_valid` is the only input that enters (0.377 against the reference 0.336, the published base on common
  rows; `base_refit` 0.326). No combination (one input entered). The winners are every `compact` shape and `+
  no2_yday_valid`. The best are `compact` (0.4316) and `compact_r30a2` (0.4312), tied within 0.005, and the tie goes to
  fewer rules: **`compact_r30a2`**.
* Round 2: none (best +0.000).
* Round 3: **`r3_minimal_unweighted`** replaces it (+0.034; worst seed 0.434 above 0.431). Proposed seed: 1.

## 5. Test 2025 (read once, `final --test`, 174,671 common rows; controls fitted on the same rows)

| model | val macro-F1 | test macro-F1 | test bal-acc | test acc | test Regular recall | test Regular prec | test Desf. recall | test Desf. prec |
|---|---|---|---|---|---|---|---|---|
| ExFuzzy AT-041d published, 3 seeds | 0.336 ± 0.011 | 0.324 ± 0.009 | 0.403 ± 0.041 | 0.735 ± 0.034 | 0.254 ± 0.214 | 0.053 ± 0.011 | 0.160 ± 0.019 | 0.014 ± 0.004 |
| ExFuzzy AT-041d published, served seed 0 | 0.348 | 0.329 | | | | | | |
| ExFuzzy base_refit, 3 seeds | 0.326 ± 0.005 | 0.314 ± 0.008 | 0.405 ± 0.045 | 0.713 ± 0.063 | 0.313 ± 0.175 | 0.056 ± 0.021 | 0.160 ± 0.051 | 0.006 ± 0.003 |
| ExFuzzy compact_r30a2 (round 1), 3 seeds | 0.431 ± 0.031 | 0.383 ± 0.018 | 0.416 ± 0.033 | 0.823 ± 0.003 | 0.293 ± 0.120 | 0.120 ± 0.047 | 0.135 ± 0.059 | 0.083 ± 0.033 |
| **ExFuzzy r3_minimal_unweighted (final), 3 seeds** | 0.465 ± 0.026 | **0.404 ± 0.008** | 0.402 ± 0.008 | 0.816 ± 0.002 | 0.202 ± 0.025 | 0.215 ± 0.004 | 0.084 ± 0.014 | 0.095 ± 0.027 |
| ExFuzzy r3_minimal_unweighted, seeds 0 / 1 / 2 | 0.479 / 0.481 / 0.434 | 0.403 / **0.411** / 0.396 | | | | | | |
| persistence (class of no2_last) | 0.294 | 0.293 | 0.294 | 0.768 | 0.021 | 0.019 | 0.000 | 0.000 |
| **persistence_24h (class of no2_yday_valid)** | 0.476 | **0.407** | 0.409 | 0.815 | 0.216 | 0.210 | 0.101 | 0.099 |
| climatology (majority class) | 0.285 | 0.291 | 0.285 | 0.828 | 0.000 | 0.000 | 0.000 | 0.000 |
| HGB, AT-041d inputs | 0.372 | 0.376 | 0.409 | 0.846 | 0.033 | 0.160 | 0.215 | 0.026 |
| HGB regression then binned, AT-041d inputs | 0.396 | 0.410 | 0.402 | 0.837 | 0.099 | 0.298 | 0.063 | 0.086 |
| RF, AT-041d inputs | 0.348 | 0.363 | 0.347 | 0.853 | 0.018 | 0.403 | 0.025 | 0.053 |
| HGB / RF / LR on the 30k subsample, AT-041d inputs | 0.409 / 0.418 / 0.340 | 0.392 / 0.399 / 0.349 | | | | | | |
| HGB, compact inputs | 0.447 | 0.422 | 0.430 | 0.856 | 0.123 | 0.264 | 0.177 | 0.051 |
| HGB regression then binned, compact inputs | 0.439 | 0.442 | 0.419 | 0.853 | 0.136 | 0.399 | 0.076 | 0.200 |
| RF, compact inputs | 0.425 | 0.415 | 0.384 | 0.861 | 0.076 | 0.460 | 0.089 | 0.171 |
| HGB / RF / LR on the 30k subsample, compact inputs | 0.454 / 0.501 / 0.479 | 0.419 / **0.448** / 0.425 | | | | | | |

AT-041d's own-row test numbers (`ica2-justified/summary.json`, 180,326 rows): ExFuzzy 0.324 ± 0.010 (served 0.329),
persistence 0.294, HGB regression then binned 0.414, RF 0.374, RF subsample 0.394; the common-row figures above agree
within 0.01 for each (RF full 0.363 against 0.374).

Reading:

* The final rule base raises test macro-F1 from 0.324 (served seed 0.329) to **0.404 ± 0.008** (proposed seed 0.411):
  **+0.08**, with 5-9 rules of one antecedent each instead of 11-15 rules of up to four. On rare classes, test precision of
  Regular goes from 0.05 to 0.22 and of Desfavorable from 0.014 to 0.10; recall of Regular falls from 0.25 to 0.20 and of
  Desfavorable from 0.16 to 0.08. It reaches the level of the strongest AT-041d baseline (HGB regression then binned with
  the old inputs, 0.410).
* **It does not beat the seasonal-naive forecast "the class at the same hour yesterday" (0.407).** On test the two are
  equal within seed noise. The gain over AT-041d comes from the input, not from the rules on top of it.
* **The tree baselines gain more from the same input**: RF on the subsample 0.448, HGB regression then binned 0.442 (+0.03
  to +0.05 over the rule base and over `persistence_24h`). The gap between ExFuzzy and the trees narrows from ~0.08 (0.324
  against 0.394-0.414) to ~0.04 (0.404 against 0.442-0.448).
* Validation overstated every model with the new input (0.465 against 0.404 for ExFuzzy, 0.476 against 0.407 for
  persistence_24h, which has no fitted part). So part of the drop belongs to the year, not only to the selection.
  Rounds 2-3 were still selected on 2024, so the ExFuzzy validation figure is optimistic on both counts.

## 6. Other tasks (section 0.7): Madrid +1 / +3 / +12 h and Germany +6 h

Same protocol per task: that task's published (AT-080 / AT-070) protocol, rows where `no2_yday_valid` (key t+h-24 h) is
finite, and three arms with 3 seeds each:

* `base_refit`;
* `compact_r30a2`, the round-1 Madrid structure: lags replaced by `no2_yday_valid`, 30 x 2, dominance weights;
* `minimal_unweighted`, the final Madrid structure: `no2_yday_valid`, `no2_last`, hour, wind; 30 x 2, unweighted.

Decision as in section 0.5 against that task's reference (the larger of the published base re-scored and `base_refit`);
the test is read once. Germany uses its own EAQI terms for `no2_yday_valid` (those of its `no2_last`), its 1,000,000-row
partition reference and its 2,000,000-row baseline bound. **Madrid +24 h was not run**: its "yesterday at the valid hour" is
the key t, which is not finished at t, so the input does not exist there (section 0.7). NYC was not tried: its target is
already relative to the zone's hour-of-week normal.

| task | reference (val) | `compact_r30a2` val | `minimal_unweighted` val | decision | test: published base | test: chosen arm | test: persistence | test: persistence_24h | test: best tree, task inputs | test: best tree, new inputs |
|---|---|---|---|---|---|---|---|---|---|---|
| Madrid +1 h | 0.474 | 0.488 ± 0.014 (+0.014) | 0.483 ± 0.033 (+0.009) | **keep base** (no gain >= 0.02) | 0.445 ± 0.005 | - | 0.462 | 0.406 | 0.522 (HGB reg. binned) | not run |
| Madrid +3 h | 0.357 | 0.431 ± 0.026 | 0.460 ± 0.041 | `minimal_unweighted` (seed 0) | 0.331 ± 0.014 | **0.402 ± 0.015** (seed 0: 0.412) | 0.330 | 0.405 | 0.443 (HGB reg. binned) | 0.450 (RF subsample) |
| Madrid +6 h (sections 2-5) | 0.336 | 0.431 ± 0.031 | 0.465 ± 0.026 | `r3_minimal_unweighted` (seed 1) | 0.324 ± 0.009 | **0.404 ± 0.008** (seed 1: 0.411) | 0.293 | 0.407 | 0.410 (HGB reg. binned) | 0.448 (RF subsample) |
| Madrid +12 h | 0.320 | 0.431 ± 0.015 | 0.465 ± 0.023 | `minimal_unweighted` (seed 1) | 0.318 ± 0.004 | **0.400 ± 0.015** (seed 1: 0.409) | 0.306 | 0.408 | 0.385 (RF subsample) | 0.421 (RF subsample) |
| Germany +6 h | 0.441 | 0.470 ± 0.009 | 0.473 ± 0.004 | `minimal_unweighted` (seed 2; tie with compact -> fewer inputs) | 0.462 ± 0.012 | **0.517 ± 0.007** (seed 2: 0.517) | 0.455 | **0.536** | 0.530 (HGB subsample) | 0.569 (RF subsample) |

"New inputs" for the trees: the chosen arm's inputs (4 at +3 h, +12 h and Germany; the 7 `compact` inputs at +6 h,
deviation 4). Each `ica4/final_test.json` holds every metric.

Germany +6 h, seed 2 (proposed by the rule), 10 rules: `no2_yday_valid IS Good -> Good`, `no2_last IS Good -> Fair`,
`no2_yday_valid IS Fair -> Fair`, `no2_last IS Fair AND valid_hour_local IS Night -> Fair`, `no2_yday_valid IS Moderate AND
wind_speed IS Light breeze -> Moderate`, `valid_hour_local IS Night AND wind_speed IS Calm to light air -> Moderate`,
`no2_last IS Fair AND wind_speed IS Calm to light air -> Moderate`, `wind_speed IS Gentle to moderate breeze -> Moderate`,
`no2_yday_valid IS Poor or worse -> Poor or worse`, `no2_last IS Poor or worse -> Poor or worse` (with ties to the better
class, as in section 3).

Reading. The pattern of Madrid +6 h repeats from +3 h to +12 h and in Germany. The input lifts the rule base by 0.06-0.08
macro-F1 on test (Madrid +3 h +0.07, +12 h +0.08, Germany +0.055), to the level of `persistence_24h` in Madrid and
**below it in Germany** (0.517 against 0.536). At +1 h the last hour already carries the information (persistence 0.462
beats persistence_24h 0.406), and no arm passes the margin.

## 7. Conclusions, risks and open questions

1. **Main hypothesis (H1/H2) rejected.** Projecting the current anomaly onto the valid-hour climatology, or giving the
   climatology alone, does not help the winning-rule classifier (-0.014 to +0.008 on validation).
2. **What raises macro-F1 is the station's NO2 24 h before the target hour**, used in place of the raw lags, with
   **unweighted** inference and short rules: Madrid +6 h test 0.324 -> 0.404 ± 0.008 (proposed seed 0.411), 5-9 rules of
   one antecedent. Same order of gain at +3 h, +12 h and in Germany. The input is a single finished hour of the station's
   own series, in ug/m3, needs no fitted quantity, and reads "yesterday at this hour".
3. **But the rule base does not beat the seasonal-naive forecast built from that same input** (Madrid +6 h 0.404 against
   0.407; Germany 0.517 against 0.536). The honest reading for the demo: the rules have rediscovered "the class it had
   yesterday at this hour", plus a few edge rules that rarely decide. The trees gain more from the input (RF subsample
   0.448 at +6 h). If the demo shows this model, it should show `persistence_24h` next to it.
4. **Unweighted inference changes how a rule is read.** Ties at firing 1.0 are frequent (23-91 % of rows depending on the
   seed) and go to the first rule in ex_fuzzy's class-major order, i.e. to the better class. Some rules fire on many rows
   and never decide one; the proposed Madrid seed 1 has four such rules. Before publication, A0/A5 need to decide how the
   UI shows "the rule that decided" when several fire at 1.0, whether rules that decide no row are shown, and
   whether seed 0 (validation 0.479 against 0.481, the cleanest five rules) should be preferred to the rule's seed 1 for
   readability. The rule chose seed 1; seed 0 is within the 0.005 tie margin, but section 0 broke ties only between arms,
   not seeds. Nothing was published.
5. **Seed instability is larger than before**: 5-seed sd 0.032 for the final arm (seeds 0.41-0.48), because some GA runs
   add rare-class rules that cost precision. The proposed seed is the best of three on validation.
6. **Selection on one validation year, three rounds.** Rounds 2-3 were post-hoc; the 2024 -> 2025 drop (0.465 -> 0.404)
   is also present in the fit-free `persistence_24h` (0.476 -> 0.407), so the year explains most of it.
7. **Publishing would need** the `no2_yday_valid` column in the feature tables (A1: `no2` at key t+h-24 h, the same
   finished-hour rule as `no2_lag24h`), `rule_weighting = "none"` in the run manifest and rules (the contract field allows it;
   A0 must check what the exported rule weight then holds, since ex_fuzzy still computes dominance scores that inference ignores), and a "no prediction" for the ~1 % of rows without
   that hour (2.3 % fewer complete rows in this experiment because all eight candidates were required).
8. **Upstream notes (ex-fuzzy, not needed by Atlas):** (a) with unweighted inference, the tie-break by rule order is the
   whole decision for most rows; an explicit, documented tie rule (or reporting ties) would make the rule shown to a
   user honest. (b) Dominance-score weights computed on a class-tempered sample penalise rare-class rules at the
   shoulders of overlapping terms (section 0.9 diagnostic: 0.447 against 0.476 for the same four rules).

## 8. Reproduce

Environment: Python 3.12, ex_fuzzy==3.3.1 (PyPI), numpy 2.3.5, pandas 2.3.3, scikit-learn 1.9.0, pymoo 0.6.2;
`export ATLAS_DATA_DIR=.../data ATLAS_ARTIFACTS_DIR=.../artifacts PYTHONPATH=src OMP_NUM_THREADS=1`.

```bash
C=configs/ml/madrid_no2_h6_ica4_experiment.json
python -m atlas.ml.experiment_ica4 base   --config $C              # published pickles on the common rows (10 s)
python -m atlas.ml.experiment_ica4 arms   --config $C --workers 10 --only base_refit,no2_clim_valid,no2_expected_valid,no2_expected_valid_ratio,no2_expected_valid_damped,no2_yday_valid,no2_week_valid,no2_mean_24h,no2_max_24h  # 27 fits, ~10 min
python -m atlas.ml.experiment_ica4 stage2 --config $C --workers 10 # compact (3 fits)
python -m atlas.ml.experiment_ica4 shape  --config $C --workers 15 # 15 fits
python -m atlas.ml.experiment_ica4 arms   --config $C --workers 15 --only r2_power075,r2_power100,r2_minimal,r2_minimal_power100,r3_base_unweighted,r3_yday_unweighted,r3_compact_unweighted,r3_compact_r60a4_unweighted,r3_minimal_unweighted
python -m atlas.ml.experiment_ica4 decide --config $C
python -m atlas.ml.experiment_ica4 robust --config $C --workers 4
python -m atlas.ml.experiment_ica4 final --test --config $C        # once: a TEST_READ marker refuses a second read
python -m atlas.ml.experiment_ica4 report --config $C              # the tables of sections 2 and 5
for C in configs/ml/madrid_no2_h{1,3,12}_ica4_experiment.json configs/ml/de_no2_h6_ica4_experiment.json; do
  for S in base arms decide; do python -m atlas.ml.experiment_ica4 $S --config $C --workers 9; done
  python -m atlas.ml.experiment_ica4 final --test --config $C
done
```

Run directories (experiment dirs, not publication run dirs): `artifacts/<task>/experiments/ica4/` for `madrid_no2_h6`,
`madrid_no2_h1`, `madrid_no2_h3`, `madrid_no2_h12`, `de_no2_h6` (`val/*.json` per arm, `fits/`, `models/*.pkl`,
`decision.json`, `final_test.json`, `TEST_READ`; Madrid +6 h also `stage2_arms.json`, `shape_arms.json` and `logs/`).
Nothing was written under `artifacts/published`.
Compute: the large machine, about 25 minutes of wall time for the 78 Madrid +6 h GA fits (10-260 s each, 4-15 in parallel) and
15 minutes for the four other tasks; peak RSS per fit process 0.9-1.0 GB for Madrid, 9.5-9.7 GB for Germany (the
27 M-row table is inherited by every worker).
Tests: `tests/ml/test_diurnal_features.py` (leakage: finished hours only, climatology and rho from training rows,
station grid), `tests/ml/test_ica4_decision.py` (the decision rules).

## 9. Publication (approved by the user via A0, 2026-11-06)

Scope: the four tasks where the rule of section 6 adopted the 4-input unweighted arm. **Madrid +1 h and +24 h keep their
served models**, and so does every other task. The old run and published directories stay on disk.

| task | served before | served now (arm, seed by the pre-registered rule) |
|---|---|---|
| madrid_no2_h3 | `exfuzzy-madrid_no2_h3-ica2-justified-seed2` | `exfuzzy-madrid_no2_h3-ica4-yday-seed0` (`minimal_unweighted`, seed 0) |
| madrid_no2_h6 | `exfuzzy-madrid_no2_h6-ica2-justified-seed0` | `exfuzzy-madrid_no2_h6-ica4-yday-seed1` (`r3_minimal_unweighted`, seed 1) |
| madrid_no2_h12 | `exfuzzy-madrid_no2_h12-ica2-justified-seed0` | `exfuzzy-madrid_no2_h12-ica4-yday-seed1` (`minimal_unweighted`, seed 1) |
| de_no2_h6 | `exfuzzy-de_no2_h6-eaqi-justified-seed0` | `exfuzzy-de_no2_h6-ica4-yday-seed2` (`minimal_unweighted`, seed 2) |

### 9.1 The input in the feature tables

`no2_yday_valid` is now a column of the A1 feature tables of those four tasks (`configs/air/{madrid_no2_h3,h6,h12,
de_no2_h6}.json`: `kind: no2`, key offset `h - 24` h, `recommended: false`, so `complete` does not change; `in_spec: true`
puts it in the feature spec with `lag_hours = 24 - h`). The feature card defines it as "NO2 of the hour with key
issued_at_utc - 18h, i.e. the hour [t-18h, t-17h). ... Same clock hour as the target, one day earlier (key valid_at_utc -
24h)". The tables were rebuilt (Madrid on the workstation, Germany on the large machine) and compared with the previous ones. Every old column
is identical in values and nulls, row for row (1,472,736 / 1,472,664 / 1,472,520 / 26,998,840 rows). The new column equals
`no2_last` of the row issued at t+h-23 h in 100 % of the rows, and equals the quantity ica4 computed in
`diurnal_features` (checked again when the run directories were written; Germany at float32, the precision of its
compact loader). Leakage tests are in `tests/air/test_features.py`: the key is valid_at - 24 h and finished at issue;
the column does not enter `complete`; the key follows the horizon (+3, +12 h). `tests/air/test_horizons.py` now allows the
input to differ by horizon. Web label (v0.5 `features` metadata, `configs/air/attribution*.json`): **«NO₂ ayer a la hora
de validez»**, with a description that gives the hour for any horizon. `lag_hours` is not stated there because one
attribution file serves every horizon; the spec carries it.

### 9.2 Ties, pruning and weights

* **What decides a tie.** Inference is unweighted (`rule_weighting = "none"`): a row goes to the rule with the largest
  firing. On equal firing, ex_fuzzy takes the first rule in its class-major order (numpy argmax over `get_rules()`): the
  rule of the better class, and within a class the earlier one. Rule ids and the order in `rules.json` are that order
  (R01 = first). With crisp ICA/EAQI cores this is the usual case, not a corner case. On the published 2025 rows the
  winner ties at the top with another rule in 97 % (Madrid +3 h), 79 % (+6 h), 97 % (+12 h) and 64 % (Germany) of the
  rows, and with a rule of another class in 97 / 76 / 97 / 58 %. **The rule base therefore reads as an ordered list:
  from the first rule down, the first one that fires fully decides.** The run manifests state this rule (`warnings`,
  `hyperparameters.tie_rule`).
* **Parity with native ex_fuzzy, row by row** (`python -m atlas.ml.publish_parity <published dir>`, every published
  input row: 185,304 / 185,330 / 185,438 / 3,095,544). The published `prediction_label` equals ex_fuzzy `predict`, and the
  published `is_winner` rule equals ex_fuzzy's winning rule and the first argmax in rule order, all in 100 % of the rows.
  `association_degree = firing_strength x weight` with every weight 1.0, and `rules.json` lists the rules in ex_fuzzy order
  with their classes. `tests/integration` (argmax with ties, first in order) passes on the new models (section 9.4).
* **Pruning.** A rule that decides no validation row of the publication rows was removed before export
  (`prune_never_deciding`). This cannot change any validation prediction, and that is checked. Of the four published seeds
  only Madrid +6 h lost one rule (`IF wind_speed IS Brisa fresca o más THEN Buena`, 8 -> 7 rules), and no 2025 prediction
  changed. The other seeds of the arms: one rule each in Madrid +3 h seed 2 and +6 h seed 2 (one 2025 prediction changes
  in the latter); none elsewhere. `experiments/ica4-yday/pruning.json` lists them. The rules that decide 2-74 of the ~185,000
  Madrid 2025 rows (for example `IF wind_speed IS Calma-ventolina THEN Desfavorable o peor`) decided at least one
  validation row and stay. They are the rows where no ICA-band rule fires fully (yesterday above 138 ug/m3, above the
  shoulder of Regular), and their accuracy there is 0-25 %.
* **Weights in the contract.** No contract change is needed to say "unweighted". `InferenceSpec.rule_weighting =
  "none"` exists, `RuleDefinition.weight` is 1.0 and the rule text drops "(peso ...)". The activation table and the trace
  carry `weight = 1.0` and `association_degree = firing_strength`. `importance.json` has `mean_weight_share: null` for
  classifiers, as before. What the contract cannot say today is that a tie was decided by order (see 9.5).
* **Seeds.** The published seed is the pre-registered one (highest validation macro-F1 on the ica4 rows). On the
  publication rows the same seed ranks first in all four tasks. Within noise, though: Madrid +6 h seed 0 scores 0.478
  against 0.480 for seed 1 (validation), and it is the cleaner rule set (five rules: `IF no2_yday_valid IS c THEN c` for
  the four classes plus one). Madrid +12 h seed 0 scores 0.478 against 0.478 with five rules. The rule was not overridden.

### 9.3 Before / after (published metrics.json; test = slice `all`, 2025; validation = `validation/all`)

The new rows are the task's complete rows with `no2_yday_valid` finite (about 1 % fewer than the served model's). The
baselines of the new run directories are fitted on the model's four inputs. `persistence_24h` (the class of
`no2_yday_valid`) is a baseline row with the same metrics and slices as `persistence` (all, validation/all, entity=...).

| task | served model | test macro-F1 (n) | new model | val macro-F1 | test macro-F1 (n) | persistence test | persistence_24h test | best tree baseline test, model's inputs | rules before -> after |
|---|---|---|---|---|---|---|---|---|---|
| madrid_no2_h3 | `exfuzzy-madrid_no2_h3-ica2-justified-seed2` | 0.344 (180773) | `exfuzzy-madrid_no2_h3-ica4-yday-seed0` | 0.484 | 0.412 (178830) | 0.330 | 0.405 | 0.448 (random_forest_subsample) | 12 -> 8 |
| madrid_no2_h6 | `exfuzzy-madrid_no2_h6-ica2-justified-seed0` | 0.329 (180326) | `exfuzzy-madrid_no2_h6-ica4-yday-seed1` | 0.480 | 0.411 (178122) | 0.293 | 0.407 | 0.425 (random_forest_subsample) | 15 -> 7 |
| madrid_no2_h12 | `exfuzzy-madrid_no2_h12-ica2-justified-seed0` | 0.317 (179888) | `exfuzzy-madrid_no2_h12-ica4-yday-seed1` | 0.478 | 0.409 (177665) | 0.306 | 0.408 | 0.418 (random_forest_subsample) | 10 -> 6 |
| de_no2_h6 | `exfuzzy-de_no2_h6-eaqi-justified-seed0` | 0.470 (2957829) | `exfuzzy-de_no2_h6-ica4-yday-seed2` | 0.477 | 0.518 (2911495) | 0.455 | 0.536 | 0.569 (random_forest_subsample) | 15 -> 10 |

All four new models beat the served ones on test. In Madrid they are at the level of `persistence_24h` (+0.007, +0.004,
+0.001). In Germany they are below it (0.518 against 0.536). The tree baselines on the same four inputs stay above them
(+0.01 to +0.05).

### 9.4 Rules of the published models

**`exfuzzy-madrid_no2_h3-ica4-yday-seed0`** (8 rules, unweighted, in ex_fuzzy order; 2025 rows decided, share, accuracy of those):

- R01: IF no2_yday_valid IS Buena AND no2_last IS Buena THEN ICA = Buena — 133542 rows (72.07 %), acc. 0.93
- R02: IF valid_hour_local IS Mediodía AND wind_speed IS Brisa ligera THEN ICA = Buena — 1052 rows (0.57 %), acc. 0.90
- R03: IF wind_speed IS Brisa gentil-moderada THEN ICA = Buena — 507 rows (0.27 %), acc. 0.86
- R04: IF no2_yday_valid IS Razonablemente buena THEN ICA = Razonablemente buena — 27901 rows (15.06 %), acc. 0.44
- R05: IF no2_yday_valid IS Buena THEN ICA = Razonablemente buena — 20752 rows (11.20 %), acc. 0.30
- R06: IF no2_last IS Desfavorable o peor AND valid_hour_local IS Noche THEN ICA = Regular — 2 rows (0.00 %), acc. 0.00
- R07: IF no2_yday_valid IS Regular THEN ICA = Regular — 1473 rows (0.79 %), acc. 0.21
- R08: IF wind_speed IS Calma-ventolina THEN ICA = Desfavorable o peor — 74 rows (0.04 %), acc. 0.11

**`exfuzzy-madrid_no2_h6-ica4-yday-seed1`** (7 rules, unweighted, in ex_fuzzy order; 2025 rows decided, share, accuracy of those):

- R01: IF wind_speed IS Brisa gentil-moderada THEN ICA = Buena — 5908 rows (3.19 %), acc. 0.96
- R02: IF no2_yday_valid IS Buena THEN ICA = Buena — 149556 rows (80.70 %), acc. 0.89
- R03: IF no2_yday_valid IS Razonablemente buena THEN ICA = Razonablemente buena — 28318 rows (15.28 %), acc. 0.43
- R04: IF valid_hour_local IS Punta de mañana THEN ICA = Razonablemente buena — 53 rows (0.03 %), acc. 0.58
- R05: IF no2_yday_valid IS Regular THEN ICA = Regular — 1424 rows (0.77 %), acc. 0.21
- R06: IF no2_last IS Razonablemente buena THEN ICA = Desfavorable o peor — 16 rows (0.01 %), acc. 0.12
- R07: IF wind_speed IS Calma-ventolina THEN ICA = Desfavorable o peor — 55 rows (0.03 %), acc. 0.11

**`exfuzzy-madrid_no2_h12-ica4-yday-seed1`** (6 rules, unweighted, in ex_fuzzy order; 2025 rows decided, share, accuracy of those):

- R01: IF no2_yday_valid IS Buena THEN ICA = Buena — 155148 rows (83.67 %), acc. 0.90
- R02: IF no2_yday_valid IS Razonablemente buena THEN ICA = Razonablemente buena — 28739 rows (15.50 %), acc. 0.42
- R03: IF no2_yday_valid IS Regular THEN ICA = Regular — 1469 rows (0.79 %), acc. 0.21
- R04: IF valid_hour_local IS Punta de mañana THEN ICA = Regular — 4 rows (0.00 %), acc. 0.00
- R05: IF wind_speed IS Brisa ligera THEN ICA = Desfavorable o peor — 4 rows (0.00 %), acc. 0.25
- R06: IF wind_speed IS Calma-ventolina THEN ICA = Desfavorable o peor — 74 rows (0.04 %), acc. 0.09

**`exfuzzy-de_no2_h6-ica4-yday-seed2`** (10 rules, unweighted, in ex_fuzzy order; 2025 rows decided, share, accuracy of those):

- R01: IF no2_yday_valid IS Good THEN EAQI NO2 = Good — 1367329 rows (44.54 %), acc. 0.77
- R02: IF no2_last IS Good THEN EAQI NO2 = Fair — 414817 rows (13.51 %), acc. 0.43
- R03: IF no2_yday_valid IS Fair THEN EAQI NO2 = Fair — 758709 rows (24.71 %), acc. 0.58
- R04: IF no2_last IS Fair AND valid_hour_local IS Night THEN EAQI NO2 = Fair — 34040 rows (1.11 %), acc. 0.50
- R05: IF no2_yday_valid IS Moderate AND wind_speed IS Light breeze THEN EAQI NO2 = Moderate — 229411 rows (7.47 %), acc. 0.60
- R06: IF valid_hour_local IS Night AND wind_speed IS Calm to light air THEN EAQI NO2 = Moderate — 17848 rows (0.58 %), acc. 0.57
- R07: IF no2_last IS Fair AND wind_speed IS Calm to light air THEN EAQI NO2 = Moderate — 66298 rows (2.16 %), acc. 0.48
- R08: IF wind_speed IS Gentle to moderate breeze THEN EAQI NO2 = Moderate — 154124 rows (5.02 %), acc. 0.46
- R09: IF no2_yday_valid IS Poor or worse THEN EAQI NO2 = Poor or worse — 19105 rows (0.62 %), acc. 0.33
- R10: IF no2_last IS Poor or worse THEN EAQI NO2 = Poor or worse — 8403 rows (0.27 %), acc. 0.10

In Madrid +6 h and +12 h no rule says "yesterday Desfavorable -> Desfavorable". When yesterday's hour is above the
shoulder of Regular (138 ug/m3), no ICA-band rule fires and one of the weak rules at the end of the list decides (55-74
rows of 2025, accuracy 0.09-0.12). The web should not present those rules as an explanation of high NO2.

### 9.5 What other agents need to do

* **Contract (A0):** nothing is needed to say "unweighted": `InferenceSpec.rule_weighting = "none"` already exists, the
  weights are 1.0 and association = firing. What the contract cannot say is that **a tie was decided by rule order**.
  Proposal, not implemented: `InferenceSpec.tie_break: Literal["first_in_rule_order"]` (a constant of ex_fuzzy
  3.3.1 winning-rule inference), and in `RuleTrace.prediction` an optional `tied_rule_ids: list[str]` (rules whose
  association equals the winner's). The web could then say "R02 decide por orden; R05 también se cumple al 100 %".
  Without it, the web can derive ties from the trace (rules with the winner's firing).
* **Web (A5):** (1) show `persistence_24h` ("misma hora ayer") next to `persistence` in the model card; it has the same
  metrics and slices. (2) For `rule_weighting = "none"`, do not show "peso" and do not say association = firing x
  weight. Say that rules are read in order and that the first fully firing rule decides. (3) The label of the new input
  is «NO₂ ayer a la hora de validez».
* **QA (A6):** `scripts/qa/reproduce.sh` still lists the AT-041d / AT-070 run directories for Madrid +6 h and Germany
  +6 h; the commands of section 9.6 replace them. The CI asset `qa-artifacts` must be refreshed (new Madrid +6 h and
  Germany +6 h directories).

### 9.6 Reproduce the publication

```bash
# 1. tables (A1 code; only no2_yday_valid is new, every other column is byte-for-byte the same)
for h in 3 6 12; do python -m atlas.domains.air.features --config configs/air/madrid_no2_h$h.json --no-doc; done
python -m atlas.domains.air.de_features --no-doc            # writes configs/air/de_no2_h6_feature_spec.json too
# 2. run directories: the selected ica4 fits, pruned, scored on the task's own rows (needs the ica4 experiment dirs)
for t in madrid_no2_h3 madrid_no2_h6 madrid_no2_h12 de_no2_h6; do
  python -m atlas.ml.experiment_ica4 publish-runs --config configs/ml/${t}_ica4_experiment.json \
    --publish-config configs/ml/${t}_ica4_publish_experiment.json; done
# 3. publish (new model ids; the registry now points the four tasks at them)
python -m atlas.services.publish --run-dir artifacts/madrid_no2_h6/ica4-yday-seed1 \
  --features data/processed/air/features/madrid_no2_h6/table --entities data/processed/air/stations.geojson \
  --feature-spec configs/ml/madrid_no2_h6_feature_spec.json --from 2025-01-01T00:00:00Z --to 2026-01-01T00:00:00Z \
  --task-id madrid_no2_h6 --title "Madrid air quality" --metadata configs/air/attribution.json \
  --territory madrid --territory-title Madrid --published-dir artifacts/published
#   (same for madrid_no2_h3 / ica4-yday-seed0 and madrid_no2_h12 / ica4-yday-seed1; Germany: de_no2_h6 / ica4-yday-seed2,
#    data/processed/air-de/..., configs/air/de_no2_h6_feature_spec.json, configs/air/attribution_de.json,
#    --title "Germany air quality (EEA)" --territory germany --territory-title Alemania)
# 4. row-by-row parity with native ex_fuzzy
python -m atlas.ml.publish_parity artifacts/published/exfuzzy-*-ica4-yday-seed*
```

Where it ran: run directories on the large machine from a clean clone at commit 0c02a4a (`git_dirty: false` in every manifest).
Madrid published on the workstation. Germany published on the large machine (its `publish.json` records that machine's path of the feature
table), with the workstation's registry copied there and back. Germany's table was rebuilt on the large machine and copied back to
the workstation's `data/`.
