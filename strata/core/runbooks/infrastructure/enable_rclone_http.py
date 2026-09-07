"""Runbook: serve registered rclone paths over local HTTP via `rclone serve http`.

Each entry in rclone_http_serves (`strata rclone serve <name> <path> --port
<port>`) becomes a diot systemd --user service bound to 127.0.0.1, so the
content can be fronted publicly without an rclone FUSE mount in the loop --
`rclone serve http` reads straight from the remote, with VFS caching so
repeat reads don't re-fetch from the cloud backend.
"""

from strata.core import guard
from strata.core.ports import PlaybookRunner


@guard.alias("enable rclone HTTP serve")
@guard.prerequisite("sudo_password")
@guard.requires("infrastructure.enable_rclone")
def main(target: str | None = None, *, runner: PlaybookRunner) -> int:
    """Start a diot --user `rclone serve http` unit per registered serve entry."""
    return runner.run_playbook("playbooks/enable_rclone_http.yml", target=target)
