"""Unit tests for strata.adapters.proc.

These run real, universally available binaries (`echo`, `true`) rather than
mocking subprocess -- the whole point of the module is what it does to argv[0].
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from strata.adapters import proc

_MISSING = "definitely-not-a-real-binary-xyzzy"


# ── resolve() ─────────────────────────────────────────────────────────


def test_resolve_returns_absolute_path() -> None:
    resolved = proc.resolve("echo")
    assert resolved == shutil.which("echo")
    assert resolved.startswith("/")


def test_resolve_missing_binary_raises_naming_it() -> None:
    with pytest.raises(proc.CommandNotFoundError) as excinfo:
        proc.resolve(_MISSING)
    assert _MISSING in str(excinfo.value)


def test_command_not_found_is_a_runtime_error() -> None:
    assert issubclass(proc.CommandNotFoundError, RuntimeError)


# ── run() ─────────────────────────────────────────────────────────────


def test_run_resolves_argv0_to_an_absolute_path(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []

    def spy(argv, **kwargs):  # noqa: ARG001
        seen.append(list(argv))
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(proc.subprocess, "run", spy)
    proc.run(["echo", "hello"], capture_output=True, text=True)

    assert len(seen) == 1
    assert seen[0][0] == shutil.which("echo")
    assert seen[0][1:] == ["hello"]


def test_run_missing_binary_raises_before_spawning() -> None:
    with pytest.raises(proc.CommandNotFoundError):
        proc.run([_MISSING, "--version"])


def test_run_captures_stdout_as_text() -> None:
    result = proc.run(["echo", "hello"], capture_output=True, text=True)
    assert result.stdout == "hello\n"
    assert result.returncode == 0


def test_run_without_capture_leaves_stdout_none() -> None:
    result = proc.run(["true"])
    assert result.stdout is None
    assert result.returncode == 0


def test_run_passes_input_to_stdin() -> None:
    result = proc.run(["cat"], input="piped", capture_output=True, text=True)
    assert result.stdout == "piped"


def test_run_check_false_returns_nonzero_instead_of_raising() -> None:
    result = proc.run(["false"])
    assert result.returncode != 0


def test_run_check_true_raises_on_nonzero() -> None:
    with pytest.raises(subprocess.CalledProcessError):
        proc.run(["false"], check=True)
