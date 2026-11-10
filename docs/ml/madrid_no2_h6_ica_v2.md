# Madrid NO2 at t+6 h as an ICA category, v2: justified linguistic terms, LR/RF baselines and the traffic question (AT-041d)

Follow-up of `madrid_no2_h6_ica.md` (AT-041c). Same task, rows, split, class merge, fitting subsample, budget and
baselines; what changes is (1) the **linguistic terms**, which now have a documented rationale per input and, for NO2,
the official ICA bands as cores, (2) two new baseline families (logistic regression, random forest), (3) a comparison
**with and without the AT-012 traffic features**. Every number below is printed by `python -m atlas.ml.report_class`
and `python -m atlas.ml.report_v2` from the run artifacts.

**What this is not.** Same limits as AT-041c: the model predicts which official ICA band the concentration will fall
in; firing, association degree and rule weight are degrees of rule match, not probabilities, contributions or risk.
No causal, clinical, sanitary or regulatory claim. A term named after a source ("Brisa ligera", "Punta de mañana") says
how the input was split, not that the rule is a physical explanation.

**Result in one paragraph.** ICA-aligned terms for the four NO2 inputs alone cost validation macro-F1 (0.312 against
0.346 for the AT-041c quantile terms, a drop larger than the 0.02 tolerance); adding the justified terms for wind, hour
and weekday brought it back to 0.336 (within tolerance), so by the rule fixed in section 0 the final scheme is
`justified`. On test (2025, read once) it scores macro-F1 0.329 for the published seed (3 seeds 0.324 +- 0.010), against
0.336 (0.332 +- 0.004) for AT-041c: no gain in accuracy, a modest gain in readability (rule-set Jaccard across seeds 0.15
instead of 0.12, still low). It stays below HGB, random forest and even logistic regression on the same 30,000 rows. The
traffic features add nothing measurable to ExFuzzy or to any of the 12 baseline variants (all differences within
+-0.01 macro-F1, ExFuzzy -0.004 on test with a seed sd of 0.014-0.017).

## 0. Decision rules (written before the comparison tables were read)

History, for honesty. The first version of these rules (commit 68e55fc) used NO2 terms with a +-5 ug/m3 shoulder and
a hand-made hour/weekday partition. Three single-seed validation fits of that variant had been logged (macro-F1 0.270,
0.333, 0.334 for 30 rules x 2, 3, 4 antecedents; the AT-041c quantile terms give 0.342, 0.333, 0.334 for the same
shapes) when A0 extended the scope: a justified partition for every input (shoulders from the legal measurement
uncertainty, WMO wind classes, a day-period partition read from the training-period traffic profile) and two more
baseline families. That variant was abandoned and its fits deleted; nothing else had been read. The rules below
replace the first version and were committed before the first fit of the new partitions.

**Partitions** (validation 2024 only). Three term schemes, same rows, split, class merge, subsample, budget (150 x 60),
sampling power 0.5 and dominance-score weighting as AT-041c:

* `quantile`: AT-041c, 3 quantile trapezoids (Low / Medium / High) for every input (run `ica-v1`, reused).
* `ica_no2`: the four NO2 inputs use the ICA bands as terms, shoulders = 15 % of each breakpoint (legal measurement
  uncertainty); every other input keeps its quantile terms.
* `justified`: `ica_no2` plus the justified terms of wind speed (WMO Beaufort groups), hour (day periods from the 2023
  traffic profile) and weekday (Laborable / Sábado / Domingo). Temperature and relative humidity keep data-driven
  quantile terms because no defensible source was found (`configs/ml/madrid_partitions.json` has the rationale and the
  source of every variable).

Rule base shape per scheme: the one of 6 shapes (nRules in {30, 60} x nAnts in {2, 3, 4}) with the highest validation
macro-F1 of a single fit with seed 0 (ties: fewer rules). For `quantile` those six fits are the ones already in the
`ica-v1` selection. Then 3 seeds (0, 1, 2) of that shape on validation.

**Final scheme.** Readability order: `justified`, then `ica_no2`, then `quantile`. Take the first scheme in that
order whose mean validation macro-F1 over the 3 seeds is within 0.02 of the best of the three means. The published seed
is, as in AT-041c, the one with the highest validation macro-F1. The test year (2025) is read once, for the final
scheme's 3 seeds and all baselines, in the same command that writes the summary.

**Baselines** (not part of any selection): logistic regression and random forest, plain and class-balanced, on the
full training period and on the 30,000-row fitting subsample, next to the HGB ones, all scored on the same rows.

**Traffic** (2023 train / 2024 validation / 2025 test; rows with finite traffic features only, identical for every arm).
The comparison is reported, not selected on: it uses the final scheme and shape, with and without
`traffic_intensity_last` and `traffic_intensity_lag24h` (data-driven quantile terms), 3 seeds for ExFuzzy, one fit for
each baseline. The published model stays on the full 2019-2025 table without traffic unless the ExFuzzy validation
macro-F1 with traffic is better than without it by more than 0.02 *and* by more than twice the larger seed standard
deviation; even then publishing it would need the 2023-only training period and a fallback for the two stations
without traffic, so it would be a separate decision for A0.

## 1. The partitions and their justification

`configs/ml/madrid_partitions.json` is the single source (fields `features`, `kind`, `domain`, `shoulders`, `terms`
with `core` and `params`, `rationale`, `source_url`, `source_status`). `atlas.ml.partitions.load_partition_file`
refuses a file whose written `params` are not the ones the cores and shoulders give. A term is a trapezoid whose core
(membership 1) is exactly the band, with linear shoulders outside it; there is one shoulder width per boundary, used by
both neighbours (`(lower - w_below, lower, upper, upper + w_above)`); the first and last band end at the domain edge.
The terms overlap over the shoulders and do not sum to 1.

| input | terms (core) | shoulders | rationale | source and what was verified |
|---|---|---|---|---|
| `no2_last`, `no2_lag1h`, `no2_lag3h`, `no2_lag24h` (ug/m3) | Buena 0-40, Razonablemente buena 41-90, Regular 91-120, Desfavorable o peor 121-1000 | 15 % of the boundary: 6, 13.5, 18 | cores are the target's own bands, so a rule reads in the language of the target | **Directive 2008/50/EC Annex I, "Data quality objectives"**: NO2 fixed measurements, uncertainty 15 %, 95 % confidence, individual measurements averaged over the limit-value period, "applicable in the region of the appropriate limit value". Read in the legislation.gov.uk copy of the original text (<https://legislation.gov.uk/cy/eudr/2008/50/annex/I/adopted/data.htm>); EUR-Lex returned an empty page to the tools used. **Directive (EU) 2024/2881, Annex V Section A Table 2**: not verified against the Official Journal; only a secondary table (<https://aq-framework-snpa.readthedocs.io/en/stable/tables/t_data_quality/>) was read, listing NO2 1 h fixed measurements as 30 ug/m3 / 15 %. So the 15 % rests on 2008/50/EC and is consistent with, but not confirmed by, the recast |
| `wind_speed` (m/s) | Calma-ventolina 0-1.5, Brisa ligera 1.6-3.3, Brisa gentil-moderada 3.4-7.9, Brisa fresca o más 8.0-40 | 0.5, 0.5, 0.79 m/s | Beaufort forces 0-1, 2, 3-4, 5 or more; low wind is associated with weaker dispersion of near-surface emissions, so higher NO2 at low wind is plausible (an association the model may or may not find) | **WMO-No. 8 (CIMO Guide) Part I Chapter 5**, preliminary 2018 edition PDF (<https://old.wmo.int/extranet/pages/prog/www/IMOP/publications/CIMO-Guide/Prelim_2018_ed/8_I_5_en_MR_tc.pdf>), text extracted and read: Beaufort table with m/s ranges (0.3-1.5, 1.6-3.3, 3.4-5.4, 5.5-7.9, 8.0-10.7 for forces 1-5) and "a required measurement uncertainty for horizontal speed of 0.5 m/s below 5 m/s and better than 10 % above 5 m/s is usually sufficient" (shoulders: 0.5 m/s, and 10 % of 7.9 = 0.79). The preliminary edition, not the current one, was read. AEMET's Spanish table was not found; the Spanish names are my translation. Beaufort speeds are 10-min means at 10 m; the Madrid values are hourly station readings with unchecked height and exposure |
| `valid_hour_local` (h) | Noche 0-6, Punta de mañana 7-9, Mediodía 10-16, Tarde-noche 17-23 | 1 h (crisp on whole hours) | day periods read from the 2023 traffic profile (table below) | no external source; computed from the AT-012 table, training year only. Four terms, not five, on purpose (observation 10 in section 9). Midnight wrap: a trapezoid cannot wrap, so Tarde-noche ends at 23 and Noche starts at 0; the flip between 23 and 0 is crisp by construction |
| `valid_weekday` | Laborable 0-4, Sábado 5, Domingo 6 | 1 day (crisp) | calendar day types; holidays are not encoded (a holiday counts as the weekday it falls on) | calendar convention |
| `temperature`, `relative_humidity` | Low / Medium / High, **data-driven** | n/a | no citable categorical scheme for hourly outdoor air was found (ASHRAE 55 is for indoor thermal comfort; AEMET warning thresholds are daily and regional); nothing was invented | searched, nothing defensible; the terms are ex_fuzzy trapezoids anchored at the 20/40/60/80 % quantiles of the training rows, as in AT-041c. The brief suggested terciles; the quantile trapezoids were kept so that the comparison with AT-041c isolates what changed |
| `traffic_intensity_last`, `traffic_intensity_lag24h` (veh/h) | Low / Medium / High, **data-driven** | n/a | no official band for street-segment counts | quantile trapezoids on the pooled training rows of all stations. The brief preferred per-station terciles or values relative to each station's normal; a per-station variable cannot be one linguistic variable without adding a derived input, so pooled terms were used (station differences in magnitude mix with within-station variation) |

Caveats on the NO2 shoulders. (1) The legal 15 % applies "in the region of the limit value" (200 ug/m3 for the hourly
NO2 limit); the ICA breakpoints 40, 90 and 120 are well below it, where real instrument uncertainty is relatively
larger, so 15 % is an assumption, not a measured uncertainty of the Madrid stations. (2) The recast reportedly gives
"15 % or 30 ug/m3 absolute"; the absolute figure would make the shoulder at 40 five times wider and was not used.
(3) The term "Desfavorable o peor" is the merged class 121-1000 of the AT-041c merge rule; the experiment refuses the
partition if the target scheme used is not exactly these four classes.

Training-period traffic profile behind the hour terms (AT-012 table, 2023 issue times, local hour of the counted hour,
`traffic_intensity_last` divided by the station's own mean over the year, mean over the stations with traffic; the
station mean is 1.0 by construction):

| local hour of the traffic hour | workday | weekend |
|---|---|---|
| 0 | 0.44 | 0.67 |
| 1 | 0.27 | 0.54 |
| 2 | 0.18 | 0.41 |
| 3 | 0.15 | 0.32 |
| 4 | 0.14 | 0.28 |
| 5 | 0.19 | 0.27 |
| 6 | 0.49 | 0.36 |
| 7 | 1.05 | 0.40 |
| 8 | 1.64 | 0.46 |
| 9 | 1.67 | 0.63 |
| 10 | 1.38 | 0.86 |
| 11 | 1.40 | 1.08 |
| 12 | 1.45 | 1.23 |
| 13 | 1.51 | 1.33 |
| 14 | 1.66 | 1.31 |
| 15 | 1.60 | 0.97 |
| 16 | 1.48 | 0.87 |
| 17 | 1.63 | 1.00 |
| 18 | 1.71 | 1.13 |
| 19 | 1.69 | 1.20 |
| 20 | 1.50 | 1.21 |
| 21 | 1.20 | 1.10 |
| 22 | 0.88 | 0.87 |
| 23 | 0.65 | 0.67 |
p25/p50/p75 workday: [0.48, 1.39, 1.6] stations 22 rows 192219


Reading: night is the run of hours below 0.5 of the station mean (hours 0-6: 0.44 ... 0.49 on workdays); the morning
rush is hours 7-9 (7 is the ramp at 1.05, 8 and 9 are 1.64 and 1.67; the p75 of the 24 workday values is 1.60); the
evening rush is 17-19 (1.63-1.71); hours 10-16 are a plateau of 1.38-1.66; after 19 the profile declines to 0.65 at 23.
The evening term (17-23) contains the rush and the decline. Weekend profiles differ (no morning rush) and are not
modelled; the weekday term only separates Mon-Fri / Sat / Sun. The profile describes the training year; it is not a
validated driver of NO2.

## 2. Partition comparison (validation 2024 only)

**Validation 2024, chosen shape per scheme, mean ± sd over the seeds (sd with n-1)**

| scheme | nRules / nAnts | macro-F1 | bal-acc | acc | MAE idx | unknown | rules kept | mean length | duplicates | rules winning >= 1 % | Jaccard rules | Jaccard antecedents |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| quantile | 60 / 3 | 0.346 ± 0.007 | 0.437 ± 0.017 | 0.740 ± 0.013 | 0.290 ± 0.013 | 0.0011 | 16.0 | 1.65 | 0.0 | 10.0 | 0.118 | 0.143 |
| ica_no2 | 30 / 4 | 0.312 ± 0.018 | 0.424 ± 0.055 | 0.655 ± 0.070 | 0.390 ± 0.095 | 0.0013 | 10.7 | 1.82 | 0.0 | 7.0 | 0.087 | 0.087 |
| justified | 60 / 4 | 0.336 ± 0.011 | 0.399 ± 0.045 | 0.731 ± 0.018 | 0.304 ± 0.044 | 0.0002 | 13.7 | 1.69 | 0.0 | 7.7 | 0.151 | 0.216 |

**Per-class validation recall and precision (mean ± sd over the seeds)**

| scheme | metric | Buena | Razonablemente buena | Regular | Desfavorable o peor |
|---|---|---|---|---|---|
| quantile | recall | 0.819 ± 0.027 | 0.373 ± 0.055 | 0.410 ± 0.034 | 0.148 ± 0.067 |
| quantile | precision | 0.889 ± 0.004 | 0.325 ± 0.018 | 0.099 ± 0.021 | 0.016 ± 0.004 |
| ica_no2 | recall | 0.706 ± 0.105 | 0.419 ± 0.092 | 0.365 ± 0.139 | 0.206 ± 0.118 |
| ica_no2 | precision | 0.888 ± 0.020 | 0.255 ± 0.022 | 0.071 ± 0.026 | 0.023 ± 0.008 |
| justified | recall | 0.804 ± 0.028 | 0.395 ± 0.089 | 0.329 ± 0.177 | 0.069 ± 0.049 |
| justified | precision | 0.883 ± 0.016 | 0.323 ± 0.012 | 0.087 ± 0.027 | 0.014 ± 0.003 |

**Shape selection, one fit (seed 0), validation, best first within each scheme**

| scheme | nRules / nAnts | rules kept | macro-F1 | bal-acc | acc |  |
|---|---|---|---|---|---|---|
| quantile | 60 / 3 | 16 | 0.354 | 0.457 | 0.733 | chosen |
| quantile | 30 / 2 | 12 | 0.342 | 0.460 | 0.714 |  |
| quantile | 60 / 3 | 21 | 0.340 | 0.386 | 0.743 |  |
| quantile | 60 / 4 | 16 | 0.339 | 0.456 | 0.678 |  |
| quantile | 30 / 4 | 13 | 0.334 | 0.428 | 0.712 |  |
| quantile | 60 / 2 | 14 | 0.334 | 0.454 | 0.729 |  |
| quantile | 30 / 3 | 9 | 0.333 | 0.437 | 0.677 |  |
| quantile | 60 / 2 | 14 | 0.331 | 0.411 | 0.729 |  |
| quantile | 30 / 3 | 13 | 0.330 | 0.329 | 0.786 |  |
| quantile | 60 / 4 | 27 | 0.329 | 0.405 | 0.722 |  |
| quantile | 15 / 2 | 11 | 0.329 | 0.423 | 0.677 |  |
| quantile | 30 / 3 | 12 | 0.327 | 0.452 | 0.688 |  |
| quantile | 15 / 3 | 9 | 0.322 | 0.455 | 0.672 |  |
| quantile | 30 / 4 | 15 | 0.321 | 0.411 | 0.685 |  |
| quantile | 30 / 2 | 16 | 0.314 | 0.385 | 0.731 |  |
| quantile | 15 / 3 | 10 | 0.314 | 0.371 | 0.721 |  |
| quantile | 15 / 2 | 9 | 0.313 | 0.391 | 0.680 |  |
| quantile | 30 / 3 | 11 | 0.311 | 0.312 | 0.779 |  |
| quantile | 15 / 4 | 10 | 0.310 | 0.319 | 0.615 |  |
| quantile | 30 / 3 | 16 | 0.309 | 0.456 | 0.623 |  |
| quantile | 15 / 4 | 9 | 0.302 | 0.444 | 0.559 |  |
| quantile | 30 / 3 | 13 | 0.287 | 0.455 | 0.591 |  |
| quantile | 30 / 3 | 14 | 0.274 | 0.510 | 0.530 |  |
| ica_no2 | 30 / 4 | 9 | 0.332 | 0.361 | 0.728 | chosen |
| ica_no2 | 60 / 4 | 13 | 0.324 | 0.483 | 0.735 |  |
| ica_no2 | 30 / 2 | 9 | 0.317 | 0.354 | 0.773 |  |
| ica_no2 | 30 / 3 | 13 | 0.308 | 0.434 | 0.625 |  |
| ica_no2 | 60 / 3 | 14 | 0.304 | 0.445 | 0.664 |  |
| ica_no2 | 60 / 2 | 18 | 0.304 | 0.487 | 0.599 |  |
| justified | 60 / 4 | 15 | 0.348 | 0.377 | 0.738 | chosen |
| justified | 30 / 2 | 9 | 0.325 | 0.345 | 0.768 |  |
| justified | 30 / 4 | 13 | 0.314 | 0.360 | 0.724 |  |
| justified | 60 / 2 | 10 | 0.297 | 0.356 | 0.747 |  |
| justified | 60 / 3 | 15 | 0.295 | 0.427 | 0.617 |  |
| justified | 30 / 3 | 12 | 0.290 | 0.332 | 0.652 |  |


Selection rule applied as written in section 0: mean validation macro-F1 over 3 seeds is 0.346 (`quantile`), 0.312
(`ica_no2`), 0.336 (`justified`); the best is `quantile` and the tolerance is 0.02. `justified` is first in the
readability order and within 0.010 of the best, so it is the final scheme. `ica_no2` failed on its own (-0.034).

Reading, without over-reading. (1) The differences between schemes are 1-3 seed standard deviations of the
single-scheme runs (sd 0.007-0.018); the ranking `quantile` > `justified` > `ica_no2` is not established beyond the
rule. (2) The cost of ICA terms on the NO2 inputs alone is plausible: 83 % of the rows are in the lowest class, and the
quantile terms split the range below 40 ug/m3 (Low ends at 10-17, Medium at 28-47) where most of the information is,
while an ICA "Buena" term covers all of it. Adding wind, hour and weekday terms restored most of the loss, so part of
the drop in `ica_no2` is the interaction with the remaining quantile terms, which this experiment does not separate.
(3) Readability moved the right way: rule-set Jaccard across seeds 0.151 (rules) and 0.216 (antecedents) against 0.118
and 0.143, no duplicates, 0.0002 share of validation rows with no prediction; the rules winning at least 1 % of the rows
fell from 10 to 7.7 (fewer rules matter). Per-class recall of "Desfavorable o peor" is lower (0.069 against 0.148,
sd 0.05-0.07; 144 validation rows).

## 3. Test results of the final scheme (`justified`, 60 rules x 4 antecedents, 2025, 180,326 complete rows)

Test was read once, in the `final` command, after the shape and the scheme were fixed by validation. Seed 0 is the
published model (highest validation macro-F1 of the three).

**Test overall**

| estimator | macro_f1 | balanced_accuracy | accuracy | mae_class_index | share_off_by_2plus | share_unknown |
|---|---|---|---|---|---|---|
| persistence | 0.294 | 0.294 | 0.769 | 0.244 | 0.012 | 0.000 |
| climatology_majority_class | 0.291 | 0.286 | 0.827 | 0.181 | 0.007 | 0.000 |
| hist_gradient_boosting | 0.373 | 0.396 | 0.845 | 0.163 | 0.006 | 0.000 |
| hist_gradient_boosting_balanced | 0.350 | 0.626 | 0.725 | 0.343 | 0.058 | 0.000 |
| hist_gradient_boosting_regression_binned | 0.414 | 0.406 | 0.836 | 0.166 | 0.002 | 0.000 |
| logistic_regression | 0.303 | 0.295 | 0.839 | 0.168 | 0.007 | 0.000 |
| logistic_regression_balanced | 0.300 | 0.568 | 0.654 | 0.499 | 0.125 | 0.000 |
| random_forest | 0.374 | 0.361 | 0.853 | 0.151 | 0.004 | 0.000 |
| random_forest_balanced | 0.371 | 0.614 | 0.752 | 0.290 | 0.038 | 0.000 |
| hist_gradient_boosting_subsample | 0.383 | 0.493 | 0.798 | 0.223 | 0.018 | 0.000 |
| logistic_regression_subsample | 0.348 | 0.384 | 0.809 | 0.204 | 0.011 | 0.000 |
| logistic_regression_balanced_subsample | 0.300 | 0.562 | 0.654 | 0.497 | 0.123 | 0.000 |
| random_forest_subsample | 0.394 | 0.464 | 0.820 | 0.191 | 0.010 | 0.000 |
| random_forest_balanced_subsample | 0.347 | 0.624 | 0.725 | 0.353 | 0.062 | 0.000 |
| exfuzzy_classifier | 0.329 | 0.374 | 0.746 | 0.269 | 0.014 | 0.001 |

**Validation overall** (same rows as section 2)

| estimator | macro_f1 | balanced_accuracy | accuracy | mae_class_index | share_off_by_2plus | share_unknown |
|---|---|---|---|---|---|---|
| persistence | 0.294 | 0.294 | 0.758 | 0.258 | 0.015 | 0.000 |
| climatology_majority_class | 0.286 | 0.283 | 0.813 | 0.197 | 0.010 | 0.000 |
| hist_gradient_boosting | 0.376 | 0.372 | 0.849 | 0.158 | 0.006 | 0.000 |
| hist_gradient_boosting_balanced | 0.375 | 0.603 | 0.740 | 0.320 | 0.050 | 0.000 |
| hist_gradient_boosting_regression_binned | 0.396 | 0.386 | 0.839 | 0.164 | 0.003 | 0.000 |
| logistic_regression | 0.279 | 0.277 | 0.822 | 0.188 | 0.009 | 0.000 |
| logistic_regression_balanced | 0.313 | 0.550 | 0.658 | 0.480 | 0.114 | 0.000 |
| random_forest | 0.347 | 0.337 | 0.849 | 0.156 | 0.005 | 0.000 |
| random_forest_balanced | 0.396 | 0.570 | 0.765 | 0.270 | 0.032 | 0.000 |
| hist_gradient_boosting_subsample | 0.405 | 0.490 | 0.806 | 0.213 | 0.016 | 0.000 |
| logistic_regression_subsample | 0.339 | 0.357 | 0.795 | 0.218 | 0.012 | 0.000 |
| logistic_regression_balanced_subsample | 0.313 | 0.544 | 0.658 | 0.478 | 0.112 | 0.000 |
| random_forest_subsample | 0.419 | 0.458 | 0.823 | 0.188 | 0.009 | 0.000 |
| random_forest_balanced_subsample | 0.370 | 0.614 | 0.737 | 0.330 | 0.053 | 0.000 |
| exfuzzy_classifier | 0.348 | 0.377 | 0.738 | 0.275 | 0.012 | 0.001 |

**Per-class recall on test**

| estimator | Buena (n=151101) | Razonablemente buena (n=27776) | Regular (n=1368) | Desfavorable o peor (n=81) |
|---|---|---|---|---|
| persistence | 0.864 | 0.291 | 0.020 | 0.000 |
| climatology_majority_class | 0.952 | 0.192 | 0.000 | 0.000 |
| hist_gradient_boosting | 0.922 | 0.471 | 0.029 | 0.160 |
| hist_gradient_boosting_balanced | 0.761 | 0.539 | 0.514 | 0.691 |
| hist_gradient_boosting_regression_binned | 0.895 | 0.554 | 0.102 | 0.074 |
| logistic_regression | 0.975 | 0.142 | 0.024 | 0.037 |
| logistic_regression_balanced | 0.706 | 0.387 | 0.364 | 0.815 |
| random_forest | 0.943 | 0.404 | 0.012 | 0.086 |
| random_forest_balanced | 0.791 | 0.553 | 0.583 | 0.531 |
| hist_gradient_boosting_subsample | 0.852 | 0.530 | 0.308 | 0.284 |
| logistic_regression_subsample | 0.906 | 0.316 | 0.115 | 0.198 |
| logistic_regression_balanced_subsample | 0.704 | 0.391 | 0.362 | 0.790 |
| random_forest_subsample | 0.890 | 0.474 | 0.232 | 0.259 |
| random_forest_balanced_subsample | 0.767 | 0.511 | 0.515 | 0.704 |
| exfuzzy_classifier | 0.801 | 0.484 | 0.074 | 0.136 |

**Per-class precision on test**

| estimator | Buena | Razonablemente buena | Regular | Desfavorable o peor |
|---|---|---|---|---|
| persistence | 0.866 | 0.288 | 0.019 | 0.000 |
| climatology_majority_class | 0.858 | 0.417 | 0.000 | 0.000 |
| hist_gradient_boosting | 0.903 | 0.518 | 0.149 | 0.022 |
| hist_gradient_boosting_balanced | 0.950 | 0.355 | 0.053 | 0.015 |
| hist_gradient_boosting_regression_binned | 0.917 | 0.477 | 0.289 | 0.105 |
| logistic_regression | 0.856 | 0.499 | 0.254 | 0.036 |
| logistic_regression_balanced | 0.919 | 0.305 | 0.024 | 0.008 |
| random_forest | 0.893 | 0.546 | 0.444 | 0.101 |
| random_forest_balanced | 0.942 | 0.373 | 0.075 | 0.025 |
| hist_gradient_boosting_subsample | 0.925 | 0.417 | 0.098 | 0.015 |
| logistic_regression_subsample | 0.879 | 0.392 | 0.116 | 0.019 |
| logistic_regression_balanced_subsample | 0.919 | 0.302 | 0.024 | 0.008 |
| random_forest_subsample | 0.910 | 0.449 | 0.134 | 0.025 |
| random_forest_balanced_subsample | 0.942 | 0.355 | 0.058 | 0.011 |
| exfuzzy_classifier | 0.896 | 0.317 | 0.052 | 0.015 |

**Confusion matrix of the ExFuzzy classifier on test**

| observed \ predicted | Buena | Razonablemente buena | Regular | Desfavorable o peor | no_prediction |
|---|---|---|---|---|---|
| **Buena** | 121,047 | 28,445 | 1,082 | 453 | 74 |
| **Razonablemente buena** | 13,333 | 13,449 | 767 | 196 | 31 |
| **Regular** | 640 | 540 | 101 | 87 | 0 |
| **Desfavorable o peor** | 51 | 16 | 3 | 11 | 0 |

### 3.1 Seeds

| seed | rules | val macro-F1 | test macro-F1 | test bal-acc | test acc | test MAE idx | test unknown | fit s |
|---|---|---|---|---|---|---|---|---|
| 0 | 15 | 0.348 | 0.329 | 0.374 | 0.746 | 0.269 | 0.001 | 133 |
| 1 | 15 | 0.329 | 0.313 | 0.450 | 0.698 | 0.379 | 0.000 | 98 |
| 2 | 11 | 0.331 | 0.330 | 0.386 | 0.764 | 0.262 | 0.000 | 105 |
| mean ± sd |  | 0.336 ± 0.010 | 0.324 ± 0.010 | 0.403 ± 0.041 | 0.736 ± 0.034 | 0.303 ± 0.066 | 0.000 ± 0.001 |  |

The seed with the highest validation macro-F1 (0) is also the second-best on test; the mean row is the fairer summary.
AT-041c, same protocol: validation 0.346 +- 0.007, test 0.332 +- 0.004 (seeds 0.336, 0.329, 0.330). Recall of
"Desfavorable o peor" on test (81 rows) for the published seed is 0.14 (AT-041c: 0.35) and of "Regular" 0.07 (0.27).

### 3.2 Comparison with the baselines (new: logistic regression, random forest)

* ExFuzzy `justified` beats persistence (0.294) and climatology (0.291) on macro-F1 (0.329) and is below every other
  model family except the logistic-regression variants fitted on all rows or class-balanced (0.300-0.303): HGB 0.373, HGB regression binned
  0.414, random forest 0.374 (all rows) and 0.394 (30,000-row subsample), logistic regression 0.348 on the subsample.
  On the identical 30,000 rows, the fuzzy classifier (0.329) is below HGB (0.383), RF (0.394) and LR (0.348).
* The class-balanced variants (HGB, RF, LR) recall the rare classes much better (Desfavorable o peor: LR balanced 0.79-0.82,
  RF balanced 0.53-0.70, HGB balanced 0.69, ExFuzzy 0.14) and pay with precision of 0.8-2.5 % and a lower accuracy
  (0.65-0.75). Higher balanced accuracy is not a better forecaster of the upper classes; precision there is poor for
  every model.
* Logistic regression gets the raw `valid_hour_local` and `valid_weekday` as linear numbers, a weak encoding of cyclic
  inputs; that is a limitation of the baseline as specified, not a statement about linear models. Random forest on
  all rows uses 300 trees, `min_samples_leaf` 20 and a bootstrap draw of 100,000 rows per tree (an unlimited draw
  would hold about 2 GB of trees); the subsample variant draws from the 30,000 rows. LR standardises with the fitting
  rows only. Both are single fits (no seed variability reported; RF `random_state` fixed).
* The ExFuzzy classifier remains the only model whose decision can be read as 15 rules; it is not competitive in accuracy.

## 4. Readability and the final rules

| readability metric (published seed) | value |
|---|---|
| rules | 15 |
| rules for Buena | 4 |
| rules for Razonablemente buena | 6 |
| rules for Regular | 3 |
| rules for Desfavorable o peor | 2 |
| mean rule length (antecedents) | 2.13 |
| duplicate rules (same antecedents) | 0 |
| antecedent sets used with more than one class | 0 |
| rules that win at least one validation row | 15 |
| rules that win at least 1 % of validation rows | 8 |
| share of validation rows with no prediction | 0.0005 |
| share of test rows with no prediction | 0.0006 |
| Jaccard of rules across seeds (mean over pairs) | 0.151 |
| Jaccard of antecedent sets across seeds | 0.216 |

Rules of the published model (seed 0). Weights are dominance scores on the class-tempered 30,000-row sample: only their
order decides between rules; they are not probabilities or importances. "Validation rows decided" is the share of
validation rows whose winning rule it is.

| rule | text | validation rows decided | of those, observed class equal |
|---|---|---|---|
| R01 | IF no2_lag3h IS Buena ∧ valid_hour_local IS Noche THEN ICA = **Buena** (peso 0.11) | 18.2 % | 0.87 |
| R02 | IF no2_lag3h IS Buena ∧ no2_lag24h IS Buena ∧ wind_speed IS Brisa ligera THEN ICA = **Buena** (peso 0.13) | 24.8 % | 0.92 |
| R03 | IF no2_last IS Buena ∧ no2_lag24h IS Buena ∧ temperature IS High THEN ICA = **Buena** (peso 0.092) | 8.5 % | 0.85 |
| R04 | IF no2_lag3h IS Buena ∧ valid_hour_local IS Mediodía THEN ICA = **Buena** (peso 0.12) | 21.9 % | 0.90 |
| R05 | IF no2_last IS Regular ∧ no2_lag1h IS Regular ∧ no2_lag24h IS Buena THEN ICA = **Razonablemente buena** (peso 0.0015) | 0.0 % | 1.00 |
| R06 | IF no2_last IS Buena THEN ICA = **Razonablemente buena** (peso 0.046) | 18.1 % | 0.31 |
| R07 | IF valid_hour_local IS Punta de mañana THEN ICA = **Razonablemente buena** (peso 0.035) | 2.2 % | 0.51 |
| R08 | IF valid_hour_local IS Noche THEN ICA = **Razonablemente buena** (peso 0.018) | 3.4 % | 0.25 |
| R09 | IF no2_lag1h IS Razonablemente buena ∧ no2_lag24h IS Buena ∧ relative_humidity IS High THEN ICA = **Razonablemente buena** (peso 0.013) | 0.9 % | 0.52 |
| R10 | IF temperature IS Medium ∧ relative_humidity IS High THEN ICA = **Razonablemente buena** (peso 0.0073) | 0.2 % | 0.46 |
| R11 | IF no2_lag24h IS Buena ∧ temperature IS Medium THEN ICA = **Regular** (peso 0.0019) | 0.0 % | 0.12 |
| R12 | IF no2_lag3h IS Razonablemente buena ∧ temperature IS Low ∧ relative_humidity IS High ∧ valid_weekday IS Laborable THEN ICA = **Regular** (peso 0.00064) | 0.1 % | 0.01 |
| R13 | IF no2_last IS Razonablemente buena ∧ relative_humidity IS Medium THEN ICA = **Regular** (peso 0.0034) | 1.5 % | 0.12 |
| R14 | IF relative_humidity IS Low THEN ICA = **Desfavorable o peor** (peso 0.0036) | 0.2 % | 0.01 |
| R15 | IF no2_last IS Regular ∧ temperature IS Low THEN ICA = **Desfavorable o peor** (peso 0.00081) | 0.0 % | 0.00 |

How to read them. The classifier is winner-takes-all over `association = firing x weight`, so a rule is not a
statement that holds on its own: "IF no2_last IS Buena THEN ICA = Razonablemente buena" (R06) does not say that a clean
hour implies a moderate one; it wins the validation rows where no Buena rule is stronger, and agrees with the observed
class in 31 % of them. Seven of the 15 rules (R01, R02, R04, R05, R06, R07, R08) use only the justified variables
and decide 88.6 % of the validation rows; the other eight use the data-driven temperature or humidity terms
(`temperature IS Medium`, `relative_humidity IS Low`) and carry the rare classes: the two rules for "Desfavorable o peor"
agree with the observed class in 1 % and 0 % of the rows they decide, and those for "Regular" in 1-12 %. They should
not be presented as explanations. The justified wind terms are used once (R02, "Brisa ligera" together with low NO2 in
the previous hours predicts Buena); the model does not use low wind to flag high NO2.

### Linguistic terms of the published model

| feature | unit | term | type | parameters |
|---|---|---|---|---|
| no2_last | ug/m3 | Buena | trapezoidal | 0, 0, 40, 46 |
| no2_last | ug/m3 | Razonablemente buena | trapezoidal | 35, 41, 90, 103.5 |
| no2_last | ug/m3 | Regular | trapezoidal | 77.5, 91, 120, 138 |
| no2_last | ug/m3 | Desfavorable o peor | trapezoidal | 103, 121, 1000, 1000 |
| no2_lag1h | ug/m3 | Buena | trapezoidal | 0, 0, 40, 46 |
| no2_lag1h | ug/m3 | Razonablemente buena | trapezoidal | 35, 41, 90, 103.5 |
| no2_lag1h | ug/m3 | Regular | trapezoidal | 77.5, 91, 120, 138 |
| no2_lag1h | ug/m3 | Desfavorable o peor | trapezoidal | 103, 121, 1000, 1000 |
| no2_lag3h | ug/m3 | Buena | trapezoidal | 0, 0, 40, 46 |
| no2_lag3h | ug/m3 | Razonablemente buena | trapezoidal | 35, 41, 90, 103.5 |
| no2_lag3h | ug/m3 | Regular | trapezoidal | 77.5, 91, 120, 138 |
| no2_lag3h | ug/m3 | Desfavorable o peor | trapezoidal | 103, 121, 1000, 1000 |
| no2_lag24h | ug/m3 | Buena | trapezoidal | 0, 0, 40, 46 |
| no2_lag24h | ug/m3 | Razonablemente buena | trapezoidal | 35, 41, 90, 103.5 |
| no2_lag24h | ug/m3 | Regular | trapezoidal | 77.5, 91, 120, 138 |
| no2_lag24h | ug/m3 | Desfavorable o peor | trapezoidal | 103, 121, 1000, 1000 |
| wind_speed | m/s | Calma-ventolina | trapezoidal | 0, 0, 1.5, 2 |
| wind_speed | m/s | Brisa ligera | trapezoidal | 1.1, 1.6, 3.3, 3.8 |
| wind_speed | m/s | Brisa gentil-moderada | trapezoidal | 2.9, 3.4, 7.9, 8.69 |
| wind_speed | m/s | Brisa fresca o más | trapezoidal | 7.21, 8, 40, 40 |
| temperature | degC | Low | trapezoidal | -14.0001, -14.0001, 8.3, 12.5 |
| temperature | degC | Medium | trapezoidal | 8.3, 12.5, 17.7, 24.2 |
| temperature | degC | High | trapezoidal | 17.7, 24.2, 47.9001, 47.9001 |
| relative_humidity | % | Low | trapezoidal | -0.0001, -0.0001, 34, 47 |
| relative_humidity | % | Medium | trapezoidal | 34, 47, 62, 78 |
| relative_humidity | % | High | trapezoidal | 62, 78, 100, 100 |
| valid_hour_local | h | Noche | trapezoidal | 0, 0, 6, 7 |
| valid_hour_local | h | Punta de mañana | trapezoidal | 6, 7, 9, 10 |
| valid_hour_local | h | Mediodía | trapezoidal | 9, 10, 16, 17 |
| valid_hour_local | h | Tarde-noche | trapezoidal | 16, 17, 23, 23 |
| valid_weekday | day | Laborable | trapezoidal | 0, 0, 4, 5 |
| valid_weekday | day | Sábado | trapezoidal | 4, 5, 5, 6 |
| valid_weekday | day | Domingo | trapezoidal | 5, 6, 6, 6 |

## 5. Traffic: with versus without (AT-012 table, 2023 train / 2024 validation / 2025 test)

Question: do `traffic_intensity_last` and `traffic_intensity_lag24h` (veh/h at the street-segment points within 500 m
of the station, previous hour and 25 h earlier) add predictive value for the ICA class at t+6 h?

Design. The AT-012 table covers issue times 2023-01-01 to 2025-12-31, so the split is 2023 / 2024 / 2025 and the
training period shrinks from 918,601 to 174,243 complete rows. The final scheme and shape (`justified`, 60 x 4) are used
in both arms; the experiment config differs only in the two features (`ica2-traffic-without` and `-with`,
`require_columns` makes both arms use the same rows). The same fitting subsample (30,000 rows of the 2023 training
rows, class power 0.5) and budget are used; 3 seeds for ExFuzzy, one fit for every baseline (their fits are deterministic
given the rows: no bootstrap or early stopping in HGB, fixed `random_state` in RF), on the same validation and test rows.
Traffic terms are data-driven quantile terms (section 1).

Treatment of missing traffic. Two stations (28079024 Casa de Campo, 28079058 El Pardo) have no traffic point within
500 m and null traffic in every row; a further 0.2-1.2 % of the rows of each other station-year have a null (an hour with fewer than 3 valid
quarter-hour records, AT-012 coverage table). **Rows with a null in either traffic feature are excluded from both arms**, so the arms see identical rows
(validation 182,374, test 170,158; 24 stations in the joined table, 2 without traffic, 21 with complete test rows). Nothing is imputed and no
traffic is borrowed from another station or the city (as the AT-012 card requires). Consequences: the result says
nothing about the two stations without traffic, and a deployed model with traffic would need the model without traffic
as a fallback there (HGB handles nulls natively, ExFuzzy does not: it answers "no prediction"). Classes of these rows:
train 76.3 / 21.1 / 2.0 / 0.6 %, validation 82.0 / 17.0 / 1.0 / 0.08 %, test 83.3 / 15.9 / 0.8 / 0.05 % (Buena,
Razonablemente buena, Regular, Desfavorable o peor); same merge rule, same four classes.

Rows (identical in both arms): train_full 174,243, train_subsample 30,000, validation 182,374, test 170,158

**Validation** (ExFuzzy: mean ± sd over seeds [0, 1, 2]; baselines: one deterministic fit)

| estimator | arm | macro-F1 | bal-acc | acc | recall Buena | recall Razonablemente buena | recall Regular | recall Desfavorable o peor |
|---|---|---|---|---|---|---|---|---|
| exfuzzy_classifier | without traffic | 0.315 ± 0.015 | 0.414 ± 0.035 | 0.658 ± 0.054 | 0.704 ± 0.077 | 0.455 ± 0.063 | 0.388 ± 0.131 | 0.111 ± 0.057 |
|  | with traffic | 0.306 ± 0.014 | 0.385 ± 0.047 | 0.674 ± 0.014 | 0.739 ± 0.029 | 0.382 ± 0.062 | 0.255 ± 0.169 | 0.162 ± 0.026 |
|  | difference (with - without) | -0.009 | -0.030 | +0.015 | +0.035 | -0.073 | -0.133 | +0.051 |
| hist_gradient_boosting | without traffic | 0.383 | 0.380 | 0.839 | 0.925 | 0.472 | 0.054 | 0.069 |
|  | with traffic | 0.390 | 0.389 | 0.839 | 0.925 | 0.474 | 0.074 | 0.083 |
|  | difference (with - without) | +0.007 | +0.009 | +0.000 | -0.000 | +0.003 | +0.020 | +0.014 |
| random_forest | without traffic | 0.355 | 0.340 | 0.844 | 0.951 | 0.381 | 0.013 | 0.014 |
|  | with traffic | 0.347 | 0.333 | 0.846 | 0.957 | 0.364 | 0.004 | 0.007 |
|  | difference (with - without) | -0.009 | -0.006 | +0.002 | +0.006 | -0.017 | -0.008 | -0.007 |
| hist_gradient_boosting_subsample | without traffic | 0.400 | 0.472 | 0.793 | 0.849 | 0.552 | 0.361 | 0.125 |
|  | with traffic | 0.401 | 0.467 | 0.796 | 0.851 | 0.561 | 0.346 | 0.111 |
|  | difference (with - without) | +0.001 | -0.005 | +0.003 | +0.002 | +0.009 | -0.015 | -0.014 |
| random_forest_subsample | without traffic | 0.408 | 0.438 | 0.813 | 0.890 | 0.475 | 0.324 | 0.062 |
|  | with traffic | 0.407 | 0.429 | 0.817 | 0.896 | 0.470 | 0.296 | 0.056 |
|  | difference (with - without) | -0.001 | -0.008 | +0.004 | +0.006 | -0.005 | -0.027 | -0.007 |

**Test** (ExFuzzy: mean ± sd over seeds [0, 1, 2]; baselines: one deterministic fit)

| estimator | arm | macro-F1 | bal-acc | acc | recall Buena | recall Razonablemente buena | recall Regular | recall Desfavorable o peor |
|---|---|---|---|---|---|---|---|---|
| exfuzzy_classifier | without traffic | 0.307 ± 0.017 | 0.420 ± 0.037 | 0.651 ± 0.065 | 0.688 ± 0.092 | 0.469 ± 0.076 | 0.437 ± 0.085 | 0.088 ± 0.076 |
|  | with traffic | 0.303 ± 0.014 | 0.412 ± 0.042 | 0.669 ± 0.020 | 0.721 ± 0.035 | 0.416 ± 0.068 | 0.275 ± 0.111 | 0.238 ± 0.075 |
|  | difference (with - without) | -0.004 | -0.008 | +0.018 | +0.034 | -0.053 | -0.162 | +0.150 |
| hist_gradient_boosting | without traffic | 0.375 | 0.382 | 0.834 | 0.911 | 0.470 | 0.071 | 0.075 |
|  | with traffic | 0.379 | 0.394 | 0.835 | 0.911 | 0.477 | 0.077 | 0.113 |
|  | difference (with - without) | +0.003 | +0.012 | +0.001 | -0.000 | +0.007 | +0.005 | +0.038 |
| random_forest | without traffic | 0.353 | 0.339 | 0.847 | 0.943 | 0.385 | 0.028 | 0.000 |
|  | with traffic | 0.351 | 0.336 | 0.849 | 0.949 | 0.370 | 0.024 | 0.000 |
|  | difference (with - without) | -0.002 | -0.003 | +0.003 | +0.006 | -0.015 | -0.004 | +0.000 |
| hist_gradient_boosting_subsample | without traffic | 0.376 | 0.460 | 0.783 | 0.833 | 0.547 | 0.337 | 0.125 |
|  | with traffic | 0.381 | 0.474 | 0.788 | 0.836 | 0.559 | 0.313 | 0.188 |
|  | difference (with - without) | +0.005 | +0.014 | +0.005 | +0.003 | +0.013 | -0.024 | +0.062 |
| random_forest_subsample | without traffic | 0.395 | 0.442 | 0.813 | 0.881 | 0.486 | 0.341 | 0.062 |
|  | with traffic | 0.396 | 0.436 | 0.818 | 0.887 | 0.481 | 0.325 | 0.050 |
|  | difference (with - without) | +0.001 | -0.007 | +0.005 | +0.006 | -0.004 | -0.016 | -0.012 |

**Difference with - without traffic, every estimator**

| estimator | val macro-F1 without | val diff macro-F1 | val diff bal-acc | test macro-F1 without | test diff macro-F1 | test diff bal-acc |
|---|---|---|---|---|---|---|
| exfuzzy_classifier | 0.315 | -0.009 | -0.030 | 0.307 | -0.004 | -0.008 |
| hist_gradient_boosting | 0.383 | +0.007 | +0.009 | 0.375 | +0.003 | +0.012 |
| hist_gradient_boosting_balanced | 0.378 | +0.003 | +0.003 | 0.352 | +0.004 | +0.015 |
| hist_gradient_boosting_regression_binned | 0.380 | +0.004 | +0.003 | 0.379 | +0.005 | +0.005 |
| logistic_regression | 0.266 | +0.002 | +0.001 | 0.276 | +0.001 | +0.000 |
| logistic_regression_balanced | 0.292 | +0.001 | +0.004 | 0.280 | +0.000 | +0.008 |
| random_forest | 0.355 | -0.009 | -0.006 | 0.353 | -0.002 | -0.003 |
| random_forest_balanced | 0.383 | +0.005 | +0.002 | 0.364 | +0.004 | +0.001 |
| hist_gradient_boosting_subsample | 0.400 | +0.001 | -0.005 | 0.376 | +0.005 | +0.014 |
| logistic_regression_subsample | 0.343 | -0.003 | -0.004 | 0.348 | -0.006 | -0.006 |
| logistic_regression_balanced_subsample | 0.291 | +0.001 | +0.003 | 0.280 | +0.000 | +0.009 |
| random_forest_subsample | 0.408 | -0.001 | -0.008 | 0.395 | +0.001 | -0.007 |
| random_forest_balanced_subsample | 0.361 | +0.002 | +0.010 | 0.344 | +0.002 | +0.022 |


Reading. The incremental value of traffic is indistinguishable from zero in this setup. ExFuzzy macro-F1 goes from
0.315 +- 0.015 to 0.306 +- 0.014 on validation and from 0.307 +- 0.017 to 0.303 +- 0.014 on test: the change is smaller than
one seed sd, so it is not evidence of harm either (the extra inputs also enlarge the GA search space at the same
budget). The 12 baseline variants move by -0.009 to +0.007 macro-F1 on validation and -0.006 to +0.005 on test, with
no consistent sign; the largest HGB gains are in the rarest class (recall of "Desfavorable o peor" +0.04 to +0.08
on test with 81 rows), which one seed or one year cannot separate from noise. ExFuzzy recall of "Desfavorable o peor"
on test moved from 0.088 +- 0.076 to 0.238 +- 0.075, and that of "Regular" from 0.437 to 0.275, with sd's as large as the
differences. No causal reading: traffic counts at a street segment, the model's inputs already include the last NO2
values and the hour of day, which carry most of the diurnal traffic signal, and the data cover one training year.
Under the rule of section 0 (gain above 0.02 and above two seed sd) the published model stays on the full 2019-2025
table without traffic.

## 6. Contract artifacts

Run directories (model ids `exfuzzy-madrid_no2_h6-ica2-justified-seed<k>`), written by `experiment_class runs`, same
layout as AT-041c: `model.pkl`, `run_manifest.json`, `metrics.json` (all baselines, validation and test), `rules.json`
(contract v0.3 with `target_scheme`, terms with their exact trapezoids), `predictions.parquet`, `SHA256SUMS`:

* `artifacts/madrid_no2_h6/ica2-justified-seed0/` (published seed, highest validation macro-F1), `-seed1`, `-seed2`.

Not published here. The traffic arms and the validation-only comparisons have experiment directories
(`artifacts/madrid_no2_h6/experiments/ica2-*`) but no run directories.

## 7. Reproduce

```bash
export ATLAS_DATA_DIR=.../data ATLAS_ARTIFACTS_DIR=.../artifacts PYTHONPATH=src OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4
PY=python
for E in justified no2; do   # 6 shapes, seed 0, validation only (about 7 min each)
  $PY -m atlas.ml.experiment_class select --config configs/ml/madrid_no2_h6_ica2_${E}_experiment.json
  $PY -m atlas.ml.experiment_class final --validation-only --no-baselines --config configs/ml/madrid_no2_h6_ica2_${E}_experiment.json
done                          # `quantile` is the ica-v1 experiment of AT-041c
$PY -m atlas.ml.report_v2 partitions --scheme quantile=$ATLAS_ARTIFACTS_DIR/madrid_no2_h6/experiments/ica-v1 \
   --scheme ica_no2=.../experiments/ica2-no2 --scheme justified=.../experiments/ica2-justified
CFG=configs/ml/madrid_no2_h6_ica2_justified_experiment.json
$PY -m atlas.ml.experiment_class final --config $CFG     # 3 seeds, all baselines, validation and TEST (read once)
$PY -m atlas.ml.experiment_class runs  --config $CFG     # run directories
for ARM in without with; do
  $PY -m atlas.ml.experiment_class final --config configs/ml/madrid_no2_h6_ica2_traffic_${ARM}_experiment.json \
     --selection $ATLAS_ARTIFACTS_DIR/madrid_no2_h6/experiments/ica2-justified/selection.json
done
$PY -m atlas.ml.report_v2 traffic --without .../experiments/ica2-traffic-without --with .../experiments/ica2-traffic-with
$PY -m atlas.ml.report_class --experiment .../experiments/ica2-justified --run-dir .../ica2-justified-seed0
```

Compute (one process, 4 threads, other agents running on the node): 12 shape fits 14.7 min, 6 validation-only seed
fits 7.4 min, 3 final seeds 5.6 min, 6 traffic seed fits 11.9 min and 1.4 min for the determinism check: 41 min of GA
fits; plus baselines (HGB, LR and RF on 918k rows, about 3 min with the RF; 3 min on the 174k-row traffic rows, twice),
data loading and reports: about 65 min wall in total. Peak RSS of the final run 1.70 GB (the random-forest and HGB
baselines are in memory), 0.9-1.4 GB for the others. The determinism check refitted the AT-041c candidate (60 x 3,
quantile terms) through the new code: the same fit, identical confusion matrix (macro-F1 0.3540476...).

## 8. Risks and limits

* Single training/validation/test year each; 2025 is much cleaner than the training years (Regular 0.8 % of rows against
  2.0-2.3 % in training), the upper classes have 1,368 and 81 test rows. Differences of a few hundredths in macro-F1
  between schemes, or between ExFuzzy and its seed-mates, are within noise.
* The shape was chosen by one fit per shape (seed 0); the chosen shape is the maximum of a noisy ranking (for
  `justified`, 60 x 4 scored 0.348 on seed 0 and 0.336 on average over three seeds).
* The NO2 shoulders rest on a legal uncertainty stated at the limit value; the 2024/2881 text was not read in the
  Official Journal; the wind table is from the preliminary 2018 edition of WMO-No. 8; the hour terms come from one year
  of one traffic dataset; temperature and humidity terms are data-driven and unjustified. Each is recorded in the partitions file.
* Hour and weekday enter the logistic regression as plain numbers (a weak encoding of cyclic inputs).
* The rare-class rules (Regular, Desfavorable o peor) are weak and lean on data-driven terms; do not present them as
  explanations. Cross-seed stability is still low (Jaccard of rules 0.15). Consensus rules, ordinal threshold
  decomposition and trend features are left to the follow-up task.

## 9. Observations for the ex_fuzzy author (3.3.1), numbered after those of AT-041c (docs/ml/madrid_no2_h6_ica.md, section 10)

All checked on the installed package.

10. **Term-index bounds are indexed by antecedent slot, not by feature.** In `FitRuleBase.__init__` the upper bound of the
   term gene of slot `j` is `n_lv_possible[j] - 1` for `j < nAnts` (`vl_antecedent_bounds`), i.e. the number of terms of
   the j-th *feature*, whatever feature the slot ends up holding. With precomputed `linguistic_variables` of unequal
   size, a feature with more terms than the first `nAnts` features can never use its extra terms (checked: five-term
   variables after three-term ones get bound 2); in the other direction the decoder silently clips the index with `min(...)`,
   so the last term of a smaller variable is drawn more often. Atlas works around it by keeping every input at four terms
   or fewer and the four-term NO2 inputs first; the 17-23 h evening term and the late-evening period could not be separate terms.
11. `fuzzyVariable` has no `membership` method, although its class docstring example calls `temp_var.membership([20, 25, 30])`;
   `compute_memberships` or the `membership` of each fuzzy set must be used.
12. Trapezoids with `a == b` or `c == d` are handled by shifting `a` down or `d` up by `1e-4` inside
    `trapezoidal_membership`, so membership at the edge is exactly 1 while the stored parameters stay unshifted; exact and
    useful, but a trapezoid with `a == d` is a special case that is 1 only at that exact value. The partition quantile
    code uses `min - epsilon` instead, which is why the exported AT-041c terms show values such as -0.0001.
13. `n_linguistic_variables` is ignored when `linguistic_variables` are given (the real counts are read from the
    variables), which is fine but not stated in the docstring.
