"""Unit tests for the read-only guard readiness check.

guard_status must never prompt or mutate, so click.prompt/getpass are left
unpatched throughout -- a test that reached them would mean the function
under test broke its own contract. target is left as None (the controller)
except where a case is specifically about a remote target.
"""

from __future__ import annotations

import os
import pwd
from pathlib import Path
from types import ModuleType

import pytest

from strata.adapters import guard_status
from strata.adapters.ansible import inventory, rclone, secrets, vault_pass
from strata.core import requirements as req
from strata.core.models import Device

_ME = pwd.getpwuid(os.getuid()).pw_name


def _remote_device(name: str) -> Device:
    return Device(name=name, host="10.0.0.9", user="root", connection="ssh")


def test_controller_only_status(monkeypatch: pytest.MonkeyPatch) -> None:
    requirement = req.ControllerOnly(reason="desktop app")
    assert guard_status.guard_status(requirement, target=None) == "satisfied"
    monkeypatch.setattr(inventory, "get", _remote_device)
    assert guard_status.guard_status(requirement, target="rpi4") == "missing"


def test_prerequisite_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(secrets, "has_secret", lambda key: key == "ansible_become_password")
    monkeypatch.setattr(vault_pass, "has_vault_password", lambda: False)
    assert guard_status.guard_status(req.Prerequisite("sudo_password"), target=None) == "satisfied"
    assert guard_status.guard_status(req.Prerequisite("vault_password"), target=None) == "missing"


def test_secret_and_storage_status_track_has_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(secrets, "has_secret", lambda _key: True)
    secret = req.Secret(
        vault_key="tailscale_auth_key", message="x", kind="password", default=None, generate=False
    )
    storage = req.Storage(
        vault_key="restic_repository",
        message="x",
        default=None,
        owner=None,
        group=None,
        mode=None,
        require_writable=False,
    )
    assert guard_status.guard_status(secret, target=None) == "satisfied"
    assert guard_status.guard_status(storage, target=None) == "satisfied"

    monkeypatch.setattr(secrets, "has_secret", lambda _key: False)
    assert guard_status.guard_status(secret, target=None) == "missing"
    assert guard_status.guard_status(storage, target=None) == "missing"


def test_system_user_status(monkeypatch: pytest.MonkeyPatch) -> None:
    requirement = req.SystemUser(username=_ME, playbook="playbooks/create_diot_user.yml")
    assert guard_status.guard_status(requirement, target=None) == "satisfied"

    monkeypatch.setattr(pwd, "getpwnam", lambda name: (_ for _ in ()).throw(KeyError(name)))
    assert guard_status.guard_status(requirement, target=None) == "missing"


def test_system_user_status_unknown_off_controller(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inventory, "get", _remote_device)
    requirement = req.SystemUser(username=_ME, playbook="playbooks/create_diot_user.yml")
    assert guard_status.guard_status(requirement, target="rpi4") == "unknown"


def test_local_path_status(tmp_path: Path) -> None:
    requirement = req.LocalPath(
        path=str(tmp_path), owner=None, group=None, mode=None, state="directory"
    )
    assert guard_status.guard_status(requirement, target=None) == "satisfied"

    missing = req.LocalPath(
        path=str(tmp_path / "nope"), owner=None, group=None, mode=None, state="directory"
    )
    assert guard_status.guard_status(missing, target=None) == "missing"


def test_mount_status(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(rclone, "list_remotes", lambda: ["pcloud"])
    monkeypatch.setattr(rclone, "is_writable", lambda _name: True)
    monkeypatch.setattr(rclone, "resolve", lambda _value: str(tmp_path))
    requirement = req.Mount(remote_path="pcloud:Media", writable=True)
    assert guard_status.guard_status(requirement, target=None) == "satisfied"

    monkeypatch.setattr(rclone, "list_remotes", list)
    assert guard_status.guard_status(requirement, target=None) == "missing"


def test_upstream_runbook_status_uses_its_own_check(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = ModuleType("fake_upstream")
    fake_module.__dict__["check"] = lambda: True
    monkeypatch.setattr(guard_status.importlib, "import_module", lambda _name: fake_module)
    requirement = req.UpstreamRunbook(dotted_name="infrastructure.install_podman")
    assert guard_status.guard_status(requirement, target=None) == "satisfied"


def test_upstream_runbook_status_unknown_without_a_check(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = ModuleType("fake_upstream")
    monkeypatch.setattr(guard_status.importlib, "import_module", lambda _name: fake_module)
    requirement = req.UpstreamRunbook(dotted_name="infrastructure.install_podman")
    assert guard_status.guard_status(requirement, target=None) == "unknown"
