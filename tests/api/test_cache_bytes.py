"""B5 (AT-061): the response caches are bounded by approximate bytes, not by number of entries."""

from datetime import datetime, timedelta, timezone

import pytest

from atlas.contracts import models as m
from atlas_api.artifact_store import ArtifactStore
from atlas_api.cache import ByteLRU, approx_bytes

WINDOW = (datetime(2024, 1, 10, tzinfo=timezone.utc), datetime(2024, 1, 12, tzinfo=timezone.utc))
FREQ = m.RuleMapMetric.ACTIVATION_FREQUENCY


def test_byte_lru_evicts_least_recently_used_until_within_budget():
    cache = ByteLRU(100)
    cache.put(("a",), "A", 40)
    cache.put(("b",), "B", 40)
    assert cache.get(("a",)) == "A"  # a is now the most recent
    cache.put(("c",), "C", 40)  # 120 > 100: evicts b, the least recently used
    assert (cache.get(("b",)), cache.get(("a",)), cache.get(("c",))) == (None, "A", "C")
    assert cache.bytes == 80 and len(cache) == 2
    cache.put(("a",), "A2", 10)  # replacing an entry replaces its size
    assert cache.bytes == 50 and cache.get(("a",)) == "A2"


def test_an_entry_bigger_than_the_whole_budget_is_not_stored_and_evicts_nothing():
    cache = ByteLRU(100)
    cache.put(("a",), "A", 60)
    cache.put(("huge",), "H", 101)
    assert cache.get(("huge",)) is None and cache.get(("a",)) == "A" and cache.bytes == 60
    cache.put(("a",), "A-too-big-now", 500)  # a stale smaller entry must not survive the replacement
    assert cache.get(("a",)) is None and cache.bytes == 0


def test_the_store_evicts_by_bytes(built, monkeypatch):
    model_id = built.run.manifest.model_id
    one = approx_bytes(ArtifactStore(built.published_dir).rule_map(model_id, "R01", FREQ, None, *WINDOW, 0.5))
    store = ArtifactStore(built.published_dir, cache_bytes=int(one * 2.5))  # room for two maps, not three
    calls = []
    original = store._compute_rule_map
    monkeypatch.setattr(store, "_compute_rule_map", lambda *a: calls.append(a) or original(*a))

    first = store.rule_map(model_id, "R01", FREQ, None, *WINDOW, 0.5)
    assert store.rule_map(model_id, "R01", FREQ, None, *WINDOW, 0.5) is first and len(calls) == 1
    for tau in (0.6, 0.7, 0.8, 0.9):  # four more maps: the byte budget keeps the last two only
        store.rule_map(model_id, "R01", FREQ, None, *WINDOW, tau)
        assert store._cache.bytes <= store._cache.max_bytes
    assert len(store._cache) == 2 and len(calls) == 5
    store.rule_map(model_id, "R01", FREQ, None, *WINDOW, 0.9)  # most recent: still cached
    assert len(calls) == 5
    store.rule_map(model_id, "R01", FREQ, None, *WINDOW, 0.5)  # evicted long ago: computed again
    assert len(calls) == 6


def test_a_response_bigger_than_the_budget_is_served_but_not_kept(built, monkeypatch):
    model_id = built.run.manifest.model_id
    store = ArtifactStore(built.published_dir, cache_bytes=100)
    calls = []
    original = store._compute_rule_map
    monkeypatch.setattr(store, "_compute_rule_map", lambda *a: calls.append(a) or original(*a))
    a = store.rule_map(model_id, "R01", FREQ, None, *WINDOW, 0.5)
    b = store.rule_map(model_id, "R01", FREQ, None, *WINDOW, 0.5)
    assert a == b and len(calls) == 2 and len(store._cache) == 0 and store._cache.bytes == 0


def test_territories_and_stories_share_the_byte_budget(built_v04):
    model_id = built_v04.run.manifest.model_id
    store = ArtifactStore(built_v04.published_dir, cache_bytes=30_000)
    start = datetime(2024, 1, 10, tzinfo=timezone.utc)
    for days in range(2, 9):
        end = start + timedelta(days=days)
        store.rule_territories(model_id, start, end, m.TerritoryMeasure.MEAN_ACTIVATION, 0.5)
        store.rule_stories(model_id, start, end, 0.5, 5)
        assert store._cache.bytes <= 30_000
    assert 0 < len(store._cache) < 14


def test_the_budget_is_configurable_from_the_environment(built, monkeypatch):
    monkeypatch.setenv("ATLAS_PUBLISHED_DIR", str(built.published_dir))
    monkeypatch.setenv("ATLAS_CACHE_MB", "0.5")
    assert ArtifactStore.from_env()._cache.max_bytes == 512 * 1024
    monkeypatch.delenv("ATLAS_CACHE_MB")
    assert ArtifactStore.from_env()._cache.max_bytes == 64 * 2**20


def test_negative_budget_is_refused():
    with pytest.raises(ValueError):
        ByteLRU(-1)
