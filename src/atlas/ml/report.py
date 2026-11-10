"""Markdown tables for ``docs/ml/madrid_no2_h6_results.md``, generated from a run and ``summary.json`` (AT-041).

``python -m atlas.ml.report --experiment <experiments/<id>> [--run-dir <run>]`` prints them, so every number in the
write-up comes from the artifacts and not from a hand copy.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from atlas.contracts import models as m

ORDER = ["persistence", "climatology", "climatology_global", "ridge", "hist_gradient_boosting",
         "hist_gradient_boosting_subsample", "exfuzzy"]


def metrics_frame(report: m.MetricsReport) -> pd.DataFrame:
    return pd.DataFrame([r.model_dump() for r in report.rows])


def _md(frame: pd.DataFrame, floatfmt: str = "{:.3f}") -> str:
    cols = [frame.index.name or ""] + [str(c) for c in frame.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for idx, row in frame.iterrows():
        cells = [floatfmt.format(v) if isinstance(v, float) else str(v) for v in row]
        lines.append("| " + " | ".join([str(idx), *cells]) + " |")
    return "\n".join(lines)


def _order(index) -> list[str]:
    known = [e for e in ORDER if e in set(index)]
    return known + sorted(set(index) - set(known))


def overall_table(df: pd.DataFrame, slice_: str, metrics=("mae", "rmse", "r2", "bias")) -> str:
    sel = df[(df.slice == slice_) & df.metric.isin(metrics)]
    wide = sel.pivot(index="estimator", columns="metric", values="value")[[k for k in metrics if k in set(sel.metric)]]
    wide = wide.loc[_order(wide.index)]
    wide.insert(0, "n", sel.groupby("estimator")["n"].first().loc[wide.index].astype(int))
    wide.index.name = "estimator"
    return _md(wide, "{:.2f}")


def slice_table(df: pd.DataFrame, prefix: str, metric: str, estimators: list[str]) -> str:
    sel = df[df.slice.str.startswith(prefix) & (df.metric == metric) & df.estimator.isin(estimators)]
    wide = sel.pivot(index="slice", columns="estimator", values="value")[estimators]
    n = sel[sel.estimator == estimators[0]].set_index("slice")["n"].astype(int)
    wide.insert(0, "n", n.reindex(wide.index))
    wide.index = [s.split("=", 1)[1] for s in wide.index]
    wide.index.name = prefix.rstrip("=")
    return wide


def per_entity_table(df: pd.DataFrame, estimators: list[str], metric: str = "mae") -> str:
    wide = slice_table(df, "entity=", metric, estimators)
    return _md(wide.sort_values(estimators[-1]), "{:.2f}")


def extremes_table(df: pd.DataFrame, estimators: list[str]) -> str:
    sel = df[df.slice.str.startswith("extreme=") & df.estimator.isin(estimators)]
    rows = []
    for (slice_, est), g in sel.groupby(["slice", "estimator"]):
        by = g.set_index("metric")
        rows.append({
            "threshold": slice_.split("=", 1)[1], "estimator": est, "n_events": int(by.loc["mae", "n"]),
            "mae": by.loc["mae", "value"], "bias": by.loc["bias", "value"],
            "event_recall": by.loc["event_recall", "value"],
            "event_precision": by["value"].get("event_precision", float("nan")),
            "n_alarms": int(by.loc["event_precision", "n"]) if "event_precision" in by.index else 0,
        })
    table = pd.DataFrame(rows).set_index(["threshold", "estimator"])
    return _md(table.reset_index().set_index("threshold"), "{:.2f}")


def rules_text(rules: m.ModelRules, metrics_df: pd.DataFrame) -> str:
    act = metrics_df[(metrics_df.estimator == "exfuzzy") & (metrics_df.metric == "rule_mean_activation")
                     & (metrics_df.slice.str.startswith("rule="))].set_index("slice")["value"]
    is_freq = metrics_df.metric.str.startswith("rule_activation_frequency")
    freq = metrics_df[(metrics_df.estimator == "exfuzzy") & is_freq
                      & (metrics_df.slice.str.startswith("rule="))].set_index("slice")["value"]
    lines = ["| rule | IF ... THEN | mean activation (test) | share of rows with activation >= 0.5 (test) |",
             "|---|---|---|---|"]
    for rule in rules.rules:
        key = f"rule={rule.rule_id}"
        lines.append(f"| {rule.rule_id} | {rule.text.removeprefix('IF ')} | {act.get(key, float('nan')):.3f} "
                     f"| {freq.get(key, float('nan')):.3f} |")
    return "\n".join(lines)


def terms_text(rules: m.ModelRules) -> str:
    lines = ["| feature | unit | term | trapezoid (a, b, c, d) |", "|---|---|---|---|"]
    for v in rules.variables:
        for t in v.terms:
            lines.append(f"| {v.feature} | {v.unit} | {t.name} | {', '.join(f'{p:.4g}' for p in t.params)} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m atlas.ml.report")
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, help="default: the published run of summary.json")
    args = parser.parse_args(argv)
    summary = json.loads((args.experiment / "summary.json").read_text())
    run_dir = args.run_dir or Path(summary["published_run"]["run_dir"])
    report = m.MetricsReport.model_validate_json((run_dir / "metrics.json").read_text())
    rules = m.ModelRules.model_validate_json((run_dir / "rules.json").read_text())
    df = metrics_frame(report)
    val = df[df.slice.str.startswith("validation/")].assign(slice=lambda d: d.slice.str.removeprefix("validation/"))
    test = df[~df.slice.str.startswith("validation/")]
    print("## Test overall\n\n" + overall_table(test, "all"))
    print("\n## Validation overall\n\n" + overall_table(val, "all"))
    pair = ["persistence", "hist_gradient_boosting", "exfuzzy"]
    print("\n## Test MAE per station\n\n" + per_entity_table(test, pair))
    for name, title in (("month", "month"), ("hour", "local hour")):
        table = slice_table(test, f"{name}=", "mae", pair).sort_index(key=lambda i: i.astype(int))
        print(f"\n## Test MAE per {title}\n\n" + _md(table, "{:.2f}"))
    print("\n## Test extremes\n\n" + extremes_table(test, pair))
    print("\n## Rules\n\n" + rules_text(rules, test))
    print("\n## Terms\n\n" + terms_text(rules))


if __name__ == "__main__":
    main()
