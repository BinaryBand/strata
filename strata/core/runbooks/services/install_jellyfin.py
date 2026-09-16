"""Runbook: deploy Jellyfin as a rootless Podman container owned by diot."""

from strata.core import guard
from strata.core.ports import PlaybookRunner
from strata.core.remote_paths import remote_name, resolve

_MEDIA_PATH = "pcloud:Media"

# The one spelling of Jellyfin's data root. The guards below provision these
# paths, the playbook binds them into the container, and it learns them as
# extravars rather than repeating the literals in its own `vars:` block.
_DATA_DIR = "/srv/jellyfin"
_CONFIG_DIR = f"{_DATA_DIR}/config"
_CACHE_DIR = f"{_DATA_DIR}/cache"


# The media library lives on the pcloud rclone mount, not here -- only
# Jellyfin's local config/state is backed up. The cache is reproducible and
# deliberately left out of the tag.
@guard.alias("install Jellyfin")
@guard.backup_tag("jellyfin", _CONFIG_DIR)
@guard.prerequisite("sudo_password")
@guard.requires("infrastructure.install_podman")
@guard.path(_CONFIG_DIR, owner="diot", group="jellyfin", mode="2770")
@guard.path(_CACHE_DIR, owner="diot", group="jellyfin", mode="2770")
@guard.mount(_MEDIA_PATH)
def main(target: str | None = None, *, runner: PlaybookRunner) -> int:
    """Deploy the Jellyfin container, wiring it to the pcloud media mount unit."""
    remote = remote_name(_MEDIA_PATH)
    return runner.run_playbook(
        "playbooks/install_jellyfin.yml",
        extravars={
            "jellyfin_config_dir": _CONFIG_DIR,
            "jellyfin_cache_dir": _CACHE_DIR,
            "jellyfin_media_dir": resolve(_MEDIA_PATH),
            "jellyfin_rclone_unit": f"rclone-{remote}.service",
        },
        target=target,
    )
