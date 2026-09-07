"""Interactive runbook picker: one autocomplete over a flat list of runbooks.

Its own module rather than more helpers in dispatch.py so that questionary --
the only prompt_toolkit dependency in the project -- has exactly one import
site, and so tests have exactly one seam (`_autocomplete`) to replace instead
of driving a real terminal.
"""

from __future__ import annotations

import sys

import questionary

from strata.adapters.ansible import inventory
from strata.core.discovery import RunbookInfo, iter_runbooks


def _autocomplete(message: str, choices: list[str], meta: dict[str, str]) -> str | None:
    """Render the autocomplete prompt and return the chosen value, or None if aborted.

    The single seam over questionary: tests monkeypatch this rather than driving
    prompt_toolkit. ``ask()`` returns None on Ctrl-C/Esc. ``validate`` keeps the
    free-text field honest -- only a known dotted name submits.
    """
    answer = questionary.autocomplete(
        message,
        choices=choices,
        meta_information=meta,
        match_middle=True,
        validate=lambda text: text in choices or "Pick a runbook from the list.",
    ).ask()
    return None if answer is None else str(answer)


def _select(message: str, choices: list[questionary.Choice], default: str | None) -> str | None:
    """Render a select prompt and return the chosen value, or None if aborted.

    A second seam over questionary -- the host picker is a short arrow-key list,
    not type-ahead. Tests monkeypatch this. ``ask()`` returns None on Ctrl-C/Esc.
    """
    answer = questionary.select(message, choices=choices, default=default).ask()
    return None if answer is None else str(answer)


def _summary(runbook: RunbookInfo) -> str:
    """One-line description, without the 'Runbook:' prefix every module repeats."""
    return runbook.docstring_first_line.removeprefix("Runbook:").strip()


def pick_host(default: str | None = None) -> str | None:
    """Pick a target host interactively and return its inventory name.

    Lists every inventory host (the local controller plus remote devices) with
    its connection type, defaulting to `default` (usually the last target) so
    Enter reuses it. Returns None off a tty or on abort, so callers keep their
    non-interactive behaviour (scripts reuse the stored target or error).
    """
    if not sys.stdin.isatty():
        return None
    hosts = inventory.all_hosts()
    if not hosts:
        return None
    choices = [questionary.Choice(title=f"{h.name}  ({h.connection})", value=h.name) for h in hosts]
    valid_default = default if any(h.name == default for h in hosts) else None
    return _select("Target host:", choices, valid_default)


def pick_runbook() -> str | None:
    """Pick a runbook interactively and return its dotted name.

    Presents every runbook in one autocomplete field (type any part of the name
    -- ``match_middle`` -- with the one-line summary shown as meta). Returns None
    when there is nothing to pick from, when stdin is not a terminal (scripts,
    pipes, CliRunner), or when the user aborts -- so callers keep whatever
    non-interactive behaviour they had.
    """
    if not sys.stdin.isatty():
        return None

    runbooks = iter_runbooks()
    if not runbooks:
        return None

    # Offer the friendly alias (falling back to the leaf) and map the pick back
    # to the dotted name, so what the operator reads/types is readable while
    # dispatch still receives the resolvable name. iter_runbooks() is sorted by
    # dotted name, so the flat list stays grouped by category.
    to_dotted = {(rb.alias or rb.leaf): rb.dotted_name for rb in runbooks}
    meta = {(rb.alias or rb.leaf): _summary(rb) for rb in runbooks}
    chosen = _autocomplete("Runbook:", list(to_dotted), meta)
    return None if chosen is None else to_dotted.get(chosen, chosen)
