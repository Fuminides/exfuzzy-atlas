import pytest
from fastapi.testclient import TestClient

from atlas.contracts.models import SCHEMA_VERSION
from atlas_api.main import app

client = TestClient(app)
MODEL = "synthetic-no2-h6-v0"
T = "2025-01-15T08:00:00Z"


def rule_map(**params):
    return client.get("/api/v1/rule-map", params={"model_id": MODEL, "rule_id": "R01", **params})


def test_health_and_synthetic_flag():
    assert client.get("/api/v1/health").json() == {"status": "ok", "schema_version": SCHEMA_VERSION, "mode": "mock"}
    for path in ["/api/v1/domains", "/api/v1/entities?domain=air", f"/api/v1/models/{MODEL}/rules"]:
        assert client.get(path).json()["synthetic"] is True


def test_map_firing_equals_backend_trace():
    features = rule_map(metric="firing_strength", time=T).json()["features"]
    for f in features:
        trace = client.get(f"/api/v1/entities/{f['id']}/rule-trace", params={"model_id": MODEL, "at": T}).json()
        firing = [r["firing_strength"] for r in trace["rules"] if r["rule_id"] == "R01"]
        assert f["properties"]["value"] == (firing[0] if firing else None)


def test_missing_input_is_null_not_zero():
    props = {f["id"]: f["properties"] for f in rule_map(metric="firing_strength", time=T).json()["features"]}
    assert props["SYN_D"]["value"] is None and props["SYN_D"]["missing_reason"] == "missing_input"
    assert props["SYN_B"]["value"] == 0.0 and props["SYN_B"]["missing_reason"] is None


def test_frequency_uses_valid_records_as_denominator():
    window = {"from": "2025-01-15T06:00:00Z", "to": "2025-01-15T12:00:00Z"}
    props = {
        f["id"]: f["properties"]
        for f in rule_map(metric="activation_frequency", tau=0.5, **window).json()["features"]
    }
    assert props["SYN_D"]["n_valid"] == 5  # one of six issue times has a missing input
    assert props["SYN_D"]["value"] == pytest.approx(3 / 5)
    assert props["SYN_B"]["n_valid"] == 6 and props["SYN_B"]["value"] == 0.0


@pytest.mark.parametrize("params", [
    {"metric": "firing_strength"},
    {"metric": "firing_strength", "time": T, "tau": 0.5},
    {"metric": "mean_activation", "time": T},
    {"metric": "activation_frequency", "from": T, "to": "2025-01-15T12:00:00Z"},
    {"metric": "mean_activation", "from": T, "to": T},
    {"metric": "firing_strength", "time": "2025-01-15T08:00:00"},
])
def test_rejects_ambiguous_queries(params):
    assert rule_map(**params).status_code == 422


def test_unknown_ids_are_404():
    assert client.get("/api/v1/rule-map", params={"model_id": "nope", "rule_id": "R01",
                                                  "metric": "firing_strength", "time": T}).status_code == 404
    assert rule_map(metric="firing_strength", time=T, rule_id="R99").status_code == 404
    assert client.get("/api/v1/entities/SYN_A/rule-trace",
                      params={"model_id": MODEL, "at": "2030-01-01T00:00:00Z"}).status_code == 404
