"""Fakes shared across the unit and feature suites."""

from __future__ import annotations

import pytest

from strata.adapters.ansible import secrets
from strata.core.models import Device


class FakePrompter:
    """Records every question and answers from a script, satisfying `ports.Prompter`.

    Answers are consumed in order; once they run out it behaves like a terminal
    where the operator just presses Enter, returning the default or "".
    """

    def __init__(self, answers: list[str] | None = None) -> None:
        self.answers = list(answers or [])
        self.asked: list[dict[str, object]] = []
        self.told: list[str] = []

    def ask(self, message: str, *, default: str | None = None, hidden: bool = False) -> str:
        self.asked.append({"message": message, "default": default, "hidden": hidden})
        if self.answers:
            return self.answers.pop(0)
        return default or ""

    def tell(self, message: str) -> None:
        self.told.append(message)


def remote_device(name: str) -> Device:
    """A registered ssh host that is not the controller, whatever it is called."""
    return Device(name=name, host="10.0.0.9", user="root", connection="ssh")


def fake_vault(
    monkeypatch: pytest.MonkeyPatch, store: dict[str, str] | None = None
) -> dict[str, str]:
    """Back the secrets adapter with an in-memory `store`, and return it.

    The vault password lives in the OS keychain, which no caller of this is
    about to test, so asking for a missing one is a no-op here.
    """
    vault = {} if store is None else store
    monkeypatch.setattr(secrets, "has_secret", vault.__contains__)
    monkeypatch.setattr(secrets, "get_secret", vault.get)
    monkeypatch.setattr(secrets, "set_secret", vault.__setitem__)
    monkeypatch.setattr(secrets, "ensure_vault_password", lambda _prompter: None)
    return vault
