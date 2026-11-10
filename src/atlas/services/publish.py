"""Publish a trained run as precomputed views for the API's artifacts mode (AT-045).

    python -m atlas.services.publish --run-dir artifacts/<task>/<run> \\
        --features 'data/processed/air/features/*.parquet' --entities data/processed/air/stations.geojson \\
        --feature-spec configs/air/feature_spec.json --from 2023-01-01T00:00:00Z --to 2025-01-01T00:00:00Z

The feature table is read with DuckDB one UTC month at a time, so memory is bounded by a month of rows (times the
number of rules for the firing table), never by the period. For every month the model is run once: the inputs,
the predictions and the tidy firing table (``atlas.explain.iter_firing_tables``) are appended to the model
directory. Layout: ``atlas.services.layout``. Nothing here trains or changes the model.

Winning-rule classifiers (contract v0.3, rules with an ``inference.family`` of ``winning_rule_classifier``) go through
the same steps with three differences: the firing table is ``atlas.explain.iter_classifier_firing_tables`` (it adds
``weight``, ``association_degree`` and ``is_winner``), the predictions carry ``prediction_label`` and
``observed_label`` (``prediction`` is null in every row: a class index is never published as a number), and
``card.json`` carries the run's ``target_scheme``.

``observed_label_column`` (``--observed-label-column``) takes the observed class from a table column instead of
applying the scheme bounds to the numeric ``observed`` value, which is wrong when the scheme is not expressed in the
units of the target (NYC: the target is a pickup count, the bounds are percentiles of a zone x week-hour reference and
the table carries the precomputed ``target_level``). A row with an observed value but no label (no reference level)
is published with a null ``prediction_label`` and ``missing_reason = prediction_unavailable``, never as a class.

``irregular_times`` (``--irregular-times``) is for tasks whose issue times are sample times and not a regular grid
(Water: minute timestamps, horizon 0): without it a gcd of the gaps that is not a whole number of hours is refused;
with it ``coverage.step_hours`` is 1 (the finest step ``TimeCoverage`` can express) and the card warns that the
timeline is not a grid, so that maps should use ``mean_activation`` / ``activation_frequency`` windows and not
``firing_strength`` instants. It also sets ``coverage.regular = False`` (contract v0.4).

Contract v0.4 additions: ``metadata_path`` (``--metadata``) is a ``layout.PublishMetadata`` JSON with the attribution
of the sources (written to ``entities.geojson`` and ``card.json``) and, for classifiers, the scheme ``kind``,
``short_name`` and per-class ``merged_from`` / description. The scheme part is applied to the published copy of
``rules.json`` only (the run directory is untouched, nothing is retrained); ``publish.json`` records the checksum of
the run's original ``rules.json`` and what was patched. Every published entity carries ``modelled = true``;
``include_unmodelled_entities`` (``--include-unmodelled-entities``) also publishes the entities of the geometry file
that have no data and do have a geometry, with ``modelled = false``, so the map can say "sin modelo" instead of
hiding them.

Contract v0.5.1: the ``terms`` of each ``features`` entry label the terms (``LinguisticTerm.label``; a name the
variable does not have is refused) and ``display_label`` of a class in the ``target_scheme`` block sets
``TargetClass.display_label``. Both are display only: no key, rule or prediction changes.

Contract v0.5 additions: the ``features`` block of the metadata labels the inputs of the published ``rules.json`` (names
must be in the ``feature_spec``; a ``lag_hours`` stated in the metadata must equal the spec's), ``--territory`` and
``--territory-title`` go to the registry, and ``importance.json`` (rule and input importance, from the published
activations and predictions) and ``summary.json`` (distribution of the observed variable over the whole feature table)
are written next to the other files and listed in ``SHA256SUMS``. ``atlas.services.enrich`` documents them and can add
them to a model that is already published.

Contract v0.7: a mixture-of-rules classifier (``inference.family`` = ``rule_mixture_classifier``) is published like a
winning-rule classifier with three differences: the firing table is ``atlas.explain.iter_mixture_firing_tables``
(``firing_strength``, ``centred_contribution`` to the predicted class and ``is_decisive``; no weight, association or
winner, since no rule decides alone), the predictions add ``top_rule_id`` and ``top_rule_share`` (the rule that
supports the predicted class the most; null where the label is null or withheld) and ``importance.json`` uses the
``rule_mixture`` measures.

Contract v0.6: the English display fields of the same blocks (``label_en``, ``description_en`` and ``terms_en`` of a
feature, ``display_label_en`` / ``description_en`` of a class, ``name_en`` / ``short_name_en`` of the scheme,
``label_en`` of the summary) are applied the same way, and ``--territory-title-en`` goes to the registry. An English
label that states an age ("4 h ago") must agree with the feature_spec and the Spanish label (``enrich``).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass
from dataclasses import replace as dataclass_replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from atlas import compound_terms
from atlas.contracts import models as m
from atlas.explain import iter_classifier_firing_tables, iter_firing_tables, iter_mixture_firing_tables
from atlas.explain.mixture import mixture_top_rules
from atlas.ml import artifacts
from atlas.ml.pipeline import LoadedRun, load_run
from atlas.paths import ARTIFACTS_DIR
from atlas.services import enrich, layout, verify

PUBLISHED_DIR = ARTIFACTS_DIR / "published"

# Activations layout (AT-061 / B3): each monthly file is sorted by these columns and written in row groups of this size,
# so a query with `rule_id = ?` reads the row groups of that rule (min/max statistics) and not the whole month.
ACTIVATION_SORT = ("rule_id", "issued_at_utc", "entity_id")
ACTIVATION_ROW_GROUP_SIZE = 100_000

_TS = pa.timestamp("us", tz="UTC")
INPUT_ID_SCHEMA = [("entity_id", pa.string()), ("issued_at_utc", _TS)]
PREDICTION_SCHEMA = pa.schema([
    ("entity_id", pa.string()), ("issued_at_utc", _TS), ("valid_at_utc", _TS), ("prediction", pa.float64()),
    ("observed", pa.float64()), ("missing_reason", pa.string()),
])
ACTIVATION_SCHEMA = pa.schema([
    ("entity_id", pa.string()), ("issued_at_utc", _TS), ("rule_id", pa.string()),
    ("firing_strength", pa.float64()), ("effective_firing", pa.float64()), ("missing_reason", pa.string()),
])
CLASS_PREDICTION_SCHEMA = pa.schema([
    ("entity_id", pa.string()), ("issued_at_utc", _TS), ("valid_at_utc", _TS), ("prediction", pa.float64()),
    ("observed", pa.float64()), ("observed_label", pa.string()), ("prediction_label", pa.string()),
    ("missing_reason", pa.string()),
])
CLASS_ACTIVATION_SCHEMA = pa.schema([
    ("entity_id", pa.string()), ("issued_at_utc", _TS), ("rule_id", pa.string()),
    ("firing_strength", pa.float64()), ("weight", pa.float64()), ("association_degree", pa.float64()),
    ("is_winner", pa.bool_()), ("missing_reason", pa.string()),
])
MIXTURE_PREDICTION_SCHEMA = pa.schema([*CLASS_PREDICTION_SCHEMA, ("top_rule_id", pa.string()),
                                       ("top_rule_share", pa.float64())])
MIXTURE_ACTIVATION_SCHEMA = pa.schema([
    ("entity_id", pa.string()), ("issued_at_utc", _TS), ("rule_id", pa.string()),
    ("firing_strength", pa.float64()), ("centred_contribution", pa.float64()), ("is_decisive", pa.bool_()),
    ("missing_reason", pa.string()),
])


@dataclass(frozen=True)
class PublishSummary:
    model_dir: Path
    n_input_rows: int
    n_activation_records: int
    n_entities: int
    coverage: m.TimeCoverage
    seconds: float


def _utc(value: datetime | str) -> datetime:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None or stamp.utcoffset() != timedelta(0):
        raise ValueError(f"{value!r}: timestamps must carry an explicit UTC offset (e.g. 2024-01-01T00:00:00Z)")
    return stamp.to_pydatetime().astimezone(timezone.utc)


def _months(start: datetime, end: datetime) -> Iterator[tuple[int, int, datetime, datetime]]:
    """``(year, month, lo, hi)`` for every UTC calendar month touched by ``[start, end)``, clipped to it."""
    year, month = start.year, start.month
    while True:
        first = datetime(year, month, 1, tzinfo=timezone.utc)
        if first >= end:
            return
        nxt = datetime(year + month // 12, month % 12 + 1, 1, tzinfo=timezone.utc)
        yield year, month, max(start, first), min(end, nxt)
        year, month = nxt.year, nxt.month


def task_type_of(run: LoadedRun) -> str:
    """``classification`` for a classifier run (winning rule or, v0.7, mixture of rules; read from its ``rules.json``),
    else ``regression``."""
    return "classification" if run.rules.inference.family in m.CLASSIFIER_FAMILIES else "regression"


def is_mixture_run(run: LoadedRun) -> bool:
    return run.rules.inference.family == m.InferenceFamily.RULE_MIXTURE_CLASSIFIER


def classify_observed(scheme: m.TargetScheme, values) -> list[str | None]:
    """Class label of each observed value; ``None`` for NaN or a value outside the scheme.

    Same convention as ``atlas.ml.classification.ClassScheme.classify`` (which produced the run's own labels):
    values are rounded half up to whole numbers, then the class is the first whose upper bound is not below the
    value (``upper_inclusive``); the first class is unbounded below only when its ``lower`` is null.
    """
    if scheme.boundary != "upper_inclusive":
        raise ValueError(f"unsupported target_scheme boundary {scheme.boundary!r}")
    v = np.floor(np.asarray(values, dtype=float) + 0.5)
    uppers = np.array([np.inf if c.upper is None else c.upper for c in scheme.classes])  # null: open top class
    idx = np.searchsorted(uppers, v, side="left")
    lowest = scheme.classes[0].lower
    bad = ~np.isfinite(v) | (idx >= len(uppers)) | (False if lowest is None else v <= lowest)
    labels = np.array([c.label for c in scheme.classes] + [None], dtype=object)
    return labels[np.where(bad, len(uppers), idx)].tolist()


def _table(frame: pd.DataFrame, schema: pa.Schema) -> pa.Table:
    """Arrow table in ``schema``; NaN becomes null (a missing value must never reach a file as a number)."""
    table = pa.Table.from_pandas(frame, preserve_index=False)
    return table.select(schema.names).cast(schema)


def _resolve_features(features: str | Path) -> str:
    path = Path(features)
    return str(path / "**" / "*.parquet") if path.is_dir() else str(features)


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _sql_path(path: Path) -> str:
    """``path`` for inside a single-quoted DuckDB string literal."""
    return str(path).replace("'", "''")


def _write_sorted_activations(
    con, chunks: list[Path], target: Path, schema: pa.Schema, row_group_size: int,
) -> None:
    """One Parquet file with the rows of ``chunks`` ordered by ``ACTIVATION_SORT``, in row groups of ``row_group_size``.

    The sort leads with the rule, so the file is written rule by rule: DuckDB sorts one rule's records of the month
    (spilling to its ``temp_directory`` beyond ``memory_limit``) and streams them, and memory stays bounded by one
    rule's month, not by the month of firing records. The rows and row groups are those of a single sort of the
    whole month. Values are copied, never recomputed, and the file is written by Arrow with the same ``schema`` as
    before (DuckDB's own writer marks columns without nulls as required).
    """
    if ACTIVATION_SORT[0] != "rule_id":
        raise AssertionError("the activations are written rule by rule: ACTIVATION_SORT must lead with rule_id")
    files = ", ".join(f"'{_sql_path(p)}'" for p in chunks)
    order = ", ".join(ACTIVATION_SORT[1:])
    rule_ids = [r[0] for r in con.execute(f"SELECT DISTINCT rule_id FROM read_parquet([{files}]) ORDER BY rule_id")
                .fetchall()]

    def write(out, batches: list[pa.RecordBatch]) -> None:
        table = pa.Table.from_batches(batches).select(schema.names).cast(schema)
        out.write_table(table, row_group_size=row_group_size)

    pending: list[pa.RecordBatch] = []
    held = 0
    with pq.ParquetWriter(target, schema, compression="zstd") as out:
        for rule_id in rule_ids:
            reader = con.sql(f"SELECT * FROM read_parquet([{files}]) WHERE rule_id = ? ORDER BY {order}",
                             params=[rule_id]).to_arrow_reader(row_group_size)
            for batch in reader:  # DuckDB hands over uneven batches: regroup them into row groups of exactly the size
                pending.append(batch)
                held += batch.num_rows
                if held >= row_group_size:
                    whole = pa.Table.from_batches(pending)
                    full = held - held % row_group_size
                    write(out, whole.slice(0, full).to_batches())
                    rest = whole.slice(full)
                    pending, held = rest.to_batches(), rest.num_rows
        if held:
            write(out, pending)


def _load_entities(path: Path, domain: m.Domain) -> m.EntityCollection:
    collection = m.EntityCollection.model_validate_json(Path(path).read_text())
    if collection.domain != domain:
        raise ValueError(f"entities file is for domain {collection.domain.value}, the model is for {domain.value}")
    return collection


def _copy_run_files(run_dir: Path, dest: Path) -> None:
    """Copy the run files the API serves and prove each copy is byte-identical to what the run checksummed."""
    artifacts.verify_checksums(run_dir)
    expected = {}
    for line in (run_dir / artifacts.CHECKSUM_FILE).read_text().splitlines():
        digest, name = line.split("  ", 1)
        expected[name] = digest
    for name in layout.RUN_FILES:
        if name not in expected:
            raise ValueError(f"{name} is not listed in {run_dir / artifacts.CHECKSUM_FILE}")
        shutil.copyfile(run_dir / name, dest / name)
        if artifacts.sha256_file(dest / name) != expected[name]:
            raise ValueError(f"copy of {name} differs from the checksummed run file")


def apply_scheme_metadata(scheme: m.TargetScheme, meta: layout.SchemeMetadata) -> m.TargetScheme:
    """The scheme with its kind, short name and class documentation set (labels, bounds and colours unchanged).

    ``display_label`` (v0.5.1) is the shown name of a class; ``label`` stays the key. The English display fields
    (v0.6: ``display_label_en``, ``description_en``, ``name_en``, ``short_name_en``) are set as well."""
    labels = {c.label for c in scheme.classes}
    if unknown := sorted(set(meta.classes) - labels):
        raise ValueError(f"scheme metadata names classes that are not in the target_scheme: {unknown}")
    classes = []
    for c in scheme.classes:
        extra = meta.classes.get(c.label)
        update = {}
        if extra is not None:
            update["merged_from"] = extra.merged_from
            if extra.description is not None:
                update["description"] = extra.description
            if extra.display_label is not None:
                update["display_label"] = extra.display_label
        classes.append(c.model_copy(update=update))
    scheme = scheme.model_copy(update={"kind": meta.kind, "short_name": meta.short_name, "classes": classes})
    return m.TargetScheme.model_validate(enrich.apply_class_display_labels(scheme, meta).model_dump())


def _patch_published_rules(
    dest: Path, run: LoadedRun, meta: layout.PublishMetadata, spec: layout.FeatureSpec,
    skip_labels_not_in_spec: bool = False,
) -> dict | None:
    """Rewrite the published ``rules.json`` with the scheme metadata (v0.4) and the input labels (v0.5).

    Returns the ``publish.json`` record or None when the metadata has neither block.
    """
    rules, reasons, fields = run.rules, [], []
    # v0.8: the display names of the compound conditions come from the config, whatever the run directory has
    named = compound_terms.apply_labels(rules)
    if named != rules:
        rules = named
        reasons.append("contract v0.8 display names of the compound conditions (configs/compound_terms.json)")
        fields += ["rules[].antecedents[].label", "rules[].antecedents[].label_en"]
    if meta.target_scheme is None and not meta.features and not fields:
        return None
    if meta.target_scheme is not None:
        if rules.target_scheme is None:
            raise ValueError("the metadata has a target_scheme block but the model is not a classifier")
        scheme = apply_scheme_metadata(rules.target_scheme, meta.target_scheme)
        rules = rules.model_copy(update={"target_scheme": scheme})
        reasons.append("contract v0.4 scheme metadata (kind, short_name, merged_from)")
        fields += ["target_scheme.kind", "target_scheme.short_name", "target_scheme.classes[].merged_from",
                   "target_scheme.classes[].description", "target_scheme.classes[].display_label",
                   "target_scheme.classes[].display_label_en", "target_scheme.classes[].description_en",
                   "target_scheme.name_en", "target_scheme.short_name_en"]
    # a label for an input the feature_spec does not have is refused (a typo), unless the caller says that the
    # metadata file is shared by tasks with other inputs (Germany: no2_yday_valid is a +6 h input only); then those
    # labels are skipped and listed in publish.json
    features = ({name: f for name, f in meta.features.items() if name in spec.features}
                if skip_labels_not_in_spec else dict(meta.features))
    skipped = sorted(set(meta.features) - set(features))
    if features:
        rules, _ = enrich.apply_feature_labels(rules, features, spec)
        reasons.append("contract v0.5/v0.5.1/v0.6 input and term labels (LinguisticVariable and LinguisticTerm label, "
                       "Spanish and English)")
        fields += ["variables[].label", "variables[].description", "variables[].terms[].label",
                   "variables[].label_en", "variables[].description_en", "variables[].terms[].label_en"]
    (dest / "rules.json").write_text(rules.model_dump_json(indent=2) + "\n")
    return {
        "reason": "; ".join(reasons) + "; no retraining",
        "run_rules_sha256": artifacts.sha256_file(run.run_dir / "rules.json"),
        "patched_fields": fields,
        **({"labels_not_in_feature_spec": skipped} if skipped else {}),
    }


def _coverage(con: duckdb.DuckDBPyConnection, inputs: Path, irregular: bool = False) -> m.TimeCoverage:
    """First and last issue time and the step: the gcd of the gaps between distinct issue times.

    ``irregular``: the issue times are sample times, not a grid; the step is then 1 hour whatever the gcd is.
    """
    rows = con.execute(
        "SELECT DISTINCT epoch(issued_at_utc)::BIGINT AS s FROM read_parquet(?) ORDER BY s", [str(inputs)]
    ).fetchall()
    seconds = [r[0] for r in rows]
    step = math.gcd(*[b - a for a, b in zip(seconds, seconds[1:], strict=False)]) if len(seconds) > 1 else 3600
    if irregular:
        step = 3600
    elif step % 3600:
        raise ValueError(f"issue times are not on a whole-hour grid (gcd of gaps = {step} s); "
                         "pass irregular_times=True (--irregular-times) if they are sample times")
    first, last = (datetime.fromtimestamp(seconds[i], tz=timezone.utc) for i in (0, -1))
    return m.TimeCoverage(issued_from_utc=first, issued_to_utc=last, step_hours=step // 3600, regular=not irregular)


def publish_run(
    run_dir: Path,
    features: str | Path,
    entities_path: Path,
    feature_spec_path: Path,
    period_from: datetime | str,
    period_to: datetime | str,
    *,
    published_dir: Path = PUBLISHED_DIR,
    task_id: str | None = None,
    synthetic: bool = False,
    title: str | None = None,
    replace: bool = False,
    chunk_size: int = 50_000,
    memory_limit: str = "1GB",
    observed_label_column: str | None = None,
    irregular_times: bool = False,
    metadata_path: Path | None = None,
    include_unmodelled_entities: bool = False,
    activation_row_group_size: int = ACTIVATION_ROW_GROUP_SIZE,
    territory: str | None = None,
    territory_title: str | None = None,
    territory_title_en: str | None = None,
    skip_labels_not_in_spec: bool = False,
) -> PublishSummary:
    """Write ``<published_dir>/<model_id>/`` for the issue times in ``[period_from, period_to)`` and register it.

    ``synthetic`` is OR-ed with the run's own flag: a run trained on synthetic data cannot be published as real.
    Raises before touching ``published_dir`` if the run's checksums fail, an input entity has no entity record,
    or a feature has no ``feature_spec`` entry. ``observed_label_column`` (classifiers only) names the table column
    that holds the observed class label and ``irregular_times`` marks issue times that are
    sample times. ``metadata_path`` and ``include_unmodelled_entities`` are the contract v0.4 options (see the
    module docstring). ``activation_row_group_size`` is the row group size of the activations files (see
    ``ACTIVATION_SORT``). Contract v0.5: ``territory`` / ``territory_title`` go to the registry (tasks that differ
    only in horizon share one; a republish without them keeps those of the task's previous entry), and
    ``importance.json`` and ``summary.json`` are computed from the published files and the feature table
    (``atlas.services.enrich``). Contract v0.6: ``territory_title_en`` is the English name of the territory (kept
    from the previous entry with the rest of the territory when ``territory`` is omitted).
    """
    started = time.perf_counter()
    run_dir, published_dir = Path(run_dir), Path(published_dir)
    start, end = _utc(period_from), _utc(period_to)
    if end <= start:
        raise ValueError("--to must be after --from")
    artifacts.verify_checksums(run_dir)  # refuse a tampered run before unpickling anything
    run = load_run(run_dir)
    manifest, config = run.manifest, run.config
    if task_id is not None and task_id != manifest.task_id:
        raise ValueError(f"task_id {task_id!r} does not match the run's task {manifest.task_id!r}")
    synthetic = synthetic or config.synthetic
    spec = layout.FeatureSpec.model_validate_json(Path(feature_spec_path).read_text())
    absent = [f for f in manifest.features if f not in spec.features]
    if absent:
        raise ValueError(f"feature_spec has no entry for model features: {absent}")
    entities = _load_entities(entities_path, manifest.domain)
    metadata = (layout.PublishMetadata.model_validate_json(Path(metadata_path).read_text())
                if metadata_path is not None else layout.PublishMetadata())
    if metadata.target_scheme is not None and task_type_of(run) != "classification":
        raise ValueError("the metadata has a target_scheme block but the model is not a classifier")
    if observed_label_column is not None and task_type_of(run) != "classification":
        raise ValueError("observed_label_column only applies to classifier runs")
    for name, value in (("territory_title", territory_title), ("territory_title_en", territory_title_en)):
        if value is not None and territory is None:
            raise ValueError(f"{name} needs a territory")

    model_id = manifest.model_id
    final = published_dir / model_id
    if final.exists() and not replace:
        raise FileExistsError(f"{final} already exists (use --replace to publish it again)")
    published_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".tmp-{model_id}-", dir=published_dir))
    scratch = Path(tempfile.mkdtemp(prefix=f".tmp-sort-{model_id}-", dir=published_dir))  # firing chunks, sort spill
    con = duckdb.connect(config={"memory_limit": memory_limit, "threads": 2})
    try:
        con.execute("SET TimeZone='UTC'")
        con.execute(f"SET temp_directory = '{_sql_path(scratch / 'spill')}'")
        _copy_run_files(run_dir, tmp)
        patch = _patch_published_rules(tmp, run, metadata, spec, skip_labels_not_in_spec)
        if patch is not None:
            run = dataclass_replace(run, rules=m.ModelRules.model_validate_json((tmp / "rules.json").read_text()))
        counts = _write_views(
            con, run, _resolve_features(features), entities, synthetic, start, end, tmp, chunk_size,
            observed_label_column, metadata.attribution, include_unmodelled_entities, scratch,
            activation_row_group_size,
        )
        coverage = _coverage(con, tmp / layout.INPUTS_FILE, irregular_times)
        _write_documents(
            tmp, run, entities, spec, coverage, counts, synthetic, str(features), start, end, irregular_times,
            metadata.attribution, patch,
        )
        fallback = enrich.regression_fallback(run.model, run.rules) if task_type_of(run) == "regression" else None
        record = enrich.write_importance_and_summary(
            tmp, con, source=_resolve_features(features), metadata=metadata, fallback=fallback)
        info_path = tmp / layout.PUBLISH_INFO_FILE
        info = json.loads(info_path.read_text())
        info["v05"] = record
        info_path.write_text(json.dumps(info, indent=2) + "\n")
        layout.write_checksums(tmp)
        verify.verify_model_dir(tmp)  # what is about to become visible matches its SHA256SUMS, file by file
        old = None
        if final.exists():
            old = published_dir / f".old-{model_id}-{os.getpid()}"
            os.rename(final, old)
        os.rename(tmp, final)
        registry = layout.read_registry(published_dir)
        registry.schema_version = m.SCHEMA_VERSION  # entries below follow the current contract (task_type)
        previous = registry.tasks.get(manifest.task_id)
        if territory is None and previous is not None:
            territory, territory_title = previous.territory, previous.territory_title
            territory_title_en = previous.territory_title_en
        registry.tasks[manifest.task_id] = layout.RegistryEntry(
            model_id=model_id, domain=manifest.domain, title=title or layout.DOMAIN_TITLES[manifest.domain],
            task_type=task_type_of(run), target=manifest.target, unit=config.unit, horizon_hours=manifest.horizon_hours,
            data_version=manifest.data_version, synthetic=synthetic, territory=territory,
            territory_title=territory_title, territory_title_en=territory_title_en,
        )
        layout.write_registry(published_dir, registry)
        if old is not None:
            shutil.rmtree(old, ignore_errors=True)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    finally:
        con.close()
        shutil.rmtree(scratch, ignore_errors=True)
    return PublishSummary(
        final, counts["inputs"], counts["activations"], len(counts["entities"]), coverage,
        time.perf_counter() - started,
    )


def _write_views(
    con, run: LoadedRun, source: str, entities, synthetic: bool, start, end, dest: Path, chunk_size: int,
    observed_label_column: str | None = None, attribution: list[m.Attribution] | None = None,
    include_unmodelled: bool = False, scratch: Path | None = None, row_group_size: int = ACTIVATION_ROW_GROUP_SIZE,
) -> dict:
    """Inputs, predictions and firing table, month by month. Returns row counts and the published entity ids.

    The firing table of a month is produced in chunks (bounded memory) into ``scratch`` and then sorted into the single
    file ``activations/year=Y/month=MM/part-000000.parquet`` (``_write_sorted_activations``).
    """
    config = run.config
    features = config.features
    schema = con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [source]).fetchall()
    types = {row[0]: row[1] for row in schema}
    need = ["entity_id", "issued_at_utc", *features]
    if absent := [c for c in need if c not in types]:
        raise KeyError(f"feature table is missing columns: {absent}")
    if not types["issued_at_utc"].startswith(("TIMESTAMP WITH TIME ZONE", "TIMESTAMPTZ")):
        raise ValueError(f"issued_at_utc must be timezone-aware UTC (TIMESTAMPTZ), found {types['issued_at_utc']}")
    has_target = config.target_column in types
    if observed_label_column is not None and observed_label_column not in types:
        raise KeyError(f"feature table is missing the observed label column: {observed_label_column}")
    extra = [observed_label_column] if observed_label_column else []
    columns = ", ".join(_quote(c) for c in [*need, *([config.target_column] if has_target else []), *extra])
    # the cast makes microsecond and nanosecond timestamp columns comparable with the period bounds
    table = "(SELECT * REPLACE (CAST(issued_at_utc AS TIMESTAMPTZ) AS issued_at_utc) FROM read_parquet(?))"
    query = (
        f"SELECT {columns} FROM {table} WHERE issued_at_utc >= ? AND issued_at_utc < ? "
        "ORDER BY issued_at_utc, entity_id"
    )

    ids = {r[0] for r in con.execute(
        f"SELECT DISTINCT entity_id FROM {table} WHERE issued_at_utc >= ? AND issued_at_utc < ?",
        [source, start, end],
    ).fetchall()}
    if not ids:
        raise ValueError(f"the feature table has no rows in [{start.isoformat()}, {end.isoformat()})")
    known = {f.properties.entity_id for f in entities.features}
    if unknown := sorted(ids - known):
        raise ValueError(f"input entities without an entity record (geometry): {unknown}")
    # An entity whose record has no geometry could be listed but never drawn, and no view may carry one (AT-062):
    # its rows are left out and publish.json lists it.
    undrawable = sorted(f.properties.entity_id for f in entities.features
                        if f.geometry is None and f.properties.entity_id in ids)
    ids -= set(undrawable)
    if not ids:
        raise ValueError("no entity of the feature table has a geometry")
    def flagged(feature: m.EntityFeature) -> m.EntityFeature:
        modelled = feature.properties.entity_id in ids
        return feature.model_copy(update={"properties": feature.properties.model_copy(update={"modelled": modelled})})

    kept = m.EntityCollection(
        data_version=entities.data_version, synthetic=synthetic or entities.synthetic, type="FeatureCollection",
        domain=entities.domain, attribution=attribution or entities.attribution,
        features=[
            flagged(f) for f in entities.features
            # an unmodelled entity is only worth publishing if it can be drawn: no geometry, no "sin modelo" polygon
            if f.properties.entity_id in ids or (include_unmodelled and f.geometry is not None)
        ],
    )
    (dest / layout.ENTITIES_FILE).write_text(kept.model_dump_json(indent=2) + "\n")

    input_schema = pa.schema([*INPUT_ID_SCHEMA, *[(f, pa.float64()) for f in features]])
    horizon = timedelta(hours=config.horizon_hours)
    counts = {"inputs": 0, "activations": 0, "entities": ids, "without_geometry": undrawable}
    classifier = task_type_of(run) == "classification"
    scheme = run.rules.target_scheme
    if classifier:
        if scheme is None:
            raise ValueError("a classifier run needs a target_scheme in its rules.json")
        if list(run.model.class_labels) != [c.label for c in scheme.classes]:
            raise ValueError("the model's class labels differ from the target_scheme of its rules.json")
    mixture = is_mixture_run(run)
    prediction_schema = MIXTURE_PREDICTION_SCHEMA if mixture else CLASS_PREDICTION_SCHEMA if classifier \
        else PREDICTION_SCHEMA
    activation_schema = MIXTURE_ACTIVATION_SCHEMA if mixture else CLASS_ACTIVATION_SCHEMA if classifier \
        else ACTIVATION_SCHEMA
    with (
        pq.ParquetWriter(dest / layout.INPUTS_FILE, input_schema, compression="zstd") as inputs_out,
        pq.ParquetWriter(dest / layout.PREDICTIONS_FILE, prediction_schema, compression="zstd") as pred_out,
    ):
        for year, month, lo, hi in _months(start, end):
            frame = con.execute(query, [source, lo, hi]).df()
            if undrawable:
                frame = frame[~frame["entity_id"].isin(undrawable)].reset_index(drop=True)
            if frame.empty:
                continue
            frame["issued_at_utc"] = pd.DatetimeIndex(frame["issued_at_utc"]).tz_convert("UTC")
            if frame.duplicated(["entity_id", "issued_at_utc"]).any():
                raise ValueError(f"duplicate (entity_id, issued_at_utc) rows in {year}-{month:02d}")
            inputs_out.write_table(_table(frame, input_schema))
            observed = frame[config.target_column] if has_target else float("nan")
            if classifier:
                predictions = _class_predictions(
                    run.model, frame, features, observed, scheme, horizon,
                    frame[observed_label_column] if observed_label_column else None, mixture=mixture,
                    rule_ids=[r.rule_id for r in run.rules.rules], chunk_size=chunk_size)
            else:
                prediction = run.model.predict(frame[features])
                predictions = pd.DataFrame({
                    "entity_id": frame["entity_id"], "issued_at_utc": frame["issued_at_utc"],
                    "valid_at_utc": frame["issued_at_utc"] + horizon, "prediction": prediction,
                    "observed": observed,
                    "missing_reason": [None if math.isfinite(p) else m.MissingReason.MISSING_INPUT.value
                                       for p in prediction],
                })
            pred_out.write_table(_table(predictions, prediction_schema))
            part_dir = dest / layout.ACTIVATIONS_DIR / f"year={year}" / f"month={month:02d}"
            part_dir.mkdir(parents=True, exist_ok=True)
            chunk_dir = Path(tempfile.mkdtemp(prefix=f"firing-{year}-{month:02d}-", dir=scratch))
            make_firing = (iter_mixture_firing_tables if mixture else iter_classifier_firing_tables if classifier
                           else iter_firing_tables)
            firing = make_firing(
                run.model, frame[features], frame["entity_id"].tolist(), frame["issued_at_utc"], chunk_size=chunk_size,
            )
            chunks = []
            for part, chunk in enumerate(firing):
                chunks.append(chunk_dir / f"chunk-{part:06d}.parquet")
                pq.write_table(_table(chunk, activation_schema), chunks[-1], compression="zstd")
                counts["activations"] += len(chunk)
            _write_sorted_activations(con, chunks, part_dir / "part-000000.parquet", activation_schema, row_group_size)
            shutil.rmtree(chunk_dir)
            counts["inputs"] += len(frame)
    return counts


def _class_predictions(model, frame, features, observed, scheme: m.TargetScheme, horizon, observed_label=None, *,
                       mixture: bool = False, rule_ids: list[str] | None = None,
                       chunk_size: int = 100_000) -> pd.DataFrame:
    """Predicted and observed class labels. ``prediction`` stays null: a class index is not a number to publish.

    Without a label the reason is ``prediction_unavailable`` (inputs present, no rule fired) or ``missing_input``.
    ``observed_label`` (one value per row, ``None``/NaN allowed) replaces the classification of ``observed`` by the
    scheme bounds. Where it is null but ``observed`` is a number, the row has no reference level: the prediction is
    withheld (null label, ``prediction_unavailable``), so that it can never be drawn as a class.

    ``mixture`` (v0.7) adds ``top_rule_id`` / ``top_rule_share`` (``atlas.explain.mixture``, ``chunk_size`` rows at a
    time), null where the label is.
    """
    labels = model.predict_labels(frame[features])
    allowed = {c.label for c in scheme.classes}
    if unknown := {label for label in labels if label is not None} - allowed:
        raise ValueError(f"the classifier predicted labels outside the target_scheme: {sorted(unknown)}")
    finite = np.isfinite(frame[features].to_numpy(dtype=float)).all(axis=1)
    observed = np.broadcast_to(np.asarray(observed, dtype=float), (len(frame),))
    withheld = np.zeros(len(frame), dtype=bool)
    if observed_label is None:
        observed_labels = classify_observed(scheme, observed)
    else:
        observed_labels = [None if pd.isna(v) else str(v) for v in observed_label]
        if unknown := {v for v in observed_labels if v is not None} - allowed:
            raise ValueError(f"observed labels outside the target_scheme: {sorted(unknown)}")
        withheld = np.array([v is None for v in observed_labels]) & np.isfinite(observed)
        labels = np.where(withheld, None, labels)
    absent = {True: m.MissingReason.PREDICTION_UNAVAILABLE.value, False: m.MissingReason.MISSING_INPUT.value}
    reason = [None if label is not None else absent[bool(ok)] for label, ok in zip(labels, finite, strict=True)]
    out = pd.DataFrame({
        "entity_id": frame["entity_id"], "issued_at_utc": frame["issued_at_utc"],
        "valid_at_utc": frame["issued_at_utc"] + horizon, "prediction": np.full(len(frame), np.nan),
        "observed": observed, "observed_label": observed_labels,
        "prediction_label": labels, "missing_reason": reason,
    })
    if mixture:
        top, share = mixture_top_rules(model, frame[features], chunk_size=chunk_size)
        keep = (top >= 0) & np.array([label is not None for label in labels])
        names = np.array([*rule_ids, None], dtype=object)
        out["top_rule_id"] = names[np.where(keep, top, len(rule_ids))]
        out["top_rule_share"] = np.where(keep, share, np.nan)
    return out


def _write_documents(dest, run: LoadedRun, entities, spec, coverage, counts, synthetic, source, start, end,
                     irregular: bool = False, attribution: list[m.Attribution] | None = None,
                     rules_patch: dict | None = None) -> None:
    manifest, split = run.manifest, run.manifest.split
    warnings = list(manifest.warnings)
    periods = [(split.train_from_utc, split.train_to_utc), (split.validation_from_utc, split.validation_to_utc)]
    if any(a is not None and start < b and a < end for a, b in periods):
        warnings.append("published period overlaps the training/validation period: predictions there are in-sample")
    if irregular:
        warnings.append("issue times are irregular sample times, not a regular grid (coverage.step_hours = 1 is only "
                        "the finest step the contract expresses): use window aggregates for maps, not instants")
    if synthetic and "synthetic data" not in warnings:
        warnings.append("synthetic data")
    card = m.ModelCard(
        data_version=manifest.data_version, synthetic=synthetic,
        manifest=manifest.model_copy(update={"warnings": warnings}), metrics=run.metrics, coverage=coverage,
        target_scheme=run.rules.target_scheme if task_type_of(run) == "classification" else None,
        attribution=attribution or [],
    )
    (dest / layout.CARD_FILE).write_text(card.model_dump_json(indent=2) + "\n")
    (dest / layout.FEATURE_SPEC_FILE).write_text(spec.model_dump_json(indent=2) + "\n")
    info = {
        "published_at_utc": datetime.now(timezone.utc).isoformat(),
        "period_from_utc": start.isoformat(), "period_to_utc": end.isoformat(),
        "feature_table": source, "run_id": manifest.run_id,
        "n_input_rows": counts["inputs"], "n_activation_records": counts["activations"],
        "entities": sorted(counts["entities"]),
        "entities_left_out_without_geometry": counts["without_geometry"],
        "rules_json_patch": rules_patch,
    }
    (dest / layout.PUBLISH_INFO_FILE).write_text(json.dumps(info, indent=2) + "\n")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m atlas.services.publish", description=__doc__.split("\n\n")[0])
    parser.add_argument("--run-dir", type=Path, required=True, help="artifacts/<task_id>/<run_id>")
    parser.add_argument("--features", required=True, help="feature table: Parquet file, glob or directory")
    parser.add_argument("--entities", type=Path, required=True, help="EntityCollection JSON for the entities")
    parser.add_argument("--feature-spec", type=Path, required=True, help="per feature: unit, source_id, lag_hours")
    parser.add_argument("--from", dest="period_from", required=True, help="first issue time (inclusive), UTC")
    parser.add_argument("--to", dest="period_to", required=True, help="end of the period (exclusive), UTC")
    parser.add_argument("--task-id", help="guard: must match the run's task (default: the run's task)")
    parser.add_argument("--published-dir", type=Path, default=PUBLISHED_DIR)
    parser.add_argument("--title", help="display title of the domain (default: generic)")
    parser.add_argument("--synthetic", action="store_true", help="label every payload as synthetic")
    parser.add_argument("--replace", action="store_true", help="overwrite an already published model_id")
    parser.add_argument("--chunk-size", type=int, default=50_000, help="input rows per firing-table chunk")
    parser.add_argument("--memory-limit", default="1GB", help="DuckDB memory_limit (the monthly sort of the firing "
                        "table spills to disk beyond it); lower it on a machine with little free memory")
    parser.add_argument("--irregular-times", action="store_true",
                        help="issue times are sample times, not an hourly grid (coverage step 1 h plus a card warning)")
    parser.add_argument("--metadata", type=Path, help="v0.4: PublishMetadata JSON (configs/<domain>/attribution.json): "
                        "source attribution and scheme kind / merged classes")
    parser.add_argument("--include-unmodelled-entities", action="store_true",
                        help="v0.4: also publish the entities of --entities that have no data, with modelled=false")
    parser.add_argument("--observed-label-column", help="classifiers: table column with the observed class label "
                        "(instead of applying the scheme bounds to the numeric target)")
    parser.add_argument("--territory", help="v0.5: territory id shared by the tasks that differ only in horizon "
                        "(e.g. madrid); kept from the task's previous registry entry when omitted")
    parser.add_argument("--territory-title", help="v0.5: display name of the territory (e.g. Madrid)")
    parser.add_argument("--territory-title-en", help="v0.6: English display name of the territory (e.g. Germany)")
    parser.add_argument("--skip-labels-not-in-spec", action="store_true",
                        help="v0.7: the --metadata file is shared by tasks with other inputs: skip (and list in "
                        "publish.json) the labels of inputs this model's feature_spec lacks, instead of refusing")
    args = parser.parse_args(argv)
    summary = publish_run(
        args.run_dir, args.features, args.entities, args.feature_spec, args.period_from, args.period_to,
        published_dir=args.published_dir, task_id=args.task_id, synthetic=args.synthetic, title=args.title,
        replace=args.replace, chunk_size=args.chunk_size, memory_limit=args.memory_limit,
        observed_label_column=args.observed_label_column, irregular_times=args.irregular_times,
        metadata_path=args.metadata, include_unmodelled_entities=args.include_unmodelled_entities,
        territory=args.territory, territory_title=args.territory_title, territory_title_en=args.territory_title_en,
        skip_labels_not_in_spec=args.skip_labels_not_in_spec,
    )
    print(json.dumps({
        "model_dir": str(summary.model_dir), "input_rows": summary.n_input_rows,
        "activation_records": summary.n_activation_records, "entities": summary.n_entities,
        "coverage": summary.coverage.model_dump(mode="json"), "seconds": round(summary.seconds, 2),
    }, indent=2))


if __name__ == "__main__":
    main()
