"""Runbook: install Podman and the rootless container toolchain for diot."""

import shutil

from strata.core import guard
from strata.core.ports import PlaybookRunner


def check() -> bool:
    """Return True if the podman binary is already on PATH."""
    return shutil.which("podman") is not None


@guard.alias("install Podman")
@guard.prerequisite("sudo_password")
@guard.user("diot", "playbooks/create_diot_user.yml")
def main(target: str | None = None, *, runner: PlaybookRunner) -> int:
    """Install Podman and the rootless toolchain, creating the diot user if absent."""
    return runner.run_playbook("playbooks/install_podman.yml", target=target)
