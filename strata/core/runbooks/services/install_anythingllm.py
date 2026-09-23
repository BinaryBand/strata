"""Runbook: deploy AnythingLLM as a rootless Podman container owned by diot.

The container is provisioned headlessly; the admin account, the LLM provider
and its API keys are all set through AnythingLLM's own onboarding on first
visit. Those keys land in the storage directory this runbook provisions, which
is why it is mapped to diot rather than left world-writable.
"""

from strata.core import guard
from strata.core.ports import PlaybookRunner

# The one spelling of AnythingLLM's storage root. The guard below provisions
# it, the playbook binds it into the container, and it learns the root as an
# extravar rather than repeating the literal in its own `vars:` block.
STORAGE_DIR = "/srv/anythingllm/storage"


@guard.alias("install AnythingLLM")
@guard.backup_tag("anythingllm", STORAGE_DIR)
@guard.prerequisite("sudo_password")
@guard.requires("infrastructure.install_podman")
# The container publishes on loopback only; `tailscale serve` is the one path
# in from another device, so the tailnet is part of the install.
@guard.requires("infrastructure.enable_tailscale")
# Baikal maps its container's internal user onto a subordinate host UID and
# opens the volume to 2777 so that user can write. AnythingLLM's storage holds
# the LLM provider API keys entered during onboarding, so the unit pins
# UserNS=keep-id onto the image's uid/gid 1000 instead: the container writes as
# diot, and the directory stays closed to everyone outside the group.
@guard.path(STORAGE_DIR, owner="diot", group="anythingllm", mode="2770")
def main(target: str | None = None, *, runner: PlaybookRunner) -> int:
    """Stand up the AnythingLLM container and its storage volume."""
    return runner.run_playbook(
        "playbooks/install_anythingllm.yml",
        extravars={"anythingllm_storage_dir": STORAGE_DIR},
        target=target,
    )
