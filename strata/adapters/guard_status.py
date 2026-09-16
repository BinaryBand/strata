"""Read-only readiness for a declared requirement, without prompting or mutating.

`guard_executor._satisfy_one` is the write path: it prompts, stats, shells
out, or runs a playbook to make a requirement true. This is its read-only
counterpart, for a status display (the GUI's readiness endpoint) that must
never block on input or touch anything -- it only ever answers "satisfied",
"missing", or "unknown", the last for a check that is only meaningful on the
controller (see `guard_executor.is_controller`) when `target` is a different
host.

Split out from guard_executor.py on its own rather than folded in: that
module is the write path and this one deliberately never writes, and keeping
them apart makes "this function never mutates" a fact about the whole module,
not one function among many to audit.
"""

from __future__ import annotations

import importlib
import pwd
from pathlib import Path
from typing import assert_never

from strata.adapters import guard_executor
from strata.adapters.ansible import rclone, secrets, vault_pass
from strata.core import ports
from strata.core import requirements as req


def _prerequisite_satisfied(name: str) -> bool:
    if name == "sudo_password":
        return secrets.has_secret("ansible_become_password")
    if name == "vault_password":
        return vault_pass.has_vault_password()
    return False


def guard_status(requirement: req.Requirement, *, target: str | None) -> str:  # noqa: PLR0911, PLR0912, C901
    """Report whether `requirement` looks satisfied, without prompting or mutating.

    Same shape as `_satisfy_one`'s dispatch and the same reasoning applies:
    one branch per Requirement variant is the union's arity, not tangled
    control flow, and assert_never keeps a new variant from silently falling
    through.
    """
    match requirement:
        case req.ControllerOnly():
            return "satisfied" if guard_executor.is_controller(target) else "missing"
        case req.Prerequisite():
            return "satisfied" if _prerequisite_satisfied(requirement.name) else "missing"
        case req.Secret():
            return "satisfied" if secrets.has_secret(requirement.vault_key) else "missing"
        case req.Storage():
            # Existence only: confirming the vault value's mount/path is live
            # would need the vault unlocked, which this read-only check must not do.
            return "satisfied" if secrets.has_secret(requirement.vault_key) else "missing"
        case req.SystemUser():
            if not guard_executor.is_controller(target):
                return "unknown"
            try:
                pwd.getpwnam(requirement.username)
            except KeyError:
                return "missing"
            return "satisfied"
        case req.LocalPath():
            if not guard_executor.is_controller(target):
                return "unknown"
            return "satisfied" if guard_executor.path_satisfied(requirement) else "missing"
        case req.Mount():
            if not guard_executor.is_controller(target):
                return "unknown"
            remote_name = rclone.remote_name(requirement.remote_path)
            if remote_name not in rclone.list_remotes():
                return "missing"
            if requirement.writable and not rclone.is_writable(remote_name):
                return "missing"
            mounted = Path(rclone.resolve(requirement.remote_path)).exists()
            return "satisfied" if mounted else "missing"
        case req.UpstreamRunbook():
            if not guard_executor.is_controller(target):
                return "unknown"
            module = importlib.import_module(f"strata.core.runbooks.{requirement.dotted_name}")
            check = getattr(module, "check", None)
            if check is None:
                return "unknown"
            satisfied = guard_executor.check_safely(check, ports.NullReporter())
            return "satisfied" if satisfied else "missing"
        case _:
            assert_never(requirement)
