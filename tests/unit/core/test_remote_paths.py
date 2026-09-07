"""Unit tests for strata.core.remote_paths (pure string translation)."""

from __future__ import annotations

import pytest

from strata.core import remote_paths

# ── is_remote_path() ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "pcloud:",
        "pcloud:Media",
        "pcloud:Media/Movies",
        "my-remote:x",
        "my_remote:x",
        "R2:bucket",
    ],
)
def test_is_remote_path_true(path: str) -> None:
    assert remote_paths.is_remote_path(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "/srv/jellyfin",
        "relative/path",
        "",
        ":no-remote-name",
        "has space:sub",
        "has.dot:sub",
        "/mnt/rclone/pcloud/Media",
    ],
)
def test_is_remote_path_false(path: str) -> None:
    assert remote_paths.is_remote_path(path) is False


def test_windows_style_drive_letter_is_treated_as_remote() -> None:
    """Documented consequence of the regex: a single-letter prefix matches."""
    assert remote_paths.is_remote_path("C:/Users") is True


# ── remote_name() ─────────────────────────────────────────────────────


def test_remote_name_of_remote_path() -> None:
    assert remote_paths.remote_name("pcloud:Media/Movies") == "pcloud"


def test_remote_name_of_bare_remote() -> None:
    assert remote_paths.remote_name("pcloud:") == "pcloud"


def test_remote_name_of_local_path_returns_path() -> None:
    assert remote_paths.remote_name("/srv/jellyfin") == "/srv/jellyfin"


def test_remote_name_splits_on_first_colon_only() -> None:
    assert remote_paths.remote_name("pcloud:a:b") == "pcloud"


# ── mount_root() ──────────────────────────────────────────────────────


def test_mount_root_is_under_the_mount_base() -> None:
    assert remote_paths.mount_root("pcloud") == "/mnt/rclone/pcloud"
    assert remote_paths.mount_root("pcloud").startswith(remote_paths.REMOTE_MOUNT_BASE + "/")


# ── resolve() ─────────────────────────────────────────────────────────


def test_resolve_remote_with_subpath() -> None:
    assert remote_paths.resolve("pcloud:Media/Movies") == "/mnt/rclone/pcloud/Media/Movies"


def test_resolve_bare_remote_has_no_trailing_slash() -> None:
    assert remote_paths.resolve("pcloud:") == "/mnt/rclone/pcloud"


def test_resolve_strips_leading_slashes_from_subpath() -> None:
    assert remote_paths.resolve("pcloud:/Media") == "/mnt/rclone/pcloud/Media"
    assert remote_paths.resolve("pcloud:///Media") == "/mnt/rclone/pcloud/Media"


def test_resolve_preserves_interior_and_trailing_slashes() -> None:
    assert remote_paths.resolve("pcloud:Media/Movies/") == "/mnt/rclone/pcloud/Media/Movies/"


@pytest.mark.parametrize("path", ["/srv/jellyfin", "relative/dir", "", "/mnt/rclone/pcloud"])
def test_resolve_local_paths_pass_through_unchanged(path: str) -> None:
    assert remote_paths.resolve(path) == path


def test_resolve_is_idempotent_on_an_already_resolved_path() -> None:
    once = remote_paths.resolve("pcloud:Media")
    assert remote_paths.resolve(once) == once


def test_resolve_uses_the_remote_name_and_mount_root_consistently() -> None:
    path = "backup:restic/repo"
    assert remote_paths.resolve(path).startswith(
        remote_paths.mount_root(remote_paths.remote_name(path))
    )
