# Static export: the demo as a fully static site (GitHub Pages)

Format version **1** (`manifest.format_version`). Contract: v0.7 (`SCHEMA_VERSION` 0.7.0); the export changes no contract.
Study behind it: the feasibility study of 2026-11-09 (sizes, Pages limits, what-if), re-checked here against `main` at
registry 0.7.0 (10 tasks, 9 mixture-of-rules classifiers plus the water TSK, NYC +6 h being a winning-rule classifier).

Nothing runs on the site: no API, no inference in the browser. Every response the web needs is either **shipped as the
exact API body** (small responses) or **rebuilt in the browser from columnar shards by a thin builder** (large ones).
The builder reshapes, selects, filters, sums and multiplies numbers that the exporter computed with ex_fuzzy. It never
evaluates a membership function, a t-norm or a rule base.

Two implementations of the builders are kept in step, and they are what the exporter's self-check compares:

* the **reference builder in Python**, `src/atlas/services/static/store.py` (`StaticStore`, a `atlas_api.store.Store`
  that reads an export directory instead of the published models). It is the executable form of this document. When this
  text and that code disagree, the code (which the golden check proves equal to the API) wins and this text is fixed.
* the **web builder in TypeScript** (`apps/web/src/api/static/`, phase 3), a port of the Python one, tested against the
  `golden/` samples.

## 1. Decisions (fixed)

| | |
|---|---|
| Hosting | GitHub Pages, free, static. Site <= 1 GB (Pages limit); target of this export **< ~800 MB**. |
| Data files | gzip-compressed JSON, `*.json.gz`, decompressed in the browser (`DecompressionStream`). The loader checks the gzip magic bytes (`1f 8b`) and decompresses only when they are there, because Pages may or may not add `Content-Encoding: gzip` to `.gz`. |
| Inference | None in the browser. The what-if (¿Y si…?) is precomputed (section 9). |
| Model files | None. No `.pkl`, `.parquet`, `SHA256SUMS`, `publish.json`, `run_manifest.json` or anything that runs a model. The exporter writes through an allow-list (section 11). |
| NYC | NYC TLC-derived zone-hour data may be published; the site carries the credit and the disclaimer already served in `attribution`. |
| tau | The slider grid: 0.05, 0.10, …, 1.00 (20 values). Stories stay at tau = 0.5. |
| Traces | "¿Por qué aquí?" is available for every row of every model (cut order of section 12 if it does not fit). |
| Periods | **Germany is exported for 2025-01-01 00:00 UTC to 2025-03-31 23:00 UTC only** (issue times, inclusive; winter has the most varied NO₂ categories). NYC and water keep their full coverage. The period is a per-task setting of the exporter (`--period`, section 14) and is recorded in the manifest and in each `meta.json.gz`. Nothing outside it is exported: no shard, window, story or what-if instant. Model cards stay as published: their evaluation metrics cover the whole test period and are not recomputed. |
| Contract | No change. `/health` is not exported: the web hides the "API: ok" footer label in static mode. |
| Privacy | No absolute path, host name or e-mail in any exported file; the export fails if one is found (section 11). |

## 2. Conventions

* **Root.** `data/<export_id>/` is the deployable tree (the web fetches `${BASE_URL}data/<export_id>/<path>`). `golden/<export_id>/`
  is test-only and is **not** deployed. `export_id` is 12 hex characters: a hash of the format version, `registry.json`, each
  served model's `SHA256SUMS`, each served model's explanation file and the export parameters. The same inputs give the same id.
* **Instants** are strings `YYYY-MM-DDTHH:MM:SSZ` (UTC), exactly as the API writes them. A *day key* is `YYYY-MM-DD` (UTC).
* **Numbers** are written with Python's shortest round-trip repr, so a double survives JSON unchanged. NaN is written `null`.
  Nothing is rounded: a map value equals the trace value equals the API value.
* **Tolerance of numeric matches** (a what-if grid value, a tau): `|a − b| <= 1e-9 · max(1, |a|, |b|)`, i.e. relative 1e-9 with an
  absolute floor of 1e-9 for values near 0 (`fmt.close`). The same rule decides which grid value a request value is.
* **Null is not 0.** In every column, `null` means missing, with the reason carried alongside; a `0` is a number.
* **Ids in file names** (`model_id`, `task_id`, `entity_id`, input names) match `^[A-Za-z0-9._-]+$`; the exporter fails otherwise.
* **Axes.** Four index spaces recur; all four are listed in `models/<model_id>/meta.json.gz`:
  * **E**: the model's *modelled* entities, in the order they have in `tasks/<task_id>/entities.json.gz` (entities with
    `properties.modelled === false` are not in E; they never have rows).
  * **R**: the rules, in `rules.json` order (`rules[r].rule_id`; `R01…`).
  * **C**: the classes, in `target_scheme.classes` order (classifiers).
  * **P**: the used `(feature, term)` pairs, in order of first appearance in the rules (`meta.mem_pairs`).
* **Missing-reason codes**: `meta.missing_reasons`, the `MissingReason` enum in contract order:
  `["no_observation","invalid_observation","censored","missing_input","prediction_unavailable","not_modelled"]`.
  A column of codes holds the index into that list, or `null`.
* **Row sets.** A model's *rows* are the rows of its `predictions.parquet`: one per (entity, issue time) the model published.
  Rows are grouped in **shards** by key: a UTC day (`2025-03-05`) for a regular task, the single key `all` for an irregular one
  (water). Inside a shard, rows are sorted by (issue time, E index). Every per-row file of a shard (`pred`, `fire`, `mem`) has the
  same row order, so row `i` of `fire` is row `i` of `pred`.
* **Period and the range the web offers.** `meta.period` is `{"from","to"}` (first and last exported issue time) or `null` (the
  whole coverage). `meta.coverage` is the exported range (`full_coverage` ∩ `period`) and **is what the web reads for its timeline,
  date pickers and controls**; `card.coverage` is the model's full coverage as published and must not be used for that.
  The same range per task is in `manifest.tasks[<task_id>].coverage` / `.period`, so the web can read it without loading a model.
* **Regular vs irregular.** `card.coverage.regular === false` is irregular (issue times are sample times). Regular tasks must
  have `step_hours = 1` (the exporter fails otherwise: the input lattice below has 24 slots a day).

## 3. Layout

```
data/<export_id>/
  manifest.json                              plain JSON, small; the only file that is not .json.gz
  files.json.gz                              { "<path>": {"bytes": n, "sha256": "<hex>"} } for every other file
  domains.json.gz                            exact body of GET /domains
  tasks/<task_id>/entities.json.gz           exact body of GET /entities?domain=<d>&task_id=<task_id>
  tasks/<task_id>/summary.json.gz            exact body of GET /summary?task_id=<task_id>   (absent: 404)
  models/<model_id>/card.json.gz             exact body of GET /models/<id>                  (paths redacted, section 11)
  models/<model_id>/rules.json.gz            exact body of GET /models/<id>/rules
  models/<model_id>/importance.json.gz       exact body of GET /models/<id>/importance       (absent: 404)
  models/<model_id>/explanation.json.gz      exact body of GET /models/<id>/explanation      (absent: 404)
  models/<model_id>/meta.json.gz             what the builders need that no API body carries (section 4)
  models/<model_id>/<key>/pred.json.gz       predictions, observed target, published label, deciding rule (section 5)
  models/<model_id>/<key>/fire.json.gz       firing per rule (section 6)
  models/<model_id>/<key>/mem.json.gz        membership per used (feature, term) (section 6)
  inputs/<territory>/<column>/<key>.json.gz  one model input over (hour of day x entity), shared by models (section 7)
  models/<model_id>/inputs/<feature>/all.json.gz   irregular tasks: the same, row-aligned (section 7)
  models/<model_id>/agg/<kind>/<from>.json.gz      window statistics for rule-map and rule-territories (section 8)
  models/<model_id>/stories/<kind>/<from>.json.gz  exact body of GET /rule-stories at tau 0.5, limit 10 (section 8)
  models/<model_id>/whatif/<entity_id>.json.gz     precomputed what-if variants (section 9)
golden/<export_id>/<model_id>.json.gz        request/response samples for the web's parity test (section 13); index.json.gz lists them
work/<export_id>/                            scratch of the exporter (input-sharing decision); never deployed
```

`<key>` is a UTC day for regular tasks and `all` for irregular ones. `<kind>` of a window is `day | week | month | year |
coverage`; `<from>` is the window start as a day key, and `coverage` has the single file `all.json.gz`. A missing shard,
window or entity file means "no data there": the builder answers as the API does (an entity without a row is
`no_observation`; a missing trace row is a 404), never with a 0.

## 4. `meta.json.gz` (one per model)

```jsonc
{
  "format_version": 1,
  "model_id": "...", "task_id": "...", "domain": "air", "territory": "germany",
  "task_type": "classification",                 // registry entry
  "family": "rule_mixture_classifier",           // rules.inference.family
  "data_version": "...", "synthetic": false,
  "target": "no2", "unit": "ug/m3",              // registry (what predictions/observations/series show)
  "target_unit": "ug/m3",                        // run_config.unit: the TracePrediction.unit of a trace
  "horizon_hours": 12,
  "antecedent_order": ["no2_last", "…"],        // input names in the engine's order: the order of feature_values in a trace
  "regular": true, "step_hours": 1,
  "coverage": {"from": "2025-01-01T00:00:00Z", "to": "2025-03-31T23:00:00Z"},   // the EXPORTED range: first / last issue time
  "full_coverage": {"from": "2025-01-01T00:00:00Z", "to": "2025-12-31T10:00:00Z"},   // card.coverage
  "period": {"from": "2025-01-01T00:00:00Z", "to": "2025-03-31T23:00:00Z"},          // null when the whole coverage is exported
  "keys": ["2025-01-01", "…"],                   // shard keys that exist, ascending; ["all"] when irregular
  "entities": ["DEBB001", "…"],                  // axis E
  "rules": ["R01", "…"],                         // axis R
  "classes": ["Good", "…"],                      // axis C ([] for a regressor)
  "decides": true,                               // pred.decided exists (winning-rule classifier or additive TSK)
  "mixture": true,                               // pred.top / pred.tshare exist
  "features": [                                  // the model inputs, in model order
    {"name": "no2_last", "obs_unit": "ug/m3", "trace_unit": "ug/m3", "source_id": "...", "lag_hours": 0.0,
     "input": "inputs/germany/no2_last"}         // base path of the input files (section 7)
  ],
  "mem_pairs": [["no2_last", "Low"], ["…", "…"]],  // axis P
  "inference": { "...": "InferenceSpec exactly as the API puts it in a RuleTrace" },
  "windows": {"day": ["2025-01-01", "…"], "week": ["2024-12-30", "…"], "month": [...], "year": [...], "coverage": true},
  "stories": {"tau": 0.5, "limit": 10},
  "taus": [0.05, 0.1, "…", 1.0],
  "whatif": {"rule": "weekly_wed_12utc", "instants": ["2025-01-01T12:00:00Z", "…"], "steps": 41, "per_entity": true}
  // rule: weekly_wed_12utc | daily_13utc | all_samples (then instants is null); the whole block is null when not exported
}
```

`obs_unit` is what `GET /observations` shows (`feature_spec.json`); `trace_unit` is what a `RuleTrace` shows (the engine's unit
overridden by `feature_spec`). They differ for some inputs, which is why both are stored. `inference` is captured from a
real trace of the model so that `exfuzzy_version` equals what the API reports.

## 5. `pred` shard

```jsonc
{
  "v": 1, "kind": "pred", "model_id": "...", "key": "2025-03-05",
  "t":  ["2025-03-05T00:00:00Z", "…"],     // distinct issue times with at least one row, ascending
  "n":  10412,                              // rows
  "ti": [0, 0, 0, …],                       // per row: index into t
  "ei": [0, 1, 2, …],                       // per row: index into meta.entities (axis E)
  "pred":   [..],   // regressor only: GET /predictions properties.prediction (float | null)
  "plabel": [..],   // classifier only: index into classes of prediction_label | null
  "obs":    [..],   // observed target (float | null)
  "olabel": [..],   // classifier only: index into classes of observed_label | null
  "reason": [..],   // code of the resolved missing_reason of the prediction (null when answered)
  "decided":[..],   // decides=true only: position of decided_by_rule_id | null
  "top":    [..],   // mixture only: position of top_rule_id | null
  "tshare": [..],   // mixture only: top_rule_share | null
  "noref":  [..]    // classifier only, omitted when all 0: 1 when the label is withheld ("no reference level")
}
```

A column that does not apply to the model is **absent**; an absent column is read as all `null`. All columns have length `n`.

`pred`, `plabel`, `reason`, `decided`, `top` and `tshare` are the *resolved* values of `GET /predictions` as the API
computes them (including `decided_by_rule_id` and the `prediction_unavailable` default), so the builder does no resolution.
`obs`/`olabel` are the parquet values. `noref` is `1` where the raw published row has no label and
`missing_reason = prediction_unavailable` (the target had no reference level, `ArtifactStore._no_reference`); a trace
withholds the label there too.

## 6. `fire` and `mem` shards

```jsonc
{"v": 1, "kind": "fire", "n": 10412, "f": [[…n floats|null…], …R arrays…]}   // f[r][i] = firing_strength of rule r in row i
{"v": 1, "kind": "mem",  "n": 10412, "m": [[…n floats|null…], …P arrays…]}   // m[p][i] = membership of pair p in row i
```

`null` marks a row whose inputs are not all present (the published firing is NaN with `missing_input`). The firing is the
published `firing_strength` (the t-norm output, before `rule_mode`). The membership is ex_fuzzy's membership of the input value in
the term, before any modifier. For every model served today `effective_firing = firing_strength`; the exporter refuses a TSK
model with `rule_mode != additive` until a column for it exists.

## 7. Input files

A model input is stored once per distinct column, so models that publish the same column share one file.

* **Regular tasks.** `inputs/<territory>/<column>/<day>.json.gz` = `{"v":1,"kind":"inputs","layout":"lattice","values":[…]}`
  with `values[hour * |E| + e]` for hour 0..23 (UTC) and `e` the E index (`null` = absent or missing). `<column>` is the input name,
  suffixed `-2`, `-3`… when two models of the territory publish a column with the same name but different content (for example
  `valid_hour_local` depends on the horizon). The exporter decides sharing by comparing the columns on their common keys
  (DuckDB `IS DISTINCT FROM`) and **fails rather than merge** a column that differs. `meta.features[i].input` is the base path
  `inputs/<territory>/<column>`; the file is `<base>/<day>.json.gz`.
* **Irregular tasks.** `models/<model_id>/inputs/<feature>/all.json.gz` = `{"v":1,"kind":"inputs","layout":"rows","values":[…n…]}`,
  row-aligned with `models/<model_id>/all/pred.json.gz`. `meta.features[i].input` is `models/<model_id>/inputs/<feature>` and the
  file is `<base>/all.json.gz`.

The value of input `f` for row `i` of a regular pred shard is `values[hour(t[ti[i]]) * |E| + ei[i]]`. A row that exists whose input
is `null` has a missing input; a row that does not exist has no entry at all (that decides `no_observation`).

## 8. Window statistics and stories

`models/<model_id>/agg/<kind>/<from>.json.gz`: the statistics `ArtifactStore` computes for a half-open window `[from, to)`
(`rule_map` aggregates and `rule_territories`), as numbers the builder only sums into mean/frequency/winner share.

```jsonc
{
  "v": 1, "kind": "agg", "model_id": "...",
  "window": {"kind": "week", "from": "2024-12-30T00:00:00Z", "to": "2025-01-06T00:00:00Z"},
  "n_records": [|E| ints],     // records of the entity with issue time in the window (rows)
  "n_valid":   [|E| ints],     // those with all inputs present (firing not NaN)
  "sum":  [|R|*|E| floats],    // [r * |E| + e]: sum of the firing over the n_valid records
  "over": [[|R|*|E| ints] × 20],  // over[k][r * |E| + e]: n_valid records with firing >= taus[k]
  "win":  [|R|*|E| ints]       // winning-rule classifiers only: n_valid records where the rule is is_winner
}
```

Windows are the ones the web offers (`apps/web/src/lib/windows.ts`): the UTC day, the ISO week (Monday start), the UTC month and the
UTC year containing any covered issue time, and the whole coverage `[issued_from_utc, issued_to_utc + step)` when it is at most
366 days (`coverageFits`). The `from` of `day|week|month|year` is a day key. A window of a kind is exported when it overlaps the
coverage; its statistics are the sums over the UTC days of the window that have rows. Every recognised window that overlaps the exported range has its `agg` and `stories` file, **also a window with no rows at all**
(its statistics are zeros; its stories body is the API's own empty `RuleStoriesResponse`), so a missing file only means "not
exported" (a window outside the range). The list is in `meta.windows`.

**Inside a period the windows are the standard ones clipped to it**: `[max(from, period.from), min(to, period.to + step))`. The
web clips `windowFor(kind, …)` to the exported coverage (for the coverage window that is the exported range itself); the response
carries the clipped `time_from_utc`/`time_to_utc` and its statistics cover only exported issue times. The file keeps the name of the
standard window (`week/2024-12-30.json.gz` holds the week of 30 December clipped to 1 January). Without a period nothing is clipped.
A request whose `[from, to)` is not one of these windows (a story's custom window, an arbitrary range) is a
**422** with `detail` "window not precomputed".

`models/<model_id>/stories/<kind>/<from>.json.gz` is the exact `RuleStoriesResponse` for that window at `tau = 0.5`, `limit = 10`.
A request with another `tau` or `limit` is a 422 (the web shows the stories at tau 0.5 and says so).

## 9. What-if

`models/<model_id>/whatif/<entity_id>.json.gz` holds, for one modelled entity, the model's answer to **one input changed at a
time** at the featured instants.

```jsonc
{
  "v": 1, "kind": "whatif", "model_id": "...", "entity_id": "...",
  "at": ["2025-01-01T12:00:00Z", "…"],              // featured instants for which this entity has a complete row
  "grid": {"no2_last": [0.0, 5.0, …, 200.0], …},    // the values tried, per input (sorted, unique)
  "variants": {                                     // variants[at][feature] = S variants, one per grid value
    "2025-01-01T12:00:00Z": {
      "no2_last": {
        "f": [[S floats] × R],                      // firing of each rule when the input takes the grid value
        "m": [[S floats] × Pf],                     // membership of the pairs of that input (meta.mem_pairs with that feature, in order)
        "pred": […], "plabel": […], "decided": […], "top": […], "tshare": […]   // the same output columns as a pred shard (those that apply)
      }
    }
  }
}
```

* **Featured instants** (`meta.whatif.instants`): NYC, every day at 13:00 UTC; Germany (and any other regular territory), every ISO week
  on Wednesday at 12:00 UTC; irregular tasks (water): every sample of the entity. A row with a missing input is excluded.
* **Grid per input**: 41 uniform steps over the variable's `domain` (`rules.variables[].domain`) plus every membership-function
  breakpoint inside the domain (the shape parameters of trapezoidal and triangular terms, the mean of a gaussian one), sorted and
  de-duplicated. A request value must equal a grid value (relative 1e-9); otherwise **422** "value not precomputed" with the nearest
  two. The web's slider snaps to the grid. A request with zero overrides needs no variant. More than one override is a 422
  ("one input at a time in the static demo"). An `at` that is not one of the entity's featured instants is a 422 that names the
  nearest featured instant (the web can offer to go there).
* Everything else in the `ScenarioResponse` is built (section 10, scenarios).
* Not exported: a 2-D grid, free values, rows outside the featured set.

## 10. Request map and builder logic

`ArtifactStore` (`apps/api/atlas_api/artifact_store.py`) is the specification of every algorithm below. The builder differs from it in
**where the numbers come from** (shards instead of Parquet/DuckDB/ex_fuzzy) and in nothing else: same response models, same field
semantics, same null/reason rules, same ordering. Entities always come in the order of `tasks/<task_id>/entities.json.gz` `features`,
unmodelled ones included. `h` = `meta`, `entry` = the registry fields in `meta`.

**Antecedent shape.** Two functions are the only readers of how a rule's antecedent is written (today feature, term and an optional
modifier): `atlas.services.static.extract.antecedent_pairs` (the P axis of `mem`) and `StaticStore._antecedent_traces` (the trace
entries). Contract v0.8 adds an operator to antecedents ("at least / at most", named unions): the exporter then **refuses to export**
(`NotImplementedError`) until those two are extended, instead of writing memberships that mean something else. Everything exact
(`rules.json`, `card.json`, …) passes through as the API serves it, whatever fields it has.

Query-shape validation (the 422s of `apps/api/atlas_api/main.py`: `time` xor `from/to`, `to > from`, window <= 366 days, `tau` only with
`activation_frequency`, `firing_strength` takes `time`) stays in the web's static layer; the builders assume valid queries.

| Web call (`api.*`) | Files | Builder |
|---|---|---|
| `health` | none | not called in static mode (the footer label is hidden) |
| `domains` | `domains.json.gz` | exact |
| `entities(domain, taskId)` | `tasks/<task>/entities.json.gz` | exact |
| `modelCard(id)` / `modelRules(id)` | `models/<id>/card.json.gz` / `rules.json.gz` | exact |
| `importance(id)` / `explanation(id)` | `…/importance.json.gz` / `explanation.json.gz` | exact; missing file = `ApiError(404)` |
| `summary(task)` | `tasks/<task>/summary.json.gz` | exact; missing = 404 |
| `predictions({taskId, time})` | `pred` of the day of `time` | **predictions** |
| `predictions({taskId, from, to})` | `pred` of every key touched by `[from, to)` | **predictions**, latest row per entity |
| `observations(…)` | the same `pred` + one `inputs` file per feature and day | **observations** |
| `ruleMap({metric: firing_strength, time})` | `pred` + `fire` of the day | **rule-map instant** |
| `ruleMap({metric: mean_activation \| activation_frequency, from, to, tau})` | `agg` of the window | **rule-map window** |
| `ruleTerritories({from, to, measure, tau})` | `agg` of the window | **territories** |
| `ruleStories(…)` | `stories/<kind>/<from>` | exact (tau 0.5, limit 10 only) |
| `ruleTrace(entity, model, at)` | `pred`, `fire`, `mem` of the day, `inputs` of each feature, `rules`, `meta` | **trace** |
| `series({taskId, entityId, from, to, cursor})` | `pred` of every key touched | **series** |
| `scenario(body)` | everything of the trace + `whatif/<entity>` | **scenario** |

**Lookup of a row.** For (entity, issue time `t`): shard key = UTC day of `t` (or `all`); `i` = the row with `ei = index of entity` and
`t[ti] = t` (build a map once per shard). `t` outside the shards, or no such row, means the entity has no row at that time.

**predictions.** `ArtifactStore.predictions`, with `rows` taken from the pred shard. For `time`: the rows whose `t` equals it. For a window:
over the shards touched, the rows with `from <= t < to`, keeping for each entity the one with the latest `t`. Per entity:
unmodelled -> `issued=valid=null`, `prediction=null`, `missing_reason=not_modelled`; no row -> same with `no_observation`; else
`issued_at_utc = t`, `valid_at_utc = t + horizon_hours`, `prediction`, `prediction_label = classes[plabel]`, `observed`,
`observed_label = classes[olabel]`, `missing_reason = classes of reason`, `decided_by_rule_id = rules[decided]`, and for a mixture
`top_rule_id = rules[top]`, `top_rule_share = tshare` when the label is not null and `top` is not null. `unit`, `model_id`,
`data_version`, `geometry_support` and `geometry` come from `meta`/`entities`. The response envelope is `PredictionsResponse` with
`issued_at_utc = time` or `time_from_utc/time_to_utc = from/to`, as the store does.

**observations.** `ArtifactStore.observations`. A row exists as above; for each feature the value is the input file's value; `unit` is
`obs_unit`, `source_id` and `lag_hours` come from `meta.features`; `observed_at_utc = t - lag_hours` (null when the value is null);
`missing_reason = no_observation` for a null value; `target = {feature: target, value: obs, unit, observed_at_utc: t + horizon,
missing_reason: no_observation if obs is null}`; `target_label = classes[olabel]`; `quality` warns `"missing input: a, b"` (names in
model order) when any value is null.

**rule-map instant.** `ArtifactStore._compute_rule_map` with `lo = t`, `hi = t + 1 µs`: per entity, `n_records = 1` if a row exists,
`n_valid = 1` if its firing is not null, `value = clamp(firing, 0, 1)`; missing -> `missing_input` (with the `"missing input"` quality
warning) or `no_observation`; unmodelled -> `not_modelled`. `valid_at_utc = t + horizon` when `n_records > 0`.

**rule-map window.** The same function with the window statistics: per (rule, entity) `n_valid`, `mean = sum / n_valid`, and
`activation_frequency = over[k] / n_valid` where `k` is the index of `tau` in `meta.taus` (equal within 1e-9; otherwise a 422). Clamp to
`[0, 1]`. An entity with `n_records = 0` is `no_observation`, with `n_records > 0` and `n_valid = 0` is `missing_input`.

**territories.** `atlas.services.territories.build_territories` (shared with the API) fed with the statistics: for each entity with
`n_records > 0` and each rule, `(n_records, n_valid, sum_firing = sum, n_over = over[k], n_win = win)`. The dominant rule is the argmax of
the chosen measure with `dominant_index` (values within `TIE_TOLERANCE` tie, the lowest position wins; null if the measure is 0 for every
rule). `winner_share` for a family that is not a winning-rule classifier is a 422, as in the store. The constants `TIE_BREAK`,
`DENOMINATORS` and `NOTES` of the response are in `atlas.services.territories` (the web copies them or reads them from a golden sample).

**series.** `ArtifactStore.series_for`: the entity's rows over the shards touched by `[max(from, cursor), to)`, ordered by time, at most
2000 per page (`next_cursor` = the issue time of the 2001st row, else null). Per point: `issued = t`, `valid = t + horizon`,
`observed`, `prediction`, `observed_label`, `predicted_label`, `missing_reason` resolved as in predictions, default `Quality`.
Unknown entity: 404; unmodelled: 404 with the store's detail.

**trace.** Let `row` be the located row, `x_f` the inputs, `fire[r]`, `mem[p]`.

1. Unknown entity: 404. Unmodelled: the `not_modelled` trace (`atlas.services.unmodelled.not_modelled_trace`, from `meta.inference`,
   `meta.target_unit`, `meta.horizon_hours`). No row: 404 `no trace for <entity> at <t>`.
2. `feature_values[f] = {feature, value: x_f, unit: trace_unit, source_id, observed_at_utc: t - lag_hours or null, missing_reason: no_observation if null}`.
3. Any input null: `rules = []`, `prediction = {value: null, unit: target_unit, fallback_used: false, missing_reason: missing_input}`, quality warning
   `"missing input: a, b"`.
4. Otherwise, per rule `r` with `rules[r].antecedents`: `antecedents[a] = {feature, term, membership: mem[p], modifier,
   effective_membership: membership ** modifier (or membership without one)}`; `firing_strength = effective_firing = fire[r]`.
   * TSK: `prediction.value = pred`, `fallback_used = (sum of the firings <= 1e-10)`.
   * Winning-rule classifier: `weight = rules[r].weight`, `association_degree = firing * (1 if inference.rule_weighting == "none" else weight)`;
     `label = classes[plabel]`, `winning_rule_id = rules[decided]`, `fallback_used = no association > 0`.
   * Mixture: `class_weights = rules[r].class_weights`, `class_contributions[c] = W[r][c] * firing`, `class_contributions_centred[c] =
     class_weights_centred[r][c] * firing`; `class_scores[c] = class_bias[c] + sum_r class_contributions[c]` (`class_bias` from `rules.json`);
     `label = classes[plabel]`, `top_rule_id = rules[top]`, `top_rule_share = tshare`, `winning_rule_id = null`,
     `fallback_used = not any(firing > 0)`; `weight` and `association_degree` are null.
   * No label (`prediction_unavailable`): `missing_reason = prediction_unavailable`. When `noref = 1` **and some rule fires** (firing > 0
     for a mixture, association > 0 for a winning-rule classifier: the engine had a class), the label, winner and top rule are withheld
     and the quality warns, with the text of `ArtifactStore._without_reference` (`noref` is also 1 for rows nothing fires on, which
     are not warned about). Feature values follow `meta.antecedent_order`.
5. `valid_at_utc = t + horizon`, `observed = obs`, `observed_label = classes[olabel]`, `observation_ids = []`.

**scenario.** `atlas.services.scenarios.build_scenario` (shared), with `rerun(values)` answered from the what-if variant: the trace
of step 4 for the modified inputs, where `fire` and the `m` memberships of the changed input come from the variant, the other
memberships from the base row, and the outputs (`pred`, `plabel`, `decided`, `top`, `tshare`) from the variant; `noref` is the base
row's. The original is the trace of the row. `validate_overrides` runs first, exactly as in the API.

**Texts the API writes from constants.** The builders must write the API's words, so these are shipped, not copied
(`manifest.texts`, written from the API's own constants; the contract v0.8 changes to them travel with the next export):

| key | used by |
|---|---|
| `tie_break`, `denominators`, `territory_notes` (list), `tie_tolerance` | `RuleTerritoriesResponse.tie_break` / `.denominators` / `.notes`, the tie rule of `dominant_index` |
| `what_if_label` | `ScenarioResponse.label` |
| `what_if_warning` | template of the warning of a modified trace: `.format(features="a, b", label=what_if_label)`, features sorted |
| `override_source_id` | `source_id` of an overridden input |
| `observations_note` | `ObservationsResponse.note` |
| `meta.texts.no_reference_warning` (per classifier) | the warning of a trace whose label is withheld (the API's `_without_reference`, for the model's family) |

Still literals of the web (they are not contract constants; the golden parity test catches a drift): the `"missing input"` rule-map
warning, the `"missing input: a, b"` prefix of observations and traces, `FALLBACK_EPS = 1e-10`, `SERIES_MAX_POINTS = 2000`.

## 11. Safety and privacy

* **Allow-list.** The writer accepts only `*.json.gz` under `data/<export_id>/` plus `manifest.json`, and `*.json.gz` under `golden/`.
  It refuses any other extension and these names regardless of extension: `*.pkl`, `*.pickle`, `*.parquet`, `*.joblib`, `*.npy`,
  `*.pt`, `*.onnx`, `SHA256SUMS`, `publish.json`, `run_manifest.json`, `metrics.json`. Symlinks are refused. After writing, the exporter
  re-walks the tree and fails on any file outside the allow-list or any `.gz` whose decompressed content does not start with `{` or `[`.
* **Redaction.** Exact bodies pass through a redactor: any string containing an absolute local path (`/home/…`, `/Users/…`, `/mnt/…`,
  `/root/…`, `/tmp/…`, `C:\…`) keeps only its last two path components behind `…/`. (The water `card.json` carried the path of a local
  ex_fuzzy worktree in `manifest.hyperparameters.exfuzzy_module_path`.) The redaction is the only difference between an exact
  body and the API's; the golden check applies the same redactor to the API body before comparing.
* **Privacy check.** After writing, **every** file is decompressed and scanned. The export fails if any contains: a path prefix
  (`/home/`, `/Users/`, `/mnt/`, `/root/`, `C:\`), the current user's home directory, this machine's host name, any host name listed in
  the environment variable `ATLAS_PRIVACY_HOSTS` (comma list, kept out of the tree), a university domain, `@gmail`, or anything shaped
  like an e-mail address. The outcome (the checks by name, files scanned, violations = 0) is in `manifest.privacy`.
* **No model files.** Only `atlas.services.static.*` read `model.pkl`, and only to compute memberships and what-if sweeps; the pickle is
  verified against `SHA256SUMS` before it is loaded, and nothing derived from it but numbers is written.

## 12. Size, cuts and the budget

Sizes were measured on a partial export and extrapolated, then confirmed by the full run (the PR reports the real numbers). The budget
is **800 MB** for `data/<export_id>/` (Pages: 1 GB). If a run goes over, cut in this order and record the cut in `manifest.cuts`:

1. tau grid 20 -> {0.25, 0.5, 0.75} (drops `over` to 3 arrays),
2. no `day` windows for the 365-day territories,
3. traces (`mem`) only for a period, the what-if only inside it,
4. coverage 12 -> 6 months,
5. fewer horizons,
6. 6-decimal rounding (breaks bit-exact parity with the API).

The exporter reports sizes per model and per file kind in `manifest.per_model` and `manifest.totals`.

## 13. Manifest, golden samples and the self-check

`manifest.json`:

```jsonc
{
  "format": "exfuzzy-atlas-static", "format_version": 1, "export_id": "…", "created_at_utc": "…",
  "schema_version": "0.7.0", "exfuzzy_version": "3.4.0", "exporter": "atlas.services.static 1",
  "source": {"registry_sha256": "…", "models": {"<model_id>": {"checksums_sha256": "…", "explanation_sha256": "…|null"}}},
  "tasks": {"<task_id>": {"model_id": "…", "domain": "…", "territory": "…", "regular": true, "keys": 90,
                          "coverage": {"from": "…", "to": "…"}, "period": {"from": "…", "to": "…"}}},   // coverage = the exported range
  "base": {"export_id": null, "reused_tasks": []},
  "params": {"taus": […], "stories_tau": 0.5, "stories_limit": 10, "series_max_points": 2000, "missing_reasons": […]},
  "totals": {"files": 0, "bytes": 0, "by_kind": {"pred": 0, …}},
  "per_model": {"<model_id>": {"files": 0, "bytes": 0, "by_kind": {…}}},
  "files_index": {"path": "files.json.gz", "sha256": "…"},
  "golden": {"n_checked": 0, "n_passed": 0, "tolerance": 1e-9, "by_kind": {"predictions": {"n": 0, "ok": 0}, …}, "failures": []},
  "privacy": {"files_scanned": 0, "patterns": […], "violations": 0},
  "cuts": []
}
```

`files.json.gz` lists every other file of `data/<export_id>/` with its size and sha256; the gzip streams are written with a fixed
header (mtime 0), so the same data gives the same hash.

**Self-check.** After writing, the exporter picks N random requests per model and per kind (predictions, observations, rule-map instant
and window, territories, stories, trace, series, scenario) from the real coverage, answers each twice, through `TestClient` over the
real API (`ArtifactStore`) and through `TestClient` over `StaticStore` reading the exported files, and compares the bodies:
strings, integers, booleans and structure **exactly**, floats with relative/absolute tolerance 1e-9 (the contract's `PARITY_TOLERANCE`).
The status code and `detail` of errors are compared too. The outcome goes to `manifest.golden`; any mismatch fails the export.

**Golden samples** (`golden/<export_id>/`, not deployed): for the web's parity test.

* `index.json.gz` = `{"format": 1, "export_id", "n", "kinds": [...], "models": {"<model_id>": {"file": "<model_id>.json.gz", "n": k}}}`.
* `<model_id>.json.gz` = a list of `{"kind", "model_id", "request", "status", "body"}`: `status` is the API's HTTP status (200 for all
  of them today), `body` the API's JSON body after the redactor.
* `kind` is exactly one of the names below (no aliases) and `request` holds the arguments of the matching `api.*` call, with
  camelCase keys as `apps/web/src/api/client.ts` takes them:

| `kind` | `request` | `api.*` |
|---|---|---|
| `predictions` | `{taskId, time}` or `{taskId, from, to}` | `predictions` |
| `observations` | `{taskId, time}` or `{taskId, from, to}` | `observations` |
| `ruleMapInstant` | `{modelId, ruleId, metric: "firing_strength", time}` | `ruleMap` |
| `ruleMapWindow` | `{modelId, ruleId, metric, from, to, tau?}` (`tau` only for `activation_frequency`) | `ruleMap` |
| `ruleTerritories` | `{modelId, from, to, measure, tau}` | `ruleTerritories` |
| `ruleStories` | `{modelId, from, to, tau: 0.5, limit: 10}` | `ruleStories` |
| `ruleTrace` | `{entityId, modelId, at}` | `ruleTrace` |
| `series` | `{taskId, entityId, from, to}` | `series` |
| `scenario` | `{model_id, entity_id, at, overrides}` (the POST body) | `scenario` |

The exporter writes `GOLDEN_KINDS` (in `atlas.services.static.export`) and keeps a few samples of each kind per model
(`golden_n`, 2 by default).

## 14. Running it

```
make export-static PYTHON=~/datasci/bin/python OUT=/path/to/out [PUBLISHED=artifacts/published] [ARGS="--tasks … --only … --groups …"]
python -u -m atlas.services.static.export --published-dir artifacts/published --out OUT [--tasks t,…] [--only t,…] [--groups g,…]
```

* `--tasks` (task ids or model ids) is the content of the export (default: the whole registry; the export id depends on it).
  `--only` restricts one invocation to some of them, so several processes can fill the same `OUT`.
* `--period KEY=FROM,TO` (repeatable) sets the issue-time period of a task, model or territory; `KEY=full` exports the whole coverage.
  Default: `germany=2025-01-01T00:00:00Z,2025-03-31T23:00:00Z` (`fmt.DEFAULT_PERIODS`). The periods are part of the export id.
* `--base <previous data/<export_id>>` re-exports **only what changed**. A task is reused (hard links, else copies) when its model's
  `SHA256SUMS`, its explanation file and its period are the same as in the base manifest and the format, tau grid and `--no-whatif`
  setting match; every other task is exported from scratch. This is the cheap way to re-export one or a few republished models:
  `make export-static ARGS="--base OUT/data/<old id>"` after republishing. The shared `inputs/<territory>/` files are reused only if the
  whole territory is unchanged; otherwise they are rewritten for all the models of the territory (reading each model's inputs), while the
  unchanged models keep their own files. `manifest.base` records the base export id and the reused tasks. `--only t` forces `t` to be
  re-exported even if unchanged; `--groups` limits the work to some file groups of those tasks.
* `--groups` is a comma list of `static` (exact bodies and `meta`; with `--base` it runs for every task, it is cheap), `inputs`,
  `days` (pred/fire/mem), `agg`, `stories`, `whatif` and `finalize` (file index, privacy scan, self-check, manifest); default all.
  Run `finalize` last, once. `--no-whatif` leaves out the what-if. `--check-n N` is the number of random requests per kind and model in the
  self-check (default 3). `--force` rewrites existing files.
* One model, one day at a time, so memory stays bounded (DuckDB `memory_limit` 1 GB, ex_fuzzy in batches of at most 100 000 rows).
  Files are written atomically; a day whose `mem` file exists is skipped.
* The log prints one `[k/N] group=… <task>` line per (group, model), for the machines dashboard.
