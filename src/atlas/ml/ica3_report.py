"""Tables and the pre-registered decision of AT-041e, read from the arm files of ``experiment_ica3`` (validation only).

``report`` prints one markdown table per idea and a combined one; ``decide`` applies the rule of
``docs/ml/madrid_no2_h6_ica_v3.md`` section 0 and writes ``decision.json``. Neither reads test rows.
"""

from __future__ import annotations

import json
import pickle
from datetime import datetime, timezone

import numpy as np

from atlas.contracts import models as m
from atlas.ml import artifacts
from atlas.ml.calibration import rule_metric_columns
from atlas.ml.classification import classification_metric_rows, classification_metrics
from atlas.ml.evaluation import classifier_readability_rows
from atlas.ml.exfuzzy_features import exfuzzy_version
from atlas.ml.experiment_class import FUZZY_CLASSIFIER, TARGET_LABEL, _class_prediction_table, _summary
from atlas.ml.experiment_ica3 import SET_KEYS, _json, _xy
from atlas.ml.rules_export import export_classifier_rules

REGULAR, DESFAVORABLE = "Regular", "Desfavorable o peor"
IDEAS = {
    "Idea 1: per-class factor on the association": ["base", "calib"],
    "Idea 2: dominance scores from all training rows": ["base", "natw", "natw_calib", "calib"],
    "Idea 3: consensus rules (stability selection)": [
        "base", "cons_p30", "cons_p30_calib", "cons_p50", "cons_p50_calib", "posthoc_cons_p10",
        "posthoc_cons_p10_calib", "posthoc_cons_p20", "posthoc_cons_p20_calib"],
    "Idea 5: extra inputs": ["base", "feat_trend", "feat_anomaly", "feat_type", "feat_all"],
    "Idea 6: best of k fits by validation": ["base", "restart_k5", "restart_k15"],
}


def _ms(values, digits=3) -> str:
    v = np.asarray(values, dtype=float)
    return f"{v.mean():.{digits}f} ± {v.std(ddof=1):.{digits}f}" if len(v) > 1 else f"{v.mean():.{digits}f}"


def _vals(doc: dict, key: str, sub: str = "validation") -> list[float]:
    return [s[sub][key] for s in doc["seeds"]]


def _class_vals(doc: dict, kind: str, label: str, sub: str = "validation") -> list[float]:
    return [s[sub][kind][label] for s in doc["seeds"] if s[sub][kind][label] is not None]


def arm_stats(doc: dict) -> dict:
    """Mean validation figures of an arm; ``f1_select`` is the cross-fitted macro-F1 for calibrated arms."""
    seeds = doc["seeds"]
    has_cross = all("crossfit" in s for s in seeds)
    st = doc.get("stability")
    return {
        "arm": doc["arm"], "f1": float(np.mean(_vals(doc, "macro_f1"))),
        "f1_select": float(np.mean([s["crossfit"]["macro_f1"] for s in seeds])) if has_cross
        else float(np.mean(_vals(doc, "macro_f1"))),
        "n_rules": float(np.mean([s["n_rules"] for s in seeds])),
        "jaccard": None if not st else st["mean_pairwise_jaccard_rule"],
    }


HEADER = ("| arm | macro-F1 | macro-F1 cross-fit | bal-acc | acc | Regular recall | Regular prec | Desf. recall | "
          "Desf. prec | rules | Jaccard |\n|---|---|---|---|---|---|---|---|---|---|---|")


def arm_line(doc: dict) -> str:
    seeds, st = doc["seeds"], doc.get("stability")
    cross = _ms([s["crossfit"]["macro_f1"] for s in seeds]) if all("crossfit" in s for s in seeds) else "-"
    jac = f"{st['mean_pairwise_jaccard_rule']:.3f}" if st else "-"
    return (f"| {doc['arm']} | {_ms(_vals(doc, 'macro_f1'))} | {cross} | {_ms(_vals(doc, 'balanced_accuracy'))} | "
            f"{_ms(_vals(doc, 'accuracy'))} | {_ms(_class_vals(doc, 'recall', REGULAR))} | "
            f"{_ms(_class_vals(doc, 'precision', REGULAR))} | {_ms(_class_vals(doc, 'recall', DESFAVORABLE))} | "
            f"{_ms(_class_vals(doc, 'precision', DESFAVORABLE))} | "
            f"{np.mean([s['n_rules'] for s in seeds]):.1f} | {jac} |")


def _load(ctx, name: str) -> dict | None:
    return ctx.load_json(name) if ctx.exists(name) else None


def ordinal_table(doc: dict) -> str:
    lines = ["| variant | macro-F1 | macro-F1 cross-fit | bal-acc | acc | Regular recall | Regular prec | "
             "Desf. recall | Desf. prec | MAE class | off by 2+ | inconsistent | any threshold unknown | rules |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    names = sorted(doc["seeds"][0]["variants"])
    for name in names:
        vs = [s["variants"][name] for s in doc["seeds"]]
        cross = _ms([v["crossfit"]["macro_f1"] for v in vs]) if "crossfit" in vs[0] else "-"
        val = [v["validation"] for v in vs]
        lines.append(
            f"| {name} | {_ms([v['macro_f1'] for v in val])} | {cross} | "
            f"{_ms([v['balanced_accuracy'] for v in val])} | "
            f"{_ms([v['accuracy'] for v in val])} | {_ms([v['recall'][REGULAR] for v in val])} | "
            f"{_ms([v['precision'][REGULAR] for v in val])} | {_ms([v['recall'][DESFAVORABLE] for v in val])} | "
            f"{_ms([v['precision'][DESFAVORABLE] for v in val])} | {_ms([v['mae_class_index'] for v in val])} | "
            f"{_ms([v['share_off_by_2plus'] for v in val])} | {_ms([v['inconsistency_rate'] for v in vs])} | "
            f"{_ms([v['share_any_unknown'] for v in vs], 4)} | {np.mean([s['n_rules'] for s in doc['seeds']]):.1f} |")
    return "\n".join(lines)


def consensus_table(docs: list[dict]) -> str:
    lines = ["| arm | set | fits | distinct rules in the pool | rules per fit | single-fit val macro-F1 | "
             "max frequency | consensus rules |", "|---|---|---|---|---|---|---|---|"]
    for doc in docs:
        for key, f in doc["frequency"].items():
            lines.append(f"| {doc['arm']} | {key} | {f['n_fits']} | {f['n_distinct_rules']} | "
                         f"{f['mean_rules_per_fit']:.1f} | {f['mean_single_fit_val_macro_f1']:.3f} | "
                         f"{f['max_frequency']:.2f} | {f['n_consensus']} |")
    return "\n".join(lines)


def report(ctx, test: bool = False) -> None:
    if test:
        raise SystemExit("report never reads test rows")
    out = []
    for title, arms in IDEAS.items():
        docs = [d for d in (_load(ctx, a) for a in arms) if d and d.get("seeds")]
        if len(docs) > 1:
            out += [f"### {title}", "", HEADER, *[arm_line(d) for d in docs], ""]
            cons_docs = [d for d in docs if "frequency" in d]
            if cons_docs:
                out += ["", consensus_table(cons_docs), ""]
    ordinal = _load(ctx, "ordinal")
    if ordinal:
        out += ["### Idea 4: ordinal decomposition (Frank and Hall)", "", ordinal_table(ordinal), ""]
    names = sorted(p.stem for p in (ctx.out / "val").glob("*.json")
                   if p.stem not in {"decision", "ordinal", "control_hgb"})
    docs = [d for d in (_load(ctx, n) for n in names) if d and d.get("seeds")]
    out += ["### All arms", "", HEADER, *[arm_line(d) for d in docs], ""]
    text = "\n".join(out)
    (ctx.out / "report_validation.md").write_text(text + "\n")
    print(text)


def decide(ctx, test: bool = False) -> None:
    """Apply the section 0 rules to the validation files; write ``decision.json``."""
    if test:
        raise SystemExit("decide never reads test rows")
    rule = ctx.cfg.decision
    names = sorted(p.stem for p in (ctx.out / "val").glob("*.json")
                   if p.stem not in {"decision", "ordinal", "control_hgb"} and "posthoc_" not in p.stem)
    stats = {n: arm_stats(d) for n in names if (d := ctx.load_json(n)).get("seeds")}
    base = stats["base"]
    rows = []
    for name, s in stats.items():
        gain = s["f1_select"] - base["f1_select"]
        jac_gain = None if s["jaccard"] is None else s["jaccard"] - base["jaccard"]
        entry = name != "base" and (gain >= rule.min_gain or (
            jac_gain is not None and jac_gain >= rule.jaccard_gain and gain >= -rule.min_gain))
        eligible = s["jaccard"] is not None and s["jaccard"] >= rule.reference_jaccard
        rows.append({**s, "gain_vs_base": gain, "jaccard_gain": jac_gain, "enters_combination": bool(entry),
                     "eligible": bool(eligible)})
    eligible = [r for r in rows if r["eligible"]]
    best = max(eligible, key=lambda r: r["f1_select"])
    close = [r for r in eligible if r["f1_select"] >= best["f1_select"] - rule.tie]
    pick = min(close, key=lambda r: (r["n_rules"], -r["f1_select"]))
    chosen = pick["arm"] if pick["f1_select"] - base["f1_select"] >= rule.min_gain else "base"
    document = {"rule": "docs/ml/madrid_no2_h6_ica_v3.md section 0", "arms": rows, "best_eligible": best["arm"],
                "chosen": chosen, "final_arm": chosen}
    (ctx.out / "val" / "decision.json").write_text(json.dumps(document, indent=2) + "\n")
    print(json.dumps({"enters": [r["arm"] for r in rows if r["enters_combination"]], "best_eligible": best["arm"],
                      "chosen": chosen}, indent=2))


def _unit_models(ctx, doc: dict) -> list[tuple[object, str]]:
    """``(model, unit label)`` of each repeated unit of an arm, from the files the stages saved."""
    out = []
    for rec in doc["seeds"]:
        label = rec["seed"]
        if "picked_fit_seed" in rec:  # restarts: the picked fit of the pool
            path = ctx.out / "pool" / f"{doc['arm'].split('restart')[0]}{label}-seed{rec['picked_fit_seed']}.pkl"
        else:
            kind = "set" if isinstance(label, str) else "seed"
            path = ctx.out / "models" / f"{doc['arm']}-{kind}{label}.pkl"
        with open(path, "rb") as fh:
            out.append((pickle.load(fh), str(label)))  # noqa: S301 - written by experiment_ica3
    return out


def final(ctx, test: bool = False) -> None:
    """Test rows, read once: ``base``, the arm in ``decision.json`` ``final_arm`` and the ``informational_arms``
    (reported, never used to choose); all units; run directories for every arm except ``base``.

    The AT-041d baselines are copied from its ``summary.json`` (same rows, same fits): nothing is refitted.
    """
    if not test:
        raise SystemExit("final reads the test rows: pass --test (it runs once)")
    guard = ctx.out / "final_test.json"
    if guard.exists():
        raise SystemExit(f"{guard} exists: the test rows have been read already")
    decision = json.loads((ctx.out / "val" / "decision.json").read_text())
    arms = list(dict.fromkeys(["base", decision["final_arm"], *decision.get("informational_arms", [])]))
    docs = {a: ctx.load_json(a) for a in arms}
    cds = {a: ctx.class_data(docs[a].get("extras")) for a in arms}
    results: dict = {"final_arm": decision["final_arm"], "informational_arms": decision.get("informational_arms", []),
                     "arms": {}}
    for arm in arms:
        cd = cds[arm]
        X, y, _ = _xy(cd, "test")
        units = []
        for model, label in _unit_models(ctx, docs[arm]):
            units.append({"unit": label, "test": _summary(classification_metrics(y, model.predict(X), len(cd.labels)),
                                                          cd.labels), "n_rules": len(model.rule_base.get_rules())})
        results["arms"][arm] = units
        results["n_test_rows"] = int(len(y))
    summary = json.loads((ctx.base_dir / "summary.json").read_text())
    results["baselines_test"] = {n: v["test"] for n, v in summary["baselines"].items()}
    results["baselines_source"] = "AT-041d ica2-justified/summary.json (same rows and fits; not refitted)"
    guard.write_text(json.dumps(results, indent=2, default=_json) + "\n")
    print(json.dumps({a: [round(u["test"]["macro_f1"], 4) for u in v] for a, v in results["arms"].items()}))
    rundirs(ctx, test=True)


def rundirs(ctx, test: bool = False) -> None:
    """Write the run directories of the arms scored by ``final`` (re-scores the same models; no new decision)."""
    if not test:
        raise SystemExit("rundirs scores the test rows of the models already chosen: pass --test")
    results = json.loads((ctx.out / "final_test.json").read_text())
    for arm in results["arms"]:
        if arm != "base":
            doc = ctx.load_json(arm)
            write_run_dirs(ctx, arm, doc, ctx.class_data(doc.get("extras")), results)


def write_run_dirs(ctx, arm: str, doc: dict, cd, results: dict) -> list:
    """One run directory per unit of the chosen arm: ``artifacts/<task>/ica3-<arm>-<unit>`` (not published)."""
    config, base = ctx.base_cfg, cd.config.base
    d = cd.data
    scheme = cd.scheme.to_target_scheme()
    created, (commit, dirty) = datetime.now(timezone.utc), artifacts.git_state()
    reference = json.loads((ctx.base_dir / "models" / "rows_seed0.json").read_text())
    baseline_rows = [m.MetricRow.model_validate(r) for r in reference if r["estimator"] != FUZZY_CLASSIFIER]
    test_all = d.frame.loc[d.masks["test"]]
    reference_rows = cd.train_sample(config.subsample.n_rows, config.subsample.seed, 0.5)
    dirs = []
    for model, label in _unit_models(ctx, doc):
        kind = "set" if label in SET_KEYS else "seed"
        run_id = f"ica3-{arm}-{kind}{label}"
        model_id = f"exfuzzy-{base.task_id}-{run_id}"
        rows = list(baseline_rows)
        for period in ("validation", "test"):
            X, y, _ = _xy(cd, period)
            prefix = "validation/" if period == "validation" else ""
            pred = model.predict(X)
            rows += classification_metric_rows(FUZZY_CLASSIFIER, y, pred, cd.labels,
                                               {"entity": d.frame["entity_id"].to_numpy()[_xy(cd, period)[2]]},
                                               prefix=prefix)
            rows += classifier_readability_rows(FUZZY_CLASSIFIER, model, X.to_numpy(dtype=float), cd.labels, y, prefix,
                                                include_static=period == "test")
        metrics = m.MetricsReport(model_id=model_id, task_id=base.task_id, split=base.split, rows=rows)
        rules = export_classifier_rules(
            model, model_id=model_id, task_id=base.task_id, domain=base.domain, target_label=TARGET_LABEL,
            target_scheme=scheme, horizon_hours=base.horizon_hours, data_version=base.data_version,
            synthetic=base.synthetic, feature_units=base.feature_units,
            X_reference=d.frame.loc[reference_rows, base.features],
            rule_metrics=rule_metric_columns(model))
        warnings = [
            f"AT-041e arm {arm}: {doc['description']}. Rule weights may be adjusted: see the metrics "
            "dominance_score_raw, class_factor and selection_frequency of each rule. Weights and factors are degrees "
            "of rule match and decision thresholds, not probabilities."]
        if doc.get("extras"):
            warnings.append(f"uses inputs that are not in the AT-041d feature table: {doc['extras']} (needs A1)")
        manifest = m.RunManifest(
            run_id=run_id, model_id=model_id, task_id=base.task_id, domain=base.domain, created_at_utc=created,
            git_commit=commit, git_dirty=dirty, exfuzzy_version=exfuzzy_version(),
            python_version=artifacts.python_version(), seed=int(label) if label.isdigit() else 0, split=base.split,
            data_version=base.data_version, data_checksums=base.data_checksums, target=base.target,
            horizon_hours=base.horizon_hours, features=base.features,
            hyperparameters={**model.params.as_dict(), "task_type": "classification", "target_label": TARGET_LABEL,
                             "class_labels": cd.labels, "official_labels": cd.official.labels, "arm": arm,
                             "unit": label, "ica3_config": json.loads(ctx.cfg.model_dump_json())},
            artifacts={"model": artifacts.MODEL_FILE, "metrics": "metrics.json", "rules": "rules.json",
                       "predictions": "predictions.parquet", "checksums": artifacts.CHECKSUM_FILE},
            warnings=warnings)
        run_dir = artifacts.write_run_dir(
            ctx.out.parent.parent / run_id, model=model,
            parity_sample=d.frame.loc[d.positions("test"), base.features].head(500),
            json_files={"run_manifest.json": manifest.model_dump_json(indent=2) + "\n",
                        "metrics.json": metrics.model_dump_json(indent=2) + "\n",
                        "rules.json": rules.model_dump_json(indent=2) + "\n"},
            parquet_files={"predictions.parquet": _class_prediction_table(model, test_all, cd, model_id)})
        dirs.append(run_dir)
        print(f"wrote {run_dir}")
    return dirs


__all__ = ["report", "decide", "final", "rundirs"]
