"""Idempotent download + manifest (fake fetcher, no network)."""

import json
from datetime import datetime, timezone

from atlas.contracts.models import Domain, SourceManifest
from atlas.ingest.sources import MANIFEST_NAME, ensure_source, sha256_file

FILES = [
    {"path": "a.zip", "url": "https://example.test/a.zip"},
    {"path": "b.csv", "url": "https://example.test/b.csv"},
]
META = dict(
    source_id="madrid-air",
    domain=Domain.AIR,
    title="t",
    landing_url="https://example.test",
    license="CC BY 4.0",
    attribution="Ayuntamiento de Madrid",
)


class FakeNet:
    def __init__(self):
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        return f"payload of {url}".encode()


def clock(*stamps):
    it = iter(stamps)
    return lambda: datetime.fromisoformat(next(it)).replace(tzinfo=timezone.utc)


def test_first_run_downloads_and_writes_a_valid_manifest(tmp_path):
    net = FakeNet()
    manifest, fetched = ensure_source(
        tmp_path, files=FILES, fetch=net, now=clock("2026-10-30T10:00:00", "2026-10-30T10:00:01"), **META
    )
    assert fetched == ["a.zip", "b.csv"] and len(net.calls) == 2
    on_disk = SourceManifest.model_validate_json((tmp_path / MANIFEST_NAME).read_text())
    assert on_disk == manifest and on_disk.license == "CC BY 4.0"
    for entry in on_disk.files:
        assert (
            entry.sha256 == sha256_file(tmp_path / entry.path) and entry.bytes == (tmp_path / entry.path).stat().st_size
        )
        assert entry.url.startswith("https://example.test/")
    assert not list(tmp_path.glob("*.part")) and (tmp_path / "a.zip").stat().st_mode & 0o222 == 0  # read-only raw


def test_second_run_is_a_no_op_and_the_manifest_is_byte_identical(tmp_path):
    net = FakeNet()
    ensure_source(tmp_path, files=FILES, fetch=net, now=clock("2026-10-30T10:00:00", "2026-10-30T10:00:01"), **META)
    first = (tmp_path / MANIFEST_NAME).read_bytes()
    _, fetched = ensure_source(tmp_path, files=FILES, fetch=net, now=clock("2027-01-01T00:00:00"), **META)
    assert fetched == [] and len(net.calls) == 2  # nothing fetched again
    assert (tmp_path / MANIFEST_NAME).read_bytes() == first


def test_a_corrupted_or_missing_file_is_fetched_again_but_others_keep_their_timestamp(tmp_path):
    net = FakeNet()
    ensure_source(tmp_path, files=FILES, fetch=net, now=clock("2026-10-30T10:00:00", "2026-10-30T10:00:01"), **META)
    (tmp_path / "b.csv").chmod(0o644)
    (tmp_path / "b.csv").write_text("tampered")
    manifest, fetched = ensure_source(tmp_path, files=FILES, fetch=net, now=clock("2026-11-02T08:00:00"), **META)
    assert fetched == ["b.csv"] and net.calls[-1] == "https://example.test/b.csv"
    assert (tmp_path / "b.csv").read_bytes() == b"payload of https://example.test/b.csv"
    notes = {n for n in manifest.notes}
    assert "downloaded a.zip at 2026-10-30T10:00:00Z" in notes and "downloaded b.csv at 2026-11-02T08:00:00Z" in notes
    assert manifest.downloaded_at_utc.isoformat().startswith("2026-11-02T08:00:00")


def test_refresh_forces_a_new_download(tmp_path):
    net = FakeNet()
    ensure_source(tmp_path, files=FILES, fetch=net, now=clock("2026-10-30T10:00:00", "2026-10-30T10:00:01"), **META)
    _, fetched = ensure_source(
        tmp_path, files=FILES, fetch=net, refresh=True, now=clock("2026-11-01T00:00:00", "2026-11-01T00:00:01"), **META
    )
    assert fetched == ["a.zip", "b.csv"]
    assert json.loads((tmp_path / MANIFEST_NAME).read_text())["files"][0]["path"] == "a.zip"
