"""Runbook: restore the latest Restic snapshot per tag into each app's data dir.

The inverse of infrastructure.backup: for every selected tag the latest
snapshot is written back into the app's data directory.  Restic overwrites
files that differ but never deletes extras, so stop the app's Quadlet unit
before restoring to avoid it reading half-written state.

The operator's own config -- hosts.ini, host_vars and the vault -- comes back
only with `--tags config`. It used to come back with every restore, so
restoring one app silently undid every device and secret added since that
backup.
"""

from strata.core import guard
from strata.core.ports import PlaybookRunner
from strata.core.runbooks.infrastructure.backup import selected_backup_paths, validate_tags

# Re-exported so dispatch finds the same pre-flight check on this runbook as on
# backup: both take --tags, and both resolve them through selected_backup_paths.
__all__ = ["main", "validate_tags"]


@guard.alias("restore from backup")
@guard.prerequisite("sudo_password")
@guard.requires("infrastructure.install_restic")
def main(
    target: str | None = None,
    tags: list[str] | None = None,
    *,
    runner: PlaybookRunner,
) -> int:
    """Write the latest Restic snapshot per tag back into each app's data directory.

    Args:
        target: Inventory host to restore onto; None uses the last selected target.
        tags: Backup tags to restore; None restores every registered app. The
            static `config` tag is restored only when named here.
        runner: Playbook runner supplied by the executor.

    Returns:
        The restore playbook's exit code.
    """
    return runner.run_playbook(
        "playbooks/restore.yml",
        extravars={"backup_paths": selected_backup_paths(tags, always_config=False)},
        target=target,
    )
