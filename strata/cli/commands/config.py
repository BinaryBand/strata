"""`strata config`: variables, secrets, the vault password, and SSH keys."""

from __future__ import annotations

import typer

from strata.adapters.ansible import group_vars, keys, secrets, vault_pass

app = typer.Typer(
    no_args_is_help=True,
    help="Manage configuration variables, secrets, vault password, and SSH keys.",
)


@app.command("var")
def config_var(
    name: str = typer.Argument(
        ...,
        help="Variable name to set in ansible/inventory/group_vars/all/managed.yml.",
    ),
    value: str | None = typer.Option(
        None,
        "--value",
        "-v",
        help="Value to set. Prompted interactively if not provided.",
    ),
) -> None:
    """Set a variable in ansible/inventory/group_vars/all/managed.yml."""
    if value is None:
        value = typer.prompt(name)

    group_vars.set_var(name, value)
    typer.echo(f"Set {name} -> {value!r} in ansible/inventory/group_vars/all/managed.yml")


@app.command("vault-password")
def config_vault_password(
    value: str | None = typer.Option(
        None,
        "--value",
        "-v",
        help="Password to store. Prompted (hidden) if not provided.",
    ),
) -> None:
    """Set or reset the ansible-vault master password in the OS keychain."""
    if value is None:
        value = typer.prompt("Vault password", hide_input=True, confirmation_prompt=True)

    vault_pass.set_vault_password(value)
    typer.echo("Vault password stored in keychain.")


@app.command("secret")
def config_secret(
    name: str = typer.Argument(..., help="Secret name in ansible/group_vars/secrets/all.yml."),
    value: str | None = typer.Option(
        None,
        "--value",
        "-v",
        help="Value to encrypt. Prompted (hidden) if not provided.",
    ),
) -> None:
    """Vault-encrypt a secret and store it in ansible/group_vars/secrets/all.yml."""
    if value is None:
        value = typer.prompt(name, hide_input=True, confirmation_prompt=True)

    secrets.set_secret(name, value)
    typer.echo(f"Encrypted and stored {name!r} in ansible/group_vars/secrets/all.yml")


@app.command("key")
def config_key(
    label: str = typer.Argument(
        ..., help="Label for the keypair, e.g. 'sandbox'. Stored at ~/.ssh/<label>."
    ),
    comment: str | None = typer.Option(
        None,
        "--comment",
        "-c",
        help="Comment for the key (defaults to the label).",
    ),
) -> None:
    """Generate an SSH keypair (if absent) and publish its public half to group_vars."""
    public = keys.generate_key(label, comment=comment)
    typer.echo(
        f"Published {keys.var_name(label)!r} to ansible/inventory/group_vars/all/managed.yml"
    )
    typer.echo(public)
