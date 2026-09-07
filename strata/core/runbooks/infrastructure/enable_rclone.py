"""Runbook: mount the configured rclone remotes under diot."""

from strata.core import guard
from strata.core.ports import PlaybookRunner


@guard.alias("enable rclone mounts")
@guard.prerequisite("sudo_password")
@guard.user("diot", "playbooks/create_diot_user.yml")
def main(target: str | None = None, *, runner: PlaybookRunner) -> int:
    """Mount every registered rclone remote as diot, creating diot if absent.

    Read-only unless the remote was registered with `--writable`.
    """
    return runner.run_playbook("playbooks/enable_rclone.yml", target=target)
