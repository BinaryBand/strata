"""Runbook: install Google Antigravity CLI via the local Homebrew tap."""

import shutil
from pathlib import Path

from strata.core import guard
from strata.core.ports import PlaybookRunner

BREW_PREFIX = Path("/home/linuxbrew/.linuxbrew")


def check() -> bool:
    """Return True if antigravity is already installed and executable."""
    binary = BREW_PREFIX / "bin" / "antigravity"
    return binary.is_file() and shutil.which("antigravity") is not None


@guard.alias("install Antigravity")
@guard.controller_only(
    "Antigravity is a desktop application installed from the local Homebrew tap."
)
# The playbook taps a local repository and installs from it, and fails on the
# first task if brew is missing. This was allowlisted in KNOWN_GAPS rather
# than declared; the allowlist is for debt worth recording, not for a
# one-line dependency.
@guard.requires("package_managers.install_homebrew")
def main(target: str | None = None, *, runner: PlaybookRunner) -> int:
    """Install the antigravity CLI from the local Homebrew tap."""
    return runner.run_playbook("playbooks/install_antigravity.yml", target=target)
