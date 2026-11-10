"""AT-062 #5: classifiers publish labels only; the winner is the argmax association (v0.7 mixture: the class is the
argmax of the class scores and the top rule the largest centred support); trace == series == published."""

from __future__ import annotations

import json
import re

import pandas as pd
import pytest
from qa_support import REPO, api_get, series, trace

ICA_CONFIG = REPO / "configs" / "ml" / "ica_no2_scheme.json"
NYC_CONFIG = REPO / "configs" / "mobility" / "nyc_level_scheme.json"


def _classifier(task):
    if not task.classifier:
        pytest.skip("regression task")


def test_no_numeric_prediction_is_published_for_a_classifier(client, task):
    _classifier(task)
    assert task.preds["prediction"].isna().all(), "predictions.parquet holds a numeric prediction for a classifier"
    for _, row in task.sample_rows(3, "nonumber").iterrows():
        pt = series(
            client, task, row["entity_id"], row["issued_at_utc"], row["issued_at_utc"] + pd.Timedelta(seconds=1)
        )["points"][0]
        assert pt["prediction"] is None
        tr = trace(client, task, row["entity_id"], row["issued_at_utc"])
        assert tr["prediction"]["value"] is None
    # the model's own consequents are classes, not numbers
    assert all(r["consequent"]["type"] == "class" and r["consequent"]["value"] is None for r in task.rules["rules"])


def test_regression_publishes_numbers_and_no_labels(client, task):
    if task.classifier:
        pytest.skip("classifier task")
    assert task.preds["prediction"].notna().sum() > 0
    assert "prediction_label" not in task.preds.columns and not task.rules.get("target_scheme")
    pt = series(client, task, task.preds["entity_id"].iloc[0], None, None)["points"]
    assert all(p["predicted_label"] is None and p["observed_label"] is None for p in pt)


def test_labels_belong_to_the_target_scheme(client, task):
    _classifier(task)
    labels = set(task.labels)
    assert len(labels) >= 2
    assert set(task.preds["prediction_label"].dropna()) <= labels
    assert set(task.preds["observed_label"].dropna()) <= labels
    assert set(task.class_of_rule.values()) <= labels
    card = api_get(client, f"/api/v1/models/{task.model_id}")
    assert [c["label"] for c in card["target_scheme"]["classes"]] == task.labels
    classes = task.rules["target_scheme"]["classes"]
    bounds = [(c["lower"], c["upper"]) for c in classes]
    assert all(a[1] == b[0] for a, b in zip(bounds, bounds[1:], strict=False)), "scheme classes must be contiguous"


def test_winning_rule_is_the_argmax_association_and_trace_series_and_table_agree(client, task):
    _classifier(task)
    if task.mixture:
        pytest.skip("mixture of rules: no winning rule (see the mixture test below)")
    checked = {"label": 0, "none": 0}
    for _, row in task.sample_rows(8, "winner").iterrows():
        t, eid = row["issued_at_utc"], row["entity_id"]
        act = task.activations("entity_id = ? AND issued_at_utc = ?", [eid, t.to_pydatetime()])
        tr = trace(client, task, eid, t)
        pt = series(client, task, eid, t, t + pd.Timedelta(seconds=1))["points"][0]
        published = None if pd.isna(row["prediction_label"]) else row["prediction_label"]
        assert pt["predicted_label"] == published, "series label differs from predictions.parquet"
        assert tr["prediction"]["label"] == published, f"trace label != published label at {eid} {t}"
        valid = act.dropna(subset=["association_degree"])
        if valid.empty or valid["association_degree"].max() <= 0:
            assert published is None
            assert tr["prediction"]["winning_rule_id"] is None
            assert (
                tr["prediction"]["missing_reason"] == "prediction_unavailable"
                or row["missing_reason"] == "missing_input"
            )
            checked["none"] += 1
            continue
        if published is None:  # a row whose label is withheld although a rule won (no reference level)
            assert (
                tr["prediction"]["winning_rule_id"] is None
                and tr["prediction"]["missing_reason"] == "prediction_unavailable"
            )
            continue
        winner = valid.loc[valid["association_degree"].idxmax(), "rule_id"]  # first on ties, like numpy argmax
        assert tr["prediction"]["winning_rule_id"] == winner
        assert task.class_of_rule[winner] == published, "the published class is not the winning rule's consequent"
        assert act.loc[act["is_winner"], "rule_id"].tolist() == [winner]
        by_rule = {r["rule_id"]: r for r in tr["rules"]}
        best = max(by_rule.values(), key=lambda r: r["association_degree"])
        assert by_rule[winner]["association_degree"] == pytest.approx(best["association_degree"], abs=1e-12)
        for r in tr["rules"]:  # association = firing x weight (ex_fuzzy dominance score)
            assert r["association_degree"] == pytest.approx(r["firing_strength"] * r["weight"], abs=1e-9)
        checked["label"] += 1
    assert checked["label"] > 0


def test_mixture_class_is_the_argmax_score_and_the_top_rule_the_largest_centred_support(client, task):
    """Contract v0.7: scores = bias + sum of weight x firing; label = first argmax; no winning rule; the top rule of the
    trace is the published one and the first record of largest positive centred contribution in the firing table."""
    if not task.mixture:
        pytest.skip("not a mixture of rules")
    order = task.labels
    weights = {r["rule_id"]: r["class_weights"] for r in task.rules["rules"]}
    checked = 0
    for _, row in task.sample_rows(8, "mixture").iterrows():
        t, eid = row["issued_at_utc"], row["entity_id"]
        tr = trace(client, task, eid, t)
        pt = series(client, task, eid, t, t + pd.Timedelta(seconds=1))["points"][0]
        published = None if pd.isna(row["prediction_label"]) else row["prediction_label"]
        assert pt["predicted_label"] == published and tr["prediction"]["label"] == published
        assert tr["prediction"]["winning_rule_id"] is None
        if not tr["rules"]:
            assert row["missing_reason"] == "missing_input"
            continue
        p = tr["prediction"]
        for c in order:
            rebuilt = p["class_bias"][c] + sum(r["class_contributions"][c] for r in tr["rules"])
            assert p["class_scores"][c] == pytest.approx(rebuilt, abs=1e-9)
        for r in tr["rules"]:
            assert r["class_weights"] == weights[r["rule_id"]]
            for c in order:
                assert r["class_contributions"][c] == pytest.approx(r["firing_strength"] * weights[r["rule_id"]][c],
                                                                    abs=1e-12)
        if published is None:
            assert p["top_rule_id"] is None
            continue
        scores = [p["class_scores"][c] for c in order]
        assert published == order[scores.index(max(scores))]
        expected_top = None if pd.isna(row["top_rule_id"]) else row["top_rule_id"]
        assert p["top_rule_id"] == expected_top
        act = task.activations("entity_id = ? AND issued_at_utc = ?", [eid, t.to_pydatetime()])
        best = act.sort_values(["centred_contribution", "rule_id"], ascending=[False, True]).iloc[0]
        assert expected_top == (best["rule_id"] if best["centred_contribution"] > 0 else None)
        checked += 1
    assert checked > 0


def test_rows_without_a_class_keep_their_rule_firings_in_the_trace(client, task):
    """#51: a null label comes with prediction_unavailable, in the series and in the trace, and firings are kept."""
    _classifier(task)
    rows = task.preds[task.preds["missing_reason"] == "prediction_unavailable"]
    if rows.empty and (task.mixture or task.rules["inference"]["rule_weighting"] == "none"):
        # AT-041h: the unweighted Madrid +6 h rule base fires a rule on every published row (wind and yesterday
        # rules cover every input), so it has no "no rule fired" row to check; a weighted model must have some.
        pytest.skip(f"{task.model_id}: every published row has a class (no row where no rule fires)")
    assert len(rows) > 0
    seen_firing = 0
    for _, row in rows.iloc[:: max(1, len(rows) // 12)].iloc[:12].iterrows():
        t, eid = row["issued_at_utc"], row["entity_id"]
        assert pd.isna(row["prediction_label"])
        pt = series(client, task, eid, t, t + pd.Timedelta(seconds=1))["points"][0]
        assert (
            pt["predicted_label"] is None
            and pt["prediction"] is None
            and pt["missing_reason"] == "prediction_unavailable"
        )
        tr = trace(client, task, eid, t)
        assert tr["prediction"]["label"] is None and tr["prediction"]["winning_rule_id"] is None
        assert tr["prediction"]["missing_reason"] == "prediction_unavailable"
        assert len(tr["rules"]) == len(task.rule_ids), "the firings must stay listed"
        seen_firing += any(r["firing_strength"] > 0 for r in tr["rules"])
    if task.task_id == "nyc_pickups_h1":
        assert seen_firing > 0, "NYC sin-referencia rows: the engine firings were dropped from the trace"


def test_ica_scheme_matches_the_config_with_the_documented_merged_upper_class(client, task):
    if task.task_id != "madrid_no2_h6":
        pytest.skip("ICA scheme")
    official = json.loads(ICA_CONFIG.read_text(encoding="utf-8"))
    published = api_get(client, f"/api/v1/models/{task.model_id}/rules")["target_scheme"]
    card = api_get(client, f"/api/v1/models/{task.model_id}")["target_scheme"]
    assert published == card
    for key in ("source_url", "unit"):
        assert published[key] == official[key]
    assert published["boundary"] == "upper_inclusive"
    off, pub = official["classes"], published["classes"]
    assert [c["label"] for c in pub[:3]] == [c["label"] for c in off[:3]]
    for i, (a, b) in enumerate(zip(pub[:3], off[:3], strict=True)):
        assert (a["upper"], a["color"], a["description"]) == (b["upper"], b["color"], b["description"])
        assert a["lower"] == (None if i == 0 else pub[i - 1]["upper"])
    merged = pub[3]
    # classes 4-6 (Desfavorable, Muy desfavorable, Extremadamente desfavorable) are one class, labelled as merged
    assert merged["label"] == "Desfavorable o peor"
    assert merged["lower"] == off[2]["upper"] == 120 and merged["upper"] == off[-1]["upper"] == 1000
    assert merged["color"] == off[3]["color"]
    assert len(pub) == 4 and len(off) == 6
    docs = (REPO / "docs" / "ml" / "madrid_no2_h6_ica_v2.md").read_text(encoding="utf-8")
    assert "Desfavorable o peor" in docs and re.search(r"121-1000|merged class 121", docs), (
        "the merge must be documented"
    )


def test_nyc_level_scheme_matches_its_config(client, task):
    if task.task_id != "nyc_pickups_h1":
        pytest.skip("NYC scheme")
    cfg = json.loads(NYC_CONFIG.read_text(encoding="utf-8"))
    pub = api_get(client, f"/api/v1/models/{task.model_id}/rules")["target_scheme"]
    assert pub["boundary"] == cfg["boundary"] == "lower_inclusive"
    assert [(c["label"], c["lower"], c["upper"], c["color"]) for c in pub["classes"]] == [
        (c["label"], c["lower"], c["upper"], c["color"]) for c in cfg["classes"]
    ]
    assert "percentil" in pub["unit"].lower(), "the NYC scheme must say it is a relative level, not a trip count"
