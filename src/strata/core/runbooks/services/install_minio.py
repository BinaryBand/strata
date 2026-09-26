"""Runbook: deploy MinIO as a rootless Podman container owned by diot."""

from strata.core import guard
from strata.core.ports import PlaybookRunner

# The one spelling of MinIO's data root. The guard below provisions it, the
# playbook binds it into the container, and it learns the root as an extravar
# rather than repeating the literal in its own `vars:` block.
_DATA_DIR = "/srv/minio/data"


@guard.alias("install MinIO")
@guard.backup_tag("minio", _DATA_DIR)
@guard.prerequisite("sudo_password")
@guard.requires("infrastructure.install_podman")
# Unlike Baikal/Jellyfin's non-root internal users, MinIO's container runs as
# root, which rootless Podman maps to the invoking diot user by default -- no
# Baikal-style 2777 workaround needed for the container to write here.
@guard.path(_DATA_DIR, owner="diot", group="minio", mode="2770")
@guard.secret(
    "minio_root_user",
    kind="text",
    prompt="MinIO root username",
    default="admin",
)
@guard.secret(
    "minio_root_password",
    prompt="MinIO root password",
    generate=True,
)
def main(target: str | None = None, *, runner: PlaybookRunner) -> int:
    """Stand up the MinIO container and its data volume."""
    return runner.run_playbook(
        "playbooks/install_minio.yml",
        extravars={"minio_data_dir": _DATA_DIR},
        target=target,
    )
