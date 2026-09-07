"""Runbook dispatch and the helpers command groups share.

Separate from main.py so command modules can use run_runbook() without
importing main, which imports them -- the cycle that would otherwise force
every group back into one file.
"""

from __future__ import annotations

import importlib
import sys
from itertools import groupby

import typer

from strata.adapters import guard_executor
from strata.adapters import state as config
from strata.cli._helpers import apply_hint
from strata.cli.picker import pick_host
from strata.cli.wiring import build_reporter
from strata.core.discovery import (
    accepts_tags,
    import_failures,
    iter_runbooks,
    resolve_name,
    suggest,
)


def run_runbook(name: str, target: str | None = None, tags: str | None = None) -> int:
    """Resolve and run a runbook by name, resolving target from arg or config."""
    state = config.load()

    # No --target: on a terminal, offer the host picker (defaulting to the last
    # target, so Enter reuses it) instead of silently inheriting it. Off a tty
    # (scripts, pipes, CliRunner) pick_host returns None and we fall through to
    # the stored target, or the error below.
    if target is None and sys.stdin.isatty():
        picked = pick_host(default=state.last_target)
        if picked is None:
            typer.echo("No target selected.", err=True)
            return 1
        target = picked

    resolved_target = target or state.last_target
    if resolved_target is None:
        typer.echo(
            "No target specified and no previous target stored. Use --target <hostname>.",
            err=True,
        )
        return 1

    if target:
        state.last_target = target
        config.save(state)

    resolved = resolve_name(name)
    if resolved is None:
        typer.echo(f"Unknown runbook: {name!r}", err=True)
        matches = suggest(name)
        if matches:
            typer.echo(f"Did you mean: {', '.join(matches)}?", err=True)
        # A runbook that fails to import is absent from resolve_name too, so
        # without this the operator is told the name is unknown -- and offered
        # spelling suggestions -- when the real problem is an ImportError in
        # the module they named.
        _report_import_failures()
        return 1

    module = importlib.import_module(f"strata.core.runbooks.{resolved}")

    parsed_tags: list[str] | None = None
    if tags is not None and accepts_tags(module.main):
        parsed_tags = [t.strip() for t in tags.split(",") if t.strip()]

    # The composition root: guard_executor satisfies whatever the runbook
    # declared, then calls its main(). Runbooks no longer provision anything
    # themselves.
    return guard_executor.execute(
        module, target=resolved_target, tags=parsed_tags, reporter=build_reporter()
    )


def _report_import_failures() -> None:
    """Print any runbook module that could not be imported, and why."""
    failures = import_failures()
    if not failures:
        return
    typer.echo("\nSome runbooks could not be imported and are missing from the list:", err=True)
    for failure in failures:
        typer.echo(f"  {failure.dotted_name}: {failure.error}", err=True)


def maybe_apply(apply_flag: bool, target: str | None, apply_runbook: str) -> None:
    """If ``--apply`` was given, run the runbook; otherwise print the hint."""
    if apply_flag:
        rc = run_runbook(apply_runbook, target=target)
        raise typer.Exit(rc)
    typer.echo(apply_hint(apply_runbook, target=target))


def runbook_completer(incomplete: str) -> list[str]:
    """Return runbook dotted names starting with `incomplete`, for tab-completion."""
    return [r.dotted_name for r in iter_runbooks() if r.dotted_name.startswith(incomplete)]


def show_runbook_list() -> None:
    """Print runbooks grouped by category with one-line docstrings."""
    runbooks = iter_runbooks()
    if not runbooks:
        typer.echo("No runbooks found.")
        _report_import_failures()
        return
    for category, items in groupby(runbooks, key=lambda r: r.category or "(root)"):
        typer.echo(f"\n{category}")
        for rb in items:
            # Friendly alias, then the leaf (the name to actually pass to
            # `strata runbook`, since resolution is by dotted/leaf not alias),
            # then the one-line summary.
            label = rb.alias or rb.leaf
            typer.echo(f"  {label:<26}{rb.leaf:<30}{rb.docstring_first_line}")
    _report_import_failures()
