"""Unit tests for requirement declaration.

Guards only record data here; the executor that acts on it is tested in
tests/unit/adapters/test_guard_executor.py.
"""

from __future__ import annotations

import pytest

from strata.core import guard
from strata.core.runbooks.infrastructure import backup


def test_backup_tag_registers_mapping_without_wrapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(guard, "_backup_paths", {})

    def fn(_target: str | None = None) -> int:
        return 0

    decorated = guard.backup_tag("app", "/srv/app")(fn)
    assert decorated is fn
    assert guard.backup_paths() == {"app": "/srv/app"}


def test_backup_tag_same_path_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-imports must be able to re-register the same mapping harmlessly."""
    monkeypatch.setattr(guard, "_backup_paths", {"app": "/srv/app"})
    guard.backup_tag("app", "/srv/app")(lambda: 0)
    assert guard.backup_paths() == {"app": "/srv/app"}


def test_backup_tag_conflicting_path_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guard, "_backup_paths", {"app": "/srv/app"})
    with pytest.raises(ValueError, match="already registered"):
        guard.backup_tag("app", "/srv/elsewhere")(lambda: 0)


def test_backup_discovery_collects_server_app_tags() -> None:
    paths = backup._discover_backup_paths()
    assert {"baikal", "jellyfin"} <= set(paths)
    assert all(path.startswith("/srv/") for path in paths.values())
