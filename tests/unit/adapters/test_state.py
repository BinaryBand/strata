"""Unit tests for strata.adapters.state.

XDG_STATE_HOME is redirected at tmp_path so nothing touches the real
~/.local/state, and the legacy repo-local file is redirected too.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from strata.adapters import state
from strata.core.models import AppState


@pytest.fixture(autouse=True)
def xdg_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point XDG_STATE_HOME and the legacy config file at scratch locations."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(state, "_OLD_CONFIG_FILE", tmp_path / "old" / ".mr_manager.json")
    return tmp_path / "state" / "strata" / "state.json"


# ── _state_path() ─────────────────────────────────────────────────────


def test_state_path_honours_xdg_state_home(xdg_state: Path) -> None:
    assert state._state_path() == xdg_state


def test_state_path_creates_the_directory(xdg_state: Path) -> None:
    assert state._state_path().parent.is_dir()
    assert xdg_state.parent.is_dir()


def test_state_path_falls_back_to_home_local_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    assert state._state_path() == Path.home() / ".local" / "state" / "strata" / "state.json"


# ── load()/save() ─────────────────────────────────────────────────────


def test_load_returns_default_when_nothing_persisted() -> None:
    assert state.load() == AppState()
    assert state.load().last_target is None


def test_save_then_load_round_trips() -> None:
    state.save(AppState(last_target="workstation"))
    assert state.load().last_target == "workstation"


def test_save_writes_indented_json_with_trailing_newline(xdg_state: Path) -> None:
    state.save(AppState(last_target="workstation"))

    text = xdg_state.read_text()
    assert text.endswith("\n")
    assert json.loads(text) == {"last_target": "workstation"}
    assert "\n  " in text  # indent=2


def test_save_overwrites_previous_state() -> None:
    state.save(AppState(last_target="workstation"))
    state.save(AppState(last_target="Rpi4"))
    assert state.load().last_target == "Rpi4"


def test_load_falls_back_to_defaults_on_a_malformed_state_file(xdg_state: Path) -> None:
    """A corrupt state file must not make every command raise.

    This holds only the last target used, so falling back costs one --target
    flag; raising made the whole CLI unusable until the file was deleted by
    hand, which is a poor trade for a cache.
    """
    xdg_state.parent.mkdir(parents=True, exist_ok=True)
    xdg_state.write_text("not json")

    assert state.load() == AppState()


# ── migration from the legacy repo-local file ─────────────────────────


def _seed_old(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, payload: str) -> Path:
    old = tmp_path / "old" / ".mr_manager.json"
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text(payload)
    monkeypatch.setattr(state, "_OLD_CONFIG_FILE", old)
    return old


def test_load_migrates_legacy_file_and_deletes_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, xdg_state: Path
) -> None:
    old = _seed_old(monkeypatch, tmp_path, json.dumps({"last_target": "Legacy"}))

    assert state.load().last_target == "Legacy"
    assert not old.exists()
    assert xdg_state.exists()


def test_migration_drops_unknown_legacy_keys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _seed_old(monkeypatch, tmp_path, json.dumps({"last_target": "Legacy", "gone": "field"}))

    loaded = state.load()
    assert loaded.last_target == "Legacy"
    assert not hasattr(loaded, "gone")


def test_corrupt_legacy_file_is_ignored_and_retired(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An unusable legacy file is discarded, not left to fail again forever.

    Leaving it in place meant every subsequent command re-read the same
    broken file. Worse, the legacy path is PROJECT_ROOT-relative, so it is
    not somewhere the operator would think to look.
    """
    old = _seed_old(monkeypatch, tmp_path, "{ not json")

    assert state.load() == AppState()
    assert not old.exists()


def test_legacy_file_with_a_wrong_typed_field_does_not_brick_the_cli(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """ValidationError was outside the except, so this recurred every run."""
    old = _seed_old(monkeypatch, tmp_path, json.dumps({"last_target": 3}))

    assert state.load() == AppState()
    assert not old.exists()


def test_legacy_top_level_array_does_not_brick_the_cli(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`.items()` on a list raised AttributeError, also outside the except."""
    old = _seed_old(monkeypatch, tmp_path, json.dumps(["not", "a", "mapping"]))

    assert state.load() == AppState()
    assert not old.exists()


def test_existing_xdg_state_is_not_overwritten_by_the_legacy_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, xdg_state: Path
) -> None:
    """The legacy path is repo-relative, so a stray file reappears on a clone.

    Migration used to save() unconditionally, so that stray file silently
    reset last_target to an older value on the next command.
    """
    state.save(AppState(last_target="Current"))
    old = _seed_old(monkeypatch, tmp_path, json.dumps({"last_target": "Ancient"}))

    assert state.load().last_target == "Current"
    assert xdg_state.exists()
    assert not old.exists()


def test_migration_does_not_run_when_no_legacy_file_exists(xdg_state: Path) -> None:
    assert state.load() == AppState()
    assert not xdg_state.exists()


# ── migration from the pre-rename `mr_manager` XDG dir ─────────────────


def _seed_old_xdg(payload: str) -> Path:
    old = state._old_state_path()
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text(payload)
    return old


def test_load_migrates_old_xdg_state_and_deletes_it(xdg_state: Path) -> None:
    old = _seed_old_xdg(json.dumps({"last_target": "Legacy"}))

    assert state.load().last_target == "Legacy"
    assert not old.exists()
    assert xdg_state.exists()


def test_corrupt_old_xdg_state_is_ignored_and_retired(xdg_state: Path) -> None:
    old = _seed_old_xdg("{ not json")

    assert state.load() == AppState()
    assert not old.exists()
    assert not xdg_state.exists()


def test_existing_new_xdg_state_is_not_overwritten_by_the_old_xdg_state(
    xdg_state: Path,
) -> None:
    state.save(AppState(last_target="Current"))
    old = _seed_old_xdg(json.dumps({"last_target": "Ancient"}))

    assert state.load().last_target == "Current"
    assert xdg_state.exists()
    assert not old.exists()


def test_old_xdg_migration_does_not_run_when_nothing_is_there(xdg_state: Path) -> None:
    assert state.load() == AppState()
    assert not xdg_state.exists()
