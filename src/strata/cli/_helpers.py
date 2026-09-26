"""Shared CLI helpers: error display and apply hints."""

from __future__ import annotations

from typing import NoReturn

import typer

from strata.adapters.ansible import inventory, rclone

# ── Shared UX helpers ──────────────────────────────────────────────────


def not_found(noun: str, key: object) -> NoReturn:
    """Echo a not-found message to stderr and abort.

    Annotated NoReturn so callers do not need an `assert x is not None` after
    it purely to re-narrow a type the checker cannot otherwise see is settled.
    """
    typer.echo(f"{noun} {key!r} not found.", err=True)
    raise typer.Exit(1)


def require_remote(name: str) -> None:
    """Abort unless `name` is a remote rclone already knows about.

    The same six-line block was written out at three call sites in
    cli/commands/rclone.py, character for character apart from the variable
    name.
    """
    if not rclone.has_remote(name):
        typer.echo(
            f"Remote {name!r} not found in rclone config. "
            f"Authorize it first: rclone config create {name} <type>",
            err=True,
        )
        raise typer.Exit(1)


def require_host(name: str) -> None:
    """Abort unless `name` is a host in the inventory.

    Ansible loads host_vars by inventory hostname, so writing them for a name
    that is not in the inventory produces a file nothing will ever read: the
    command reports success, `list` shows the entry, and the playbook then
    skips every task because its list is empty -- a silent no-op wearing a
    success message. It also keeps a name like `../group_vars/all/managed`
    from being turned into a path outside host_vars/.
    """
    if inventory.get(name) is None:
        known = ", ".join(sorted(d.name for d in inventory.all_hosts())) or "none registered"
        typer.echo(f"Host {name!r} is not in the inventory. Known hosts: {known}.", err=True)
        raise typer.Exit(1)


def apply_hint(runbook: str, *, target: str | None = None) -> str:
    """Return the canonical 'run this runbook to apply' message."""
    suffix = f" --target {target}" if target else ""
    return f"Run `strata runbook {runbook}{suffix}` to apply."
