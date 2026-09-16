"""A runbook's check() must answer the same question its playbook answers.

`check()` is an optimisation: a True skips the run. That makes a check which
answers a *cheaper, different* question worse than no check at all, and three
of them did.

`install_homebrew` and `install_antigravity` both asked `shutil.which`, but
their playbooks install into /home/linuxbrew/.linuxbrew and put it on no PATH,
so both answered False forever on machines where they had already succeeded --
re-running the play every time and never letting `@guard.requires` short
circuit. `install_from_git` asked `all([])` over an empty git_apps.toml and
answered True everywhere, including machines it had never touched.

Runbooks are exempt from the mirror-test rule (MIRROR_EXEMPT_DIRS), so this is
a collective module like test_guard_completeness.py rather than one file per
runbook under tests/unit/.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from strata.core.runbooks.development import install_antigravity
from strata.core.runbooks.package_managers import install_homebrew
from strata.core.runbooks.services import install_from_git


def _executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)
    return path


# ── install_homebrew ───────────────────────────────────────────────────────


def test_homebrew_check_is_false_when_the_prefix_holds_no_brew(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(install_homebrew, "BREW_BIN", tmp_path / "bin" / "brew")
    assert install_homebrew.check() is False


def test_homebrew_check_does_not_depend_on_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The binary is never added to PATH, which is why which() was the wrong probe."""
    monkeypatch.setattr(install_homebrew, "BREW_BIN", _executable(tmp_path / "bin" / "brew"))
    monkeypatch.setattr(shutil, "which", lambda *_a, **_kw: None)
    assert install_homebrew.check() is True


# ── install_antigravity ────────────────────────────────────────────────────


def test_antigravity_check_is_false_when_the_binary_is_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(install_antigravity, "BREW_PREFIX", tmp_path)
    assert install_antigravity.check() is False


def test_antigravity_check_does_not_depend_on_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Same prefix as brew, so the same reasoning: PATH says nothing about it."""
    _executable(tmp_path / "bin" / "antigravity")
    monkeypatch.setattr(install_antigravity, "BREW_PREFIX", tmp_path)
    monkeypatch.setattr(shutil, "which", lambda *_a, **_kw: None)
    assert install_antigravity.check() is True


def test_antigravity_reads_the_prefix_homebrew_owns() -> None:
    """One spelling of the Homebrew prefix, on the runbook that installs it."""
    assert install_antigravity.BREW_PREFIX is install_homebrew.BREW_PREFIX


# ── install_from_git ───────────────────────────────────────────────────────


def test_install_from_git_is_not_installed_when_no_apps_are_listed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """all([]) reported this runbook installed on machines it had never run on."""
    monkeypatch.setattr(install_from_git, "_load_apps", list)
    assert install_from_git.check() is False


def test_install_from_git_is_installed_when_every_listed_app_is_on_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(install_from_git, "_load_apps", lambda: [{"name": "tool", "repo": "/x"}])
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    assert install_from_git.check() is True


def test_install_from_git_is_not_installed_when_one_app_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        install_from_git,
        "_load_apps",
        lambda: [{"name": "here", "repo": "/x"}, {"name": "gone", "repo": "/y"}],
    )
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/here" if name == "here" else None)
    assert install_from_git.check() is False
