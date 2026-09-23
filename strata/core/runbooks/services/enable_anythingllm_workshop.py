"""Runbook: install the strata-workshop skill, which drafts customizations from chat.

The skill lets AnythingLLM's agent draft custom skills, Agent Flows, MCP servers
and workspace prompts from the chat window. Every draft is shown on an approval
card, and skills and flows are held in a form AnythingLLM cannot load until the
user switches them on in the settings UI. The skill's source is
ansible/playbooks/files/strata-workshop/, so what runs in the container is what
was reviewed in this repository.
"""

from strata.core import guard
from strata.core.ports import PlaybookRunner
from strata.core.runbooks.services.install_anythingllm import STORAGE_DIR


@guard.alias("enable AnythingLLM workshop")
@guard.prerequisite("sudo_password")
@guard.requires("services.install_anythingllm")
def main(target: str | None = None, *, runner: PlaybookRunner) -> int:
    """Copy the strata-workshop skill into AnythingLLM's agent-skills folder."""
    return runner.run_playbook(
        "playbooks/enable_anythingllm_workshop.yml",
        extravars={"anythingllm_storage_dir": STORAGE_DIR},
        target=target,
    )
