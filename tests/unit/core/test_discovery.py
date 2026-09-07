"""Unit tests for strata.core.discovery.

These run against the real runbook package rather than a synthetic one -- the
value of the module is that it finds the actual runbooks, and a fixture package
would only re-test pkgutil.
"""

from __future__ import annotations

import dataclasses
import importlib
import pkgutil
import sys
from types import ModuleType

import pytest

from strata.core import discovery

# A runbook that must exist for the dependency chain documented in docs/ARCHITECTURE.md
# to work at all; if it is renamed these tests should be updated deliberately.
_KNOWN_DOTTED = "services.install_jellyfin"
_KNOWN_LEAF = "install_jellyfin"


@pytest.fixture(scope="module")
def runbooks() -> list[discovery.RunbookInfo]:
    return discovery.iter_runbooks()


# ── iter_runbooks() ───────────────────────────────────────────────────


def test_iter_runbooks_finds_real_runbooks(runbooks: list[discovery.RunbookInfo]) -> None:
    assert runbooks
    assert _KNOWN_DOTTED in {r.dotted_name for r in runbooks}


def test_iter_runbooks_is_sorted_by_dotted_name(runbooks: list[discovery.RunbookInfo]) -> None:
    names = [r.dotted_name for r in runbooks]
    assert names == sorted(names)


def test_iter_runbooks_names_are_unique(runbooks: list[discovery.RunbookInfo]) -> None:
    names = [r.dotted_name for r in runbooks]
    assert len(names) == len(set(names))


def test_leaf_and_category_are_derived_from_the_dotted_name(
    runbooks: list[discovery.RunbookInfo],
) -> None:
    for info in runbooks:
        parts = info.dotted_name.split(".")
        assert info.leaf == parts[-1]
        assert info.category == (parts[-2] if len(parts) > 1 else "")


def test_every_listed_runbook_actually_has_a_main(
    runbooks: list[discovery.RunbookInfo],
) -> None:
    """A helper module under runbooks/ must not be offered as a runbook.

    Replaces a check against the old _EXCLUDE set, which could never match
    anything: it held "discovery", a module that is not in the runbooks
    package at all, so the assertion passed tautologically while modules
    without a main() were listed and then crashed dispatch with a bare
    AttributeError.
    """
    assert runbooks
    for info in runbooks:
        module = importlib.import_module(f"strata.core.runbooks.{info.dotted_name}")
        assert callable(module.main)


def test_a_module_without_main_is_not_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    helper = ModuleType("strata.core.runbooks.services._helper")
    helper.__doc__ = "Not a runbook."
    monkeypatch.setitem(sys.modules, "strata.core.runbooks.services._helper", helper)

    real_walk = pkgutil.walk_packages

    def walk_with_helper(*args: object, **kwargs: object) -> object:
        yield from real_walk(*args, **kwargs)  # ty: ignore[invalid-argument-type]
        yield None, "strata.core.runbooks.services._helper", False

    monkeypatch.setattr(discovery.pkgutil, "walk_packages", walk_with_helper)

    names = {r.dotted_name for r in discovery.iter_runbooks()}
    assert "services._helper" not in names


def test_packages_themselves_are_not_listed(runbooks: list[discovery.RunbookInfo]) -> None:
    """A category package (e.g. "services") must not appear as a runbook."""
    categories = {r.category for r in runbooks if r.category}
    assert categories
    assert categories.isdisjoint({r.dotted_name for r in runbooks})


def test_every_runbook_has_a_docstring_first_line(
    runbooks: list[discovery.RunbookInfo],
) -> None:
    missing = [r.dotted_name for r in runbooks if not r.docstring_first_line]
    assert missing == []


def test_docstring_first_line_is_a_single_line(
    runbooks: list[discovery.RunbookInfo],
) -> None:
    for info in runbooks:
        assert "\n" not in info.docstring_first_line


def test_accepts_tags_matches_the_real_signature(
    runbooks: list[discovery.RunbookInfo],
) -> None:
    """backup/restore take --tags; a plain install runbook does not."""
    by_name = {r.dotted_name: r for r in runbooks}
    assert by_name["infrastructure.backup"].accepts_tags is True
    assert by_name["infrastructure.restore"].accepts_tags is True
    assert by_name[_KNOWN_DOTTED].accepts_tags is False


def test_runbook_info_is_frozen(runbooks: list[discovery.RunbookInfo]) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        runbooks[0].leaf = "nope"  # ty: ignore[invalid-assignment]


def test_an_unimportable_module_is_skipped_not_raised(
    monkeypatch: pytest.MonkeyPatch,
    runbooks: list[discovery.RunbookInfo],
) -> None:
    real_import = discovery.importlib.import_module

    def flaky(name: str, package: str | None = None) -> ModuleType:
        if name.endswith("." + _KNOWN_LEAF):
            msg = "boom"
            raise ImportError(msg)
        return real_import(name, package)

    monkeypatch.setattr(discovery.importlib, "import_module", flaky)

    names = {r.dotted_name for r in discovery.iter_runbooks()}
    assert _KNOWN_DOTTED not in names
    assert len(names) == len(runbooks) - 1


# ── resolve_name() ────────────────────────────────────────────────────


def test_resolve_name_accepts_a_dotted_name() -> None:
    assert discovery.resolve_name(_KNOWN_DOTTED) == _KNOWN_DOTTED


def test_resolve_name_accepts_a_bare_leaf() -> None:
    assert discovery.resolve_name(_KNOWN_LEAF) == _KNOWN_DOTTED


def test_resolve_name_unknown_returns_none() -> None:
    assert discovery.resolve_name("install_nothing_at_all") is None


def test_resolve_name_wrong_category_returns_none() -> None:
    assert discovery.resolve_name("system." + _KNOWN_LEAF) is None


def test_resolve_name_is_case_sensitive() -> None:
    assert discovery.resolve_name(_KNOWN_LEAF.upper()) is None


def test_every_leaf_resolves_back_to_its_own_dotted_name(
    runbooks: list[discovery.RunbookInfo],
) -> None:
    leaves = [r.leaf for r in runbooks]
    for info in runbooks:
        if leaves.count(info.leaf) == 1:
            assert discovery.resolve_name(info.leaf) == info.dotted_name


# ── suggest() ─────────────────────────────────────────────────────────


def test_suggest_returns_close_match_for_a_typo() -> None:
    assert _KNOWN_DOTTED in discovery.suggest("services.install_jellyfn")


def test_suggest_returns_empty_for_gibberish() -> None:
    assert discovery.suggest("zzzzqqqqwwww") == []


def test_suggest_respects_the_limit() -> None:
    assert len(discovery.suggest("install", limit=2)) <= 2


def test_suggest_only_returns_known_runbooks(
    runbooks: list[discovery.RunbookInfo],
) -> None:
    known = {r.dotted_name for r in runbooks}
    assert set(discovery.suggest("services.install_jellyfn")) <= known
