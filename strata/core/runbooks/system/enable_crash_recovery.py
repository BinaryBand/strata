"""Runbook: recover from kernel panics/freezes and keep crash evidence readable."""

from strata.core import guard
from strata.core.ports import PlaybookRunner


@guard.alias("enable crash recovery")
@guard.prerequisite("sudo_password")
def main(target: str | None = None, *, runner: PlaybookRunner) -> int:
    """Configure kernel panic reboots and persistent journald crash logs."""
    return runner.run_playbook("playbooks/enable_crash_recovery.yml", target=target)
