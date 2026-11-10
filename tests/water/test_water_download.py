"""Raw cache: immutable pages, manifest with sha256, idempotence, reconciliation with X-Total-Items."""

import json
import stat

import pytest
from water_helpers import BASE, FakeApi, Response, ScriptedTransport, make_client, obs_row, ok, point_member

from atlas.contracts.models import SourceManifest
from atlas.domains.water.download import (
    INDEX_NAME,
    MANIFEST_NAME,
    InconsistentPaging,
    build_store,
    count_csv_rows,
    fetch_collection,
    sha256_file,
)

CONFIG = {
    "source_id": "uk-water-quality",
    "title": "t",
    "landing_url": "https://example.test",
    "license": "Open Government Licence v3.0",
    "attribution": "EA",
    "manifest_notes": ["note"],
}
QUERY = dict(
    method="POST",
    path="data/observation",
    params={"determinand": "9924", "dateFrom": "2019-01-01", "dateTo": "2019-12-01"},
    accept="text/csv",
    limit=2,
    extension="csv",
    count_rows=count_csv_rows,
)


def observations(n):
    return [obs_row("NE-1", i, "9924", f"2019-01-{i:02d}T10:00:00", str(i)) for i in range(1, n + 1)]


def setup(tmp_path, n=5):
    api = FakeApi([point_member("NE-1", 409570, 639530)], observations(n))
    client, clock = make_client(api)
    store = build_store(tmp_path / "raw", CONFIG, period=(2019, 2019))
    return api, client, store


def test_fetches_every_page_stores_them_read_only_and_writes_a_valid_manifest(tmp_path):
    api, client, store = setup(tmp_path)
    result = fetch_collection(store, client, rel_dir="obs/2019", **QUERY)
    assert result.fetched and result.total_items == 5 and [p["rows"] for p in result.index["pages"]] == [2, 2, 1]
    assert len(api.calls) == 3
    raw = tmp_path / "raw"
    manifest = SourceManifest.model_validate_json((raw / MANIFEST_NAME).read_text())
    assert manifest.domain.value == "water" and manifest.license == "Open Government Licence v3.0"
    assert sorted(f.path for f in manifest.files) == [f"obs/2019/page-000{i}.csv" for i in range(3)] + [
        f"obs/2019/{INDEX_NAME}"
    ]
    for entry in manifest.files:
        path = raw / entry.path
        assert entry.sha256 == sha256_file(path) and entry.bytes == path.stat().st_size
        assert not path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
        if entry.path.endswith(".csv"):
            assert entry.url.startswith(f"{BASE}/data/observation?") and "skip=" in entry.url
    assert not list(raw.rglob("*.part")) and "downloaded obs/2019/request.json at " in " ".join(manifest.notes)
    index = json.loads((raw / "obs/2019" / INDEX_NAME).read_text())
    assert index["total_items"] == 5 == index["rows"] and index["query"]["limit"] == 2


def test_second_run_makes_no_request_and_leaves_the_manifest_byte_identical(tmp_path):
    api, client, store = setup(tmp_path)
    fetch_collection(store, client, rel_dir="obs/2019", **QUERY)
    before = (tmp_path / "raw" / MANIFEST_NAME).read_bytes()
    n_calls = len(api.calls)

    store2 = build_store(tmp_path / "raw", CONFIG, period=(2019, 2019))  # a fresh process
    again = fetch_collection(store2, client, rel_dir="obs/2019", **QUERY)
    assert not again.fetched and len(api.calls) == n_calls and again.total_items == 5
    assert store2.commit() is None  # nothing changed: no rewrite
    assert (tmp_path / "raw" / MANIFEST_NAME).read_bytes() == before


def test_a_different_query_for_the_same_directory_is_refetched(tmp_path):
    api, client, store = setup(tmp_path)
    fetch_collection(store, client, rel_dir="obs/2019", **QUERY)
    n_calls = len(api.calls)
    other = {**QUERY, "params": {**QUERY["params"], "determinand": "0111"}}
    fetch_collection(store, client, rel_dir="obs/2019", **other)
    assert len(api.calls) > n_calls


def test_modified_or_missing_page_is_detected_and_refetched(tmp_path):
    api, client, store = setup(tmp_path)
    fetch_collection(store, client, rel_dir="obs/2019", **QUERY)
    page = tmp_path / "raw/obs/2019/page-0001.csv"
    page.chmod(0o644)
    page.write_bytes(b"tampered")
    n_calls = len(api.calls)
    fresh = build_store(tmp_path / "raw", CONFIG, period=(2019, 2019))
    assert not fresh.is_intact("obs/2019/page-0001.csv")
    again = fetch_collection(fresh, client, rel_dir="obs/2019", **QUERY)
    assert again.fetched and len(api.calls) == n_calls + 3
    assert sha256_file(page) == fresh.files["obs/2019/page-0001.csv"].sha256 and page.read_bytes() != b"tampered"


def test_refresh_refetches_and_drops_pages_that_no_longer_exist(tmp_path):
    api, client, store = setup(tmp_path, n=5)
    fetch_collection(store, client, rel_dir="obs/2019", **QUERY)
    api.observations = observations(2)  # the archive shrank
    result = fetch_collection(store, client, rel_dir="obs/2019", refresh=True, **QUERY)
    assert result.fetched and [p["file"] for p in result.index["pages"]] == ["page-0000.csv"]
    assert not (tmp_path / "raw/obs/2019/page-0001.csv").exists()
    manifest = SourceManifest.model_validate_json((tmp_path / "raw" / MANIFEST_NAME).read_text())
    assert sorted(f.path for f in manifest.files) == ["obs/2019/page-0000.csv", f"obs/2019/{INDEX_NAME}"]


def test_empty_result_is_a_complete_empty_collection(tmp_path):
    api, client, store = setup(tmp_path, n=0)
    result = fetch_collection(store, client, rel_dir="obs/2019", **QUERY)
    assert result.total_items == 0 and result.index["pages"] == [] and len(api.calls) == 1
    again = fetch_collection(store, client, rel_dir="obs/2019", **QUERY)
    assert not again.fetched


def test_counts_that_do_not_add_up_are_rejected_and_nothing_enters_the_cache(tmp_path):
    rows = observations(4)
    from water_helpers import csv_bytes

    # the server claims 5 items but only delivers 4 (e.g. the archive refreshed while we were paging)
    transport = ScriptedTransport(
        ok(csv_bytes(rows[:2]), total=5, next_url=f"{BASE}/n"), ok(csv_bytes(rows[2:]), total=5)
    )
    client, _ = make_client(transport)
    store = build_store(tmp_path / "raw", CONFIG, period=(2019, 2019))
    with pytest.raises(InconsistentPaging, match="4 rows"):
        fetch_collection(store, client, rel_dir="obs/2019", **QUERY)
    assert not list((tmp_path / "raw").rglob("*.csv")) and not (tmp_path / "raw" / MANIFEST_NAME).exists()


def test_total_changing_between_pages_is_rejected(tmp_path):
    from water_helpers import csv_bytes

    rows = observations(4)
    transport = ScriptedTransport(
        ok(csv_bytes(rows[:2]), total=4, next_url=f"{BASE}/n"), ok(csv_bytes(rows[2:]), total=6)
    )
    client, _ = make_client(transport)
    store = build_store(tmp_path / "raw", CONFIG, period=(2019, 2019))
    with pytest.raises(InconsistentPaging):
        fetch_collection(store, client, rel_dir="obs/2019", **QUERY)


def test_a_failing_request_leaves_earlier_collections_committed_and_intact(tmp_path):
    api, client, store = setup(tmp_path)
    fetch_collection(store, client, rel_dir="obs/2019", **QUERY)
    failing, _ = make_client(ScriptedTransport(Response(500, {}, b"x"), Response(500, {}, b"x")), max_attempts=2)
    next_year = {**QUERY, "params": {**QUERY["params"], "dateFrom": "2020-01-01", "dateTo": "2020-12-01"}}
    with pytest.raises(Exception, match="after 2 attempts"):
        fetch_collection(store, failing, rel_dir="obs/2020", **next_year)
    fresh = build_store(tmp_path / "raw", CONFIG, period=(2019, 2020))
    assert all(fresh.is_intact(p) for p in fresh.files) and fresh.files
    assert all(p.startswith("obs/2019") for p in fresh.files)
