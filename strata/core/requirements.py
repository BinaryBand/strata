"""Declarative descriptions of what a runbook needs before it can run.

A guard decorator records one of these on the function and does nothing else;
adapters/guard_executor.py walks the recorded list and satisfies each one. That
split is what lets runbooks live in core: declaring "this needs a vault secret"
is a statement, while prompting for one and writing it to the vault is I/O.

These are plain frozen data. Anything that needs to *do* something belongs in
the executor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Prerequisite:
    """A named prerequisite registered with the executor, e.g. "sudo_password"."""

    name: str


@dataclass(frozen=True)
class Secret:
    """A vault key that must hold a value, prompting the operator if it does not."""

    vault_key: str
    message: str
    kind: Literal["text", "password"]
    default: str | None
    generate: bool


@dataclass(frozen=True)
class SystemUser:
    """A system account that must exist, created by `playbook` if absent."""

    username: str
    playbook: str


@dataclass(frozen=True)
class LocalPath:
    """A local filesystem path that must exist with the given ownership and mode."""

    path: str
    owner: str | None
    group: str | None
    mode: str | None
    state: str


@dataclass(frozen=True)
class Mount:
    """An rclone remote (``remote:subpath``) that must be registered and mounted."""

    remote_path: str
    writable: bool


@dataclass(frozen=True)
class Storage:
    """A vaulted location that is either a local directory or an rclone remote.

    Which one is not known until the stored value is read, so the executor
    dispatches to the LocalPath or Mount flow at runtime.
    """

    vault_key: str
    message: str
    default: str | None
    owner: str | None
    group: str | None
    mode: str | None
    require_writable: bool


@dataclass(frozen=True)
class UpstreamRunbook:
    """Another runbook that must have run first, identified by dotted name."""

    dotted_name: str


@dataclass(frozen=True)
class ControllerOnly:
    """The runbook only makes sense on the controller, and refuses other targets.

    `reason` is shown to the operator, so it should say why rather than
    restate the rule.
    """

    reason: str


Requirement = (
    Prerequisite
    | Secret
    | SystemUser
    | LocalPath
    | Mount
    | Storage
    | UpstreamRunbook
    | ControllerOnly
)

# Attribute the guard decorators attach to a runbook's main(). Ordered
# outermost-decorator-first, which is call order: the outermost wrapper used to
# run its guard work before delegating inward, so a declarative list has to be
# built by prepending as decorators apply bottom-up.
REQUIREMENTS_ATTR = "__requirements__"
