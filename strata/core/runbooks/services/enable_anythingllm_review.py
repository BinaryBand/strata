"""Runbook: a read-only admin monitor for AnythingLLM at /review on the site's port.

It shows the data folder's layout, allowlisted non-secret files and status from
the database, rebuilt on a request at most once a minute. Only the tailnet user
logged in on the controller when this runs may open it: the monitor listens on
a Unix socket, not a port, and `tailscale serve` stamps each request with the
viewer's login, which the monitor checks. Secrets -- the settings file, the
database file, signing keys, the MCP config, chat text -- are never shown.
"""

from strata.core import guard
from strata.core.ports import PlaybookRunner
from strata.core.runbooks.services.install_anythingllm import STORAGE_DIR

# The monitor reads everything under the AnythingLLM root, not only storage:
# nginx's config beside it is part of what an admin wants to see.
_ROOT = STORAGE_DIR.rsplit("/", 1)[0]


@guard.alias("enable AnythingLLM review")
@guard.prerequisite("sudo_password")
@guard.requires("services.enable_anythingllm_site")
@guard.requires("infrastructure.enable_tailscale")
def main(target: str | None = None, *, runner: PlaybookRunner) -> int:
    """Install the /review monitor and mount it on the site's tailnet port."""
    return runner.run_playbook(
        "playbooks/enable_anythingllm_review.yml",
        extravars={"anythingllm_root": _ROOT},
        target=target,
    )
