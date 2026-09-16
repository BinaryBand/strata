"""Runbook: install Homebrew and core dev tools (node, pipx, uv, openjdk, rust)."""

import os
from pathlib import Path

from strata.core import guard
from strata.core.ports import PlaybookRunner

# The one spelling of where Homebrew lands. install_antigravity imports these
# rather than declaring its own copy; the YAML side still spells the prefix
# itself, which is the remaining half of this duplication.
BREW_PREFIX = Path("/home/linuxbrew/.linuxbrew")
BREW_BIN = BREW_PREFIX / "bin" / "brew"


def check() -> bool:
    """Return True if brew is installed and executable at the Homebrew prefix.

    Not shutil.which("brew"): install_homebrew.yml installs to BREW_PREFIX and
    adds it to no profile and no PATH, so which() answered False on every
    machine where this runbook had already succeeded. The whole play re-ran
    each time, and @guard.requires("package_managers.install_homebrew") never
    short-circuited. tests/integration/test_runbooks_container.py was already
    probing the right thing with `test -x`, which is what this now mirrors.
    """
    return BREW_BIN.is_file() and os.access(BREW_BIN, os.X_OK)


@guard.alias("install Homebrew")
@guard.prerequisite("sudo_password")
def main(target: str | None = None, *, runner: PlaybookRunner) -> int:
    """Install Homebrew and core dev tools (node, pipx, uv, openjdk, rust)."""
    return runner.run_playbook("playbooks/install_homebrew.yml", target=target)
