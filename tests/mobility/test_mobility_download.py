"""Download + manifest for the TLC files (fake fetcher, no network) and the month-range parser."""

import json
import urllib.error
from datetime import date
from pathlib import Path

import pytest

from atlas.contracts.models import SourceManifest
from atlas.domains.mobility.download import download, with_manual_fallback
from atlas.ingest.sources import MANIFEST_NAME, sha256_file

CONFIG = json.loads((Path(__file__).parents[2] / "configs" / "mobility" / "nyc_tlc.json").read_text(encoding="utf-8"))


class FakeNet:
    def __init__(self, refuse=()):
        self.calls, self.refuse = [], tuple(refuse)

    def __call__(self, url):
        self.calls.append(url)
        if url.endswith(self.refuse):
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
        return f"payload of {url}".encode()


def test_only_the_requested_months_are_fetched_and_the_manifest_is_complete(tmp_path):
    net = FakeNet()
    manifest, fetched = download(CONFIG, ["2025-02"], tmp_path, fetch=net)
    wanted = [f["path"] for f in CONFIG["tlc"]["files"] if f["role"] != "data" or f["month"] == "2025-02"]
    assert sorted(fetched) == sorted(wanted)
    assert "yellow_tripdata_2025-02.parquet" in fetched and "yellow_tripdata_2025-01.parquet" not in fetched
    on_disk = SourceManifest.model_validate_json((tmp_path / MANIFEST_NAME).read_text())
    assert on_disk == manifest and on_disk.source_id == "nyc-tlc" and on_disk.domain.value == "mobility"
    assert (manifest.period_start, manifest.period_end) == (date(2025, 2, 1), date(2025, 2, 28))
    assert "licence" in manifest.license and "TLC" in manifest.attribution
    for entry in manifest.files:
        assert entry.sha256 == sha256_file(tmp_path / entry.path) and entry.url.startswith("https://")
    assert (tmp_path / "taxi_zones.zip").stat().st_mode & 0o222 == 0  # raw files are read-only


def test_second_run_downloads_nothing(tmp_path):
    net = FakeNet()
    download(CONFIG, ["2025-01"], tmp_path, fetch=net)
    first = (tmp_path / MANIFEST_NAME).read_bytes()
    _, fetched = download(CONFIG, ["2025-01"], tmp_path, fetch=net)
    assert fetched == [] and (tmp_path / MANIFEST_NAME).read_bytes() == first


def test_unknown_month_is_rejected(tmp_path):
    with pytest.raises(SystemExit, match="2019-01"):
        download(CONFIG, ["2019-01"], tmp_path, fetch=FakeNet())


def test_blocked_pdf_falls_back_to_a_manually_saved_copy(tmp_path):
    (tmp_path / "manual").mkdir()
    (tmp_path / "manual" / "data_dictionary_trip_records_yellow.pdf").write_bytes(b"%PDF-manual")
    net = FakeNet(refuse=(".pdf",))
    manifest, _ = download(CONFIG, ["2025-01"], tmp_path, fetch=net)
    assert (tmp_path / "data_dictionary_trip_records_yellow.pdf").read_bytes() == b"%PDF-manual"
    assert any(f.path.endswith(".pdf") for f in manifest.files)


def test_blocked_file_without_a_manual_copy_still_fails(tmp_path):
    fetch = with_manual_fallback(tmp_path, FakeNet(refuse=(".pdf",)))
    with pytest.raises(urllib.error.HTTPError):
        fetch("https://example.test/x.pdf")
