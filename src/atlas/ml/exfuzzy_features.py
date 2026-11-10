"""Which ex_fuzzy fixes the installed library has, and a clear error where an experiment needs one (FX retrain).

The serving pin is ex-fuzzy 3.4.0 from PyPI (contract v0.7; before it, 3.3.1), which has every change below. They
matter to the experiments of ``docs/ml/fx_retrain_with_fixed_exfuzzy.md`` and later; they are detected by what the code
*does*, not by the version string (the local integration builds said 3.3.1):

``term_bound_fix`` (upstream PR 32)
    every term gene of ``FitRuleBase`` is bounded by the largest partition, so a variable with more terms than the
    first ``nAnts`` ones can use all of them. In 3.3.1 slot ``j`` is bounded by the term count of feature ``j``.
``unique_antecedents`` (PR 30)
    ``BaseFuzzyRulesRegressor(unique_antecedents=True)`` drops rules that repeat an earlier antecedent set.
``breakpoint_partition`` (PR 31)
    ``utils.construct_breakpoint_partition``.
``proportional_term_remap`` (PR 35, stacked on 32)
    a term gene ``g`` selects term ``(g * n) // M`` of a variable with ``n`` terms (``M`` = the largest partition)
    instead of being clipped to its last term; the identity when ``n == M``.
``rule_mixture`` (PR 44, in 3.4.0)
    ``BaseFuzzyRulesClassifier(inference='mixture')``: every rule's firing enters a learned per-class weighted sum
    (``docs/ml/rule_mixture.md``).
``mixture_pruning`` (PR 44, in 3.4.0)
    ``mixture_search`` prunes by the rules' role in the mixture (``mixture_pruning``, ``mixture_prune_threshold``).
``ordinal_conditions`` (PR 45, open: ``docs/ml/ordinal_conditions.md``)
    ``ordinal_conditions=True`` (or a collection of features, from 7a0844a) on the classifier and regressor lets a
    rule say ``x IS at least t`` / ``at most t``; ``rule.conditions(antecedents)`` returns operator and term without
    parsing text. Not in 3.4.0: the serving pin must not need it, and the helpers below (``rule_conditions``,
    ``condition_labels``) also work without it.
``compound_terms`` (PR 45, 7a0844a)
    ``compound_terms={feature: [(name, [terms])]}``: named unions of terms (bounded sum); a rule condition on one has
    operator ``any_of``, its members in ``terms`` and the given ``name``.

Nothing in Atlas serving may need them: experiment configs name what they require (``requires_exfuzzy``) and
``ensure_config`` refuses to run on a library without it. A model fitted on the integration build also carries
``exfuzzy_source`` (config) in its manifest and summary, see ``provenance_warnings``.

Every place that records the library version (manifests, ``rules.json`` inference block) calls ``exfuzzy_version()``,
which is ``ex_fuzzy.__version__`` for a PyPI install and a PEP 440 local version naming the git commit for a checkout
(``3.3.1+g2ffcfb9``, ``3.3.1+g2ffcfb9.dirty``), detected at runtime from where the module was imported. A pip install
from git (``ex_fuzzy @ git+https://...@<sha>``, the v0.7 pin until 3.4.0 was released) records its commit in the
distribution's ``direct_url.json`` (PEP 610), so it gives the same ``<release>+g<commit>`` as a checkout of that commit.
"""

from __future__ import annotations

import inspect
import json
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from importlib import metadata
from pathlib import Path
from typing import NamedTuple

import ex_fuzzy
import numpy as np
import pandas as pd

FEATURES = ("term_bound_fix", "unique_antecedents", "breakpoint_partition", "proportional_term_remap", "rule_mixture",
            "mixture_pruning", "ordinal_conditions", "compound_terms")
_UPSTREAM = {"term_bound_fix": "Fuminides/ex-fuzzy PR 32", "unique_antecedents": "Fuminides/ex-fuzzy PR 30",
             "breakpoint_partition": "Fuminides/ex-fuzzy PR 31",
             "proportional_term_remap": "Fuminides/ex-fuzzy PR 35",
             "rule_mixture": "Fuminides/ex-fuzzy PR 44 (feat/rule-mixture)",
             "mixture_pruning": "Fuminides/ex-fuzzy PR 44 (feat/rule-mixture, pruning by the role in the mixture)",
             "ordinal_conditions": "Fuminides/ex-fuzzy PR 45 (feature/ordinal-conditions)",
             "compound_terms": "Fuminides/ex-fuzzy PR 45 (feature/ordinal-conditions, 7a0844a)"}


@dataclass(frozen=True)
class ExFuzzyBuild:
    """Where the imported ex_fuzzy comes from: a git checkout (``commit`` set) or an installed package."""

    release: str  # ex_fuzzy.__version__
    commit: str | None = None  # abbreviated commit of the checkout the module was imported from
    dirty: bool = False  # the checkout has uncommitted or untracked changes

    @property
    def version(self) -> str:
        """``release`` for an installed package, else ``release+g<commit>[.dirty]`` (PEP 440 local version)."""
        if self.commit is None:
            return self.release
        joiner = "." if "+" in self.release else "+"
        return f"{self.release}{joiner}g{self.commit}{'.dirty' if self.dirty else ''}"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True,
                          timeout=30).stdout.strip()


def detect_build(module_file: str | None = None, release: str | None = None) -> ExFuzzyBuild:
    """The build of the ex_fuzzy module at ``module_file`` (default: the imported one).

    A git checkout is recognised only when the repository root contains the package directory itself
    (``<root>/ex_fuzzy`` is the directory of the module), so a PyPI install inside some unrelated repository, or
    without git, is plain ``release``.
    """
    release = release or ex_fuzzy.__version__
    package = Path(module_file or ex_fuzzy.__file__).resolve().parent
    try:
        root = Path(_git(package, "rev-parse", "--show-toplevel")).resolve()
        if root / package.name != package:
            return ExFuzzyBuild(release, vcs_install_commit(package))
        commit = _git(root, "rev-parse", "--short=7", "HEAD")
        dirty = bool(_git(root, "status", "--porcelain"))
    except (OSError, subprocess.SubprocessError):
        return ExFuzzyBuild(release, vcs_install_commit(package))
    return ExFuzzyBuild(release, commit, dirty)


def vcs_install_commit(package: Path, distribution: str = "ex_fuzzy") -> str | None:
    """The abbreviated commit of a pip install from git (PEP 610 ``direct_url.json``), when ``package`` is that install.

    None for an index (PyPI) install, an install of another copy, or no distribution metadata."""
    try:
        dist = metadata.distribution(distribution)
        if Path(dist.locate_file(f"{distribution}/__init__.py")).resolve().parent != package.resolve():
            return None
        text = dist.read_text("direct_url.json")
    except (metadata.PackageNotFoundError, OSError):
        return None
    if not text:
        return None
    commit = json.loads(text).get("vcs_info", {}).get("commit_id")
    return commit[:7] if commit else None


@lru_cache(maxsize=1)
def exfuzzy_build() -> ExFuzzyBuild:
    return detect_build()


def exfuzzy_version() -> str:
    """The version to record for the imported ex_fuzzy: ``3.4.0`` from PyPI, ``3.4.0+g10d811b`` from a checkout."""
    return exfuzzy_build().version


class ExFuzzyFeatureError(RuntimeError):
    """The installed ex_fuzzy lacks a fix that the requested experiment or option needs."""


@lru_cache(maxsize=1)
def has_unique_antecedents() -> bool:
    from ex_fuzzy.evolutionary_fit_regression import BaseFuzzyRulesRegressor

    return "unique_antecedents" in inspect.signature(BaseFuzzyRulesRegressor.__init__).parameters


@lru_cache(maxsize=1)
def has_rule_mixture() -> bool:
    from ex_fuzzy.evolutionary_fit import BaseFuzzyRulesClassifier

    return "inference" in inspect.signature(BaseFuzzyRulesClassifier.__init__).parameters


@lru_cache(maxsize=1)
def has_mixture_pruning() -> bool:
    """Whether ``mixture_search`` can prune by the rules' role in the mixture (``mixture_pruning``)."""
    from ex_fuzzy.evolutionary_fit import BaseFuzzyRulesClassifier

    return "mixture_pruning" in inspect.signature(BaseFuzzyRulesClassifier.__init__).parameters


@lru_cache(maxsize=1)
def has_ordinal_conditions() -> bool:
    """Whether the classifier and the regressor take ``ordinal_conditions`` and a rule can list its ``conditions``."""
    from ex_fuzzy.evolutionary_fit import BaseFuzzyRulesClassifier
    from ex_fuzzy.evolutionary_fit_regression import BaseFuzzyRulesRegressor
    from ex_fuzzy.rules import RuleSimple

    return (all("ordinal_conditions" in inspect.signature(c.__init__).parameters
                for c in (BaseFuzzyRulesClassifier, BaseFuzzyRulesRegressor)) and hasattr(RuleSimple, "conditions"))


@lru_cache(maxsize=1)
def has_compound_terms() -> bool:
    """Whether the classifier and the regressor take ``compound_terms`` (named unions of terms)."""
    from ex_fuzzy.evolutionary_fit import BaseFuzzyRulesClassifier
    from ex_fuzzy.evolutionary_fit_regression import BaseFuzzyRulesRegressor

    return all("compound_terms" in inspect.signature(c.__init__).parameters
               for c in (BaseFuzzyRulesClassifier, BaseFuzzyRulesRegressor))


@lru_cache(maxsize=1)
def has_breakpoint_partition() -> bool:
    from ex_fuzzy import utils

    return hasattr(utils, "construct_breakpoint_partition")


@lru_cache(maxsize=1)
def has_term_bound_fix() -> bool:
    """Whether the term genes of ``FitRuleBase`` are bounded by the largest partition (PR 32 reproduction).

    Variables with (3, 3, 5, 5) terms and two antecedents per rule: in 3.3.1 the largest term-gene bound is 2 (the
    third and fourth terms of the 5-term variables are unreachable), with the fix it is 4.
    """
    from ex_fuzzy import fuzzy_sets as fs
    from ex_fuzzy import utils
    from ex_fuzzy.evolutionary_fit import FitRuleBase

    rng = np.random.default_rng(0)
    X = pd.DataFrame(rng.random((120, 4)), columns=list("abcd"))
    y = (X["d"] > 0.5).astype(int).to_numpy()
    variables = [utils.construct_partitions(X[[c]], fs.FUZZY_SETS.t1, n_partitions=k)[0]
                 for c, k in zip(X.columns, (3, 3, 5, 5), strict=True)]
    n_rules, n_ants = 5, 2
    problem = FitRuleBase(X.to_numpy(), y, nRules=n_rules, nAnts=n_ants, n_classes=2, linguistic_variables=variables)
    term_genes = np.asarray(problem.xu)[n_rules * n_ants: 2 * n_rules * n_ants]
    return int(term_genes.max()) == 4


@lru_cache(maxsize=1)
def has_proportional_term_remap() -> bool:
    """Whether a term gene is mapped proportionally onto the terms of its variable (PR 35), not clipped.

    Variables with (3, 5) terms, one antecedent: the term gene 2 of the feature with 3 terms decodes to term 2 when it
    is clipped (3.3.1, PR 32) and to term ``(2 * 3) // 5 = 1`` with the remap. Needs the PR 32 bound (gene up to 4).
    """
    from ex_fuzzy import fuzzy_sets as fs
    from ex_fuzzy import utils
    from ex_fuzzy.evolutionary_fit import FitRuleBase

    if not has_term_bound_fix():
        return False
    rng = np.random.default_rng(0)
    X = pd.DataFrame(rng.random((60, 2)), columns=list("ab"))
    y = (X["a"] > 0.5).astype(int).to_numpy()
    variables = [utils.construct_partitions(X[[c]], fs.FUZZY_SETS.t1, n_partitions=k)[0]
                 for c, k in zip(X.columns, (3, 5), strict=True)]
    problem = FitRuleBase(X.to_numpy(), y, nRules=1, nAnts=1, n_classes=2, linguistic_variables=variables)
    decoded = problem._construct_ruleBase(np.array([0, 2, 0]), fs.FUZZY_SETS.t1)  # feature a, term gene 2, class 0
    return int(decoded.get_rules()[0].antecedents[0]) == 1


_PROBES = {"term_bound_fix": has_term_bound_fix, "unique_antecedents": has_unique_antecedents,
           "breakpoint_partition": has_breakpoint_partition, "proportional_term_remap": has_proportional_term_remap,
           "rule_mixture": has_rule_mixture, "mixture_pruning": has_mixture_pruning,
           "ordinal_conditions": has_ordinal_conditions, "compound_terms": has_compound_terms}


class RuleCondition(NamedTuple):
    """One condition of a rule: input ``feature`` (index), ``operator`` (``is`` | ``at_least`` | ``at_most`` |
    ``any_of``), the ``term`` it refers to (the compound's name for ``any_of``), and ``text`` (the term,
    ``at least <term>``, ``at most <term>`` or the compound's name, as ex_fuzzy prints it)."""

    feature: int
    operator: str
    term: str
    text: str


def rule_conditions(rule, antecedents) -> list[RuleCondition]:
    """The conditions of ``rule`` (an ex_fuzzy ``RuleSimple``) in variable order, without the don't-cares.

    With ex_fuzzy PR 45 this is ``rule.conditions(antecedents)``, so an ordinal code (a term gene beyond the number of
    terms) reads as ``at least`` / ``at most`` and a compound code as ``any_of`` with its name. Without it (3.4.0)
    every antecedent is the term it indexes: both give the same answer for a rule with single terms, which is why
    callers use this instead of indexing the term names.
    """
    if has_ordinal_conditions():
        return [RuleCondition(c.feature, c.operator, str(c.name if c.operator == "any_of" else c.term),
                              _OPERATOR_TEXT[c.operator] + str(c.name if c.operator == "any_of" else c.term))
                for c in rule.conditions(antecedents)]
    names = [v.linguistic_variable_names() for v in antecedents]
    return [RuleCondition(f, "is", str(names[f][int(t)]), str(names[f][int(t)]))
            for f, t in enumerate(rule.antecedents) if t >= 0]


_OPERATOR_TEXT = {"is": "", "at_least": "at least ", "at_most": "at most ", "any_of": ""}


def condition_labels(variable) -> list[str]:
    """Text of every condition code of ``variable``, by code: its terms (3.4.0, or the option off), then, with the
    option on, ``at least <term>`` and ``at most <term>``."""
    names = getattr(variable, "condition_names", variable.linguistic_variable_names)()
    return [str(n) for n in names]


def require(feature: str) -> None:
    """Raise ``ExFuzzyFeatureError`` unless the installed ex_fuzzy has ``feature`` (one of ``FEATURES``)."""
    if feature not in _PROBES:
        raise ValueError(f"unknown ex_fuzzy feature {feature!r}; known: {FEATURES}")
    if not _PROBES[feature]():
        raise ExFuzzyFeatureError(
            f"{feature!r} needs an ex_fuzzy build with {_UPSTREAM[feature]}; the installed one "
            f"({ex_fuzzy.__version__} at {ex_fuzzy.__file__}) does not have it. Experiments that need it run only "
            "with PYTHONPATH=<ex-fuzzy atlas/local-integration worktree>:src "
            "(docs/ml/fx_retrain_with_fixed_exfuzzy.md); the pinned release used for serving must not be asked for it")


def ensure_config(config) -> None:
    """``require`` every feature in ``config.requires_exfuzzy`` (an experiment config field; none by default)."""
    for feature in getattr(config, "requires_exfuzzy", []):
        require(feature)


def provenance_warnings(config) -> list[str]:
    """Manifest warnings for a model fitted on a non-release ex_fuzzy (empty on a PyPI install without a source)."""
    source = getattr(config, "exfuzzy_source", None)
    build = exfuzzy_build()
    if not source and build.commit is None:
        return []
    if not source:  # a git checkout or install without a named source (EXFUZZY_SRC, or the v0.7 commit pins)
        dirty = " (with uncommitted changes)" if build.dirty else ""
        return [f"fitted with ex_fuzzy at git commit {build.commit}{dirty} (exfuzzy_version {build.version}), not the "
                "pinned release (pyproject.toml, docs/reproduce.md)"]
    if build.commit is None:
        commit = "unknown (the imported ex_fuzzy is not a git checkout)"
    else:
        commit = build.commit + (" (worktree with uncommitted changes)" if build.dirty else "")
    return [f"fitted on an unreleased ex_fuzzy build, exfuzzy_source = {source or 'unnamed git checkout'!r} @ {commit} "
            f"(exfuzzy_version {build.version}); rebuild it as in docs/reproduce.md, section 'ex_fuzzy local "
            "integration build'; a release pin will replace it"]


def provenance_hyperparameters(config) -> dict:
    """Entries for ``hyperparameters`` of a manifest: the source and the library actually imported."""
    source = getattr(config, "exfuzzy_source", None)
    if not source:
        return {}
    return {"exfuzzy_source": source, "exfuzzy_module_path": ex_fuzzy.__file__,
            "requires_exfuzzy": list(getattr(config, "requires_exfuzzy", []))}
