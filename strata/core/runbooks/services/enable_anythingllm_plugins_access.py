"""Runbook: let the operator's login account edit AnythingLLM's plugins folder.

Custom skills, agent flows and the MCP config live in storage/plugins. This
grants the account strata connects as read-write ACLs there, and only
traverse on the folders above it, with "other" access stripped from the rest
of storage so traversal cannot reach the chat database or the .env holding the
provider API keys. Skills written this way skip the strata-workshop review.
"""

from strata.core import guard
from strata.core.ports import PlaybookRunner
from strata.core.runbooks.services.install_anythingllm import STORAGE_DIR


@guard.alias("enable AnythingLLM plugins access")
@guard.prerequisite("sudo_password")
@guard.requires("services.install_anythingllm")
def main(target: str | None = None, *, runner: PlaybookRunner) -> int:
    """Grant the connecting account read-write access to storage/plugins."""
    return runner.run_playbook(
        "playbooks/enable_anythingllm_plugins_access.yml",
        extravars={"anythingllm_storage_dir": STORAGE_DIR},
        target=target,
    )
