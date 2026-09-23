"""Runbook: publish a folder AnythingLLM's agent can write as a tailnet website.

The folder sits inside the built-in File System skill's root, so the agent
writes the site itself -- a template, a stylesheet, one page per day -- from
chat or from a scheduled job. `tailscale serve` publishes it over HTTPS on its
own port, tailnet-only, so no web server is added and a page there cannot
reach AnythingLLM's login on the other port. A README of house rules is placed
in the folder on first install; the agent follows it and may edit it later.
"""

from strata.core import guard
from strata.core.ports import PlaybookRunner
from strata.core.runbooks.services.install_anythingllm import STORAGE_DIR

# The built-in File System skill's default root is <storage>/anythingllm-fs,
# and the agent names files relative to it, so the site is "site/..." there.
_SITE_DIR = f"{STORAGE_DIR}/anythingllm-fs/site"


@guard.alias("enable AnythingLLM site")
@guard.prerequisite("sudo_password")
@guard.requires("services.install_anythingllm")
@guard.requires("infrastructure.enable_tailscale")
@guard.path(_SITE_DIR, owner="diot", group="anythingllm", mode="2770")
def main(target: str | None = None, *, runner: PlaybookRunner) -> int:
    """Seed the site folder's README and serve the folder to the tailnet."""
    return runner.run_playbook(
        "playbooks/enable_anythingllm_site.yml",
        extravars={"anythingllm_site_dir": _SITE_DIR},
        target=target,
    )
