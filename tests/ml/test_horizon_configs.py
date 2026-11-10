"""The experiment configs of the longer horizons (AT-080) are the published ones with only table, task and horizon changed."""

# ruff: noqa: E501  (long assertions)

import json
from pathlib import Path

import pytest

from atlas.ml.experiment_class import ClassExperimentConfig
from atlas.ml.experiment_nyc import NycExperimentConfig

CONFIGS = Path(__file__).resolve().parents[2] / "configs" / "ml"
# territory -> (published config, horizon config name, horizons, table directory, data_version template, config class)
CASES = {
    "madrid": ("madrid_no2_h6_ica2_justified_experiment.json", "madrid_no2_h{h}_ica2_justified_experiment.json", (1, 3, 12, 24),
               "processed/air/features/madrid_no2_h{h}/table", "madrid-no2-h{h}-v1", ClassExperimentConfig),
    "de": ("de_no2_h6_eaqi_experiment.json", "de_no2_h{h}_eaqi_experiment.json", (1, 3, 12, 24),
           "processed/air-de/features/de_no2_h{h}/table", "de-no2-h{h}-v1", ClassExperimentConfig),
    "nyc": ("nyc_pickups_h1_level_rel7_experiment.json", "nyc_pickups_h{h}_level_rel7_experiment.json", (3, 6, 24),
            "processed/mobility/features/nyc_pickups_h{h}_level", None, NycExperimentConfig),
}
CASE_IDS = [(t, h) for t, case in CASES.items() for h in case[2]]


@pytest.mark.parametrize("territory, h", CASE_IDS)
def test_only_table_task_horizon_version_and_checksums_differ_from_the_published_config(territory, h):
    published_name, name, _, table, version, cls = CASES[territory]
    old = json.loads((CONFIGS / published_name).read_text())
    new = json.loads((CONFIGS / name.format(h=h)).read_text())
    cls.model_validate(new)  # loads with the experiment's own config class
    assert new["table"] == table.format(h=h)
    assert new["base"]["horizon_hours"] == h and new["base"]["task_id"].endswith(f"_h{h}")
    if version:
        assert new["base"]["data_version"] == version.format(h=h)
    assert set(new["base"]["data_checksums"]) <= set(old["base"]["data_checksums"]) | {f"nyc_pickups_h{h}_level_report.json", f"nyc_pickups_h{h}_level_reference.parquet"}
    # everything else is the published protocol: features, split, embargo, grid, budget, seeds, partitions, class scheme
    for key in set(old) | set(new):
        if key in ("table", "base"):
            continue
        assert new[key] == old[key], key
    for key in set(old["base"]) | set(new["base"]):
        if key in ("task_id", "horizon_hours", "data_version", "data_checksums"):
            continue
        assert new["base"][key] == old["base"][key], key
