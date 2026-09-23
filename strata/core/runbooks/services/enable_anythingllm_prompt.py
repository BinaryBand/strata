"""Runbook: give AnythingLLM a default system prompt describing this host.

The prompt tells the agent what strata set up around it -- the tailnet site
folder, the strata-workshop skill -- in conditional wording, so it stays true
on a host where either is missing. It is written as AnythingLLM's default
system prompt and into every workspace whose prompt is still untouched. A
prompt edited in AnythingLLM's settings is left alone from then on.
"""

from strata.core import guard
from strata.core.ports import PlaybookRunner


@guard.alias("enable AnythingLLM prompt")
@guard.prerequisite("sudo_password")
@guard.requires("services.install_anythingllm")
# The API that sets prompts needs a login; the password is the one
# install_anythingllm vaulted and wrote into AnythingLLM's settings.
@guard.secret(
    "anythingllm_password",
    prompt="AnythingLLM login password (blank to generate one)",
    generate=True,
)
def main(target: str | None = None, *, runner: PlaybookRunner) -> int:
    """Write the default system prompt and update untouched workspaces."""
    return runner.run_playbook("playbooks/enable_anythingllm_prompt.yml", target=target)
