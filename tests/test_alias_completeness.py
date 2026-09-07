"""Every runbook must declare a human-friendly @guard.alias.

This is the gate that makes @guard.alias effectively required: a new runbook
without one fails here rather than silently showing its dotted/leaf name in the
picker and --list. Aliases must also be unique, since the picker maps the chosen
alias back to a single dotted name.
"""

from __future__ import annotations

from strata.core.discovery import iter_runbooks


def test_every_runbook_declares_an_alias() -> None:
    missing = [rb.dotted_name for rb in iter_runbooks() if not rb.alias]
    assert not missing, f"runbooks missing @guard.alias(...): {missing}"


def test_runbook_aliases_are_unique() -> None:
    aliases = [rb.alias for rb in iter_runbooks() if rb.alias]
    dupes = sorted({a for a in aliases if aliases.count(a) > 1})
    assert not dupes, f"duplicate runbook aliases (picker would map them ambiguously): {dupes}"
