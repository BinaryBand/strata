"""Persistent application state via Pydantic models using XDG Base Directory spec."""

import json
import os
from pathlib import Path

from strata.adapters import fs
from strata.core import paths
from strata.core.models import AppState

_OLD_CONFIG_FILE = paths.PROJECT_ROOT / ".mr_manager.json"


def _old_state_path() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "mr_manager" / "state.json"


def _state_path() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    state_dir = base / "strata"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "state.json"


def _migrate_from_old_xdg_name() -> None:
    """Adopt the state file from the pre-rename `mr_manager` XDG dir, once.

    Same shape as _migrate_from_old_location below, one XDG rename earlier:
    an existing new-path file always wins, and a malformed old file is
    discarded rather than left to fail the same way on every invocation.
    """
    old_path = _old_state_path()
    if not old_path.exists():
        return
    if not _state_path().exists():
        try:
            old_data = json.loads(old_path.read_text())
            save(AppState(**{k: v for k, v in old_data.items() if k in AppState.model_fields}))
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    old_path.unlink(missing_ok=True)


def _migrate_from_old_location() -> None:
    """Adopt the legacy repo-local state file, once, if there is nothing newer.

    Two things make this delicate. The legacy path is PROJECT_ROOT-relative,
    so a stray .mr_manager.json reappears on any fresh clone or branch switch
    -- and this used to save() unconditionally, overwriting whatever the XDG
    file already held with the older value. An existing XDG file therefore
    wins, and the legacy file is retired rather than applied.

    The old file is also arbitrary JSON a human may have edited. Narrowing the
    except to JSONDecodeError/OSError meant a legacy `{"last_target": 3}`
    raised ValidationError and a top-level array raised AttributeError, and
    since the unlink only ran after a successful save, the same exception
    recurred on every single invocation -- the CLI stayed unusable until the
    file was found and deleted by hand. Anything unusable is now discarded.
    """
    if not _OLD_CONFIG_FILE.exists():
        return
    if not _state_path().exists():
        try:
            old_data = json.loads(_OLD_CONFIG_FILE.read_text())
            save(AppState(**{k: v for k, v in old_data.items() if k in AppState.model_fields}))
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    _OLD_CONFIG_FILE.unlink(missing_ok=True)


def load() -> AppState:
    """Return the persisted AppState, migrating from the legacy repo-local file first.

    A corrupt state file falls back to defaults rather than raising: this
    holds nothing but the last target used, so losing it costs one `--target`
    flag, while raising makes every command fail with a traceback until the
    file is deleted by hand. The tolerant handling of the legacy file above
    would have made no sense next to a hard failure here.

    Returns:
        The state read from the XDG state file, or a default AppState if it
        is absent, unreadable, or malformed.
    """
    _migrate_from_old_xdg_name()
    _migrate_from_old_location()
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
