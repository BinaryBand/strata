"""pytest-bdd binding for features/config.feature (var / secret / vault-password / key).

Isolation (Stage 1 decision + the keychain/subprocess caveats):
  * config var / config key -> real adapters against tmp files (group_vars, ~/.ssh)
  * config vault-password    -> real adapter, in-memory keyring fake
  * config secret            -> secrets.set_secret boundary-faked (its real path
    shells out to ansible-vault reading the OS keychain in a child process, which
    a test must never touch)
A typer.prompt spy records prompt kwargs so the "hidden, confirmed input"
scenarios can assert what the CLI actually asked for.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import typer
from pytest_bdd import given, parsers, scenarios, then

from strata.adapters.ansible import group_vars, keys, secrets, vault_pass

scenarios("config.feature")


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ctx: dict[str, Any]) -> None:
    """Redirect every config side effect at throwaway/in-memory stand-ins."""
    # Files: group_vars document and the ~/.ssh keypair dir.
    monkeypatch.setattr(group_vars, "_GROUP_VARS", tmp_path / "group_vars" / "all" / "managed.yml")
    monkeypatch.setattr(keys, "_SSH_DIR", tmp_path / ".ssh")

    # Keychain: an in-memory dict standing in for the OS keyring.
    keychain: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(vault_pass.keyring, "get_password", lambda s, a: keychain.get((s, a)))
    monkeypatch.setattr(
        vault_pass.keyring, "set_password", lambda s, a, v: keychain.__setitem__((s, a), v)
    )
    ctx["keychain"] = keychain

    # Secret: boundary-fake so no ansible-vault subprocess / real keychain is hit.
    secret_store: dict[str, str] = {}
    monkeypatch.setattr(secrets, "set_secret", secret_store.__setitem__)
    monkeypatch.setattr(secrets, "has_secret", secret_store.__contains__)
    ctx["secrets"] = secret_store

    # Prompt spy: record kwargs, then delegate to the real prompt (reads stdin).
    real_prompt = typer.prompt
    prompts: list[dict[str, Any]] = []

    def spy(text: str, *args: Any, **kwargs: Any) -> Any:
        prompts.append({"text": text, **kwargs})
        return real_prompt(text, *args, **kwargs)

    monkeypatch.setattr(typer, "prompt", spy)
    ctx["prompts"] = prompts


# ── config var ───────────────────────────────────────────────────────────


@then(parsers.parse('the variable "{name}" is stored as "{value}"'))
def variable_stored(name: str, value: str) -> None:
    assert group_vars.load().get(name) == value


# ── config secret ──────────────────────────────────────────────────────────


@then(parsers.parse('the secret "{name}" is stored'))
def secret_stored(ctx: dict[str, Any], name: str) -> None:
    assert name in ctx["secrets"]


# ── config vault-password ────────────────────────────────────────────────


@then(parsers.parse('the keychain holds the vault password "{value}"'))
def keychain_holds_password(ctx: dict[str, Any], value: str) -> None:
    assert ctx["keychain"].get(("strata", "vault")) == value


# ── shared prompt assertion ──────────────────────────────────────────────


@then("the last prompt used hidden, confirmed input")
def last_prompt_hidden_confirmed(ctx: dict[str, Any]) -> None:
    last = ctx["prompts"][-1]
    assert last.get("hide_input") is True
    assert last.get("confirmation_prompt") is True


# ── config key ──────────────────────────────────────────────────────────────


@given(parsers.parse('no keypair exists for "{label}"'))
def no_keypair(label: str) -> None:
    assert not keys.has_key(label)


@given(parsers.parse('a keypair already exists for "{label}"'))
def existing_keypair(ctx: dict[str, Any], label: str) -> None:
    keys.generate_key(label)
    ctx["priv_before"] = keys._private_path(label).read_text()


@then(parsers.parse('a keypair exists for "{label}"'))
def keypair_exists(label: str) -> None:
    assert keys.has_key(label)


@then(parsers.parse('its public key is published as "{var}"'))
def public_key_published(var: str) -> None:
    published = group_vars.load().get(var, "")
    assert published.startswith("ssh-")


@then("the public key is printed to the operator")
def public_key_printed(ctx: dict[str, Any]) -> None:
    assert "ssh-ed25519" in ctx["result"].output


@then(parsers.parse('the private key for "{label}" is unchanged'))
def private_key_unchanged(ctx: dict[str, Any], label: str) -> None:
    assert keys._private_path(label).read_text() == ctx["priv_before"]
