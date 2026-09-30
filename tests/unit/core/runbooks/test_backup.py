"""The backup tags the runbooks declare, and when they cannot be trusted."""

from __future__ import annotations

from pathlib import Path

import pytest

from strata.core.runbooks.infrastructure import backup
from tests._fakes import fail_import


def _write_spec(apps_dir: Path, name: str, *, tag: str, path: str) -> None:
    (apps_dir / f"{name}.yml").write_text(
        f"name: {name}\nalias: install {name}\ndescription: {name} server\n"
        f"image: docker.io/x/{name}:1\ndirs:\n  - path: {path}\n"
        f"backup:\n  tag: {tag}\n  path: {path}\n"
    )


def test_the_tags_are_the_ones_the_shipped_specs_declare() -> None:
    assert backup.declared_backup_paths() == {
        "baikal": "/srv/baikal",
        "jellyfin": "/srv/jellyfin/config",
        "minio": "/srv/minio/data",
    }


def test_a_tag_declared_for_two_paths_is_refused(apps_dir: Path) -> None:
    _write_spec(apps_dir, "alpha", tag="shared", path="/srv/alpha")
    _write_spec(apps_dir, "beta", tag="shared", path="/srv/beta")
    with pytest.raises(
        ValueError, match="'shared' is declared for '/srv/alpha' and for '/srv/beta'"
    ):
        backup.declared_backup_paths()


def test_a_tag_repeated_for_the_same_path_is_accepted(apps_dir: Path) -> None:
    _write_spec(apps_dir, "alpha", tag="shared", path="/srv/alpha")
    _write_spec(apps_dir, "beta", tag="shared", path="/srv/alpha")
    assert backup.declared_backup_paths() == {"shared": "/srv/alpha"}


def test_backup_refuses_while_a_spec_fails_to_build(apps_dir: Path) -> None:
    _write_spec(apps_dir, "alpha", tag="alpha", path="/srv/alpha")
    (apps_dir / "broken.yml").write_text("name: broken\n")
    with pytest.raises(ValueError, match=r"services\.install_broken: AppSpecError"):
        backup.declared_backup_paths()


def test_backup_refuses_while_a_runbook_module_fails_to_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fail_import(monkeypatch, "development.install_antigravity")
    with pytest.raises(ValueError, match=r"development\.install_antigravity"):
        backup.validate_tags(None)
