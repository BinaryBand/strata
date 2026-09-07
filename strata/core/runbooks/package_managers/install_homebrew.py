"""Runbook: install Homebrew and core dev tools (node, pipx, uv, openjdk, rust)."""

import shutil

from strata.core import guard
from strata.core.ports import PlaybookRunner


def check() -> bool:
    """Return True if the brew binary is already on PATH."""
    return shutil.which("brew") is not None


@guard.alias("install Homebrew")
@guard.prerequisite("sudo_password")
def main(target: str | None = None, *, runner: PlaybookRunner) -> int:
    """Install Homebrew and core dev tools (node, pipx, uv, openjdk, rust)."""
    return runner.run_playbook("playbooks/install_homebrew.yml", target=target)
