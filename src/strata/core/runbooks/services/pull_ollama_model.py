"""Runbook: pull models into the managed Ollama container.

The models are named with `--tags`, the one list a runbook can be handed, e.g.
`--tags qwen2.5:3b,llama3.2:3b`. Pulling is idempotent: a model already
present is skipped. Install the container first with services.install_ollama.
"""

import re

from strata.core import guard
from strata.core.ports import PlaybookRunner

# A registry model reference: an optional namespace, a name and an optional tag.
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*(:[A-Za-z0-9._-]+)?")


def validate_tags(tags: list[str] | None) -> None:
    """Reject a missing or malformed model list before any guard provisions anything."""
    if not tags:
        msg = "Name the models to pull with --tags, e.g. --tags qwen2.5:3b"
        raise ValueError(msg)
    bad = [tag for tag in tags if not _MODEL.fullmatch(tag)]
    if bad:
        msg = f"Not a model name: {', '.join(repr(tag) for tag in bad)}"
        raise ValueError(msg)


@guard.alias("pull Ollama models")
@guard.prerequisite("sudo_password")
@guard.requires("services.install_ollama")
def main(
    target: str | None = None,
    tags: list[str] | None = None,
    *,
    runner: PlaybookRunner,
) -> int:
    """Pull each named model into the Ollama container.

    Args:
        target: Inventory host running the container; None uses the last selected target.
        tags: Model names to pull, as `name` or `name:tag`.
        runner: Playbook runner supplied by the executor.

    Returns:
        The pull playbook's exit code.
    """
    validate_tags(tags)
    return runner.run_playbook(
        "playbooks/pull_ollama_model.yml",
        extravars={"ollama_models": tags},
        target=target,
    )
