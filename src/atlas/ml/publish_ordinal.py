"""AT-041k publication: run directories of the arm-B fits that won the pre-registered gate (contract v0.8).

::

    python -m atlas.ml.publish_ordinal runs --tasks de_no2_h3 nyc_pickups_h3 nyc_pickups_h6 uk_water_do
    python -m atlas.ml.publish_ordinal strip-paths <published dir>      # after atlas.services.publish

Reads the selected arm-B fit of each task from ``<artifacts>/experiments/ordinal_conditions`` (``decisions.json``,
``models/B-seed<k>.pkl``, ``fits/B-seed<k>.json``) and writes ``<artifacts>/<task>/<run id>/`` the way the earlier
serve stages did (``experiment_mixture.write_serve_run``, ``experiment_nyc.write_runs``,
``experiment_water._write_run``): model, ``rules.json`` (contract v0.8, with ordinal and compound conditions),
``metrics.json`` (the served model's baseline rows, which are the same rows, split and fitting sample, plus the new
model's rows for the validation and test periods), ``run_manifest.json`` and the test-period
``predictions.parquet``. Publishing them is the usual
``python -m atlas.services.publish`` (docs/ml/ordinal_conditions.md, section 6).

The fits ran on ex-fuzzy commit ``7a0844a`` (version string ``3.4.0+g7a0844a``), whose code is that of the released
ex-fuzzy 3.5.0 (only the version and the changelog differ); the manifest and ``rules.json`` keep the version the fit
recorded and a warning says so.
"""

from __future__ import annotations

import argparse
import json
import pickle
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from atlas.contracts import models as m
from atlas.explain.classifier import rule_ids
from atlas.ml import artifacts
from atlas.ml.classification import classification_metric_rows
from atlas.ml.evaluation import classifier_readability_rows, interpretability_rows, period_metric_rows
from atlas.ml.experiment_class import FUZZY_CLASSIFIER, VALIDATION_PREFIX, _class_prediction_table, _log
from atlas.ml.experiment_mixture import mixture_readability_rows
from atlas.ml.experiment_ordinal import Job, TaskSpec, load_config, load_context, out_dir, water_params
from atlas.ml.pipeline import FUZZY, _model_id, _prediction_table
from atlas.ml.rules_export import export_classifier_rules, export_model_rules
from atlas.paths import ARTIFACTS_DIR

TASKS = ("de_no2_h3", "nyc_pickups_h3", "nyc_pickups_h6", "uk_water_do")
SAME_CODE_AS_RELEASE = (
    "fitted with ex-fuzzy commit 7a0844a (PR 45, feature/ordinal-conditions), whose code is that of the released "
    "ex-fuzzy 3.5.0 (only the version and the changelog differ)")


def run_id_of(spec: TaskSpec, seed: int) -> str:
    return {"mixture": "mixture-nonneg-ordinal", "winning": "level-rel7-ordinal",
            "water": "fx-w-unique-ordinal"}[spec.kind] + f"-seed{seed}"


def _selected(artifacts_dir: Path, task: str) -> tuple[dict, dict, Path]:
    """``(decision, fit record, pickle path)`` of the arm-B selected fit of ``task``; refuses a task B did not win."""
    out = out_dir(artifacts_dir)
    decision = json.loads((out / "decisions.json").read_text())["tasks"][task]
    if decision["winner"] != "B":
        raise SystemExit(f"{task}: the pre-registered gate was not won by arm B")
    seed = decision["B"]["selected_seed"]
    fit = json.loads((out / task / "fits" / f"B-seed{seed}.json").read_text())
    return decision, fit, out / task / "models" / f"B-seed{seed}.pkl"


def _with_fit_version(rules: m.ModelRules, version: str) -> m.ModelRules:
    return rules.model_copy(update={"inference": rules.inference.model_copy(update={"exfuzzy_version": version})})


def _manifest(*, run_id, model_id, base, seed, fit, hyper, warnings, artifact_names) -> m.RunManifest:
    commit, dirty = artifacts.git_state()
    return m.RunManifest(
        run_id=run_id, model_id=model_id, task_id=base.task_id, domain=base.domain,
        created_at_utc=datetime.now(timezone.utc), git_commit=commit, git_dirty=dirty,
        exfuzzy_version=fit["exfuzzy_version"], python_version=artifacts.python_version(), seed=seed, split=base.split,
        data_version=base.data_version, data_checksums=base.data_checksums, target=base.target,
        horizon_hours=base.horizon_hours, features=list(base.features), hyperparameters=hyper,
        artifacts=artifact_names, warnings=warnings)


def _served_rows(run_dir: Path, keep) -> list[m.MetricRow]:
    served = json.loads((run_dir / "metrics.json").read_text())
    return [m.MetricRow.model_validate(r) for r in served["rows"] if keep(r["estimator"])]


def _selection_note(decision: dict, seed: int) -> str:
    p = decision["primary"]
    return (f"selected in experiment ordinal-conditions (AT-041k, docs/ml/ordinal_conditions.md): arm B, seed {seed}; "
            f"validation gain D = {p['D']:+.4f} with tolerance {p['tau']:.4f}, "
            f"{'also' if decision['robust'] else 'not'} on the medians of the three seeds; rule: {decision['rule']}")


def _write(artifacts_dir: Path, base, run_id, model, parity_sample, manifest, metrics, rules, predictions) -> Path:
    run_dir = artifacts.write_run_dir(
        Path(artifacts_dir) / base.task_id / run_id, model=model, parity_sample=parity_sample,
        json_files={"run_manifest.json": manifest.model_dump_json(indent=2) + "\n",
                    "metrics.json": metrics.model_dump_json(indent=2) + "\n",
                    "rules.json": rules.model_dump_json(indent=2) + "\n"},
        parquet_files={"predictions.parquet": predictions})
    _log(f"wrote {run_dir}")
    return run_dir


def write_mixture_run(spec: TaskSpec, artifacts_dir: Path) -> Path:
    """Mixture of rules with ordinal and compound conditions (de_no2_h3, nyc_pickups_h3): as ``write_serve_run``."""
    decision, fit, pkl = _selected(artifacts_dir, spec.task_id)
    seed = fit["seed"]
    with open(pkl, "rb") as fh:
        model = pickle.load(fh)  # noqa: S301 - written by experiment_ordinal
    ctx = load_context(spec, artifacts_dir)
    cd, d, base = ctx.cd, ctx.cd.data, ctx.task.base
    nyc = ctx.cfg.kind == "nyc"
    run_id = run_id_of(spec, seed)
    model_id = f"exfuzzy-{base.task_id}-{run_id}"
    if nyc:
        from atlas.ml.experiment_nyc import TARGET_LABEL
        scheme, target_label = cd.target_scheme, TARGET_LABEL
    else:
        scheme, target_label = cd.scheme.to_target_scheme(), ctx.task.target_label
    sub_frame = d.frame.loc[ctx.sub_rows]
    rules = _with_fit_version(export_classifier_rules(
        model, model_id=model_id, task_id=base.task_id, domain=base.domain, target_label=target_label,
        target_scheme=scheme, horizon_hours=base.horizon_hours, data_version=base.data_version,
        synthetic=base.synthetic, feature_units=base.feature_units, X_reference=sub_frame[ctx.features]),
        fit["exfuzzy_version"])
    ids = rule_ids(model.rule_base)
    rows = _served_rows(ctx.served_run, lambda e: e != FUZZY_CLASSIFIER)
    for period, prefix in (("validation", VALIDATION_PREFIX), ("test", "")):
        pos = d.positions(period)
        frame = d.frame.loc[pos]
        rows += classification_metric_rows(FUZZY_CLASSIFIER, cd.y_class[pos], model.predict(frame[ctx.features]),
                                           cd.labels, {"entity": frame["entity_id"].array}, prefix=prefix)
        X = frame[ctx.features].to_numpy(dtype=float)
        rows += mixture_readability_rows(model, X[np.isfinite(X).all(axis=1)], ids, prefix,
                                         include_static=period == "test")
    rows += [m.MetricRow(estimator=FUZZY_CLASSIFIER, metric="fit_seconds", value=fit["fit_seconds"],
                         n=len(ctx.sub_rows)),
             m.MetricRow(estimator=FUZZY_CLASSIFIER, metric="fit_peak_rss_mb", value=fit["peak_rss_mb"],
                         n=len(ctx.sub_rows))]
    metrics = m.MetricsReport(model_id=model_id, task_id=base.task_id, split=base.split, rows=rows)
    served_manifest = json.loads((ctx.served_run / "run_manifest.json").read_text())
    counts = np.bincount(cd.y_class[ctx.sub_rows], minlength=len(cd.labels)).tolist()
    warnings = [
        f"fitted on the served model's class-aware subsample of {len(ctx.sub_rows)} of the {len(d.train_pos)} "
        f"complete training rows (class counts {counts}; {ctx.served_dir.relative_to(ctx.artifacts)}/"
        "subsample_keys.parquet); the mixture weights and biases therefore reflect that sampling, not the natural "
        "class frequencies",
        "mixture of rules (ex_fuzzy inference='mixture'): every rule that fires adds class_weights x firing to every "
        "class score and the class is the largest score plus bias; no single rule decides. A weight is a coefficient "
        "of a fitted multinomial logistic model on the rule firings; negative centred weights suppress a class "
        "relative to the others. The softmax of the scores is not served",
        "rules may say 'x is at least / at most <term>' on the quantity inputs and name a compound term on the clock "
        "and calendar inputs (contract v0.8): the membership of such a condition is the bounded sum "
        "min(1, sum of the memberships of the terms it covers)",
        _selection_note(decision, seed), SAME_CODE_AS_RELEASE]
    if nyc:
        warnings.insert(-2, served_manifest["warnings"][1])  # the level is relative to the zone's own 2024 norm
    hyper = {
        **model.params.as_dict(), "task_type": "classification", "target_label": target_label,
        "class_labels": cd.labels, "persistence_feature": base.persistence_feature, "timezone": base.timezone,
        "n_train_rows": len(ctx.sub_rows), "fit_info": model.fit_info,
        "sampling_power": served_manifest["hyperparameters"].get("sampling_power"),
        "experiment": json.loads(ctx.task.model_dump_json(exclude={"base"})),
        "run_config": json.loads(base.model_copy(update={"seed": seed, "run_id": run_id}).model_dump_json()),
        "selected_arm": "B", "selection_experiment": "ordinal-conditions", "served_reference_run": ctx.cfg.served_run,
        "mixture": {"C": ctx.cfg.mixture_C, "non_negative": True, "pruning": "winning_rule", **fit["mixture"]},
        "baseline_rows": f"copied from {ctx.cfg.served_run}/metrics.json (same rows, split and fitting sample)",
        "ordinal_conditions": list(model.params.ordinal_conditions or ()),
        "compound_terms": {f: [[n, list(t)] for n, t in v] for f, v in (model.params.compound_terms or {}).items()},
    }
    if not nyc:
        hyper["official_labels"] = cd.official.labels
    manifest = _manifest(run_id=run_id, model_id=model_id, base=base, seed=seed, fit=fit, hyper=hyper,
                         warnings=warnings, artifact_names={
                             "model": artifacts.MODEL_FILE, "metrics": "metrics.json", "rules": "rules.json",
                             "predictions": "predictions.parquet", "checksums": artifacts.CHECKSUM_FILE})
    test_all = d.frame.loc[d.masks["test"]]
    if nyc:
        from atlas.services.publish import _class_predictions

        predictions = _class_predictions(
            model, test_all, list(base.features), test_all[base.target_column].to_numpy(dtype=float), scheme,
            pd.Timedelta(hours=base.horizon_hours), test_all[ctx.task.label_column], mixture=True, rule_ids=ids)
        predictions["model_id"] = model_id
    else:
        predictions = _class_prediction_table(model, test_all, cd, model_id)
    return _write(artifacts_dir, base, run_id, model, d.frame.loc[d.positions("test"), list(base.features)].head(500),
                  manifest, metrics, rules, predictions)


def write_winning_run(spec: TaskSpec, artifacts_dir: Path) -> Path:
    """Winning-rule classifier (nyc_pickups_h6, shape 60 x 4): as ``experiment_nyc.write_runs`` for one seed."""
    from atlas.ml.experiment_nyc import TARGET_LABEL, _rows
    from atlas.services.publish import _class_predictions

    decision, fit, pkl = _selected(artifacts_dir, spec.task_id)
    seed = fit["seed"]
    with open(pkl, "rb") as fh:
        model = pickle.load(fh)  # noqa: S301 - written by experiment_ordinal
    ctx = load_context(spec, artifacts_dir)
    cd, d, base, config = ctx.cd, ctx.cd.data, ctx.task.base, ctx.task
    run_id = run_id_of(spec, seed)
    model_id = f"exfuzzy-{base.task_id}-{run_id}"
    sub_frame = d.frame.loc[ctx.sub_rows]
    rules = _with_fit_version(export_classifier_rules(
        model, model_id=model_id, task_id=base.task_id, domain=base.domain, target_label=TARGET_LABEL,
        target_scheme=cd.target_scheme, horizon_hours=base.horizon_hours, data_version=base.data_version,
        synthetic=base.synthetic, feature_units=base.feature_units, X_reference=sub_frame[base.features]),
        fit["exfuzzy_version"])
    rows = _served_rows(ctx.served_run, lambda e: e != FUZZY_CLASSIFIER)
    for period, prefix in (("validation", VALIDATION_PREFIX), ("test", "")):
        pos = d.positions(period)
        X = d.frame.loc[pos, base.features]
        rows += _rows(cd, FUZZY_CLASSIFIER, pos, model.predict(X), prefix)
        values = X.to_numpy(dtype=float)
        finite = np.isfinite(values).all(axis=1)
        rows += classifier_readability_rows(FUZZY_CLASSIFIER, model, values[finite], cd.labels,
                                            cd.y_class[pos][finite], prefix, include_static=period == "test")
    rows += [m.MetricRow(estimator=FUZZY_CLASSIFIER, metric="fit_seconds", value=fit["fit_seconds"],
                         n=len(ctx.sub_rows)),
             m.MetricRow(estimator=FUZZY_CLASSIFIER, metric="fit_peak_rss_mb", value=fit["peak_rss_mb"],
                         n=len(ctx.sub_rows))]
    metrics = m.MetricsReport(model_id=model_id, task_id=base.task_id, split=base.split, rows=rows)
    served_manifest = json.loads((ctx.served_run / "run_manifest.json").read_text())
    counts = np.bincount(cd.y_class[ctx.sub_rows], minlength=len(cd.labels)).tolist()
    warnings = [
        f"fitted on a class-aware subsample of {len(ctx.sub_rows)} of the {len(d.train_pos)} complete training rows "
        f"(class counts {counts}); the dominance scores and rule weights therefore reflect that sampling, not the "
        "natural class frequencies",
        served_manifest["warnings"][1],  # the level is relative to the zone's own 2024 norm
        "rules may say 'x is at least / at most <term>' on the quantity inputs (contract v0.8): the membership of such "
        "a condition is the bounded sum min(1, sum of the memberships of the terms it covers)",
        f"the shape was selected again in this arm among the six published shapes: {fit['shape'][0]} rules x "
        f"{fit['shape'][1]} antecedents (the earlier model is 30 x 3)",
        _selection_note(decision, seed), SAME_CODE_AS_RELEASE]
    hyper = {
        **model.params.as_dict(), "task_type": "classification", "target_label": TARGET_LABEL,
        "class_labels": cd.labels, "persistence_feature": base.persistence_feature, "timezone": base.timezone,
        "n_train_rows": len(ctx.sub_rows), "fit_info": model.fit_info,
        "sampling_power": ctx.task.selection.candidates[0].sampling_power,
        "experiment": json.loads(config.model_dump_json(exclude={"base"})),
        "run_config": json.loads(base.model_copy(update={"seed": seed, "run_id": run_id}).model_dump_json()),
        "selected_arm": "B", "selection_experiment": "ordinal-conditions", "served_reference_run": ctx.cfg.served_run,
        "baseline_rows": f"copied from {ctx.cfg.served_run}/metrics.json (same rows, split and fitting sample)",
        "ordinal_conditions": list(model.params.ordinal_conditions or ()),
    }
    manifest = _manifest(run_id=run_id, model_id=model_id, base=base, seed=seed, fit=fit, hyper=hyper,
                         warnings=warnings, artifact_names={
                             "model": artifacts.MODEL_FILE, "metrics": "metrics.json", "rules": "rules.json",
                             "predictions": "predictions.parquet", "checksums": artifacts.CHECKSUM_FILE})
    test_all = d.frame.loc[d.masks["test"]]
    predictions = _class_predictions(
        model, test_all, base.features, test_all[base.target_column].to_numpy(dtype=float), cd.target_scheme,
        pd.Timedelta(hours=base.horizon_hours), test_all[config.label_column])
    predictions["model_id"] = model_id
    return _write(artifacts_dir, base, run_id, model, d.frame.loc[d.positions("test"), base.features].head(500),
                  manifest, metrics, rules, predictions)


def write_water_run(spec: TaskSpec, artifacts_dir: Path) -> Path:
    """TSK regressor (uk_water_do, shape 40 x 3): as ``experiment_water._write_run``."""
    decision, fit, pkl = _selected(artifacts_dir, spec.task_id)
    seed = fit["seed"]
    with open(pkl, "rb") as fh:
        model = pickle.load(fh)  # noqa: S301 - written by experiment_ordinal
    ctx = load_context(spec, artifacts_dir)
    wd, config = ctx.wd, ctx.config
    base = config.base
    job = Job(spec.task_id, "B", "final", seed, tuple(fit["shape"]))
    params = water_params(ctx, spec, job, False)
    run_id = run_id_of(spec, seed)
    run_config = base.model_copy(update={"fuzzy": params, "seed": seed, "run_id": run_id})
    model_id = _model_id(run_config, run_id)
    train = wd.frame.loc[wd.train_pos]
    rules = _with_fit_version(export_model_rules(
        model, model_id=model_id, task_id=base.task_id, domain=base.domain, target=base.target, target_unit=base.unit,
        horizon_hours=base.horizon_hours, data_version=base.data_version, synthetic=base.synthetic,
        feature_units=base.feature_units, X_reference=train[base.features]), fit["exfuzzy_version"])
    served_run = artifacts_dir / base.task_id / f"{config.experiment_id}-seed0"
    rows = _served_rows(served_run, lambda e: e != FUZZY)
    frames, last = {}, None
    for period in ("validation", "test"):
        pos = wd.positions(period)
        frames[period] = wd.frame.loc[pos]
        X = frames[period][base.features]
        pred = model.predict(X)
        prefix = VALIDATION_PREFIX if period == "validation" else ""
        rows += period_metric_rows(FUZZY, frames[period], wd.y[pos], pred, horizon_hours=base.horizon_hours,
                                   timezone=base.timezone, thresholds={}, prefix=prefix)
        last = X
    rows += interpretability_rows(FUZZY, model.get_rulebase(), last.to_numpy(dtype=float))
    rows += [m.MetricRow(estimator=FUZZY, metric="fit_seconds", value=fit["fit_seconds"], n=len(train)),
             m.MetricRow(estimator=FUZZY, metric="fit_peak_rss_mb", value=fit["peak_rss_mb"], n=len(train))]
    metrics = m.MetricsReport(model_id=model_id, task_id=base.task_id, split=base.split, rows=rows)
    warnings = [
        "descriptive same-sample inference, not a forecast: the dissolved oxygen of a sample is estimated from the "
        "other determinands measured in that sample (valid_at = issued_at)",
        "additive TSK rules: a rule's consequent is not the oxygen of the samples it covers, and duplicate or "
        "compensating consequents are possible; read the rule set, not one rule",
        "rules may say 'x is at least / at most <term>' on the quantity inputs and name a compound term on the hour "
        "of sampling (contract v0.8): the membership of such a condition is the bounded sum "
        "min(1, sum of the memberships of the terms it covers)",
        f"the shape was selected again in this arm among the nine published shapes: {fit['shape'][0]} rules x "
        f"{fit['shape'][1]} antecedents (the earlier model is 40 x 2)",
        _selection_note(decision, seed), SAME_CODE_AS_RELEASE]
    hyper = {
        **params.as_dict(), "ridge_alpha": base.ridge_alpha, "gbm_max_iter": base.gbm_max_iter,
        "timezone": base.timezone, "n_train_rows": len(train), "fit_info": model.fit_info,
        "task_type": "regression", "inference_kind": "descriptive same-sample inference (horizon 0)",
        "experiment": json.loads(config.model_dump_json(exclude={"base"})),
        "run_config": json.loads(run_config.model_dump_json()),
        "selected_arm": "B", "selection_experiment": "ordinal-conditions", "served_reference_run": served_run.name,
        "baseline_rows": f"copied from {served_run.name}/metrics.json (same rows, split and data)",
    }
    manifest = _manifest(run_id=run_id, model_id=model_id, base=base, seed=seed, fit=fit, hyper=hyper,
                         warnings=warnings, artifact_names={
                             "model": artifacts.MODEL_FILE, "metrics": "metrics.json", "rules": "rules.json",
                             "predictions": "predictions.parquet", "checksums": artifacts.CHECKSUM_FILE})
    predictions = _prediction_table(model, wd.frame.loc[wd.masks["test"]], run_config, model_id)
    return _write(artifacts_dir, base, run_id, model, frames["test"][base.features].head(500), manifest, metrics,
                  rules, predictions)


def strip_local_paths(published_dir: Path, data_dir: Path) -> list[str]:
    """Rewrite the local data root in the ``publish.json`` of every model of ``published_dir`` as the
    repository-relative ``data/...`` (what the public cleanup did to the earlier models) and refresh its
    ``SHA256SUMS``. Returns the models that changed."""
    from atlas.services import layout, verify

    done = []
    for model_dir in sorted(Path(published_dir).glob("exfuzzy-*")):
        path = model_dir / layout.PUBLISH_INFO_FILE
        text = path.read_text()
        new = text.replace(str(Path(data_dir)) + "/", "data/")
        if new != text:
            path.write_text(new)
            layout.write_checksums(model_dir)
            verify.verify_model_dir(model_dir)
            done.append(model_dir.name)
        if "/home/" in new:
            raise SystemExit(f"{path}: an absolute path is left")
    return done


WRITERS = {"mixture": write_mixture_run, "winning": write_winning_run, "water": write_water_run}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m atlas.ml.publish_ordinal", description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["runs", "strip-paths"])
    parser.add_argument("published_dir", nargs="?", type=Path, help="strip-paths: the published directory")
    parser.add_argument("--tasks", nargs="+", choices=TASKS, default=list(TASKS))
    parser.add_argument("--artifacts-dir", type=Path, default=ARTIFACTS_DIR)
    args = parser.parse_args(argv)
    if args.command == "strip-paths":
        from atlas.paths import DATA_DIR

        print(json.dumps(strip_local_paths(args.published_dir, DATA_DIR), indent=1))
        return
    specs = {t.task_id: t for t in load_config().tasks}
    for k, task in enumerate(args.tasks, 1):
        WRITERS[specs[task].kind](specs[task], args.artifacts_dir)
        print(f"[{k}/{len(args.tasks)}] {task} written", flush=True)


if __name__ == "__main__":
    main()
