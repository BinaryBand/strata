"""Runbook: give AnythingLLM's agent the research skill, searching with DuckDuckGo.

The engine (research.py, SKILL.md and its contracts) is the operator's own
research skill, copied from their skills directory on the controller, so it is
never vendored into this repository. strata supplies only the AnythingLLM tool
that drives it: runs live in a folder outside the agent's File System root, the
agent writes briefs, handbacks and reports through the tool, and a report is
published only after the engine's `check` passes.
"""

from strata.core import guard
from strata.core.ports import PlaybookRunner
from strata.core.runbooks.services.install_anythingllm import STORAGE_DIR

# Outside <storage>/anythingllm-fs, the File System tools' root, so only the
# research tool can change a run's evidence.
_RUNS_DIR = f"{STORAGE_DIR}/research-runs"


@guard.alias("enable AnythingLLM research")
@guard.prerequisite("sudo_password")
@guard.requires("services.install_anythingllm")
@guard.path(_RUNS_DIR, owner="diot", group="anythingllm", mode="2770")
def main(target: str | None = None, *, runner: PlaybookRunner) -> int:
    """Install the research tool and copy the operator's research engine into it."""
    return runner.run_playbook(
        "playbooks/enable_anythingllm_research.yml",
        extravars={"anythingllm_storage_dir": STORAGE_DIR},
        target=target,
    )
