"""Unit tests for strata.adapters.ansible.host_scope -- a host's view of a vaulted value."""

from __future__ import annotations

import pytest

from strata.adapters.ansible import host_scope, host_vars, inventory
from tests._fakes import fake_vault, remote_device


@pytest.fixture(autouse=True)
def vault(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setattr(inventory, "get", remote_device)
    return fake_vault(monkeypatch, {"restic_repository": "/srv/restic"})


def test_the_hosts_override_wins_over_the_vault() -> None:
    host_vars.set_var("nas", "restic_repository", "pcloud:nas-restic")
    scoped = host_scope.HostSecrets("nas")
    assert scoped.get_secret("restic_repository") == "pcloud:nas-restic"
    assert scoped.override("restic_repository") == "pcloud:nas-restic"


def test_without_an_override_the_vault_answers() -> None:
    host_vars.set_var("other", "restic_repository", "pcloud:other")
    assert host_scope.HostSecrets("nas").get_secret("restic_repository") == "/srv/restic"


def test_no_host_reads_the_vault_alone() -> None:
    assert host_scope.HostSecrets(None).override("restic_repository") is None
    assert host_scope.HostSecrets(None).get_secret("restic_repository") == "/srv/restic"


def test_a_host_outside_the_inventory_has_no_override(monkeypatch: pytest.MonkeyPatch) -> None:
    host_vars.set_var("ghost", "restic_repository", "pcloud:ghost")
    monkeypatch.setattr(inventory, "get", lambda _name: None)
    assert host_scope.HostSecrets("ghost").override("restic_repository") is None


def test_has_value_counts_an_override_without_a_vault_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(host_scope.secrets, "has_secret", lambda _name: False)
    host_vars.set_var("nas", "restic_repository", "pcloud:nas-restic")
    assert host_scope.HostSecrets("nas").has_value("restic_repository") is True
    assert host_scope.HostSecrets(None).has_value("restic_repository") is False
