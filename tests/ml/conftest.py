"""Shared tiny fixtures: a synthetic multi-entity series and a few fitted / hand-built fuzzy models."""

import os

# Keep BLAS/OpenMP polite on the shared machine; must be set before numpy spins up its pools.
for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "2")

import pandas as pd  # noqa: E402
import pytest  # noqa: E402
from ml_helpers import SMALL, fit_fuzzy  # noqa: E402

from atlas.contracts import models as m  # noqa: E402
from atlas.ml.fuzzy import FuzzyRegressor  # noqa: E402
from atlas.ml.pipeline import RunConfig  # noqa: E402
from atlas.ml.split import chronological_split_spec  # noqa: E402
from atlas.ml.synthetic import FEATURE_UNITS, FEATURES, TARGET, make_synthetic_table  # noqa: E402


@pytest.fixture(scope="session")
def table() -> pd.DataFrame:
    """3 entities x 20 days of hourly rows; 3% of the exogenous inputs are missing."""
    return make_synthetic_table(n_entities=3, n_hours=24 * 20, seed=1, exo_missing_fraction=0.03)


@pytest.fixture(scope="session")
def complete_rows(table) -> pd.DataFrame:
    return table.dropna().reset_index(drop=True)


@pytest.fixture(scope="session")
def run_config(table) -> RunConfig:
    return RunConfig(
        task_id="synthetic_y_h6", domain=m.Domain.AIR, target="y", target_column=TARGET, unit="u", horizon_hours=6,
        features=FEATURES, feature_units=FEATURE_UNITS, persistence_feature="y_t",
        split=chronological_split_spec(table["issued_at_utc"], horizon_hours=6), seed=3,
        data_version="synthetic-test", synthetic=True, fuzzy=SMALL, gbm_max_iter=20,
    )


@pytest.fixture(scope="session")
def additive_model(complete_rows) -> FuzzyRegressor:
    return fit_fuzzy(complete_rows)


@pytest.fixture(scope="session")
def sufficient_model(complete_rows) -> FuzzyRegressor:
    return fit_fuzzy(complete_rows, rule_mode="sufficient", tolerance=0.3)
