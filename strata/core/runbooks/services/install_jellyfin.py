"""Runbook: deploy Jellyfin as a rootless Podman container owned by diot."""

from strata.core import guard
from strata.core.ports import PlaybookRunner
from strata.core.remote_paths import remote_name, resolve

_MEDIA_PATH = "pcloud:Media"


# The media library lives on the pcloud rclone mount, not here -- only
# Jellyfin's local config/state is backed up.
@guard.alias("install Jellyfin")
@guard.backup_tag("jellyfin", "/srv/jellyfin/config")
@guard.prerequisite("sudo_password")
@guard.requires("infrastructure.install_podman")
@guard.path("/srv/jellyfin/config", owner="diot", group="jellyfin", mode="2770")
@guard.path("/srv/jellyfin/cache", owner="diot", group="jellyfin", mode="2770")
@guard.mount(_MEDIA_PATH)
def main(target: str | None = None, *, runner: PlaybookRunner) -> int:
    """Deploy the Jellyfin container, wiring it to the pcloud media mount unit."""
    remote = remote_name(_MEDIA_PATH)
    return runner.run_playbook(
        "playbooks/install_jellyfin.yml",
        extravars={
            "jellyfin_media_dir": resolve(_MEDIA_PATH),
            "jellyfin_rclone_unit": f"rclone-{remote}.service",
        },
        target=target,
    )
