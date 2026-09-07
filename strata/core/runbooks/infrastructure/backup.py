"""Runbook: back up server app data to the Restic repository, tagged per app.

Each app declares its own backup location with @guard.backup_tag on its install
runbook; this runbook discovers them by importing sibling modules under
strata.core.runbooks.services.  Scope can be narrowed with
`strata runbook infrastructure.backup --tags baikal,jellyfin` or left unset to
back up every app.
"""

import importlib
import pkgutil

from strata.core import guard, paths
from strata.core.ports import PlaybookRunner
from strata.core.runbooks import services

# Operator-owned repo config: host_vars, group_vars (including the vaulted
# secrets), and hosts.ini. Always backed up under a static tag, as root rather
# than diot. The path only exists on the controller (ansible_connection=local);
# the playbook skips the tag on hosts where it's absent.
_CONFIG_TAG = "config"
_CONFIG_PATH = str(paths.INVENTORY_DIR)


def _discover_backup_paths() -> dict[str, str]:
    """Import every services runbook so its backup_tag declarations register."""
    for module in pkgutil.iter_modules(services.__path__):
        importlib.import_module(f"strata.core.runbooks.services.{module.name}")
    return guard.backup_paths()


def selected_backup_paths(tags: list[str] | None) -> dict[str, str]:
    """Resolve a --tags selection (or None for everything) to tag -> path.

    Shared with infrastructure.restore, which writes snapshots back into the
    same per-app paths this runbook reads them from.  The static config tag is
    always included, whatever the selection.
    """
    backup_paths = _discover_backup_paths()
    selected = tags or sorted(backup_paths)
    unknown = sorted(set(selected) - set(backup_paths) - {_CONFIG_TAG})
    if unknown:
        msg = f"Unknown backup tag(s): {unknown}. Known: {sorted(backup_paths)}"
        raise ValueError(msg)
    chosen = {tag: backup_paths[tag] for tag in selected if tag != _CONFIG_TAG}
    chosen[_CONFIG_TAG] = _CONFIG_PATH
    return chosen


@guard.alias("back up app data")
@guard.prerequisite("sudo_password")
@guard.requires("infrastructure.install_restic")
def main(
    target: str | None = None,
    tags: list[str] | None = None,
    *,
    runner: PlaybookRunner,
) -> int:
    """Snapshot the selected app data directories into the Restic repository.

    Args:
        target: Inventory host to back up; None uses the last selected target.
        tags: Backup tags to include; None backs up every registered app. The
            static `config` tag is always added on top of the selection.
        runner: Playbook runner supplied by the executor.

    Returns:
        The backup playbook's exit code.
    """
    # The restic repository is resolved per host inside the playbook (vaulted
    # default plus host_vars override), so no repository path is passed here.
    return runner.run_playbook(
        "playbooks/backup.yml",
        extravars={"backup_paths": selected_backup_paths(tags)},
        target=target,
    )
