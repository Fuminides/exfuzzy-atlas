"""Dissolved oxygen of UK rivers from the same sample, ExFuzzy TSK regressor versus baselines (AT-041f).

::

    C=configs/ml/water_do_chrono_temp_experiment.json
    python -m atlas.ml.experiment_water select --config $C   # validation only
    python -m atlas.ml.experiment_water final  --config $C   # seeds, baselines, test (read once), run directories

A **descriptive same-sample inference** (``valid_at = issued_at``, horizon 0), not a forecast: the dissolved oxygen
of a sample is estimated from ammonia, orthophosphate, temperature, pH, season and time of day measured in that very
sample (``docs/water/water_feasibility.md``). The experiment config picks one of the two splits of AT-021 and one
feature set; the four arms are ``{chrono, spatial} x {with, without} water temperature``.

* ``chrono``: the period split of ``configs/water/uk_water_do.json`` (embargo 30 days). ``spatial``: whole sampling
  points held out (``uk_water_do_spatial_split.json``, an ``entity_id`` mask, every date), the shape of "a point the
  model has never seen".
* The fuzzy regressor is the zero-order TSK of ``atlas.ml.fuzzy`` with the linguistic variables of
  ``configs/ml/water_partitions.json``: ammonia and phosphate get a term exactly for "at or below the detection
  limit L" (the table harmonises every censored result to L) plus data-driven terms *above* L, the season terms
  come from ``days_from_midwinter``, the rest are data-driven quantile terms. All of them are built from the
  *training rows of the split in use*. The fit uses every complete training row (there are only 7-9 thousand).
* Baselines: global mean, point mean (chronological split only; the global mean for points not in train), season-only
  mean, Ridge, random forest and histogram gradient boosting, plus a quadratic in water temperature when the
  temperature is an input. No persistence feature exists, so none is used.
* ``select`` ranks a grid of rule-base shapes on the validation rows by RMSE (ties: fewer rules); ``final`` fits the
  chosen shape with several seeds and scores validation and test once.
"""

from __future__ import annotations

import argparse
import json
import pickle
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from atlas.contracts import models as m
from atlas.ml import artifacts
from atlas.ml.baselines import SklearnBaseline
from atlas.ml.evaluation import PeakRss, interpretability_rows, period_metric_rows, rule_signatures, rule_stability
from atlas.ml.exfuzzy_features import ensure_config, exfuzzy_version, provenance_hyperparameters, provenance_warnings
from atlas.ml.fuzzy import FuzzyParams
from atlas.ml.metrics import regression_metrics
from atlas.ml.partitions import PartitionConfig
from atlas.ml.pipeline import FUZZY, RunConfig, _model_id, _prediction_table
from atlas.ml.rules_export import export_model_rules
from atlas.ml.split import assert_no_temporal_leakage, split_masks
from atlas.ml.water_fuzzy import WaterFuzzyRegressor, load_censored
from atlas.paths import ARTIFACTS_DIR, DATA_DIR, REPO_ROOT

VALIDATION_PREFIX = "validation/"
LOW_DO_MG_L = 8.0  # descriptive slice only: 3.4 % of the rows are below it; not a standard or a class
SEASON_CUTS = (45.5, 137.5)  # days_from_midwinter: winter | spring-autumn | summer (the cores of the season terms)


def _log(text: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {text}", flush=True)


# ---------------------------------------------------------------------------------------------------- config


class WaterSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nRules: list[int]
    nAnts: list[int]
    n_linguistic_variables: int = 3
    n_gen: int
    pop_size: int
    seed: int = 0


class WaterFinal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n_gen: int
    pop_size: int
    seeds: list[int]


class WaterConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str
    table: str  # parquet directory; relative paths resolve against ATLAS_DATA_DIR
    split_kind: str  # "chrono" or "spatial"
    spatial_split_file: str | None = None  # relative to ATLAS_DATA_DIR
    base: RunConfig
    require_columns: list[str] = []  # finite in every arm, so that every arm scores the same rows
    partitions: PartitionConfig  # fixed terms (season); ``censored`` entries of the same file give the limits
    selection: WaterSelection
    final: WaterFinal
    rule_mode: str = "additive"  # "additive" or "sufficient" (ex_fuzzy rule_mode of the TSK regressor)
    unique_antecedents: bool = False  # drop repeated antecedent sets (needs ex_fuzzy PR 30, see exfuzzy_features)
    exfuzzy_source: str | None = None  # provenance of a non-release ex_fuzzy (FX retrain); echoed in manifests
    requires_exfuzzy: list[str] = []  # fixes the experiment needs (atlas.ml.exfuzzy_features.FEATURES); checked at run


def _resolve(table: str) -> Path:
    path = Path(table)
    return path if path.is_absolute() else DATA_DIR / path


# ------------------------------------------------------------------------------------------------------ data


class WaterData:
    """The table, the period masks of the split in use and the complete-row mask."""

    def __init__(self, config: WaterConfig, frame: pd.DataFrame | None = None, assignment: dict | None = None):
        base = config.base
        if frame is None:
            columns = ["entity_id", "issued_at_utc", base.target_column,
                       *dict.fromkeys([*base.features, *config.require_columns])]
            frame = pd.read_parquet(_resolve(config.table), columns=columns)
        self.config = config
        self.frame = frame.reset_index(drop=True)
        issued = pd.DatetimeIndex(self.frame["issued_at_utc"])
        if issued.tz is None or str(issued.tz) != "UTC":
            raise ValueError("issued_at_utc must be timezone-aware UTC")
        if self.frame.duplicated(["entity_id", "issued_at_utc"]).any():
            raise ValueError("duplicate (entity_id, issued_at_utc) rows")
        self.issued = issued
        need = list(dict.fromkeys([base.target_column, *base.features, *config.require_columns]))
        self.complete = np.isfinite(self.frame[need].to_numpy(dtype=float)).all(axis=1)
        self.y = self.frame[base.target_column].to_numpy(dtype=float)
        if config.split_kind == "chrono":
            self.masks = split_masks(issued, base.split)
            assert_no_temporal_leakage(issued, self.masks, base.horizon_hours)
            self.assignment = None
        elif config.split_kind == "spatial":
            if assignment is None:
                points = json.loads(_resolve(config.spatial_split_file).read_text())["points"]
                assignment = {e: g for g, ids in points.items() for e in ids}
            self.assignment = assignment
            group = self.frame["entity_id"].map(assignment)
            if group.isna().any():
                raise ValueError(f"{int(group.isna().sum())} rows of points that are in no spatial group")
            self.masks = {p: (group == p).to_numpy() for p in ("train", "validation", "test")}
        else:
            raise ValueError("split_kind must be 'chrono' or 'spatial'")
        self.train_pos = np.flatnonzero(self.masks["train"] & self.complete)
        seen = set(self.frame["entity_id"].to_numpy()[self.train_pos])
        self.seen_in_train = self.frame["entity_id"].isin(seen).to_numpy()

    def positions(self, period: str) -> np.ndarray:
        return np.flatnonzero(self.masks[period] & self.complete)

    def season(self, pos: np.ndarray) -> np.ndarray:
        d = self.frame["days_from_midwinter"].to_numpy(dtype=float)[pos]
        return np.array(["winter", "spring_autumn", "summer"], dtype=object)[np.searchsorted(SEASON_CUTS, d)]

    def slices(self, pos: np.ndarray) -> dict[str, np.ndarray]:
        out = {"season": self.season(pos), "low_do": np.where(self.y[pos] < LOW_DO_MG_L, "lt_8", "ge_8")}
        if self.config.split_kind == "chrono":
            out["point_in_train"] = np.where(self.seen_in_train[pos], "yes", "no")
        return out


# -------------------------------------------------------------------------------------------------- baselines


class GlobalMean:
    name = "global_mean"

    def fit(self, frame, y) -> GlobalMean:
        self.mean_ = float(np.mean(y))
        return self

    def predict(self, frame) -> np.ndarray:
        return np.full(len(frame), self.mean_)


class PointMean:
    """Mean of the training OD of the sampling point; the global mean for points never seen in training."""

    name = "point_mean"

    def fit(self, frame, y) -> PointMean:
        self.global_ = float(np.mean(y))
        series = pd.Series(np.asarray(y, dtype=float), index=frame["entity_id"].to_numpy())
        self.by_point_ = series.groupby(level=0).mean()
        return self

    def predict(self, frame) -> np.ndarray:
        return self.by_point_.reindex(frame["entity_id"].to_numpy()).fillna(self.global_).to_numpy()


class SeasonOnlyMean:
    """Mean OD by bin of ``days_from_midwinter`` (12 equal bins over 0-183 days); no point, no nutrients."""

    name = "season_only"
    N_BINS = 12

    def _bin(self, frame) -> np.ndarray:
        d = frame["days_from_midwinter"].to_numpy(dtype=float)
        return np.clip((d / 183.0 * self.N_BINS).astype(int), 0, self.N_BINS - 1)

    def fit(self, frame, y) -> SeasonOnlyMean:
        means = pd.Series(np.asarray(y, dtype=float)).groupby(self._bin(frame)).mean()
        self.means_ = means.reindex(range(self.N_BINS)).interpolate(limit_direction="both").to_numpy()
        return self

    def predict(self, frame) -> np.ndarray:
        return self.means_[self._bin(frame)]


def _baselines(config: WaterConfig):
    from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LinearRegression, Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import PolynomialFeatures, StandardScaler

    base = config.base
    out = [GlobalMean()]
    if config.split_kind == "chrono":
        out.append(PointMean())
    out.append(SeasonOnlyMean())
    if "water_temperature" in base.features:
        out.append(SklearnBaseline("temperature_only_quadratic", make_pipeline(
            PolynomialFeatures(2), LinearRegression()), ["water_temperature"]))
    out += [
        SklearnBaseline("ridge", make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                                               Ridge(alpha=base.ridge_alpha)), base.features),
        SklearnBaseline("random_forest", RandomForestRegressor(
            n_estimators=300, min_samples_leaf=5, n_jobs=4, random_state=base.seed), base.features),
        SklearnBaseline("hist_gradient_boosting", HistGradientBoostingRegressor(
            max_iter=base.gbm_max_iter, early_stopping=False, random_state=base.seed), base.features),
    ]
    return out


# ------------------------------------------------------------------------------------------------- scoring


def _block(wd: WaterData, pos: np.ndarray, pred: np.ndarray) -> dict:
    y = wd.y[pos]
    out = {"overall": {**regression_metrics(y, pred), "n": int(len(y))}, "slices": {}}
    for name, labels in wd.slices(pos).items():
        out["slices"][name] = {str(v): {**regression_metrics(y[labels == v], pred[labels == v]),
                                        "n": int((labels == v).sum())} for v in sorted(set(labels))}
    return out


def _fit_fuzzy(wd: WaterData, params: FuzzyParams, seed: int):
    config, d = wd.config, wd
    base = config.base
    fixed = config.partitions.resolve()
    censored = load_censored(_resolve_repo(config.partitions.file))
    X = d.frame.loc[d.train_pos, base.features]
    with PeakRss() as rss:
        start = time.perf_counter()
        model = WaterFuzzyRegressor(params, base.feature_units, censored).fit(
            X, d.y[d.train_pos], seed, partition_reference=X, fixed=fixed)
        seconds = time.perf_counter() - start
    return model, seconds, rss.peak_mb


def _resolve_repo(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else REPO_ROOT / p


def experiment_dir(config: WaterConfig, artifacts_dir: Path) -> Path:
    return Path(artifacts_dir) / config.base.task_id / "experiments" / config.experiment_id


# ------------------------------------------------------------------------------------------------- select


def run_selection(config: WaterConfig, wd: WaterData, out_dir: Path) -> dict:
    sel, base = config.selection, config.base
    ensure_config(config)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "selection.json"
    result = json.loads(path.read_text()) if path.exists() else {"fits": []}
    if config.exfuzzy_source:
        result["exfuzzy_source"] = config.exfuzzy_source
    val = wd.positions("validation")
    X_val, y_val = wd.frame.loc[val, base.features], wd.y[val]
    done = {(f["nRules"], f["nAnts"]) for f in result["fits"]}
    for n_rules in sel.nRules:
        for n_ants in sel.nAnts:
            if (n_rules, n_ants) in done:
                continue
            params = FuzzyParams(nRules=n_rules, nAnts=n_ants, n_linguistic_variables=sel.n_linguistic_variables,
                                 n_gen=sel.n_gen, pop_size=sel.pop_size, rule_mode=config.rule_mode,
                                 unique_antecedents=config.unique_antecedents)
            model, secs, rss = _fit_fuzzy(wd, params, sel.seed)
            metrics = regression_metrics(y_val, model.predict(X_val))
            sigs = rule_signatures(model.get_rulebase())
            result["fits"].append({
                "nRules": n_rules, "nAnts": n_ants, "n_linguistic_variables": sel.n_linguistic_variables,
                "seed": sel.seed, "n_gen": sel.n_gen, "pop_size": sel.pop_size,
                "n_train_rows": int(len(wd.train_pos)), "validation": metrics, "n_validation_rows": int(len(val)),
                "train_fitness_r2": model.fit_info["train_fitness"], "fit_seconds": secs, "peak_rss_mb": rss,
                "mean_rule_length": float(np.mean([len(s) for s in sigs])), "n_distinct_rules": len(set(sigs)),
            })
            _log(f"select {config.experiment_id}: {n_rules} x {n_ants}: validation {metrics} fit {secs:.0f}s")
            path.write_text(json.dumps(result, indent=2) + "\n")
    best = min(result["fits"], key=lambda f: (f["validation"]["rmse"], f["nRules"], f["nAnts"]))
    result["criterion"] = "lowest validation RMSE (ties: fewer rules, then fewer antecedents)"
    result["chosen"] = {k: best[k] for k in ("nRules", "nAnts", "n_linguistic_variables")}
    path.write_text(json.dumps(result, indent=2) + "\n")
    return result


# --------------------------------------------------------------------------------------------------- final


def run_final(config: WaterConfig, wd: WaterData, out_dir: Path, artifacts_dir: Path, *, selection: dict | None = None,
              write_runs: bool = True, test: bool = True) -> dict:
    """Seeds, baselines and scoring; ``test=False`` never reads the test rows and writes no run directory
    (``summary_validation.json``)."""
    base = config.base
    ensure_config(config)
    out_dir.mkdir(parents=True, exist_ok=True)
    selection = selection or json.loads((out_dir / "selection.json").read_text())
    chosen = selection["chosen"]
    write_runs = write_runs and test
    periods = {"validation": wd.positions("validation"), **({"test": wd.positions("test")} if test else {})}
    frames = {p: wd.frame.loc[pos] for p, pos in periods.items()}
    train_frame, y_train = wd.frame.loc[wd.train_pos], wd.y[wd.train_pos]
    _log(f"final {config.experiment_id}: rows train {len(wd.train_pos)}, "
         f"{({p: len(v) for p, v in periods.items()})}, chosen {chosen}")

    baseline_rows: list[m.MetricRow] = []
    baseline_blocks: dict[str, dict] = {}
    for baseline in _baselines(config):
        start = time.perf_counter()
        baseline.fit(train_frame, y_train)
        fit_s = time.perf_counter() - start
        baseline_blocks[baseline.name] = {}
        for p, pos in periods.items():
            pred = baseline.predict(frames[p])
            baseline_blocks[baseline.name][p] = _block(wd, pos, pred)
            prefix = VALIDATION_PREFIX if p == "validation" else ""
            baseline_rows += period_metric_rows(baseline.name, frames[p], wd.y[pos], pred,
                                                horizon_hours=base.horizon_hours, timezone=base.timezone,
                                                thresholds={}, prefix=prefix)
        baseline_rows.append(m.MetricRow(estimator=baseline.name, metric="fit_seconds", value=fit_s,
                                         n=len(train_frame)))

    params = FuzzyParams(nRules=chosen["nRules"], nAnts=chosen["nAnts"],
                         n_linguistic_variables=chosen["n_linguistic_variables"], n_gen=config.final.n_gen,
                         pop_size=config.final.pop_size, rule_mode=config.rule_mode,
                         unique_antecedents=config.unique_antecedents)
    runs, signatures = [], []
    created = datetime.now(timezone.utc)
    for seed in config.final.seeds:
        _log(f"final {config.experiment_id}: fuzzy seed {seed} {params}")
        model, fit_s, rss = _fit_fuzzy(wd, params, seed)
        rows, blocks, preds = list(baseline_rows), {}, {}
        for p, pos in periods.items():
            X = frames[p][base.features]
            preds[p] = model.predict(X)
            blocks[p] = _block(wd, pos, preds[p])
            prefix = VALIDATION_PREFIX if p == "validation" else ""
            rows += period_metric_rows(FUZZY, frames[p], wd.y[pos], preds[p], horizon_hours=base.horizon_hours,
                                       timezone=base.timezone, thresholds={}, prefix=prefix)
            if p == list(periods)[-1]:
                rows += interpretability_rows(FUZZY, model.get_rulebase(), X.to_numpy(dtype=float))
        rows += [m.MetricRow(estimator=FUZZY, metric="fit_seconds", value=fit_s, n=len(train_frame)),
                 m.MetricRow(estimator=FUZZY, metric="fit_peak_rss_mb", value=rss, n=len(train_frame))]
        signatures.append(rule_signatures(model.get_rulebase()))
        run = {"seed": seed, "fit_seconds": fit_s, "peak_rss_mb": rss, "fit_info": model.fit_info,
               "validation_rmse": blocks["validation"]["overall"]["rmse"],
               "n_rules": len(signatures[-1]), "partitions": model.variables_summary, **blocks,
               "rules": [[list(a) for a in sig] for sig in signatures[-1]]}
        if write_runs and config.split_kind == "chrono":
            run.update(_write_run(config, wd, model, rows, seed, params, created, frames, artifacts_dir))
        with open(out_dir / f"seed{seed}.pkl", "wb") as fh:
            pickle.dump(model, fh)
        runs.append(run)
    best = min(runs, key=lambda r: r["validation_rmse"])
    summary = {
        "experiment_id": config.experiment_id, "split_kind": config.split_kind, "features": base.features,
        "n_complete_rows": {"train": int(len(wd.train_pos)), **{p: int(len(v)) for p, v in periods.items()}},
        "chosen_shape": chosen,
        "final_budget": {"n_gen": params.n_gen, "pop_size": params.pop_size, "seeds": config.final.seeds},
        "runs": runs, "published_seed_rule": "lowest validation RMSE among the seeds",
        "published_seed": best["seed"], "rule_stability": rule_stability(signatures),
        "baselines": baseline_blocks,
        **({"exfuzzy_source": config.exfuzzy_source} if config.exfuzzy_source else {}),
    }
    (out_dir / ("summary.json" if test else "summary_validation.json")).write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def _write_run(config, wd, model, rows, seed, params, created, frames, artifacts_dir) -> dict:
    base = config.base
    run_id = f"{config.experiment_id}-seed{seed}"
    run_config = base.model_copy(update={"fuzzy": params, "seed": seed, "run_id": run_id})
    model_id = _model_id(run_config, run_id)
    metrics = m.MetricsReport(model_id=model_id, task_id=base.task_id, split=base.split, rows=rows)
    train = wd.frame.loc[wd.train_pos]
    rules = export_model_rules(
        model, model_id=model_id, task_id=base.task_id, domain=base.domain, target=base.target, target_unit=base.unit,
        horizon_hours=base.horizon_hours, data_version=base.data_version, synthetic=base.synthetic,
        feature_units=base.feature_units, X_reference=train[base.features])
    commit, dirty = artifacts.git_state()
    manifest = m.RunManifest(
        run_id=run_id, model_id=model_id, task_id=base.task_id, domain=base.domain, created_at_utc=created,
        git_commit=commit, git_dirty=dirty, exfuzzy_version=exfuzzy_version(),
        python_version=artifacts.python_version(), seed=seed, split=base.split, data_version=base.data_version,
        data_checksums=base.data_checksums, target=base.target, horizon_hours=base.horizon_hours,
        features=base.features,
        hyperparameters={
            **params.as_dict(), "ridge_alpha": base.ridge_alpha, "gbm_max_iter": base.gbm_max_iter,
            "timezone": base.timezone, "n_train_rows": len(train), "fit_info": model.fit_info,
            "task_type": "regression", "inference_kind": "descriptive same-sample inference (horizon 0)",
            "experiment": json.loads(config.model_dump_json(exclude={"base"})),
            "run_config": json.loads(run_config.model_dump_json()),
            **provenance_hyperparameters(config),
        },
        artifacts={"model": artifacts.MODEL_FILE, "metrics": "metrics.json", "rules": "rules.json",
                   "predictions": "predictions.parquet", "checksums": artifacts.CHECKSUM_FILE},
        warnings=[
            "descriptive same-sample inference, not a forecast: the dissolved oxygen of a sample is estimated from "
            "the other determinands measured in that sample (valid_at = issued_at)",
            "additive TSK rules: a rule's consequent is not the oxygen of the samples it covers, and duplicate or "
            "compensating consequents are possible; read the rule set, not one rule",
            *([] if "water_temperature" in base.features else ["trained without water temperature"]),
            *provenance_warnings(config),
        ],
    )
    test_all = wd.frame.loc[wd.masks["test"]]
    predictions = _prediction_table(model, test_all, run_config, model_id)
    run_dir = artifacts.write_run_dir(
        Path(artifacts_dir) / base.task_id / run_id, model=model, parity_sample=frames["test"][base.features].head(500),
        json_files={"run_manifest.json": manifest.model_dump_json(indent=2) + "\n",
                    "metrics.json": metrics.model_dump_json(indent=2) + "\n",
                    "rules.json": rules.model_dump_json(indent=2) + "\n"},
        parquet_files={"predictions.parquet": predictions})
    return {"run_id": run_id, "model_id": model_id, "run_dir": str(run_dir)}


# --------------------------------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m atlas.ml.experiment_water", description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["select", "final", "all"])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--artifacts-dir", type=Path, default=ARTIFACTS_DIR)
    parser.add_argument("--no-runs", action="store_true", help="final: do not write run directories")
    parser.add_argument("--validation-only", action="store_true",
                        help="final: no test rows read, no run directories (summary_validation.json)")
    args = parser.parse_args(argv)
    config = WaterConfig.model_validate_json(args.config.read_text())
    out_dir = experiment_dir(config, args.artifacts_dir)
    wd = WaterData(config)
    if args.command in ("select", "all"):
        print(json.dumps(run_selection(config, wd, out_dir)["chosen"]))
    if args.command in ("final", "all"):
        summary = run_final(config, wd, out_dir, args.artifacts_dir, write_runs=not args.no_runs,
                            test=not args.validation_only)
        print(json.dumps({"published_seed": summary["published_seed"]}))


if __name__ == "__main__":
    main()
