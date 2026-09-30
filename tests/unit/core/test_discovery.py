"""Unit tests for strata.core.discovery.

These run against the real runbook package rather than a synthetic one -- the
value of the module is that it finds the actual runbooks, and a fixture package
would only re-test pkgutil.
"""

from __future__ import annotations

import dataclasses
import pkgutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

from strata.core import discovery, paths
from tests._fakes import fail_import

# A runbook that must exist for the dependency chain documented in docs/ARCHITECTURE.md
# to work at all; if it is renamed these tests should be updated deliberately.
_KNOWN_DOTTED = "services.install_jellyfin"
_KNOWN_LEAF = "install_jellyfin"
# A runbook that is a module file, for the tests that break its import.
_FILE_DOTTED = "development.install_antigravity"


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
        assert callable(discovery.load(info.dotted_name).main)


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
    fail_import(monkeypatch, _FILE_DOTTED)

    names = {r.dotted_name for r in discovery.iter_runbooks()}
    assert _FILE_DOTTED not in names
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


# ── runbooks built from app specs ─────────────────────────────────────


def test_an_app_spec_is_listed_as_a_runbook_with_its_alias(
    runbooks: list[discovery.RunbookInfo],
) -> None:
    info = next(r for r in runbooks if r.dotted_name == _KNOWN_DOTTED)
    assert (info.leaf, info.category, info.alias) == (_KNOWN_LEAF, "services", "install Jellyfin")
    assert info.summary.startswith("deploy Jellyfin")


def test_load_returns_the_module_built_from_the_spec() -> None:
    module = discovery.load(_KNOWN_DOTTED)
    assert callable(module.main)
    assert discovery.load(_KNOWN_DOTTED) is module


_SHIPPED_APPS = paths.APPS_DIR


def _copy_spec(apps_dir: Path, name: str) -> None:
    (apps_dir / f"{name}.yml").write_text((_SHIPPED_APPS / f"{name}.yml").read_text())


def test_a_bad_spec_is_reported_and_the_others_still_load(apps_dir: Path) -> None:
    _copy_spec(apps_dir, "baikal")
    (apps_dir / "broken.yml").write_text("name: broken\n")

    services = {r.dotted_name for r in discovery.iter_runbooks() if r.category == "services"}
    failures = {f.dotted_name: f.error for f in discovery.import_failures()}

    assert services == {"services.install_baikal"}
    assert "AppSpecError" in failures["services.install_broken"]
    assert "broken.yml" in failures["services.install_broken"]


def test_a_spec_that_repeats_a_runbook_module_is_reported(
    apps_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _copy_spec(apps_dir, "baikal")
    twin = ModuleType("strata.core.runbooks.services.install_baikal")
    twin.main = lambda: 0  # ty: ignore[unresolved-attribute]
    monkeypatch.setitem(sys.modules, "strata.core.runbooks.services.install_baikal", twin)
    real_walk = pkgutil.walk_packages
    yielded_twin = False

    def walk_with_twin(*args: object, **kwargs: object) -> object:
        # walk_packages recurses through this name, so offer the twin only once.
        nonlocal yielded_twin
        yield from real_walk(*args, **kwargs)  # ty: ignore[invalid-argument-type]
        if not yielded_twin:
            yielded_twin = True
            yield None, "strata.core.runbooks.services.install_baikal", False

    monkeypatch.setattr(discovery.pkgutil, "walk_packages", walk_with_twin)

    failures = {f.dotted_name: f.error for f in discovery.import_failures()}
    assert "declared by both" in failures["services.install_baikal"]
    listed = [r for r in discovery.iter_runbooks() if r.dotted_name == "services.install_baikal"]
    assert len(listed) == 1
    # The listing describes the module that load() returns: the spec's, not the twin's.
    assert listed[0].summary.startswith("deploy Baikal")
    assert discovery.load("services.install_baikal") is not twin
