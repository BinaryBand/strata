"""pytest-bdd binding for features/runbook_dispatch.feature (discover + launch).

Dispatch is pure control-flow. Fakes: guard_executor.execute records the
(module, target, tags) it would run and returns a code instead of satisfying
guards / running playbooks; the XDG state file is redirected to tmp (real
AppState logic); main.pick_runbook is stubbed for the picker scenarios. Name
resolution / --list run the real discovery walk over the actual runbook package.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest
from pytest_bdd import given, parsers, scenarios, then

from strata.adapters import guard_executor, state
from strata.cli import main
from strata.core.models import AppState

scenarios("runbook_dispatch.feature")


@pytest.fixture(autouse=True)
def _isolate_dispatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ctx: dict[str, Any]) -> None:
    # State: real AppState logic against a throwaway XDG dir; block legacy migration.
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(state, "_OLD_CONFIG_FILE", tmp_path / "no-legacy.json")

    # guard_executor.execute: record instead of satisfying guards / running playbooks.
    calls: list[dict[str, Any]] = []

    def fake_execute(
        module: Any, *, target: str | None, tags: list[str] | None = None, **_: Any
    ) -> int:
        calls.append({"module": module.__name__, "target": target, "tags": tags})
        return ctx.get("main_rc", 0)

    monkeypatch.setattr(guard_executor, "execute", fake_execute)
    ctx["execute_calls"] = calls


# ── Given ─────────────────────────────────────────────────────────────────


@given(parsers.parse('the runbook "{dotted}" fails to import'))
def runbook_fails_import(monkeypatch: pytest.MonkeyPatch, dotted: str) -> None:
    real_import = importlib.import_module
    broken = f"strata.core.runbooks.{dotted}"

    def flaky(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == broken:
            msg = "simulated import failure"
            raise ImportError(msg)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("strata.core.discovery.importlib.import_module", flaky)


@given(parsers.parse('the picker will choose "{dotted}"'))
def picker_chooses(ctx: dict[str, Any], monkeypatch: pytest.MonkeyPatch, dotted: str) -> None:
    def spy() -> str:
        ctx["picker_called"] = True
        return dotted

    monkeypatch.setattr(main, "pick_runbook", spy)


@given("the picker returns nothing because stdin is not a terminal")
def picker_returns_none(ctx: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    def spy() -> None:
        ctx["picker_called"] = True

    monkeypatch.setattr(main, "pick_runbook", spy)


@given(parsers.parse('a previous target "{target}" is stored'))
def previous_target_stored(target: str) -> None:
    state.save(AppState(last_target=target))


@given("no target has ever been used")
def no_previous_target() -> None:
    """No-op: the redirected XDG state starts empty."""


@given(parsers.parse("the runbook's main() returns {code:d}"))
def main_returns(ctx: dict[str, Any], code: int) -> None:
    ctx["main_rc"] = code


# ── Then ──────────────────────────────────────────────────────────────────


@then(parsers.parse('the runbook "{dotted}" is executed against "{target}"'))
def executed_against(ctx: dict[str, Any], dotted: str, target: str) -> None:
    calls = ctx["execute_calls"]
    assert calls, "expected a runbook to execute"
    assert calls[-1]["module"].endswith(dotted)
    assert calls[-1]["target"] == target


@then("no runbook is executed")
def no_runbook_executed(ctx: dict[str, Any]) -> None:
    assert ctx["execute_calls"] == []


@then("the picker was offered")
def picker_was_offered(ctx: dict[str, Any]) -> None:
    assert ctx.get("picker_called") is True


@then(parsers.parse('"{target}" is saved as the last used target'))
def target_saved(target: str) -> None:
    assert state.load().last_target == target


@then(parsers.parse('the runbook is executed with tags "{tags}"'))
def executed_with_tags(ctx: dict[str, Any], tags: str) -> None:
    assert ctx["execute_calls"][-1]["tags"] == tags.split(",")


@then("the runbook is executed with no tags")
def executed_without_tags(ctx: dict[str, Any]) -> None:
    assert ctx["execute_calls"][-1]["tags"] is None
