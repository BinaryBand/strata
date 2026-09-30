"""Unit tests for requirement declaration.

Guards only record data here; the executor that acts on it is tested in
tests/unit/adapters/test_guard_executor.py.
"""

from __future__ import annotations

from types import ModuleType

import pytest

from strata.core import discovery, guard
from strata.core import requirements as req
from strata.core.runbooks.infrastructure import backup


def _plain() -> int:
    return 0


def test_backup_tag_records_the_pair_without_wrapping() -> None:
    decorated = guard.backup_tag("app", "/srv/app")(_plain)
    assert decorated is _plain
    assert guard.backup_tags_of(_plain) == (("app", "/srv/app"),)


def test_backup_tags_accumulate_in_decorator_order() -> None:
    def fn() -> int:
        return 0

    guard.backup_tag("second", "/srv/two")(fn)
    guard.backup_tag("third", "/srv/three")(fn)
    assert guard.backup_tags_of(fn) == (("second", "/srv/two"), ("third", "/srv/three"))


def test_a_function_with_no_backup_tag_declares_none() -> None:
    assert guard.backup_tags_of(lambda: 0) == ()


def test_requires_declares_the_upstream_and_nothing_else() -> None:
    def fn() -> int:
        return 0

    guard.requires("infrastructure.install_podman")(fn)
    assert guard.declared(fn) == [req.UpstreamRunbook("infrastructure.install_podman")]


def test_backup_discovery_collects_server_app_tags() -> None:
    paths = backup._discover_backup_paths()
    assert {"baikal", "jellyfin"} <= set(paths)
    assert all(path.startswith("/srv/") for path in paths.values())


def test_backup_refuses_while_a_runbook_fails_to_load(monkeypatch: pytest.MonkeyPatch) -> None:
    """A tag missing because its runbook did not load must not pass for a complete backup."""
    real_import = discovery.importlib.import_module

    def flaky(name: str, package: str | None = None) -> ModuleType:
        if name.endswith(".install_antigravity"):
            msg = "boom"
            raise ImportError(msg)
        return real_import(name, package)

    monkeypatch.setattr(discovery.importlib, "import_module", flaky)
    with pytest.raises(ValueError, match=r"development\.install_antigravity"):
        backup.validate_tags(None)
