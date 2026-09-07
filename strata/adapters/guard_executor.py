"""Satisfy the requirements a runbook declares, then run it.

This holds what the guard decorators used to do inside their wrappers. Keeping
it here rather than in core is the whole point of the split: every branch below
prompts, stats, shells out, or runs a playbook.

Fast paths
----------
Each requirement has a cheap local check that can skip the playbook. Those
checks are only meaningful when the machine being provisioned is the one we are
running on, so they are gated on `_is_controller(target)`.

This condition used to be `target is not None`, which dated from when a target
of None meant "local". The CLI later started always resolving a target -- for
the local box, its own hostname -- so the condition was permanently true and
every fast path was dead code: `check()`, `_path_satisfied` and the pwd lookup
had not run in production for as long as that resolution has been in place.
Asking the inventory whether the target is the controller restores the
intended meaning.
"""

from __future__ import annotations

import getpass
import grp
import importlib
import inspect
import pwd
import types
from collections.abc import Callable
from pathlib import Path
from secrets import token_urlsafe
from typing import assert_never

import click

from strata.adapters.ansible import inventory, rclone, runner, secrets
from strata.core import guard, ports
from strata.core import requirements as req


def _is_controller(target: str | None) -> bool:
    """Report whether `target` is the machine we are running on.

    No target at all means the controller -- that is the pre-inventory
    default, and it keeps the local fast paths working before any device has
    been registered.

    A *named* host the inventory does not know is not. That case used to
    return True on the same "pre-inventory default" reasoning, but a name was
    typed for it, and the plausible reasons for the lookup to fail -- a typo,
    a host removed from the inventory, an ansible group rather than a host --
    all describe somewhere that is not this machine. Answering True made
    every fast path (_path_satisfied, the pwd lookup, the mount check,
    upstream check()) interrogate the controller on that host's behalf and
    report work as already done.
    """
    if target is None:
        return True
    device = inventory.get(target)
    return device is not None and device.connection == "local"


# ── Individual requirement handlers ────────────────────────────────────────


def _ensure_sudo_password() -> None:
    if not secrets.has_secret("ansible_become_password"):
        secrets.set_secret(
            "ansible_become_password",
            getpass.getpass("sudo password (will be stored in vault): "),
        )


# Replaces the old runtime registry that utils/prerequisites.py populated as an
# import side effect -- which is why cli/main.py had to import that module for
# its side effect alone, and why every @guard.prerequisite carried a lazy import
# to make sure it had happened. A plain table needs neither.
_PREREQUISITES: dict[str, Callable[[], None]] = {
    "sudo_password": _ensure_sudo_password,
    "vault_password": secrets.ensure_vault_password,
}


def _ensure_prerequisite(requirement: req.Prerequisite) -> None:
    handler = _PREREQUISITES.get(requirement.name)
    if handler is None:
        msg = (
            f"Prerequisite {requirement.name!r} is not registered. "
            f"Available: {sorted(_PREREQUISITES)}"
        )
        raise KeyError(msg)
    handler()


def _ensure_secret(
    vault_key: str, message: str, *, kind: str, default: str | None, generate: bool
) -> None:
    """Prompt for and store `vault_key` if it is not already in the vault.

    click renders the default (e.g. "[admin]") and returns it on a blank
    answer, so prompt strings should not repeat it by hand.

    An empty answer is re-prompted rather than stored. `default=default or ""`
    made the prompt non-mandatory even when there was no default, so pressing
    Enter yielded "" and wrote it -- and since has_secret() only checks that
    the key exists, nothing ever asked again. One stray Enter on
    tailscale_auth_key permanently poisoned it, and every later run silently
    handed the playbook an empty key.
    """
    if secrets.has_secret(vault_key):
        return
    while True:
        entry: str = click.prompt(
            message,
            default=default or "",
            show_default=default is not None,
            hide_input=kind == "password",
        ).strip()
        if entry:
            break
        if generate:
            entry = token_urlsafe(24)
            break
        click.echo(f"{vault_key} cannot be empty.")
    secrets.set_secret(vault_key, entry)


def _path_satisfied(spec: req.LocalPath) -> bool:  # noqa: PLR0911
    """Report whether the path already has the requested type, owner, group and mode.

    One return per unmet condition reads better than nesting them; PLR0911
    counts guard clauses it cannot distinguish from tangled control flow.
    """
    owner, group, mode = spec.owner, spec.group, spec.mode
    resolved = Path(spec.path)
    if not resolved.exists():
        return False
    if spec.state == "directory" and not resolved.is_dir():
        return False
    info = resolved.stat()
    try:
        if owner is not None and pwd.getpwuid(info.st_uid).pw_name != owner:
            return False
        if group is not None and grp.getgrgid(info.st_gid).gr_name != group:
            return False
    except KeyError:
        # uid/gid with no passwd/group entry: let the playbook reconcile it.
        return False
    return mode is None or (info.st_mode & 0o7777) == int(mode, 8)


def _ensure_local_path(spec: req.LocalPath, *, target: str | None) -> int | None:
    """Provision `spec` via ensure_path.yml unless it is already satisfied."""
    if _is_controller(target) and _path_satisfied(spec):
        return None
    extravars: dict[str, object] = {"guard_path": spec.path, "guard_state": spec.state}
    if spec.owner is not None:
        extravars["guard_owner"] = spec.owner
    if spec.group is not None:
        extravars["guard_group"] = spec.group
    if spec.mode is not None:
        extravars["guard_mode"] = spec.mode
    exit_code = runner.run_playbook("playbooks/ensure_path.yml", extravars=extravars, target=target)
    return exit_code or None


def _ensure_mount(remote_path: str, *, target: str | None, writable: bool = False) -> int | None:
    remote_name = rclone.remote_name(remote_path)
    needs_remount = False
    if not rclone.has_remote(remote_name):
        rclone.prompt_create_remote(remote_name)
    if remote_name not in rclone.list_remotes():
        rclone.add_to_config(remote_name, writable=writable)
        needs_remount = True
    elif writable and not rclone.is_writable(remote_name):
        rclone.add_to_config(remote_name, writable=True)
        needs_remount = True

    # os.path.exists(resolved) describes the controller's mount state, so it can
    # only stand in for a remote host's when they are the same machine.
    mounted = _is_controller(target) and Path(rclone.resolve(remote_path)).exists()
    if not needs_remount and mounted:
        return None
    exit_code = runner.run_playbook("playbooks/enable_rclone.yml", target=target)
    return exit_code or None


def _ensure_user(username: str, playbook: str, *, target: str | None) -> int | None:
    if _is_controller(target):
        try:
            pwd.getpwnam(username)
        except KeyError:
            pass
        else:
            return None
    exit_code = runner.run_playbook(playbook, target=target)
    return exit_code or None


def _ensure_storage(requirement: req.Storage, *, target: str | None) -> int | None:
    _ensure_secret(
        requirement.vault_key,
        requirement.message,
        kind="text",
        default=requirement.default,
        generate=False,
    )
    value = secrets.get_secret(requirement.vault_key)
    if not value:
        # This used to say "was just set but could not be read back", which
        # was almost never what happened: the usual cause was an empty value
        # stored by a blank prompt (now re-prompted), and the other is a
        # hand-edited block get_secret's stricter pattern will not match.
        # Both are about the stored value, not a failed read.
        msg = (
            f"{requirement.vault_key!r} holds no usable value. "
            f"Re-set it with `strata config secret {requirement.vault_key}`."
        )
        raise RuntimeError(msg)

    if rclone.is_remote_path(value):
        return _ensure_mount(value, target=target, writable=requirement.require_writable)
    return _ensure_local_path(
        req.LocalPath(
            path=value,
            owner=requirement.owner,
            group=requirement.group,
            mode=requirement.mode,
            state="directory",
        ),
        target=target,
    )


# ── Dispatch ───────────────────────────────────────────────────────────────


def _refuse_non_controller(
    requirement: req.ControllerOnly, *, target: str | None, reporter: ports.Reporter
) -> int | None:
    if _is_controller(target):
        return None
    reporter.info(f"This runbook only runs on the controller, not {target!r}: {requirement.reason}")
    return 1


def _satisfy_one(  # noqa: PLR0911, C901
    requirement: req.Requirement, *, target: str | None, reporter: ports.Reporter
) -> int | None:
    """Satisfy one requirement, returning a non-zero exit code on failure.

    One return per requirement kind is what a dispatch table looks like, and
    both suppressions above measure the same thing: the arity of the
    Requirement union, not branching within any one arm. Every case delegates
    immediately. Splitting the table to satisfy the metric would hide the one
    property worth being able to read off it -- that every variant is handled,
    which assert_never below makes the type checker enforce.
    """
    match requirement:
        case req.ControllerOnly():
            return _refuse_non_controller(requirement, target=target, reporter=reporter)
        case req.Prerequisite():
            _ensure_prerequisite(requirement)
            return None
        case req.Secret():
            _ensure_secret(
                requirement.vault_key,
                requirement.message,
                kind=requirement.kind,
                default=requirement.default,
                generate=requirement.generate,
            )
            return None
        case req.SystemUser():
            return _ensure_user(requirement.username, requirement.playbook, target=target)
        case req.LocalPath():
            return _ensure_local_path(requirement, target=target)
        case req.Mount():
            return _ensure_mount(
                requirement.remote_path, target=target, writable=requirement.writable
            )
        case req.Storage():
            return _ensure_storage(requirement, target=target)
        case req.UpstreamRunbook():
            return _run_upstream(requirement.dotted_name, target=target, reporter=reporter)
        case _:
            # Without this the match silently falls through and returns None
            # -- i.e. "satisfied" -- for any Requirement variant added to the
            # union but not handled here. assert_never turns that into a type
            # error at check time instead of a guard that quietly does nothing.
            assert_never(requirement)


def _run_upstream(dotted_name: str, *, target: str | None, reporter: ports.Reporter) -> int | None:
    """Run an upstream runbook unless its own check() says it is satisfied."""
    module = importlib.import_module(f"strata.core.runbooks.{dotted_name}")
    check = getattr(module, "check", None)
    if _is_controller(target) and check is not None and _checks_satisfied(check, reporter):
        return None
    # Forward the reporter rather than letting execute() install a null one:
    # a runbook's own progress messages were shown when it was invoked
    # directly and swallowed when the same runbook ran as a dependency.
    exit_code = execute(module, target=target, reporter=reporter)
    return exit_code or None


def _checks_satisfied(check: Callable[..., bool], reporter: ports.Reporter) -> bool:
    """Report whether `check()` says the upstream runbook is already satisfied.

    check() gets the same adapter injection main() does. It used to be called
    with no arguments at all, which left no way to hand it a vault reader --
    so install_restic.check, whose whole job is to read the vaulted
    repository path, could only `return False` and infrastructure.backup
    re-ran the entire restic container on every single run. The `secrets`
    entry in _PROVIDERS and the SecretReader port both existed already; they
    just had nothing to inject into.

    A check() is only ever an optimisation -- it skips work the playbook would
    redo idempotently -- so a check that cannot answer must not be fatal. These
    checks stat paths and read config that a runbook may not be permitted to
    see (a service's private state dir, a repository on an unmounted volume),
    and an error there means "cannot tell", not "broken". RuntimeError counts:
    secrets.get_secret raises it when ansible-vault cannot decrypt, which is
    exactly the locked-keychain case install_restic.check runs into. Fall back
    to running the playbook.
    """
    try:
        return check(**_injectables(check, reporter))
    except (OSError, RuntimeError):
        return False


def execute(
    module: types.ModuleType,
    *,
    target: str | None,
    tags: list[str] | None = None,
    reporter: ports.Reporter | None = None,
) -> int:
    """Satisfy a runbook module's declared requirements, then run its main().

    Requirements are satisfied in declaration order (outermost decorator first);
    the first one to fail short-circuits and its exit code is returned without
    main() running.
    """
    reporter = reporter or ports.NullReporter()
    for requirement in guard.declared(module.main):
        exit_code = _satisfy_one(requirement, target=target, reporter=reporter)
        if exit_code is not None:
            return exit_code

    kwargs: dict[str, object] = {"target": target, **_injectables(module.main, reporter)}
    if tags is not None:
        kwargs["tags"] = tags
    return module.main(**kwargs)


# ── Dependency injection ───────────────────────────────────────────────────

# Adapters a runbook's main() may ask for, keyed by parameter name. Values are
# built lazily so declaring one here costs nothing for runbooks that don't want
# it. Modules satisfy their Protocol ports structurally, so no adapter has to
# inherit anything.
_PROVIDERS: dict[str, Callable[[], object]] = {
    "runner": lambda: runner,
    "secrets": lambda: secrets,
}


def _injectables(main: Callable[..., int], reporter: ports.Reporter) -> dict[str, object]:
    """Build the subset of adapters `main` actually declares parameters for."""
    accepted = inspect.signature(main).parameters
    supplied: dict[str, object] = {
        name: provider() for name, provider in _PROVIDERS.items() if name in accepted
    }
    if "reporter" in accepted:
        supplied["reporter"] = reporter
    return supplied
