"""The named-prerequisite table: establishing one, and reporting on one."""

from __future__ import annotations

import pytest

from strata.adapters import prerequisites
from strata.adapters.ansible import secrets, vault_pass


def test_ensure_rejects_an_unregistered_name() -> None:
    """A runbook declaring a name nobody registered is a bug, not a no-op."""
    with pytest.raises(KeyError, match="not registered"):
        prerequisites.ensure("no_such_prerequisite")


def test_satisfied_reports_an_unregistered_name_as_unsatisfied() -> None:
    """The read path answers a status display, so it must not raise where ensure does."""
    assert prerequisites.satisfied("no_such_prerequisite") is False


def test_sudo_password_reads_the_vault_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(secrets, "has_secret", lambda key: seen.append(key) or True)
    assert prerequisites.satisfied("sudo_password") is True
    assert seen == ["ansible_become_password"]


def test_vault_password_reads_the_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vault_pass, "has_vault_password", lambda: False)
    assert prerequisites.satisfied("vault_password") is False
    monkeypatch.setattr(vault_pass, "has_vault_password", lambda: True)
    assert prerequisites.satisfied("vault_password") is True


def test_ensure_sudo_password_prompts_only_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    stored: list[tuple[str, str]] = []
    monkeypatch.setattr(secrets, "has_secret", lambda _key: True)
    monkeypatch.setattr(secrets, "set_secret", lambda k, v: stored.append((k, v)))
    prerequisites.ensure("sudo_password")
    assert stored == []

    monkeypatch.setattr(secrets, "has_secret", lambda _key: False)
    monkeypatch.setattr(prerequisites.getpass, "getpass", lambda _prompt: "hunter2")
    prerequisites.ensure("sudo_password")
    assert stored == [("ansible_become_password", "hunter2")]


def test_every_entry_answers_both_halves(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each registered prerequisite must be both establishable and checkable.

    The point of one table is that a new entry cannot arrive with only its
    write half, which is what left the status endpoint reporting a live
    prerequisite as missing before these were paired.
    """
    monkeypatch.setattr(secrets, "has_secret", lambda _key: True)
    monkeypatch.setattr(vault_pass, "has_vault_password", lambda: True)
    for name in prerequisites._TABLE:
        assert prerequisites.satisfied(name) is True
        prerequisites.ensure(name)
