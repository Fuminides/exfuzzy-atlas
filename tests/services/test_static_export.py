"""Static export (docs/static_export.md): exporter on the synthetic models, parity with the API, safety, privacy."""

from __future__ import annotations

import gzip
import json
import os

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from atlas.contracts import models as m
from atlas.ml.exfuzzy_features import has_compound_terms, has_ordinal_conditions, has_rule_mixture
from atlas.services.static import export, fmt
from atlas.services.static.store import StaticStore
from atlas.services.synthetic import build_synthetic
from atlas_api.main import create_app

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "2")

needs_ordinal = pytest.mark.skipif(not (has_ordinal_conditions() and has_compound_terms()),
                                   reason="needs ex_fuzzy with ordinal conditions and compound terms (3.5.0)")
needs_mixture = pytest.mark.skipif(not has_rule_mixture() and not os.environ.get("CI"),
                                   reason="needs ex_fuzzy with inference='mixture'")


@pytest.fixture(scope="module", params=[
    "regression", "classification", pytest.param("mixture", marks=needs_mixture),
    pytest.param("regression-ordinal", marks=needs_ordinal),
    pytest.param("classification-ordinal", marks=needs_ordinal),
    pytest.param("mixture-ordinal", marks=[needs_mixture, needs_ordinal]),
])
def exported(request, tmp_path_factory):
    root = tmp_path_factory.mktemp(f"static-{request.param}")
    task, _, ordinal = request.param.partition("-")
    built = build_synthetic(root / "syn", task=task, v04=True, ordinal=bool(ordinal))
    out = root / "out"
    export.main(["--published-dir", str(built.published_dir), "--out", str(out),
                 "--explanations-dir", str(root / "none"), "--check-n", "4"])
    (data,) = (out / "data").iterdir()
    return built, out, data


def test_parity_with_the_api_and_a_clean_tree(exported):
    _, out, data = exported
    manifest = json.loads((data / "manifest.json").read_text())
    golden = manifest["golden"]
    assert golden["n_checked"] > 40 and golden["n_passed"] == golden["n_checked"] and not golden["failures"]
    for kind in ("predictions", "observations", "ruleMapInstant", "ruleMapWindow", "ruleTerritories", "ruleStories",
                 "ruleTrace", "series", "scenario"):
        assert golden["by_kind"][kind]["http_200"] > 0, kind  # not only agreeing errors
    assert manifest["privacy"]["violations"] == 0
    assert manifest["privacy"]["files_scanned"] >= manifest["totals"]["files"]
    index = json.loads(gzip.decompress((data / "files.json.gz").read_bytes()))
    assert len(index) == manifest["totals"]["files"]
    for rel, info in index.items():
        assert (data / rel).stat().st_size == info["bytes"] and rel.endswith(".json.gz")
    names = {p.name for p in data.rglob("*") if p.is_file()}
    assert not any(n.endswith((".pkl", ".parquet")) or n in ("SHA256SUMS", "publish.json") for n in names)
    assert (out / "golden" / data.name / "index.json.gz").is_file()


def test_every_kind_of_condition_is_exported_and_traced(exported, request):
    """v0.8: at_least / at_most / any_of conditions have their own memberships (the bounded sum ex_fuzzy computes)."""
    _, _, data = exported
    rules = json.loads(gzip.decompress(next((data / "models").glob("*/rules.json.gz")).read_bytes()))
    kinds = {a["operator"] for r in rules["rules"] for a in r["antecedents"]}
    meta = json.loads(gzip.decompress(next((data / "models").glob("*/meta.json.gz")).read_bytes()))
    assert [p[1] for p in meta["mem_pairs"]] and {p[1] for p in meta["mem_pairs"]} == kinds
    if request.node.callspec.params["exported"].endswith("-ordinal"):
        assert {"is", "at_least", "at_most", "any_of"} <= kinds
        client = TestClient(create_app(StaticStore(data)))
        entry = next(iter(json.loads(gzip.decompress((data / "domains.json.gz").read_bytes()))["domains"][0]["tasks"]))
        shard = json.loads(gzip.decompress(next((data / "models").glob("*/20*/pred.json.gz")).read_bytes()))
        trace = client.get(f"/api/v1/entities/{meta['entities'][shard['ei'][5]]}/rule-trace",
                           params={"model_id": meta["model_id"], "at": shard["t"][shard["ti"][5]]}).json()
        got = {(a["operator"], tuple(a["terms"])) for e in trace["rules"] for a in e["antecedents"]}
        assert ("at_least", ("Medium", "High")) in got and ("any_of", ("Low", "Medium")) in got
        assert ("any_of", ("Low", "High")) in got and ("at_most", ("Low", "Medium")) in got
        assert entry["task_id"] == meta["task_id"]


def test_the_static_store_refuses_what_is_not_precomputed(exported):
    built, _, data = exported
    client = TestClient(create_app(StaticStore(data)))
    meta = json.loads(gzip.decompress(next((data / "models").glob("*/meta.json.gz")).read_bytes()))
    mid = meta["model_id"]
    first = fmt.parse_iso(meta["coverage"]["from"])
    window = {"model_id": mid, "from": fmt.iso(first), "to": fmt.iso(first + 3 * fmt.DAY)}
    # a custom window and a tau outside the grid are 422s, never an approximation
    assert client.get("/api/v1/rule-territories", params=window).status_code == 422
    day = fmt.window_of("day", first)
    ok = {"model_id": mid, "from": fmt.iso(day[0]), "to": fmt.iso(day[1])}
    assert client.get("/api/v1/rule-territories", params={**ok, "tau": 0.5}).status_code == 200
    assert client.get("/api/v1/rule-territories", params={**ok, "tau": 0.52}).status_code == 422
    assert client.get("/api/v1/rule-stories", params={**ok, "tau": 0.4}).status_code == 422
    # what-if: one input at a time, on the grid
    doc = json.loads(gzip.decompress(next((data / "models" / mid / "whatif").glob("*.json.gz")).read_bytes()))
    features = sorted(doc["grid"])
    body = {"model_id": mid, "entity_id": doc["entity_id"], "at": doc["at"][0]}
    value = doc["grid"][features[0]][1]
    assert client.post("/api/v1/scenarios", json={**body, "overrides": {features[0]: value}}).status_code == 200
    off = (doc["grid"][features[0]][1] + doc["grid"][features[0]][2]) / 2
    assert client.post("/api/v1/scenarios", json={**body, "overrides": {features[0]: off}}).status_code == 422
    two = {f: doc["grid"][f][1] for f in features[:2]}
    if len(features) > 1:
        assert client.post("/api/v1/scenarios", json={**body, "overrides": two}).status_code == 422
    nothing = client.post("/api/v1/scenarios", json={**body, "overrides": {}})
    assert nothing.status_code == 200
    unchanged = m.ScenarioResponse.model_validate(nothing.json())
    assert unchanged.original == unchanged.modified


def test_files_are_deterministic(exported):
    _, _, data = exported
    path = next((data / "models").glob("*/*/pred.json.gz"))
    raw = gzip.decompress(path.read_bytes())
    assert fmt.gz(raw) == path.read_bytes()


def test_a_period_keeps_every_view_inside_it_and_a_base_export_is_reused(tmp_path_factory):
    root = tmp_path_factory.mktemp("static-period")
    built = build_synthetic(root / "syn", task="classification", v04=True)
    (task,) = json.loads((built.published_dir / "registry.json").read_text())["tasks"]
    first = built.table["issued_at_utc"].min() + pd.Timedelta(days=4)
    lo, hi = first + pd.Timedelta(days=3, hours=5), first + pd.Timedelta(days=14, hours=10)
    args = ["--published-dir", str(built.published_dir), "--explanations-dir", str(root / "none"), "--check-n", "5",
            "--period", f"{task}={lo.strftime('%Y-%m-%dT%H:%M:%SZ')},{hi.strftime('%Y-%m-%dT%H:%M:%SZ')}"]
    export.main([*args, "--out", str(root / "a")])
    (data_a,) = (root / "a" / "data").iterdir()
    manifest = json.loads((data_a / "manifest.json").read_text())
    assert manifest["golden"]["n_passed"] == manifest["golden"]["n_checked"] > 40
    meta = json.loads(gzip.decompress(next((data_a / "models").glob("*/meta.json.gz")).read_bytes()))
    assert meta["period"]["from"] == fmt.iso(lo.to_pydatetime())
    assert meta["coverage"]["to"] == fmt.iso(hi.to_pydatetime())
    assert meta["full_coverage"]["to"] > meta["coverage"]["to"]
    assert manifest["tasks"][task]["period"] == meta["period"]
    # no row, window or story outside the period
    for path in (data_a / "models").glob("*/20*/pred.json.gz"):
        times = json.loads(gzip.decompress(path.read_bytes()))["t"]
        assert all(meta["period"]["from"] <= t <= meta["period"]["to"] for t in times)
    client = TestClient(create_app(StaticStore(data_a)))
    week = fmt.window_of("week", lo.to_pydatetime())
    std = {"model_id": meta["model_id"], "from": fmt.iso(week[0]), "to": fmt.iso(week[1])}
    # the standard window crosses the start of the period
    assert client.get("/api/v1/rule-territories", params=std).status_code == 422
    clipped = {**std, "from": fmt.iso(max(week[0], lo.to_pydatetime()))}
    assert client.get("/api/v1/rule-territories", params=clipped).status_code == 200
    assert client.get("/api/v1/rule-stories", params={**clipped, "tau": 0.5, "limit": 10}).status_code == 200
    # a second export of the same published models reuses every file of the first (hard links), re-exporting nothing
    export.main([*args, "--out", str(root / "b"), "--base", str(data_a), "--check-n", "3"])
    (data_b,) = (root / "b" / "data").iterdir()
    manifest_b = json.loads((data_b / "manifest.json").read_text())
    assert manifest_b["base"]["reused_tasks"] == [task] and manifest_b["base"]["export_id"] == manifest["export_id"]
    pred_a = next((data_a / "models").glob("*/20*/pred.json.gz"))
    assert (data_b / pred_a.relative_to(data_a)).stat().st_ino == pred_a.stat().st_ino
    assert manifest_b["golden"]["n_passed"] == manifest_b["golden"]["n_checked"]


# ------------------------------------------------------------------------------------------------ safety units
@pytest.mark.parametrize("rel", ["models/x/model.pkl", "a/b.parquet", "SHA256SUMS", "models/x/publish.json",
                                 "models/x/run_manifest.json", "models/x/card.json", "../escape.json.gz",
                                 "/abs.json.gz", "models/x/model.pickle.json.gz.bak"])
def test_allow_list_refuses_model_files(rel):
    with pytest.raises(fmt.ForbiddenFile):
        fmt.check_allowed(rel)


@pytest.mark.parametrize("rel", ["manifest.json", "domains.json.gz", "models/m/2025-01-01/pred.json.gz"])
def test_allow_list_accepts_the_layout(rel):
    fmt.check_allowed(rel)


def test_ids_that_are_not_file_safe_are_refused():
    assert fmt.check_id("DEBB001") == "DEBB001"
    for bad in ("a/b", "x y", "é", ""):
        with pytest.raises(ValueError):
            fmt.check_id(bad)


def test_redaction_keeps_the_last_two_components():
    body = {"p": "/home/someone/work/ex-fuzzy-wt/ex_fuzzy/__init__.py", "q": ["see C:\\Users\\a\\b\\c.txt", 3],
            "ok": "local atlas/local-integration @ 2ffcfb9"}
    red = fmt.redact(body)
    assert red["p"] == ".../ex_fuzzy/__init__.py" and red["q"][0] == "see .../b/c.txt" and red["ok"] == body["ok"]


def test_privacy_scan_finds_paths_hosts_and_mails(tmp_path, monkeypatch):
    monkeypatch.setenv(fmt.EXTRA_HOSTS_ENV, "labhost, other-box")
    fine = tmp_path / "a.json.gz"
    fine.write_bytes(fmt.gz(fmt.dumps({"x": "nothing here", "n": [1.5, None]})))
    assert fmt.scan_privacy(tmp_path) == (1, [])
    for i, text in enumerate(["/home/someone/x", "ssh labhost2", "me@example.org", "person@gmail", "x.essex.ac.uk"]):
        (tmp_path / f"bad{i}.json.gz").write_bytes(fmt.gz(fmt.dumps({"t": text})))
    n, bad = fmt.scan_privacy(tmp_path)
    assert n == 6 and len(bad) == 5


def test_audit_refuses_symlinks_and_non_json(tmp_path):
    (tmp_path / "ok.json.gz").write_bytes(fmt.gz(b"{}"))
    fmt.audit_tree(tmp_path)
    (tmp_path / "pickle.json.gz").write_bytes(fmt.gz(b"\x80\x04N."))
    with pytest.raises(fmt.ForbiddenFile):
        fmt.audit_tree(tmp_path)
    (tmp_path / "pickle.json.gz").unlink()
    (tmp_path / "link.json.gz").symlink_to(tmp_path / "ok.json.gz")
    with pytest.raises(fmt.ForbiddenFile):
        fmt.audit_tree(tmp_path)


def test_diff_uses_a_float_tolerance_and_exact_everything_else():
    assert export.diff({"a": [1.0, 2.0]}, {"a": [1.0 + 1e-12, 2.0]}) is None
    assert export.diff({"a": 1.0}, {"a": 1.001}) is not None
    assert export.diff({"a": 0}, {"a": None}) is not None
    assert export.diff({"a": "x"}, {"a": "y"}) is not None
    assert export.diff({"a": True}, {"a": 1}) is not None
