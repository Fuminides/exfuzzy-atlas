"""Rule and input importance of a published model (contract v0.5, ``GET /api/v1/models/{model_id}/importance``).

Computed once, from what was published (``activations/`` and ``predictions.parquet``), and stored as
``importance.json``. Nothing here reruns the model and nothing uses the activation of a rule as a measure of importance:

* Classifier (``winning_rule``): each published prediction (one with a class label) is decided by exactly one rule, the
  record with ``is_winner``. ``decided_share`` is the share of predictions a rule decides; ``accuracy`` the share of
  those, among the ones with an observed class, whose predicted class is the observed one.
* Regression, TSK zero order and additive (``weighted_average``): the share of a rule in one prediction is
  ``effective_firing / sum(effective_firing)``, and ``sum(share * consequent)`` is the published prediction. The
  check against ``predictions.parquet`` is part of the computation and raises when it fails. A rule "decides" a
  prediction when its share is the largest (ties: the lowest position); ``mae`` is the error of those predictions
  that have an observation.
* Mixture of rules (``rule_mixture``, contract v0.7): no rule decides alone. ``top_contributor_share`` is the share of
  predictions whose top rule (``top_rule_id`` of ``predictions.parquet``: the largest positive centred contribution to
  the predicted class) is the rule, and ``accuracy`` is computed on those; ``decisive_share`` is the share of
  predictions whose class would change if the rule's weights were 0 (``is_decisive`` of the firing table, computed at
  publish time by ex_fuzzy with that rule's weights removed: exact, and affordable because it is one extra product of
  the firing matrix per rule). Per input: the share of predictions whose top rule uses it, and the share for which at
  least one rule that uses it is decisive. The top rule of each prediction is checked against the firing table.
* An issue time with complete inputs where no rule fired counts in ``n_no_rule`` and is attributed to no rule. A
  prediction that the publish withheld although a rule fired (NYC rows without a reference level, which have no class
  label) is not a published prediction: it is in neither count (``n_withheld`` of the returned checks).

Memory is bounded by one UTC month of activation records: the activations are read month by month (the layout of
``atlas.services.publish``) and only counters are carried between months.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from atlas.contracts import models as m
from atlas.explain.engine import COVERAGE_EPSILON
from atlas.services import layout

PARITY_TOLERANCE = 1e-9  # sum(share x consequent) against the published prediction


class ImportanceError(ValueError):
    """The published files do not agree with each other: nothing is written."""


@dataclass
class _Counts:
    """Additive counters, merged month by month."""

    by_rule: pd.DataFrame = field(default_factory=pd.DataFrame)  # (entity_id, rule_id) -> counters
    n_predicted: int = 0
    n_no_rule: int = 0
    n_withheld: int = 0
    n_missing_input: int = 0
    max_abs_error: float = 0.0
    n_fallback: int = 0
    observed: dict[str, int] = field(default_factory=dict)  # classifiers: observed label -> checked predictions
    n_no_top: int = 0  # mixture: predictions without a rule that supports the predicted class
    variable_decisive: dict[str, int] = field(default_factory=dict)  # mixture: feature -> predictions

    def add(self, frame: pd.DataFrame) -> None:
        both = frame if self.by_rule.empty else pd.concat([self.by_rule, frame])
        self.by_rule = both.groupby(["entity_id", "rule_id"], sort=False).sum().reset_index()


def _months(model_dir: Path) -> Iterator[tuple[datetime, datetime, list[str]]]:
    """``(lo, hi, files)`` for every month of the activations layout, in time order."""
    for month_dir in sorted((model_dir / layout.ACTIVATIONS_DIR).glob("year=*/month=*")):
        files = sorted(str(p) for p in month_dir.glob("*.parquet"))
        year, month = int(month_dir.parent.name.split("=")[1]), int(month_dir.name.split("=")[1])
        lo = datetime(year, month, 1, tzinfo=timezone.utc)
        hi = datetime(year + month // 12, month % 12 + 1, 1, tzinfo=timezone.utc)
        if files:
            yield lo, hi, files


def weight_shares(act: pd.DataFrame, position: dict[str, int]) -> pd.Series:
    """Add ``pos``, ``total`` and ``share`` (f_r / sum f) to the rows ``act`` of the additive TSK firing records.

    ``act`` has ``entity_id``, ``issued_at_utc``, ``rule_id`` and ``effective_firing`` (non-null), with all the rules
    of every (entity, issue time) in it. Returns the mask of the rows whose (entity, issue time) is covered (total above
    ``COVERAGE_EPSILON``); the share of the others is 0.
    """
    key = ["entity_id", "issued_at_utc"]
    act["pos"] = act["rule_id"].map(position)
    act["total"] = act.groupby(key)["effective_firing"].transform("sum")
    covered = act["total"] > COVERAGE_EPSILON
    act["share"] = np.where(covered, act["effective_firing"] / act["total"].where(covered, 1.0), 0.0)
    return covered


def deciding_rows(fired: pd.DataFrame) -> pd.DataFrame:
    """One row per (entity, issue time) of ``fired`` (covered rows with ``share`` and ``pos``): the deciding rule.

    It is the one with the largest share, ties to the lowest position. This is the definition of "decides" of
    ``compute_importance`` and of ``decided_by_rule_id`` in ``GET /predictions``.
    """
    key = ["entity_id", "issued_at_utc"]
    return fired.sort_values([*key, "share", "pos"], ascending=[True, True, False, True]).drop_duplicates(key)


def _classifier_month(
    con, predictions: str, files: list[str], lo, hi, class_of: dict[str, str], counts: _Counts,
) -> int:
    """Add one month; returns the number of prediction rows seen."""
    df = con.execute(
        """
        WITH w AS (
            SELECT entity_id, CAST(issued_at_utc AS TIMESTAMPTZ) AS issued_at_utc, count(*) AS n_win,
                   min(rule_id) AS winner
            FROM read_parquet(?) WHERE is_winner GROUP BY 1, 2)
        SELECT coalesce(p.entity_id, w.entity_id) AS entity_id, p.entity_id IS NULL AS orphan,
               p.prediction_label, p.observed_label, p.missing_reason, w.n_win, w.winner
        FROM (SELECT * FROM (
                   SELECT * REPLACE (CAST(issued_at_utc AS TIMESTAMPTZ) AS issued_at_utc) FROM read_parquet(?))
               WHERE issued_at_utc >= ? AND issued_at_utc < ?) p
        FULL OUTER JOIN w ON p.entity_id = w.entity_id AND p.issued_at_utc = w.issued_at_utc
        """,
        [files, predictions, lo, hi],
    ).df()
    if df["orphan"].any():
        raise ImportanceError(
            f"{int(df['orphan'].sum())} winning-rule records have no published prediction in {lo:%Y-%m}")
    df = df.drop(columns="orphan")
    labelled = df["prediction_label"].notna()
    if (df.loc[labelled, "n_win"] != 1).any():
        raise ImportanceError(f"a published class label without exactly one winning rule in {lo:%Y-%m}")
    won = df[labelled]
    if (won["missing_reason"].notna()).any():
        raise ImportanceError(f"a published class label with a missing_reason in {lo:%Y-%m}")
    if (won["winner"].map(class_of) != won["prediction_label"]).any():
        raise ImportanceError(f"the class of the winning rule differs from prediction_label in {lo:%Y-%m}")
    rest = df[~labelled]
    reasons = set(rest["missing_reason"].dropna()) - {m.MissingReason.MISSING_INPUT.value,
                                                       m.MissingReason.PREDICTION_UNAVAILABLE.value}
    if reasons or rest["missing_reason"].isna().any():
        raise ImportanceError(f"unexpected missing reasons without a label in {lo:%Y-%m}: {sorted(reasons)}")
    missing_input = rest["missing_reason"] == m.MissingReason.MISSING_INPUT.value
    if rest.loc[missing_input, "n_win"].notna().any():
        raise ImportanceError(f"a winning rule on a row with missing input in {lo:%Y-%m}")
    unavailable = rest[~missing_input]
    counts.n_missing_input += int(missing_input.sum())
    counts.n_no_rule += int(unavailable["n_win"].isna().sum())
    counts.n_withheld += int(unavailable["n_win"].notna().sum())
    counts.n_predicted += len(won)
    checked = won["observed_label"].notna()
    frame = pd.DataFrame({
        "entity_id": won["entity_id"].to_numpy(), "rule_id": won["winner"].to_numpy(), "n_decided": 1,
        "n_checked": checked.astype(int).to_numpy(),
        "n_hit": (checked & (won["observed_label"] == won["prediction_label"])).astype(int).to_numpy(),
    })
    counts.add(frame)
    for label, k in won.loc[checked, "observed_label"].value_counts().items():
        counts.observed[label] = counts.observed.get(label, 0) + int(k)
    return len(df)


def _mixture_month(
    con, predictions: str, files: list[str], lo, hi, users: dict[str, list[str]], counts: _Counts,
) -> int:
    """Add one month of a mixture of rules; returns the number of prediction rows seen."""
    key = ["entity_id", "issued_at_utc"]
    pred = con.execute(
        "SELECT entity_id, issued_at_utc, prediction_label, observed_label, missing_reason, top_rule_id "
        "FROM (SELECT * REPLACE (CAST(issued_at_utc AS TIMESTAMPTZ) AS issued_at_utc) FROM read_parquet(?)) "
        "WHERE issued_at_utc >= ? AND issued_at_utc < ?", [predictions, lo, hi],
    ).df()
    # per row: record counts and the first rule (rule ids are positional and of equal width) of largest centred
    # contribution to the predicted class, which must be the published top rule when that contribution is positive
    rows = con.execute(
        """
        SELECT entity_id, issued_at_utc, n_records, n_valid, n_fired, best, rule_id AS first_best FROM (
            SELECT entity_id, CAST(issued_at_utc AS TIMESTAMPTZ) AS issued_at_utc, rule_id, centred_contribution,
                   count(*) OVER w AS n_records, count(firing_strength) OVER w AS n_valid,
                   count(*) FILTER (WHERE firing_strength > 0) OVER w AS n_fired,
                   max(centred_contribution) OVER w AS best,
                   row_number() OVER (PARTITION BY entity_id, issued_at_utc
                                      ORDER BY centred_contribution DESC NULLS LAST, rule_id) AS k
            FROM read_parquet(?) WINDOW w AS (PARTITION BY entity_id, issued_at_utc))
        WHERE k = 1
        """, [files],
    ).df()
    joined = pred.merge(rows, on=key, how="outer", indicator=True)
    if (joined["_merge"] == "right_only").any():
        raise ImportanceError(f"firing records without a published prediction in {lo:%Y-%m}")
    labelled = joined["prediction_label"].notna()
    won = joined[labelled]
    if won["missing_reason"].notna().any():
        raise ImportanceError(f"a published class label with a missing_reason in {lo:%Y-%m}")
    if won["n_records"].isna().any() or (won["n_valid"] != won["n_records"]).any():
        raise ImportanceError(f"a published class label without complete firing records in {lo:%Y-%m}")
    has_top = won["top_rule_id"].notna()
    wrong_top = won.loc[has_top, "first_best"] != won.loc[has_top, "top_rule_id"]
    if ((won["best"] > 0) != has_top).any() or wrong_top.any():
        raise ImportanceError(f"top_rule_id is not the first rule of largest positive centred contribution in "
                              f"{lo:%Y-%m}")
    rest = joined[~labelled]
    reasons = set(rest["missing_reason"].dropna()) - {m.MissingReason.MISSING_INPUT.value,
                                                       m.MissingReason.PREDICTION_UNAVAILABLE.value}
    if reasons or rest["missing_reason"].isna().any() or rest["top_rule_id"].notna().any():
        raise ImportanceError(f"unexpected rows without a label in {lo:%Y-%m}: {sorted(reasons)}")
    missing_input = rest["missing_reason"] == m.MissingReason.MISSING_INPUT.value
    if (rest.loc[missing_input, "n_valid"] > 0).any():
        raise ImportanceError(f"firing values on a row with missing input in {lo:%Y-%m}")
    unavailable = rest[~missing_input]
    counts.n_missing_input += int(missing_input.sum())
    counts.n_no_rule += int((unavailable["n_fired"] == 0).sum())
    counts.n_withheld += int((unavailable["n_fired"] > 0).sum())
    counts.n_predicted += len(won)
    counts.n_no_top += int((~has_top).sum())

    top = won[has_top]
    checked = top["observed_label"].notna()
    frame = pd.DataFrame({
        "entity_id": top["entity_id"].to_numpy(), "rule_id": top["top_rule_id"].to_numpy(), "n_top": 1,
        "n_checked": checked.astype(int).to_numpy(),
        "n_hit": (checked & (top["observed_label"] == top["prediction_label"])).astype(int).to_numpy(),
        "n_decisive": 0,
    })
    # decisive records of the published predictions only (a withheld row has engine flags but no prediction)
    decisive = con.execute(
        "SELECT entity_id, CAST(issued_at_utc AS TIMESTAMPTZ) AS issued_at_utc, rule_id FROM read_parquet(?) "
        "WHERE is_decisive", [files]).df().merge(won[key], on=key, how="inner")
    frame = pd.concat([frame, decisive.groupby(["entity_id", "rule_id"], sort=False).size().reset_index(
        name="n_decisive").assign(n_top=0, n_checked=0, n_hit=0)], ignore_index=True)
    counts.add(frame.groupby(["entity_id", "rule_id"], sort=False).sum().reset_index())
    for feature, rule_ids in users.items():
        hit = decisive.loc[decisive["rule_id"].isin(rule_ids), key].drop_duplicates()
        counts.variable_decisive[feature] = counts.variable_decisive.get(feature, 0) + len(hit)
    for label, k in top.loc[checked, "observed_label"].value_counts().items():  # the union of the rules' n_checked
        counts.observed[label] = counts.observed.get(label, 0) + int(k)
    return len(pred)


def _regression_month(
    con, predictions: str, files: list[str], lo, hi, consequent: dict[str, float], position: dict[str, int],
    fallback: float | None, counts: _Counts,
) -> int:
    act = con.execute(
        "SELECT entity_id, CAST(issued_at_utc AS TIMESTAMPTZ) AS issued_at_utc, rule_id, effective_firing "
        "FROM read_parquet(?) WHERE effective_firing IS NOT NULL", [files],
    ).df()
    pred = con.execute(
        "SELECT entity_id, issued_at_utc, prediction, observed, missing_reason FROM "
        "(SELECT * REPLACE (CAST(issued_at_utc AS TIMESTAMPTZ) AS issued_at_utc) FROM read_parquet(?)) "
        "WHERE issued_at_utc >= ? AND issued_at_utc < ?", [predictions, lo, hi],
    ).df()
    if unknown := set(act["rule_id"]) - set(position):
        raise ImportanceError(f"activation records of rules that are not in rules.json: {sorted(unknown)}")
    key = ["entity_id", "issued_at_utc"]
    covered = weight_shares(act, position)
    act["part"] = act["share"] * act["rule_id"].map(consequent)
    per_row = act.groupby(key).agg(total=("total", "first"), rebuilt=("part", "sum")).reset_index()
    joined = pred.merge(per_row, on=key, how="outer", indicator=True)
    if (joined["_merge"] == "right_only").any():
        raise ImportanceError(f"activation records without a published prediction in {lo:%Y-%m}")
    has_output = joined["prediction"].notna()
    if (has_output & joined["total"].isna()).any():
        raise ImportanceError(f"a published prediction without activation records in {lo:%Y-%m}")
    if (~has_output & joined["total"].notna()).any():
        raise ImportanceError(f"activation records for a row without a prediction in {lo:%Y-%m}")
    counts.n_missing_input += int((~has_output).sum())
    live = joined[has_output]
    none_fired = live["total"] <= COVERAGE_EPSILON
    if none_fired.any():
        if fallback is None:
            raise ImportanceError("no rule fired for some rows and the model has no fallback value")
        expected = pd.Series(np.where(none_fired, fallback, live["rebuilt"]), index=live.index)
    else:
        expected = live["rebuilt"]
    error = float((expected - live["prediction"]).abs().max()) if len(live) else 0.0
    if not error <= PARITY_TOLERANCE:
        raise ImportanceError(f"sum(share x consequent) differs from the published prediction by {error:.3e} "
                              f"in {lo:%Y-%m} (limit {PARITY_TOLERANCE:g})")
    counts.max_abs_error = max(counts.max_abs_error, error)
    counts.n_no_rule += int(none_fired.sum())
    counts.n_fallback += int(none_fired.sum())
    fired = act[covered].merge(pred[["entity_id", "issued_at_utc", "prediction", "observed"]], on=key)
    # the deciding rule of each prediction: the largest share, ties to the lowest position
    winner = deciding_rows(fired)[[*key, "rule_id", "prediction", "observed"]]
    checked = winner["observed"].notna()
    decided = pd.DataFrame({
        "entity_id": winner["entity_id"].to_numpy(), "rule_id": winner["rule_id"].to_numpy(), "n_decided": 1,
        "n_checked": checked.astype(int).to_numpy(),
        "abs_error": np.where(checked, (winner["prediction"] - winner["observed"]).abs(), 0.0),
    })
    shares = fired.groupby(["entity_id", "rule_id"], sort=False)["share"].sum().reset_index(name="share_sum")
    counts.n_predicted += len(winner)
    counts.add(decided.groupby(["entity_id", "rule_id"], sort=False).sum().reset_index().merge(
        shares, on=["entity_id", "rule_id"], how="outer").fillna(0.0))
    return len(pred)


def _unit(value: float) -> float:
    """``value`` clipped to [0, 1] (float noise only: the callers' sums are exact in real arithmetic)."""
    return min(1.0, max(0.0, float(value)))


def compute_importance(
    model_dir: Path, rules: m.ModelRules, *, data_version: str, synthetic: bool, fallback: float | None, con,
) -> tuple[m.RuleImportanceResponse, dict]:
    """The ``RuleImportanceResponse`` of a published model directory and the record of the checks that were run.

    ``rules`` are the published rules; ``fallback`` the model's ``train_target_mean`` (regression only). ``con`` is a
    DuckDB connection. Raises ``ImportanceError`` when the activations and the predictions disagree.
    """
    model_dir = Path(model_dir)
    predictions = str(model_dir / layout.PREDICTIONS_FILE)
    mixture = rules.inference.family == m.InferenceFamily.RULE_MIXTURE_CLASSIFIER
    classifier = mixture or rules.inference.family == m.InferenceFamily.WINNING_RULE_CLASSIFIER
    if not classifier and (rules.inference.family != m.InferenceFamily.TSK_ZERO_ORDER
                           or rules.inference.rule_mode != m.RuleMode.ADDITIVE):
        raise ImportanceError("importance is defined for classifiers and additive zero-order TSK only")
    position = {r.rule_id: r.position for r in rules.rules}
    users = {v.feature: [r.rule_id for r in rules.rules if v.feature in {a.feature for a in r.antecedents}]
             for v in rules.variables}
    counts = _Counts()
    n_rows = 0
    for lo, hi, files in _months(model_dir):
        if mixture:
            n_rows += _mixture_month(con, predictions, files, lo, hi, users, counts)
        elif classifier:
            class_of = {r.rule_id: r.consequent.term for r in rules.rules}
            n_rows += _classifier_month(con, predictions, files, lo, hi, class_of, counts)
        else:
            consequent = {r.rule_id: r.consequent.value for r in rules.rules}
            n_rows += _regression_month(con, predictions, files, lo, hi, consequent, position, fallback, counts)
    total_rows, first, last = con.execute(
        "SELECT count(*), min(issued_at_utc), max(issued_at_utc) FROM read_parquet(?)", [predictions]).fetchone()
    if total_rows != n_rows or not total_rows:
        raise ImportanceError(f"{total_rows} published predictions but activations for {n_rows} of them")

    n = counts.n_predicted
    columns = ["n_decided", "n_checked", "n_hit", "abs_error", "share_sum", "n_top", "n_decisive"]
    table = counts.by_rule if not counts.by_rule.empty else pd.DataFrame(columns=["entity_id", "rule_id", *columns])
    for column in columns:
        if column not in table:
            table[column] = 0
    per_rule = table.groupby("rule_id").sum(numeric_only=True)

    def measures(row, denominator: int) -> dict:
        checked = int(row["n_checked"])
        if mixture:
            return {
                "top_contributor_share": _unit(row["n_top"] / denominator) if denominator else 0.0,
                "decisive_share": _unit(row["n_decisive"] / denominator) if denominator else 0.0,
                "accuracy": _unit(row["n_hit"] / checked) if checked else None,
            }
        decided = int(row["n_decided"])
        out = {"decided_share": _unit(decided / denominator) if denominator else 0.0}
        if classifier:
            out["accuracy"] = _unit(row["n_hit"] / checked) if checked else None
        else:
            out["mean_weight_share"] = _unit(row["share_sum"] / denominator) if denominator else 0.0
            out["mae"] = float(row["abs_error"] / checked) if checked else None
        return out

    empty = pd.Series(dict.fromkeys(columns, 0))
    rule_rows = []
    for rule in rules.rules:
        row = per_rule.loc[rule.rule_id] if rule.rule_id in per_rule.index else empty
        counted = ({"n_top": int(row["n_top"]), "n_decisive": int(row["n_decisive"])} if mixture
                   else {"n_decided": int(row["n_decided"])})
        rule_rows.append(m.RuleImportance(
            rule_id=rule.rule_id, n_checked=int(row["n_checked"]), **counted, **measures(row, n)))
    variables = []
    for variable in rules.variables:
        used_by = [u for u in users[variable.feature] if u in per_rule.index]
        if mixture:
            top = sum(per_rule.loc[u, "n_top"] for u in used_by) / n if n else 0.0
            decisive = counts.variable_decisive.get(variable.feature, 0) / n if n else 0.0
            shares = {"top_contributor_share": _unit(top), "decisive_share": _unit(decisive)}
        elif classifier:
            shares = {"decided_share": _unit(sum(per_rule.loc[u, "n_decided"] for u in used_by) / n if n else 0.0)}
        else:
            shares = {"decided_share": _unit(sum(per_rule.loc[u, "share_sum"] for u in used_by) / n if n else 0.0)}
        variables.append(m.VariableImportance(feature=variable.feature, n_rules=len(users[variable.feature]),
                                              **shares))

    entity_ids = [r[0] for r in con.execute(
        "SELECT DISTINCT entity_id FROM read_parquet(?) ORDER BY entity_id", [predictions]).fetchall()]
    entity_predicted = dict(con.execute(  # mixture: published predictions per entity (a prediction may have no top)
        "SELECT entity_id, count(*) FROM read_parquet(?) WHERE prediction_label IS NOT NULL GROUP BY 1",
        [predictions]).fetchall()) if mixture else {}
    per_entity = {e: g for e, g in table.groupby("entity_id")} if not table.empty else {}
    rule_order = [r.rule_id for r in rules.rules]
    entities = []
    for entity_id in entity_ids:
        group = per_entity.get(entity_id)
        if group is None:
            entities.append(m.EntityImportance(entity_id=entity_id, n_predicted=int(entity_predicted.get(entity_id, 0)),
                                               rules=[]))
            continue
        group = group.set_index("rule_id")
        n_entity = int(entity_predicted.get(entity_id, 0) if mixture else group["n_decided"].sum())
        listed = []
        for rule_id in rule_order:
            counted = ((group.loc[rule_id, "n_top"] + group.loc[rule_id, "n_decisive"]) if mixture
                       else group.loc[rule_id, "n_decided"]) if rule_id in group.index else 0
            if counted > 0:
                listed.append(m.EntityRuleImportance(
                    rule_id=rule_id, **{k: v for k, v in measures(group.loc[rule_id], n_entity).items()}))
        entities.append(m.EntityImportance(entity_id=entity_id, n_predicted=n_entity, rules=listed))

    observed_class_shares = None
    n_observed = sum(counts.observed.values())
    if classifier and n_observed:
        labels = [c.label for c in rules.target_scheme.classes]
        if unknown := set(counts.observed) - set(labels):
            raise ImportanceError(f"observed labels that are not classes of the target_scheme: {sorted(unknown)}")
        observed_class_shares = {label: counts.observed.get(label, 0) / n_observed for label in labels}

    measure = (m.ImportanceMeasure.RULE_MIXTURE if mixture else m.ImportanceMeasure.WINNING_RULE if classifier
               else m.ImportanceMeasure.WEIGHTED_AVERAGE)
    response = m.RuleImportanceResponse(
        data_version=data_version, synthetic=synthetic, model_id=rules.model_id, task_id=rules.task_id,
        measure=measure, period_from_utc=first, period_to_utc=last, n_predicted=n, n_no_rule=counts.n_no_rule,
        n_withheld=counts.n_withheld, n_no_top_rule=counts.n_no_top if mixture else None,
        rules=rule_rows, variables=variables, entities=entities, observed_class_shares=observed_class_shares,
    )
    checks = {
        "measure": response.measure.value, "n_predictions_rows": int(total_rows), "n_predicted": n,
        "n_no_rule": counts.n_no_rule, "n_missing_input": counts.n_missing_input,
    }
    if mixture:
        checks |= {
            "n_withheld_excluded": counts.n_withheld, "n_no_top_rule": counts.n_no_top,
            "top_rule_is_first_largest_positive_centred_contribution": True,
            "decisive": "is_decisive of the firing table: ex_fuzzy RuleMixture.predict with the rule's weights at 0",
        }
    elif classifier:
        checks |= {
            "n_withheld_excluded": counts.n_withheld,
            "each_labelled_prediction_has_one_winner_of_its_class": True,
        }
    else:
        checks |= {"max_abs_error_sum_share_x_consequent": counts.max_abs_error, "tolerance": PARITY_TOLERANCE,
                   "n_fallback_rows": counts.n_fallback}
    return response, checks
