"""Persistent application state via Pydantic models using XDG Base Directory spec."""

import os
from pathlib import Path

from strata.adapters import fs
from strata.core.models import AppState


def _state_path() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    state_dir = base / "strata"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "state.json"


def load() -> AppState:
    """Return the persisted AppState.

    A corrupt state file falls back to defaults rather than raising: this
    holds nothing but the last target used, so losing it costs one `--target`
    flag, while raising makes every command fail with a traceback until the
    file is deleted by hand.

    Returns:
        The state read from the XDG state file, or a default AppState if it
        is absent, unreadable, or malformed.
    """
    path = _state_path()
    if not path.exists():
        return AppState()
    try:
        return AppState.model_validate_json(path.read_text())
    except (OSError, ValueError):
        return AppState()


def save(state: AppState) -> None:
    """Write `state` as indented JSON to the XDG state file.

    Args:
        state: The application state to persist.
    """
    fs.write_text(_state_path(), state.model_dump_json(indent=2) + "\n")
