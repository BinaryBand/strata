"""Unit tests for strata.cli.wiring -- the reporter composition root."""

from __future__ import annotations

import pytest

from strata.adapters.ansible import runner
from strata.cli.wiring import TyperReporter, build_reporter


class _Sentinel:
    """Stands in for whatever reporter the runner happens to hold."""

    def info(self, message: str) -> None:
        """Swallow the message."""


@pytest.fixture(autouse=True)
def _isolate_runner_reporter() -> object:
    """build_reporter mutates module state; reset it around every test."""
    original = runner._reporter
    runner._reporter = _Sentinel()
    yield
    runner._reporter = original


def test_build_reporter_returns_typer_reporter() -> None:
    assert isinstance(build_reporter(), TyperReporter)


def test_build_reporter_installs_itself_on_runner() -> None:
    """The returned reporter is the exact object the runner will report through."""
    assert not isinstance(runner._reporter, TyperReporter)
    reporter = build_reporter()
    assert runner._reporter is reporter


def test_typer_reporter_info_writes_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    TyperReporter().info("provisioning jellyfin")
    captured = capsys.readouterr()
    assert captured.out == "provisioning jellyfin\n"
    assert captured.err == ""


def test_installed_reporter_carries_runner_output(capsys: pytest.CaptureFixture[str]) -> None:
    """After wiring, runner-side progress lands on stdout rather than being dropped."""
    build_reporter()
    runner._reporter.info("  [ok] install podman")
    assert "[ok] install podman" in capsys.readouterr().out
