"""The /review monitor's data access: files, the database, settings and service state.

Every screen module reads through here, and nothing here writes anything.
Files are opened read-only one path component at a time without following
symlinks, only regular files are read, and every read is bounded; the
database is opened read-only. The agent's file folder can be read in full,
since the agent itself can; everywhere else only an allowlist of non-secret
files is. Secret settings leave this module as names only. Standard library only.
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
PREFIX = os.environ.get("REVIEW_PREFIX", "")
# The agent-built site lives on its own origin; links to it are absolute.
SITE_URL = os.environ.get("REVIEW_SITE_URL", "").rstrip("/")
AGENT_DIR = "storage/anythingllm-fs"
MAX_VIEW_BYTES = 256 * 1024
REDACTED = "<redacted>"

# Outside the agent's folder, the only files whose contents may be shown.
VIEWABLE = [
    re.compile(p)
    for p in (
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
    rf"{AGENT_DIR}/.*|storage/plugins/agent-skills/[^/]+/handler\.js\.draft"
    r"|storage/plugins/agent-flows/.*|storage/research-runs/.*"
)
# A settings-file key whose value is a credential. Its value never leaves here.
SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASS|AUTH|SALT|SIG_|JWT|PRIVATE|CREDENTIAL|COOKIE")
THINKING = {"deepseek-flash", "deepseek-v4-flash", "deepseek-v4-pro", "deepseek-reasoner"}
PROVIDERS = {"deepseek": "DeepSeek", "openai": "OpenAI", "anthropic": "Anthropic"}
HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; "
        "frame-ancestors 'none'"
    ),
    "X-Frame-Options": "DENY",
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


def in_agent_dir(rel: str) -> bool:
    """Whether ROOT/rel is inside the agent's file folder."""
    return rel.startswith(f"{AGENT_DIR}/")


def viewable(rel: str) -> bool:
    """Whether ROOT/rel's contents may be shown: anything the agent can read, or the allowlist."""
    return in_agent_dir(rel) or any(p.fullmatch(rel) for p in VIEWABLE)


def open_no_follow(rel: str) -> int:
    """A read-only descriptor for ROOT/rel, refusing a symlink at any step.

    Each component is opened relative to the last with O_NOFOLLOW, so a path
    swapped for a symlink after a check cannot redirect the read.
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


class ViewError(Exception):
    """A file the viewer will not show, with the status and message to answer."""

    def __init__(self, status: int, message: str) -> None:
        """Keep the HTTP status beside the message."""
        super().__init__(message)
        self.status = status


def read_bytes(rel: str, limit: int = MAX_VIEW_BYTES) -> tuple[bytes, os.stat_result]:
    """Up to `limit` bytes of a regular file and its stat; a FIFO or device is refused."""
    try:
        fd = open_no_follow(rel)
    except FileNotFoundError as exc:
        raise ViewError(404, "No such file.") from exc
    except OSError as exc:
        raise ViewError(403, "That path cannot be opened here.") from exc
    with os.fdopen(fd, "rb") as handle:
        st = os.fstat(handle.fileno())
        if not stat.S_ISREG(st.st_mode):
            raise ViewError(403, "Not a regular file.")
        return handle.read(limit), st


def read_allowed(rel: str) -> str:
    """The text of a viewable, regular, not-too-large file, or ViewError."""
    if not viewable(rel):
        raise ViewError(403, "Not viewable here: only its name and size are shown.")
    data, _ = read_bytes(rel, MAX_VIEW_BYTES + 1)
    if len(data) > MAX_VIEW_BYTES:
        raise ViewError(413, f"Over {MAX_VIEW_BYTES // 1024} KB; not shown.")
    return data.decode("utf-8", errors="replace")


def read_json(rel: str) -> object:
    """A JSON file under ROOT, read without following links, or None."""
    try:
        data, _ = read_bytes(rel, MAX_VIEW_BYTES + 1)
        return json.loads(data) if len(data) <= MAX_VIEW_BYTES else None
    except (ViewError, ValueError):
        return None


def redact_manifest(text: str) -> str:
    """A skill's plugin.json with every setup value the user entered hidden."""
    try:
        data = json.loads(text)
    except ValueError:
        return text
    if not isinstance(data, dict):
        return text
    for arg in (data.get("setup_args") or {}).values():
        if isinstance(arg, dict) and "value" in arg:
            arg["value"] = REDACTED
    return json.dumps(data, indent=2, ensure_ascii=False)


def env() -> dict[str, str]:
    """AnythingLLM's settings file as a dict. Callers show secret values as 'set' only."""
    try:
        data, _ = read_bytes("storage/.env", 64 * 1024)
    except ViewError:
        return {}
    found = {}
    for line in data.decode("utf-8", errors="replace").splitlines():
        name, sep, value = line.strip().partition("=")
        if sep and name and not name.startswith("#"):
            found[name.strip()] = value.strip().strip("'\"")
    return found


def is_secret(name: str) -> bool:
    """Whether a settings-file key holds a credential."""
    return bool(SECRET_NAME.search(name.upper()))


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


def setting(label: str, default: str = "") -> str:
    """One value from AnythingLLM's system settings."""
    found = rows("select value from system_settings where label = ?", (label,))
    return str(found[0][0]) if found and found[0][0] is not None else default


def setting_list(label: str) -> list[str]:
    """A JSON list stored in AnythingLLM's system settings."""
    try:
        value = json.loads(setting(label, "[]"))
    except ValueError:
        return []
    return [str(v) for v in value] if isinstance(value, list) else []


def workspaces() -> list[tuple[str, str]]:
    """(slug, name) of every workspace, oldest first."""
    return [(str(s), str(n)) for s, n in rows("select slug, name from workspaces order by id")]


def model(chat_provider: object = None, chat_model: object = None) -> tuple[str, str, bool]:
    """(provider label, model, thinking) for a workspace override, else the system's."""
    settings = env()
    provider = str(chat_provider or settings.get("LLM_PROVIDER", ""))
    pref = "OPEN_MODEL_PREF" if provider == "openai" else f"{provider.upper()}_MODEL_PREF"
    name = str(chat_model or settings.get(pref, ""))
    return PROVIDERS.get(provider, provider or "--"), name or "--", name in THINKING


def as_dict(value: object) -> dict:
    """The value when it is a dict, else {}: parsed JSON is checked before it is read."""
    return value if isinstance(value, dict) else {}


def as_list(value: object) -> list:
    """The value when it is a list, else []."""
    return value if isinstance(value, list) else []


def json_field(value: object) -> dict:
    """A JSON text column as a dict; {} when it is not one."""
    try:
        data = json.loads(value) if isinstance(value, str) else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def owner(st: os.stat_result) -> str:
    """The file's owning account name, or its uid when unknown."""
    try:
        return pwd.getpwuid(st.st_uid).pw_name
    except KeyError:
        return str(st.st_uid)


def when(value: object) -> str:
    """An AnythingLLM timestamp (epoch milliseconds, or an ISO date) as local 'YYYY-MM-DD HH:MM'."""
    try:
        seconds = float(value) / 1000  # ty: ignore[invalid-argument-type]
    except (TypeError, ValueError):
        return "" if value is None else str(value)[:16].replace("T", " ")
    if seconds <= 0:
        return ""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(seconds))


def millis(value: object) -> float:
    """An epoch-milliseconds value as a number; 0 when it is not one."""
    try:
        return float(value)  # ty: ignore[invalid-argument-type]
    except (TypeError, ValueError):
        return 0.0


def day_time(value: object) -> str:
    """An epoch-milliseconds time as 'today 06:00', 'yesterday 06:00' or 'Sep 23 06:00'."""
    ms = millis(value)
    if ms <= 0:
        return when(value)
    moment = time.localtime(ms / 1000)
    days = (time.mktime((*time.localtime()[:3], 0, 0, 0, 0, 0, -1)) - ms / 1000) / 86400
    hour = time.strftime("%H:%M", moment)
    if days <= 0:
        return f"today {hour}"
    if days <= 1:
        return f"yesterday {hour}"
    return time.strftime("%b %d %H:%M", moment).replace(" 0", " ", 1)


def size_text(size: float) -> str:
    """Bytes as B, KB, MB or GB."""
    for unit in ("B", "KB", "MB"):
        if size < 1024:  # noqa: PLR2004
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def service_state(unit: str, *, user: bool = True) -> str:
    """`systemctl is-active` for one of diot's units, or a system unit."""
    environment = {
        "PATH": "/usr/bin:/bin",
        "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", ""),
        "DBUS_SESSION_BUS_ADDRESS": os.environ.get("DBUS_SESSION_BUS_ADDRESS", ""),
    }
    scope = ["--user"] if user else []
    try:
        done = subprocess.run(
            ["/usr/bin/systemctl", *scope, "is-active", unit],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"unavailable: {exc}"
    return (done.stdout or done.stderr).strip()
