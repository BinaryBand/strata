"""Runbook: deploy Baikal CalDAV/CardDAV as a rootless Podman container owned by diot.

The container is provisioned headlessly, but admin and user accounts are created
through Baikal's own web installer on first visit -- this runbook only stands up
the service and its data volumes.
"""

from strata.core import guard
from strata.core.ports import PlaybookRunner


@guard.alias("install Baïkal")
@guard.backup_tag("baikal", "/srv/baikal")
@guard.prerequisite("sudo_password")
@guard.requires("infrastructure.install_podman")
@guard.path("/srv/baikal", owner="diot", group="baikal", mode="2770")
# Rootless Podman maps the container's www-data (UID 33) to a subordinate host
# UID that is neither diot nor in the baikal group. Mode 2777 is a pragmatic
# workaround: it lets the container's internal user write to these volumes while
# the setgid bit keeps the baikal group on new files.
@guard.path("/srv/baikal/config", owner="diot", group="baikal", mode="2777")
@guard.path("/srv/baikal/Specific", owner="diot", group="baikal", mode="2777")
def main(target: str | None = None, *, runner: PlaybookRunner) -> int:
    """Stand up the Baikal container and its /srv/baikal data volumes."""
    return runner.run_playbook("playbooks/install_baikal.yml", target=target)
