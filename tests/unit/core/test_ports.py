"""Unit tests for strata.core.ports -- the non-interactive implementations."""

from __future__ import annotations

import pytest

from strata.core import ports


def test_non_interactive_prompter_refuses_every_question() -> None:
    with pytest.raises(ports.PromptUnavailableError):
        ports.NonInteractivePrompter().ask("x")


def test_non_interactive_prompter_refuses_even_with_a_default() -> None:
    """A default is an answer the operator gets to confirm, and there is no operator."""
    with pytest.raises(ports.PromptUnavailableError):
        ports.NonInteractivePrompter().ask("x", default="y")


def test_the_refusal_names_the_question_and_the_way_out() -> None:
    with pytest.raises(ports.PromptUnavailableError) as excinfo:
        ports.NonInteractivePrompter().ask("  jellyfin admin password  ", hidden=True)
    message = str(excinfo.value)
    assert "'jellyfin admin password' needs an answer" in message
    assert "strata config secret" in message


def test_non_interactive_prompter_drops_notices() -> None:
    assert ports.NonInteractivePrompter().tell("anything") is None
