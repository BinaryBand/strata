"""Compose adapters for the CLI.

The composition root. cli is the one layer allowed to decide that "reporting
progress" means "write to this terminal" and that "asking the operator" means
"prompt on it", so the concrete Reporter and Prompter are built here and
handed to the adapters that need one.
"""

from __future__ import annotations

import typer

from strata.adapters.ansible import runner


class TyperReporter:
    """Writes progress to the terminal through Typer."""

    def info(self, message: str) -> None:
        """Echo `message` to stdout."""
        typer.echo(message)


class TyperPrompter:
    """Asks on the terminal through Typer."""

    def ask(self, message: str, *, default: str | None = None, hidden: bool = False) -> str:
        """Prompt for `message`; a blank answer returns `default`, or "" when there is none."""
        return typer.prompt(
            message, default=default or "", show_default=default is not None, hide_input=hidden
        )

    def tell(self, message: str) -> None:
        """Echo `message` to stderr."""
        typer.echo(message, err=True)


def build_prompter() -> TyperPrompter:
    """Return the terminal prompter."""
    return TyperPrompter()


def build_reporter() -> TyperReporter:
    """Return the reporter, installing it wherever adapters need one implicitly."""
    reporter = TyperReporter()
    runner.set_reporter(reporter)
    return reporter
