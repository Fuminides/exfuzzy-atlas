"""Contract v0.5 over the real published models: importance, summary, input labels and territories.

The expected numbers come from DuckDB/pandas over the published Parquet files and the feature table, never from the
code that wrote ``importance.json`` / ``summary.json``. A model published before v0.5 (no such files) is skipped with
the command that adds them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest
import wording_audit
from qa_support import api_get

BACKFILL = "python -m atlas.services.enrich --published-dir <dir> --model-id <id> --metadata configs/<domain>/..."


@pytest.fixture(scope="module")
def v05(task):
    for name in ("importance.json", "summary.json"):
        if not (task.path / name).is_file():
            pytest.skip(f"{task.model_id} was published before contract v0.5 (no {name}); add it with: {BACKFILL}")
    return task


def test_importance_counts_are_the_winners_of_the_published_predictions(client, v05):
    task = v05
    importance = api_get(client, f"/api/v1/models/{task.model_id}/importance")
    assert importance["task_id"] == task.task_id and importance["model_id"] == task.model_id
    assert [r["rule_id"] for r in importance["rules"]] == task.rule_ids
    assert [v["feature"] for v in importance["variables"]] == [v["feature"] for v in task.rules["variables"]]
    preds = task.preds
    assert {e["entity_id"] for e in importance["entities"]} == set(preds["entity_id"])
    assert sum(e["n_predicted"] for e in importance["entities"]) == importance["n_predicted"]
    if task.mixture:  # contract v0.7: top rules from predictions.parquet, decisive flags from the firing table
        assert importance["measure"] == "rule_mixture"
        labelled = preds[preds["prediction_label"].notna()]
        assert importance["n_predicted"] == len(labelled)
        tops = labelled["top_rule_id"].value_counts()
        glob = str(task.path / "activations" / "*" / "*" / "*.parquet")
        decisive = task._db.execute(
            """
            SELECT a.rule_id, count(*) AS n FROM read_parquet(?, hive_partitioning=true) a
            JOIN read_parquet(?) p ON a.entity_id = p.entity_id AND a.issued_at_utc = p.issued_at_utc
            WHERE a.is_decisive AND p.prediction_label IS NOT NULL GROUP BY 1
            """, [glob, str(task.path / "predictions.parquet")]).df().set_index("rule_id")["n"]
        for rule in importance["rules"]:
            assert rule["n_decided"] is None and rule["decided_share"] is None
            assert rule["n_top"] == int(tops.get(rule["rule_id"], 0))
            assert rule["n_decisive"] == int(decisive.get(rule["rule_id"], 0))
        assert importance["n_no_top_rule"] == int(labelled["top_rule_id"].isna().sum())
    elif task.classifier:
        assert importance["measure"] == "winning_rule"
        labelled = int(preds["prediction_label"].notna().sum())
        assert importance["n_predicted"] == labelled
        glob = str(task.path / "activations" / "*" / "*" / "*.parquet")
        rows = task._db.execute(
            """
            SELECT w.rule_id, count(*) AS n, count(p.observed_label) AS checked,
                   count(*) FILTER (WHERE p.observed_label = p.prediction_label) AS hits,
                   count(*) FILTER (WHERE r.cls <> p.prediction_label) AS wrong_class
            FROM read_parquet(?, hive_partitioning=true) w
            JOIN read_parquet(?) p ON w.entity_id = p.entity_id AND w.issued_at_utc = p.issued_at_utc
            JOIN (SELECT unnest(?) AS rule_id, unnest(?) AS cls) r ON r.rule_id = w.rule_id
            WHERE w.is_winner AND p.prediction_label IS NOT NULL GROUP BY 1
            """,
            [glob, str(task.path / "predictions.parquet"), task.rule_ids,
             [task.class_of_rule[r] for r in task.rule_ids]],
        ).df().set_index("rule_id")
        assert int(rows["n"].sum()) == labelled and int(rows["wrong_class"].sum()) == 0
        for rule in importance["rules"]:
            row = rows.loc[rule["rule_id"]] if rule["rule_id"] in rows.index else None
            n = 0 if row is None else int(row["n"])
            assert rule["n_decided"] == n
            assert rule["n_checked"] == (0 if row is None else int(row["checked"]))
            if rule["n_checked"]:
                assert rule["accuracy"] == pytest.approx(row["hits"] / row["checked"], abs=1e-12)
        unavailable = int((preds["missing_reason"] == "prediction_unavailable").sum())
        # NYC: the rest are predictions withheld without a reference. AT-041h: the unweighted Madrid +6 h rule base
        # fires a rule on every published row, so its count is 0; a weighted model must have some.
        floor = 0 if task.rules["inference"]["rule_weighting"] == "none" else 1
        assert floor <= importance["n_no_rule"] <= unavailable
    else:
        assert importance["measure"] == "weighted_average"
        assert importance["n_predicted"] + importance["n_no_rule"] == int(preds["prediction"].notna().sum())
        assert sum(r["mean_weight_share"] for r in importance["rules"]) == pytest.approx(1.0, abs=1e-9)
        assert sum(r["n_decided"] for r in importance["rules"]) == importance["n_predicted"]


def test_importance_headline_is_consistent_with_the_rules(client, v05):
    task = v05
    importance = api_get(client, f"/api/v1/models/{task.model_id}/importance")
    uses = {r["rule_id"]: {a["feature"] for a in r["antecedents"]} for r in task.rules["rules"]}
    if task.mixture:  # contract v0.7: shares of top rules add up to at most 1; decisive shares are not a partition
        tops = {r["rule_id"]: r["top_contributor_share"] for r in importance["rules"]}
        assert sum(tops.values()) <= 1 + 1e-9
        for variable in importance["variables"]:
            expected = sum(share for rule, share in tops.items() if variable["feature"] in uses[rule])
            assert variable["top_contributor_share"] == pytest.approx(expected, abs=1e-9)
            assert variable["decided_share"] is None
        return
    decided = {r["rule_id"]: r["decided_share"] for r in importance["rules"]}
    if task.classifier:
        assert sum(decided.values()) == pytest.approx(1.0, abs=1e-9)
        for variable in importance["variables"]:
            expected = sum(share for rule, share in decided.items() if variable["feature"] in uses[rule])
            assert variable["decided_share"] == pytest.approx(expected, abs=1e-9)
            assert variable["n_rules"] == sum(variable["feature"] in u for u in uses.values())
    for entity in importance["entities"]:
        shares = sum(r["decided_share"] for r in entity["rules"])
        assert entity["n_predicted"] == 0 or shares == pytest.approx(1.0, abs=1e-9)


def test_summary_counts_each_observed_value_once_for_the_published_entities(client, v05):
    task = v05
    summary = api_get(client, "/api/v1/summary", task_id=task.task_id)
    groups = summary["groups"]
    assert set(groups) == {"all", "year", "month", "hour", "weekday", "entity"}
    total = groups["all"][0]["n"]
    for name, rows in groups.items():
        assert sum(r["n"] for r in rows) == total, name
    assert {r["key"] for r in groups["entity"]} == {
        f["properties"]["entity_id"] for f in task.entities["features"] if f["properties"].get("modelled") is not False}
    assert (summary["classes"] is not None) == (task.task_id in {"madrid_no2_h6", "de_no2_h6"})
    table = task.json("publish.json")["feature_table"]
    pattern = table if "*" in table else str(Path(table) / "**" / "*.parquet")
    if not Path(table).exists():
        pytest.skip(f"the feature table {table} is not on this machine")
    entities = sorted({r["key"] for r in groups["entity"]})
    column = {"nyc_pickups_h1": "issued_at_utc"}.get(task.task_id, "valid_at_utc")
    expected = task._db.execute(
        f"SELECT count(*), min({column}), max({column}), count(DISTINCT (entity_id, {column})) FROM read_parquet(?) "
        "WHERE target IS NOT NULL AND isfinite(target) AND list_contains(?, entity_id)", [pattern, entities]).fetchone()
    assert total == expected[0] == expected[3], "each (entity, time) is one observed value"
    assert pd.Timestamp(summary["period_from_utc"]) == pd.Timestamp(expected[1])
    assert pd.Timestamp(summary["period_to_utc"]) == pd.Timestamp(expected[2])
    if summary["classes"]:
        assert all(r["n"] == 0 or abs(sum(r["shares"]) - 1) < 1e-9 for rows in groups.values() for r in rows)
        classes = summary["classes"]
        n_above = task._db.execute(
            "SELECT count(*) FROM read_parquet(?) WHERE target IS NOT NULL AND isfinite(target) "
            "AND list_contains(?, entity_id) AND floor(target + 0.5) > ?", [pattern, entities, classes[-1]["lower"]],
        ).fetchone()[0]
        assert groups["all"][0]["shares"][-1] == pytest.approx(n_above / total, abs=1e-12)  # the open top class
    else:
        q = groups["all"][0]["quantiles"]
        assert q["p10"] <= q["p25"] <= q["p50"] <= q["p75"] <= q["p90"]


def test_input_labels_state_the_lag_of_the_feature_spec_and_territories_are_set(client, v05):
    task = v05
    rules = api_get(client, f"/api/v1/models/{task.model_id}/rules")
    for variable in rules["variables"]:
        assert variable["label"] and variable["description"], variable["feature"]
        lag = task.spec[variable["feature"]]["lag_hours"]
        for hours in re.findall(r"hace (\d+(?:[.,]\d+)?) h", variable["label"]):
            assert float(hours.replace(",", ".")) == lag, (variable["feature"], variable["label"], lag)
    tasks = {t["task_id"]: t for d in api_get(client, "/api/v1/domains")["domains"] for t in d["tasks"]}
    assert tasks[task.task_id]["territory"] and tasks[task.task_id]["territory_title"]


def test_the_new_payloads_pass_the_wording_audit(client, v05):
    task = v05
    requests = ((f"/api/v1/models/{task.model_id}/importance", {}), ("/api/v1/summary", {"task_id": task.task_id}),
                (f"/api/v1/models/{task.model_id}/rules", {}))
    for path, params in requests:
        found = wording_audit.scan_text(client.get(path, params=params).text, path)
        hits = [h for h in found if h.kind != "other-context"]
        assert hits == [], "\n".join(str(h) for h in hits)
