"""FX retrain: detecting which ex_fuzzy fixes are installed and refusing to run without a needed one.

The suite must pass on the pinned 3.3.1 (no fixes) and on the integration build (all of them): tests that need a fix
skip, tests of the refusal run on whichever side lacks it.
"""

import shutil
import subprocess
from types import SimpleNamespace

import ex_fuzzy
import pytest

from atlas.ml import exfuzzy_features as xf
from atlas.ml.fuzzy import FuzzyParams

SOURCE = "local atlas/local-integration @ 2ffcfb9 (3.3.1 + PRs #27 #29 #31 #32)"


def test_probes_are_booleans_and_stable():
    for name, probe in xf._PROBES.items():
        assert probe() is probe() and isinstance(probe(), bool), name


def test_require_unknown_feature_is_a_value_error():
    with pytest.raises(ValueError, match="unknown ex_fuzzy feature"):
        xf.require("nonsense")


@pytest.mark.parametrize("feature", xf.FEATURES)
def test_require_refuses_a_missing_fix_with_a_clear_message(feature, monkeypatch):
    monkeypatch.setitem(xf._PROBES, feature, lambda: False)
    with pytest.raises(xf.ExFuzzyFeatureError) as err:
        xf.require(feature)
    text = str(err.value)
    assert feature in text and "PR" in text and ex_fuzzy.__version__ in text and "PYTHONPATH" in text
    monkeypatch.setitem(xf._PROBES, feature, lambda: True)
    xf.require(feature)


def test_ensure_config_checks_every_listed_feature(monkeypatch):
    monkeypatch.setitem(xf._PROBES, "unique_antecedents", lambda: True)
    monkeypatch.setitem(xf._PROBES, "term_bound_fix", lambda: False)
    xf.ensure_config(SimpleNamespace(requires_exfuzzy=["unique_antecedents"]))
    xf.ensure_config(SimpleNamespace())  # a config without the field needs nothing
    with pytest.raises(xf.ExFuzzyFeatureError, match="term_bound_fix"):
        xf.ensure_config(SimpleNamespace(requires_exfuzzy=["unique_antecedents", "term_bound_fix"]))


def _git(repo, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(repo), *args], check=True,
                   capture_output=True)


@pytest.fixture
def checkout(tmp_path):
    """A git repository whose root holds a package directory ``ex_fuzzy``, like a clone of Fuminides/ex-fuzzy."""
    if shutil.which("git") is None:
        pytest.skip("git is not available")
    repo = tmp_path / "ex-fuzzy"
    (repo / "ex_fuzzy").mkdir(parents=True)
    (repo / "ex_fuzzy" / "__init__.py").write_text("__version__ = '3.3.1'\n")
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def test_version_of_a_git_checkout_names_the_commit_and_the_dirty_state(checkout):
    init = str(checkout / "ex_fuzzy" / "__init__.py")
    head = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"], capture_output=True, text=True,
                          check=True).stdout.strip()
    build = xf.detect_build(init, release="3.3.1")
    assert build == xf.ExFuzzyBuild("3.3.1", head[:7], False) and build.version == f"3.3.1+g{head[:7]}"
    (checkout / "ex_fuzzy" / "new.py").write_text("x = 1\n")  # an untracked file changes what is imported
    assert xf.detect_build(init, release="3.3.1").version == f"3.3.1+g{head[:7]}.dirty"
    _git(checkout, "add", ".")
    _git(checkout, "commit", "-q", "-m", "more")
    assert xf.detect_build(init, release="3.3.1").version.startswith("3.3.1+g") and not xf.detect_build(
        init, release="3.3.1").dirty
    (checkout / "ex_fuzzy" / "__init__.py").write_text("__version__ = '3.3.1'\n# edited\n")
    assert xf.detect_build(init, release="3.3.1").version.endswith(".dirty")


def test_release_that_is_already_a_local_version_gets_a_dot_not_a_second_plus():
    assert xf.ExFuzzyBuild("3.3.1+x", "abc1234", False).version == "3.3.1+x.gabc1234"


def test_an_installed_package_records_the_plain_release(tmp_path, checkout):
    plain = tmp_path / "site-packages" / "ex_fuzzy"
    plain.mkdir(parents=True)
    (plain / "__init__.py").write_text("")
    assert xf.detect_build(str(plain / "__init__.py"), release="3.3.1") == xf.ExFuzzyBuild("3.3.1")
    # inside some unrelated repository, but not at its root: still an installed package
    nested = checkout / "venv" / "lib" / "ex_fuzzy"
    nested.mkdir(parents=True)
    (nested / "__init__.py").write_text("")
    assert xf.detect_build(str(nested / "__init__.py"), release="3.3.1").version == "3.3.1"


def test_without_git_the_release_is_recorded_unchanged(checkout, monkeypatch):
    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(xf.subprocess, "run", no_git)
    assert xf.detect_build(str(checkout / "ex_fuzzy" / "__init__.py"), release="3.3.1").version == "3.3.1"


def test_the_imported_library_version_is_what_every_manifest_records():
    build = xf.exfuzzy_build()
    assert xf.exfuzzy_version() == build.version and build.release == ex_fuzzy.__version__
    assert xf.exfuzzy_version().startswith(ex_fuzzy.__version__)
    if build.commit is None:  # the PyPI pin: nothing changes for the published artifacts
        assert xf.exfuzzy_version() == ex_fuzzy.__version__
    else:
        assert f"+g{build.commit}" in xf.exfuzzy_version()


def test_inference_specs_record_the_same_version(monkeypatch):
    from atlas.explain import engine

    monkeypatch.setattr(xf, "exfuzzy_build", lambda: xf.ExFuzzyBuild("3.3.1", "2ffcfb9", False))
    from atlas.services.mock_model import build_rulebase

    spec = engine.inference_spec(engine.get_rulebase(build_rulebase()))
    assert spec.exfuzzy_version == "3.3.1+g2ffcfb9"


def test_provenance_is_empty_on_a_release_without_a_source_and_factual_with_one(monkeypatch):
    plain = SimpleNamespace(exfuzzy_source=None, requires_exfuzzy=[])
    monkeypatch.setattr(xf, "exfuzzy_build", lambda: xf.ExFuzzyBuild("3.3.1"))
    assert xf.provenance_warnings(plain) == [] and xf.provenance_hyperparameters(plain) == {}
    config = SimpleNamespace(exfuzzy_source=SOURCE, requires_exfuzzy=["term_bound_fix"])
    (warning,) = xf.provenance_warnings(config)
    assert "unknown" in warning and "experimental" not in warning  # source named, but not a git checkout
    monkeypatch.setattr(xf, "exfuzzy_build", lambda: xf.ExFuzzyBuild("3.3.1", "2ffcfb9", False))
    (warning,) = xf.provenance_warnings(config)
    assert f"exfuzzy_source = {SOURCE!r}" in warning and "@ 2ffcfb9" in warning and "3.3.1+g2ffcfb9" in warning
    assert "docs/reproduce.md" in warning and "release pin will replace it" in warning
    assert "experimental" not in warning and "not for publication" not in warning
    (warning,) = xf.provenance_warnings(plain)  # a commit without a named source: not the pinned release
    assert "git commit 2ffcfb9" in warning and "not the pinned release" in warning and "3.3.1+g2ffcfb9" in warning
    monkeypatch.setattr(xf, "exfuzzy_build", lambda: xf.ExFuzzyBuild("3.3.1", "2ffcfb9", True))
    (warning,) = xf.provenance_warnings(config)
    assert "uncommitted" in warning and "3.3.1+g2ffcfb9.dirty" in warning
    hyper = xf.provenance_hyperparameters(config)
    assert hyper["exfuzzy_source"] == SOURCE and hyper["requires_exfuzzy"] == ["term_bound_fix"]
    assert hyper["exfuzzy_module_path"] == ex_fuzzy.__file__


def test_unique_antecedents_is_opt_in_gated_and_invisible_when_off():
    off = FuzzyParams()
    assert "unique_antecedents" not in off.as_dict() and off.estimator_options() == {}
    on = FuzzyParams(unique_antecedents=True)
    assert on.as_dict()["unique_antecedents"] is True
    if xf.has_unique_antecedents():
        assert on.estimator_options() == {"unique_antecedents": True}
    else:
        with pytest.raises(xf.ExFuzzyFeatureError, match="unique_antecedents"):
            on.estimator_options()


@pytest.mark.skipif(not xf.has_term_bound_fix(), reason="needs ex_fuzzy PR 32 (integration build)")
def test_term_genes_of_a_larger_variable_can_reach_every_term():
    """With mixed counts (3, 3, 5, 5) the term genes reach index 4: the premise of the 5-term hour experiments."""
    assert xf.has_term_bound_fix()


@pytest.mark.skipif(xf.has_term_bound_fix(), reason="documents the 3.3.1 behaviour; the fix is installed")
def test_pinned_library_bounds_term_genes_by_slot():
    assert not xf.has_term_bound_fix()


@pytest.mark.skipif(not xf.has_proportional_term_remap(), reason="needs ex_fuzzy PR 35 (integration build)")
def test_term_genes_are_mapped_proportionally_not_clipped():
    """Gene 2 of a 3-term variable under a 5-term maximum selects term (2 * 3) // 5 = 1; clipping would give 2."""
    assert xf.has_proportional_term_remap() and xf.has_term_bound_fix()


@pytest.mark.skipif(xf.has_proportional_term_remap(), reason="documents the 3.3.1 / PR 32 behaviour")
def test_without_pr35_term_genes_are_clipped():
    assert not xf.has_proportional_term_remap()


def test_a_pip_install_from_git_records_its_commit(monkeypatch, tmp_path):
    """A pip install from git (``ex_fuzzy @ git+...@<sha>``, the v0.7 pin before 3.4.0): PEP 610 names the commit."""
    package = tmp_path / "ex_fuzzy"
    package.mkdir()
    (package / "__init__.py").write_text("")

    class Dist:
        def __init__(self, text):
            self.text = text

        def locate_file(self, name):
            return tmp_path / name

        def read_text(self, name):
            return self.text if name == "direct_url.json" else None

    vcs = '{"url": "https://github.com/Fuminides/ex-fuzzy", "vcs_info": {"vcs": "git", "commit_id": "20c1095a1314"}}'
    monkeypatch.setattr(xf.metadata, "distribution", lambda name: Dist(vcs))
    assert xf.vcs_install_commit(package) == "20c1095"
    assert xf.ExFuzzyBuild("3.3.1", xf.vcs_install_commit(package)).version == "3.3.1+g20c1095"
    monkeypatch.setattr(xf.metadata, "distribution", lambda name: Dist(None))  # an index (PyPI) install
    assert xf.vcs_install_commit(package) is None
    monkeypatch.setattr(xf.metadata, "distribution", lambda name: Dist(vcs))
    assert xf.vcs_install_commit(tmp_path / "elsewhere") is None  # the imported copy is not that distribution
