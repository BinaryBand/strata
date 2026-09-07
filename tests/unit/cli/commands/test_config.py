"""Unit tests for `strata config` (strata.cli.commands.config).

Every adapter seam (group_vars, secrets, vault_pass, keys) is monkeypatched,
so no test writes group_vars, shells out to ansible-vault, touches the OS
keychain, or generates an SSH keypair.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from strata.adapters.ansible import group_vars, keys, secrets, vault_pass
from strata.cli.commands.config import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _no_real_adapters(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if a test forgets to stub a seam it exercises."""

    def boom(*_a: object, **_kw: object) -> None:
        msg = "adapter called without a stub"
        raise AssertionError(msg)

    monkeypatch.setattr(group_vars, "set_var", boom)
    monkeypatch.setattr(secrets, "set_secret", boom)
    monkeypatch.setattr(vault_pass, "set_vault_password", boom)
    monkeypatch.setattr(keys, "generate_key", boom)


# -- config var ----------------------------------------------------------


def test_var_passes_name_and_value_to_group_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(group_vars, "set_var", lambda k, v: calls.append((k, v)))

    result = runner.invoke(app, ["var", "restic_repository", "--value", "/srv/restic"])
    assert result.exit_code == 0
    assert calls == [("restic_repository", "/srv/restic")]
    assert "Set restic_repository -> '/srv/restic'" in result.output


def test_var_short_value_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(group_vars, "set_var", lambda k, v: calls.append((k, v)))

    result = runner.invoke(app, ["var", "media_root", "-v", "/mnt/media"])
    assert result.exit_code == 0
    assert calls == [("media_root", "/mnt/media")]


def test_var_prompts_when_value_omitted(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(group_vars, "set_var", lambda k, v: calls.append((k, v)))

    result = runner.invoke(app, ["var", "media_root"], input="/mnt/media\n")
    assert result.exit_code == 0
    assert calls == [("media_root", "/mnt/media")]
    assert "media_root" in result.output


def test_var_requires_a_name() -> None:
    result = runner.invoke(app, ["var"])
    assert result.exit_code != 0


# -- config vault-password -----------------------------------------------


def test_vault_password_stores_given_value(monkeypatch: pytest.MonkeyPatch) -> None:
    stored: list[str] = []
    monkeypatch.setattr(vault_pass, "set_vault_password", stored.append)

    result = runner.invoke(app, ["vault-password", "--value", "hunter2"])
    assert result.exit_code == 0
    assert stored == ["hunter2"]
    assert "Vault password stored in keychain." in result.output


def test_vault_password_prompts_with_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    stored: list[str] = []
    monkeypatch.setattr(vault_pass, "set_vault_password", stored.append)

    result = runner.invoke(app, ["vault-password"], input="hunter2\nhunter2\n")
    assert result.exit_code == 0
    assert stored == ["hunter2"]
    # Hidden input must not be echoed back to the terminal.
    assert "hunter2" not in result.output


def test_vault_password_mismatched_confirmation_is_not_stored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored: list[str] = []
    monkeypatch.setattr(vault_pass, "set_vault_password", stored.append)

    runner.invoke(app, ["vault-password"], input="hunter2\nhunter3\n\n\n")
    assert stored == []


# -- config secret -------------------------------------------------------


def test_secret_encrypts_given_value(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(secrets, "set_secret", lambda n, v: calls.append((n, v)))

    result = runner.invoke(app, ["secret", "jellyfin_api_key", "--value", "abc123"])
    assert result.exit_code == 0
    assert calls == [("jellyfin_api_key", "abc123")]
    assert "Encrypted and stored 'jellyfin_api_key'" in result.output


def test_secret_prompts_hidden_with_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(secrets, "set_secret", lambda n, v: calls.append((n, v)))

    result = runner.invoke(app, ["secret", "sudo_password"], input="s3cret\ns3cret\n")
    assert result.exit_code == 0
    assert calls == [("sudo_password", "s3cret")]
    assert "s3cret" not in result.output


# -- config key ----------------------------------------------------------


def test_key_generates_and_echoes_public_half(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str | None]] = []

    def fake_generate(label: str, comment: str | None = None) -> str:
        calls.append((label, comment))
        return "ssh-ed25519 AAAAPUBLIC sandbox"

    monkeypatch.setattr(keys, "generate_key", fake_generate)
    monkeypatch.setattr(keys, "var_name", lambda label: f"{label}_public_key")

    result = runner.invoke(app, ["key", "sandbox"])
    assert result.exit_code == 0
    assert calls == [("sandbox", None)]
    assert "Published 'sandbox_public_key'" in result.output
    assert "ssh-ed25519 AAAAPUBLIC sandbox" in result.output


def test_key_forwards_comment(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str | None]] = []

    def fake_generate(label: str, comment: str | None = None) -> str:
        calls.append((label, comment))
        return "ssh-ed25519 AAAA backup@workstation"

    monkeypatch.setattr(keys, "generate_key", fake_generate)
    monkeypatch.setattr(keys, "var_name", lambda label: f"{label}_public_key")

    result = runner.invoke(app, ["key", "backup", "--comment", "backup@workstation"])
    assert result.exit_code == 0
    assert calls == [("backup", "backup@workstation")]


# -- group surface -------------------------------------------------------


def test_bare_group_shows_help_not_an_error() -> None:
    """no_args_is_help means an argument-less invocation lists the subcommands."""
    result = runner.invoke(app, [])
    for name in ("var", "secret", "vault-password", "key"):
        assert name in result.output


def test_unknown_subcommand_fails() -> None:
    result = runner.invoke(app, ["nope"])
    assert result.exit_code != 0
