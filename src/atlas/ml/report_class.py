"""Markdown tables for ``docs/ml/madrid_no2_h6_ica.md``, generated from the artifacts (AT-041c).

``python -m atlas.ml.report_class --experiment <experiments/<id>> --run-dir <run>`` prints them, so every number in
the write-up comes from ``class_distribution.json``, ``selection.json``, ``summary.json`` and the run's
``metrics.json`` / ``rules.json`` and not from a hand copy.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from atlas.contracts import models as m
from atlas.ml.experiment_class import FUZZY_CLASSIFIER

ORDER = ["persistence", "climatology_majority_class", "hist_gradient_boosting", "hist_gradient_boosting_balanced",
         "hist_gradient_boosting_regression_binned", "logistic_regression", "logistic_regression_balanced",
         "random_forest", "random_forest_balanced", "hist_gradient_boosting_subsample", "logistic_regression_subsample",
         "logistic_regression_balanced_subsample", "random_forest_subsample", "random_forest_balanced_subsample",
         FUZZY_CLASSIFIER]


def _md(header: list[str], rows: list[list]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def _f(v, digits=3) -> str:
    return "" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:.{digits}f}"


def distribution_tables(dist: dict) -> str:
    out = []
    for kind, title in (("official", "Official classes"), ("used", "Classes used by the model")):
        labels = dist["official_labels"] if kind == "official" else dist["used_labels"]
        rows = []
        for period, info in dist["periods"].items():
            rows.append([period, info["n"]] + [f"{info[kind][lab]} ({100 * info[kind + '_share'][lab]:.3f} %)"
                                               for lab in labels])
        out.append(f"**{title}** (complete rows, target at t+6 h)\n\n" + _md(["period", "n", *labels], rows))
    return "\n\n".join(out)


def selection_table(selection: dict) -> str:
    rows = []
    for f in selection["fits"]:
        c, v = f["candidate"], f["validation"]
        rows.append([c["sampling_power"], c["rule_weighting"], c["nRules"], c["nAnts"], c["n_linguistic_variables"],
                     f["n_rules"], _f(f["fit_info"]["train_fitness_macro_f1_penalised"]), _f(v["macro_f1"]),
                     _f(v["balanced_accuracy"]), _f(v["accuracy"]), _f(v["mae_class_index"]),
                     _f(v["share_unknown"]), f"{f['fit_seconds']:.0f}"])
    rows.sort(key=lambda r: -float(r[7]))
    return _md(["power", "weighting", "nRules", "nAnts", "terms", "rules kept", "GA fitness (train)",
                "val macro-F1", "val bal-acc", "val acc", "val MAE idx", "unknown", "fit s"], rows)


def metrics_frame(report: m.MetricsReport) -> pd.DataFrame:
    return pd.DataFrame([r.model_dump() for r in report.rows])


def _order(names) -> list[str]:
    known = [e for e in ORDER if e in set(names)]
    return known + sorted(set(names) - set(known))


def overall_table(df: pd.DataFrame, prefix: str = "") -> str:
    metrics = ["macro_f1", "balanced_accuracy", "accuracy", "mae_class_index", "share_off_by_2plus", "share_unknown"]
    sel = df[(df.slice == prefix + "all") & df.metric.isin(metrics)]
    wide = sel.pivot(index="estimator", columns="metric", values="value")
    rows = [[e] + [_f(wide.loc[e].get(k)) for k in metrics] for e in _order(wide.index)]
    return _md(["estimator", *metrics], rows)


def per_class_table(df: pd.DataFrame, labels: list[str], metric: str, prefix: str = "") -> str:
    sel = df[(df.slice == prefix + "all") & df.metric.str.startswith(metric + "[")]
    wide = sel.pivot(index="estimator", columns="metric", values="value")
    n = sel[sel.estimator == FUZZY_CLASSIFIER].set_index("metric")["n"]
    cols = [f"{metric}[{lab}]" for lab in labels]
    header = ["estimator"] + [f"{lab} (n={int(n.get(c, 0))})" if metric == "recall" else lab
                              for lab, c in zip(labels, cols, strict=True)]
    rows = [[e] + [_f(wide.loc[e].get(c)) for c in cols] for e in _order(wide.index)]
    return _md(header, rows)


def confusion_table(df: pd.DataFrame, estimator: str, labels: list[str], prefix: str = "") -> str:
    cols = [*labels, "no_prediction"]
    sel = df[(df.estimator == estimator) & (df.slice == prefix + "all") & df.metric.str.startswith("confusion[")]
    got = {r.metric: int(r.value) for r in sel.itertuples()}
    rows = [[f"**{t}**"] + [f"{got.get(f'confusion[{t}>{p}]', 0):,}" for p in cols] for t in labels]
    return _md(["observed \\ predicted", *cols], rows)


def station_table(df: pd.DataFrame, estimators: list[str], prefix: str = "") -> str:
    sel = df[df.slice.str.startswith(prefix + "entity=") & (df.metric == "macro_f1") & df.estimator.isin(estimators)]
    wide = sel.pivot(index="slice", columns="estimator", values="value")[estimators]
    wide.index = [i.split("=", 1)[1] for i in wide.index]
    best = wide.idxmax(axis=1).value_counts()
    rows = [[e, _f(wide[e].mean()), _f(wide[e].min()), _f(wide[e].max()), int(best.get(e, 0))] for e in estimators]
    return _md(["estimator", "mean over stations", "min", "max", "stations where best"], rows) \
        + f"\n\n{len(wide)} stations; macro-F1 per station averages only the classes observed at that station."


def seeds_table(summary: dict) -> str:
    rows = []
    for r in summary["runs"]:
        v, t = r["validation"], r["test"]
        rows.append([r["seed"], r["n_rules"], _f(v["macro_f1"]), _f(t["macro_f1"]), _f(t["balanced_accuracy"]),
                     _f(t["accuracy"]), _f(t["mae_class_index"]), _f(t["share_unknown"]), f"{r['fit_seconds']:.0f}"])
    cols = list(zip(*[[float(c) for c in row[2:8]] for row in rows], strict=True))
    rows.append(["mean ± sd", ""] + [f"{np.mean(c):.3f} ± {np.std(c, ddof=1):.3f}" for c in cols] + [""])
    return _md(["seed", "rules", "val macro-F1", "test macro-F1", "test bal-acc", "test acc", "test MAE idx",
                "test unknown", "fit s"], rows)


def seeds_class_f1_table(summary: dict, period: str = "test") -> str:
    """Per-class F1 of every seed (from the stored precision and recall; a class absent from the period is blank)."""
    labels = summary["labels"]
    rows = []
    for r in summary["runs"]:
        got = r[period]
        f1 = [None if got["recall"][lab] is None else
              (0.0 if got["precision"][lab] + got["recall"][lab] == 0 else
               2 * got["precision"][lab] * got["recall"][lab] / (got["precision"][lab] + got["recall"][lab]))
              for lab in labels]
        rows.append([r["seed"], *[_f(v) for v in f1]])
    return _md(["seed", *labels], rows)


def readability_table(df: pd.DataFrame, labels: list[str], stability: dict) -> str:
    sel = df[df.estimator == FUZZY_CLASSIFIER]
    one = {r.metric: r.value for r in sel[sel.slice == "all"].itertuples()}
    val = {r.metric: r.value for r in sel[sel.slice == "validation/all"].itertuples()}
    rows = [["rules", f"{one['n_rules']:.0f}"]]
    rows += [[f"rules for {lab}", f"{one.get(f'n_rules[{lab}]', 0):.0f}"] for lab in labels]
    rows += [["mean rule length (antecedents)", _f(one["mean_rule_length"], 2)],
             ["duplicate rules (same antecedents)", f"{one['n_duplicate_rules']:.0f}"],
             ["antecedent sets used with more than one class", f"{one['n_conflicting_antecedent_sets']:.0f}"],
             ["rules that win at least one validation row", f"{val['n_rules_winning']:.0f}"],
             ["rules that win at least 1 % of validation rows", f"{val['n_rules_winning_ge_1pct']:.0f}"],
             ["share of validation rows with no prediction", _f(val["share_unknown"], 4)],
             ["share of test rows with no prediction", _f(one["share_unknown"], 4)],
             ["Jaccard of rules across seeds (mean over pairs)", _f(stability["mean_pairwise_jaccard_rule"])],
             ["Jaccard of antecedent sets across seeds", _f(stability["mean_pairwise_jaccard_antecedents"])]]
    return _md(["readability metric (published seed)", "value"], rows)


def rules_table(rules: m.ModelRules, df: pd.DataFrame, target_label: str = "ICA") -> str:
    sel = df[(df.estimator == FUZZY_CLASSIFIER) & df.slice.str.startswith("validation/rule=")]
    win = {r.slice.split("=", 1)[1]: r.value for r in sel[sel.metric == "rule_win_share"].itertuples()}
    pre = {r.slice.split("=", 1)[1]: r.value for r in sel[sel.metric == "rule_win_precision"].itertuples()}
    rows = []
    for r in rules.rules:
        ants = " ∧ ".join(f"{a.feature} IS {a.term}" for a in r.antecedents)
        weight = "" if rules.inference.rule_weighting == "none" else f" (peso {r.weight:.2g})"
        rows.append([r.rule_id, f"IF {ants} THEN {target_label} = **{r.consequent.term}**{weight}",
                     f"{100 * win.get(r.rule_id, 0):.1f} %", _f(pre.get(r.rule_id), 2)])
    return _md(["rule", "text", "validation rows decided", "of those, observed class equal"], rows)


def terms_table(rules: m.ModelRules) -> str:
    rows = []
    for v in rules.variables:
        for t in v.terms:
            rows.append([v.feature, v.unit or "", t.name, t.membership_type, ", ".join(f"{p:.6g}" for p in t.params)])
    return _md(["feature", "unit", "term", "type", "parameters"], rows)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m atlas.ml.report_class")
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    exp = args.experiment
    dist = json.loads((exp / "class_distribution.json").read_text())
    selection = json.loads((exp / "selection.json").read_text())
    summary = json.loads((exp / "summary.json").read_text())
    report = m.MetricsReport.model_validate_json((args.run_dir / "metrics.json").read_text())
    rules = m.ModelRules.model_validate_json((args.run_dir / "rules.json").read_text())
    manifest = m.RunManifest.model_validate_json((args.run_dir / "run_manifest.json").read_text())
    target_label = manifest.hyperparameters.get("target_label", "ICA")
    df = metrics_frame(report)
    labels = summary["labels"]
    sections = [
        ("Class distribution", distribution_tables(dist)),
        ("Selection (validation)", selection_table(selection)),
        ("Test overall", overall_table(df)),
        ("Validation overall", overall_table(df, "validation/")),
        ("Test recall per class", per_class_table(df, labels, "recall")),
        ("Test precision per class", per_class_table(df, labels, "precision")),
        ("Test F1 per class", per_class_table(df, labels, "f1")),
        ("Test F1 per class, ExFuzzy seeds", seeds_class_f1_table(summary)),
        ("Validation F1 per class, ExFuzzy seeds", seeds_class_f1_table(summary, "validation")),
        ("Test confusion matrix, ExFuzzy classifier", confusion_table(df, FUZZY_CLASSIFIER, labels)),
        ("Test confusion matrix, persistence", confusion_table(df, "persistence", labels)),
        ("Test confusion matrix, HGB classifier", confusion_table(df, "hist_gradient_boosting", labels)),
        ("Test macro-F1 per station", station_table(df, [e for e in _order(set(df.estimator)) if e in (
            "persistence", "climatology_majority_class", "hist_gradient_boosting", FUZZY_CLASSIFIER)])),
        ("Seeds", seeds_table(summary)),
        ("Readability", readability_table(df, labels, summary["rule_stability"])),
        ("Rules of the published model", rules_table(rules, df, target_label)),
        ("Linguistic terms", terms_table(rules)),
    ]
    for title, body in sections:
        print(f"## {title}\n\n{body}\n")


if __name__ == "__main__":
    main()
