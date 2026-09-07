"""Runbook: enable automatic security updates via unattended-upgrades."""

from strata.core import guard
from strata.core.ports import PlaybookRunner


@guard.alias("enable security autoupdates")
@guard.prerequisite("sudo_password")
def main(target: str | None = None, *, runner: PlaybookRunner) -> int:
    """Enable unattended-upgrades for the security pocket."""
    return runner.run_playbook("playbooks/enable_security_autoupdates.yml", target=target)
