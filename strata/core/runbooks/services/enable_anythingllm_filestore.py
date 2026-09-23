"""Runbook: give AnythingLLM's agent a filesystem MCP server over one folder.

The folder sits inside AnythingLLM's storage directory, which the container
already binds at /app/server/storage, so no unit change is needed and the
anythingllm backup tag already covers it. The MCP server is passed only that
folder as its allowed directory and refuses paths outside it, which keeps the
sibling .env holding the provider API keys out of the agent's reach.
"""

from strata.core import guard
from strata.core.ports import PlaybookRunner
from strata.core.runbooks.services.install_anythingllm import STORAGE_DIR

_FILESTORE_DIR = f"{STORAGE_DIR}/files"


@guard.alias("enable AnythingLLM filestore")
@guard.prerequisite("sudo_password")
@guard.requires("services.install_anythingllm")
@guard.path(_FILESTORE_DIR, owner="diot", group="anythingllm", mode="2770")
def main(target: str | None = None, *, runner: PlaybookRunner) -> int:
    """Register the filestore MCP server with AnythingLLM and restart it on change."""
    return runner.run_playbook(
        "playbooks/enable_anythingllm_filestore.yml",
        extravars={
            "anythingllm_storage_dir": STORAGE_DIR,
            "anythingllm_filestore_dir": _FILESTORE_DIR,
        },
        target=target,
    )
