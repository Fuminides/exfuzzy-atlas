"""Contract v0.6 (CONTRACTS.md §15): English display fields next to the Spanish ones, all optional."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from atlas.contracts import models as m

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "synthetic"
T0 = datetime(2025, 1, 8, 7, tzinfo=timezone.utc)


def test_v052_payloads_validate_without_the_english_fields():
    term = m.LinguisticTerm(name="Buena", membership_type="trapezoidal", params=[0, 0, 40, 46])
    variable = m.LinguisticVariable(feature="no2_last", label="NO₂ hace 1 h", terms=[term])
    cls = m.TargetClass(label="Buena", lower=None, upper=40.0, description="Calidad del aire satisfactoria")
    scheme = m.TargetScheme(name="ICA", source_url="https://example.org", unit="ug/m3",
                            classes=[cls, m.TargetClass(label="Regular", lower=40.0, upper=None)])
    task = m.TaskInfo(task_id="t", target="no2", unit="ug/m3", horizon_hours=6, status="available",
                      territory="madrid", territory_title="Madrid")
    assert term.label_en is None
    assert (variable.label_en, variable.description_en) == (None, None)
    assert (cls.display_label_en, cls.description_en) == (None, None)
    assert (scheme.name_en, scheme.short_name_en) == (None, None)
    assert task.territory_title_en is None


def test_english_fields_round_trip():
    term = m.LinguisticTerm(name="<=L", label="≤ límite de detección", label_en="≤ detection limit",
                            membership_type="trapezoidal", params=[0.0, 0.0, 0.03, 0.0304])
    variable = m.LinguisticVariable(feature="no2_lag3h", label="NO₂ hace 4 h", label_en="NO₂ 4 h ago",
                                    description="d", description_en="e", terms=[term])
    cls = m.TargetClass(label="Buena", display_label_en="Good", lower=None, upper=40.0,
                        description="Calidad del aire satisfactoria", description_en="Satisfactory air quality")
    scheme = m.TargetScheme(name="Nivel", name_en="Level", short_name="Nivel relativo",
                            short_name_en="Relative level", source_url="https://example.org", unit="u",
                            classes=[cls, m.TargetClass(label="Regular", lower=40.0, upper=None)])
    task = m.TaskInfo(task_id="t", target="no2", unit="ug/m3", horizon_hours=6, status="available",
                      territory="germany", territory_title="Alemania", territory_title_en="Germany")
    again = m.LinguisticVariable.model_validate_json(variable.model_dump_json())
    assert (again.label_en, again.description_en, again.terms[0].label_en) == ("NO₂ 4 h ago", "e", "≤ detection limit")
    again_scheme = m.TargetScheme.model_validate_json(scheme.model_dump_json())
    assert (again_scheme.name_en, again_scheme.short_name_en) == ("Level", "Relative level")
    assert again_scheme.classes[0].display_label_en == "Good"
    assert again_scheme.classes[0].description_en == "Satisfactory air quality"
    assert m.TaskInfo.model_validate_json(task.model_dump_json()).territory_title_en == "Germany"


def test_summary_label_en_is_optional():
    summary = json.loads((FIXTURES / "summary.json").read_text())[0]
    summary.pop("label_en", None)
    assert m.SummaryResponse.model_validate(summary).label_en is None
    summary["label_en"] = "Observed hourly NO₂"
    assert m.SummaryResponse.model_validate(summary).label_en == "Observed hourly NO₂"


def test_fixtures_carry_english_where_spanish_exists():
    rules = m.ModelRules.model_validate_json((FIXTURES / "model_rules.json").read_text())
    for v in rules.variables:
        assert v.label and v.label_en and v.description and v.description_en
        assert all(t.label_en for t in v.terms if t.label)
    extra = m.ModelRules.model_validate(json.loads((FIXTURES / "model_rules_extra.json").read_text())[0])
    assert all(c.display_label_en for c in extra.target_scheme.classes if c.display_label)
    assert extra.target_scheme.name_en
    summaries = [m.SummaryResponse.model_validate(s) for s in json.loads((FIXTURES / "summary.json").read_text())]
    assert all(s.label_en for s in summaries)
    domains = m.DomainsResponse.model_validate_json((FIXTURES / "domains.json").read_text())
    assert all(t.territory_title_en for d in domains.domains for t in d.tasks if t.territory_title)
