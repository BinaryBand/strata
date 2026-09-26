"""Runbook: initialize a Restic repository for backing up server app data.

Restic isn't a persistent service -- there's nothing to keep running between
backups -- so it runs in a throwaway rootless Podman container as diot: a
build-and-exit run rather than a Quadlet unit.
"""

from pathlib import Path

from strata.core import guard
from strata.core.ports import PlaybookRunner, SecretReader
from strata.core.remote_paths import resolve


def check(secrets: SecretReader) -> bool:
    """Return True if the vaulted Restic repository is already initialized.

    A Restic repository writes a `config` file at its root on init, so its
    presence is a cheap proxy for "already initialized" without spinning up
    the throwaway podman container the playbook uses to check.

    `secrets` is supplied by the executor, which injects into check() the same
    way it does into main(). It used to call check() with no arguments, so
    this had to default to None and give up immediately -- meaning
    infrastructure.backup re-ran the whole restic container every time.
    """
    value = secrets.get_secret("restic_repository")
    if not value:
        return False
    return (Path(resolve(value)) / "config").is_file()


@guard.alias("install Restic")
@guard.prerequisite("sudo_password")
# install_podman carries @guard.user("diot"), and the storage guard below
# chowns the repository to diot -- so it has to be satisfied first. Guards
# resolve outermost-first, which makes decorator order load-bearing; this
# sat below the storage guard and asked ensure_path.yml to chown an account
# that did not exist yet, so install_restic could never bootstrap a fresh
# host. test_owned_paths_are_declared_after_the_guard_that_creates_the_owner
# now enforces the ordering that every sibling runbook already followed.
@guard.requires("infrastructure.install_podman")
@guard.secret(
    "restic_password",
    prompt="Restic repository password (blank to generate a random one)",
    generate=True,
)
@guard.storage(
    "restic_repository",
    prompt="Restic repository path or rclone remote (name:subpath)",
    default="/srv/restic",
    owner="diot",
    group="diot",
    mode="2770",
    require_writable=True,
)
def main(target: str | None = None, *, runner: PlaybookRunner) -> int:
    """Initialize the vaulted Restic repository from a throwaway Podman container."""
    # The playbook resolves restic_repository per host itself (vaulted default
    # plus host_vars override), so no resolved path is passed here.
    return runner.run_playbook("playbooks/install_restic.yml", target=target)
