"""Publish the fNIRS n-back model (contract v0.9): rules, montage, card, trials and one trace per trial.

::

    PYTHONPATH=src python -m atlas.domains.fnirs.publish \\
        --run artifacts/fnirs_nback/mixture-r20-a2-ordinal-seed0 [--published artifacts/published]

Everything served for a montage task is computed here with ex_fuzzy and written to ``<published>/<model_id>/``:
``rules.json`` (``ModelRules``), ``montage.json``, ``card.json`` (``FnirsModelCard``), ``trials.json``, ``traces.json``
(``{sample_id: TrialTrace}``), the run's ``model.pkl`` and ``SHA256SUMS``. The registry entry gets ``view: montage``.
The API and the static export only read these files: no inference at request time.

Checks: the trace predictions equal the run's ``predictions.parquet`` (the model's ``predict``) for every row, and every
document validates against the contract before anything is written.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from atlas.contracts import models as m
from atlas.domains.fnirs.montage import OUT as MONTAGE_FILE
from atlas.domains.fnirs.regions import OUT as REGIONS_FILE
from atlas.explain import mixture as mix_engine
from atlas.explain.classifier import build_classifier_traces
from atlas.ml import artifacts
from atlas.ml.experiment_fnirs import CLASS_LABELS, SIGNALS, UNIT, feature_columns, load_table
from atlas.ml.rules_export import export_classifier_rules
from atlas.paths import ARTIFACTS_DIR, DATA_DIR
from atlas.services import layout

TASK_ID = "fnirs_nback"
RAW = DATA_DIR / "raw/fnirs-nback"
TABLE = RAW / "block_avg_tmb.csv"
DATA_VERSION = "fnirs-nback-shin2018-caterson-244d8a0"
CONDITIONS = {7: "0-back", 8: "2-back", 9: "3-back"}
FILES = {"montage": "montage.json", "trials": "trials.json", "traces": "traces.json"}
# Never a real time: ``build_*_traces`` key rows by (entity, issue time); this placeholder is dropped with them.
_NO_TIME = datetime(1970, 1, 1, tzinfo=timezone.utc)
TERM_LABELS = {"Low": ("Bajo", "Low"), "Medium": ("Medio", "Medium"), "High": ("Alto", "High")}
SIGNAL_ES = {"HbO": "HbO (oxihemoglobina)", "HbR": "HbR (desoxihemoglobina)"}
SIGNAL_EN = {"HbO": "HbO (oxyhaemoglobin)", "HbR": "HbR (deoxyhaemoglobin)"}
ATTRIBUTION = [
    m.Attribution(
        text="Promedios por bloque: J. Caterson et al., demo ex-Fuzzy fNIRS (github.com/jjcato9/ex_fuzzy_fnirs_demo), "
             "licencia MIT.",
        text_en="Block averages: J. Caterson et al., ex-Fuzzy fNIRS demo (github.com/jjcato9/ex_fuzzy_fnirs_demo), "
                "MIT licence.",
        license="MIT", url="https://github.com/jjcato9/ex_fuzzy_fnirs_demo"),
    m.Attribution(
        text="Registros: J. Shin, A. von Lühmann, D.-W. Kim, J. Mehnert, H.-J. Hwang y K.-R. Müller, «Simultaneous "
             "acquisition of EEG and NIRS during cognitive tasks for an open access dataset», Scientific Data 5, "
             "180003 (2018). CC0 1.0.",
        text_en="Recordings: J. Shin, A. von Lühmann, D.-W. Kim, J. Mehnert, H.-J. Hwang and K.-R. Müller, "
                "'Simultaneous acquisition of EEG and NIRS during cognitive tasks for an open access dataset', "
                "Scientific Data 5, 180003 (2018). CC0 1.0.",
        license="CC0-1.0", url="https://doc.ml.tu-berlin.de/simultaneous_EEG_NIRS/"),
]
SCHEME = m.TargetScheme(
    name="Carga de memoria de trabajo", name_en="Working-memory load", short_name="carga",
    short_name_en="load", kind=m.SchemeKind.ANALYTICAL, source_url="https://doc.ml.tu-berlin.de/simultaneous_EEG_NIRS/",
    unit="n",
    # Keys: the dataset's conditions; shown names say what they mean. Colours: two steps of one green (a level
    # of one quantity), away from the scalp's diverging blue/sienna and the rule colours; dataviz validator, light mode,
    # Paper and Mist: all checks pass, the light step 2.6:1 / 2.4:1 (WARN: chips and cells always carry text).
    classes=[
        m.TargetClass(label="0-back", display_label="Carga baja", display_label_en="Low load",
                      lower=None, upper=1, color="#36b26f",
                      description="Tarea fácil: basta con reconocer cada dígito, sin recordar los anteriores.",
                      description_en="Easy task: each digit only has to be recognised, with no earlier digits to "
                                     "remember."),
        m.TargetClass(label="2/3-back", display_label="Carga alta", display_label_en="High load", lower=1, upper=None,
                      color="#0b6e36",
                      description="Tarea difícil: decir si cada dígito es igual al de 2 o 3 posiciones antes, así que "
                                  "hay que recordar los últimos dígitos.",
                      description_en="Hard task: say whether each digit equals the one 2 or 3 positions back, so the "
                                     "last digits have to be held in memory."),
    ])


def split_feature(feature: str) -> tuple[str, str]:
    """'tmb_s1_chAF7' -> ('HbO', 'AF7')."""
    signal, channel = feature.removeprefix("tmb_").split("_ch", 1)
    return SIGNALS[signal], channel


def sample_id(subject: int, trial: int) -> str:
    return f"s{int(subject):02d}-t{int(trial):02d}"


def _labels(rules: m.ModelRules, regions: dict) -> m.ModelRules:
    variables = []
    for var in rules.variables:
        signal, channel = split_feature(var.feature)
        region = regions.get(channel, {})
        where_es = f", región aproximada: {region['region'].lower()}" if region else ""
        where_en = f", approximate region: {region['region_en'].lower()}" if region else ""
        variables.append(var.model_copy(update={
            "label": f"{signal} en {channel}", "label_en": f"{signal} at {channel}",
            "description": f"Cambio medio de {SIGNAL_ES[signal]} en el canal {channel} entre 10 y 40 s del bloque, "
                           f"respecto a la media de −5 a −2 s ({UNIT}{where_es}).",
            "description_en": f"Mean change of {SIGNAL_EN[signal]} at channel {channel} 10 to 40 s into the block, "
                              f"relative to the mean from −5 to −2 s ({UNIT}{where_en}).",
            "terms": [t.model_copy(update=dict(zip(("label", "label_en"), TERM_LABELS.get(t.name, (None, None)),
                                                   strict=True)))
                      for t in var.terms],
        }))
    return rules.model_copy(update={"variables": variables})


def build_montage(features: list[str], regions_doc: dict, montage_doc: dict) -> m.MontageResponse:
    by_channel: dict[str, list[m.SensorInput]] = {}
    for feature in features:
        signal, channel = split_feature(feature)
        by_channel.setdefault(channel, []).append(m.SensorInput(
            feature=feature, signal=signal, label=f"{signal} en {channel}", label_en=f"{signal} at {channel}"))
    regions = regions_doc["channels"]
    channels = []
    for ch in montage_doc["channels"]:
        name, xyz = ch["label"], tuple(ch["xyz"])
        region = regions.get(name, {})
        channels.append(m.MontageChannel(
            channel_id=name, xyz=xyz, xy=m.head_projection(xyz), region=region.get("region"),
            region_en=region.get("region_en"), brodmann=region.get("brodmann"),
            inputs=sorted(by_channel.pop(name), key=lambda i: i.signal.value)))
    if by_channel:
        raise ValueError(f"inputs without a channel position: {sorted(by_channel)}")
    return m.MontageResponse(
        data_version=DATA_VERSION, task_id=TASK_ID, frame=montage_doc["frame"], source=montage_doc["source"],
        source_url=montage_doc["source_url"], source_sha256=montage_doc["source_sha256"],
        region_source=regions_doc["source"], region_approximate=regions_doc["approximate"], channels=channels)


def build_traces(model, frame: pd.DataFrame, features: list[str], test_subjects: set[int], model_id: str
                 ) -> dict[str, m.TrialTrace]:
    ids = [sample_id(s, t) for s, t in zip(frame["subject"], frame["trial"], strict=True)]
    build = mix_engine.build_mixture_traces if mix_engine.is_mixture(model) else build_classifier_traces
    traces = build(model, frame[features], ids, [_NO_TIME] * len(frame), class_labels=CLASS_LABELS, model_id=model_id,
                   task_id=TASK_ID, horizon_hours=0, target_unit="n", data_version=DATA_VERSION,
                   feature_units={f: UNIT for f in features})
    out = {}
    for trace, (_, row), sid in zip(traces, frame.iterrows(), ids, strict=True):
        body = trace.model_dump(exclude={"entity_id", "issued_at_utc", "valid_at_utc", "observation_ids", "observed",
                                         "observed_label"})
        out[sid] = m.TrialTrace.model_validate({
            **body, "sample_id": sid, "subject": int(row.subject), "trial": int(row.trial),
            "split": "test" if row.subject in test_subjects else "train",
            "observed_label": CLASS_LABELS[int(row.y)],
        })
    return out


def build_trials(frame: pd.DataFrame, traces: dict[str, m.TrialTrace], model_id: str) -> m.TrialsResponse:
    trials = []
    for _, row in frame.iterrows():
        t = traces[sample_id(row.subject, row.trial)]
        p = t.prediction
        trials.append(m.TrialRecord(
            sample_id=t.sample_id, subject=t.subject, trial=t.trial, condition=CONDITIONS[int(row.event)],
            split=t.split, observed_label=t.observed_label, predicted_label=p.label,
            missing_reason=None if p.label is not None else p.missing_reason, winning_rule_id=p.winning_rule_id,
            top_rule_id=p.top_rule_id))
    trials.sort(key=lambda r: (r.split != "test", r.subject, r.trial))  # test subjects first, as the view opens
    return m.TrialsResponse(data_version=DATA_VERSION, model_id=model_id, task_id=TASK_ID, trials=trials)


def _metric_rows(select: dict, final: dict, shape: str, seed: int, seeds: dict | None = None,
                 nested: dict | None = None) -> list[m.MetricRow]:
    names = ("macro_f1", "accuracy", "balanced_accuracy", "mcc", "share_unknown")
    rows = []
    fits = [f for f in select["fits"] if f["shape"] == shape]
    n_val = sum(f["n"] for f in fits if f["seed"] == fits[0]["seed"])  # every training row is held out once per seed
    for name in names:
        rows.append(m.MetricRow(estimator="exfuzzy", metric=name, value=float(np.mean([f[name] for f in fits])),
                                n=n_val, slice="validation"))
    for b in select["baselines"]:
        for name in ("macro_f1", "accuracy", "mcc"):
            rows.append(m.MetricRow(estimator=b["estimator"], metric=name, value=float(b[name]), n=n_val,
                                    slice="validation"))
    published = final["estimators"][f"exfuzzy-seed{seed}"]
    for name in names:
        rows.append(m.MetricRow(estimator="exfuzzy", metric=name, value=float(published[name]), n=published["n"],
                                slice="test"))
        rows.append(m.MetricRow(estimator="exfuzzy", metric=name, value=float(published["train"][name]),
                                n=published["train"]["n"], slice="train"))
    # error bars (experiment_fnirs seeds): every estimator on test with each seed, and on each validation fold
    for part, key in (("test", "seed"), ("validation", "fold")):
        for est, by in (seeds or {}).get(part, {}).items():
            for k, res in by.items():
                rows += [m.MetricRow(estimator=est, metric=name, value=float(res[name]), n=int(res["n"]),
                                     slice=f"{part}/{key}={k}") for name in ("macro_f1", "accuracy", "mcc")]
    # spread over people (experiment_fnirs nested): each outer group of subjects as test, mean over the seeds
    for fold in (nested or {}).get("folds", []):
        for est, res in fold["mean_over_seeds"].items():
            rows += [m.MetricRow(estimator=est, metric=name, value=float(res[name]), n=int(fold["n_test"]),
                                 slice=f"nested/fold={fold['fold']}") for name in ("macro_f1", "accuracy", "mcc")]
    for est, v in final["estimators"].items():
        if not est.startswith("exfuzzy"):
            rows += [m.MetricRow(estimator=est, metric=name, value=float(v[name]), n=v["n"], slice="test")
                     for name in names]
    return rows


def publish(run_dir: Path, published_dir: Path, *, table: Path = TABLE) -> Path:
    run_dir, published_dir = Path(run_dir), Path(published_dir)
    run = json.loads((run_dir / "run.json").read_text())
    if not run.get("published"):
        raise ValueError(f"{run_dir.name} is not the seed fixed for publication in the experiment config")
    experiments = run_dir.parent / "experiments"
    select = json.loads((experiments / f"{run['experiment_id']}-select.json").read_text())
    final = json.loads((experiments / f"{run['experiment_id']}-final.json").read_text())
    seeds_path = experiments / f"{run['experiment_id']}-seeds.json"
    seeds = json.loads(seeds_path.read_text()) if seeds_path.exists() else None
    nested_path = experiments / f"{run['experiment_id']}-nested.json"
    nested = json.loads(nested_path.read_text()) if nested_path.exists() else None
    shape = select["chosen_shape"]
    model_id = f"exfuzzy-{TASK_ID}-{shape}-seed{run['seed']}"
    model = artifacts.load_model(run_dir)
    frame = load_table(table)
    features = feature_columns(frame)
    test = set(run["test_subjects"])

    regions_doc = json.loads(REGIONS_FILE.read_text())
    montage = build_montage(features, regions_doc, json.loads(MONTAGE_FILE.read_text()))
    rules = export_classifier_rules(
        model, model_id=model_id, task_id=TASK_ID, domain=m.Domain.FNIRS, target_label="carga de memoria",
        target_scheme=SCHEME, horizon_hours=0, data_version=DATA_VERSION, feature_units={f: UNIT for f in features},
        X_reference=frame.loc[~frame["subject"].isin(test), features])
    rules = _labels(rules, regions_doc["channels"])
    traces = build_traces(model, frame, features, test, model_id)
    expected = pd.read_parquet(run_dir / "predictions.parquet").set_index(["subject", "trial"])["predicted"]
    for t in traces.values():
        got = -1 if t.prediction.label is None else CLASS_LABELS.index(t.prediction.label)
        if got != int(expected.loc[(t.subject, t.trial)]):
            raise AssertionError(f"{t.sample_id}: trace class differs from the model's predict")
    trials = build_trials(frame, traces, model_id)
    git_commit, git_dirty = run["git"]
    card = m.FnirsModelCard(
        data_version=DATA_VERSION, model_id=model_id, task_id=TASK_ID, domain=m.Domain.FNIRS, run_id=run_dir.name,
        created_at_utc=datetime.fromtimestamp((run_dir / artifacts.MODEL_FILE).stat().st_mtime, timezone.utc),
        git_commit=git_commit, git_dirty=git_dirty, exfuzzy_version=run["exfuzzy_version"],
        python_version=run["python"],
        seed=run["seed"], target="n-back load", features=features, hyperparameters=run["params"],
        data_checksums={Path(table).name: artifacts.sha256_file(table)},
        split=m.SubjectSplit(
            train_subjects=sorted(set(frame["subject"]) - test), test_subjects=sorted(test),
            selection_folds=select["folds"], selection_metric="macro_f1"),
        target_scheme=SCHEME, metrics=_metric_rows(select, final, shape, run["seed"], seeds, nested),
        attribution=ATTRIBUTION,
        warnings=["Las filas de train son predicciones dentro de la muestra: el modelo se ajustó con ellas."])

    final_dir = published_dir / model_id
    published_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f".tmp-{model_id}-", dir=published_dir))
    try:
        shutil.copy2(run_dir / artifacts.MODEL_FILE, tmp / artifacts.MODEL_FILE)
        (tmp / "rules.json").write_text(rules.model_dump_json(indent=1))
        (tmp / layout.CARD_FILE).write_text(card.model_dump_json(indent=1))
        (tmp / FILES["montage"]).write_text(montage.model_dump_json(indent=1))
        (tmp / FILES["trials"]).write_text(trials.model_dump_json())
        (tmp / FILES["traces"]).write_text(json.dumps({k: v.model_dump(mode="json") for k, v in traces.items()}))
        layout.write_checksums(tmp)
        if final_dir.exists():
            shutil.rmtree(final_dir)
        os.rename(tmp, final_dir)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    registry = layout.read_registry(published_dir)
    registry.tasks[TASK_ID] = layout.RegistryEntry(
        model_id=model_id, domain=m.Domain.FNIRS, title="Working-memory load from fNIRS (Shin et al. 2018)",
        task_type="classification", target="n-back load", unit="n", horizon_hours=0, data_version=DATA_VERSION,
        territory="fnirs_nback", territory_title="Cuero cabelludo (36 canales NIRS)",
        territory_title_en="Scalp (36 NIRS channels)", view=m.TaskView.MONTAGE)
    registry.schema_version = m.SCHEMA_VERSION
    layout.write_registry(published_dir, registry)
    print(f"published {model_id}: {len(trials.trials)} trials, {len(rules.rules)} rules -> {final_dir}", flush=True)
    return final_dir


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--published", type=Path, default=ARTIFACTS_DIR / "published")
    args = parser.parse_args(argv)
    publish(args.run, args.published)


if __name__ == "__main__":
    main()
