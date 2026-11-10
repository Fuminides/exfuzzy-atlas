"""Contract v0.6.2: every served model has an explanation, written from its current published files, that passes the
validator of ``scripts/explain_model.py`` (numbers, wording, rule ids, the template's limits).

A republished model whose explanation was not regenerated fails here (``input_sha256`` no longer matches the context
rebuilt from the published files): run ``make explain MODEL_ID=<id>``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from atlas.contracts import models as m

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import explain_model as em  # noqa: E402


def test_every_served_model_has_a_current_valid_explanation(published):
    registry = json.loads((published / "registry.json").read_text())["tasks"]
    problems: list[str] = []
    for task_id, entry in sorted(registry.items()):
        model_id = entry["model_id"]
        path = em.OUT_DIR / f"{model_id}.json"
        if not path.is_file():
            problems.append(f"{task_id}: {model_id} has no explanation ({path.name}); make explain MODEL_ID={model_id}")
            continue
        explanation = m.ModelExplanation.model_validate_json(path.read_text(encoding="utf-8"))
        context = em.build_context(published, model_id)
        if explanation.model_id != model_id or explanation.data_version != context["data_version"]:
            problems.append(f"{task_id}: {path.name} is for {explanation.model_id} / {explanation.data_version}")
        if explanation.input_sha256 != em.context_sha256(context):
            problems.append(f"{task_id}: {path.name} was written from other published files (input_sha256 differs); "
                            f"make explain MODEL_ID={model_id}")
        if explanation.template_version != em.read_template()[1]:
            problems.append(f"{task_id}: written from template version {explanation.template_version}")
        texts = {"es": explanation.es.model_dump(), "en": explanation.en.model_dump()}
        problems += [f"{task_id}: {e}" for e in em.validate(texts, context)]
    assert problems == [], "\n".join(problems)
