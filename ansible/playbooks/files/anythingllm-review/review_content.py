"""The /review monitor's data access: allowlisted files, the database, service state.

Every screen module reads through here. Nothing here writes anything: files
are opened read-only without following symlinks, the database is opened
read-only, and secrets are listed by name and size only. Standard library only.
"""

from __future__ import annotations

import json
import os
import pwd
import re
import sqlite3
import stat
import subprocess
import time
from pathlib import Path

ROOT = Path(os.environ.get("REVIEW_ROOT", "/srv/anythingllm"))
PREFIX = os.environ.get("REVIEW_PREFIX", "/review")
MAX_VIEW_BYTES = 256 * 1024
MAX_ENTRIES = 5000
MAX_DEPTH = 12
REDACTED = "<redacted>"

# The only files whose contents may be shown, as paths relative to ROOT.
# Anything else is listed by name and size only.
VIEWABLE = [
    re.compile(p)
    for p in (
        r"storage/anythingllm-fs/.+\.(md|html|css)",
        r"storage/plugins/agent-skills/[^/]+/(plugin\.json|handler\.js|handler\.js\.draft)",
        r"storage/plugins/agent-skills/[^/]+/lib/[^/]+\.js",
        r"storage/plugins/agent-skills/[^/]+/engine/[^/]+\.(py|md)",
        r"storage/plugins/agent-skills/[^/]+/engine/contracts/[^/]+\.md",
        r"storage/plugins/agent-flows/[^/]+\.json",
        r"storage/research-runs/[^/]+/reports/final\.md",
        r"site-nginx/default\.conf",
    )
]
# Files the AI agent can write: shown, but labelled so their text is never
# mistaken for the monitor's own.
AGENT_WRITTEN = re.compile(
    r"storage/anythingllm-fs/.*|storage/plugins/agent-skills/[^/]+/handler\.js\.draft"
    r"|storage/plugins/agent-flows/.*|storage/research-runs/.*"
)
SETTING_VALUES = {"default_agent_skills", "disabled_agent_skills", "whitelisted_agent_skills"}
HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
    ),
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


def viewable(rel: str) -> bool:
    """Whether ROOT/rel is on the allowlist of files whose contents may be shown."""
    return any(p.fullmatch(rel) for p in VIEWABLE)


def open_no_follow(rel: str) -> int:
    """A read-only descriptor for ROOT/rel, refusing a symlink at any step.

    Each component is opened relative to the last with O_NOFOLLOW, so a path
    swapped for a symlink after the allowlist check cannot redirect the read.
    """
    parts = [p for p in rel.split("/") if p]
    if not parts or any(p in (".", "..") for p in parts):
        raise PermissionError(rel)
    fd = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        return os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    finally:
        os.close(fd)


def redact_manifest(text: str) -> str:
    """A skill's plugin.json with every setup value the user entered hidden."""
    try:
        data = json.loads(text)
    except ValueError:
        return text
    for arg in (data.get("setup_args") or {}).values():
        if isinstance(arg, dict) and "value" in arg:
            arg["value"] = REDACTED
    return json.dumps(data, indent=2, ensure_ascii=False)


class ViewError(Exception):
    """A file the viewer will not show, with the status and message to answer."""

    def __init__(self, status: int, message: str) -> None:
        """Keep the HTTP status beside the message."""
        super().__init__(message)
        self.status = status


def read_allowed(rel: str) -> str:
    """The text of an allowlisted, regular, not-too-large file, or ViewError."""
    if not viewable(rel):
        raise ViewError(403, "Not viewable here: only its name and size are shown in the tree.")
    try:
        fd = open_no_follow(rel)
    except FileNotFoundError as exc:
        raise ViewError(404, "No such file.") from exc
    except OSError as exc:
        raise ViewError(403, "That path cannot be opened here.") from exc
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ViewError(403, "Not a regular file.")
        data = handle.read(MAX_VIEW_BYTES + 1)
    if len(data) > MAX_VIEW_BYTES:
        raise ViewError(413, f"Over {MAX_VIEW_BYTES // 1024} KB; not shown.")
    return data.decode("utf-8", errors="replace")


def owner(st: os.stat_result) -> str:
    """The file's owning account name, or its uid when unknown."""
    try:
        return pwd.getpwuid(st.st_uid).pw_name
    except KeyError:
        return str(st.st_uid)


WORKSPACES_SQL = (
    "select w.name, w.slug, count(c.id), max(c.createdAt) from workspaces w "
    "left join workspace_chats c on c.workspaceId = w.id group by w.id order by w.name"
)
SETTINGS_SQL = "select label, value from system_settings order by label"
EVENTS_SQL = "select event, occurredAt from event_logs order by id desc limit 30"


def shown_setting(row: tuple) -> tuple:
    """A settings row with its value hidden unless it is on the allowlist."""
    if len(row) > 1 and row[0] not in SETTING_VALUES:
        return (row[0], "(not shown)")
    return row


def open_db() -> sqlite3.Connection | None:
    """AnythingLLM's database, read-only, or None when there is none."""
    path = ROOT / "storage" / "anythingllm.db"
    if not path.exists():
        return None
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)


def rows(sql: str, params: tuple = ()) -> list[tuple]:
    """The rows for `sql` from the read-only database; [] when it is missing or differs."""
    db = open_db()
    if db is None:
        return []
    try:
        return db.execute(sql, params).fetchall()
    except sqlite3.Error:
        return []
    finally:
        db.close()


def read_json(rel: str) -> object:
    """A JSON file under ROOT, read without following links, or None."""
    try:
        fd = open_no_follow(rel)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            return None
        data = handle.read(MAX_VIEW_BYTES + 1)
    try:
        return json.loads(data) if len(data) <= MAX_VIEW_BYTES else None
    except ValueError:
        return None


def when(value: object) -> str:
    """An AnythingLLM timestamp (epoch milliseconds) as local 'YYYY-MM-DD HH:MM', or ''."""
    try:
        seconds = float(value) / 1000  # ty: ignore[invalid-argument-type]
    except (TypeError, ValueError):
        return "" if value is None else str(value)
    if seconds <= 0:
        return ""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(seconds))


def service_state(unit: str) -> str:
    """`systemctl --user is-active` for one of diot's units."""
    env = {
        "PATH": "/usr/bin:/bin",
        "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", ""),
        "DBUS_SESSION_BUS_ADDRESS": os.environ.get("DBUS_SESSION_BUS_ADDRESS", ""),
    }
    try:
        done = subprocess.run(
            ["/usr/bin/systemctl", "--user", "is-active", unit],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"unavailable: {exc}"
    return (done.stdout or done.stderr).strip()
