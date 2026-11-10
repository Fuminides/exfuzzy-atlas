"""AT-062 #6: firing, association and weights are never called probability, risk, contribution, importance or cause.

``scripts/qa/wording_audit.py`` has the rules (a negated mention such as "no es una probabilidad" is the project's own
disclaimer, not a hit). The web-source test needs no artifacts and also runs in CI; the payload tests need them.
"""

from __future__ import annotations

import pandas as pd
import pytest
import wording_audit as wa
from qa_support import api_get, iso, series, trace


def _show(hits) -> str:
    return "\n".join(str(h) for h in hits)


def test_negation_logic_of_the_scanner():
    flagged = lambda s: [h.kind for h in wa.scan_text(s, "x")]  # noqa: E731
    assert flagged("Firing 0.8 = 80 % de probabilidad de la regla") == ["rule-context"]
    assert flagged("La importancia de la regla R01") == ["rule-context"]
    assert flagged("No es una probabilidad, un riesgo ni una contribución. Grado de activación de la regla") == []
    assert flagged("the weight is never a risk or an importance") == []
    assert flagged("Describen la regla, no son una importancia, una\n probabilidad ni una contribución") == []
    assert flagged("dissolved_oxygen(t+0h) = 5 mg/l") == ["zero-horizon"]
    assert flagged("a +6 h, emisión + 1 h") == []
    assert flagged("grupos de riesgo") == ["other-context"]
    assert flagged("© OpenStreetMap contributors") == []


def test_web_sources_never_describe_a_rule_with_forbidden_words():
    hits = wa.scan_web()
    assert [h for h in hits if h.kind != "other-context"] == [], "\n" + _show(hits)


def _payloads(client, task):
    t = task.sample_rows(1, "wording")["issued_at_utc"].iloc[0]
    row = task.preds[task.preds["issued_at_utc"] == t].iloc[0]
    rid = task.rule_ids[0]
    yield "domains", api_get(client, "/api/v1/domains")
    yield "entities", api_get(client, "/api/v1/entities", domain=task.expect.domain, task_id=task.task_id)
    yield "card", api_get(client, f"/api/v1/models/{task.model_id}")
    yield "rules", api_get(client, f"/api/v1/models/{task.model_id}/rules")
    yield (
        "rule-map",
        api_get(client, "/api/v1/rule-map", model_id=task.model_id, rule_id=rid, metric="firing_strength", time=iso(t)),
    )
    yield (
        "rule-map-window",
        api_get(
            client,
            "/api/v1/rule-map",
            model_id=task.model_id,
            rule_id=rid,
            metric="activation_frequency",
            tau=0.5,
            **{"from": iso(t), "to": iso(t + pd.Timedelta(days=1))},
        ),
    )
    yield "rule-trace", trace(client, task, row["entity_id"], t)
    yield "series", series(client, task, row["entity_id"], t, t + pd.Timedelta(days=1))


def test_api_payloads_never_describe_a_rule_with_forbidden_words(client, task):
    hits = []
    for name, body in _payloads(client, task):
        hits += wa.scan_payload(body, f"api:{name}[{task.task_id}]")
    rule_hits = [h for h in hits if h.kind == "rule-context"]
    assert rule_hits == [], "\n" + _show(rule_hits)


def test_horizon_zero_is_never_written_as_t_plus_0h_in_api_payloads(client, task):
    if task.expect.horizon_hours != 0:
        pytest.skip("only horizon-0 tasks")
    hits = []
    for name, body in _payloads(client, task):
        hits += wa.scan_payload(body, f"api:{name}[{task.task_id}]")
    zero = [h for h in hits if h.kind == "zero-horizon"]
    assert zero == [], f"{len(zero)} hit(s); first:\n" + _show(zero[:3])


def test_published_json_files_of_the_registry_models(task):
    """rules.json / card.json / manifest / metrics texts (real file lines)."""
    hits = [h for h in wa.scan_published_files(task.path.parent, task.model_id) if h.kind == "rule-context"]
    assert hits == [], "\n" + _show(hits)
