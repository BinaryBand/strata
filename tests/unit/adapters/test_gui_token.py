"""Unit tests for strata.adapters.gui_token.

`keyring` is replaced with an in-memory double so the real OS keychain is
never touched, same pattern as tests/unit/adapters/ansible/test_vault_pass.py.
"""

from __future__ import annotations

import pytest

from strata.adapters import gui_token


class FakeKeyring:
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, account: str) -> str | None:
        return self.store.get((service, account))

    def set_password(self, service: str, account: str, value: str) -> None:
        self.store[(service, account)] = value


@pytest.fixture(autouse=True)
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> FakeKeyring:
    fake = FakeKeyring()
    monkeypatch.setattr(gui_token, "keyring", fake)
    return fake


def test_has_token_false_when_absent() -> None:
    assert gui_token.has_token() is False


def test_get_or_create_generates_and_stores_a_token(fake_keyring: FakeKeyring) -> None:
    token = gui_token.get_or_create_token()
    assert token
    assert fake_keyring.store == {("strata", "gui_token"): token}
    assert gui_token.has_token() is True


def test_get_or_create_returns_the_same_token_on_a_second_call() -> None:
    first = gui_token.get_or_create_token()
    second = gui_token.get_or_create_token()
    assert first == second


def test_rotate_replaces_the_stored_token(fake_keyring: FakeKeyring) -> None:
    first = gui_token.get_or_create_token()
    second = gui_token.rotate_token()
    assert second != first
    assert fake_keyring.store[("strata", "gui_token")] == second


def test_tokens_are_not_trivially_guessable() -> None:
    """A short or predictable token would defeat the point of requiring one."""
    assert len(gui_token.get_or_create_token()) >= 32
