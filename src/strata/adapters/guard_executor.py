"""Satisfy the requirements a runbook declares, then run it.

This holds what the guard decorators used to do inside their wrappers. Keeping
it here rather than in core is the whole point of the split: every branch below
prompts, stats, shells out, or runs a playbook.

Fast paths
----------
Each requirement has a cheap local check that can skip the playbook. Those
checks are only meaningful when the machine being provisioned is the one we are
running on, so they are gated on `is_controller(target)`.

This condition used to be `target is not None`, which dated from when a target
of None meant "local". The CLI later started always resolving a target -- for
the local box, its own hostname -- so the condition was permanently true and
every fast path was dead code: `check()`, `path_satisfied` and the pwd lookup
had not run in production for as long as that resolution has been in place.
Asking the inventory whether the target is the controller restores the
intended meaning.
"""

from __future__ import annotations

import grp
import inspect
import pwd
import types
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import assert_never

from strata.adapters import prerequisites
from strata.adapters.ansible import inventory, rclone, runner, secrets
from strata.core import discovery, guard, ports
from strata.core import requirements as req


def is_controller(target: str | None) -> bool:
    """Report whether `target` is the machine we are running on.

    No target at all means the controller -- that is the pre-inventory
    default, and it keeps the local fast paths working before any device has
    been registered.

    A *named* host the inventory does not know is not. That case used to
    return True on the same "pre-inventory default" reasoning, but a name was
    typed for it, and the plausible reasons for the lookup to fail -- a typo,
    a host removed from the inventory, an ansible group rather than a host --
    all describe somewhere that is not this machine. Answering True made
    every fast path (path_satisfied, the pwd lookup, the mount check,
    upstream check()) interrogate the controller on that host's behalf and
    report work as already done.
    """
    if target is None:
        return True
    device = inventory.get(target)
    return device is not None and device.is_controller


# ── Individual requirement handlers ────────────────────────────────────────


def path_satisfied(spec: req.LocalPath) -> bool:  # noqa: PLR0911
    """Report whether the path already has the requested type, owner, group and mode.

    One return per unmet condition reads better than nesting them; PLR0911
    counts guard clauses it cannot distinguish from tangled control flow.

    Every branch below either stats the path or resolves a uid/gid, and both
    can fail for a reason that is not an answer. `Path.exists()` and `stat()`
    used to sit outside the handler, and `Path.exists()` does not swallow
    EACCES -- CPython's `_ignore_error` covers ENOENT, ENOTDIR, EBADF and
    ELOOP only -- so an unreadable parent left `execute()` as an unhandled
    traceback. services.install_baikal reaches that unaided: its first guard
    creates /srv/baikal mode 2770 diot:baikal, and its next two stat paths
    inside it as an operator who is not in the baikal group.

    A path we cannot read is not evidence the path is right, so it gets the
    same answer an unresolvable uid already got: False, and ensure_path.yml
    reconciles it.
    """
    owner, group, mode = spec.owner, spec.group, spec.mode
    resolved = Path(spec.path)
    try:
        if not resolved.exists():
            return False
        if spec.state == "directory" and not resolved.is_dir():
            return False
        info = resolved.stat()
        if owner is not None and pwd.getpwuid(info.st_uid).pw_name != owner:
            return False
        if group is not None and grp.getgrgid(info.st_gid).gr_name != group:
            return False
        return mode is None or (info.st_mode & 0o7777) == int(mode, 8)
    except (OSError, KeyError):
        # Unreadable path, or a uid/gid with no passwd/group entry: both mean
        # "cannot tell", so let the playbook reconcile it.
        return False


def _play(
    playbook: str, *, target: str | None, extravars: Mapping[str, object] | None = None
) -> int | None:
    """Run `playbook`, mapping a zero exit to None (satisfied) and any failure to its code."""
    return runner.run_playbook(playbook, extravars=extravars, target=target) or None


def _ensure_local_path(spec: req.LocalPath, *, target: str | None) -> int | None:
    """Provision `spec` via ensure_path.yml unless it is already satisfied."""
    if is_controller(target) and path_satisfied(spec):
        return None
    extravars: dict[str, object] = {"guard_path": spec.path, "guard_state": spec.state}
    if spec.owner is not None:
        extravars["guard_owner"] = spec.owner
    if spec.group is not None:
        extravars["guard_group"] = spec.group
    if spec.mode is not None:
        extravars["guard_mode"] = spec.mode
    return _play("playbooks/ensure_path.yml", extravars=extravars, target=target)


def _ensure_mount(
    remote_path: str, *, target: str | None, prompter: ports.Prompter, writable: bool = False
) -> int | None:
    remote_name = rclone.remote_name(remote_path)
    if not rclone.has_remote(remote_name):
        rclone.prompt_create_remote(remote_name, prompter)
    needs_remount = not rclone.is_registered(remote_name, writable=writable)
    if needs_remount:
        rclone.add_to_config(remote_name, writable=writable)

    # is_mounted describes the controller's mount state, so it can only stand
    # in for a remote host's when they are the same machine.
    mounted = is_controller(target) and rclone.is_mounted(remote_path)
    if not needs_remount and mounted:
        return None
    return _play("playbooks/enable_rclone.yml", target=target)


def _ensure_user(playbook: str, *, target: str | None) -> int | None:
    """Run the account's creation playbook, unconditionally.

    There was a `pwd.getpwnam` fast path here. Existence is not fitness:
    create_diot_user.yml guarantees five things -- the group, the user, a
    subuid range, a subgid range, and lingering -- and the lookup checked only
    the second. A diot missing its subuid range or its linger file satisfied
    the guard permanently, nothing ever repaired it, and rootless podman
    failed later with an error naming none of that.

    The playbook is idempotent and costs one play, so running it is cheaper
    than restating its postconditions in Python, where the restatement would
    drift from the playbook that owns them.
    """
    return _play(playbook, target=target)


def _ensure_storage(
    requirement: req.Storage, *, target: str | None, prompter: ports.Prompter
) -> int | None:
    secrets.ensure_secret(requirement.as_secret(), prompter)
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
        return _ensure_mount(
            value, target=target, prompter=prompter, writable=requirement.require_writable
        )
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
    if is_controller(target):
        return None
    reporter.info(f"This runbook only runs on the controller, not {target!r}: {requirement.reason}")
    return 1


def _satisfy_one(  # noqa: PLR0911, C901
    requirement: req.Requirement,
    *,
    target: str | None,
    reporter: ports.Reporter,
    prompter: ports.Prompter,
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
            prerequisites.ensure(requirement.name, prompter)
            return None
        case req.Secret():
            secrets.ensure_secret(requirement, prompter)
            return None
        case req.SystemUser():
            return _ensure_user(requirement.playbook, target=target)
        case req.LocalPath():
            return _ensure_local_path(requirement, target=target)
        case req.Mount():
            return _ensure_mount(
                requirement.remote_path,
                target=target,
                prompter=prompter,
                writable=requirement.writable,
            )
        case req.Storage():
            return _ensure_storage(requirement, target=target, prompter=prompter)
        case req.UpstreamRunbook():
            return _run_upstream(
                requirement.dotted_name, target=target, reporter=reporter, prompter=prompter
            )
        case _:
            # Without this the match silently falls through and returns None
            # -- i.e. "satisfied" -- for any Requirement variant added to the
            # union but not handled here. assert_never turns that into a type
            # error at check time instead of a guard that quietly does nothing.
            assert_never(requirement)


def _run_upstream(
    dotted_name: str, *, target: str | None, reporter: ports.Reporter, prompter: ports.Prompter
) -> int | None:
    """Satisfy an upstream runbook, skipping its own main() if check() says so.

    A satisfied check() skips the upstream's *play*, never its guards. It used
    to return here outright, which meant a satisfied upstream took its whole
    declared chain with it: `install_podman.check()` is `shutil.which("podman")`,
    so on any machine with podman on PATH the `@guard.user("diot")` it declares
    was not merely fast-pathed, it was unreachable from install_jellyfin,
    install_baikal and install_restic. check() answers for the runbook's own
    work; it was never evidence about the runbook's dependencies.
    """
    module = discovery.load(dotted_name)
    check = getattr(module, "check", None)
    if is_controller(target) and check is not None and check_safely(check, reporter):
        return _satisfy_all(module, target=target, reporter=reporter, prompter=prompter)
    # Forward the reporter rather than letting execute() install a null one:
    # a runbook's own progress messages were shown when it was invoked
    # directly and swallowed when the same runbook ran as a dependency. The
    # prompter goes the same way, or an upstream's missing secret would be
    # refused in a run that was allowed to ask.
    return execute(module, target=target, reporter=reporter, prompter=prompter) or None


def check_safely(check: Callable[..., bool], reporter: ports.Reporter) -> bool:
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


def _satisfy_all(
    module: types.ModuleType,
    *,
    target: str | None,
    reporter: ports.Reporter,
    prompter: ports.Prompter,
) -> int | None:
    """Satisfy every requirement a module declares; None means all of them hold.

    Separate from execute() because a satisfied upstream needs exactly this and
    not the main() that follows it.
    """
    for requirement in guard.declared(module.main):
        exit_code = _satisfy_one(requirement, target=target, reporter=reporter, prompter=prompter)
        if exit_code is not None:
            return exit_code
    return None


def execute(
    module: types.ModuleType,
    *,
    target: str | None,
    tags: list[str] | None = None,
    reporter: ports.Reporter | None = None,
    prompter: ports.Prompter | None = None,
) -> int:
    """Satisfy a runbook module's declared requirements, then run its main().

    Requirements are satisfied in declaration order (outermost decorator first);
    the first one to fail short-circuits and its exit code is returned without
    main() running.

    A caller that omits `prompter` gets one that refuses every question, the
    way an omitted `reporter` gets one that drops every message: a missing
    secret then fails the run with a message naming it, where a default that
    prompted would hang any caller with no terminal.
    """
    reporter = reporter or ports.NullReporter()
    prompter = prompter or ports.NonInteractivePrompter()
    exit_code = _satisfy_all(module, target=target, reporter=reporter, prompter=prompter)
    if exit_code is not None:
        return exit_code

    kwargs: dict[str, object] = {"target": target, **_injectables(module.main, reporter)}
    if tags is not None:
        kwargs["tags"] = tags
    return module.main(**kwargs)


# ── Dependency injection ───────────────────────────────────────────────────

# Adapters a runbook's main() may ask for, keyed by parameter name. Modules
# satisfy their Protocol ports structurally, so no adapter has to inherit
# anything.
_PROVIDERS: dict[str, object] = {"runner": runner, "secrets": secrets}


def _injectables(main: Callable[..., int], reporter: ports.Reporter) -> dict[str, object]:
    """Build the subset of adapters `main` actually declares parameters for."""
    accepted = inspect.signature(main).parameters
    supplied = {name: adapter for name, adapter in _PROVIDERS.items() if name in accepted}
    if "reporter" in accepted:
        supplied["reporter"] = reporter
    return supplied
