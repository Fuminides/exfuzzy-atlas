"""Train / evaluate / predict / explain for one task, on a feature table.

Feature table contract (what A1/A2/A3 hand over): one row per ``(entity_id, issued_at_utc)`` with
``issued_at_utc`` timezone-aware UTC, the feature columns named in the config, and the target column holding
``y(issued_at_utc + horizon)``. Features must be observable at ``issued_at_utc``; that is the producer's
responsibility, this module only guarantees the split and the train-only fitting.

Evaluation rows: test-period rows whose target and *all* features are finite. Every estimator is scored on
exactly those rows (ex_fuzzy cannot run on NaN), so the comparison is like for like.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict

from atlas.contracts import models as m
from atlas.explain import build_rule_traces, compute_activations
from atlas.ml import artifacts
from atlas.ml.baselines import make_baselines
from atlas.ml.exfuzzy_features import exfuzzy_version
from atlas.ml.fuzzy import FuzzyParams, FuzzyRegressor
from atlas.ml.fuzzy_classifier import FuzzyClassifier
from atlas.ml.metrics import metric_rows
from atlas.ml.rules_export import export_model_rules
from atlas.ml.split import assert_no_temporal_leakage, split_masks
from atlas.paths import ARTIFACTS_DIR

FUZZY = "exfuzzy"


class RunConfig(BaseModel):
    """Everything that defines a run besides the data. Serialisable, so a run can be reproduced."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    domain: m.Domain
    target: str
    target_column: str
    unit: str
    horizon_hours: int
    features: list[str]
    feature_units: dict[str, str] = {}
    persistence_feature: str | None = None
    split: m.SplitSpec
    seed: int
    data_version: str
    data_checksums: dict[str, m.Sha256] = {}
    synthetic: bool = False
    timezone: str = "UTC"
    fuzzy: FuzzyParams = FuzzyParams()
    ridge_alpha: float = 1.0
    gbm_max_iter: int = 200
    run_id: str | None = None
    model_id: str | None = None


@dataclass
class RunResult:
    run_dir: Path
    manifest: m.RunManifest
    metrics: m.MetricsReport
    rules: m.ModelRules


def _prepare(table: pd.DataFrame, config: RunConfig, *, need_target: bool = True):
    needed = ["entity_id", "issued_at_utc", *config.features] + ([config.target_column] if need_target else [])
    absent = [c for c in needed if c not in table.columns]
    if absent:
        raise KeyError(f"feature table is missing columns: {absent}")
    issued = pd.DatetimeIndex(table["issued_at_utc"])
    if issued.tz is None or str(issued.tz) != "UTC":
        raise ValueError("issued_at_utc must be timezone-aware UTC")
    if table.duplicated(["entity_id", "issued_at_utc"]).any():
        raise ValueError("duplicate (entity_id, issued_at_utc) rows")
    return issued


def _complete(table: pd.DataFrame, config: RunConfig, need_target: bool = True) -> np.ndarray:
    ok = np.isfinite(table[config.features].to_numpy(dtype=float)).all(axis=1)
    if need_target:
        ok &= np.isfinite(table[config.target_column].to_numpy(dtype=float))
    return ok


def _model_id(config: RunConfig, run_id: str) -> str:
    return config.model_id or f"exfuzzy-{config.task_id}-{run_id}"


def train_run(table: pd.DataFrame, config: RunConfig, *, artifacts_dir: Path = ARTIFACTS_DIR) -> RunResult:
    """Fit the fuzzy model and the baselines on the training period, evaluate on test, write the run."""
    issued = _prepare(table, config)
    masks = split_masks(issued, config.split)
    assert_no_temporal_leakage(issued, masks, config.horizon_hours)
    complete = _complete(table, config)
    train, test = masks["train"] & complete, masks["test"] & complete
    if train.sum() < 2 or test.sum() < 1:
        raise ValueError(f"too few complete rows: train={int(train.sum())}, test={int(test.sum())}")
    warnings = []
    for name in ("train", "test"):
        dropped = int(masks[name].sum() - (masks[name] & complete).sum())
        if dropped:
            warnings.append(f"{dropped} {name} rows dropped for a missing/non-finite feature or target")

    created = datetime.now(timezone.utc)
    run_id = config.run_id or f"{created:%Y%m%dT%H%M%SZ}-seed{config.seed}"
    model_id = _model_id(config, run_id)
    frame_train, frame_test = table[train], table[test]
    y_train = frame_train[config.target_column].to_numpy(dtype=float)
    y_test = frame_test[config.target_column].to_numpy(dtype=float)
    slices = {"entity": frame_test["entity_id"].to_numpy()}

    rows: list[m.MetricRow] = []
    n_train, n_test = len(frame_train), len(frame_test)

    def timed(fn, *args, **kwargs):
        start = time.perf_counter()
        out = fn(*args, **kwargs)
        return out, time.perf_counter() - start

    fuzzy = FuzzyRegressor(config.fuzzy, config.feature_units)
    _, fit_seconds = timed(fuzzy.fit, frame_train[config.features], y_train, seed=config.seed)
    pred, predict_seconds = timed(fuzzy.predict, frame_test[config.features])
    rows += metric_rows(FUZZY, y_test, pred, slices)
    rows += [m.MetricRow(estimator=FUZZY, metric="fit_seconds", value=fit_seconds, n=n_train),
             m.MetricRow(estimator=FUZZY, metric="predict_seconds", value=predict_seconds, n=n_test)]
    rows += _interpretability_rows(fuzzy, frame_test[config.features], n_test)

    for baseline in make_baselines(
        config.features, horizon_hours=config.horizon_hours, seed=config.seed,
        persistence_feature=config.persistence_feature, timezone=config.timezone,
        ridge_alpha=config.ridge_alpha, gbm_max_iter=config.gbm_max_iter,
    ):
        _, fit_s = timed(baseline.fit, frame_train, y_train)
        base_pred, pred_s = timed(baseline.predict, frame_test)
        rows += metric_rows(baseline.name, y_test, base_pred, slices)
        rows += [m.MetricRow(estimator=baseline.name, metric="fit_seconds", value=fit_s, n=n_train),
                 m.MetricRow(estimator=baseline.name, metric="predict_seconds", value=pred_s, n=n_test)]

    metrics = m.MetricsReport(model_id=model_id, task_id=config.task_id, split=config.split, rows=rows)
    rules = export_model_rules(
        fuzzy, model_id=model_id, task_id=config.task_id, domain=config.domain, target=config.target,
        target_unit=config.unit, horizon_hours=config.horizon_hours, data_version=config.data_version,
        synthetic=config.synthetic, feature_units=config.feature_units, X_reference=frame_train[config.features],
    )
    commit, dirty = artifacts.git_state()
    names = {
        "model": artifacts.MODEL_FILE, "metrics": "metrics.json", "rules": "rules.json",
        "predictions": "predictions.parquet", "checksums": artifacts.CHECKSUM_FILE,
    }
    manifest = m.RunManifest(
        run_id=run_id, model_id=model_id, task_id=config.task_id, domain=config.domain, created_at_utc=created,
        git_commit=commit, git_dirty=dirty, exfuzzy_version=exfuzzy_version(),
        python_version=artifacts.python_version(), seed=config.seed, split=config.split,
        data_version=config.data_version, data_checksums=config.data_checksums, target=config.target,
        horizon_hours=config.horizon_hours, features=config.features,
        hyperparameters={
            **config.fuzzy.as_dict(), "ridge_alpha": config.ridge_alpha, "gbm_max_iter": config.gbm_max_iter,
            "persistence_feature": config.persistence_feature, "timezone": config.timezone,
            "n_train_rows": n_train, "n_test_rows": n_test, "fit_info": fuzzy.fit_info,
            "run_config": config.model_dump(mode="json"),
        },
        artifacts=names, warnings=warnings + (["synthetic data"] if config.synthetic else []),
    )
    test_all = table[masks["test"]]
    predictions = _prediction_table(fuzzy, test_all, config, model_id)
    run_dir = artifacts.write_run_dir(
        Path(artifacts_dir) / config.task_id / run_id,
        model=fuzzy, parity_sample=frame_test[config.features].head(500),
        json_files={
            "run_manifest.json": manifest.model_dump_json(indent=2) + "\n",
            "metrics.json": metrics.model_dump_json(indent=2) + "\n",
            "rules.json": rules.model_dump_json(indent=2) + "\n",
        },
        parquet_files={"predictions.parquet": predictions},
    )
    return RunResult(run_dir, manifest, metrics, rules)


def _interpretability_rows(fuzzy: FuzzyRegressor, X_test: pd.DataFrame, n_test: int) -> list[m.MetricRow]:
    rulebase = fuzzy.get_rulebase()
    lengths = [sum(t >= 0 for t in rule.antecedents) for rule in rulebase.rules]
    act = compute_activations(rulebase, X_test.to_numpy(dtype=float), with_prediction=False)
    return [
        m.MetricRow(estimator=FUZZY, metric="n_rules", value=float(len(lengths)), n=len(lengths)),
        m.MetricRow(estimator=FUZZY, metric="mean_rule_length", value=float(np.mean(lengths)), n=len(lengths)),
        m.MetricRow(estimator=FUZZY, metric="fraction_fallback", value=float(act.fallback_used.mean()), n=n_test),
    ]


def _prediction_table(fuzzy: FuzzyRegressor, frame: pd.DataFrame, config: RunConfig, model_id: str) -> pd.DataFrame:
    """Fuzzy predictions for every row of ``frame`` (null prediction + reason where an input is missing)."""
    pred = fuzzy.predict(frame[config.features])
    observed = frame[config.target_column].to_numpy(dtype=float)
    return pd.DataFrame({
        "entity_id": frame["entity_id"].to_numpy(),
        "issued_at_utc": pd.DatetimeIndex(frame["issued_at_utc"]),
        "valid_at_utc": pd.DatetimeIndex(frame["issued_at_utc"]) + timedelta(hours=config.horizon_hours),
        "observed": np.where(np.isfinite(observed), observed, np.nan),
        "prediction": pred,
        "model_id": model_id,
        "missing_reason": np.where(np.isfinite(pred), None, m.MissingReason.MISSING_INPUT.value),
    })


@dataclass
class LoadedRun:
    run_dir: Path
    manifest: m.RunManifest
    metrics: m.MetricsReport
    rules: m.ModelRules
    model: FuzzyRegressor | FuzzyClassifier
    config: RunConfig


def load_run(run_dir: Path) -> LoadedRun:
    run_dir = Path(run_dir)
    model = artifacts.load_model(run_dir)
    manifest = m.RunManifest.model_validate_json((run_dir / "run_manifest.json").read_text())
    return LoadedRun(
        run_dir=run_dir, manifest=manifest, model=model,
        metrics=m.MetricsReport.model_validate_json((run_dir / "metrics.json").read_text()),
        rules=m.ModelRules.model_validate_json((run_dir / "rules.json").read_text()),
        config=RunConfig.model_validate(manifest.hyperparameters["run_config"]),
    )


def predict_table(run: LoadedRun, table: pd.DataFrame) -> pd.DataFrame:
    """Fuzzy predictions for every row of ``table`` (the target column is not needed)."""
    config = run.config
    issued = _prepare(table, config, need_target=False)
    pred = run.model.predict(table[config.features])
    return pd.DataFrame({
        "entity_id": table["entity_id"].to_numpy(),
        "issued_at_utc": issued,
        "valid_at_utc": issued + timedelta(hours=config.horizon_hours),
        "prediction": pred,
        "model_id": run.manifest.model_id,
        "missing_reason": np.where(np.isfinite(pred), None, m.MissingReason.MISSING_INPUT.value),
    })


def evaluate_run(run: LoadedRun, table: pd.DataFrame) -> tuple[list[m.MetricRow], float | None]:
    """Fuzzy metrics on the test rows of ``table`` and the largest gap to the stored MAE/RMSE/R2 (all slices).

    The gap is 0.0 when ``table`` is the table the run was trained on: a reproducibility check of the artifact.
    """
    config = run.config
    issued = _prepare(table, config)
    masks = split_masks(issued, run.manifest.split)
    sel = masks["test"] & _complete(table, config)
    frame = table[sel]
    rows = metric_rows(
        FUZZY, frame[config.target_column].to_numpy(dtype=float), run.model.predict(frame[config.features]),
        {"entity": frame["entity_id"].to_numpy()},
    )
    stored = {(r.metric, r.slice): r.value for r in run.metrics.rows if r.estimator == FUZZY}
    gaps = [abs(r.value - stored[(r.metric, r.slice)]) for r in rows if (r.metric, r.slice) in stored]
    return rows, (max(gaps) if gaps else None)


def explain_rows(run: LoadedRun, table: pd.DataFrame, entity_id: str, issued_at_utc: str | pd.Timestamp):
    """``RuleTrace`` for the row of ``entity_id`` issued at ``issued_at_utc`` (one trace per match)."""
    config = run.config
    _prepare(table, config, need_target=False)
    sel = (table["entity_id"] == entity_id) & (pd.DatetimeIndex(table["issued_at_utc"]) == pd.Timestamp(issued_at_utc))
    frame = table[sel.to_numpy()]
    if frame.empty:
        raise KeyError(f"no row for {entity_id} at {issued_at_utc}")
    return build_rule_traces(
        run.model, frame[config.features], frame["entity_id"].tolist(), frame["issued_at_utc"],
        model_id=run.manifest.model_id, task_id=config.task_id, horizon_hours=config.horizon_hours,
        target_unit=config.unit, data_version=config.data_version, synthetic=config.synthetic,
        feature_units=config.feature_units,
    )


__all__ = [
    "FUZZY", "LoadedRun", "RunConfig", "RunResult", "evaluate_run", "explain_rows", "load_run", "predict_table",
    "train_run",
]
