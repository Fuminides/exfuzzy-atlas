"""Row-by-row parity of a published classifier with native ex_fuzzy (AT-041h; mixture of rules, contract v0.7).

    python -m atlas.ml.publish_parity artifacts/published/<model_id> [...]
    python -m atlas.ml.publish_parity --tables artifacts/published/<model_id> [...]

The family is read from ``rules.json``. A mixture of rules goes to ``check_mixture`` (below). ``--tables`` instead
recomputes, with the ex_fuzzy installed now, the whole firing table and the predictions of any published model
(regression, winning rule or mixture) and compares them with the published files bit for bit: the check that a library
change leaves the served models untouched. Both work through the published period in windows of ``WINDOW_DAYS`` days
(about 21,000 Germany rows), reading only those rows of every file, so memory stays bounded (well under 1 GB).

Winning-rule classifier:

For every published input row with finite inputs it checks, against the pickled model run natively by ex_fuzzy:
the published ``prediction_label``; the published ``is_winner`` rule against ex_fuzzy's winning rule
(``explainable_predict``) and against the first rule of largest association in the rule order (numpy ``argmax``:
what decides a tie); ``association_degree = firing_strength x weight``; and that ``rules.json`` lists the rules in
ex_fuzzy's order with their classes. It also counts the rows whose winner ties at the top with another rule, and with
a rule of another class (a tie is decided by rule order). Reads the whole activation table: for Madrid (~0.2 M rows)
this is seconds; Germany (~3.8 M rows, ~30 M records) needs several GB.
"""

from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

from atlas.explain import classifier as ce
from atlas.explain import mixture as me

KEYS = ["entity_id", "issued_at_utc"]
MIXTURE_TRACE_SAMPLE = 400  # rows a month (spread over its windows) whose RuleTrace (the API's rule-trace) is compared
WINDOW_DAYS = 2  # issue days compared at a time (rows are independent: the window only bounds memory)


def _load(model_dir: Path):
    with open(model_dir / "model.pkl", "rb") as fh:
        return pickle.load(fh)  # noqa: S301 - a published artifact of this repository


def check(model_dir: Path) -> dict:
    model_dir = Path(model_dir)
    rules = json.loads((model_dir / "rules.json").read_text())
    if rules["inference"]["family"] == "rule_mixture_classifier":
        return check_mixture(model_dir)
    model = _load(model_dir)
    rb = ce.get_master_rulebase(model)
    ids, classes = ce.rule_ids(rb), ce.rule_classes(rb)
    labels = [c["label"] for c in rules["target_scheme"]["classes"]]
    order_ok = ([r["rule_id"] for r in rules["rules"]] == ids
                and [r["position"] for r in rules["rules"]] == list(range(len(ids)))
                and all(r["consequent"]["term"] == labels[c] for r, c in zip(rules["rules"], classes, strict=True)))
    inputs = pd.read_parquet(model_dir / "inputs.parquet")
    X = inputs[model.feature_names].to_numpy(dtype=float)
    finite = np.isfinite(X).all(axis=1)
    act = ce.compute_classifier_activations(model, X[finite])
    names = np.array([*model.class_labels, None], dtype=object)
    rule_names = np.array([*ids, None], dtype=object)
    top = act.association.max(axis=1)
    at_top = act.association == top[:, None]
    cls = np.asarray(classes)
    rows = inputs.loc[finite, KEYS].reset_index(drop=True)
    rows["native_label"] = names[np.where(act.prediction < 0, len(model.class_labels), act.prediction)]
    rows["native_winner"] = rule_names[np.where(act.winner < 0, len(ids), act.winner)]
    rows["first_argmax"] = rule_names[np.where(top > 0, act.association.argmax(axis=1), len(ids))]
    rows["tie"] = (at_top.sum(axis=1) > 1) & (top > 0)
    rows["tie_other_class"] = rows["tie"] & np.array([len(set(cls[r])) > 1 for r in at_top])
    preds = pd.read_parquet(model_dir / "predictions.parquet", columns=[*KEYS, "prediction_label", "missing_reason"])
    table = ds.dataset(model_dir / "activations", format="parquet", partitioning="hive").to_table(
        columns=[*KEYS, "rule_id", "firing_strength", "weight", "association_degree", "is_winner"]).to_pandas()
    winners = table.loc[table["is_winner"], [*KEYS, "rule_id"]].rename(columns={"rule_id": "published_winner"})
    merged = rows.merge(preds, on=KEYS, how="left", validate="1:1").merge(winners, on=KEYS, how="left", validate="1:1")

    # a row the publication withholds (NYC, no reference level: null label, prediction_unavailable) although a rule
    # won is not a published prediction: the label comparison leaves it out, as the mixture path does
    withheld = (merged["prediction_label"].isna() & merged["native_label"].notna()
                & (merged["missing_reason"] == "prediction_unavailable"))

    def same(a, b, rows=None):
        equal = (merged[a].astype(object).where(merged[a].notna(), "-")
                 == merged[b].astype(object).where(merged[b].notna(), "-"))
        return float(equal[rows].mean() if rows is not None else equal.mean())

    valid = table.dropna(subset=["association_degree"])
    out = {
        "model_dir": model_dir.name, "rule_weighting": rules["inference"]["rule_weighting"], "n_rules": len(ids),
        "rules_json_in_exfuzzy_order": bool(order_ok), "rows_with_inputs": int(finite.sum()),
        "rows_withheld": int(withheld.sum()),
        "label_equal_native": same("prediction_label", "native_label", ~withheld),
        "published_winner_equal_native": same("published_winner", "native_winner"),
        "native_winner_is_first_argmax_in_rule_order": same("native_winner", "first_argmax"),
        "association_equals_firing_x_weight": bool(np.allclose(
            valid["association_degree"], valid["firing_strength"] * valid["weight"], atol=1e-12)),
        "distinct_weights": sorted({round(float(w), 12) for w in valid["weight"].unique()})[:6],
        "share_rows_tied_at_the_top": float(merged["tie"].mean()),
        "share_rows_tied_with_another_class": float(merged["tie_other_class"].mean()),
    }
    out["ok"] = bool(order_ok and out["association_equals_firing_x_weight"] and min(
        out["label_equal_native"], out["published_winner_equal_native"],
        out["native_winner_is_first_argmax_in_rule_order"]) == 1.0)
    return out


def _objects(values) -> np.ndarray:
    """Values as an object array with every missing value as None (pandas 2 gives None, pandas 3 NaN for strings)."""
    series = pd.Series(values)
    return np.where(series.isna().to_numpy(), None, series.to_numpy(dtype=object))


def _months(model_dir: Path):
    for month_dir in sorted((model_dir / "activations").glob("year=*/month=*")):
        year, month = int(month_dir.parent.name.split("=")[1]), int(month_dir.name.split("=")[1])
        lo = pd.Timestamp(year=year, month=month, day=1, tz="UTC")
        yield lo, lo + pd.DateOffset(months=1), sorted(month_dir.glob("*.parquet"))


def _month_rows(path, lo, hi, columns=None) -> pd.DataFrame:
    """The rows of ``path`` (a file or a list of files) issued in ``[lo, hi)``."""
    return pd.read_parquet(path, columns=columns, filters=[("issued_at_utc", ">=", lo), ("issued_at_utc", "<", hi)])


def _windows(model_dir: Path, days: int = WINDOW_DAYS):
    """``(lo, hi, files, share)`` for every window of ``days`` issue days inside each published month: its bounds, the
    month's activation files and the window's share of the month."""
    for lo, hi, files in _months(model_dir):
        start = lo
        while start < hi:
            end = min(start + pd.Timedelta(days=days), hi)
            yield start, end, files, (end - start) / (hi - lo)
            start = end


def check_mixture(model_dir: Path) -> dict:
    """A published mixture of rules against native ex_fuzzy, every row, in windows of ``WINDOW_DAYS`` (bounded memory).

    Checked exactly (bit for bit): ``rules.json`` lists the rules in ex_fuzzy's order with the fitted ``coef_`` as
    ``class_weights`` and ``intercept_`` as ``class_bias``; for every published row with finite inputs, the label
    against ex_fuzzy ``predict`` (rows withheld by the publish excepted), the firing records against
    ``rule_mixture.rule_firing``, the centred contribution to the predicted class against ``firing x (W - mean W)``
    of ex_fuzzy's weights, ``is_decisive`` against ex_fuzzy's ``RuleMixture.predict`` with the rule's weights at 0, and
    ``top_rule_id`` / ``top_rule_share`` against the first rule of largest positive centred contribution. For
    ``MIXTURE_TRACE_SAMPLE`` rows a month (spread over its windows), the ``RuleTrace`` the API serves
    (``atlas.explain.build_mixture_traces``) is built and its ``class_scores`` and ``class_contributions`` compared
    with ex_fuzzy ``mixture_scores`` and ``mixture_contributions`` on the same rows.
    """
    from atlas.explain import build_mixture_traces

    model = _load(model_dir)
    rules = json.loads((model_dir / "rules.json").read_text())
    rb, est, mixture = ce.get_master_rulebase(model), me.get_estimator(model), me.fitted_mixture(model)
    ids, classes = ce.rule_ids(rb), ce.rule_classes(rb)
    labels = [c["label"] for c in rules["target_scheme"]["classes"]]
    order_ok = ([r["rule_id"] for r in rules["rules"]] == ids
                and [r["position"] for r in rules["rules"]] == list(range(len(ids)))
                and all(r["consequent"]["term"] == labels[c] for r, c in zip(rules["rules"], classes, strict=True)))
    weights_ok = (all(list(r["class_weights"].values()) == [float(w) for w in mixture.coef_[k]]
                      for k, r in enumerate(rules["rules"]))
                  and list(rules["class_bias"].values()) == [float(b) for b in mixture.intercept_])
    names = list(model.feature_names)
    position = {rule_id: k for k, rule_id in enumerate(ids)}
    stats = {"rows_with_inputs": 0, "rows_labelled": 0, "rows_withheld": 0, "label_mismatch": 0,
             "firing_mismatch": 0, "contribution_mismatch": 0, "decisive_mismatch": 0, "top_mismatch": 0,
             "top_share_max_abs_diff": 0.0, "traces_built": 0, "trace_scores_mismatch": 0,
             "trace_contributions_mismatch": 0, "rows_scores_within_1e-12_of_a_tie": 0}
    for lo, hi, files, share in _windows(model_dir):
        inputs = _month_rows(model_dir / "inputs.parquet", lo, hi)
        X = inputs[names].to_numpy(dtype=float)
        finite = np.isfinite(X).all(axis=1)
        rows = inputs.loc[finite, KEYS].reset_index(drop=True)
        if not len(rows):
            continue
        act = me.compute_mixture_activations(model, X[finite])
        stats["rows_with_inputs"] += len(rows)
        top = np.sort(act.scores, axis=1)
        stats["rows_scores_within_1e-12_of_a_tie"] += int((top[:, -1] - top[:, -2] < 1e-12).sum())
        preds = _month_rows(model_dir / "predictions.parquet", lo, hi,
                            [*KEYS, "prediction_label", "missing_reason", "top_rule_id", "top_rule_share"])
        merged = rows.assign(k=np.arange(len(rows))).merge(preds, on=KEYS, how="left", validate="1:1")
        native = np.array([*labels, None], dtype=object)[np.where(act.prediction < 0, len(labels), act.prediction)]
        withheld = merged["prediction_label"].isna() & (act.prediction >= 0) & (
            merged["missing_reason"] == "prediction_unavailable") & np.any(act.firing > 0, axis=1)
        labelled = merged["prediction_label"].notna()
        stats["rows_withheld"] += int(withheld.sum())
        stats["rows_labelled"] += int(labelled.sum())
        published_label = np.where(labelled, _objects(merged["prediction_label"]), None)
        wrong = (labelled & (published_label != native)) | (~labelled & ~withheld & (act.prediction >= 0))
        stats["label_mismatch"] += int(wrong.sum())
        id_names = np.array([*ids, None], dtype=object)
        native_top = np.where(labelled, id_names[np.where(act.top >= 0, act.top, len(ids))], None)
        stats["top_mismatch"] += int((np.where(labelled, _objects(merged["top_rule_id"]), None) != native_top).sum())
        has_top = labelled & merged["top_rule_id"].notna()
        if has_top.any():
            diff = np.abs(merged.loc[has_top, "top_rule_share"].to_numpy() - act.top_share[has_top.to_numpy()])
            stats["top_share_max_abs_diff"] = max(stats["top_share_max_abs_diff"], float(diff.max()))
        table = _month_rows(files, lo, hi, [*KEYS, "rule_id", "firing_strength", "centred_contribution", "is_decisive"])
        table = table.merge(rows.assign(k=np.arange(len(rows))), on=KEYS, how="inner")
        k, r = table["k"].to_numpy(), table["rule_id"].map(position).to_numpy()
        stats["firing_mismatch"] += int((table["firing_strength"].to_numpy() != act.firing[k, r]).sum())
        answered = act.prediction[k] >= 0
        expected = np.where(answered, act.support[k, r], np.nan)
        published = table["centred_contribution"].to_numpy()
        stats["contribution_mismatch"] += int((~((published == expected) | (np.isnan(published) & np.isnan(expected)))
                                               ).sum())
        stats["decisive_mismatch"] += int((table["is_decisive"].to_numpy() != act.decisive[k, r]).sum())
        # the API's rule-trace on a spread sample of the window: scores and contributions are ex_fuzzy's own
        n_sample = min(max(1, round(MIXTURE_TRACE_SAMPLE * share)), len(rows))
        sample = np.unique(np.linspace(0, len(rows) - 1, n_sample).astype(int))
        Xs = pd.DataFrame(X[finite][sample], columns=names)
        traces = build_mixture_traces(
            model, Xs, rows["entity_id"].iloc[sample].tolist(), rows["issued_at_utc"].iloc[sample], class_labels=labels,
            model_id=rules["model_id"], task_id=rules["task_id"], horizon_hours=0, target_unit="-", data_version="-")
        scores, contributions = est.mixture_scores(Xs.to_numpy()), est.mixture_contributions(Xs.to_numpy())
        for i, trace in enumerate(traces):
            stats["traces_built"] += 1
            stats["trace_scores_mismatch"] += int(list(trace.prediction.class_scores.values())
                                                  != [float(v) for v in scores[i]])
            stats["trace_contributions_mismatch"] += int(any(
                list(e.class_contributions.values()) != [float(v) for v in contributions[i, j]]
                for j, e in enumerate(trace.rules)))
    out = {"model_dir": model_dir.name, "family": "rule_mixture_classifier",
           "mixture_weights": rules["inference"]["mixture_weights"], "n_rules": len(ids),
           "rules_json_in_exfuzzy_order": bool(order_ok), "rules_json_weights_equal_coef": bool(weights_ok), **stats}
    out["ok"] = bool(order_ok and weights_ok and stats["rows_with_inputs"] and all(
        stats[k] == 0 for k in ("label_mismatch", "firing_mismatch", "contribution_mismatch", "decisive_mismatch",
                                "top_mismatch", "trace_scores_mismatch", "trace_contributions_mismatch"))
        and stats["top_share_max_abs_diff"] == 0.0)
    return out


def check_tables(model_dir: Path) -> dict:
    """Recompute the firing table and predictions of a published model with the installed ex_fuzzy, in windows of
    ``WINDOW_DAYS``, and compare them with the published ones exactly (NaN == NaN). Any family; nothing is written."""
    from atlas.explain import iter_classifier_firing_tables, iter_firing_tables, iter_mixture_firing_tables
    from atlas.ml.exfuzzy_features import exfuzzy_version

    model_dir = Path(model_dir)
    model = _load(model_dir)
    family = json.loads((model_dir / "rules.json").read_text())["inference"]["family"]
    make = {"rule_mixture_classifier": iter_mixture_firing_tables,
            "winning_rule_classifier": iter_classifier_firing_tables}.get(family, iter_firing_tables)
    names = list(getattr(model, "feature_names", None) or [str(v.name) for v in model.get_rulebase().antecedents])
    out = {"model_dir": model_dir.name, "family": family, "exfuzzy_version": exfuzzy_version(), "records": 0,
           "records_differing": 0, "rows": 0, "predictions_differing": 0, "columns": None}
    for lo, hi, files, _share in _windows(model_dir):
        inputs = _month_rows(model_dir / "inputs.parquet", lo, hi)
        if inputs.empty:
            continue
        fresh = pd.concat(make(model, inputs[names], inputs["entity_id"].tolist(),
                               pd.DatetimeIndex(inputs["issued_at_utc"]), chunk_size=50_000))
        published = _month_rows(files, lo, hi, list(fresh.columns))
        columns = [c for c in fresh.columns if c not in (*KEYS, "rule_id")]
        out["columns"] = columns
        # both in the publish order (rule, issue time, entity), then compared position by position
        frames = []
        for frame in (published, fresh):
            frame = frame.assign(entity_id=frame["entity_id"].astype(str), rule_id=frame["rule_id"].astype(str),
                                 issued_at_utc=pd.DatetimeIndex(frame["issued_at_utc"]).as_unit("us"),
                                 missing_reason=frame["missing_reason"].astype(object))
            frames.append(frame.sort_values(["rule_id", "issued_at_utc", "entity_id"], kind="stable")
                          .reset_index(drop=True))
        a, b = frames
        if len(a) != len(b) or not all(a[c].equals(b[c]) for c in ("rule_id", "issued_at_utc", "entity_id")):
            out["records_differing"] += max(len(a), len(b))
        else:
            differing = np.zeros(len(a), dtype=bool)
            for column in columns:
                x, y = a[column].to_numpy(dtype=object), b[column].to_numpy(dtype=object)
                same = (x == y) | (pd.isna(a[column]).to_numpy() & pd.isna(b[column]).to_numpy())
                differing |= ~same
            out["records_differing"] += int(differing.sum())
        out["records"] += len(a)
        del published, fresh, frames, a, b
        preds = _month_rows(model_dir / "predictions.parquet", lo, hi)
        X = inputs[names]
        if family == "rule_mixture_classifier" or family == "winning_rule_classifier":
            new = pd.Series(model.predict_labels(X), index=inputs.index)
            got = inputs[KEYS].assign(new=new).merge(preds[[*KEYS, "prediction_label"]], on=KEYS)
            kept = got["prediction_label"].notna()  # withheld rows (no reference level) publish no label
            out["predictions_differing"] += int((got.loc[kept, "new"] != got.loc[kept, "prediction_label"]).sum())
        else:
            got = inputs[KEYS].assign(new=model.predict(X)).merge(preds[[*KEYS, "prediction"]], on=KEYS)
            same = (got["new"] == got["prediction"]) | (got["new"].isna() & got["prediction"].isna())
            out["predictions_differing"] += int((~same).sum())
        out["rows"] += len(inputs)
    out["ok"] = out["records"] > 0 and out["records_differing"] == 0 and out["predictions_differing"] == 0
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m atlas.ml.publish_parity", description=__doc__.split("\n\n")[0])
    parser.add_argument("model_dirs", nargs="+", type=Path)
    parser.add_argument("--tables", action="store_true", help="recompute firing tables and predictions with the "
                        "installed ex_fuzzy and compare them with the published files bit for bit (any family)")
    args = parser.parse_args(argv)
    results = [check_tables(d) if args.tables else check(d) for d in args.model_dirs]
    print(json.dumps(results, indent=1))
    if not all(r["ok"] for r in results):
        raise SystemExit("parity failed")


if __name__ == "__main__":
    main()
