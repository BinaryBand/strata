"""Unit tests for strata.adapters.ansible.vault_pass.

`keyring` is replaced with an in-memory double so the real OS keychain is never
touched. The service/account pair is asserted on because ansible/vault_pass.py
reads the same entry independently -- a drift there breaks every playbook.
"""

from __future__ import annotations

import pytest

from strata.adapters.ansible import vault_pass
from strata.core import paths


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
    monkeypatch.setattr(vault_pass, "keyring", fake)
    return fake


def test_has_vault_password_false_when_absent() -> None:
    assert vault_pass.has_vault_password() is False


def test_set_then_has(fake_keyring: FakeKeyring) -> None:
    vault_pass.set_vault_password("hunter2")
    assert vault_pass.has_vault_password() is True
    assert fake_keyring.store == {("strata", "vault"): "hunter2"}


def test_set_uses_the_documented_service_and_account(fake_keyring: FakeKeyring) -> None:
    """ansible/vault_pass.py reads strata/vault; these must stay in sync."""
    vault_pass.set_vault_password("x")
    assert ("strata", "vault") in fake_keyring.store


def test_set_replaces_an_existing_entry(fake_keyring: FakeKeyring) -> None:
    vault_pass.set_vault_password("old")
    vault_pass.set_vault_password("new")
    assert fake_keyring.store[("strata", "vault")] == "new"
    assert len(fake_keyring.store) == 1


def test_has_is_true_for_an_empty_stored_password(fake_keyring: FakeKeyring) -> None:
    """An empty string is a stored value, not an absent one."""
    fake_keyring.store[("strata", "vault")] = ""
    assert vault_pass.has_vault_password() is True


def test_has_reads_only_this_projects_entry(fake_keyring: FakeKeyring) -> None:
    fake_keyring.store[("some-other-app", "vault")] = "not ours"
    assert vault_pass.has_vault_password() is False


def test_the_shell_script_reads_the_same_keychain_entry() -> None:
    """The --vault-password-file script must use the same service/account."""
    # Asserted, not skipped-on-absence: the script is tracked and load-bearing
    # (ansible.cfg names it as vault_password_file), so its disappearance is
    # the failure this test exists to catch. A skip here read as a pass.
    script = paths.ANSIBLE_DIR / "vault_pass.py"
    assert script.exists(), f"{script} is missing; ansible.cfg still points at it"
    text = script.read_text()
    assert vault_pass._SERVICE in text
    assert vault_pass._ACCOUNT in text


# ── migration from the pre-rename mr-manager keychain entry ────────────


def test_get_migrates_password_stored_under_the_old_service(fake_keyring: FakeKeyring) -> None:
    fake_keyring.store[("mr-manager", "vault")] = "hunter2"

    assert vault_pass.get_vault_password() == "hunter2"
    assert fake_keyring.store[("strata", "vault")] == "hunter2"


def test_migration_leaves_the_old_entry_in_place(fake_keyring: FakeKeyring) -> None:
    fake_keyring.store[("mr-manager", "vault")] = "hunter2"

    vault_pass.get_vault_password()

    assert fake_keyring.store[("mr-manager", "vault")] == "hunter2"


def test_new_entry_is_not_overwritten_by_the_old_one(fake_keyring: FakeKeyring) -> None:
    fake_keyring.store[("strata", "vault")] = "current"
    fake_keyring.store[("mr-manager", "vault")] = "stale"

    assert vault_pass.get_vault_password() == "current"


def test_get_returns_none_when_neither_entry_exists(fake_keyring: FakeKeyring) -> None:
    assert vault_pass.get_vault_password() is None
    assert fake_keyring.store == {}
