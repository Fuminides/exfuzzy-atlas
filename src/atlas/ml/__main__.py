"""CLI: ``python -m atlas.ml {train,evaluate,predict,explain,demo}``. See docs/ml/exfuzzy_api_notes.md."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from atlas.contracts import models as m
from atlas.ml import pipeline
from atlas.ml.fuzzy import FuzzyParams
from atlas.ml.split import chronological_split_spec
from atlas.ml.synthetic import FEATURE_UNITS, FEATURES, TARGET, make_synthetic_table
from atlas.paths import ARTIFACTS_DIR


def demo_config(table: pd.DataFrame, seed: int, fuzzy: FuzzyParams) -> pipeline.RunConfig:
    """Config for the synthetic series (invented data; the run is labelled ``synthetic``)."""
    return pipeline.RunConfig(
        task_id="synthetic_y_h6", domain=m.Domain.AIR, target="y", target_column=TARGET, unit="u", horizon_hours=6,
        features=FEATURES, feature_units=FEATURE_UNITS, persistence_feature="y_t",
        split=chronological_split_spec(table["issued_at_utc"], horizon_hours=6), seed=seed,
        data_version="synthetic-ml-demo", synthetic=True, fuzzy=fuzzy,
    )


def _summary(result: pipeline.RunResult) -> str:
    rows = [r for r in result.metrics.rows if r.slice == "all" and r.metric in ("mae", "rmse", "r2")]
    table = pd.DataFrame([(r.estimator, r.metric, r.value) for r in rows], columns=["estimator", "metric", "value"])
    table = table.pivot(index="estimator", columns="metric", values="value")[["mae", "rmse", "r2"]]
    return f"run: {result.run_dir}\n{table.to_string(float_format=lambda v: f'{v:.3f}')}"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m atlas.ml", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    train = sub.add_parser("train", help="fit the fuzzy model and baselines, write artifacts/<task>/<run>/")
    train.add_argument("--table", type=Path, required=True, help="feature table (parquet)")
    train.add_argument("--config", type=Path, required=True, help="RunConfig as JSON")
    train.add_argument("--artifacts-dir", type=Path, default=ARTIFACTS_DIR)
    for name, text in (("evaluate", "recompute fuzzy metrics and compare with metrics.json"),
                       ("predict", "write predictions for every row of a table"),
                       ("explain", "print the RuleTrace of one entity and issue time")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--run", type=Path, required=True, help="run directory")
        p.add_argument("--table", type=Path, required=True, help="feature table (parquet)")
        if name == "predict":
            p.add_argument("--out", type=Path, required=True)
        if name == "explain":
            p.add_argument("--entity", required=True)
            p.add_argument("--at", required=True, help="issue time, ISO 8601 with Z")
    demo = sub.add_parser("demo", help="train on an invented synthetic series")
    demo.add_argument("--seed", type=int, default=0)
    demo.add_argument("--n-gen", type=int, default=30)
    demo.add_argument("--pop-size", type=int, default=30)
    demo.add_argument("--artifacts-dir", type=Path, default=ARTIFACTS_DIR)
    args = parser.parse_args(argv)

    if args.command == "train":
        config = pipeline.RunConfig.model_validate_json(args.config.read_text())
        print(_summary(pipeline.train_run(pd.read_parquet(args.table), config, artifacts_dir=args.artifacts_dir)))
    elif args.command == "demo":
        table = make_synthetic_table(seed=args.seed)
        config = demo_config(table, args.seed, FuzzyParams(n_gen=args.n_gen, pop_size=args.pop_size))
        print(_summary(pipeline.train_run(table, config, artifacts_dir=args.artifacts_dir)))
    else:
        run, table = pipeline.load_run(args.run), pd.read_parquet(args.table)
        if args.command == "evaluate":
            rows, gap = pipeline.evaluate_run(run, table)
            print(json.dumps({"rows": [r.model_dump() for r in rows if r.slice == "all"], "max_gap_vs_stored": gap}))
        elif args.command == "predict":
            pipeline.predict_table(run, table).to_parquet(args.out, index=False)
            print(f"wrote {args.out}")
        else:
            for trace in pipeline.explain_rows(run, table, args.entity, args.at):
                print(trace.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
