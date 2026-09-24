"""Runbook: a read-only monitor of everything the AnythingLLM agent can see, on its own port.

It shows what reaches the model -- prompts, chats, job prompts, run output,
tool schemas, documents, memories and every file in the agent's folder -- and
keeps what only the server sees in parts marked Admin only. Credentials never
leave it: settings show as "set", secret files as a fingerprint, and a key
check names where a stored key turns up in the agent's reach. Only the tailnet
user logged in on the controller when this runs may open it: the monitor
listens on a Unix socket, not a port, and `tailscale serve` stamps each request
with the viewer's login, which the monitor checks. It is served at the root of
`server_apps_defaults.anythingllm.review_port`, a separate origin from the site.
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
    """Install the /review monitor and serve it on its own tailnet port."""
    return runner.run_playbook(
        "playbooks/enable_anythingllm_review.yml",
        extravars={"anythingllm_root": _ROOT},
        target=target,
    )
