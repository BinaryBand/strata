"""`strata rclone`: remotes to auto-mount, and paths served over local HTTP."""

from __future__ import annotations

from typing import Annotated

import typer

from strata.adapters.ansible import rclone
from strata.cli._helpers import not_found, require_host, require_remote
from strata.cli.dispatch import maybe_apply

app = typer.Typer(
    no_args_is_help=True,
    help="Register rclone remotes for auto-mounting under /mnt/rclone/<name>.",
)
serve_app = typer.Typer(no_args_is_help=True, help="Manage rclone paths served over local HTTP.")
app.add_typer(serve_app, name="serve")
sync_app = typer.Typer(
    no_args_is_help=True,
    help="Copy an authorized rclone remote's credentials onto a device.",
)
app.add_typer(sync_app, name="sync")


def _remote_completer(incomplete: str) -> list[str]:
    """Complete rclone remote names, suffixed with ':' ready for a subpath."""
    prefix = incomplete.split(":", maxsplit=1)[0]
    return [f"{r}:" for r in rclone.remote_completion() if r.startswith(prefix)]


def _bare_remote_completer(incomplete: str) -> list[str]:
    """Complete rclone remote names with no trailing ':', for name-only arguments."""
    return [r for r in rclone.remote_completion() if r.startswith(incomplete)]


@app.command("add")
def rclone_add(
    name: str = typer.Argument(
        ...,
        autocompletion=_bare_remote_completer,
        help="Remote name as configured in rclone, e.g. 'pcloud'.",
    ),
    writable: Annotated[
        bool,
        typer.Option(
            "--writable",
            help="Mount read-write instead of the default read-only. Only set this "
            "for a remote a runbook needs to write to, e.g. a backup destination.",
        ),
    ] = False,
    apply: Annotated[
        bool, typer.Option("--apply", help="Run infrastructure.enable_rclone after registering.")
    ] = False,
    target: str | None = typer.Option(None, "--target", "-t", help="Target for --apply."),
) -> None:
    """Register an existing rclone remote for auto-mounting under /mnt/rclone/<name>.

    Authorize the remote first with: rclone config create <name> <type>
    """
    require_remote(name)
    rclone.add_to_config(name, writable=writable)
    mode = "read-write" if writable else "read-only"
    typer.echo(f"Registered {name!r} -- will mount at {rclone.mount_root(name)} ({mode})")
    maybe_apply(apply, target, "infrastructure.enable_rclone")


@app.command("remove")
def rclone_remove(
    name: str = typer.Argument(..., help="Remote name to remove, e.g. 'pcloud'."),
    apply: Annotated[
        bool, typer.Option("--apply", help="Run infrastructure.enable_rclone after removing.")
    ] = False,
    target: str | None = typer.Option(None, "--target", "-t", help="Target for --apply."),
) -> None:
    """Remove a registered remote (the rclone config and credential are untouched)."""
    if not rclone.remove_from_config(name):
        not_found("remote", name)
    typer.echo(f"Removed {name!r}.")
    maybe_apply(apply, target, "infrastructure.enable_rclone")


@app.command("list")
def rclone_list() -> None:
    """List remotes registered for auto-mounting."""
    remotes = rclone.list_remotes()
    if not remotes:
        typer.echo("No remotes registered. Use `strata rclone add <name>`.")
        return
    for name in remotes:
        mode = " (read-write)" if rclone.is_writable(name) else ""
        typer.echo(f"{name} -> {rclone.mount_root(name)}{mode}")


# -- rclone serve -------------------------------------------------------


@serve_app.command("add")
def rclone_serve_add(
    name: str = typer.Argument(..., help="Name for this HTTP serve, e.g. 'media-store'."),
    path: str = typer.Argument(
        ...,
        autocompletion=_remote_completer,
        help="rclone path to serve, e.g. 'pcloud:Media'.",
    ),
    port: int = typer.Option(..., "--port", "-p", help="Localhost port to bind, e.g. 8083."),
    base_url: str = typer.Option(
        "",
        "--base-url",
        help="Public URL prefix, e.g. '/media/podcasts', if it should differ "
        "from the served path (rclone's --baseurl).",
    ),
    apply: Annotated[
        bool,
        typer.Option("--apply", help="Run infrastructure.enable_rclone_http after registering."),
    ] = False,
    target: str | None = typer.Option(None, "--target", "-t", help="Target for --apply."),
) -> None:
    """Serve an rclone path over local HTTP (127.0.0.1:<port>) instead of mounting it."""
    remote_name = rclone.remote_name(path)
    require_remote(remote_name)
    rclone.add_http_serve(name, path, port, base_url=base_url or None)
    typer.echo(f"Registered serve {name!r}: {path} -> http://127.0.0.1:{port}")
    maybe_apply(apply, target, "infrastructure.enable_rclone_http")


@serve_app.command("remove")
def rclone_serve_remove(
    name: str = typer.Argument(..., help="Name of the HTTP serve to remove."),
    apply: Annotated[
        bool, typer.Option("--apply", help="Run infrastructure.enable_rclone_http after removing.")
    ] = False,
    target: str | None = typer.Option(None, "--target", "-t", help="Target for --apply."),
) -> None:
    """Remove a registered HTTP serve entry."""
    if not rclone.remove_http_serve(name):
        not_found("HTTP serve", name)
    typer.echo(f"Removed {name!r}.")
    maybe_apply(apply, target, "infrastructure.enable_rclone_http")


@serve_app.command("list")
def rclone_serve_list() -> None:
    """List rclone paths registered to be served over local HTTP."""
    serves = rclone.list_http_serves()
    if not serves:
        typer.echo(
            "No HTTP serves registered. Use `strata rclone serve add <name> <path> --port <port>`."
        )
        return
    for s in serves:
        base_url = s.get("base_url")
        suffix = f" (base_url={base_url})" if base_url else ""
        typer.echo(f"{s['name']}: {s['path']} -> http://127.0.0.1:{s['port']}{suffix}")


# -- rclone sync ----------------------------------------------------------


@sync_app.command("add")
def rclone_sync_add(
    name: str = typer.Argument(
        ..., autocompletion=_bare_remote_completer, help="Remote name to sync, e.g. 'pcloud'."
    ),
    target: str = typer.Option(
        ..., "--target", "-t", help="Device to copy this remote's credentials onto, e.g. 'nas'."
    ),
    apply: Annotated[
        bool,
        typer.Option("--apply", help="Run infrastructure.sync_rclone_remote after registering."),
    ] = False,
) -> None:
    """Copy an already-authorized rclone remote's credentials onto --target.

    Makes plain `rclone` commands (e.g. `rclone listremotes`) work on that
    device too. This is credential sync only -- it does not mount anything;
    mounting under diot only happens on the controller, see `rclone add`.
    """
    require_host(target)
    require_remote(name)
    rclone.add_synced_remote(target, name)
    typer.echo(f"Registered {name!r} to sync onto {target!r}.")
    maybe_apply(apply, target, "infrastructure.sync_rclone_remote")


@sync_app.command("remove")
def rclone_sync_remove(
    name: str = typer.Argument(
        ..., autocompletion=_bare_remote_completer, help="Remote name to stop syncing."
    ),
    target: str = typer.Option(..., "--target", "-t", help="Device to remove it from."),
    apply: Annotated[
        bool,
        typer.Option("--apply", help="Run infrastructure.sync_rclone_remote after removing."),
    ] = False,
) -> None:
    """Stop syncing a remote's credentials onto --target (an existing copy there is untouched)."""
    require_host(target)
    if not rclone.remove_synced_remote(target, name):
        not_found("synced remote", name)
    typer.echo(f"Removed {name!r} from {target!r}'s sync list.")
    maybe_apply(apply, target, "infrastructure.sync_rclone_remote")


@sync_app.command("list")
def rclone_sync_list(
    target: str = typer.Option(..., "--target", "-t", help="Device to list."),
) -> None:
    """List remotes registered to sync onto --target."""
    require_host(target)
    remotes = rclone.list_synced_remotes(target)
    if not remotes:
        typer.echo(
            f"No remotes registered to sync onto {target!r}. "
            f"Use `strata rclone sync add <name> --target {target}`."
        )
        return
    for name in remotes:
        typer.echo(name)
