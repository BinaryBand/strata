"""Runbook: install uv, the Python toolchain external projects build and run with."""

from strata.core import guard
from strata.core.ports import PlaybookRunner


@guard.alias("install uv")
@guard.prerequisite("sudo_password")
def main(target: str | None = None, *, runner: PlaybookRunner) -> int:
    """Install a pinned uv release system-wide."""
    return runner.run_playbook("playbooks/install_uv.yml", target=target)
