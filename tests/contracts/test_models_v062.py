"""Contract v0.6.2 (CONTRACTS.md §17): ModelExplanation, a text about the rule base written by an AI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from atlas.contracts import models as m

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic"


def _text():
    return {"headline": "h", "summary": ["a", "b"], "points": ["x", "y", "z"]}


def _payload(**over):
    return {
        "data_version": "v", "model_id": "exfuzzy-x", "template_version": "1",
        "generated_by": {"tool": "Claude Code", "tool_version": "2.1.319", "model": "claude-opus-5-5"},
        "generated_at_utc": "2026-11-09T10:00:00Z", "input_sha256": "a" * 64, "reviewed": False,
        "es": _text(), "en": _text(), **over,
    }


def test_round_trip_and_defaults():
    e = m.ModelExplanation.model_validate(_payload())
    assert e.schema_version == m.SCHEMA_VERSION == "0.8.0" and e.synthetic is False and e.reviewed is False
    again = m.ModelExplanation.model_validate_json(e.model_dump_json())
    assert again == e and again.generated_by.model == "claude-opus-5-5"


@pytest.mark.parametrize("bad", [
    {"input_sha256": "not-a-hash"},
    {"generated_at_utc": "2026-11-09T10:00:00+01:00"},
    {"es": {"headline": "", "summary": ["a"], "points": []}},
    {"en": {"headline": "h", "summary": [], "points": []}},
    {"reviewed": None},
    {"extra": 1},
])
def test_rejects(bad):
    with pytest.raises(ValidationError):
        m.ModelExplanation.model_validate(_payload(**bad))


def test_the_mock_fixture_is_synthetic_and_valid():
    items = [m.ModelExplanation.model_validate(x) for x in json.loads((FIXTURES / "explanations.json").read_text())]
    assert [x.model_id for x in items] == ["synthetic-no2-h6-v0"]
    assert all(x.synthetic and not x.reviewed for x in items)
