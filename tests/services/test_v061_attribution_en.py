"""Contract v0.6.1: the source credits in English (``Attribution.text_en``), filled in by the labels-only backfill."""

import json
import shutil

from test_v05_enrich import read

from atlas.contracts import models as m
from atlas.ml import artifacts
from atlas.services import enrich, layout, verify
from atlas.services.synthetic import V04_METADATA

FIRST = V04_METADATA.attribution[0].text


def test_english_is_copied_by_matching_text_and_never_adds_drops_or_reorders_credits():
    published = [m.Attribution(text="b"), m.Attribution(text="a", license="CC BY 4.0")]
    metadata = [m.Attribution(text="a", text_en="A"), m.Attribution(text="c", text_en="C")]
    credits, changed = enrich.apply_attribution_en(published, metadata)
    assert [(c.text, c.text_en, c.license) for c in credits] == [("b", None, None), ("a", "A", "CC BY 4.0")]
    assert changed == 1
    assert enrich.apply_attribution_en(credits, metadata)[1] == 0  # idempotent


def test_the_labels_only_backfill_writes_the_english_credits_in_card_and_entities_and_nothing_else(built_v04, tmp_path):
    root = tmp_path / "published"
    shutil.copytree(built_v04.published_dir, root)
    model_dir = root / built_v04.model_dir.name
    before = {p.name: artifacts.sha256_file(p) for p in model_dir.iterdir() if p.is_file()}
    credits = [a.model_copy(update={"text_en": "Synthetic data: made up (English)."}) if a.text == FIRST else a
               for a in V04_METADATA.attribution]
    metadata = tmp_path / "metadata.json"
    metadata.write_text(V04_METADATA.model_copy(update={"attribution": credits}).model_dump_json())
    enrich.main(["--published-dir", str(root), "--model-id", model_dir.name, "--metadata", str(metadata),
                 "--labels-only", "--features", "/nonexistent/never/read.parquet"])
    verify.verify_model_dir(model_dir)
    for credits_now in (read(model_dir, layout.CARD_FILE, m.ModelCard).attribution,
                        read(model_dir, layout.ENTITIES_FILE, m.EntityCollection).attribution):
        english = "Synthetic data: made up (English)."
        assert [(c.text, c.text_en) for c in credits_now] == [
            (a.text, english if a.text == FIRST else None) for a in V04_METADATA.attribution]
    # entities: only the credits changed (features and geometry are the same)
    old = json.loads((built_v04.model_dir / layout.ENTITIES_FILE).read_text())
    new = json.loads((model_dir / layout.ENTITIES_FILE).read_text())
    assert {k: v for k, v in new.items() if k != "attribution"} == {k: v for k, v in old.items() if k != "attribution"}
    for name in ("model.pkl", "predictions.parquet", "inputs.parquet", "importance.json", "run_manifest.json"):
        assert artifacts.sha256_file(model_dir / name) == before[name], name
    info = json.loads((model_dir / layout.PUBLISH_INFO_FILE).read_text())
    record = info.get("v061") or info["v06"]
    assert record["credits_text_en"] == 2  # card.json and entities.geojson


def test_every_shipped_spanish_credit_has_its_english():
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    for path in ("configs/air/attribution.json", "configs/mobility/attribution.json"):
        meta = layout.PublishMetadata.model_validate_json((repo / path).read_text())
        assert meta.attribution and all(a.text_en for a in meta.attribution), path
