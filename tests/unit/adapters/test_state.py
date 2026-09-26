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
    """Point XDG_STATE_HOME at a scratch location."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
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
