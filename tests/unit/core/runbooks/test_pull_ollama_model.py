"""The runbook that pulls models into the Ollama container."""

from __future__ import annotations

import pytest

from strata.core import discovery
from strata.core.runbooks.services import pull_ollama_model


class _Runner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object] | None, str | None]] = []

    def run_playbook(
        self, playbook: str, *, extravars: dict[str, object] | None = None, target: str | None
    ) -> int:
        self.calls.append((playbook, extravars, target))
        return 0


def test_the_models_are_handed_to_the_playbook() -> None:
    runner = _Runner()
    rc = pull_ollama_model.main("owen", ["qwen2.5:3b", "llama3.2"], runner=runner)  # ty: ignore[invalid-argument-type]
    assert rc == 0
    assert runner.calls == [
        (
            "playbooks/pull_ollama_model.yml",
            {"ollama_models": ["qwen2.5:3b", "llama3.2"]},
            "owen",
        )
    ]


@pytest.mark.parametrize("tags", [None, [], ["qwen2.5:3b", "bad name"], ["x;rm -rf /"]])
def test_a_missing_or_malformed_selection_is_refused(tags: list[str] | None) -> None:
    with pytest.raises(ValueError, match=r"--tags|Not a model name"):
        pull_ollama_model.validate_tags(tags)


def test_discovery_forwards_the_selection_to_this_runbook() -> None:
    module = discovery.load("services.pull_ollama_model")
    assert discovery.forwarded_tags(module, ["qwen2.5:3b"]) == ["qwen2.5:3b"]
    with pytest.raises(ValueError, match="--tags"):
        discovery.forwarded_tags(module, None)
