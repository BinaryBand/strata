"""Unit tests for strata.adapters.ansible.keys.

ssh-keygen is never invoked: ``proc.run`` is replaced with a fake that writes
plausible key files, so the assertions are about the argv keys.py builds and the
group_vars it publishes. group_vars itself is exercised for real against a
scratch all.yml.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from strata.adapters.ansible import group_vars, keys

PUBLIC = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA fake"


class FakeSshKeygen:
    """Stands in for proc.run, emulating just enough ssh-keygen behaviour."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs) -> subprocess.CompletedProcess[str]:  # noqa: ARG002
        argv = list(argv)
        self.calls.append(argv)
        if "-y" in argv:  # derive public half from private key
            return subprocess.CompletedProcess(argv, 0, stdout=PUBLIC + "\n", stderr="")
        priv = Path(argv[argv.index("-f") + 1])
        priv.write_text("PRIVATE\n")
        priv.with_suffix(priv.suffix + ".pub").write_text(PUBLIC + "\n")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


@pytest.fixture(autouse=True)
def ssh_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect ~/.ssh and group_vars/all.yml at scratch locations."""
    ssh = tmp_path / "ssh"
    monkeypatch.setattr(keys, "_SSH_DIR", ssh)
    monkeypatch.setattr(group_vars, "_GROUP_VARS", tmp_path / "all.yml")
    return ssh


@pytest.fixture(autouse=True)
def fake_run(monkeypatch: pytest.MonkeyPatch) -> FakeSshKeygen:
    fake = FakeSshKeygen()
    monkeypatch.setattr(keys.proc, "run", fake)
    return fake


# ── var_name() ────────────────────────────────────────────────────────


def test_var_name_is_the_published_group_var() -> None:
    assert keys.var_name("backup") == "backup_authorized_key"


# ── has_key() ─────────────────────────────────────────────────────────


def test_has_key_false_when_absent() -> None:
    assert keys.has_key("backup") is False


def test_has_key_true_once_the_private_half_exists(ssh_dir: Path) -> None:
    ssh_dir.mkdir(parents=True)
    (ssh_dir / "backup").write_text("PRIVATE\n")
    assert keys.has_key("backup") is True


def test_has_key_ignores_a_lone_public_half(ssh_dir: Path) -> None:
    ssh_dir.mkdir(parents=True)
    (ssh_dir / "backup.pub").write_text(PUBLIC)
    assert keys.has_key("backup") is False


# ── public_key() ──────────────────────────────────────────────────────


def test_public_key_none_when_no_keypair(fake_run: FakeSshKeygen) -> None:
    assert keys.public_key("backup") is None
    assert fake_run.calls == []


def test_public_key_reads_the_pub_file_without_shelling_out(
    ssh_dir: Path, fake_run: FakeSshKeygen
) -> None:
    ssh_dir.mkdir(parents=True)
    (ssh_dir / "backup.pub").write_text(PUBLIC + "\n")

    assert keys.public_key("backup") == PUBLIC
    assert fake_run.calls == []


def test_public_key_derives_from_the_private_half_when_pub_is_missing(
    ssh_dir: Path, fake_run: FakeSshKeygen
) -> None:
    ssh_dir.mkdir(parents=True)
    (ssh_dir / "backup").write_text("PRIVATE\n")

    assert keys.public_key("backup") == PUBLIC
    assert fake_run.calls == [["ssh-keygen", "-y", "-f", str(ssh_dir / "backup")]]


# ── generate_key() ────────────────────────────────────────────────────


def test_generate_key_creates_the_keypair_and_returns_the_public_half(ssh_dir: Path) -> None:
    assert keys.generate_key("backup") == PUBLIC
    assert (ssh_dir / "backup").exists()
    assert (ssh_dir / "backup.pub").exists()


def test_generate_key_builds_a_passphraseless_ed25519_argv(
    ssh_dir: Path, fake_run: FakeSshKeygen
) -> None:
    keys.generate_key("backup", comment="restic@workstation")

    argv = fake_run.calls[0]
    assert argv[0] == "ssh-keygen"
    assert argv[argv.index("-t") + 1] == "ed25519"
    assert argv[argv.index("-N") + 1] == ""
    assert argv[argv.index("-C") + 1] == "restic@workstation"
    assert argv[argv.index("-f") + 1] == str(ssh_dir / "backup")


def test_generate_key_defaults_the_comment_to_the_label(fake_run: FakeSshKeygen) -> None:
    keys.generate_key("backup")
    argv = fake_run.calls[0]
    assert argv[argv.index("-C") + 1] == "backup"


def test_generate_key_creates_ssh_dir_with_0700(ssh_dir: Path) -> None:
    keys.generate_key("backup")
    assert ssh_dir.is_dir()
    assert ssh_dir.stat().st_mode & 0o777 == 0o700


def test_generate_key_publishes_the_public_half_to_group_vars() -> None:
    keys.generate_key("backup")
    assert group_vars.load()["backup_authorized_key"] == PUBLIC


def test_generate_key_is_a_noop_when_the_key_exists(ssh_dir: Path, fake_run: FakeSshKeygen) -> None:
    ssh_dir.mkdir(parents=True)
    (ssh_dir / "backup").write_text("EXISTING\n")
    (ssh_dir / "backup.pub").write_text(PUBLIC + "\n")

    assert keys.generate_key("backup") == PUBLIC
    assert fake_run.calls == []
    assert (ssh_dir / "backup").read_text() == "EXISTING\n"


def test_generate_key_republishes_even_when_the_key_already_exists(ssh_dir: Path) -> None:
    ssh_dir.mkdir(parents=True)
    (ssh_dir / "backup").write_text("EXISTING\n")
    (ssh_dir / "backup.pub").write_text(PUBLIC + "\n")
    group_vars.set_var("backup_authorized_key", "stale")

    keys.generate_key("backup")
    assert group_vars.load()["backup_authorized_key"] == PUBLIC


def test_generate_key_raises_when_the_public_half_is_unreadable(
    monkeypatch: pytest.MonkeyPatch, ssh_dir: Path
) -> None:
    """ssh-keygen exiting 0 without producing a key must not pass silently."""

    def silent_run(argv, **kwargs) -> subprocess.CompletedProcess[str]:  # noqa: ARG001
        return subprocess.CompletedProcess(list(argv), 0, stdout="", stderr="")

    monkeypatch.setattr(keys.proc, "run", silent_run)

    with pytest.raises(RuntimeError) as excinfo:
        keys.generate_key("backup")

    assert "backup" in str(excinfo.value)
    assert str(ssh_dir / "backup.pub") in str(excinfo.value)


def test_generate_key_does_not_publish_when_it_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def silent_run(argv, **kwargs) -> subprocess.CompletedProcess[str]:  # noqa: ARG001
        return subprocess.CompletedProcess(list(argv), 0, stdout="", stderr="")

    monkeypatch.setattr(keys.proc, "run", silent_run)

    with pytest.raises(RuntimeError):
        keys.generate_key("backup")
    assert group_vars.load() == {}


def test_labels_do_not_collide(ssh_dir: Path) -> None:
    keys.generate_key("backup")
    keys.generate_key("deploy")

    assert (ssh_dir / "backup").exists()
    assert (ssh_dir / "deploy").exists()
    loaded = group_vars.load()
    assert "backup_authorized_key" in loaded
    assert "deploy_authorized_key" in loaded
