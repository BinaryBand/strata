"""Unit tests for strata.cli.dispatch.

`guard_executor.execute` is monkeypatched throughout so no playbook ever runs,
and XDG_STATE_HOME is redirected to a tmp dir so the real last-target state
file is never read or written.
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest
import typer

from strata.adapters import guard_executor
from strata.adapters import state as state_mod
from strata.cli import dispatch
from strata.cli.wiring import TyperReporter
from strata.core.models import AppState


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point AppState persistence at a scratch XDG state dir."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    # The legacy-location migration would otherwise touch the repo.
    monkeypatch.setattr(state_mod, "_OLD_CONFIG_FILE", tmp_path / "absent.json")
    # Default every dispatch test to a non-tty so the host picker never fires;
    # the picker tests below opt back into a tty explicitly.
    monkeypatch.setattr(dispatch.sys.stdin, "isatty", lambda: False)
    return tmp_path


@pytest.fixture
def executions(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """Record guard_executor.execute calls instead of provisioning anything."""
    calls: list[dict[str, object]] = []

    def fake_execute(
        module: types.ModuleType,
        *,
        target: str | None,
        tags: list[str] | None = None,
        reporter: object | None = None,
    ) -> int:
        calls.append(
            {"module": module.__name__, "target": target, "tags": tags, "reporter": reporter}
        )
        return 0

    monkeypatch.setattr(guard_executor, "execute", fake_execute)
    return calls


# -- target resolution ---------------------------------------------------


def test_run_runbook_uses_explicit_target(executions: list[dict[str, object]]) -> None:
    rc = dispatch.run_runbook("install_jellyfin", target="workstation")
    assert rc == 0
    assert executions[0]["target"] == "workstation"


def test_run_runbook_persists_explicit_target(executions: list[dict[str, object]]) -> None:
    dispatch.run_runbook("install_jellyfin", target="workstation")
    assert state_mod.load().last_target == "workstation"
    assert executions


def test_run_runbook_falls_back_to_stored_target(executions: list[dict[str, object]]) -> None:
    state = state_mod.load()
    state.last_target = "Rpi4"
    state_mod.save(state)

    rc = dispatch.run_runbook("install_jellyfin")
    assert rc == 0
    assert executions[0]["target"] == "Rpi4"


def test_run_runbook_without_any_target_errors(
    executions: list[dict[str, object]], capsys: pytest.CaptureFixture[str]
) -> None:
    rc = dispatch.run_runbook("install_jellyfin")
    assert rc == 1
    assert "No target specified" in capsys.readouterr().err
    assert executions == []


def test_run_runbook_does_not_clobber_stored_target_when_omitted(
    executions: list[dict[str, object]],
) -> None:
    state = state_mod.load()
    state.last_target = "Rpi4"
    state_mod.save(state)

    dispatch.run_runbook("install_jellyfin")
    assert state_mod.load().last_target == "Rpi4"
    assert executions


# -- name resolution -----------------------------------------------------


def test_run_runbook_resolves_bare_leaf_to_dotted_module(
    executions: list[dict[str, object]],
) -> None:
    dispatch.run_runbook("install_jellyfin", target="workstation")
    assert executions[0]["module"] == "strata.core.runbooks.services.install_jellyfin"


def test_run_runbook_accepts_dotted_name(executions: list[dict[str, object]]) -> None:
    dispatch.run_runbook("services.install_jellyfin", target="workstation")
    assert executions[0]["module"] == "strata.core.runbooks.services.install_jellyfin"


def test_run_runbook_unknown_name_reports_and_suggests(
    executions: list[dict[str, object]], capsys: pytest.CaptureFixture[str]
) -> None:
    rc = dispatch.run_runbook("install_jelyfin", target="workstation")
    assert rc == 1
    err = capsys.readouterr().err
    assert "Unknown runbook: 'install_jelyfin'" in err
    assert "Did you mean" in err
    assert "install_jellyfin" in err
    assert executions == []


def test_run_runbook_unknown_unsuggestible_name_omits_suggestion(
    executions: list[dict[str, object]], capsys: pytest.CaptureFixture[str]
) -> None:
    rc = dispatch.run_runbook("zzzzzzzzzzzz", target="workstation")
    assert rc == 1
    err = capsys.readouterr().err
    assert "Unknown runbook" in err
    assert "Did you mean" not in err
    assert executions == []


# -- tags forwarding -----------------------------------------------------


def test_tags_are_parsed_for_runbooks_that_accept_them(
    executions: list[dict[str, object]],
) -> None:
    dispatch.run_runbook("infrastructure.backup", target="workstation", tags=" jellyfin , config ,")
    assert executions[0]["tags"] == ["jellyfin", "config"]


def test_tags_are_dropped_for_runbooks_that_do_not_accept_them(
    executions: list[dict[str, object]],
) -> None:
    dispatch.run_runbook("services.install_jellyfin", target="workstation", tags="jellyfin")
    assert executions[0]["tags"] is None


def test_no_tags_argument_passes_none(executions: list[dict[str, object]]) -> None:
    dispatch.run_runbook("infrastructure.backup", target="workstation")
    assert executions[0]["tags"] is None


# -- reporter wiring -----------------------------------------------------


def test_run_runbook_hands_a_typer_reporter_to_the_executor(
    executions: list[dict[str, object]],
) -> None:
    dispatch.run_runbook("install_jellyfin", target="workstation")
    assert isinstance(executions[0]["reporter"], TyperReporter)


# -- exit code passthrough -----------------------------------------------


def test_run_runbook_returns_executor_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guard_executor, "execute", lambda *_a, **_kw: 42)
    assert dispatch.run_runbook("install_jellyfin", target="workstation") == 42


# -- maybe_apply --------------------------------------------------------


def test_maybe_apply_without_flag_prints_hint(capsys: pytest.CaptureFixture[str]) -> None:
    dispatch.maybe_apply(
        apply_flag=False, target="workstation", apply_runbook="infrastructure.backup"
    )
    out = capsys.readouterr().out
    assert (
        out.strip() == "Run `strata runbook infrastructure.backup --target workstation` to apply."
    )


def test_maybe_apply_with_flag_runs_and_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str | None]] = []

    def fake_run(name: str, target: str | None = None, **_kw: object) -> int:
        calls.append((name, target))
        return 3

    monkeypatch.setattr(dispatch, "run_runbook", fake_run)
    with pytest.raises(typer.Exit) as excinfo:
        dispatch.maybe_apply(
            apply_flag=True, target="workstation", apply_runbook="infrastructure.backup"
        )
    assert excinfo.value.exit_code == 3
    assert calls == [("infrastructure.backup", "workstation")]


# -- listing / completion ------------------------------------------------


def test_list_runbooks_groups_by_category(capsys: pytest.CaptureFixture[str]) -> None:
    dispatch.show_runbook_list()
    out = capsys.readouterr().out
    assert "services" in out
    assert "install_jellyfin" in out
    # Leaves are printed bare under their category header, not dotted.
    assert "services.install_jellyfin" not in out


def test_runbook_completer_filters_by_prefix() -> None:
    matches = dispatch.runbook_completer("services.")
    assert matches
    assert all(m.startswith("services.") for m in matches)
    assert "services.install_jellyfin" in matches


def test_runbook_completer_no_match_returns_empty() -> None:
    assert dispatch.runbook_completer("nope.") == []


# -- host picker (--target omitted on a tty) -----------------------------


def test_omitting_target_on_a_tty_opens_the_host_picker(
    monkeypatch: pytest.MonkeyPatch, executions: list[dict[str, object]]
) -> None:
    monkeypatch.setattr(dispatch.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(dispatch, "pick_host", lambda **_: "nas")
    rc = dispatch.run_runbook("install_jellyfin")
    assert rc == 0
    assert executions[0]["target"] == "nas"


def test_aborting_the_host_picker_runs_nothing(
    monkeypatch: pytest.MonkeyPatch, executions: list[dict[str, object]]
) -> None:
    monkeypatch.setattr(dispatch.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(dispatch, "pick_host", lambda **_: None)
    rc = dispatch.run_runbook("install_jellyfin")
    assert rc == 1
    assert executions == []


def test_host_picker_defaults_to_the_last_target(
    monkeypatch: pytest.MonkeyPatch, executions: list[dict[str, object]]
) -> None:
    state_mod.save(AppState(last_target="nas"))
    seen: dict[str, str | None] = {}

    def fake_pick(default: str | None = None) -> str:
        seen["default"] = default
        return "workstation"

    monkeypatch.setattr(dispatch.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(dispatch, "pick_host", fake_pick)
    dispatch.run_runbook("install_jellyfin")
    assert seen["default"] == "nas"
    assert executions[0]["target"] == "workstation"


def test_omitting_target_off_tty_still_reuses_the_stored_target(
    executions: list[dict[str, object]],
) -> None:
    # isatty is forced False by the autouse fixture: no picker, silent reuse.
    state_mod.save(AppState(last_target="nas"))
    rc = dispatch.run_runbook("install_jellyfin")
    assert rc == 0
    assert executions[0]["target"] == "nas"
