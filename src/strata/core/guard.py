"""Declare what a runbook needs before it runs.

Each decorator here records a requirement on the decorated function and
returns it unwrapped. Nothing is executed, prompted for, or provisioned at
decoration time or at call time -- adapters/guard_executor.py reads the
recorded list and satisfies it before invoking main().

That is a change from the original design, where each decorator wrapped the
function and did the work itself. Wrapping meant a runbook could not live in
core (the wrappers prompted, stat'd, and ran playbooks), forced a lazy import
in every guard to break the guard <-> secrets import cycle, and made each
wrapper claim to return the decorated function's type while actually being
able to return an int exit code -- which is why every one of them carried a
blanket `# type: ignore`. Declaring instead of doing removes all three.

`alias` and `backup_tag` are the two that record no requirement. They attach
metadata to the function, read back by `alias_of` and `backup_tags_of`, and
nothing is accumulated anywhere else: what a runbook declares is a property of
the runbook, so discovery reads it off the runbooks it finds.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from strata.core import requirements as req


def _declare[F: Callable[..., object]](fn: F, requirement: req.Requirement) -> F:
    """Prepend `requirement` to `fn`'s declared list.

    Prepend, not append: decorators apply bottom-up, so the outermost decorator
    is recorded last but must be satisfied first -- matching the old wrapper
    nesting, where the outermost wrapper ran its guard before delegating in.
    """
    existing: list[req.Requirement] = list(getattr(fn, req.REQUIREMENTS_ATTR, ()))
    setattr(fn, req.REQUIREMENTS_ATTR, [requirement, *existing])
    return fn


def declared(fn: object) -> list[req.Requirement]:
    """Return the requirements declared on `fn`, outermost first."""
    return list(getattr(fn, req.REQUIREMENTS_ATTR, ()))


def _requirement[F: Callable[..., object]](requirement: req.Requirement) -> Callable[[F], F]:
    """Return a decorator that declares `requirement` on the function it wraps."""

    def decorator(fn: F) -> F:
        return _declare(fn, requirement)

    return decorator


def prerequisite[F: Callable[..., object]](name: str) -> Callable[[F], F]:
    """Require a named prerequisite the executor knows how to satisfy."""
    return _requirement(req.Prerequisite(name))


def secret[F: Callable[..., object]](
    vault_key: str,
    *,
    kind: Literal["text", "password"] = "password",
    prompt: str | None = None,
    default: str | None = None,
    generate: bool = False,
) -> Callable[[F], F]:
    """Require a vault secret, prompting for it if it is not already stored.

    `kind` selects the input style ("password" hides typing). When the operator
    enters nothing, a `generate`d random value (or `default`) is stored instead,
    so the secret is never left unset.
    """
    return _requirement(
        req.Secret(
            vault_key=vault_key,
            message=prompt or f"{vault_key} ({kind})",
            kind=kind,
            default=default,
            generate=generate,
        )
    )


def user[F: Callable[..., object]](username: str, playbook: str) -> Callable[[F], F]:
    """Require a system account, created by `playbook` when absent."""
    return _requirement(req.SystemUser(username=username, playbook=playbook))


def path[F: Callable[..., object]](
    target_path: str,
    *,
    owner: str | None = None,
    group: str | None = None,
    mode: str | None = None,
    state: str = "directory",
) -> Callable[[F], F]:
    """Require a local filesystem path with the given ownership and mode.

    `mode` is an octal string, e.g. "2770". For rclone remotes
    (``remote:subpath`` notation) use mount() instead.
    """
    return _requirement(
        req.LocalPath(path=target_path, owner=owner, group=group, mode=mode, state=state)
    )


def mount[F: Callable[..., object]](remote_path: str) -> Callable[[F], F]:
    """Require an rclone remote, in ``remote:subpath`` form, to be mounted."""
    return _requirement(req.Mount(remote_path=remote_path, writable=False))


def storage[F: Callable[..., object]](  # noqa: PLR0913
    vault_key: str,
    *,
    prompt: str | None = None,
    default: str | None = None,
    owner: str | None = None,
    group: str | None = None,
    mode: str | None = None,
    require_writable: bool = False,
) -> Callable[[F], F]:
    """Require a vaulted location that may be a local directory or an rclone remote.

    Lets a runbook declare one data-layer location -- a backup repository, say --
    that works as either, without the caller knowing which ahead of time.
    `owner`/`group`/`mode` apply only to the local-directory branch; a mounted
    remote's permissions come from enable_rclone.yml. `require_writable`
    promotes a remote to writable and remounts it if it was registered
    read-only, since a read-only mount cannot serve as a write destination.
    """
    return _requirement(
        req.Storage(
            vault_key=vault_key,
            message=prompt or f"{vault_key} (text)",
            default=default,
            owner=owner,
            group=group,
            mode=mode,
            require_writable=require_writable,
        )
    )


def controller_only[F: Callable[..., object]](reason: str) -> Callable[[F], F]:
    """Refuse to run this runbook against anything but the controller.

    Some playbooks are deliberately `hosts: local` -- workstation tooling
    whose whole point is the machine the operator is sitting at. Because
    run_playbook always appends `--limit <target>`, such a play simply
    matches no hosts when given a remote target, which ansible reports as
    success. The runner now catches that, but "matched no hosts" describes
    the symptom; declaring the constraint here lets the operator be told
    what is actually true, before any playbook runs.

    Note this is *not* the way to say "the local fast path only applies on
    the controller" -- guards already handle that per requirement. This says
    the runbook itself has no meaning elsewhere.
    """
    return _requirement(req.ControllerOnly(reason))


def requires[F: Callable[..., object]](runbook_name: str) -> Callable[[F], F]:
    """Require another runbook to have run first, by dotted name."""
    return _requirement(req.UpstreamRunbook(runbook_name))


_BACKUP_ATTR = "_backup_tags"


def backup_tag[F: Callable[..., object]](tag: str, path: str) -> Callable[[F], F]:
    """Declare that `path` is backed up under restic tag `tag`.

    Metadata only, like `alias`: infrastructure.backup reads the tags off the
    runbooks discovery finds, and --tags narrows which get backed up.
    """

    def decorator(fn: F) -> F:
        setattr(fn, _BACKUP_ATTR, (*backup_tags_of(fn), (tag, path)))
        return fn

    return decorator


def backup_tags_of(fn: object) -> tuple[tuple[str, str], ...]:
    """Return the (tag, path) pairs declared on `fn` via @backup_tag, in decorator order."""
    return getattr(fn, _BACKUP_ATTR, ())


_ALIAS_ATTR = "_mr_alias"


def alias[F: Callable[..., object]](display_name: str) -> Callable[[F], F]:
    """Declare the human-friendly name shown for this runbook in the picker and --list.

    Metadata only: unlike the requirement decorators it records nothing the
    executor acts on. discovery reads it via alias_of() for display; a runbook
    is still invoked and resolved by its dotted/leaf name, never its alias.
    """

    def decorator(fn: F) -> F:
        setattr(fn, _ALIAS_ATTR, display_name)
        return fn

    return decorator


def alias_of(fn: object) -> str | None:
    """Return the display alias declared on `fn` via @alias, or None."""
    return getattr(fn, _ALIAS_ATTR, None)
