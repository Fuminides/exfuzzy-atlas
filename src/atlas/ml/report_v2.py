"""Markdown tables of AT-041d for ``docs/ml/madrid_no2_h6_ica_v2.md``, generated from the experiment artifacts.

::

    python -m atlas.ml.report_v2 partitions --scheme quantile=<experiments/ica-v1> --scheme ica_no2=<dir> ...
    python -m atlas.ml.report_v2 traffic --without <experiments/ica2-traffic-without> --with <.../ica2-traffic-with>

``partitions`` reads, per experiment directory, ``summary_validation.json`` (or ``summary.json``), ``selection.json``
and ``models/rows_seed<k>.json``: validation numbers only, no test row is read. ``traffic`` reads both ``summary.json``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from atlas.ml.experiment_class import FUZZY_CLASSIFIER
from atlas.ml.report_class import _f, _md


def SHAPE_GRID(c: dict) -> bool:  # noqa: N802 - the 6 shapes compared across schemes (the ica-v1 selection had 23)
    return (c["nRules"] in (30, 60) and c["nAnts"] in (2, 3, 4) and c["n_linguistic_variables"] == 3
            and c["rule_weighting"] == "dominance_score" and c["sampling_power"] == 0.5)


def _summary(exp: Path) -> dict:
    name = "summary_validation.json" if (exp / "summary_validation.json").exists() else "summary.json"
    return json.loads((exp / name).read_text())


def _ms(values, digits=3) -> str:
    v = np.asarray(values, dtype=float)
    return f"{v.mean():.{digits}f} ± {v.std(ddof=1):.{digits}f}" if len(v) > 1 else _f(float(v[0]), digits)


def _seed_rows(exp: Path, seeds: list[int]) -> list[pd.DataFrame]:
    return [pd.DataFrame(json.loads((exp / "models" / f"rows_seed{s}.json").read_text())) for s in seeds]


def _value(df: pd.DataFrame, metric: str, slice_: str) -> float:
    sel = df[(df.estimator == FUZZY_CLASSIFIER) & (df.metric == metric) & (df.slice == slice_)]
    return float(sel.value.iloc[0])


def partition_tables(schemes: dict[str, Path]) -> str:
    comparison, per_class, shapes = [], [], []
    labels: list[str] = []
    for name, exp in schemes.items():
        summary, selection = _summary(exp), json.loads((exp / "selection.json").read_text())
        labels = summary["labels"]
        runs, seeds = summary["runs"], [r["seed"] for r in summary["runs"]]
        dfs = _seed_rows(exp, seeds)
        c = summary["chosen"]
        val = [r["validation"] for r in runs]
        stab = summary["rule_stability"]
        comparison.append([
            name, f"{c['nRules']} / {c['nAnts']}", _ms([v["macro_f1"] for v in val]),
            _ms([v["balanced_accuracy"] for v in val]), _ms([v["accuracy"] for v in val]),
            _ms([v["mae_class_index"] for v in val]), _f(float(np.mean([v["share_unknown"] for v in val])), 4),
            f"{np.mean([r['n_rules'] for r in runs]):.1f}",
            _f(float(np.mean([_value(d, "mean_rule_length", "all") for d in dfs])), 2),
            f"{np.mean([_value(d, 'n_duplicate_rules', 'all') for d in dfs]):.1f}",
            f"{np.mean([_value(d, 'n_rules_winning_ge_1pct', 'validation/all') for d in dfs]):.1f}",
            _f(stab["mean_pairwise_jaccard_rule"]), _f(stab["mean_pairwise_jaccard_antecedents"]),
        ])
        for kind in ("recall", "precision"):
            per_class.append([name, kind] + [_ms([v[kind][lab] for v in val if v[kind][lab] is not None], 3)
                                             for lab in labels])
        grid = [f for f in selection["fits"] if SHAPE_GRID(f["candidate"])]
        for f in sorted(grid, key=lambda f: -f["validation"]["macro_f1"]):
            cand = f["candidate"]
            shapes.append([name, f"{cand['nRules']} / {cand['nAnts']}", f["n_rules"],
                           _f(f["validation"]["macro_f1"]), _f(f["validation"]["balanced_accuracy"]),
                           _f(f["validation"]["accuracy"]), "chosen" if cand == selection["chosen"] else ""])
    return "\n\n".join([
        "**Validation 2024, chosen shape per scheme, mean ± sd over the seeds (sd with n-1)**\n\n" + _md(
            ["scheme", "nRules / nAnts", "macro-F1", "bal-acc", "acc", "MAE idx", "unknown", "rules kept",
             "mean length", "duplicates", "rules winning >= 1 %", "Jaccard rules", "Jaccard antecedents"], comparison),
        "**Per-class validation recall and precision (mean ± sd over the seeds)**\n\n" + _md(
            ["scheme", "metric", *labels], per_class),
        "**Shape selection, one fit (seed 0), validation, best first within each scheme**\n\n" + _md(
            ["scheme", "nRules / nAnts", "rules kept", "macro-F1", "bal-acc", "acc", ""], shapes),
    ])


TRAFFIC_ESTIMATORS = [
    "hist_gradient_boosting", "hist_gradient_boosting_balanced", "hist_gradient_boosting_regression_binned",
    "logistic_regression", "logistic_regression_balanced", "random_forest", "random_forest_balanced",
    "hist_gradient_boosting_subsample", "logistic_regression_subsample", "logistic_regression_balanced_subsample",
    "random_forest_subsample", "random_forest_balanced_subsample"]


DETAIL = ["exfuzzy_classifier", "hist_gradient_boosting", "hist_gradient_boosting_subsample", "random_forest",
          "random_forest_subsample"]


def _arm_values(summary: dict, estimator: str, period: str, labels: list[str]) -> dict:
    if estimator == "exfuzzy_classifier":
        runs = [r[period] for r in summary["runs"]]
    else:
        runs = [summary["baselines"][estimator][period]]
    out = {k: [r[k] for r in runs] for k in ("macro_f1", "balanced_accuracy", "accuracy")}
    out["recall"] = {lab: [r["recall"][lab] for r in runs] for lab in labels}
    return out


def traffic_tables(without: Path, with_traffic: Path) -> str:
    arms = {"without traffic": json.loads((without / "summary.json").read_text()),
            "with traffic": json.loads((with_traffic / "summary.json").read_text())}
    labels = arms["without traffic"]["labels"]
    if arms["with traffic"]["labels"] != labels or arms["with traffic"]["n_complete_rows"] != arms[
            "without traffic"]["n_complete_rows"]:
        raise ValueError("the two arms do not share classes and rows")
    seeds = arms["with traffic"]["final_budget"]["seeds"]
    n = arms["with traffic"]["n_complete_rows"]
    out = ["Rows (identical in both arms): " + ", ".join(f"{k} {v:,}" for k, v in n.items())]
    diff_rows = []
    for period in ("validation", "test"):
        rows = []
        for estimator in ("exfuzzy_classifier", *TRAFFIC_ESTIMATORS):
            pair = {arm: _arm_values(summary, estimator, period, labels) for arm, summary in arms.items()}
            w, t = pair["without traffic"], pair["with traffic"]
            diff = {k: float(np.mean(t[k]) - np.mean(w[k])) for k in ("macro_f1", "balanced_accuracy", "accuracy")}
            if estimator in DETAIL:
                for arm, v in pair.items():
                    rows.append([estimator if arm == "without traffic" else "", arm, _ms(v["macro_f1"]),
                                 _ms(v["balanced_accuracy"]), _ms(v["accuracy"])]
                                + [_ms(v["recall"][lab]) for lab in labels])
                rows.append(["", "difference (with - without)", f"{diff['macro_f1']:+.3f}",
                             f"{diff['balanced_accuracy']:+.3f}", f"{diff['accuracy']:+.3f}"]
                            + [f"{np.mean(t['recall'][lab]) - np.mean(w['recall'][lab]):+.3f}" for lab in labels])
            diff_rows.append((estimator, period, float(np.mean(w["macro_f1"])), diff["macro_f1"],
                              diff["balanced_accuracy"]))
        header = ["estimator", "arm", "macro-F1", "bal-acc", "acc", *[f"recall {lab}" for lab in labels]]
        out.append(f"**{period.capitalize()}** (ExFuzzy: mean ± sd over seeds {seeds}; "
                   "baselines: one deterministic fit)\n\n" + _md(header, rows))
    by = {}
    for estimator, period, base, d_f1, d_ba in diff_rows:
        by.setdefault(estimator, {})[period] = (base, d_f1, d_ba)
    table = [[e, _f(v["validation"][0]), f"{v['validation'][1]:+.3f}", f"{v['validation'][2]:+.3f}", _f(v["test"][0]),
              f"{v['test'][1]:+.3f}", f"{v['test'][2]:+.3f}"] for e, v in by.items()]
    out.append("**Difference with - without traffic, every estimator**\n\n" + _md(
        ["estimator", "val macro-F1 without", "val diff macro-F1", "val diff bal-acc", "test macro-F1 without",
         "test diff macro-F1", "test diff bal-acc"], table))
    return "\n\n".join(out)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m atlas.ml.report_v2")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("partitions")
    p.add_argument("--scheme", action="append", required=True, metavar="NAME=DIR")
    t = sub.add_parser("traffic")
    t.add_argument("--without", type=Path, required=True)
    t.add_argument("--with", dest="with_traffic", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "partitions":
        print(partition_tables({s.split("=", 1)[0]: Path(s.split("=", 1)[1]) for s in args.scheme}))
    else:
        print(traffic_tables(args.without, args.with_traffic))


if __name__ == "__main__":
    main()
