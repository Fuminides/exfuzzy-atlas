# ExFuzzy Atlas web (AT-050, AT-053/054 real scale)

Vite + React + TypeScript (`strict`) + MapLibre GL JS. Works against the **mock API** (fixtures, every payload
synthetic, persistent banner) and against the **artifacts API** (`ATLAS_API_MODE=artifacts`, real published models;
the banner appears only when a payload says `synthetic: true`). No deck.gl, no chart library (charts are hand-rolled SVG).

What it shows (spec: `MAP_EXPERIENCE.md`). Since v0.5 (below) the **Rules** and **Data** modes are the two views of the Explorar section and the
**Prediction** mode is the map of the Predicción section:

- **Rules** mode: pick a rule, stations are coloured by the API's `value` (viridis, 0–1 legend, `null` drawn as a
  hollow grey ring labelled "sin dato" plus its `missing_reason`), a visual-emphasis slider, `n_valid` counts, an
  optional window view (`mean_activation`, `activation_frequency` with `tau`), a timeline over issue times and the
  "¿Por qué aquí?" drill-down (`/rule-trace`: inputs, μ per antecedent, firing, t-norm, full prediction, other rules).
- **Rule Duel** (E4, Rules mode, "Duelo de reglas"): rule A is the selected rule, rule B another rule **of the same model**
  (no rule mapping exists between models, so a cross-model duel is not offered). Both `/rule-map` requests are built from one
  parameter set and differ only in `rule_id`. Side by side: two maps with the same 0–1 viridis scale, one shared legend, cameras
  linked. Difference view: `value(A) − value(B)` per entity on a diverging scale centred at 0 ("diferencia de activación (A − B),
  no probabilidad ni contribución"); an entity missing in A or B is missing, never 0. The table lists A, B, A − B and `n_valid`,
  selection is shared with both maps, Up/Down move between entities and Enter selects. Points, polygons and irregular tasks
  (windows only) work the same way.
- **¿Por qué aquí?** for classifiers separates *activación* (how much the rule fires, 0–1), *peso* (dominance score, from the
  training data) and *asociación* (their product, which decides), with one plain sentence for the winner and for the
  strongest-firing loser. The numbers are the trace's; only the words (más/menos, por encima/por debajo) come from comparing them.
- **Prediction** mode: separate title, unit (NO₂ µg/m³) and legend (magma); observed vs predicted series per station.
  It never fetches a full series: per entity it requests a 6-day block of issue times `[block-48h, block+96h)` around
  the selected time (blocks are 48 h wide, so scrubbing inside one costs no request), following `next_cursor`.
  The colour scale only grows while browsing. The legend says whether the selected issue time falls in the train,
  validation or test period of `manifest.split`.
- **Timeline at scale** (8,760 hourly steps): slider, a date-time field (typed in UTC or Europe/Madrid, snapped to the
  nearest issue time, both zones displayed), jump buttons −1 d / −1 h / +1 h / +1 d. Keyboard: PageUp/PageDown = −1 d/+1 d,
  Shift+←/→ = −1 h/+1 h. The slider is debounced (150 ms) before asking the API.
- **Aggregate window selector** (mean_activation / activation_frequency): UTC day, ISO week (Monday start) or month
  containing the selected time, or the whole coverage when it is ≤ 366 days (the API limit). Windows are half-open
  `[from, to)` and the legend states them with the `n_valid` range.
- **Rules at scale** (15–30 rules): searchable rail (text on feature/term/id, plus a feature filter). Rules with
  `duplicate_of` get the badge "mismas condiciones que Rxx (dispara igual)" and are never merged. Each rule shows its
  published `metrics` under their own names (never "importance"/"probability").
- **Linguistic partitions panel**: opens from a rule or from an antecedent in "¿Por qué aquí?". Trapezoidal and
  triangular terms are the polyline of their four params `(a,0) (b,1) (c,1) (d,0)` on the variable's `domain`;
  gaussian terms are listed. The station's input and every μ come from the rule trace (only terms some rule uses
  have a μ there; the others say so).
- **Model panel**: `ModelCard.metrics` as a table (ExFuzzy vs baselines, test split, MAE/RMSE/R², n), split periods from
  `manifest.split`, `manifest.warnings`, `data_version`. Neutral wording: no "best model", no causality.
- Entities with `geometry: null` are listed as "sin geometría" and never drawn.
- **Data** mode (contract v0.4): the observed target per entity at `valid_at` and, for the selected entity, the model's
  inputs with unit, source and observation instant (`/observations`). Own title, legend and a single-hue blue scale;
  a missing value is "sin dato" with its reason, never 0; nothing is interpolated.
- Water and Mobility: honest "planned" placeholders driven by `/api/v1/domains`.
- A station table (keyboard-navigable) is an alternative to the map and selects the same station.

The client never computes memberships, t-norms or firing: it paints what the API returns.

## v0.5 redesign: what is where

The app opens on a **territory selector** (one button per territory, grouped by domain; `TaskInfo.territory`, else one per
task) and four sections, **Resumen | Patrones | Predicción | Explorar**, opening on Resumen. A **horizon** control lists the
territory's tasks by `horizon_hours` (a fixed, explained label when there is one; "Misma muestra" at horizon 0, which is
inference and not a forecast). Every section starts with one plain sentence about what is shown and over which period.

- **Resumen** (`tabs/SummaryTab.tsx`, `/summary`): headline facts, a 100 % stacked bar in the official class colours (or median and
  spread for a numeric variable), a map of the share of hours in the worse classes (median when numeric), small charts by year,
  month, hour and weekday, and a ranking table that is the map's alternative. A group with no data is a labelled gap, never 0.
- **Patrones** (`tabs/PatternsTab.tsx`, `/models/{id}/rules` + `/importance`): variable bars, each rule as a sentence with its
  labels ("Si **NO₂ hace 4 h** es *Buena* → Buena"), how many predictions it decides and how often it is right (or the exact
  weight share and the MAE for TSK), its terms on demand, and "Por zonas". Importance here is **decides and hits**; the page never
  presents an activation as importance. `n_no_rule` and `n_withheld` are said plainly.
- **Predicción** (`tabs/PredictionTab.tsx`): the horizon box with a timeline of the inputs (lags read from the published
  `observed_at_utc`), the existing prediction map, series and "¿Y si…?", and "¿Cuánto acierta?" from the model card.
- **Explorar** (`tabs/ExploreTab.tsx`): the expert tools (rule firing map, territories, duel, stories, data mode); activation
  appears only as "activación (0–1), no es importancia ni probabilidad".
- The two new endpoints answer 404 until a model has its precomputed files: that is the explicit state "no disponible todavía"
  (`hooks/useOptionalAsync.ts`, `components/Card.tsx#NotYet`), not an error.
- Names of inputs come from `variables[].label`; `lib/labels.ts` humanises the feature when it is missing and provides the
  `LabelContext` every component reads, so no raw identifier is on screen. Numbers are es-ES (`lib/format.ts`: `dec`, `pct`).
- Dev against a second API next to a running demo: `ATLAS_API_URL=http://127.0.0.1:8010 npm run dev -- --port 5180`
  (the Vite proxy target, `http://127.0.0.1:8000` by default).

## Static build (GitHub Pages)

The site can be deployed as plain files: no API and no inference in the browser. `VITE_ATLAS_DATA=static` swaps the live
`api` (`src/api/client.ts`) for `staticApi` (`src/api/static/`), which has the same methods and types and answers every
request from the precomputed export of `docs/static_export.md` (`*.json.gz`, decompressed with `DecompressionStream`,
with a byte-bounded LRU). The small bodies are served as they are; the large ones (predictions, observations, rule maps,
territories, series, traces, scenarios) are rebuilt from columnar shards by one builder each, with no membership, t-norm or
rule evaluated.

```bash
VITE_ATLAS_EXPORT_ID=<12 hex> npm run build:static   # base /exfuzzy-atlas/, data under <base>data/<id>/
```

`VITE_ATLAS_DATA_URL` points the data elsewhere; `VITE_BASE` overrides the base. Static mode hides the "API: ok" footer
label, and the controls offer only what the export holds (`meta.json.gz`: its τ grid, window kinds, exported range and
what-if sweeps), so no request comes back unsupported. The ¿Y si…? panel moves one input at a time over the precomputed
grid, at the instants that have a sweep.

Tests: `src/api/static/*.test.ts` run each builder on a hand-written export (`testExport.ts`). The parity test replays the
exporter's golden samples against the builders: `ATLAS_STATIC_EXPORT=<data/id> ATLAS_STATIC_GOLDEN=<golden/id/index.json.gz>
npx vitest run src/api/static/parity.test.ts --maxWorkers=1` (skipped without them).

## Commands (run from `apps/web`)

```bash
npm ci                 # install the pinned dependencies (package-lock.json)

# Dev with the mock API
make api               # in a first terminal, from the REPO ROOT (serves http://127.0.0.1:8000)
npm run dev            # in a second terminal; Vite proxies /api -> http://127.0.0.1:8000

npm run typecheck      # tsc --noEmit (strict)
npm run lint           # eslint, zero warnings allowed
npm test               # vitest + Testing Library; reads ../../fixtures/synthetic/*.json
npm run build          # typecheck + production build into dist/ (git-ignored)
npm run preview        # serve dist/ (also proxies /api to ATLAS_API_URL, default 127.0.0.1:8000)

npm run gen:types      # regenerate src/api/generated/ from src/atlas/contracts/schemas/*.schema.json
```

`src/api/generated/` is committed and produced by `json-schema-to-typescript`; never edit it by hand. After a
contract change, run `make schemas` at the repo root, then `npm run gen:types`, and commit both.

## Configuration (Vite env, optional)

| Variable | Default | Meaning |
|---|---|---|
| `VITE_BASEMAP_STYLE_URL` | `https://tiles.openfreemap.org/styles/positron` | MapLibre style URL for the basemap |
| `VITE_MODEL_ID` | _(unset)_ | Override of the model to explore; by default the one `/api/v1/domains` lists for the task (`tasks[].model_id`) |
| `VITE_API_BASE` | `/api/v1` | API base path |

## Basemap

OpenFreeMap Positron by default (no key; data from OpenStreetMap, ODbL). The attribution
"© OpenStreetMap contributors · OpenFreeMap" is always visible on the map. If the style fails to load (offline,
blocked, bad URL, or no answer in 8 s) the app switches to a plain background, says so on the map, and still draws
the stations. Review OpenFreeMap's terms or serve your own PMTiles before any public deployment (D8).

## Layout of `src/`

- `api/`: typed client (`client.ts`), generated contract types (`generated/`), re-exports (`types.ts`).
- `map/`: `mapLayers.ts` (pure layer specs and the data-driven expression on `properties.value`), `StationMap.tsx`
  (MapLibre wrapper with basemap fallback), `stations.ts` (view model).
- `components/`: legend, station table, rule rail and detail, partitions panel, model panel, timeline, why-here panel,
  series chart, banner. `lib/windows.ts` (aggregate windows, series blocks, split period), `lib/localTime.ts` (date-time
  field zones), `lib/ruleMetrics.ts` (metric labels).
- `tabs/`: the four sections (Summary, Patterns, Prediction, Explore); `lib/labels.ts`, `lib/tasks.ts` (territories and horizons), `lib/summary.ts`, `lib/importance.ts`, `lib/taskText.ts`.
- `Workspace.tsx`: orchestrator of one task's map, rail and timeline (used by Predicción and Explorar) (selected entity, glue between sections, layout); `App.tsx`: domains,
  sections, territory and horizon, footer. Each mode owns its state and requests in a hook (`hooks/useModelContext`, `useTimeWindow`,
  `useDataMode`, `usePredictionMode`, `useRulesMode`, `useRuleDuel`, `useTerritories`, `useRuleStories`,
  `useProvenance`); `lib/mapLayer.ts` turns the answers in hand into the rows and colours the map and table draw.
- `test/`: fixture loader, a fake `fetch` API (`fakeApi.ts`, serves the golden backend rule maps) and a fake MapLibre (no WebGL).

## Real-scale API locally

```bash
# synthetic published model (3 entities, 45 days), from the repo root
make publish-demo && ATLAS_PUBLISHED_DIR=artifacts/published-demo/published make api-artifacts
# real model, when published: ATLAS_API_MODE=artifacts ATLAS_PUBLISHED_DIR=<repo>/artifacts/published make api
cd apps/web && npm run dev
```

Attribution: the footer lists `attribution` as the API states it (`ModelCard.attribution`, else the entities'; v0.4): text,
link and licence, with "no declarada en la fuente" when `license` is null (NYC TLC, the MITECO ICA document). Nothing is
hard-coded per domain any more; `src/lib/domainUi.ts` keeps only the wording (what an entity is called, the NYC level title).

## NYC and Water (AT-052)

- **Polygons.** `Polygon`/`MultiPolygon` entities are drawn with `fill` + `line` layers (`zones-*`) that read the same
  `value`/`label` properties as the circle layers; points keep the circle layers (every circle layer is filtered to `Point`
  because MapLibre also draws circles at polygon vertices). Entities with `geometry: null` stay in the table only.
- **"Sin referencia"** (observed value, no `observed_label`, `prediction_unavailable`, see `isNoReference`) is a hatched
  fill with a dashed outline, never a class colour. Other missing polygons are a pale wash with a grey outline. Zones the API
  has no model for (`modelled: false`, `not_modelled`: NYC serves 263 zones, 153 of them without a model) are drawn light and
  quiet (layers `zones-unmodelled`, `zones-line-unmodelled`, `stations-unmodelled`), never with the missing outline, and
  the legend counts "110 zonas con modelo de 263".
- **Timezone.** Local time is the entities' `properties.timezone` (`ZoneContext`, `lib/zone.ts`); Madrid is only the default
  of the formatters when nothing is provided (tests).
- **Irregular issue times (Water).** `isIrregular` reads `coverage.regular === false` (v0.4). Such tasks get a window navigator instead of the hourly slider, default to
  a monthly `mean_activation`, hide `firing_strength`, show the latest sample of each point in the window in Prediction mode
  and a per-point observed-vs-predicted chart by sample date. "¿Por qué aquí?" first asks for one of the point's samples.
- **Horizon 0** is worded "inferencia sobre la misma muestra (no es un pronóstico)", never "+0 h".
- Golden payloads of the real NYC and Water models: `src/test/fixtures-real/`, saved by `scripts/save-real-fixtures.mjs`
  (source and cuts documented in the script header and in `src/test/fixturesReal.ts`).

## Contract v0.4 views (AT-055/056)

- **Prediction** mode makes one `/predictions` request (an issue `time`, or `from`/`to` for irregular tasks) and loads a
  series only for the selected entity's chart. A new instant never draws the previous answer.
- **Rules > Territorios** (`/rule-territories`, E2): the dominant rule per entity for `mean_activation`,
  `activation_frequency` (with `tau`) or `winner_share` (classifiers only). Categorical rule colours
  (`lib/territories.ts`, own legend, only the rules present) are kept apart from the sequential activation scale
  (the "intensidad de la regla" view, viridis, own legend). The legend states measure, tau, tie-break, `n_valid` and that
  territories overlap; the API's own `tie_break`/`denominators`/`notes` text is under "Texto del criterio".
- **What-if** (`POST /scenarios`, E5, `components/WhatIfPanel.tsx`): edits a copy of one published row within each
  variable's `domain`; the memberships, firing, association, winning rule and prediction shown are the API's. The label
  "respuesta del modelo ante entradas modificadas" is always on screen (the API's own `label` still carries the contract's longer text); the map and the
  dataset never change. A 422 is shown with the API's reason. It opens from Rules mode (below "¿Por qué aquí?") and from
  Prediction mode: with an entity and a time selected, "¿Y si…?" (`components/PredictionWhatIf.tsx`,
  `hooks/useScenarioEntry.ts`) swaps the series for the same panel, prefilled with that entity, time and row, and
  "Volver a la predicción" brings the series back with the selection untouched. A "sin modelo" entity has no entry; for
  irregular tasks the row is the entity's own latest sample in the window.
- **Historias** (`/rule-stories`): the API's text rendered as is; "Reproducir" moves the app to the exact query (rule,
  metric, issue time or window, tau) through `lib/stories.ts`; numbers and checks are listed on demand.
- Test doubles for these endpoints: `src/test/fakeApi.ts` (predictions, observations and territories are derived from the
  fixtures with the backend's rules; stories and the scenario are the backend's `fixtures/synthetic/v04_responses.json`).

## Known limits

- `npm test` uses fixtures: 4 fictional stations, 6 issue times, 3 hand-written rules (plus derived variants for
  scale, null geometry, duplicates and `synthetic: false`). Real-scale checks were done by hand against the artifacts API.
- Rule `metrics` are labelled by key (`mean_activation`, `activation_frequency_tau0.5`, `n_antecedents`; unknown keys are
  shown as they come). That the activation ones were computed on training rows is how the current exporter
  (`atlas.ml.rules_export`) works; the contract does not say so, so the UI does not claim it.
- Predictions of all entities at one time need one request per entity (windowed); an endpoint for that is requested.
- The prediction colour scale is not fixed: it follows the loaded windows and only grows.
- Time handling shows issue time (UTC and the entities' zone) and valid time (issue + horizon) separately; the horizon
  comes from the domain task. Nothing is interpolated between issue times.
- Headless/visual checks were done with Chrome; the unit tests mock MapLibre, so real WebGL rendering is not
  covered by `npm test`.
