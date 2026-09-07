"""Runbook: copy registered rclone remote credentials onto a target host.

Credential sync only -- unlike infrastructure.enable_rclone (local-only,
mounts under diot), this works on any inventory host, including a plain SSH
device like nas, so plain `rclone` commands work there too.
"""

from strata.core import guard
from strata.core.ports import PlaybookRunner


@guard.alias("sync rclone credentials")
@guard.prerequisite("sudo_password")
def main(target: str | None = None, *, runner: PlaybookRunner) -> int:
    """Copy every remote registered with `strata rclone sync add` onto target's rclone.conf."""
    return runner.run_playbook("playbooks/sync_rclone_remote.yml", target=target)
