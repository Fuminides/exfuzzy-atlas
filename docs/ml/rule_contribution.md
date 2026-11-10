# Is a per-rule contribution semantically valid? (AT-044, MAP_EXPERIENCE §4)

**Scope:** `BaseFuzzyRulesRegressor` with `consequent_type="crisp"` (zero-order TSK), ex_fuzzy 3.3.1, the only
family Atlas trains today. Nothing here adds `rule_contribution` to a contract: this is the evidence A0 asked for.

## Result in one paragraph

For this family the prediction is an exact convex combination of the rule consequents,
`ŷ = Σ_r w_r · c_r` with `w_r = f_r / Σ_s f_s` (`f` = *effective* firing, after `rule_mode`). The identity holds to
float precision, in `additive` and `sufficient` mode, so `w_r · c_r` is a **faithful, additive bookkeeping of the
output**. It is **not** the effect of the rule, not a probability, not an importance and not a causal statement. It
can be exposed only under a name that says what it is (e.g. `weighted_consequent_share`, with `w_r` as the
`normalized_weight`), never as "contribution to the prediction" without that qualification, and never in the
fallback case.

## What was verified (numerically, `tests/ml/test_rule_traces.py`, `atlas.explain.tsk_decomposition`)

| Claim | How it was checked | Result |
|---|---|---|
| `Σ_r w_r c_r == model.predict`, `additive` | fitted model, 122 rows incl. two far outside the training domain | max abs error ≤ 1e-9 (test bound); observed ≤ 2.2e-14 |
| same, `sufficient` (tolerance 0.3) | fitted model, same rows | ≤ 1e-9; exactly one rule has `w = 1`, all others `w = 0` |
| `Σ_r w_r = 1` on covered rows | same | to 1e-12 |
| Fallback (nothing fires) | hand-built rule base, and `sufficient` with every firing ≤ tolerance | `w = 0` for all rules, `Σ w c = 0`, prediction = `y_mean`: **the decomposition does not exist**, the output is the training-target mean |
| Many models | 6 seeds × {additive, sufficient tol 0 / 0.3 / 0.8}, 3,762 probe rows per configuration (data rows plus random points up to 50 units outside the data range); ad hoc sweep, the committed test runs 3 seeds × 3 configurations | max abs error 2.1e-14 (additive), 7.1e-15 (sufficient); 287 to 1,266 probe rows fell back to `y_mean`, always reproduced exactly |
| Removing a rule | rule base rebuilt without rule r, re-run through `inference` | `ŷ − ŷ₍₋r₎ = w_r (c_r − ŷ₍₋r₎)` to 1e-9; this differs from `w_r c_r` |

`tsk_decomposition` uses the library's `inference` for the reference and `_apply_rule_mode` for the effective
firing; it never evaluates a membership or a t-norm itself.

## What the quantity means, and what it does not

1. **A share of a weighted average, in output units.** `w_r c_r` sums to the prediction, so it answers "how much of
   the final number is carried by rule r's consequent". It does *not* say how far rule r moves the prediction.
2. **Level, not uplift.** A rule with a large weight and a consequent equal to the prediction contributes a lot of
   "level" and changes nothing: removing it leaves `ŷ` untouched (`c_r = ŷ₍₋r₎` in the identity above). If the UI
   wants "what does this rule change", the exact, library-computed quantity is the leave-one-out difference
   `ŷ − ŷ₍₋r₎ = w_r (c_r − ŷ₍₋r₎)` (re-run `inference` on the rule base without r). It is not additive over rules.
3. **Not a ranking of importance.** Weights depend on the row; a rule can dominate rows that never matter for the
   error. Aggregating `w_r` over a window gives a mean weight, not an importance, and no inference about the
   data-generating process follows (no causality, per AGENTS.md invariant 7).
4. **Firing is not the weight.** `firing_strength` is an absolute degree in [0, 1]; `w_r` is relative to the other
   rules of that row. A rule with firing 0.05 can carry weight 1.0 if it is the only one firing. The map must keep
   saying "activation" for `firing_strength` and must not recolour it as share.
5. **`sufficient` mode is degenerate.** Only the argmax rule has weight 1; the others are 0 whatever their raw
   firing. Ties go to the first rule (numpy `argmax`), so a later duplicate of the winner never speaks. The
   decomposition is exact but says nothing about the second-strongest rule.
6. **Fallback.** When `Σ f ≤ 1e-10` the library returns `y_mean`; there is no rule to credit. Expose it as
   "no rule fired: model returned the training mean" (the trace already has `prediction.fallback_used`), never as a
   zero contribution of every rule.
7. **Duplicate antecedents.** The GA can return several rules with identical antecedents. In `additive` mode they
   fire identically and share one weight pro rata; the *group* behaves as one rule whose consequent is their
   mean. Reporting each duplicate separately is exact but can mislead; report the group.
8. **Clipping.** ex_fuzzy clips the prediction into `[min c, max c]` to remove division noise. For a convex
   combination this changes the value by at most ~1e-15, below the 1e-9 parity tolerance.
9. **Does not apply** to Mamdani (`consequent_type="fuzzy"`): the output is the centroid of a clipped, max-aggregated
   curve, which is not a weighted sum of per-rule numbers. It is not supported by the wrapper anyway.
10. **Not a calibrated or conformal quantity.** No uncertainty is implied.

## Recommendation for A0

* `dominant_rule` stays "argmax of firing" (MAP_EXPERIENCE §4): it is a statement about activation.
* If a `dominant_contributor` / `rule_contribution` is wanted, define it as
  `normalized_weight = effective_firing / Σ effective_firing` plus `weighted_consequent = normalized_weight × consequent`,
  valid only for `family = tsk_zero_order` and `fallback_used = false`, with copy that says "share of the weighted
  average" and the rule text next to it. Do not add it to `RuleTraceEntry` until the UI has a use for it; all inputs
  are already in the trace (`effective_firing`, `consequent` from `rules.json`) so the frontend would only divide,
  but then it would be recomputing model output: prefer to have the backend precompute it from the same function.
* A leave-one-out "effect of the rule" is available at the price of one extra `inference` per rule and row; it is
  the better answer to "what does this rule do to the forecast", but it is a different quantity and should not
  share a name with the share above.
