"""Unit tests for strata.cli._helpers.

Covers the two UX helpers (`not_found`, `apply_hint`).
"""

from __future__ import annotations

import pytest
import typer

from strata.cli._helpers import apply_hint, not_found

# -- not_found -----------------------------------------------------------


def test_not_found_raises_exit_1() -> None:
    with pytest.raises(typer.Exit) as excinfo:
        not_found("widget", "nope")
    assert excinfo.value.exit_code == 1


def test_not_found_writes_message_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(typer.Exit):
        not_found("widget", "nope")
    captured = capsys.readouterr()
    assert "widget 'nope' not found." in captured.err
    assert captured.out == ""


def test_not_found_is_annotated_noreturn() -> None:
    """The NoReturn annotation is load-bearing: callers skip re-narrowing after it."""
    assert not_found.__annotations__["return"] == "NoReturn"


# -- apply_hint ----------------------------------------------------------


def test_apply_hint_without_target_has_no_suffix() -> None:
    assert apply_hint("services.install_baikal") == (
        "Run `strata runbook services.install_baikal` to apply."
    )


def test_apply_hint_with_target_appends_target_flag() -> None:
    assert apply_hint("services.install_baikal", target="workstation") == (
        "Run `strata runbook services.install_baikal --target workstation` to apply."
    )


def test_apply_hint_empty_target_is_treated_as_absent() -> None:
    assert "--target" not in apply_hint("infrastructure.backup", target="")
