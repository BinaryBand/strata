"""Unit tests for strata.adapters.ansible.secrets.

`VaultLib` is faked with a reversible "encryption" so the file-shape logic
(block replace vs append, sibling secrets surviving) can be tested end to end
against a scratch secrets file without a real vault password.

One test deliberately opts back into the real `VaultLib`:
test_the_written_block_matches_what_ansible_vault_cli_produces. The on-disk
layout is load-bearing -- every block already in
group_vars/secrets/all.yml was written by `ansible-vault encrypt_string`, and
this module now formats that block itself -- so a fake asserting against
another fake would prove nothing about compatibility.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from ansible.parsing.vault import AnsibleVaultError, VaultSecret

from strata.adapters.ansible import secrets

_REAL_VAULTLIB = secrets.VaultLib


def _fake_vaulttext(value: str) -> bytes:
    """Mimic the shape of VaultLib.encrypt() output: header, body, newline."""
    body = "\n".join(textwrap.wrap(value.encode().hex(), 80)) or "00"
    return f"$ANSIBLE_VAULT;1.1;AES256\n{body}\n".encode()


class FakeVaultLib:
    """Stands in for VaultLib, recording every construction and password."""

    constructions: list[bytes] = []  # noqa: RUF012

    def __init__(self, *, secrets: list[tuple[str, object]]) -> None:
        (_vault_id, secret), *_ = secrets
        FakeVaultLib.constructions.append(secret.bytes)  # ty: ignore[unresolved-attribute]
        self.fail = False

    def encrypt(self, plaintext: str) -> bytes:
        return _fake_vaulttext(plaintext)

    def decrypt(self, vaulttext: str | bytes) -> bytes:
        if isinstance(vaulttext, bytes):
            vaulttext = vaulttext.decode()
        if self.fail:
            msg = "Decryption failed (no vault secrets were found that could decrypt)."
            raise AnsibleVaultError(msg)
        return bytes.fromhex("".join(vaulttext.splitlines()[1:]))


@pytest.fixture(autouse=True)
def secrets_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect the secrets file, and pretend the vault password already exists."""
    directory = tmp_path / "secrets"
    monkeypatch.setattr(secrets, "_SECRETS_DIR", directory)
    monkeypatch.setattr(secrets, "_SECRETS_FILE", directory / "all.yml")
    monkeypatch.setattr(secrets.vault_pass, "has_vault_password", lambda: True)
    monkeypatch.setattr(secrets.vault_pass, "get_vault_password", lambda: "keychain-pw")
    return directory / "all.yml"


@pytest.fixture(autouse=True)
def fake_vault(monkeypatch: pytest.MonkeyPatch) -> type[FakeVaultLib]:
    FakeVaultLib.constructions = []
    monkeypatch.setattr(secrets, "VaultLib", FakeVaultLib)
    return FakeVaultLib


# ── ensure_vault_password() ───────────────────────────────────────────


def test_ensure_vault_password_is_a_noop_when_already_stored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(_: str) -> str:
        msg = "should not prompt"
        raise AssertionError(msg)

    monkeypatch.setattr(secrets.getpass, "getpass", boom)
    secrets.ensure_vault_password()


def test_ensure_vault_password_prompts_and_stores_when_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored: list[str] = []
    monkeypatch.setattr(secrets.vault_pass, "has_vault_password", lambda: False)
    monkeypatch.setattr(secrets.vault_pass, "set_vault_password", stored.append)
    monkeypatch.setattr(secrets.getpass, "getpass", lambda _prompt: "hunter2")

    secrets.ensure_vault_password()
    assert stored == ["hunter2"]


# ── has_secret() ──────────────────────────────────────────────────────


def test_has_secret_false_when_file_absent() -> None:
    assert secrets.has_secret("restic_password") is False


def test_has_secret_true_after_set() -> None:
    secrets.set_secret("restic_password", "s3cret")
    assert secrets.has_secret("restic_password") is True


def test_has_secret_does_not_match_a_prefix(secrets_file: Path) -> None:
    secrets.set_secret("restic_password_old", "x")
    assert secrets.has_secret("restic_password") is False
    assert "restic_password_old" in secrets_file.read_text()


def test_has_secret_does_not_match_an_indented_line(secrets_file: Path) -> None:
    secrets_file.parent.mkdir(parents=True)
    secrets_file.write_text("outer: !vault |\n          restic_password: nope\n")
    assert secrets.has_secret("restic_password") is False


def test_has_secret_needs_no_vault_password(fake_vault: type[FakeVaultLib]) -> None:
    """Scanning for a key must not require decrypting anything."""
    secrets.set_secret("restic_password", "s3cret")
    fake_vault.constructions.clear()

    assert secrets.has_secret("restic_password") is True
    assert fake_vault.constructions == []


# ── set_secret() ──────────────────────────────────────────────────────


def test_set_secret_creates_the_directory_and_file(secrets_file: Path) -> None:
    secrets.set_secret("restic_password", "s3cret")
    assert secrets_file.exists()


def test_set_secret_never_writes_the_plaintext(secrets_file: Path) -> None:
    secrets.set_secret("restic_password", "s3cret")
    assert "s3cret" not in secrets_file.read_text()


def test_set_secret_encrypts_with_the_keychain_password(
    fake_vault: type[FakeVaultLib],
) -> None:
    """The password comes from the OS keychain, in-process.

    It used to be handed to a child `ansible-vault` as
    --vault-password-file=ansible/vault_pass.py, a script that read this same
    keychain entry. Playbook runs still go through that script; this module
    no longer does.
    """
    secrets.set_secret("restic_password", "s3cret")
    assert fake_vault.constructions == [b"keychain-pw"]


def test_set_secret_fails_helpfully_when_the_keychain_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(secrets.vault_pass, "get_vault_password", lambda: None)

    with pytest.raises(RuntimeError, match="strata config vault-password"):
        secrets.set_secret("restic_password", "s3cret")


def test_a_vault_failure_does_not_leak_the_plaintext(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The plaintext must never reach an exception message.

    This was a real bug: the value was once a positional argument to
    `ansible-vault`, and check=True raises CalledProcessError, whose message
    embeds the whole argument vector -- so a vault failure printed the
    plaintext sudo password into the terminal. There is no argument vector
    now, but the obligation survives the subprocess that created it.
    """
    monkeypatch.setattr(secrets.vault_pass, "get_vault_password", lambda: None)

    with pytest.raises(RuntimeError) as excinfo:
        secrets.set_secret("ansible_become_password", "s3cret")

    assert "s3cret" not in str(excinfo.value)


def test_set_secret_handles_a_value_that_looks_like_a_flag() -> None:
    """A leading dash used to be parsed as an option by the ansible-vault CLI.

    In-process there is no argument parsing left to fool, so this now guards
    against a regression rather than a live hazard -- but a value like this is
    exactly what a generated token can look like, so it stays.
    """
    secrets.set_secret("odd", "--please-no")

    assert secrets.get_secret("odd") == "--please-no"


def test_set_secret_appends_without_disturbing_siblings() -> None:
    secrets.set_secret("first", "one")
    secrets.set_secret("second", "two")

    assert secrets.get_secret("first") == "one"
    assert secrets.get_secret("second") == "two"


def test_set_secret_replaces_an_existing_block(secrets_file: Path) -> None:
    secrets.set_secret("restic_password", "old")
    secrets.set_secret("restic_password", "new")

    assert secrets_file.read_text().count("restic_password:") == 1
    assert secrets.get_secret("restic_password") == "new"


def test_replacing_the_first_of_several_keeps_the_rest() -> None:
    secrets.set_secret("first", "one")
    secrets.set_secret("second", "two")
    secrets.set_secret("first", "one-updated")

    assert secrets.get_secret("first") == "one-updated"
    assert secrets.get_secret("second") == "two"


# ── get_secret() ──────────────────────────────────────────────────────


def test_get_secret_none_when_unset() -> None:
    assert secrets.get_secret("nope") is None


def test_get_secret_round_trips_a_stored_value() -> None:
    secrets.set_secret("restic_password", "s3cret")
    assert secrets.get_secret("restic_password") == "s3cret"


def test_get_secret_raises_naming_the_key_when_decryption_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secrets.set_secret("restic_password", "s3cret")

    def failing_vault(**_kwargs: object) -> FakeVaultLib:
        vault = FakeVaultLib(secrets=[("default", type("S", (), {"bytes": b"x"})())])
        vault.fail = True
        return vault

    monkeypatch.setattr(secrets, "VaultLib", failing_vault)

    with pytest.raises(RuntimeError) as excinfo:
        secrets.get_secret("restic_password")

    message = str(excinfo.value)
    assert "restic_password" in message
    assert "Decryption failed" in message


def test_get_secret_none_when_the_block_is_malformed(secrets_file: Path) -> None:
    """The key is declared but not as a vault block -- no crash, just None."""
    secrets_file.parent.mkdir(parents=True)
    secrets_file.write_text("restic_password: plain-value\n")
    assert secrets.get_secret("restic_password") is None


# ── on-disk format compatibility (real VaultLib) ──────────────────────


def test_the_written_block_matches_what_ansible_vault_cli_produces(
    monkeypatch: pytest.MonkeyPatch, secrets_file: Path
) -> None:
    """The block this module writes must be shaped exactly like the CLI's.

    Every secret currently in group_vars/secrets/all.yml was written by
    `ansible-vault encrypt_string --stdin-name`, and has_secret/get_secret/
    set_secret all parse the file by regex. Three properties have to hold, and
    each has a distinct way of silently breaking: the ten-space indent (the
    regexes need *some* indent, but the CLI's is ten), the 1.1 header (passing
    a vault_id to encrypt() would emit a 1.2 header with the id appended), and
    an 80-column body.
    """
    monkeypatch.setattr(secrets, "VaultLib", _REAL_VAULTLIB)
    secrets.set_secret("restic_password", "s3cret")

    lines = secrets_file.read_text().splitlines()
    assert lines[0] == "restic_password: !vault |"
    assert lines[1] == " " * 10 + "$ANSIBLE_VAULT;1.1;AES256"
    assert all(line.startswith(" " * 10) for line in lines[1:])
    assert all(len(line) - 10 == 80 for line in lines[2:-1])


def test_a_block_written_by_the_ansible_vault_cli_still_decrypts(
    monkeypatch: pytest.MonkeyPatch, secrets_file: Path
) -> None:
    """Reading must stay backward-compatible with the subprocess era.

    Built with the real VaultLib rather than checked in, so the fixture cannot
    rot against a vault format change -- what it pins is that a block in the
    CLI's exact layout, which is what is on disk today, round-trips.
    """
    monkeypatch.setattr(secrets, "VaultLib", _REAL_VAULTLIB)
    vault = _REAL_VAULTLIB(secrets=[("default", VaultSecret(b"keychain-pw"))])
    vaulttext = vault.encrypt("legacy-value").decode()

    secrets_file.parent.mkdir(parents=True)
    secrets_file.write_text(
        "restic_password: !vault |\n" + textwrap.indent(vaulttext.rstrip("\n"), " " * 10) + "\n"
    )

    assert secrets.get_secret("restic_password") == "legacy-value"
