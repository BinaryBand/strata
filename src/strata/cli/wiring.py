"""Compose adapters for the CLI.

The composition root. cli is the one layer allowed to decide that "reporting
progress" means "write to this terminal", so the concrete Reporter is built
here and handed to the adapters that need one.
"""

from __future__ import annotations

import typer

from strata.adapters.ansible import runner


class TyperReporter:
    """Writes progress to the terminal through Typer."""

    def info(self, message: str) -> None:
        """Echo `message` to stdout."""
        typer.echo(message)


def build_reporter() -> TyperReporter:
    """Return the reporter, installing it wherever adapters need one implicitly."""
    reporter = TyperReporter()
    runner.set_reporter(reporter)
    return reporter
