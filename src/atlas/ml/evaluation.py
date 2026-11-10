"""Evaluation helpers beyond the plain overall / per-entity metrics (AT-041).

* ``evaluation_slices``: entity, calendar month and local hour of the *target* (valid) time.
* ``extreme_rows``: errors and event detection on the rows whose observed target reaches a threshold. The
  thresholds are analytical (a training quantile, a fixed level), never presented as regulatory limits.
* ``period_metric_rows``: all of the above for one estimator on one period, with the period encoded in the
  ``MetricRow.slice`` prefix (test rows carry no prefix, see ``docs/ml/madrid_no2_h6_results.md``).
* ``rule_signatures`` / ``rule_stability``: which antecedent sets a fitted rule base uses and how much two or
  more seeds agree on them.
* ``classifier_readability_rows`` / ``classifier_rule_sets`` / ``rule_set_stability``: readability of a winning-rule
  classifier (AT-043): rules per class, rule length, duplicates, how often each rule wins, unknown share and the
  agreement of several seeds on (antecedent set, class) pairs.
* ``PeakRss``: peak resident memory of this process inside a ``with`` block (Linux).
"""

from __future__ import annotations

import itertools
import os
from collections.abc import Mapping, Sequence
from datetime import timedelta

import numpy as np
import pandas as pd

from atlas.contracts.models import MetricRow
from atlas.explain import compute_activations, duplicate_groups, feature_names
from atlas.explain.classifier import (
    compute_classifier_activations,
    get_master_rulebase,
    rule_classes,
    rule_ids,
)
from atlas.explain.classifier import feature_names as classifier_feature_names
from atlas.ml.exfuzzy_features import rule_conditions
from atlas.ml.metrics import metric_rows
from atlas.ml.rules_export import ACTIVATION_TAU

ACTIVATION_CHUNK = 250_000  # rows per ex_fuzzy activation call in classifier_readability_rows


def evaluation_slices(frame: pd.DataFrame, horizon_hours: int, timezone: str) -> dict[str, np.ndarray]:
    """Slice labels per row: ``entity``, ``month`` (1-12) and ``hour`` (0-23), both of the target time, local."""
    valid = (pd.DatetimeIndex(frame["issued_at_utc"]) + timedelta(hours=horizon_hours)).tz_convert(timezone)
    return {
        "entity": frame["entity_id"].to_numpy(),
        "month": np.asarray(valid.month),
        "hour": np.asarray(valid.hour),
    }


def extreme_rows(
    estimator: str, y_true: np.ndarray, y_pred: np.ndarray, thresholds: Mapping[str, float], prefix: str = ""
) -> list[MetricRow]:
    """For each ``name -> level``: errors on the rows with ``y_true >= level`` and event detection.

    ``event_recall`` is the share of those rows predicted at or above the level; ``event_precision`` the share of
    the rows predicted at or above the level that really reached it (omitted when nothing is predicted there).
    """
    y_true, y_pred = np.asarray(y_true, dtype=float), np.asarray(y_pred, dtype=float)
    rows = []
    for name, level in thresholds.items():
        slice_ = f"{prefix}extreme={name}"
        event, alarm = y_true >= level, y_pred >= level
        if event.any():
            err = y_pred[event] - y_true[event]
            stats = {
                "mae": np.abs(err).mean(), "rmse": np.sqrt((err**2).mean()), "bias": err.mean(),
                "event_recall": alarm[event].mean(),
            }
            rows += [MetricRow(estimator=estimator, metric=k, value=float(v), n=int(event.sum()), slice=slice_)
                     for k, v in stats.items()]
        if alarm.any():
            rows.append(MetricRow(estimator=estimator, metric="event_precision", value=float(event[alarm].mean()),
                                  n=int(alarm.sum()), slice=slice_))
    return rows


def period_metric_rows(
    estimator: str,
    frame: pd.DataFrame,
    y_true: np.ndarray,
    y_pred: np.ndarray,
    *,
    horizon_hours: int,
    timezone: str,
    thresholds: Mapping[str, float],
    prefix: str = "",
) -> list[MetricRow]:
    """MAE / RMSE / R2 / bias overall and per entity, month and hour, plus the extreme-episode rows."""
    y_true, y_pred = np.asarray(y_true, dtype=float), np.asarray(y_pred, dtype=float)
    rows = metric_rows(estimator, y_true, y_pred, evaluation_slices(frame, horizon_hours, timezone))
    rows.append(MetricRow(estimator=estimator, metric="bias", value=float((y_pred - y_true).mean()), n=len(y_true)))
    rows = [r.model_copy(update={"slice": prefix + r.slice}) for r in rows]
    return rows + extreme_rows(estimator, y_true, y_pred, thresholds, prefix)


def rule_signatures(rulebase) -> list[tuple[tuple[str, str], ...]]:
    """One hashable antecedent set per rule: sorted ``(feature, condition)`` pairs of the used features.

    The condition is the linguistic term, or ``at least <term>`` / ``at most <term>`` (ex_fuzzy ordinal conditions).
    """
    names = feature_names(rulebase)
    return [
        tuple(sorted((names[c.feature], c.text) for c in rule_conditions(rule, rulebase.antecedents)))
        for rule in rulebase.rules
    ]


def interpretability_rows(estimator: str, rulebase, X: np.ndarray, prefix: str = "") -> list[MetricRow]:
    """Rule counts and, on the rows ``X`` (finite), fallback share plus per-rule mean activation and frequency.

    ``activation`` is the raw t-norm firing in [0, 1]; it is a degree of rule match, not a probability and not a
    contribution to the prediction. Per-rule rows use slice ``rule=R01`` etc. (positional ids, as in rules.json).
    """
    signatures = rule_signatures(rulebase)
    duplicates = sum(len(g) - 1 for g in duplicate_groups(rulebase))
    act = compute_activations(rulebase, X, with_prediction=False)
    n = len(X)
    rows = [
        MetricRow(estimator=estimator, metric="n_rules", value=float(len(signatures)), n=len(signatures)),
        MetricRow(estimator=estimator, metric="mean_rule_length", value=float(np.mean([len(s) for s in signatures])),
                  n=len(signatures)),
        MetricRow(estimator=estimator, metric="n_duplicate_rules", value=float(duplicates), n=len(signatures)),
        MetricRow(estimator=estimator, metric="n_distinct_antecedent_sets", value=float(len(set(signatures))),
                  n=len(signatures)),
        MetricRow(estimator=estimator, metric="fraction_fallback", value=float(act.fallback_used.mean()), n=n,
                  slice=prefix + "all"),
    ]
    mean_act, freq = act.raw.mean(axis=0), (act.raw >= ACTIVATION_TAU).mean(axis=0)
    for r in range(len(signatures)):
        slice_ = f"{prefix}rule=R{r + 1:02d}"
        rows += [
            MetricRow(estimator=estimator, metric="rule_mean_activation", value=float(mean_act[r]), n=n, slice=slice_),
            MetricRow(estimator=estimator, metric=f"rule_activation_frequency_tau{ACTIVATION_TAU:g}",
                      value=float(freq[r]), n=n, slice=slice_),
        ]
    return rows


def rule_stability(signature_sets: Sequence[Sequence[tuple[tuple[str, str], ...]]]) -> dict:
    """Agreement of several fitted rule bases on their antecedent sets.

    ``pairwise_jaccard``: Jaccard index of the sets of distinct antecedent sets, for every pair of seeds.
    ``reference_found_in_others``: for each model, the share of its distinct antecedent sets that appear in at
    least one other model. ``feature_usage``: per model, the share of rules using each feature.
    """
    sets = [set(s) for s in signature_sets]
    jaccards = [len(a & b) / len(a | b) if a | b else 1.0 for a, b in itertools.combinations(sets, 2)]
    found = [
        (sum(any(s in other for j, other in enumerate(sets) if j != i) for s in own) / len(own)) if own else 1.0
        for i, own in enumerate(sets)
    ]
    usage = []
    for sigs in signature_sets:
        counts: dict[str, int] = {}
        for sig in sigs:
            for feature, _ in sig:
                counts[feature] = counts.get(feature, 0) + 1
        usage.append({f: c / len(sigs) for f, c in sorted(counts.items())} if len(sigs) else {})
    return {
        "n_models": len(sets),
        "pairwise_jaccard": jaccards,
        "mean_pairwise_jaccard": float(np.mean(jaccards)) if jaccards else None,
        "reference_found_in_others": found,
        "feature_usage": usage,
    }


def classifier_rule_sets(model, class_labels: Sequence[str]) -> list[tuple[tuple[tuple[str, str], ...], str]]:
    """One ``(antecedent set, class label)`` per rule of a winning-rule classifier, in rule order.

    The antecedent set is the sorted ``(feature, condition)`` pairs of the used features: the linguistic term, or
    ``at least <term>`` / ``at most <term>`` with ex_fuzzy ordinal conditions.
    """
    rb = get_master_rulebase(model)
    names = classifier_feature_names(rb)
    out = []
    for rule, cls in zip(rb.get_rules(), rule_classes(rb), strict=True):
        antecedents = tuple(sorted((names[c.feature], c.text) for c in rule_conditions(rule, rb.antecedents)))
        out.append((antecedents, class_labels[cls]))
    return out


def classifier_readability_rows(
    estimator: str, model, X: np.ndarray, class_labels: Sequence[str], y_class: np.ndarray | None = None,
    prefix: str = "", include_static: bool = True,
) -> list[MetricRow]:
    """Readability metrics of a winning-rule classifier; rows ``X`` (finite) give the winning frequencies.

    * ``n_rules``, ``n_rules[<class>]``, ``mean_rule_length`` (antecedents per rule), ``n_distinct_antecedent_sets``,
      ``n_duplicate_rules`` (rules whose antecedent set already appeared, any class) and
      ``n_conflicting_antecedent_sets`` (antecedent sets used with more than one class).
    * on ``X``: ``share_no_rule_fires`` (no rule fired), ``rule_win_share`` per rule (slice ``rule=R01``: share of
      rows it decides), ``n_rules_winning`` (rules that win at least one row) and ``n_rules_winning_ge_1pct``.
    * with ``y_class``: ``rule_win_precision`` per rule (share of its won rows whose observed class is the rule's).
    ``include_static=False`` leaves out the rule-base counts (identical for every period) so that they are written once.
    The win share is a share of rows decided, not a probability and not a contribution.
    """
    sets = classifier_rule_sets(model, class_labels)
    rb = get_master_rulebase(model)
    ids, classes = rule_ids(rb), rule_classes(rb)
    by_set: dict = {}
    for antecedents, label in sets:
        by_set.setdefault(antecedents, []).append(label)
    n_rules = len(sets)
    static = [
        MetricRow(estimator=estimator, metric="n_rules", value=float(n_rules), n=n_rules),
        MetricRow(estimator=estimator, metric="mean_rule_length", n=n_rules,
                  value=float(np.mean([len(a) for a, _ in sets])) if sets else 0.0),
        MetricRow(estimator=estimator, metric="n_distinct_antecedent_sets", value=float(len(by_set)), n=n_rules),
        MetricRow(estimator=estimator, metric="n_duplicate_rules", value=float(n_rules - len(by_set)), n=n_rules),
        MetricRow(estimator=estimator, metric="n_conflicting_antecedent_sets", n=n_rules,
                  value=float(sum(len(set(v)) > 1 for v in by_set.values()))),
    ]
    static += [MetricRow(estimator=estimator, metric=f"n_rules[{label}]", n=n_rules,
                         value=float(sum(c == k for c in classes))) for k, label in enumerate(class_labels)]
    rows = static if include_static else []
    n = len(X)
    winner = np.concatenate([compute_classifier_activations(model, X[i:i + ACTIVATION_CHUNK]).winner
                             for i in range(0, max(n, 1), ACTIVATION_CHUNK)])  # chunks: rows x rules arrays are big
    wins = np.bincount(winner[winner >= 0], minlength=n_rules)
    rows += [
        MetricRow(estimator=estimator, metric="share_no_rule_fires", value=float((winner < 0).mean()), n=n,
                  slice=prefix + "all"),
        MetricRow(estimator=estimator, metric="n_rules_winning", value=float((wins > 0).sum()), n=n,
                  slice=prefix + "all"),
        MetricRow(estimator=estimator, metric="n_rules_winning_ge_1pct", value=float((wins >= 0.01 * n).sum()), n=n,
                  slice=prefix + "all"),
    ]
    for r in range(n_rules):
        rows.append(MetricRow(estimator=estimator, metric="rule_win_share", value=float(wins[r] / n), n=n,
                              slice=f"{prefix}rule={ids[r]}"))
        if y_class is not None and wins[r]:
            hit = float((np.asarray(y_class)[winner == r] == classes[r]).mean())
            rows.append(MetricRow(estimator=estimator, metric="rule_win_precision", value=hit, n=int(wins[r]),
                                  slice=f"{prefix}rule={ids[r]}"))
    return rows


def rule_set_stability(rule_sets: Sequence[Sequence[tuple]]) -> dict:
    """Jaccard agreement of several fits on their rules.

    ``pairwise_jaccard_rule``: Jaccard of the sets of ``(antecedent set, class)`` pairs;
    ``pairwise_jaccard_antecedents``: the same ignoring the class. Both over every pair of seeds.
    """
    full = [set(s) for s in rule_sets]
    ante = [{a for a, _ in s} for s in rule_sets]

    def jac(sets):
        return [len(a & b) / len(a | b) if a | b else 1.0 for a, b in itertools.combinations(sets, 2)]

    jr, ja = jac(full), jac(ante)
    return {
        "n_models": len(full),
        "pairwise_jaccard_rule": jr, "mean_pairwise_jaccard_rule": float(np.mean(jr)) if jr else None,
        "pairwise_jaccard_antecedents": ja, "mean_pairwise_jaccard_antecedents": float(np.mean(ja)) if ja else None,
    }


class PeakRss:
    """Peak resident set size (MB) reached by this process inside the block; ``peak_mb`` is set on exit.

    Resets the kernel's high-water mark through ``/proc/self/clear_refs``; where that is unavailable the value
    is the process peak so far (``ru_maxrss``), an upper bound.
    """

    def __enter__(self) -> PeakRss:
        self.peak_mb = float("nan")
        try:
            with open("/proc/self/clear_refs", "w") as fh:
                fh.write("5")
            self._reset = True
        except OSError:
            self._reset = False
        return self

    def __exit__(self, *exc) -> None:
        self.peak_mb = self._read()

    def _read(self) -> float:
        key = "VmHWM:" if self._reset else None
        try:
            if key:
                with open("/proc/self/status") as fh:
                    for line in fh:
                        if line.startswith(key):
                            return int(line.split()[1]) / 1024
            import resource

            return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        except (OSError, ValueError):
            return float("nan")


def current_rss_mb() -> float:
    """Resident set size of this process now, in MB (nan if /proc is unavailable)."""
    try:
        with open("/proc/self/statm") as fh:
            return int(fh.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 2**20
    except (OSError, ValueError):
        return float("nan")
