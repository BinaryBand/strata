"""Runbook: install Flatpak and add the Flathub remote."""

import shutil

from strata.core import guard
from strata.core.ports import PlaybookRunner


def check() -> bool:
    """Return True if the flatpak binary is already on PATH."""
    return shutil.which("flatpak") is not None


@guard.alias("install Flatpak")
@guard.controller_only("Flatpak here exists to install desktop applications on the workstation.")
@guard.prerequisite("sudo_password")
def main(target: str | None = None, *, runner: PlaybookRunner) -> int:
    """Install Flatpak and register the Flathub remote."""
    return runner.run_playbook("playbooks/install_flatpak.yml", target=target)
