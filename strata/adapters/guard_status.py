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
import types
from pathlib import Path
from typing import assert_never

from strata.adapters import guard_executor, prerequisites
from strata.adapters.ansible import rclone, secrets
from strata.core import ports
from strata.core import requirements as req


def check_result(module: types.ModuleType, *, target: str | None) -> bool | None:
    """Report a runbook's own check(), or None when it cannot be meaningful.

    Every check() in the codebase inspects the *local* machine -- shutil.which,
    a stat, the vault on this box -- so it describes `target` only when target
    is the controller. None means "cannot tell": either the runbook declares no
    check(), or the answer would be about the wrong machine.

    One owner for that gate. The GUI's readiness endpoint used to call
    check_safely() with no gate at all while reporting each guard's status
    target-aware in the same response, so the two halves of one payload
    described two different machines.
    """
    check = getattr(module, "check", None)
    if check is None or not guard_executor.is_controller(target):
        return None
    return guard_executor.check_safely(check, ports.NullReporter())


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
            # Answered from the shared prerequisite table rather than a ladder
            # of names here, so registering a prerequisite cannot leave this
            # endpoint reporting it missing forever.
            return "satisfied" if prerequisites.satisfied(requirement.name) else "missing"
        case req.Secret():
            return "satisfied" if secrets.has_secret(requirement.vault_key) else "missing"
        case req.Storage():
            # Existence only: confirming the vault value's mount/path is live
            # would need the vault unlocked, which this read-only check must not do.
            return "satisfied" if secrets.has_secret(requirement.vault_key) else "missing"
        case req.SystemUser():
            # Existence, deliberately, even though the executor stopped
            # treating it as proof the account is fit (it now always runs the
            # creation playbook). The question this endpoint answers is "does
            # the account exist", which is still a true thing to report; it is
            # simply no longer a skip condition.
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
            module = importlib.import_module(f"strata.core.runbooks.{requirement.dotted_name}")
            satisfied = check_result(module, target=target)
            if satisfied is None:
                return "unknown"
            return "satisfied" if satisfied else "missing"
        case _:
            assert_never(requirement)
