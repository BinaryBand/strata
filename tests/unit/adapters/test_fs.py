"""Unit tests for strata.adapters.fs.

The point of the module is what is *not* observable: no reader ever sees a
truncated file. These cover the properties that guarantee it -- the target is
only ever replaced wholesale, the temporary lands on the same filesystem so
os.replace stays atomic, nothing is left behind, and a rewrite does not
quietly change the file's mode.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from strata.adapters import fs


def test_write_text_creates_the_file(tmp_path: Path) -> None:
    target = tmp_path / "new.txt"
    fs.write_text(target, "hello\n")
    assert target.read_text() == "hello\n"


def test_write_text_creates_missing_parent_directories(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "new.txt"
    fs.write_text(target, "hello\n")
    assert target.read_text() == "hello\n"


def test_write_text_replaces_existing_content_entirely(tmp_path: Path) -> None:
    target = tmp_path / "existing.txt"
    target.write_text("old and much longer content\n")

    fs.write_text(target, "new\n")
    assert target.read_text() == "new\n"


def test_write_text_leaves_no_temporary_behind(tmp_path: Path) -> None:
    target = tmp_path / "f.txt"
    fs.write_text(target, "x")
    assert [p.name for p in tmp_path.iterdir()] == ["f.txt"]


def test_a_failed_write_leaves_the_original_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point: an interrupted write must not destroy the old file.

    Path.write_text truncates first, so the same interruption there leaves an
    empty file -- and for the vault secrets file that is the only copy of
    every credential.
    """
    target = tmp_path / "precious.txt"
    target.write_text("original\n")

    def boom(*_args: object, **_kwargs: object) -> None:
        msg = "disk full"
        raise OSError(msg)

    monkeypatch.setattr(Path, "replace", boom)

    with pytest.raises(OSError, match="disk full"):
        fs.write_text(target, "replacement\n")

    assert target.read_text() == "original\n"
    assert [p.name for p in tmp_path.iterdir()] == ["precious.txt"]


def test_write_text_preserves_the_mode_of_an_existing_file(tmp_path: Path) -> None:
    """NamedTemporaryFile is 0600, so a rewrite would otherwise tighten it."""
    target = tmp_path / "hosts.ini"
    target.write_text("old\n")
    target.chmod(0o644)

    fs.write_text(target, "new\n")
    assert target.stat().st_mode & 0o777 == 0o644


def test_a_new_file_gets_ordinary_create_permissions(tmp_path: Path) -> None:
    target = tmp_path / "fresh.txt"
    fs.write_text(target, "x")

    umask = os.umask(0)
    os.umask(umask)
    assert target.stat().st_mode & 0o777 == 0o666 & ~umask


def test_the_temporary_is_created_beside_the_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """os.replace is only atomic within one filesystem, and /tmp is often another."""
    target = tmp_path / "sub" / "f.txt"
    seen: list[Path] = []
    real_replace = Path.replace

    def spy(self: Path, dst: Path) -> Path:
        seen.append(self)
        return real_replace(self, dst)

    monkeypatch.setattr(Path, "replace", spy)
    fs.write_text(target, "x")

    assert seen[0].parent == target.parent
