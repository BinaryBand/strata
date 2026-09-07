"""Unit tests for host_vars.py: per-host read/modify/write of host_vars/<host>.yml."""

from __future__ import annotations

from pathlib import Path

import pytest

from strata.adapters.ansible import host_vars


@pytest.fixture(autouse=True)
def _patch_host_vars_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(host_vars, "_HOST_VARS_DIR", tmp_path)
    return tmp_path


def test_load_missing_host_returns_empty_dict() -> None:
    assert host_vars.load("nosuchhost") == {}


def test_set_var_then_load_round_trips() -> None:
    host_vars.set_var("testhost", "rclone_remotes", ["pcloud"])
    assert host_vars.load("testhost") == {"rclone_remotes": ["pcloud"]}


def test_set_var_preserves_unmanaged_keys() -> None:
    """A key host_vars.py doesn't manage (e.g. a hand-written restic_repository)
    must survive a set_var() call for a different key."""
    host_vars.save("testhost", {"restic_repository": "pcloud:Backups/_Restic"})
    host_vars.set_var("testhost", "rclone_remotes", ["pcloud"])
    data = host_vars.load("testhost")
    assert data["restic_repository"] == "pcloud:Backups/_Restic"
    assert data["rclone_remotes"] == ["pcloud"]


def test_set_var_overwrites_existing_key() -> None:
    host_vars.set_var("testhost", "rclone_remotes", ["pcloud"])
    host_vars.set_var("testhost", "rclone_remotes", ["pcloud", "backblaze"])
    assert host_vars.load("testhost")["rclone_remotes"] == ["pcloud", "backblaze"]


def test_different_hosts_are_isolated() -> None:
    host_vars.set_var("hosta", "rclone_remotes", ["a"])
    host_vars.set_var("hostb", "rclone_remotes", ["b"])
    assert host_vars.load("hosta") == {"rclone_remotes": ["a"]}
    assert host_vars.load("hostb") == {"rclone_remotes": ["b"]}
