"""The named prerequisites `@guard.prerequisite` refers to, and how to check them.

A prerequisite is a piece of operator state a runbook needs before anything
runs -- the vaulted sudo password, the vault password itself. Each entry pairs
the way to establish it with the way to tell whether it is already there, so
the set is enumerated exactly once: the write path (`guard_executor`) calls
`ensure`, and the read-only status path (`guard_status`) calls `satisfied`.

`satisfied` used to be a separate `if name == ...` ladder in guard_status.py.
Registering a third prerequisite here would have left the GUI's readiness
endpoint reporting it missing forever -- satisfied correctly at run time,
permanently red on the status display -- with nothing to catch the omission.

This is not a return of the old `utils/prerequisites.py`, which was a *runtime
registry* populated by import side effect: cli/main.py had to import it for
that side effect alone, and every `@guard.prerequisite` carried a lazy import
to be sure it had happened. This module is a plain table, imported like any
other, with no registration step and nothing to sequence.
"""

from __future__ import annotations

import getpass
from collections.abc import Callable
from dataclasses import dataclass

from strata.adapters.ansible import secrets, vault_pass

# The vault variable the sudo password is stored under. Named for the ansible
# variable it becomes, not for what it holds.
_SUDO_VAULT_VAR = "ansible_become_password"


def _ensure_sudo_password() -> None:
    if not secrets.has_secret(_SUDO_VAULT_VAR):
        secrets.set_secret(
            _SUDO_VAULT_VAR,
            getpass.getpass("sudo password (will be stored in vault): "),
        )


@dataclass(frozen=True)
class _Prerequisite:
    """How to establish one named prerequisite, and how to tell whether it holds."""

    ensure: Callable[[], None]
    satisfied: Callable[[], bool]


def _sudo_password_satisfied() -> bool:
    return secrets.has_secret(_SUDO_VAULT_VAR)


def _ensure_vault_password() -> None:
    secrets.ensure_vault_password()


def _vault_password_satisfied() -> bool:
    return vault_pass.has_vault_password()


# Entries name these local wrappers rather than the adapter functions
# themselves, so each adapter attribute is looked up at call time. A direct
# reference is resolved once at import and keeps answering from the function
# this table was built against, which silently ignores any later substitution
# of it -- including the ones the tests rely on.
_TABLE: dict[str, _Prerequisite] = {
    "sudo_password": _Prerequisite(
        ensure=_ensure_sudo_password,
        satisfied=_sudo_password_satisfied,
    ),
    "vault_password": _Prerequisite(
        ensure=_ensure_vault_password,
        satisfied=_vault_password_satisfied,
    ),
}


def ensure(name: str) -> None:
    """Establish prerequisite `name`, prompting the operator if it is absent.

    An unregistered name is a programming error in the runbook that declared
    it, so it raises rather than passing silently.
    """
    entry = _TABLE.get(name)
    if entry is None:
        msg = f"Prerequisite {name!r} is not registered. Available: {sorted(_TABLE)}"
        raise KeyError(msg)
    entry.ensure()


def satisfied(name: str) -> bool:
    """Report whether prerequisite `name` is already in place, without prompting.

    An unregistered name is reported unsatisfied rather than raising: this
    answers a status display, which must not blow up on a name the write path
    would reject loudly.
    """
    entry = _TABLE.get(name)
    return entry is not None and entry.satisfied()
