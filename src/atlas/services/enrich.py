"""Contract v0.5 enrichment of a published model: input labels, rule importance, data summary and territory.

Contract v0.5.1 adds two display-only patches of the same kind: ``LinguisticTerm.label`` (the ``terms`` of each
``features`` entry) and ``TargetClass.display_label`` (the ``display_label`` of each class of the ``target_scheme``
block). They never change a term or class name, a rule or a prediction.

Contract v0.6 adds the English display fields, from the same blocks: ``label_en``, ``description_en`` and ``terms_en``
of each ``features`` entry (``LinguisticVariable.label_en``/``description_en``, ``LinguisticTerm.label_en``),
``display_label_en`` and ``description_en`` of each class and ``name_en``/``short_name_en`` of the ``target_scheme``
block, ``label_en`` of the ``summary`` block (``SummaryResponse.label_en``) and ``--territory-title-en`` for the
registry. An English label that states an age ("4 h ago") must agree with the feature_spec and with the Spanish label.
``--labels-only`` applies the display fields (rules, card and the label and classes of ``summary.json``) without
recomputing ``importance.json`` and ``summary.json``, so no number changes and the feature table is not read.

``publish_run`` calls :func:`apply_feature_labels` and :func:`write_importance_and_summary` while it builds a model
directory. The same steps can be added to a model that is **already published**, without republishing:

    python -m atlas.services.enrich --published-dir artifacts/published \\
        --model-id exfuzzy-madrid_no2_h6-ica2-justified-seed0 --metadata configs/air/attribution.json \\
        --territory madrid --territory-title Madrid [--features 'data/processed/air/features/madrid_no2_h6/table']

What the backfill does, in this order, and nothing else (model, predictions and activations are not touched):

1. verifies the model directory against its ``SHA256SUMS``;
2. computes ``importance.json`` and ``summary.json`` into a staging directory (nothing is visible yet);
3. patches the published ``rules.json`` with the ``features`` block of ``--metadata`` (labels, descriptions and term
   labels) and the ``display_label`` of the classes in its ``target_scheme`` block (also in ``card.json``; the rest of
   that block was applied by the v0.4 publish and is ignored here);
4. replaces the files, rewrites ``SHA256SUMS`` last (atomic replace), checks ``verify`` and records what it did under
   ``v05`` in ``publish.json``;
5. sets ``territory`` / ``territory_title`` (and ``territory_title_en``, v0.6) of the registry entry when given.

``--features`` defaults to the feature table recorded in ``publish.json``. A reader that opens the directory between
steps 4's file replacements sees a ``rules.json`` newer than ``SHA256SUMS`` for a few milliseconds (a model load would
refuse it); run the backfill when nobody is loading the model, or restart the API afterwards.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from atlas.contracts import models as m
from atlas.ml import artifacts
from atlas.services import layout, verify
from atlas.services.importance import compute_importance
from atlas.services.summary import classes_for, compute_summary

DEFAULT_MEMORY_LIMIT = "2GB"
_AGE_ES = re.compile(r"\bhace (\d+(?:[.,]\d+)?) h\b")
_AGE_EN = re.compile(r"\b(\d+(?:\.\d+)?) h ago\b")


def _stated_age(pattern: re.Pattern, label: str) -> float | None:
    """The age in hours that a label states ('hace 4 h', '4 h ago'), or None when it states none."""
    match = pattern.search(label)
    return None if match is None else float(match.group(1).replace(",", "."))


def apply_feature_labels(
    rules: m.ModelRules, features: dict[str, layout.FeatureMetadata], spec: layout.FeatureSpec,
) -> tuple[m.ModelRules, list[str]]:
    """The rules with ``label``/``description`` (and the ``terms`` labels) set on the variables named in ``features``.

    Refuses a name that is not in the ``feature_spec`` of the model, a label that states a ``lag_hours`` the spec
    contradicts, and a term label whose term the variable does not have (v0.5.1). v0.6 sets ``label_en``,
    ``description_en`` and the ``terms_en`` labels too, and refuses an English label whose stated age ("4 h ago") is
    not the spec's ``lag_hours`` or not the age the Spanish label states ("hace 4 h"). Returns the rules and the names
    of the variables that were labelled (a spec feature the model does not use is simply not shown).
    """
    if unknown := sorted(set(features) - set(spec.features)):
        raise ValueError(f"feature labels name inputs that are not in the feature_spec of the model: {unknown}")
    for name, meta in features.items():
        if meta.lag_hours is not None and meta.lag_hours != spec.features[name].lag_hours:
            raise ValueError(
                f"{name}: the label {meta.label!r} says lag_hours={meta.lag_hours:g} but the feature_spec says "
                f"{spec.features[name].lag_hours:g}"
            )
        if meta.label_en is not None:
            stated, spanish = _stated_age(_AGE_EN, meta.label_en), _stated_age(_AGE_ES, meta.label)
            lag = spec.features[name].lag_hours
            if stated is not None and stated != lag:
                raise ValueError(
                    f"{name}: the English label {meta.label_en!r} says {stated:g} h ago but the feature_spec says "
                    f"lag_hours={lag:g}")
            if stated != spanish:
                raise ValueError(
                    f"{name}: the English label {meta.label_en!r} and the Spanish label {meta.label!r} state different "
                    "ages")
    labelled = []
    variables = []
    for variable in rules.variables:
        meta = features.get(variable.feature)
        if meta is None:
            variables.append(variable)
            continue
        names = {t.name for t in variable.terms}
        if unknown := sorted((set(meta.terms) | set(meta.terms_en)) - names):
            raise ValueError(
                f"{variable.feature}: term labels name terms that the variable does not have: {unknown} "
                f"(its terms are {sorted(names)})")
        labelled.append(variable.feature)
        terms = []
        for t in variable.terms:
            update = {}
            if t.name in meta.terms:
                update["label"] = meta.terms[t.name]
            if t.name in meta.terms_en:
                update["label_en"] = meta.terms_en[t.name]
            terms.append(t.model_copy(update=update) if update else t)
        variables.append(variable.model_copy(update={
            "label": meta.label, "description": meta.description, "label_en": meta.label_en,
            "description_en": meta.description_en, "terms": terms}))
    return rules.model_copy(update={"variables": variables}), labelled


DISPLAY_CLASS_FIELDS = ("display_label", "display_label_en", "description_en")
DISPLAY_SCHEME_FIELDS = ("name_en", "short_name_en")


def apply_class_display_labels(scheme: m.TargetScheme, meta: layout.SchemeMetadata) -> m.TargetScheme:
    """The scheme with the display fields of ``meta`` set: ``display_label`` (v0.5.1), ``display_label_en`` and
    ``description_en`` of each class and ``name_en`` / ``short_name_en`` of the scheme (v0.6). A field ``meta`` leaves
    null is not touched; nothing else changes.

    Refuses a class that is not in the scheme.
    """
    if unknown := sorted(set(meta.classes) - {c.label for c in scheme.classes}):
        raise ValueError(f"scheme metadata names classes that are not in the target_scheme: {unknown}")
    classes = []
    for c in scheme.classes:
        extra = meta.classes.get(c.label)
        update = {} if extra is None else {
            f: getattr(extra, f) for f in DISPLAY_CLASS_FIELDS if getattr(extra, f) is not None}
        classes.append(c.model_copy(update=update) if update else c)
    update = {f: getattr(meta, f) for f in DISPLAY_SCHEME_FIELDS if getattr(meta, f) is not None}
    return scheme.model_copy(update={"classes": classes, **update})


def regression_fallback(model, rules: m.ModelRules) -> float | None:
    """The ``train_target_mean`` a zero-order TSK model returns when no rule fires; ``None`` for a classifier."""
    from atlas.explain import get_rulebase

    if rules.inference.family in m.CLASSIFIER_FAMILIES:
        return None
    y_mean = get_rulebase(model).y_mean
    return None if y_mean is None else float(y_mean)


def write_importance_and_summary(
    model_dir: Path, con, *, source: str, metadata: layout.PublishMetadata, fallback: float | None,
    into: Path | None = None, rules: m.ModelRules | None = None,
) -> dict:
    """Write ``importance.json`` and ``summary.json`` for the model directory; returns the record for ``publish.json``.

    Reads the published ``rules.json``, ``card.json``, ``entities.geojson``, ``predictions.parquet`` and
    ``activations/`` of ``model_dir`` and the feature table ``source``. The files go to ``into`` (default:
    ``model_dir``). ``rules`` are the rules to use instead of the ones in ``model_dir`` (the backfill passes the
    patched ones, so that the classes of ``summary.json`` carry their ``display_label``).
    """
    model_dir, into = Path(model_dir), Path(into or model_dir)
    if rules is None:
        rules = m.ModelRules.model_validate_json((model_dir / "rules.json").read_text())
    card = m.ModelCard.model_validate_json((model_dir / layout.CARD_FILE).read_text())
    entities = m.EntityCollection.model_validate_json((model_dir / layout.ENTITIES_FILE).read_text())
    manifest = card.manifest
    run_config = manifest.hyperparameters["run_config"]

    importance, importance_checks = compute_importance(
        model_dir, rules, data_version=manifest.data_version, synthetic=card.synthetic, fallback=fallback, con=con)
    (into / layout.IMPORTANCE_FILE).write_text(importance.model_dump_json(indent=2) + "\n")

    modelled = [f.properties for f in entities.features if f.properties.modelled is not False]
    zones = sorted({p.timezone for p in modelled})
    if len(zones) != 1:
        raise ValueError(f"the summary needs one time zone for the published entities, found {zones}")
    spec = metadata.summary or layout.SummaryMetadata(label=f"{manifest.target} observado")
    scheme = classes_for(rules.target_scheme)
    summary = compute_summary(
        con, source=source, task_id=manifest.task_id, domain=manifest.domain, variable=manifest.target,
        label=spec.label, unit=run_config["unit"], column=spec.column or run_config["target_column"],
        time_column=spec.time_column, horizon_hours=manifest.horizon_hours,
        entity_ids=sorted(p.entity_id for p in modelled), timezone=zones[0], scheme=scheme,
        data_version=manifest.data_version, synthetic=card.synthetic, notes=spec.notes,
    ).model_copy(update={"label_en": spec.label_en})
    (into / layout.SUMMARY_FILE).write_text(summary.model_dump_json(indent=2) + "\n")
    return {
        "importance": importance_checks,
        "summary": {
            "variable": summary.variable, "column": spec.column or run_config["target_column"],
            "time_column": spec.time_column, "binned_into_classes": summary.classes is not None,
            "n": summary.groups[m.SummaryGroup.ALL][0].n, "timezone": zones[0],
            "period_from_utc": summary.period_from_utc.isoformat(), "period_to_utc": summary.period_to_utc.isoformat(),
            "n_entities": len(modelled), "feature_table": source,
        },
    }


def apply_attribution_en(
    credits: list[m.Attribution], metadata: list[m.Attribution],
) -> tuple[list[m.Attribution], int]:
    """v0.6.1: copy ``text_en`` from the metadata credits onto the published ones with the same ``text``.

    Matching by the Spanish text never adds, drops or reorders a credit: only the English of a credit that is already
    published is filled in. Returns the credits and how many changed.
    """
    english = {a.text: a.text_en for a in metadata if a.text_en}
    out, changed = [], 0
    for credit in credits:
        en = english.get(credit.text)
        if en is not None and en != credit.text_en:
            credit = credit.model_copy(update={"text_en": en})
            changed += 1
        out.append(credit)
    return out, changed


def _checksum_text(model_dir: Path) -> str:
    names = sorted(p.relative_to(model_dir).as_posix() for p in model_dir.rglob("*") if p.is_file())
    return "".join(f"{artifacts.sha256_file(model_dir / n)}  {n}\n" for n in names if n != artifacts.CHECKSUM_FILE)


def _replace(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _patched_summary(model_dir: Path, metadata: layout.PublishMetadata, rules: m.ModelRules) -> str | None:
    """``summary.json`` with only its display fields refreshed (``--labels-only``): ``label`` and ``label_en`` from the
    ``summary`` block, and the classes from the patched scheme when the summary is binned into classes. Refuses a
    scheme whose class labels or bounds are not those of the summary. None when the model has no summary."""
    path = model_dir / layout.SUMMARY_FILE
    if not path.is_file():
        return None
    summary = m.SummaryResponse.model_validate_json(path.read_text())
    update: dict = {}
    if metadata.summary is not None:
        update |= {"label": metadata.summary.label, "label_en": metadata.summary.label_en}
    if summary.classes is not None:
        scheme = classes_for(rules.target_scheme)
        if scheme is None or [(c.label, c.lower, c.upper) for c in scheme.classes] != [
                (c.label, c.lower, c.upper) for c in summary.classes]:
            raise ValueError(f"{model_dir.name}: the summary classes are not those of the target_scheme")
        update["classes"] = scheme.classes
    return summary.model_copy(update=update).model_dump_json(indent=2) + "\n"


def _set_territory(published_dir: Path, model_id: str, territory: str, title: str | None, title_en: str | None) -> None:
    registry = layout.read_registry(published_dir)
    entries = [e for e in registry.tasks.values() if e.model_id == model_id]
    if not entries:
        raise ValueError(f"{model_id} is not in the registry of {published_dir}")
    for entry in entries:
        entry.territory, entry.territory_title, entry.territory_title_en = territory, title, title_en
    registry.schema_version = m.SCHEMA_VERSION
    layout.write_registry(published_dir, registry)


def backfill(
    published_dir: Path, model_id: str, *, metadata_path: Path | None = None, features: str | None = None,
    territory: str | None = None, territory_title: str | None = None, territory_title_en: str | None = None,
    memory_limit: str = DEFAULT_MEMORY_LIMIT, labels_only: bool = False,
) -> dict:
    """Add the v0.5 files, the v0.5/v0.6 labels and the territory to the published ``model_id``; returns the record.

    ``labels_only`` (v0.6) only applies the display fields: ``importance.json`` and the numbers of ``summary.json`` are
    kept as published and the feature table is not read.
    """
    started = time.perf_counter()
    published_dir = Path(published_dir)
    model_dir = published_dir / model_id
    if "/" in model_id or not (model_dir / artifacts.CHECKSUM_FILE).is_file():
        raise FileNotFoundError(f"{model_dir} is not a published model directory")
    if (territory_title is not None or territory_title_en is not None) and territory is None:
        raise ValueError("--territory-title and --territory-title-en need --territory")
    verify.verify_model_dir(model_dir)
    info = json.loads((model_dir / layout.PUBLISH_INFO_FILE).read_text())
    source = None
    if not labels_only:
        source = features or info.get("feature_table")
        if not source:
            raise ValueError("publish.json records no feature table: pass --features")
        from atlas.services.publish import _resolve_features  # noqa: PLC0415 - publish imports this module

        source = _resolve_features(source)
    metadata = (layout.PublishMetadata.model_validate_json(Path(metadata_path).read_text())
                if metadata_path is not None else layout.PublishMetadata())
    spec = layout.FeatureSpec.model_validate_json((model_dir / layout.FEATURE_SPEC_FILE).read_text())
    rules_text = (model_dir / "rules.json").read_text()
    rules = m.ModelRules.model_validate_json(rules_text)

    patch = None
    new_rules_text, new_card_text = rules_text, None
    patched_rules = rules
    fields, labelled, class_labels = [], [], []
    if metadata.features:
        patched_rules, labelled = apply_feature_labels(patched_rules, metadata.features, spec)
        fields += ["variables[].label", "variables[].description", "variables[].terms[].label",
                   "variables[].label_en", "variables[].description_en", "variables[].terms[].label_en"]
    if metadata.target_scheme is not None and patched_rules.target_scheme is not None:
        scheme = apply_class_display_labels(patched_rules.target_scheme, metadata.target_scheme)
        class_labels = [c.label for c in scheme.classes
                        if c.label in metadata.target_scheme.classes and (c.display_label or c.display_label_en)]
        if scheme != patched_rules.target_scheme:
            patched_rules = patched_rules.model_copy(update={"target_scheme": scheme})
            card = m.ModelCard.model_validate_json((model_dir / layout.CARD_FILE).read_text())
            new_card_text = card.model_copy(update={"target_scheme": scheme}).model_dump_json(indent=2) + "\n"
            fields += ["target_scheme.classes[].display_label", "target_scheme.classes[].display_label_en",
                       "target_scheme.classes[].description_en", "target_scheme.name_en",
                       "target_scheme.short_name_en"]
    # v0.6.1: the credits in English, in card.json and entities.geojson
    new_entities_text, n_credits_en = None, 0
    if metadata.attribution:
        card = m.ModelCard.model_validate_json(new_card_text or (model_dir / layout.CARD_FILE).read_text())
        credits, n_card = apply_attribution_en(card.attribution, metadata.attribution)
        if n_card:
            new_card_text = card.model_copy(update={"attribution": credits}).model_dump_json(indent=2) + "\n"
        entities = m.EntityCollection.model_validate_json((model_dir / layout.ENTITIES_FILE).read_text())
        credits, n_entities = apply_attribution_en(entities.attribution, metadata.attribution)
        if n_entities:
            new_entities_text = entities.model_copy(update={"attribution": credits}).model_dump_json(indent=2) + "\n"
        n_credits_en = n_card + n_entities
    if fields:
        new_rules_text = patched_rules.model_dump_json(indent=2) + "\n"
        patch = {
            "reason": "contract v0.5/v0.5.1/v0.6 display labels (variable, term and class labels, Spanish and "
                      "English); no retraining",
            "previous_rules_sha256": artifacts.sha256_file(model_dir / "rules.json"),
            "patched_fields": fields, "labelled": labelled,
            "n_term_labels": sum(t.label is not None for v in patched_rules.variables for t in v.terms),
            "n_term_labels_en": sum(t.label_en is not None for v in patched_rules.variables for t in v.terms),
            "class_display_labels": class_labels,
        }

    stage = Path(tempfile.mkdtemp(prefix=".v05-", dir=published_dir))
    try:
        if labels_only:
            summary_text = _patched_summary(model_dir, metadata, patched_rules)
            if summary_text is not None:
                (stage / layout.SUMMARY_FILE).write_text(summary_text)
            record = {"backfilled_at_utc": datetime.now(timezone.utc).isoformat(), "rules_json_patch": patch,
                      "summary_display_fields": summary_text is not None, "credits_text_en": n_credits_en,
                      "note": "--labels-only: importance.json and the numbers of summary.json are unchanged"}
            # a later labels pass (v0.6.1 credits) keeps the record of the first v0.6 backfill
            info["v061" if "v06" in info else "v06"] = record
            replaced = [layout.SUMMARY_FILE] if summary_text is not None else []
        else:
            classifier = rules.inference.family in m.CLASSIFIER_FAMILIES
            fallback = None if classifier else regression_fallback(verify.load_verified_model(model_dir), rules)
            con = duckdb.connect(config={"memory_limit": memory_limit, "threads": 2})
            try:
                con.execute("SET TimeZone='UTC'")
                con.execute(f"SET temp_directory = '{str(stage / 'spill').replace(chr(39), chr(39) * 2)}'")
                record = write_importance_and_summary(
                    model_dir, con, source=source, metadata=metadata, fallback=fallback, into=stage,
                    rules=patched_rules)
            finally:
                con.close()
            record |= {"backfilled_at_utc": datetime.now(timezone.utc).isoformat(), "rules_json_patch_v05": patch}
            info["v05"] = record
            replaced = [layout.IMPORTANCE_FILE, layout.SUMMARY_FILE]
        (stage / layout.PUBLISH_INFO_FILE).write_text(json.dumps(info, indent=2) + "\n")
        # replace the files, SHA256SUMS last
        for name in replaced:
            os.replace(stage / name, model_dir / name)
        if patch is not None:
            _replace(model_dir / "rules.json", new_rules_text)
        if new_card_text is not None:
            _replace(model_dir / layout.CARD_FILE, new_card_text)
        if new_entities_text is not None:
            _replace(model_dir / layout.ENTITIES_FILE, new_entities_text)
        os.replace(stage / layout.PUBLISH_INFO_FILE, model_dir / layout.PUBLISH_INFO_FILE)
        _replace(model_dir / artifacts.CHECKSUM_FILE, _checksum_text(model_dir))
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    verify.verify_model_dir(model_dir)
    if territory is not None:
        _set_territory(published_dir, model_id, territory, territory_title, territory_title_en)
    record["seconds"] = round(time.perf_counter() - started, 2)
    return record


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m atlas.services.enrich", description=__doc__.split("\n\n")[0])
    parser.add_argument("--published-dir", type=Path, required=True)
    parser.add_argument("--model-id", help="default: the only model of the registry")
    parser.add_argument("--metadata", type=Path, help="PublishMetadata JSON (configs/<domain>/attribution*.json): "
                        "the features block labels the inputs, the summary block names the observed variable")
    parser.add_argument("--features", help="feature table (default: the one recorded in publish.json)")
    parser.add_argument("--territory", help="registry territory id, e.g. madrid")
    parser.add_argument("--territory-title", help="display name of the territory, e.g. Madrid")
    parser.add_argument("--territory-title-en", help="v0.6: English display name of the territory, e.g. Germany")
    parser.add_argument("--labels-only", action="store_true",
                        help="v0.6: apply the display fields only; importance.json and summary.json numbers are kept")
    parser.add_argument("--memory-limit", default=DEFAULT_MEMORY_LIMIT, help="DuckDB memory limit (default 2GB)")
    args = parser.parse_args(argv)
    model_id = args.model_id
    if model_id is None:
        ids = sorted({e.model_id for e in layout.read_registry(args.published_dir).tasks.values()})
        if len(ids) != 1:
            raise SystemExit(f"--model-id is required: the registry has {len(ids)} models")
        model_id = ids[0]
    record = backfill(
        args.published_dir, model_id, metadata_path=args.metadata, features=args.features, territory=args.territory,
        territory_title=args.territory_title, territory_title_en=args.territory_title_en,
        memory_limit=args.memory_limit, labels_only=args.labels_only,
    )
    print(json.dumps({"model_id": model_id, **record}, indent=2))


if __name__ == "__main__":
    main()
