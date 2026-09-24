"""Runbook: full stories for The Daily Seek, written when a headline is first opened.

A small service mounted at /story on the site's tailnet port serves only the
tailnet user logged in on the controller when this runs. On a story's first
open it fetches the story's sources and has a dedicated AnythingLLM workspace
write the story through AnythingLLM's developer API, then caches it. The site
builder is switched to link headlines to /story instead of to the first
source. The API key the service uses is created here and kept in a root-only
file on the host.
"""

from strata.core import guard
from strata.core.ports import PlaybookRunner
from strata.core.runbooks.services.enable_anythingllm_site import _PUBLIC_DIR, _ROOT

# Beside storage, not in it: the agent cannot write the service's code or cache.
_STORY_DIR = f"{_ROOT}/story"
_CACHE_DIR = f"{_ROOT}/story-cache"


@guard.alias("enable AnythingLLM story")
@guard.prerequisite("sudo_password")
@guard.requires("services.enable_anythingllm_site")
@guard.requires("infrastructure.enable_tailscale")
@guard.path(_CACHE_DIR, owner="diot", group="anythingllm", mode="0700")
# Creating the workspace and the API key needs a login; the password is the
# one install_anythingllm vaulted and wrote into AnythingLLM's settings.
@guard.secret(
    "anythingllm_password",
    prompt="AnythingLLM login password (blank to generate one)",
    generate=True,
)
def main(target: str | None = None, *, runner: PlaybookRunner) -> int:
    """Install the /story service and point the site's headlines at it."""
    return runner.run_playbook(
        "playbooks/enable_anythingllm_story.yml",
        extravars={
            "anythingllm_story_dir": _STORY_DIR,
            "anythingllm_story_cache_dir": _CACHE_DIR,
            "anythingllm_site_public_dir": _PUBLIC_DIR,
        },
        target=target,
    )
