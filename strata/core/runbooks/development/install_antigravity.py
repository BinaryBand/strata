"""Runbook: install Google Antigravity CLI via the local Homebrew tap."""

import os

from strata.core import guard
from strata.core.ports import PlaybookRunner
from strata.core.runbooks.package_managers.install_homebrew import BREW_PREFIX


def check() -> bool:
    """Return True if antigravity is already installed and executable.

    The PATH half of this used to be `shutil.which("antigravity")`, which had
    the same defect as install_homebrew's own check: antigravity installs into
    the Homebrew prefix, and nothing puts that prefix on PATH, so the check
    could never be True on a machine where the runbook had succeeded.
    """
    binary = BREW_PREFIX / "bin" / "antigravity"
    return binary.is_file() and os.access(binary, os.X_OK)


@guard.alias("install Antigravity")
@guard.controller_only(
    "Antigravity is a desktop application installed from the local Homebrew tap."
)
# The playbook copies the formula into a local tap and installs from it, and
# fails on the first task if brew is missing. This was allowlisted in
# KNOWN_GAPS rather than declared; the allowlist is for debt worth recording,
# not for a one-line dependency.
@guard.requires("package_managers.install_homebrew")
def main(target: str | None = None, *, runner: PlaybookRunner) -> int:
    """Install the antigravity CLI from the local Homebrew tap."""
    return runner.run_playbook("playbooks/install_antigravity.yml", target=target)
