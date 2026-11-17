"""Contract v0.9 (CONTRACTS.md §20): fNIRS domain, task view, sensor montage, subject split, trials and trial traces."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from atlas.contracts import models as m
from atlas.services import layout

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic"
SCHEMAS = Path(__file__).resolve().parents[2] / "src" / "atlas" / "contracts" / "schemas"
RULE_TRACE_FIELDS = {  # RuleTrace as of v0.8: v0.9 shares its checks through a mixin without touching its fields
    "schema_version", "data_version", "synthetic", "model_id", "task_id", "entity_id", "issued_at_utc", "valid_at_utc",
    "inference", "feature_values", "rules", "prediction", "observation_ids", "observed", "observed_label", "quality",
}


def _mixture_trace() -> dict:
    """A rule-mixture RuleTrace of the committed v0.7 fixtures (computed with ex_fuzzy)."""
    return copy.deepcopy(json.loads((FIXTURES / "v07_responses.json").read_text())[1]["response"])


def _trial_trace(trace: dict, **extra) -> dict:
    out = {k: v for k, v in trace.items() if k not in ("entity_id", "issued_at_utc", "valid_at_utc", "observation_ids",
                                                         "observed")}
    out["feature_values"] = [{**fv, "observed_at_utc": None} for fv in out["feature_values"]]
    return {**out, "sample_id": "s03-t05", "subject": 3, "trial": 5, "split": "test", **extra}


def _channel(cid="AF7", xyz=(-0.5878, 0.809, 0.0), **extra) -> dict:
    return {"channel_id": cid, "xyz": list(xyz), "xy": list(m.head_projection(xyz)),
            "inputs": [{"feature": f"tmb_s1_ch{cid}", "signal": "HbO", "label": f"HbO en {cid}"}], **extra}


def _montage(channels) -> dict:
    return {"data_version": "v", "task_id": "fnirs_nback", "frame": "unit sphere", "source": "PDF",
            "source_url": "http://example.org/x.pdf", "source_sha256": "0" * 64, "channels": channels}


# ------------------------------------------------------------------------------------------- compatibility


def test_rule_trace_keeps_its_v08_fields():
    schema = json.loads((SCHEMAS / "RuleTrace.schema.json").read_text())
    assert set(schema["properties"]) == RULE_TRACE_FIELDS
    m.RuleTrace.model_validate(_mixture_trace())


def test_v08_domains_payload_validates_and_defaults_to_the_map_view():
    payload = json.loads((FIXTURES / "domains.json").read_text())
    for domain in payload["domains"]:
        for task in domain["tasks"]:
            task.pop("view")
    tasks = [t for d in m.DomainsResponse.model_validate(payload).domains for t in d.tasks]
    assert tasks and {t.view for t in tasks} == {m.TaskView.MAP}


def test_every_domain_has_a_title_and_registry_entries_default_to_map():
    assert set(layout.DOMAIN_TITLES) == set(m.Domain)
    entry = layout.RegistryEntry(model_id="x", domain="air", title="t", target="no2", unit="ug/m3", horizon_hours=1,
                                 data_version="v")
    assert entry.view == m.TaskView.MAP


# ------------------------------------------------------------------------------------------------ montage


def test_head_projection_keeps_left_right_and_front():
    assert m.head_projection((0, 0, 1)) == (0.0, 0.0)  # vertex at the centre
    assert m.head_projection((0, 1, 0)) == pytest.approx((0.0, 1.0))  # nose up, ear plane on the unit circle
    assert m.head_projection((1, 0, 0)) == pytest.approx((1.0, 0.0))  # right ear to the right
    x, y = m.head_projection((0, 2, 2))  # not normalised: same direction, polar angle 45 degrees
    assert (x, y) == pytest.approx((0.0, 0.5))
    with pytest.raises(ValueError):
        m.head_projection((0, 0, 0))


def test_montage_channel_xy_must_be_the_projection_of_xyz():
    m.MontageChannel.model_validate(_channel())
    bad = _channel()
    bad["xy"] = [0.1, 0.2]
    with pytest.raises(ValidationError, match="head_projection"):
        m.MontageChannel.model_validate(bad)


def test_montage_rejects_duplicates_and_unsourced_regions():
    m.MontageResponse.model_validate(_montage([_channel(), _channel("AF8", (0.5878, 0.809, 0.0))]))
    with pytest.raises(ValidationError, match="unique"):
        m.MontageResponse.model_validate(_montage([_channel(), _channel()]))
    with pytest.raises(ValidationError, match="region_source"):
        m.MontageResponse.model_validate(_montage([_channel(region="Corteza prefrontal izquierda")]))
    labelled = _montage([_channel(region="Corteza prefrontal izquierda", brodmann="BA10")])
    labelled.update(region_source="notebook 005", region_approximate=True)
    assert m.MontageResponse.model_validate(labelled).region_approximate


# ------------------------------------------------------------------------------------------- split, trials


def test_subject_split_is_disjoint_and_folds_are_training_subjects():
    m.SubjectSplit(train_subjects=[1, 2, 6, 7], test_subjects=[3, 4], selection_folds=[[1, 2], [6, 7]],
                   selection_metric="macro_f1")
    with pytest.raises(ValidationError, match="train and test"):
        m.SubjectSplit(train_subjects=[1, 2, 3], test_subjects=[3, 4])
    with pytest.raises(ValidationError, match="folds"):
        m.SubjectSplit(train_subjects=[1, 2], test_subjects=[3], selection_folds=[[1], [3]])
    with pytest.raises(ValidationError, match="folds"):
        m.SubjectSplit(train_subjects=[1, 2], test_subjects=[3], selection_folds=[[1, 2], [2]])


def _trial(sample_id="s03-t05", subject=3, trial=5, split="test", **extra) -> dict:
    return {"sample_id": sample_id, "subject": subject, "trial": trial, "condition": "3-back", "split": split,
            "observed_label": "2/3-back", "predicted_label": "2/3-back", **extra}


def test_trial_without_class_needs_a_reason():
    m.TrialRecord.model_validate(_trial(top_rule_id="R03"))
    m.TrialRecord.model_validate(_trial(predicted_label=None, missing_reason="prediction_unavailable"))
    with pytest.raises(ValidationError, match="missing_reason"):
        m.TrialRecord.model_validate(_trial(predicted_label=None))
    with pytest.raises(ValidationError, match="families"):
        m.TrialRecord.model_validate(_trial(top_rule_id="R03", winning_rule_id="R01"))


def test_trials_are_unique_and_a_subject_stays_in_one_split():
    body = {"data_version": "v", "model_id": "mod", "task_id": "fnirs_nback"}
    m.TrialsResponse.model_validate({**body, "trials": [_trial(), _trial("s01-t01", 1, 1, "train")]})
    with pytest.raises(ValidationError, match="unique"):
        m.TrialsResponse.model_validate({**body, "trials": [_trial(), _trial("s03-t05b")]})
    with pytest.raises(ValidationError, match="one split"):
        m.TrialsResponse.model_validate({**body, "trials": [_trial(), _trial("s03-t06", trial=6, split="train")]})


# ------------------------------------------------------------------------------------------------- traces


def test_trial_trace_has_the_parity_checks_of_rule_trace():
    trace = m.TrialTrace.model_validate(_trial_trace(_mixture_trace()))
    assert trace.prediction.class_scores is not None
    broken = _trial_trace(_mixture_trace())
    broken["rules"][0]["firing_strength"] = min(1.0, broken["rules"][0]["firing_strength"] + 0.1)
    with pytest.raises(ValidationError, match="t-norm"):
        m.TrialTrace.model_validate(broken)
    scores = _trial_trace(_mixture_trace())
    first = next(iter(scores["prediction"]["class_scores"]))
    scores["prediction"]["class_scores"][first] += 1.0
    with pytest.raises(ValidationError, match="class_scores"):
        m.TrialTrace.model_validate(scores)


def test_trial_trace_has_no_observation_times():
    payload = _trial_trace(_mixture_trace())
    payload["feature_values"][0]["observed_at_utc"] = "2025-01-08T07:00:00Z"
    with pytest.raises(ValidationError, match="observation times"):
        m.TrialTrace.model_validate(payload)


def test_fnirs_card_needs_a_subject_split():
    scheme = json.loads((FIXTURES / "v07_responses.json").read_text())[0]["response"]["target_scheme"]
    card = m.FnirsModelCard(
        data_version="v", model_id="mod", task_id="fnirs_nback", domain=m.Domain.FNIRS, run_id="r",
        created_at_utc="2026-11-16T11:00:00Z", git_commit=None, git_dirty=False, exfuzzy_version="3.5.0",
        python_version="3.12", seed=0, target="n-back load", features=["tmb_s1_chAF7"], hyperparameters={},
        data_checksums={}, split=m.SubjectSplit(train_subjects=[1], test_subjects=[3]), target_scheme=scheme,
        metrics=[m.MetricRow(estimator="exfuzzy", metric="macro_f1", value=0.78, n=162, slice="test")])
    assert card.domain == m.Domain.FNIRS and math.isclose(card.metrics[0].value, 0.78)
