"""One-command experiment: ExFuzzy versus baselines on a chronological split of a real feature table (AT-041).

::

    python -m atlas.ml.experiment select --config configs/ml/madrid_no2_h6_experiment.json   # validation only
    python -m atlas.ml.experiment final  --config configs/ml/madrid_no2_h6_experiment.json   # seeds, baselines, test
    python -m atlas.ml.experiment feature-spec --card card.json --config cfg.json --source kind=id --out f.json

Protocol (all of it is in the config and echoed in ``summary.json``):

* The split is ``config.base.split`` (issue time, half-open, embargo); a hard leakage check runs first.
* ``select`` fits a small grid of rule-base shapes on a stratified subsample of the *training period* and ranks it by
  RMSE on the *validation* rows. The test rows are never read by this stage.
* ``final`` fits the chosen shape with several seeds on one fixed subsample, fits the baselines on the full training
  period (and HistGradientBoosting also on the same subsample), and scores every estimator on all complete validation
  and test rows. Each seed becomes a run directory (``artifacts/<task>/<run_id>/``) the publish step can use; the seed
  with the lowest *validation* RMSE is the one to publish.
* Evaluation rows are complete rows only: features, target and the table's own ``complete`` flag.
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
from atlas.ml.baselines import Climatology, Persistence, SklearnBaseline
from atlas.ml.evaluation import (
    PeakRss,
    interpretability_rows,
    period_metric_rows,
    rule_signatures,
    rule_stability,
)
from atlas.ml.exfuzzy_features import exfuzzy_version
from atlas.ml.feature_spec import feature_spec_from_card, write_feature_spec
from atlas.ml.fuzzy import FuzzyParams, FuzzyRegressor
from atlas.ml.metrics import regression_metrics
from atlas.ml.pipeline import FUZZY, RunConfig, _model_id, _prediction_table
from atlas.ml.rules_export import export_model_rules
from atlas.ml.split import assert_no_temporal_leakage, split_masks
from atlas.ml.subsample import stratified_subsample, subsample_spec
from atlas.paths import ARTIFACTS_DIR, DATA_DIR

VALIDATION_PREFIX = "validation/"


class SubsampleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n_rows: int
    seed: int


class SelectionConfig(BaseModel):
    """Grid of rule-base shapes, fitted once each (``seed``) with the same budget and ranked on validation."""

    model_config = ConfigDict(extra="forbid")

    nRules: list[int]
    nAnts: list[int]
    n_linguistic_variables: list[int] = [3]
    n_gen: int
    pop_size: int
    seed: int = 0
    subsample_rows: int | None = None  # defaults to subsample.n_rows


class FinalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n_gen: int
    pop_size: int
    seeds: list[int]


class ExtremesConfig(BaseModel):
    """Analytical thresholds for the extreme-episode rows (never regulatory limits)."""

    model_config = ConfigDict(extra="forbid")

    train_quantiles: list[float] = [0.99]
    absolute: list[float] = []


class ExperimentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str
    table: str  # parquet file or hive directory; relative paths resolve against ATLAS_DATA_DIR
    complete_column: str | None = "complete"
    base: RunConfig  # task, features, units, split, persistence feature; ``fuzzy`` and ``seed`` are overridden
    subsample: SubsampleConfig
    selection: SelectionConfig
    final: FinalConfig
    extremes: ExtremesConfig = ExtremesConfig()
    compact_load: bool = False  # read only the complete rows, float32 features (atlas.ml.compact_load); for huge tables
    covid_window_utc: list[str] | None = None  # sensitivity: also train without [from, to)
    train_exclude_windows_utc: list[list[str]] = []  # windows removed from every training set
    exfuzzy_source: str | None = None  # provenance of a non-release ex_fuzzy (FX retrain); echoed in manifests
    requires_exfuzzy: list[str] = []  # fixes the experiment needs (atlas.ml.exfuzzy_features.FEATURES); checked at run


def _utc(text: str) -> pd.Timestamp:
    stamp = pd.Timestamp(text)
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def experiment_dir(config: ExperimentConfig, artifacts_dir: Path) -> Path:
    return Path(artifacts_dir) / config.base.task_id / "experiments" / config.experiment_id


def _has_duplicate_keys(frame: pd.DataFrame) -> bool:
    """``frame.duplicated(["entity_id", "issued_at_utc"]).any()``; with a categorical ``entity_id`` it sorts one int64
    key instead of hashing the pair (about 0.4 GB less at 21 M rows)."""
    entity, stamps = frame["entity_id"], pd.DatetimeIndex(frame["issued_at_utc"])
    if isinstance(entity.dtype, pd.CategoricalDtype) and len(frame):
        ticks = stamps.asi8
        span = int(ticks.max() - ticks.min()) + 1
        if len(entity.cat.categories) * span < 2**62:
            key = entity.cat.codes.to_numpy().astype(np.int64) * span
            key += ticks - ticks.min()
            key.sort()
            return bool((key[1:] == key[:-1]).any())
    return bool(frame.duplicated(["entity_id", "issued_at_utc"]).any())


class Data:
    """The loaded table, its split masks and the complete-row masks (positions in ``frame``)."""

    def __init__(self, frame: pd.DataFrame, config: ExperimentConfig):
        base = config.base
        plain = isinstance(frame.index, pd.RangeIndex) and frame.index.start == 0 and frame.index.step == 1
        self.frame, self.config = (frame if plain else frame.reset_index(drop=True)), config  # no copy of a big frame
        issued = pd.DatetimeIndex(self.frame["issued_at_utc"])
        if issued.tz is None or str(issued.tz) != "UTC":
            raise ValueError("issued_at_utc must be timezone-aware UTC")
        if _has_duplicate_keys(self.frame):
            raise ValueError("duplicate (entity_id, issued_at_utc) rows")
        self.issued = issued
        masks = split_masks(issued, base.split)
        assert_no_temporal_leakage(issued, masks, base.horizon_hours)
        ok = np.ones(len(self.frame), dtype=bool)
        for column in [base.target_column, *base.features]:  # column by column: no (rows x columns) float64 copy
            ok &= np.isfinite(self.frame[column].to_numpy(dtype=float))
        if config.complete_column:
            ok &= self.frame[config.complete_column].to_numpy(dtype=bool)
        self.complete = ok
        self.masks = masks
        self.y = self.frame[base.target_column].to_numpy(dtype=float)
        drop = np.zeros(len(self.frame), dtype=bool)
        for lo, hi in config.train_exclude_windows_utc:
            drop |= np.asarray((issued >= _utc(lo)) & (issued < _utc(hi)))
        self.train_pos = np.flatnonzero(masks["train"] & ok & ~drop)
        self.windows = config.train_exclude_windows_utc

    def positions(self, period: str) -> np.ndarray:
        return np.flatnonzero(self.masks[period] & self.complete)

    def subsample(self, n_rows: int, seed: int, extra_window: list[str] | None = None) -> tuple[np.ndarray, dict]:
        """Positions in ``frame`` of the stratified training subsample (and its spec)."""
        pos = self.train_pos
        windows = [list(w) for w in self.windows]
        if extra_window:
            lo, hi = _utc(extra_window[0]), _utc(extra_window[1])
            pos = pos[~np.asarray((self.issued[pos] >= lo) & (self.issued[pos] < hi))]
            windows.append(list(extra_window))
        picked = stratified_subsample(self.frame["entity_id"].to_numpy()[pos], self.issued[pos], n_rows, seed)
        split = self.config.base.split
        spec = subsample_spec(
            self.frame["entity_id"].to_numpy()[pos], self.issued[pos], picked, n_target=n_rows, seed=seed,
            train_from_utc=split.train_from_utc.isoformat(), train_to_utc=split.train_to_utc.isoformat(),
            excluded_windows=windows,
        )
        return pos[picked], spec


def load_data(config: ExperimentConfig, frame: pd.DataFrame | None = None) -> Data:
    base = config.base
    if frame is None:
        path = Path(config.table)
        path = path if path.is_absolute() else DATA_DIR / path
        if config.compact_load:
            from atlas.ml.compact_load import load_complete_compact

            frame = load_complete_compact(
                path, target_column=base.target_column, features=base.features,
                complete_column=config.complete_column, float64_columns=[base.persistence_feature])
            return Data(frame, config)
        columns = ["entity_id", "issued_at_utc", base.target_column, *base.features]
        if config.complete_column:
            columns.append(config.complete_column)
        frame = pd.read_parquet(path, columns=columns)
    return Data(frame, config)


def _log(text: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {text}", flush=True)


def _fit_fuzzy(params: FuzzyParams, units: dict[str, str], X: pd.DataFrame, y: np.ndarray, seed: int):
    with PeakRss() as rss:
        start = time.perf_counter()
        model = FuzzyRegressor(params, units).fit(X, y, seed=seed)
        seconds = time.perf_counter() - start
    return model, seconds, rss.peak_mb


def _params(n_rules: int, n_ants: int, n_lv: int, n_gen: int, pop: int) -> FuzzyParams:
    return FuzzyParams(nRules=n_rules, nAnts=n_ants, n_linguistic_variables=n_lv, n_gen=n_gen, pop_size=pop)


# ----------------------------------------------------------------------------------------------------- select


def run_selection(config: ExperimentConfig, data: Data, out_dir: Path) -> dict:
    """Fit the grid on a training subsample, rank on validation, write ``selection.json`` (resumable)."""
    base, sel = config.base, config.selection
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "selection.json"
    result = json.loads(path.read_text()) if path.exists() else {"fits": []}
    n_rows = sel.subsample_rows or config.subsample.n_rows
    rows, spec = data.subsample(n_rows, config.subsample.seed)
    result["subsample"] = spec
    X_train, y_train = data.frame.loc[rows, base.features], data.y[rows]
    val = data.positions("validation")
    X_val, y_val = data.frame.loc[val, base.features], data.y[val]
    done = {(f["nRules"], f["nAnts"], f["n_linguistic_variables"]) for f in result["fits"]}
    for n_rules in sel.nRules:
        for n_ants in sel.nAnts:
            for n_lv in sel.n_linguistic_variables:
                if (n_rules, n_ants, n_lv) in done:
                    continue
                params = _params(n_rules, n_ants, n_lv, sel.n_gen, sel.pop_size)
                _log(f"select: fitting {params} on {len(rows)} rows")
                model, secs, rss = _fit_fuzzy(params, base.feature_units, X_train, y_train, sel.seed)
                pred = model.predict(X_val)
                metrics = regression_metrics(y_val, pred)
                rb = model.get_rulebase()
                sigs = rule_signatures(rb)
                result["fits"].append({
                    "nRules": n_rules, "nAnts": n_ants, "n_linguistic_variables": n_lv, "seed": sel.seed,
                    "n_gen": sel.n_gen, "pop_size": sel.pop_size, "n_train_rows": len(rows),
                    "validation": metrics, "n_validation_rows": len(val),
                    "train_fitness_r2": model.fit_info["train_fitness"], "fit_seconds": secs, "peak_rss_mb": rss,
                    "mean_rule_length": float(np.mean([len(s) for s in sigs])),
                    "n_distinct_rules": len(set(sigs)),
                })
                _log(f"select: validation {metrics} fit {secs:.0f}s rss {rss:.0f} MB")
                path.write_text(json.dumps(result, indent=2) + "\n")
    best = min(result["fits"], key=lambda f: (f["validation"]["rmse"], f["nRules"], f["nAnts"]))
    result["criterion"] = "lowest validation RMSE (ties: fewer rules, then fewer antecedents)"
    result["chosen"] = {k: best[k] for k in ("nRules", "nAnts", "n_linguistic_variables")}
    path.write_text(json.dumps(result, indent=2) + "\n")
    return result


# ------------------------------------------------------------------------------------------------------ final


def _baselines(config: ExperimentConfig):
    base = config.base
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    def hgb():
        return SklearnBaseline("hist_gradient_boosting", HistGradientBoostingRegressor(
            max_iter=base.gbm_max_iter, early_stopping=False, random_state=base.seed), base.features)

    ridge = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=base.ridge_alpha))
    full = [
        Persistence(base.persistence_feature) if base.persistence_feature else None,
        Climatology(base.horizon_hours, base.timezone),
        Climatology(base.horizon_hours, base.timezone, by_entity=False),
        SklearnBaseline("ridge", ridge, base.features),
        hgb(),
    ]
    full = [b for b in full if b is not None]
    next(b for b in full if isinstance(b, Climatology) and not b.by_entity).name = "climatology_global"
    return full, hgb()


def _timed(fn, *args):
    start = time.perf_counter()
    out = fn(*args)
    return out, time.perf_counter() - start


def _single_row_ms(model: FuzzyRegressor, X: pd.DataFrame, repeats: int = 20) -> float:
    times = []
    for i in range(repeats):
        start = time.perf_counter()
        model.predict(X.iloc[[i]])
        times.append(time.perf_counter() - start)
    return float(np.median(times) * 1e3)


def run_final(
    config: ExperimentConfig, data: Data, out_dir: Path, artifacts_dir: Path, *, selection: dict | None = None
) -> dict:
    base = config.base
    out_dir.mkdir(parents=True, exist_ok=True)
    selection = selection or json.loads((out_dir / "selection.json").read_text())
    chosen = selection["chosen"]
    periods = {"validation": data.positions("validation"), "test": data.positions("test")}
    frames = {p: data.frame.loc[pos] for p, pos in periods.items()}
    y = {p: data.y[pos] for p, pos in periods.items()}
    y_train_full = data.y[data.train_pos]
    thresholds = {
        f"ge_p{round(q * 100):g}_train": float(np.quantile(y_train_full, q)) for q in config.extremes.train_quantiles
    }
    thresholds.update({f"ge_{a:g}": float(a) for a in config.extremes.absolute})
    n_train_full = len(data.train_pos)
    _log(f"final: train rows {n_train_full}, validation {len(y['validation'])}, test {len(y['test'])}, "
         f"thresholds {thresholds}")

    sub_rows, sub_spec = data.subsample(config.subsample.n_rows, config.subsample.seed)
    pd.DataFrame({
        "entity_id": data.frame["entity_id"].to_numpy()[sub_rows], "issued_at_utc": data.issued[sub_rows],
    }).to_parquet(out_dir / "subsample_keys.parquet", index=False)
    (out_dir / "subsample_spec.json").write_text(json.dumps(sub_spec, indent=2) + "\n")

    # --- baselines
    full_baselines, hgb_sub = _baselines(config)
    hgb_sub.name = "hist_gradient_boosting_subsample"
    train_full_frame, sub_frame = data.frame.loc[data.train_pos], data.frame.loc[sub_rows]
    baseline_rows: list[m.MetricRow] = []
    baseline_preds: dict[str, dict[str, np.ndarray]] = {}
    fits = [(b, train_full_frame, y_train_full) for b in full_baselines] + [(hgb_sub, sub_frame, data.y[sub_rows])]
    for baseline, frame_fit, y_fit in fits:
        _log(f"final: baseline {baseline.name} (fit rows {len(frame_fit)})")
        _, fit_s = _timed(baseline.fit, frame_fit, y_fit)
        baseline_preds[baseline.name] = {}
        for period in ("validation", "test"):
            pred, pred_s = _timed(baseline.predict, frames[period])
            baseline_preds[baseline.name][period] = pred
            prefix = VALIDATION_PREFIX if period == "validation" else ""
            baseline_rows += period_metric_rows(
                baseline.name, frames[period], y[period], pred, horizon_hours=base.horizon_hours,
                timezone=base.timezone, thresholds=thresholds, prefix=prefix)
            if period == "test":
                baseline_rows += [
                    m.MetricRow(estimator=baseline.name, metric="fit_seconds", value=fit_s, n=len(frame_fit)),
                    m.MetricRow(estimator=baseline.name, metric="predict_seconds", value=pred_s, n=len(y[period])),
                ]

    # --- the fuzzy model, one run per seed
    params = _params(chosen["nRules"], chosen["nAnts"], chosen["n_linguistic_variables"],
                     config.final.n_gen, config.final.pop_size)
    X_sub, y_sub = sub_frame[base.features], data.y[sub_rows]
    runs, signatures = [], []
    created = datetime.now(timezone.utc)
    for seed in config.final.seeds:
        _log(f"final: fuzzy seed {seed} {params}")
        model, fit_s, rss = _fit_fuzzy(params, base.feature_units, X_sub, y_sub, seed)
        rows = list(baseline_rows)
        preds = {}
        for period in ("validation", "test"):
            X = frames[period][base.features]
            preds[period], pred_s = _timed(model.predict, X)
            prefix = VALIDATION_PREFIX if period == "validation" else ""
            rows += period_metric_rows(
                FUZZY, frames[period], y[period], preds[period], horizon_hours=base.horizon_hours,
                timezone=base.timezone, thresholds=thresholds, prefix=prefix)
            if period == "test":
                rows += interpretability_rows(FUZZY, model.get_rulebase(), X.to_numpy(dtype=float))
                latency_ms = _single_row_ms(model, X)
                rows += [
                    m.MetricRow(estimator=FUZZY, metric="fit_seconds", value=fit_s, n=len(y_sub)),
                    m.MetricRow(estimator=FUZZY, metric="predict_seconds", value=pred_s, n=len(y[period])),
                    m.MetricRow(estimator=FUZZY, metric="predict_ms_single_row", value=latency_ms, n=20),
                    m.MetricRow(estimator=FUZZY, metric="fit_peak_rss_mb", value=rss, n=len(y_sub)),
                    m.MetricRow(estimator=FUZZY, metric="model_pkl_bytes", value=float(len(pickle.dumps(model))), n=1),
                ]
        signatures.append(rule_signatures(model.get_rulebase()))
        run_id = f"{config.experiment_id}-seed{seed}"
        runs.append(_write_run(config, data, model, rows, run_id, seed, params, sub_spec, thresholds, created,
                               frames, y, artifacts_dir, sub_frame, preds, fit_s))

    # --- summary
    val_rmse = {r["seed"]: r["validation_rmse"] for r in runs}
    best = min(runs, key=lambda r: r["validation_rmse"])
    summary = {
        "experiment_id": config.experiment_id,
        "split": json.loads(base.split.model_dump_json()),
        "n_complete_rows": {"train_full": n_train_full, "train_subsample": len(sub_rows),
                            "validation": len(y["validation"]), "test": len(y["test"])},
        "thresholds": thresholds,
        "chosen_shape": chosen,
        "final_budget": {"n_gen": params.n_gen, "pop_size": params.pop_size, "seeds": config.final.seeds},
        "runs": runs,
        "published_seed_rule": "lowest validation RMSE among the seeds",
        "published_run": {"seed": best["seed"], "run_dir": best["run_dir"], "model_id": best["model_id"]},
        "validation_rmse_by_seed": val_rmse,
        "rule_stability": rule_stability(signatures),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def _write_run(config, data, model, rows, run_id, seed, params, sub_spec, thresholds, created, frames, y,
               artifacts_dir, sub_frame, preds, fit_seconds) -> dict:
    base = config.base
    run_config = base.model_copy(update={"fuzzy": params, "seed": seed, "run_id": run_id})
    model_id = _model_id(run_config, run_id)
    metrics = m.MetricsReport(model_id=model_id, task_id=base.task_id, split=base.split, rows=rows)
    rules = export_model_rules(
        model, model_id=model_id, task_id=base.task_id, domain=base.domain, target=base.target, target_unit=base.unit,
        horizon_hours=base.horizon_hours, data_version=base.data_version, synthetic=base.synthetic,
        feature_units=base.feature_units, X_reference=sub_frame[base.features],
    )
    commit, dirty = artifacts.git_state()
    names = {"model": artifacts.MODEL_FILE, "metrics": "metrics.json", "rules": "rules.json",
             "predictions": "predictions.parquet", "checksums": artifacts.CHECKSUM_FILE}
    n_dropped = {p: int(data.masks[p].sum() - len(frames[p])) for p in ("validation", "test")}
    manifest = m.RunManifest(
        run_id=run_id, model_id=model_id, task_id=base.task_id, domain=base.domain, created_at_utc=created,
        git_commit=commit, git_dirty=dirty, exfuzzy_version=exfuzzy_version(),
        python_version=artifacts.python_version(), seed=seed, split=base.split, data_version=base.data_version,
        data_checksums=base.data_checksums, target=base.target, horizon_hours=base.horizon_hours,
        features=base.features,
        hyperparameters={
            **params.as_dict(), "ridge_alpha": base.ridge_alpha, "gbm_max_iter": base.gbm_max_iter,
            "persistence_feature": base.persistence_feature, "timezone": base.timezone,
            "n_train_rows": len(sub_frame), "n_test_rows": len(frames["test"]), "fit_info": model.fit_info,
            "train_subsample": sub_spec, "extreme_thresholds": thresholds,
            "experiment": json.loads(config.model_dump_json(exclude={"base"})),
            "run_config": json.loads(run_config.model_dump_json()),
        },
        artifacts=names,
        warnings=[
            f"{n} {p} rows excluded as incomplete (feature/target missing or flagged)"
            for p, n in n_dropped.items() if n
        ] + [
            f"fitted on a stratified subsample of {len(sub_frame)} of the {len(data.train_pos)} complete training rows"
        ],
    )
    test_all = data.frame.loc[data.masks["test"]]
    predictions = _prediction_table(model, test_all, run_config, model_id)
    run_dir = artifacts.write_run_dir(
        Path(artifacts_dir) / base.task_id / run_id,
        model=model, parity_sample=frames["test"][base.features].head(500),
        json_files={
            "run_manifest.json": manifest.model_dump_json(indent=2) + "\n",
            "metrics.json": metrics.model_dump_json(indent=2) + "\n",
            "rules.json": rules.model_dump_json(indent=2) + "\n",
        },
        parquet_files={"predictions.parquet": predictions},
    )
    size = sum(p.stat().st_size for p in run_dir.iterdir())
    fuzzy_val = regression_metrics(y["validation"], preds["validation"])
    fuzzy_test = regression_metrics(y["test"], preds["test"])
    return {
        "seed": seed, "run_id": run_id, "model_id": model_id, "run_dir": str(run_dir), "run_dir_bytes": size,
        "fit_seconds": fit_seconds, "train_fitness_r2": model.fit_info["train_fitness"],
        "n_generations_run": model.fit_info["n_generations_run"],
        "validation_rmse": fuzzy_val["rmse"], "validation": fuzzy_val, "test": fuzzy_test,
    }


# ------------------------------------------------------------------------------------- COVID sensitivity


def run_sensitivity(config: ExperimentConfig, data: Data, out_dir: Path, *, selection: dict | None = None) -> dict:
    """Refit HistGradientBoosting (full train) and the chosen fuzzy shape (seed 0 of the final seeds, a fresh
    subsample) without ``covid_window_utc``; report validation and test MAE / RMSE / R2. Not part of any run dir."""
    if not config.covid_window_utc:
        raise ValueError("covid_window_utc is not set in the config")
    base = config.base
    selection = selection or json.loads((out_dir / "selection.json").read_text())
    chosen = selection["chosen"]
    window = config.covid_window_utc
    lo, hi = _utc(window[0]), _utc(window[1])
    pos = data.train_pos[~np.asarray((data.issued[data.train_pos] >= lo) & (data.issued[data.train_pos] < hi))]
    periods = {p: data.positions(p) for p in ("validation", "test")}
    out = {"window_utc": window, "n_train_full": int(len(pos)), "n_removed": int(len(data.train_pos) - len(pos)),
           "estimators": {}}
    _, hgb = _baselines(config)
    hgb.fit(data.frame.loc[pos], data.y[pos])
    out["estimators"]["hist_gradient_boosting"] = {
        p: regression_metrics(data.y[idx], hgb.predict(data.frame.loc[idx])) for p, idx in periods.items()}
    rows, spec = data.subsample(config.subsample.n_rows, config.subsample.seed, extra_window=window)
    params = _params(chosen["nRules"], chosen["nAnts"], chosen["n_linguistic_variables"],
                     config.final.n_gen, config.final.pop_size)
    seed = config.final.seeds[0]
    _log(f"sensitivity: fuzzy seed {seed} on {len(rows)} rows without {window}")
    model, secs, rss = _fit_fuzzy(params, base.feature_units, data.frame.loc[rows, base.features], data.y[rows], seed)
    out["estimators"][FUZZY] = {
        p: regression_metrics(data.y[idx], model.predict(data.frame.loc[idx, base.features]))
        for p, idx in periods.items()
    }
    out["fuzzy"] = {"seed": seed, "fit_seconds": secs, "n_train_rows": len(rows), "subsample": spec}
    (out_dir / "sensitivity_covid.json").write_text(json.dumps(out, indent=2) + "\n")
    return out


# --------------------------------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m atlas.ml.experiment", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("select", "final", "sensitivity", "all"):
        p = sub.add_parser(name)
        p.add_argument("--config", type=Path, required=True)
        p.add_argument("--artifacts-dir", type=Path, default=ARTIFACTS_DIR)
    spec = sub.add_parser("feature-spec", help="write feature_spec.json from a feature card")
    spec.add_argument("--card", type=Path, required=True)
    spec.add_argument("--config", type=Path, required=True, help="experiment config (for the feature list)")
    spec.add_argument("--source", nargs="+", required=True, metavar="KIND=SOURCE_ID", help="e.g. no2=madrid-air")
    spec.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    config = ExperimentConfig.model_validate_json(args.config.read_text())
    if args.command == "feature-spec":
        source_ids = dict(item.split("=", 1) for item in args.source)
        card = json.loads(args.card.read_text())
        write_feature_spec(feature_spec_from_card(card, config.base.features, source_ids), args.out)
        print(f"wrote {args.out}")
        return
    out_dir = experiment_dir(config, args.artifacts_dir)
    data = load_data(config)
    if args.command in ("select", "all"):
        print(json.dumps(run_selection(config, data, out_dir)["chosen"]))
    if args.command in ("final", "all"):
        summary = run_final(config, data, out_dir, args.artifacts_dir)
        print(json.dumps(summary["published_run"]))
    if args.command == "sensitivity":
        print(json.dumps(run_sensitivity(config, data, out_dir)["estimators"]))


if __name__ == "__main__":
    main()
