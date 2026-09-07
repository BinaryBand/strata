"""Every runbook module is named `install_*`, `enable_*`, or allowlisted.

The prefix carries real meaning for the operator: `install_*` puts a binary or
package on the box once, `enable_*` stands up something that keeps running
afterwards (a systemd unit, a mount). Since runbooks are discovered by walking
the package and are offered to the operator as a flat list of dotted names --
in `--list`, in the autocomplete picker, in tab completion -- the prefix is
often the only thing distinguishing "this changes the machine once" from "this
leaves a service running" at the moment of choosing.

`docs/LEDGER.md` carried this as an open opportunity for a long time,
noting the rule was neither written down nor enforced (and misremembering a
`remove_*` prefix that never existed). It is written down now, in docs/ARCHITECTURE.md.
This gate is what keeps it true: no ast-grep rule can express it, because the
rules in `static/rules/` match code structure and this is a fact about file
names.

The allowlist is deliberately small and each entry has to say why. It exists
for the runbooks that are neither kind of provisioning step -- operations you
run against a machine that is already provisioned -- where a verb reads better
than a prefix that would be a lie.
"""

from __future__ import annotations

import pkgutil

import strata.core.runbooks as _runbook_pkg

_PREFIXES = ("install_", "enable_")

# Dotted runbook name -> why it is neither install_* nor enable_*.
ALLOWED_EXCEPTIONS: dict[str, str] = {
    "infrastructure.backup": "an operation on a provisioned machine, not a provisioning step",
    "infrastructure.restore": "the inverse operation of backup; same reasoning",
    "infrastructure.sync_rclone_remote": "pushes existing rclone config; installs nothing",
}


def _runbook_names() -> list[str]:
    """Dotted runbook names, e.g. 'services.install_from_git'.

    Walks the package the same way discovery does, so a module this gate would
    reject cannot hide by being unimportable or by sitting outside a category.
    """
    prefix = _runbook_pkg.__name__ + "."
    return sorted(
        name.removeprefix(prefix)
        for _, name, ispkg in pkgutil.walk_packages(_runbook_pkg.__path__, prefix)
        if not ispkg
    )


def test_every_runbook_uses_a_documented_prefix() -> None:
    offenders = sorted(
        name
        for name in _runbook_names()
        if name not in ALLOWED_EXCEPTIONS and not name.rpartition(".")[2].startswith(_PREFIXES)
    )
    assert not offenders, (
        f"These runbooks are named neither install_* nor enable_*: {offenders}. "
        f"Rename to install_* (a one-time binary/package install) or enable_* (a "
        f"service that keeps running), or -- if it is an operation on an "
        f"already-provisioned machine rather than a provisioning step -- add it to "
        f"ALLOWED_EXCEPTIONS in this file with the reason."
    )


def test_no_allowlisted_runbook_has_disappeared() -> None:
    """A renamed or deleted runbook must not leave its exemption behind.

    A stale entry silently pre-approves whatever later takes that name.
    """
    stale = sorted(set(ALLOWED_EXCEPTIONS) - set(_runbook_names()))
    assert not stale, (
        f"ALLOWED_EXCEPTIONS names runbooks that no longer exist: {stale}. "
        f"Remove them -- an exemption outliving its module pre-approves the next "
        f"thing to claim that name."
    )


def test_no_allowlisted_runbook_would_pass_anyway() -> None:
    """An exemption for a name that already conforms is noise."""
    redundant = sorted(
        name for name in ALLOWED_EXCEPTIONS if name.rpartition(".")[2].startswith(_PREFIXES)
    )
    assert not redundant, (
        f"These ALLOWED_EXCEPTIONS entries already match the convention: {redundant}. "
        f"Remove them from the allowlist."
    )
