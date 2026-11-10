"""One tiny synthetic run, trained and published once per session (about a second)."""

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "2")

import pytest  # noqa: E402

from atlas.services.synthetic import SyntheticPublished, build_synthetic  # noqa: E402


@pytest.fixture(scope="session")
def built(tmp_path_factory) -> SyntheticPublished:
    return build_synthetic(tmp_path_factory.mktemp("published"))


@pytest.fixture(scope="session")
def built_class(tmp_path_factory) -> SyntheticPublished:
    """The same, for a tiny winning-rule classifier over three invented bands."""
    return build_synthetic(tmp_path_factory.mktemp("published-class"), task="classification")


@pytest.fixture(scope="session")
def built_v04(tmp_path_factory) -> SyntheticPublished:
    """Contract v0.4 variant of the regressor: unmodelled entity E9, attribution, scheme metadata."""
    return build_synthetic(tmp_path_factory.mktemp("published-v04"), v04=True)


@pytest.fixture(scope="session")
def built_class_v04(tmp_path_factory) -> SyntheticPublished:
    return build_synthetic(tmp_path_factory.mktemp("published-class-v04"), task="classification", v04=True)


@pytest.fixture(scope="session")
def built_mixture(tmp_path_factory) -> SyntheticPublished:
    """Contract v0.7: the tiny classifier with the mixture of rules (needs an ex_fuzzy with inference='mixture')."""
    return build_synthetic(tmp_path_factory.mktemp("published-mixture"), task="mixture", v04=True)
