"""Shared pytest-bdd fixtures and step vocabulary for the CLI feature suite.

The .feature files in this directory are the user-story spec; these steps drive
the `strata` CLI through Typer's CliRunner, so no real Ansible, vault or
inventory work happens. Feature-specific steps live alongside their
``scenarios(...)`` binding in the per-feature ``test_<name>.py`` modules.
"""

from __future__ import annotations

import shlex
from typing import Any

import pytest
from pytest_bdd import parsers, then, when
from typer.testing import CliRunner

from strata.cli.main import app

_runner = CliRunner()


@pytest.fixture
def ctx() -> dict[str, Any]:
    """Mutable bag threading the last CLI result between steps."""
    return {}


# ── shared step vocabulary ──────────────────────────────────────────────


@when(parsers.parse('I run "strata {argstr}"'))
def run_strata(ctx: dict[str, Any], argstr: str) -> None:
    """Invoke ``strata <argstr>`` via CliRunner and stash the result on ctx."""
    ctx["result"] = _runner.invoke(app, shlex.split(argstr))


@when(parsers.parse('I run "strata {argstr}" and enter "{answer}"'))
def run_strata_with_input(ctx: dict[str, Any], argstr: str, answer: str) -> None:
    """Invoke ``strata <argstr>`` feeding `answer` to its prompt(s).

    The answer is fed three times: a plain prompt consumes one line, a
    confirmation prompt consumes two matching lines, and any surplus is ignored
    -- so one step drives both prompt shapes.
    """
    stdin = (answer + "\n") * 3
    ctx["result"] = _runner.invoke(app, shlex.split(argstr), input=stdin)


@then(parsers.parse("the exit code is {code:d}"))
def exit_code_is(ctx: dict[str, Any], code: int) -> None:
    assert ctx["result"].exit_code == code


@then(parsers.parse('the output contains "{text}"'))
def output_contains(ctx: dict[str, Any], text: str) -> None:
    assert text in ctx["result"].output


@then(parsers.parse('the output does not contain "{text}"'))
def output_excludes(ctx: dict[str, Any], text: str) -> None:
    assert text not in ctx["result"].output


@then("the exit code is non-zero")
def exit_code_nonzero(ctx: dict[str, Any]) -> None:
    assert ctx["result"].exit_code != 0


@then(parsers.parse('the output tells me to use "{hint}"'))
def output_tells_me_to_use(ctx: dict[str, Any], hint: str) -> None:
    assert hint in ctx["result"].output


@then(parsers.parse('it reports {noun} "{name}" was not found'))
def reports_not_found(ctx: dict[str, Any], noun: str, name: str) -> None:
    # Matches the adapters' not_found() format: `<noun> '<name>' not found`.
    assert f"{noun} {name!r} not found" in ctx["result"].output
