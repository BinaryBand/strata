"""Register rclone remotes for auto-mounting.

Remotes are normally authorized via ``rclone config create <name> <type>``, but
guard.mount/guard.storage now drive that interactively through
``prompt_create_remote`` when a remote turns out to be missing, rather than
telling the caller to run it themselves. This module records which remotes
should be mounted (plain group_vars) and provides the path resolver used by
guard.mount and runbooks.

One static mount per remote at /mnt/rclone/<remote> (the remote root). Sub-paths
are addressed with the ``remote:subpath`` notation and resolved to a local path at
the point of use.
"""

import json
import re

import click

from strata.adapters import proc
from strata.adapters.ansible import group_vars, host_vars

# Re-exported so existing callers keep importing path translation from the
# rclone module they already use. The implementations are pure and live in core
# so that core code needing only a path translation need not reach into an
# adapter.
from strata.core.remote_paths import (  # noqa: F401
    REMOTE_MOUNT_BASE,
    is_remote_path,
    mount_root,
    remote_name,
    resolve,
)

_REMOTES_VAR = "rclone_remotes"
_WRITABLE_VAR = "rclone_writable_remotes"
_HTTP_SERVES_VAR = "rclone_http_serves"
_SYNCED_REMOTES_VAR = "rclone_synced_remotes"


def has_remote(name: str) -> bool:
    """True if rclone knows this remote on the local machine.

    Compares against parsed names rather than searching the raw output for
    `<name>:`, which matched any remote *ending* in that name -- with `pcloud`
    configured, has_remote("cloud") was True. Callers act on this: the guard
    executor skipped creating the remote, and `strata rclone add` registered
    a name rclone had never heard of, which then failed at mount time. The
    exit status matters too; ignoring it read an rclone failure as "absent".
    """
    return name in remote_completion()


def list_remotes() -> list[str]:
    """Return the list of remote names registered for auto-mounting."""
    return group_vars.load().get(_REMOTES_VAR, [])


def list_writable_remotes() -> list[str]:
    """Return the subset of registered remotes mounted read-write."""
    return group_vars.load().get(_WRITABLE_VAR, [])


def is_writable(name: str) -> bool:
    """True if *name* is mounted read-write rather than the default read-only."""
    return name in list_writable_remotes()


def add_to_config(name: str, *, writable: bool = False) -> None:
    """Record *name* in rclone_remotes (idempotent). Does not touch rclone config.

    `writable` drops --read-only from the mount unit -- only set it for remotes
    a runbook needs to write to, e.g. a backup destination.
    """
    remotes = list_remotes()
    if name not in remotes:
        remotes.append(name)
        group_vars.set_var(_REMOTES_VAR, remotes)

    writable_remotes = list_writable_remotes()
    if writable and name not in writable_remotes:
        group_vars.set_var(_WRITABLE_VAR, [*writable_remotes, name])
    elif not writable and name in writable_remotes:
        group_vars.set_var(_WRITABLE_VAR, [r for r in writable_remotes if r != name])


def remove_from_config(name: str) -> bool:
    """Drop *name* from rclone_remotes (and rclone_writable_remotes).

    Args:
        name: Remote name to unregister.

    Returns:
        False if the remote was not registered.
    """
    remotes = list_remotes()
    if name not in remotes:
        return False
    group_vars.set_var(_REMOTES_VAR, [r for r in remotes if r != name])
    writable_remotes = list_writable_remotes()
    if name in writable_remotes:
        group_vars.set_var(_WRITABLE_VAR, [r for r in writable_remotes if r != name])
    return True


def list_http_serves() -> list[dict[str, object]]:
    """Return the list of rclone paths registered to be served over local HTTP."""
    return group_vars.load().get(_HTTP_SERVES_VAR, [])


def add_http_serve(name: str, path: str, port: int, base_url: str | None = None) -> None:
    """Record an rclone `path` to be served at http://127.0.0.1:<port> (idempotent).

    `base_url` lets the public URL prefix diverge from the served path -- e.g.
    serving `pcloud:Media/Podcasts` under `/media/podcasts` -- so existing
    client URLs keep working even if the underlying storage path changes.
    """
    serves = [s for s in list_http_serves() if s["name"] != name]
    entry: dict[str, object] = {"name": name, "path": path, "port": port}
    if base_url:
        entry["base_url"] = base_url
    serves.append(entry)
    group_vars.set_var(_HTTP_SERVES_VAR, serves)


def remove_http_serve(name: str) -> bool:
    """Drop a registered HTTP serve. Returns False if not present."""
    serves = list_http_serves()
    remaining = [s for s in serves if s["name"] != name]
    if len(remaining) == len(serves):
        return False
    group_vars.set_var(_HTTP_SERVES_VAR, remaining)
    return True


def list_synced_remotes(host: str) -> list[str]:
    """Return remotes registered to have their credentials synced onto `host`.

    Host-scoped (unlike `list_remotes`): each device gets its own copy of a
    remote's credentials, so registering one for `nas` must not affect `workstation`.
    """
    return host_vars.load(host).get(_SYNCED_REMOTES_VAR, [])


def add_synced_remote(host: str, name: str) -> None:
    """Record that `name`'s rclone credentials should be synced onto `host` (idempotent).

    Does not touch rclone config; sync_rclone_remote.yml reads this list and
    copies the credential from the controller's own rclone.conf.
    """
    remotes = list_synced_remotes(host)
    if name not in remotes:
        remotes.append(name)
        host_vars.set_var(host, _SYNCED_REMOTES_VAR, remotes)


def remove_synced_remote(host: str, name: str) -> bool:
    """Drop `name` from `host`'s synced-remote list. Returns False if not registered.

    Leaves any credential already copied onto `host` in place -- this only
    stops future syncs from refreshing it.
    """
    remotes = list_synced_remotes(host)
    if name not in remotes:
        return False
    host_vars.set_var(host, _SYNCED_REMOTES_VAR, [r for r in remotes if r != name])
    return True


def remote_completion() -> list[str]:
    """Return remote names known to rclone, for Typer autocompletion."""
    result = proc.run(["rclone", "listremotes"], capture_output=True, text=True)
    if result.returncode != 0:
        return []
    return [r.rstrip(":") for r in result.stdout.splitlines()]


def remote_type(name: str) -> str | None:
    """Return the backend type of an existing rclone remote (e.g. 'pcloud'), or None."""
    result = proc.run(["rclone", "config", "show", name], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    match = re.search(r"(?m)^type\s*=\s*(\S+)", result.stdout)
    return match.group(1) if match else None


def _known_backend_types() -> set[str]:
    """Return the set of valid rclone backend type names (e.g. 'pcloud', 's3').

    Used to validate a typed-in backend before attempting to create a remote
    with it, so a typo gets a clean re-prompt instead of rclone's raw
    command-line usage dump. Empty on any failure (e.g. rclone too old to
    support `config providers`) so validation is skipped rather than blocking.
    """
    result = proc.run(["rclone", "config", "providers"], capture_output=True, text=True)
    if result.returncode != 0:
        return set()
    try:
        providers = json.loads(result.stdout)
    except json.JSONDecodeError:
        return set()
    return {p["Name"] for p in providers if p.get("Name")}


def _guess_default_backend_type(name: str) -> str | None:
    """Suggest a backend type for a new remote from an existing one.

    Prefers `pcloud` specifically since it's the primary cloud backend in
    this project -- registering a second remote against the same pcloud
    account is the most common case -- and falls back to the only other
    remote if there's exactly one, since multiple existing remotes
    (e.g. `pcloud`) give no unambiguous default.
    """
    existing = [r for r in remote_completion() if r != name]
    if "pcloud" in existing:
        return remote_type("pcloud")
    if len(existing) == 1:
        return remote_type(existing[0])
    return None


def prompt_create_remote(name: str) -> None:
    """Interactively authorize rclone remote *name* if it isn't configured yet.

    Hands the terminal to rclone's own ``config create`` wizard (OAuth
    browser flow, backend-specific prompts, etc.) instead of telling the
    caller to run it themselves -- that step's stdio is never captured, so
    the wizard works normally. The backend type answer is validated against
    rclone's own provider list first (which *is* safe to capture), and a bad
    answer or a failed/aborted `config create` re-prompts instead of crashing.
    """
    if has_remote(name):
        return

    known = _known_backend_types()
    default_type = _guess_default_backend_type(name)
    message = f"rclone remote {name!r} isn't configured yet. Backend type"
    if not default_type:
        message += " (e.g. pcloud, drive, s3 -- see `rclone help backends`)"

    while True:
        backend: str = click.prompt(message, default=default_type).strip()
        if known and backend not in known:
            click.echo(
                f"{backend!r} isn't a known rclone backend type. "
                "Try again, or see `rclone help backends` for the full list."
            )
            continue

        click.echo(f"Running: rclone config create {name} {backend}")
        result = proc.run(["rclone", "config", "create", name, backend])
        if result.returncode == 0 and has_remote(name):
            return
        click.echo(
            f"rclone config create {name} {backend!r} did not succeed -- "
            "try again (or Ctrl+C to abort)."
        )
