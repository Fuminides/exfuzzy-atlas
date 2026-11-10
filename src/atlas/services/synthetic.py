"""A tiny synthetic run, published: for the tests and to try ``ATLAS_API_MODE=artifacts`` without real data.

    PYTHONPATH=src python -m atlas.services.synthetic --out artifacts/published-demo
    ATLAS_API_MODE=artifacts ATLAS_PUBLISHED_DIR=artifacts/published-demo make api

``--task classification`` trains and publishes a tiny winning-rule classifier over three invented bands instead of the
regressor (task ``synthetic_class_h6``); the default regression demo is unchanged. ``--task mixture`` (contract v0.7)
trains the same tiny classifier with the mixture-of-rules inference (non-negative weights, rules searched under the
mixture; task ``synthetic_mixture_h6``); it needs an ex_fuzzy with ``inference='mixture'``.

``--v04`` also exercises the contract v0.4 metadata: an extra entity ``E9`` that is in the geometry file but has no
data (``modelled = false``), a two-credit attribution and, for the classifier, a scheme kind and a merged class; and
the v0.5 ones: input labels, a summary label and a territory. Every model also gets ``importance.json`` and
``summary.json`` from the publish.

Everything is invented (``atlas.ml.synthetic``) and labelled synthetic in every payload.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from atlas.contracts import models as m
from atlas.ml import artifacts
from atlas.ml.classification import ClassScheme, classification_metric_rows
from atlas.ml.fuzzy import FuzzyParams, FuzzyRegressor
from atlas.ml.fuzzy_classifier import FuzzyClassifier, FuzzyClassifierParams
from atlas.ml.pipeline import LoadedRun, RunConfig, load_run, train_run
from atlas.ml.rules_export import export_classifier_rules
from atlas.ml.split import chronological_split_spec, split_masks
from atlas.ml.synthetic import FEATURE_UNITS, FEATURES, TARGET, make_synthetic_table
from atlas.services import layout
from atlas.services.publish import PublishSummary, publish_run

HORIZON_HOURS = 6
COORDINATES = {"E0": (-3.703, 40.417), "E1": (-3.688, 40.452), "E2": (-3.712, 40.381)}
UNMODELLED = {"E9": (-3.650, 40.400)}  # --v04: in the geometry file, no data
TERMS = {"Low": "baja (inventada)", "Medium": "media (inventada)", "High": "alta (inventada)"}  # contract v0.5.1
TERMS_EN = {"Low": "low (made up)", "Medium": "medium (made up)", "High": "high (made up)"}  # contract v0.6
V04_METADATA = layout.PublishMetadata(
    attribution=[
        m.Attribution(text="Synthetic data: invented, not a real source."),
        m.Attribution(text="Second invented credit", license="CC BY 4.0", url="https://example.org/credit"),
    ],
    features={  # contract v0.5; the lag_hours are those of LAGS below
        "y_t": layout.FeatureMetadata(
            label="Serie y en la emisión (inventada)", lag_hours=0,
            description="Valor inventado de la serie y a la hora de emisión; no es una fuente real.", terms=TERMS,
            label_en="Series y at the issue time (made up)",
            description_en="Made-up value of series y at the issue time; not a real source.", terms_en=TERMS_EN),
        "y_lag3": layout.FeatureMetadata(
            label="Serie y hace 3 h (inventada)", lag_hours=3,
            description="Valor inventado de la serie y 3 h antes de la hora de emisión; no es una fuente real.",
            terms=TERMS, label_en="Series y 3 h ago (made up)",
            description_en="Made-up value of series y 3 h before the issue time; not a real source.",
            terms_en=TERMS_EN),
        "exo_t": layout.FeatureMetadata(
            label="Viento hace 1 h (m/s, inventado)", lag_hours=1,
            description="Variable exógena inventada (m/s) de la hora anterior a la emisión; no es una fuente real.",
            terms=TERMS, label_en="Wind 1 h ago (m/s, made up)",
            description_en="Made-up exogenous variable (m/s) of the hour before the issue time; not a real source.",
            terms_en=TERMS_EN),
        "hour": layout.FeatureMetadata(
            label="Hora de emisión (inventada)", lag_hours=0,
            description="Hora del día de la emisión (0-23), calendario conocido de antemano.", terms=TERMS,
            label_en="Issue hour (made up)",
            description_en="Hour of the day of the issue time (0-23), calendar known in advance.", terms_en=TERMS_EN),
    },
    summary=layout.SummaryMetadata(label="Serie y observada (inventada)", label_en="Observed series y (made up)"),
)
V04_TERRITORY = ("synthetic", "Sintético (inventado)", "Synthetic (made up)")
V04_SCHEME_METADATA = layout.SchemeMetadata(
    kind=m.SchemeKind.ANALYTICAL, short_name="synthetic", name_en="Synthetic bands (made up, not an official index)",
    short_name_en="synthetic",
    classes={  # display_label: contract v0.5.1; *_en: v0.6
        "low": layout.ClassMetadata(display_label="baja (inventada)", display_label_en="low (made up)"),
        "mid": layout.ClassMetadata(display_label="media (inventada)", display_label_en="medium (made up)"),
        "high": layout.ClassMetadata(
            merged_from=["very high (invented)", "extreme (invented)"],
            description="invented: groups two invented bands", display_label="alta (inventada)",
            display_label_en="high (made up)", description_en="made up: groups two made-up bands"),
    },
)
LAGS = {"y_t": 0, "y_lag3": 3, "exo_t": 1, "hour": 0}
TASKS = ("regression", "classification", "mixture")
TASK_IDS = {"regression": "synthetic_y_h6", "classification": "synthetic_class_h6", "mixture": "synthetic_mixture_h6"}
# three invented bands over the synthetic target (never a real index); bounds are whole numbers, both inclusive
SCHEME = ClassScheme.model_validate({
    "name": "Synthetic bands (invented, not an official index)", "source_url": "https://example.org/synthetic",
    "unit": "u", "classes": [
        {"label": "low", "lower": -1000, "upper": 34, "color": "#00FFFF", "description": "invented"},
        {"label": "mid", "lower": 35, "upper": 50, "color": "#FFCC00", "description": "invented"},
        {"label": "high", "lower": 51, "upper": 1000, "color": "#FF3300", "description": "invented"},
    ],
})


@dataclass
class SyntheticPublished:
    root: Path
    published_dir: Path
    model_dir: Path
    table: pd.DataFrame
    run: LoadedRun
    summary: PublishSummary


# Contract v0.8 (``build_synthetic(..., ordinal=True)``): the fitted rules are rewritten so that every kind of condition
# appears: ``at least``, ``at most``, a compound of adjacent terms and a compound that wraps (the first and last term).
ORDINAL_INPUTS = ("y_t", "exo_t")
ORDINAL_COMPOUNDS = {"hour": [("Test stretch", ["Low", "Medium"]), ("Test ends", ["Low", "High"])]}


def force_ordinal_rules(rulebase, rules) -> None:
    """Rewrite the first rules of a fitted rule base: R01 ``y_t at least Medium AND hour Test stretch``, R02 ``exo_t at
    most Medium``, R03 ``y_t at most Medium AND hour Test ends``; the others stay as the search left them."""
    from atlas.ml import exfuzzy_features as xf
    from atlas.ml.synthetic import FEATURES

    by = {str(v.name): v for v in rulebase.antecedents}

    def code(feature: str, text: str) -> int:
        return xf.condition_labels(by[feature]).index(text)

    wanted = [{"y_t": "at least Medium", "hour": "Test stretch"}, {"exo_t": "at most Medium"},
              {"y_t": "at most Medium", "hour": "Test ends"}]
    for rule, conditions in zip(rules, wanted, strict=False):
        for f in range(len(FEATURES)):
            rule.antecedents[f] = -1
        for feature, text in conditions.items():
            rule.antecedents[FEATURES.index(feature)] = code(feature, text)


def _train_classifier_run(table: pd.DataFrame, config: RunConfig, artifacts_dir: Path, mixture: bool = False,
                          ordinal: bool = False) -> Path:
    """Fit a tiny ``FuzzyClassifier`` on the training rows and write a run directory (what A4's runs contain).

    ``mixture``: the mixture-of-rules inference (v0.7), non-negative weights, rules searched under the mixture."""
    labels = SCHEME.labels
    issued = pd.DatetimeIndex(table["issued_at_utc"])
    masks = split_masks(issued, config.split)
    complete = np.isfinite(table[[*config.features, config.target_column]].to_numpy(dtype=float)).all(axis=1)
    train, test = table[masks["train"] & complete], table[masks["test"] & complete]
    y_train, y_test = SCHEME.classify(train[config.target_column]), SCHEME.classify(test[config.target_column])
    extra = dict(inference="mixture", mixture_non_negative=True, mixture_search=True) if mixture else {}
    if ordinal:
        extra |= dict(ordinal_conditions=ORDINAL_INPUTS, compound_terms=ORDINAL_COMPOUNDS)
    params = FuzzyClassifierParams(nRules=9, nAnts=2, n_gen=8, pop_size=16, patience=None, **extra)
    model = FuzzyClassifier(params, config.feature_units).fit(train[config.features], y_train, labels, config.seed)
    if ordinal:
        from atlas.explain.classifier import get_master_rulebase

        rb = get_master_rulebase(model)
        force_ordinal_rules(rb, rb.get_rules())
        if mixture:  # the fitted weights stay with their positions; only the check that they belong to the rules moves
            from ex_fuzzy import rule_mixture

            model.estimator.mixture_.rule_keys_ = rule_mixture.rule_keys(model.estimator.rule_base)
    run_id = f"synthetic-{'mixture' if mixture else 'class'}{'-ordinal' if ordinal else ''}-seed{config.seed}"
    model_id = f"exfuzzy-{config.task_id}-{run_id}"
    created = datetime.now(timezone.utc)
    commit, dirty = artifacts.git_state()
    rules = export_classifier_rules(
        model, model_id=model_id, task_id=config.task_id, domain=config.domain, target_label="Y",
        target_scheme=SCHEME.to_target_scheme(), horizon_hours=config.horizon_hours, data_version=config.data_version,
        synthetic=True, feature_units=config.feature_units, X_reference=train[config.features],
    )
    metrics = m.MetricsReport(
        model_id=model_id, task_id=config.task_id, split=config.split,
        rows=classification_metric_rows("exfuzzy", y_test, model.predict(test[config.features]), labels),
    )
    manifest = m.RunManifest(
        run_id=run_id, model_id=model_id, task_id=config.task_id, domain=config.domain, created_at_utc=created,
        git_commit=commit, git_dirty=dirty, exfuzzy_version=rules.inference.exfuzzy_version,
        python_version=artifacts.python_version(), seed=config.seed, split=config.split,
        data_version=config.data_version, data_checksums={}, target=config.target, horizon_hours=config.horizon_hours,
        features=config.features,
        hyperparameters={
            **params.as_dict(), "task_type": "classification", "class_labels": labels, "n_train_rows": len(train),
            "fit_info": model.fit_info,
            "run_config": config.model_copy(update={"run_id": run_id}).model_dump(mode="json"),
        },
        artifacts={"model": artifacts.MODEL_FILE, "metrics": "metrics.json", "rules": "rules.json",
                   "checksums": artifacts.CHECKSUM_FILE},
        warnings=["synthetic data"],
    )
    return artifacts.write_run_dir(
        artifacts_dir / config.task_id / run_id, model=model, parity_sample=test[config.features].head(200),
        json_files={"run_manifest.json": manifest.model_dump_json(indent=2) + "\n",
                    "metrics.json": metrics.model_dump_json(indent=2) + "\n",
                    "rules.json": rules.model_dump_json(indent=2) + "\n"},
        parquet_files={},
    )


@contextmanager
def _ordinal_regressor(on: bool):
    """With ``on``, every regressor fitted inside the block has its first rules rewritten by ``force_ordinal_rules``."""
    if not on:
        yield
        return
    original = FuzzyRegressor.fit

    def fit(self, X, y, seed):
        out = original(self, X, y, seed)
        rb = self.get_rulebase()
        force_ordinal_rules(rb, rb.rules)
        return out

    FuzzyRegressor.fit = fit
    try:
        yield
    finally:
        FuzzyRegressor.fit = original


def build_synthetic(
    root: Path, *, n_hours: int = 24 * 45, exo_missing_fraction: float = 0.03, task: str = "regression",
    v04: bool = False, ordinal: bool = False,
) -> SyntheticPublished:
    """Train a small model on a synthetic table (3 entities, from 2024-01-01) and publish most of it under ``root``.

    ``task`` is ``regression`` (the default demo), ``classification`` (a tiny winning-rule classifier over the
    invented bands of ``SCHEME``) or ``mixture`` (the same classifier with the mixture of rules, v0.7). ``v04`` adds
    the unmodelled entity ``E9`` and the v0.4 metadata (see the module docstring). ``ordinal`` (contract v0.8, needs
    ex-fuzzy 3.5.0) makes the first rules use ``at least`` / ``at most`` conditions and compound terms.
    """
    if task not in TASKS:
        raise ValueError(f"task must be one of {TASKS}, got {task!r}")
    classifier = task in ("classification", "mixture")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    options_ordinal = dict(ordinal_conditions=ORDINAL_INPUTS, compound_terms=ORDINAL_COMPOUNDS) if ordinal else {}
    table = make_synthetic_table(n_entities=3, n_hours=n_hours, seed=1, exo_missing_fraction=exo_missing_fraction)
    table.to_parquet(root / "features.parquet", index=False)
    config = RunConfig(
        task_id=TASK_IDS[task], domain=m.Domain.AIR, target="y",
        target_column=TARGET, unit="u",
        horizon_hours=HORIZON_HOURS, features=FEATURES, feature_units=FEATURE_UNITS, persistence_feature="y_t",
        split=chronological_split_spec(table["issued_at_utc"], horizon_hours=HORIZON_HOURS), seed=3,
        data_version="synthetic-test", synthetic=True, gbm_max_iter=20,
        fuzzy=FuzzyParams(nRules=8, nAnts=3, n_gen=8, pop_size=16, **options_ordinal),
    )
    if classifier:
        run_dir = _train_classifier_run(table, config, root / "runs", mixture=task == "mixture", ordinal=ordinal)
    else:
        with _ordinal_regressor(ordinal):
            run_dir = train_run(table, config, artifacts_dir=root / "runs").run_dir
    entities = m.EntityCollection(
        data_version="synthetic-entities", synthetic=True, type="FeatureCollection", domain=m.Domain.AIR,
        features=[
            m.EntityFeature(
                type="Feature", id=eid, geometry=m.PointGeometry(type="Point", coordinates=xy),
                properties=m.EntityProperties(
                    entity_id=eid, domain=m.Domain.AIR, name=f"Synthetic station {eid} (not real)",
                    geometry_support=m.GeometrySupport.OBSERVED_POINT, geometry_source="synthetic",
                    timezone="Europe/Madrid",
                ),
            )
            for eid, xy in {**COORDINATES, **(UNMODELLED if v04 else {})}.items()
        ],
    )
    (root / "entities.geojson").write_text(entities.model_dump_json(indent=2))
    spec = layout.FeatureSpec(features={
        f: layout.FeatureSource(unit=FEATURE_UNITS[f], source_id=f"synthetic-{f}", lag_hours=LAGS[f])
        for f in FEATURES
    })
    (root / "feature_spec.json").write_text(spec.model_dump_json(indent=2))
    last = table["issued_at_utc"].max()
    options = {}
    if v04:
        metadata = V04_METADATA.model_copy(update={"target_scheme": V04_SCHEME_METADATA if classifier else None})
        (root / "metadata.json").write_text(metadata.model_dump_json(indent=2))
        options = {"metadata_path": root / "metadata.json", "include_unmodelled_entities": True,
                   "territory": V04_TERRITORY[0], "territory_title": V04_TERRITORY[1],
                   "territory_title_en": V04_TERRITORY[2]}
    summary = publish_run(
        run_dir, root / "features.parquet", root / "entities.geojson", root / "feature_spec.json",
        table["issued_at_utc"].min() + pd.Timedelta(days=4), last, published_dir=root / "published", synthetic=True,
        **options,
    )
    return SyntheticPublished(root, root / "published", summary.model_dir, table, load_run(run_dir), summary)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m atlas.services.synthetic", description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True, help="directory to create; the models go in <out>/published")
    parser.add_argument("--task", choices=TASKS, default="regression", help="regressor (default) or classifier demo")
    parser.add_argument("--v04", action="store_true", help="add an unmodelled entity and the v0.4 metadata")
    args = parser.parse_args(argv)
    built = build_synthetic(args.out, task=args.task, v04=args.v04)
    print(f"published {built.model_dir} ({built.summary.n_input_rows} input rows)")


if __name__ == "__main__":
    main()
